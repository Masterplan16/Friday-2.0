"""
Module de filtrage sender/domain pour pipeline email (Story 2.8, A.6 nouvelle semantique).

Semantique des filtres (decision 2026-02-12) :
- vip       -> flag is_vip=True, notification immediate, analyse prioritaire
- blacklist -> skip analyse Claude, stocker metadonnees seulement (economie tokens)
- whitelist -> proceed to classify normalement (interessant, garder en memoire)
- non liste -> proceed to classify normalement

IMPORTANT : blacklist != spam. Un email blackliste peut etre une newsletter legitime.
C'est simplement "pas interessant a investir des tokens Claude".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import asyncpg
import structlog

if TYPE_CHECKING:
    from typing import Any

logger = structlog.get_logger(__name__)

# Circuit breaker pour check_sender_filter
_circuit_breaker_failures: dict[str, int] = {}
CIRCUIT_BREAKER_THRESHOLD = 3


class SenderFilterError(Exception):
    """Erreur dans le processus de filtrage sender."""

    pass


async def check_sender_filter(
    email_id: str,
    sender_email: Optional[str],
    sender_domain: Optional[str],
    db_pool: asyncpg.Pool,
) -> Optional[dict[str, Any]]:
    """
    Verifie si un sender/domain est dans les filtres (vip/whitelist/blacklist).

    Appele AVANT classify_email() dans le pipeline email.

    Workflow:
    1. Lookup sender_email exact match (prioritaire)
    2. Si pas trouve, fallback sur sender_domain
    3. Si trouve blacklist -> retourne {filter_type='blacklist', ...} (skip analyse)
    4. Si trouve vip -> retourne {filter_type='vip', is_vip=True} (analyse prioritaire)
    5. Si trouve whitelist OU pas trouve -> retourne None (proceed to classify)

    Args:
        email_id: ID de l'email
        sender_email: Email sender exact ou None
        sender_domain: Domaine sender ou None
        db_pool: Pool de connexions PostgreSQL

    Returns:
        dict si blacklist ou vip, None si whitelist ou pas de filtre (proceed to classify)

    Raises:
        ValueError: Si sender_email ET sender_domain sont tous les deux None
    """
    if sender_email is None and sender_domain is None:
        raise ValueError("Au moins sender_email ou sender_domain requis")

    component_key = "sender_filter"
    if _circuit_breaker_failures.get(component_key, 0) >= CIRCUIT_BREAKER_THRESHOLD:
        logger.warning(
            "sender_filter_circuit_breaker_open",
            email_id=email_id,
            failures=_circuit_breaker_failures[component_key],
        )
        return None

    try:
        async with db_pool.acquire() as conn:
            filter_row = None

            # PHASE 1: Lookup sender_email exact match (prioritaire)
            if sender_email is not None:
                filter_row = await conn.fetchrow(
                    """
                    SELECT id, filter_type, category, confidence
                    FROM core.sender_filters
                    WHERE sender_email = $1
                    LIMIT 1
                    """,
                    sender_email,
                )

                if filter_row:
                    logger.debug(
                        "sender_filter_email_match",
                        email_id=email_id,
                        sender_email=sender_email,
                        filter_type=filter_row["filter_type"],
                    )

            # PHASE 2: Fallback sender_domain si email pas trouve
            if filter_row is None and sender_domain is not None:
                filter_row = await conn.fetchrow(
                    """
                    SELECT id, filter_type, category, confidence
                    FROM core.sender_filters
                    WHERE sender_domain = $1
                    LIMIT 1
                    """,
                    sender_domain,
                )

                if filter_row:
                    logger.debug(
                        "sender_filter_domain_match",
                        email_id=email_id,
                        sender_domain=sender_domain,
                        filter_type=filter_row["filter_type"],
                    )

            # Pas de match -> proceed to classify
            if filter_row is None:
                logger.debug(
                    "sender_filter_no_match",
                    email_id=email_id,
                    sender_email=sender_email,
                    sender_domain=sender_domain,
                )
                _circuit_breaker_failures[component_key] = 0
                return None

            filter_type = filter_row["filter_type"]
            category = filter_row["category"]
            confidence = filter_row["confidence"]

            # Whitelist -> proceed to classify (analyser normalement)
            if filter_type == "whitelist":
                logger.debug(
                    "sender_filter_whitelist_proceed",
                    email_id=email_id,
                    sender_email=sender_email,
                )
                _circuit_breaker_failures[component_key] = 0
                return None

            # VIP -> flag + proceed to classify avec priorite
            if filter_type == "vip":
                logger.info(
                    "sender_filter_vip",
                    email_id=email_id,
                    sender_email=sender_email,
                    sender_domain=sender_domain,
                )
                _circuit_breaker_failures[component_key] = 0
                return {
                    "filter_type": "vip",
                    "is_vip": True,
                    "category": category,
                    "confidence": confidence or 0.95,
                    "tokens_saved_estimate": 0,
                }

            # Blacklist -> skip analyse (economie tokens)
            if filter_type == "blacklist":
                tokens_saved_estimate = (
                    0.006  # $0.006 economie par email (classification + entites + embeddings)
                )
                logger.info(
                    "sender_filter_blacklist",
                    email_id=email_id,
                    sender_email=sender_email,
                    sender_domain=sender_domain,
                    tokens_saved_estimate=tokens_saved_estimate,
                )
                _circuit_breaker_failures[component_key] = 0
                return {
                    "filter_type": "blacklist",
                    "category": "blacklisted",
                    "confidence": 1.0,
                    "tokens_saved_estimate": tokens_saved_estimate,
                }

            # Fallback inconnu -> proceed to classify
            _circuit_breaker_failures[component_key] = 0
            return None

    except Exception as e:
        _circuit_breaker_failures[component_key] = (
            _circuit_breaker_failures.get(component_key, 0) + 1
        )

        logger.warning(
            "sender_filter_error",
            email_id=email_id,
            sender_email=sender_email,
            sender_domain=sender_domain,
            error=str(e),
            error_type=type(e).__name__,
            failures=_circuit_breaker_failures[component_key],
        )

        return None
