#!/usr/bin/env python3
"""
Friday 2.0 - API Usage Tracking (Story 6.2 Task 6 - Stub minimal)

Compteur tokens Voyage AI + Claude pour budget monitoring.

IMPORTANT: Implémentation minimale pour Story 6.2.

Date: 2026-02-11
Story: 6.2 - Task 6 (stub)
"""

import logging
from datetime import datetime
from typing import Literal

logger = logging.getLogger(__name__)


async def track_api_usage(
    provider: Literal["voyage", "claude"],
    service: Literal["embeddings", "llm"],
    tokens_in: int,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
):
    """
    Enregistre usage API dans core.api_usage.

    Args:
        provider: "voyage" ou "claude"
        service: "embeddings" ou "llm"
        tokens_in: Tokens input
        tokens_out: Tokens output (0 pour embeddings)
        cost_usd: Coût USD calculé

    TODO (Story 6.2 complet):
        - INSERT dans core.api_usage
        - Calcul auto cost selon pricing
        - Alerte si >budget mensuel
    """
    logger.info(
        "API usage: provider=%s service=%s tokens_in=%d tokens_out=%d cost=$%.4f",
        provider,
        service,
        tokens_in,
        tokens_out,
        cost_usd,
    )

    # Stub minimal : log seulement (pas encore DB)
    # TODO: INSERT INTO core.api_usage ...
