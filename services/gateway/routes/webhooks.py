"""
Gateway Webhooks Routes - Story 2.1 Task 2
Endpoints webhook pour services internes.

D25 (2026-02-13): Route EmailEngine retirée.
    L'IMAP fetcher publie directement dans Redis Streams,
    plus besoin de webhook HTTP. Garder ce fichier pour le
    healthcheck et d'eventuels futurs webhooks (n8n, etc.).

Author: Claude Sonnet 4.5
Date: 2026-02-11 (D25 refactor: 2026-02-13)
"""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


# ============================================
# [RETIRÉ D25] Route EmailEngine webhook
# L'IMAP fetcher (imap_fetcher.py) publie directement
# dans Redis Streams "email.received". Plus besoin de
# webhook HTTP depuis EmailEngine.
# ============================================


@router.get("/health")
async def webhooks_health():
    """Healthcheck endpoint pour webhooks"""
    return {"status": "ok", "service": "webhooks"}
