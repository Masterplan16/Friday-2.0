"""
Heartbeat Daemon - Story 4.1 Task 9.2

Point d'entrée Docker pour Heartbeat Engine en mode daemon.
Démarre le cycle HeartbeatEngine en boucle infinie avec gestion graceful shutdown.

Usage:
    python -m agents.src.core.heartbeat_daemon

Environment Variables:
    HEARTBEAT_ENABLED: true/false (default: true)
    HEARTBEAT_MODE: daemon/cron (default: daemon)
    HEARTBEAT_INTERVAL_MINUTES: Minutes entre cycles (default: 30)
    DATABASE_URL: PostgreSQL connection string
    REDIS_URL: Redis connection string
"""

import asyncio
import os
import signal
import sys
from typing import Optional

import asyncpg
import structlog
from redis.asyncio import Redis
from anthropic import AsyncAnthropic

from agents.src.core.heartbeat_engine import HeartbeatEngine
from agents.src.core.context_provider import ContextProvider
from agents.src.core.context_manager import ContextManager
from agents.src.core.check_registry import CheckRegistry
from agents.src.core.llm_decider import LLMDecider
from agents.src.core.check_executor import CheckExecutor
from agents.src.core.checks import register_all_checks

# Configuration structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging_level=getattr(__import__("logging"), os.getenv("LOG_LEVEL", "INFO"), 20)
    ),
)

logger = structlog.get_logger(__name__)


class HeartbeatDaemon:
    """
    Daemon Heartbeat Engine avec gestion graceful shutdown.
    """

    def __init__(self):
        """Initialize daemon."""
        self.enabled = os.getenv("HEARTBEAT_ENABLED", "true").lower() == "true"
        self.mode = os.getenv("HEARTBEAT_MODE", "daemon")
        self.interval_minutes = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", "30"))

        self.db_pool: Optional[asyncpg.Pool] = None
        self.redis_client: Optional[Redis] = None
        self.engine: Optional[HeartbeatEngine] = None
        self.shutdown_event = asyncio.Event()

        logger.info(
            "HeartbeatDaemon initialized",
            enabled=self.enabled,
            mode=self.mode,
            interval_minutes=self.interval_minutes
        )

    async def connect(self):
        """Connect to PostgreSQL and Redis."""
        # PostgreSQL
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")

        self.db_pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=5
        )
        logger.info("Connected to PostgreSQL")

        # Redis
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise ValueError("REDIS_URL environment variable not set")

        self.redis_client = await Redis.from_url(
            redis_url,
            decode_responses=True
        )
        logger.info("Connected to Redis")

        # Initialize stack Heartbeat
        await self._init_heartbeat_stack()

    async def _init_heartbeat_stack(self):
        """Initialize Heartbeat Engine stack."""
        # Context Manager + Provider
        context_manager = ContextManager(
            db_pool=self.db_pool,
            redis_client=self.redis_client
        )
        context_provider = ContextProvider(
            context_manager=context_manager,
            db_pool=self.db_pool
        )

        # Check Registry + register checks
        check_registry = CheckRegistry()
        register_all_checks(check_registry)
        logger.info("Registered checks", count=len(check_registry.get_all_checks()))

        # LLM Decider
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        llm_client = AsyncAnthropic(api_key=anthropic_api_key)
        llm_decider = LLMDecider(
            llm_client=llm_client,
            redis_client=self.redis_client
        )

        # Check Executor
        check_executor = CheckExecutor(
            db_pool=self.db_pool,
            redis_client=self.redis_client,
            check_registry=check_registry
        )

        # Heartbeat Engine
        self.engine = HeartbeatEngine(
            db_pool=self.db_pool,
            redis_client=self.redis_client,
            context_provider=context_provider,
            check_registry=check_registry,
            llm_decider=llm_decider,
            check_executor=check_executor
        )

        logger.info("HeartbeatEngine initialized")

    async def run(self):
        """Run daemon (mode daemon ou one-shot selon config)."""
        if not self.enabled:
            logger.warning("Heartbeat disabled (HEARTBEAT_ENABLED=false)")
            return

        if self.mode == "daemon":
            # Daemon mode : boucle infinie
            logger.info("Starting Heartbeat daemon mode", interval_minutes=self.interval_minutes)

            try:
                await self.engine.run_heartbeat_cycle(
                    mode="daemon",
                    interval_minutes=self.interval_minutes
                )
            except asyncio.CancelledError:
                logger.info("Heartbeat daemon stopped (SIGTERM received)")

        elif self.mode == "cron":
            # Cron mode : cycle unique puis exit
            logger.info("Running Heartbeat one-shot mode (cron)")
            result = await self.engine.run_heartbeat_cycle(mode="one-shot")
            logger.info("Heartbeat cycle completed", result=result)

        else:
            logger.error("Invalid HEARTBEAT_MODE", mode=self.mode)
            sys.exit(1)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down HeartbeatDaemon...")

        # Close connections
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")

        if self.db_pool:
            await self.db_pool.close()
            logger.info("PostgreSQL pool closed")

        logger.info("HeartbeatDaemon shutdown complete")

    def handle_signal(self, sig):
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        logger.info("Signal received", signal=sig.name)
        self.shutdown_event.set()


async def main():
    """Main entry point."""
    daemon = HeartbeatDaemon()

    # Setup signal handlers (not available on Windows)
    loop = asyncio.get_event_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: daemon.handle_signal(s)
            )
    except NotImplementedError:
        # Windows: loop.add_signal_handler() not supported
        logger.warning("Signal handlers not supported on this platform (Windows)")

    try:
        # Connect
        await daemon.connect()

        # Run daemon
        run_task = asyncio.create_task(daemon.run())

        # Wait for shutdown signal or task completion
        await asyncio.wait(
            [run_task, asyncio.create_task(daemon.shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel running task if still active
        if not run_task.done():
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        logger.error("HeartbeatDaemon fatal error", error=str(e), exc_info=True)
        sys.exit(1)

    finally:
        # Graceful shutdown
        await daemon.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, exiting...")
        sys.exit(0)
