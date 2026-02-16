"""
Gateway Heartbeat Routes - Story 4.1 Task 9.4

Endpoint pour déclencher manuellement cycle Heartbeat (mode cron).

Author: Claude Sonnet 4.5
Date: 2026-02-16
"""

import os
from typing import Dict, Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, Request, HTTPException
from redis.asyncio import Redis
from anthropic import AsyncAnthropic

from ..auth import get_current_user
from agents.src.core.heartbeat_engine import HeartbeatEngine
from agents.src.core.context_provider import ContextProvider
from agents.src.core.context_manager import ContextManager
from agents.src.core.check_registry import CheckRegistry
from agents.src.core.llm_decider import LLMDecider
from agents.src.core.check_executor import CheckExecutor
from agents.src.core.checks import register_all_checks

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/heartbeat", tags=["heartbeat"])

# Singleton HeartbeatEngine (avoid re-registration crash)
_heartbeat_engine: Optional[HeartbeatEngine] = None


# ============================================
# Helper: Initialize Heartbeat Stack
# ============================================


async def get_heartbeat_engine(db_pool: asyncpg.Pool, redis_client: Redis) -> HeartbeatEngine:
    """
    Initialize and return HeartbeatEngine singleton.

    Uses module-level cache to avoid CheckRegistry re-registration
    ValueError on repeated calls.

    Args:
        db_pool: PostgreSQL pool
        redis_client: Redis client

    Returns:
        HeartbeatEngine instance ready to run
    """
    global _heartbeat_engine
    if _heartbeat_engine is not None:
        return _heartbeat_engine

    # Context Manager + Provider
    context_manager = ContextManager(db_pool=db_pool, redis_client=redis_client)
    context_provider = ContextProvider(context_manager=context_manager, db_pool=db_pool)

    # Check Registry + register checks (singleton, safe to call once)
    check_registry = CheckRegistry()
    if not check_registry.get_all_checks():
        register_all_checks(check_registry)

    # LLM Decider
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    llm_client = AsyncAnthropic(api_key=anthropic_api_key)
    llm_decider = LLMDecider(llm_client=llm_client, redis_client=redis_client)

    # Check Executor
    check_executor = CheckExecutor(
        db_pool=db_pool, redis_client=redis_client, check_registry=check_registry
    )

    # Heartbeat Engine
    _heartbeat_engine = HeartbeatEngine(
        db_pool=db_pool,
        redis_client=redis_client,
        context_provider=context_provider,
        check_registry=check_registry,
        llm_decider=llm_decider,
        check_executor=check_executor,
    )

    return _heartbeat_engine


# ============================================
# POST /api/v1/heartbeat/trigger
# ============================================


@router.post("/trigger")
async def trigger_heartbeat_cycle(
    request: Request, current_user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Déclenche cycle Heartbeat one-shot (mode cron).

    **Authentification requise** : Bearer token dans Authorization header.

    **Usage** : Appelé par n8n workflow cron ou manuellement.

    **Returns** :
        - status: success/error/partial_success
        - checks_executed: Nombre de checks exécutés
        - checks_notified: Nombre de notifications envoyées
        - duration_ms: Durée cycle en millisecondes
        - llm_reasoning: Reasoning du LLM décideur (si applicable)

    **Story 4.1 Task 9.4** : Endpoint FastAPI Gateway pour mode cron.
    """
    # Check if Heartbeat enabled
    if os.getenv("HEARTBEAT_ENABLED", "true").lower() != "true":
        raise HTTPException(
            status_code=503, detail="Heartbeat Engine is disabled (HEARTBEAT_ENABLED=false)"
        )

    # Get dependencies from app state
    db_pool: asyncpg.Pool = request.app.state.pg_pool
    redis_client: Redis = request.app.state.redis

    if db_pool is None or redis_client is None:
        raise HTTPException(status_code=503, detail="Database or Redis connection not available")

    try:
        logger.info(
            "Heartbeat cycle triggered", triggered_by=current_user.get("username", "unknown")
        )

        # Initialize HeartbeatEngine
        engine = await get_heartbeat_engine(db_pool, redis_client)

        # Run one-shot cycle
        result = await engine.run_heartbeat_cycle(mode="one-shot")

        logger.info(
            "Heartbeat cycle completed",
            status=result["status"],
            checks_executed=result["checks_executed"],
            checks_notified=result["checks_notified"],
            duration_ms=result.get("duration_ms", 0),
        )

        return result

    except Exception as e:
        logger.error("Heartbeat cycle failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Heartbeat cycle failed: {str(e)}")


# ============================================
# GET /api/v1/heartbeat/status
# ============================================


@router.get("/status")
async def heartbeat_status(
    request: Request, current_user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Retourne statut Heartbeat Engine.

    **Authentification requise** : Bearer token dans Authorization header.

    **Returns** :
        - enabled: true/false
        - mode: daemon/cron
        - interval_minutes: Minutes entre cycles (mode daemon)
        - last_cycle_timestamp: Timestamp dernier cycle (si disponible)
        - silence_rate_7d: Taux de silence sur 7 jours (si données disponibles)
    """
    db_pool: asyncpg.Pool = request.app.state.pg_pool

    enabled = os.getenv("HEARTBEAT_ENABLED", "true").lower() == "true"
    mode = os.getenv("HEARTBEAT_MODE", "daemon")
    interval_minutes = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", "30"))

    status = {
        "enabled": enabled,
        "mode": mode,
        "interval_minutes": interval_minutes,
        "last_cycle_timestamp": None,
        "silence_rate_7d": None,
    }

    # Get last cycle timestamp from DB (if available)
    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                # Get last cycle timestamp
                last_cycle = await conn.fetchrow(
                    "SELECT cycle_timestamp FROM core.heartbeat_metrics "
                    "ORDER BY cycle_timestamp DESC LIMIT 1"
                )
                if last_cycle:
                    status["last_cycle_timestamp"] = last_cycle["cycle_timestamp"].isoformat()

                # Calculate silence_rate 7d
                silence_rate = await conn.fetchval("SELECT core.calculate_silence_rate(7)")
                if silence_rate is not None:
                    status["silence_rate_7d"] = float(silence_rate)

        except Exception as e:
            logger.warning("Failed to fetch Heartbeat metrics", error=str(e))

    return status


# ============================================================================
# GET /api/v1/heartbeat/health
# ============================================================================


@router.get("/health")
async def heartbeat_health() -> Dict[str, str]:
    """
    Healthcheck endpoint pour Heartbeat routes.

    **Public** : Pas d'authentification requise.

    **Returns** : {"status": "ok", "service": "heartbeat"}
    """
    return {"status": "ok", "service": "heartbeat"}
