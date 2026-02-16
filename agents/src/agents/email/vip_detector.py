"""
Module de détection VIP (Story 2.3).

Lookup rapide des expéditeurs VIP via hash SHA256 sans accès PII.
Support designation manuelle (/vip add) et apprentissage futur.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import asyncpg
import structlog
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action
from agents.src.models.vip_detection import VIPSender

if TYPE_CHECKING:
    from typing import Any

logger = structlog.get_logger(__name__)


class VIPDetectorError(Exception):
    """Erreur dans le processus de détection VIP."""



def compute_email_hash(email: str) -> str:
    """
    Calcule le hash SHA256 d'un email pour lookup VIP.

    Normalisation : lowercase + strip pour éviter collisions
    dues à la casse ou espaces.

    Args:
        email: Adresse email originale (ex: "doyen@univ.fr")

    Returns:
        Hash SHA256 hexdigest (64 caractères hex)

    Examples:
        >>> compute_email_hash("Doyen@Univ.FR  ")
        "..."  # Même hash que "doyen@univ.fr"
        >>> compute_email_hash("doyen@univ.fr")
        "a1b2c3..."  # 64 caractères hex
    """
    normalized = email.lower().strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@friday_action(module="email", action="detect_vip", trust_default="auto")
async def detect_vip_sender(
    email_anon: str,
    email_hash: str,
    db_pool: asyncpg.Pool,
    **kwargs: Any,  # Absorbe _correction_rules et _rules_prompt injectés par décorateur
) -> ActionResult:
    """
    Détecte si un expéditeur est VIP via lookup hash SHA256.

    IMPORTANT: Lookup via hash uniquement (pas d'accès PII).
    Le hash DOIT être calculé depuis l'email original (avant anonymisation).

    Args:
        email_anon: Email anonymisé Presidio (ex: "[EMAIL_123]")
        email_hash: SHA256(email_original.lower().strip())
        db_pool: Pool de connexions PostgreSQL

    Returns:
        ActionResult avec:
            - confidence=1.0 si VIP trouvé (lookup binaire)
            - confidence=1.0 si non VIP (pas d'incertitude)
            - payload contient VIPSender si trouvé

    Raises:
        VIPDetectorError: Si lookup échoue
        asyncpg.PostgresError: Si erreur base de données

    Notes:
        - Trust level: auto (pas d'erreur possible, lookup simple)
        - Latence cible: <100ms (index sur email_hash)
        - Soft delete: active=TRUE dans requête
        - Retour None dans payload si non VIP
    """
    try:
        # === PHASE 1: Lookup VIP via hash ===
        vip_row = await db_pool.fetchrow(
            """
            SELECT id, email_anon, email_hash, label, priority_override,
                   designation_source, added_by, emails_received_count, active
            FROM core.vip_senders
            WHERE email_hash = $1 AND active = TRUE
            """,
            email_hash,
        )

        if vip_row:
            # VIP trouvé
            vip = VIPSender(
                id=vip_row["id"],
                email_anon=vip_row["email_anon"],
                email_hash=vip_row["email_hash"],
                label=vip_row["label"],
                priority_override=vip_row["priority_override"],
                designation_source=vip_row["designation_source"],
                added_by=vip_row["added_by"],
                emails_received_count=vip_row["emails_received_count"],
                active=vip_row["active"],
            )

            logger.info(
                "vip_detected",
                email_anon=email_anon,
                vip_id=str(vip.id),
                label=vip.label,
                designation_source=vip.designation_source,
            )

            return ActionResult(
                input_summary=f"Email de {email_anon}",
                output_summary=f"VIP detecte: {vip.label or email_anon}",
                confidence=1.0,  # Lookup binaire, pas d'incertitude
                reasoning=f"Expediteur dans table VIP (source={vip.designation_source}, "
                f"emails_received={vip.emails_received_count})",
                payload={"vip": vip.model_dump(), "is_vip": True},
            )
        else:
            # Non VIP
            logger.debug(
                "vip_not_found",
                email_anon=email_anon,
                email_hash=email_hash[:16] + "...",  # Log partiel pour debug
            )

            return ActionResult(
                input_summary=f"Email de {email_anon}",
                output_summary="Non VIP detecte",
                confidence=1.0,  # Pas d'incertitude (absence confirmée)
                reasoning="Expediteur pas dans table VIP",
                payload={"vip": None, "is_vip": False},
            )

    except asyncpg.PostgresError as e:
        logger.error(
            "vip_lookup_db_error",
            email_anon=email_anon,
            error=str(e),
        )
        raise VIPDetectorError(f"Database error during VIP lookup: {e}") from e

    except Exception as e:
        logger.error(
            "vip_lookup_unexpected_error",
            email_anon=email_anon,
            error=str(e),
        )
        raise VIPDetectorError(f"Unexpected error during VIP lookup: {e}") from e


async def update_vip_email_stats(
    vip_id: str,
    db_pool: asyncpg.Pool,
) -> None:
    """
    Met à jour les stats d'un VIP (emails_received_count, last_email_at).

    Appelé après détection VIP pour tracker activité.

    Args:
        vip_id: UUID du VIP sender
        db_pool: Pool de connexions PostgreSQL

    Notes:
        Ne raise jamais - erreurs loggées uniquement (stats non critiques)
    """
    try:
        await db_pool.execute(
            """
            UPDATE core.vip_senders
            SET emails_received_count = emails_received_count + 1,
                last_email_at = NOW()
            WHERE id = $1 AND active = TRUE
            """,
            vip_id,
        )

        logger.debug(
            "vip_stats_updated",
            vip_id=vip_id,
        )

    except Exception as e:
        # Attraper TOUTES les exceptions (asyncpg.PostgresError + autres)
        logger.error(
            "vip_stats_update_error",
            vip_id=vip_id,
            error=str(e),
        )
        # Ne pas raise - stats non critiques
        # L'email sera quand même traité
