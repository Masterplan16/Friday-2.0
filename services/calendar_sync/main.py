"""Daemon de synchronisation Google Calendar - Point d'entrée."""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import asyncpg
import redis.asyncio as aioredis

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.src.integrations.google_calendar.auth import GoogleCalendarAuth
from agents.src.integrations.google_calendar.config import CalendarConfig
from agents.src.integrations.google_calendar.sync_manager import GoogleCalendarSync
from services.calendar_sync.worker import CalendarSyncWorker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class CalendarSyncDaemon:
    """Daemon principal de synchronisation Google Calendar."""

    def __init__(self):
        self.db_pool: asyncpg.Pool | None = None
        self.redis: aioredis.Redis | None = None
        self.worker: CalendarSyncWorker | None = None
        self.shutdown_event = asyncio.Event()

    async def setup(self):
        """Initialise les connexions DB, Redis, et le worker."""
        logger.info("Starting Calendar Sync Daemon...")

        # 1. Load configuration
        config_path = os.getenv(
            "CALENDAR_CONFIG_PATH", "config/calendar_config.yaml"
        )
        if not Path(config_path).exists():
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}\n"
                "Set CALENDAR_CONFIG_PATH environment variable or place config at default path."
            )

        calendar_config = CalendarConfig.from_yaml(config_path)
        logger.info(
            f"Configuration loaded: {len(calendar_config.google_calendar.calendars)} calendars"
        )

        # 2. Initialize PostgreSQL connection pool
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")

        self.db_pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=2,
            max_size=5,
            command_timeout=60,
        )
        logger.info("PostgreSQL connection pool created")

        # 3. Initialize Redis connection
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        # Test connection
        await self.redis.ping()
        logger.info("Redis connection established")

        # 4. Initialize Google Calendar auth manager
        credentials_path = os.getenv(
            "GOOGLE_CALENDAR_TOKEN_PATH", "config/google_token.json"
        )
        encrypted_credentials_path = os.getenv(
            "GOOGLE_CALENDAR_TOKEN_ENC_PATH", "config/google_token.json.enc"
        )
        client_secret_path = os.getenv(
            "GOOGLE_CLIENT_SECRET_PATH", "config/google_client_secret.json"
        )

        auth_manager = GoogleCalendarAuth(
            credentials_path=credentials_path,
            encrypted_credentials_path=encrypted_credentials_path,
            client_secret_path=client_secret_path,
        )

        # 5. Initialize Google Calendar sync manager
        sync_manager = GoogleCalendarSync(
            config=calendar_config,
            db_pool=self.db_pool,
            auth_manager=auth_manager,
        )

        # 6. Initialize worker
        self.worker = CalendarSyncWorker(
            sync_manager=sync_manager,
            redis_client=self.redis,
            config=calendar_config.model_dump(),  # Convert Pydantic model to dict
        )

        logger.info("Calendar Sync Worker initialized successfully")

    async def run(self):
        """Lance le daemon et attend le signal d'arrêt."""
        await self.setup()

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        try:
            # Run worker
            await self.worker.run()
        except asyncio.CancelledError:
            logger.info("Worker cancelled, shutting down...")
        except Exception as e:
            logger.error(f"Unexpected error in worker: {e}", exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def shutdown(self):
        """Déclenche l'arrêt gracieux."""
        logger.info("Shutdown signal received")
        self.shutdown_event.set()

    async def cleanup(self):
        """Ferme proprement toutes les connexions."""
        logger.info("Cleaning up resources...")

        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")

        if self.db_pool:
            await self.db_pool.close()
            logger.info("PostgreSQL connection pool closed")

        logger.info("Calendar Sync Daemon stopped")


def main():
    """Point d'entrée du daemon."""
    daemon = CalendarSyncDaemon()

    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, exiting...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
