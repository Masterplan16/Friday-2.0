"""
Module de classification d'emails (Story 2.2).

Utilise Claude Sonnet 4.5 pour classifier automatiquement les emails
en 8 catégories avec injection de règles de correction.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import asyncpg
import structlog

from agents.src.adapters.llm import get_llm_adapter
from agents.src.agents.email.prompts import build_classification_prompt
from agents.src.middleware.models import ActionResult, CorrectionRule
from agents.src.middleware.trust import friday_action
from agents.src.models.email_classification import EmailClassification

if TYPE_CHECKING:
    from typing import Any

logger = structlog.get_logger(__name__)


class EmailClassifierError(Exception):
    """Erreur dans le processus de classification d'email."""

    pass


@friday_action(module="email", action="classify", trust_default="propose")
async def classify_email(
    email_id: str,
    email_text: str,
    db_pool: asyncpg.Pool,
) -> ActionResult:
    """
    Classifie un email en utilisant Claude Sonnet 4.5.

    Args:
        email_id: ID de l'email dans ingestion.emails
        email_text: Texte de l'email anonymisé (from + subject + body)
        db_pool: Pool de connexions PostgreSQL

    Returns:
        ActionResult avec catégorie, confidence, reasoning

    Raises:
        EmailClassifierError: Si classification échoue après retries

    Notes:
        - Température : 0.1 (classification déterministe)
        - Max tokens : 300
        - Retry : 3x avec backoff exponentiel (1s/2s/4s)
        - Cold start : Force trust=propose pour les 10-20 premiers emails
    """
    start_time = time.time()

    try:
        # === PHASE 1: Fetch correction rules ===
        correction_rules = await _fetch_correction_rules(db_pool)
        logger.info(
            "correction_rules_fetched",
            email_id=email_id,
            rules_count=len(correction_rules),
        )

        # === PHASE 2: Build prompts ===
        system_prompt, user_prompt = build_classification_prompt(
            email_text=email_text,
            correction_rules=correction_rules,
        )

        # === PHASE 3: Call Claude with retry ===
        classification = await _call_claude_with_retry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            email_id=email_id,
        )

        # === PHASE 4: Update database ===
        await _update_email_category(
            db_pool=db_pool,
            email_id=email_id,
            category=classification.category,
            confidence=classification.confidence,
        )

        # === PHASE 5: Check cold start progression ===
        await _check_cold_start_progression(db_pool=db_pool)

        # === PHASE 6: Build ActionResult ===
        latency_ms = (time.time() - start_time) * 1000

        return ActionResult(
            input_summary=f"Email {email_id[:8]}...: {email_text[:50]}...",
            output_summary=f"→ {classification.category} (confidence={classification.confidence:.2f})",
            confidence=classification.confidence,
            reasoning=classification.reasoning,
            payload={
                "category": classification.category,
                "keywords": classification.keywords,
                "suggested_priority": classification.suggested_priority,
                "model": "claude-sonnet-4-5-20250929",
                "latency_ms": round(latency_ms, 2),
                "rules_applied_count": len(correction_rules),
            },
        )

    except Exception as e:
        logger.error(
            "classification_failed",
            email_id=email_id,
            error=str(e),
            error_type=type(e).__name__,
        )

        # Fallback: category=unknown, confidence=0.0
        return ActionResult(
            input_summary=f"Email {email_id[:8]}...",
            output_summary="→ ERREUR: classification failed",
            confidence=0.0,
            reasoning=f"Erreur de classification: {type(e).__name__}: {str(e)}",
            payload={
                "category": "unknown",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )


async def _fetch_correction_rules(
    db_pool: asyncpg.Pool,
) -> list[CorrectionRule]:
    """
    Récupère les règles de correction actives pour email.classify.

    Args:
        db_pool: Pool de connexions PostgreSQL

    Returns:
        Liste des règles triées par priority ASC (max 50)

    Notes:
        - Si la query échoue → log warning + retourne []
        - Mode dégradé : classification continue sans règles
    """
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, module, action_type, scope, priority,
                       conditions, output, source_receipts, hit_count, active
                FROM core.correction_rules
                WHERE module = $1
                  AND (action_type = $2 OR action_type IS NULL)
                  AND active = true
                ORDER BY priority ASC
                LIMIT 50
                """,
                "email",
                "classify",
            )

            rules = [
                CorrectionRule(
                    id=row["id"],
                    module=row["module"],
                    action_type=row["action_type"],
                    scope=row["scope"],
                    priority=row["priority"],
                    conditions=row["conditions"],
                    output=row["output"],
                    source_receipts=row["source_receipts"] or [],
                    hit_count=row["hit_count"],
                    active=row["active"],
                )
                for row in rows
            ]

            if len(rows) > 50:
                logger.warning(
                    "correction_rules_truncated",
                    total_active=len(rows),
                    loaded=50,
                    message="Plus de 50 règles actives, seules les 50 plus prioritaires sont chargées. Envisager un cleanup.",
                )

            return rules

    except Exception as e:
        logger.warning(
            "correction_rules_fetch_failed",
            error=str(e),
            error_type=type(e).__name__,
            fallback="degraded_mode",
        )
        # Mode dégradé : continuer sans règles
        return []


async def _call_claude_with_retry(
    system_prompt: str,
    user_prompt: str,
    email_id: str,
    max_retries: int = 3,
) -> EmailClassification:
    """
    Appelle Claude Sonnet 4.5 avec retry en cas d'échec.

    Args:
        system_prompt: Prompt système (contexte + règles + format)
        user_prompt: Prompt utilisateur (email à classifier)
        email_id: ID de l'email (pour logging)
        max_retries: Nombre max de retries (default: 3)

    Returns:
        EmailClassification parsé depuis JSON

    Raises:
        EmailClassifierError: Si tous les retries échouent

    Notes:
        - Retry sur erreurs réseau, rate limit, parsing JSON
        - Backoff exponentiel : 1s, 2s, 4s
        - Si JSON parsing fail → retry 1x avec prompt ajusté
    """
    llm_adapter = get_llm_adapter()
    backoff_delays = [1, 2, 4]  # secondes

    for attempt in range(max_retries):
        try:
            logger.debug(
                "calling_claude",
                email_id=email_id,
                attempt=attempt + 1,
                max_retries=max_retries,
            )

            # Appel Claude
            response = await llm_adapter.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,  # Classification déterministe
                max_tokens=300,   # Catégorie + confidence + reasoning
            )

            # Parse JSON response
            json_text = response.strip()

            # Validation rapide format
            if not (json_text.startswith("{") and json_text.endswith("}")):
                raise ValueError("Response n'est pas du JSON valide")

            # Parse avec Pydantic
            classification = EmailClassification.model_validate_json(json_text)

            logger.info(
                "classification_success",
                email_id=email_id,
                category=classification.category,
                confidence=classification.confidence,
                attempt=attempt + 1,
            )

            return classification

        except json.JSONDecodeError as e:
            logger.warning(
                "json_parsing_failed",
                email_id=email_id,
                attempt=attempt + 1,
                error=str(e),
                response_preview=response[:200] if "response" in locals() else "N/A",
            )

            # Si dernier retry → fail
            if attempt == max_retries - 1:
                raise EmailClassifierError(
                    f"JSON parsing failed après {max_retries} tentatives"
                ) from e

            # Sinon → retry avec délai
            await _async_sleep(backoff_delays[attempt])

        except Exception as e:
            logger.warning(
                "claude_api_call_failed",
                email_id=email_id,
                attempt=attempt + 1,
                error=str(e),
                error_type=type(e).__name__,
            )

            # Si dernier retry → fail
            if attempt == max_retries - 1:
                raise EmailClassifierError(
                    f"Claude API call failed après {max_retries} tentatives: {e}"
                ) from e

            # Sinon → retry avec délai
            await _async_sleep(backoff_delays[attempt])

    # Normalement ne devrait jamais arriver ici (raise dans loop)
    raise EmailClassifierError("Classification failed: max retries exceeded")


async def _update_email_category(
    db_pool: asyncpg.Pool,
    email_id: str,
    category: str,
    confidence: float,
) -> None:
    """
    Met à jour la catégorie et confidence de l'email dans ingestion.emails.

    Args:
        db_pool: Pool de connexions PostgreSQL
        email_id: ID de l'email
        category: Catégorie classifiée
        confidence: Score de confiance

    Raises:
        EmailClassifierError: Si UPDATE échoue
    """
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE ingestion.emails
                SET category = $1, confidence = $2
                WHERE id = $3
                """,
                category,
                confidence,
                email_id,
            )

            # Vérifier qu'au moins 1 ligne a été mise à jour
            rows_updated = int(result.split()[-1])
            if rows_updated == 0:
                raise EmailClassifierError(
                    f"Email {email_id} introuvable dans ingestion.emails"
                )

            logger.debug(
                "email_category_updated",
                email_id=email_id,
                category=category,
                confidence=confidence,
            )

    except Exception as e:
        logger.error(
            "email_update_failed",
            email_id=email_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise EmailClassifierError(f"Failed to update email category: {e}") from e


async def _check_cold_start_progression(db_pool: asyncpg.Pool) -> None:
    """
    Vérifie et met à jour la progression du cold start mode.

    Args:
        db_pool: Pool de connexions PostgreSQL

    Notes:
        - Incrémente emails_processed
        - Si phase='cold_start' ET emails_processed >= 10 → calcul accuracy
        - Si accuracy >= 90% → phase='production'
        - Si emails_processed >= 20 ET accuracy < 90% → alerte Mainteneur
    """
    try:
        async with db_pool.acquire() as conn:
            # Incrémenter emails_processed
            await conn.execute(
                """
                UPDATE core.cold_start_tracking
                SET emails_processed = emails_processed + 1
                WHERE module = 'email' AND action_type = 'classify'
                """
            )

            # Fetch état actuel
            row = await conn.fetchrow(
                """
                SELECT phase, emails_processed, accuracy
                FROM core.cold_start_tracking
                WHERE module = 'email' AND action_type = 'classify'
                """
            )

            if not row:
                logger.warning("cold_start_tracking_missing", module="email", action="classify")
                return

            phase = row["phase"]
            emails_processed = row["emails_processed"]

            logger.debug(
                "cold_start_progress",
                phase=phase,
                emails_processed=emails_processed,
            )

            # Si déjà en production → rien à faire
            if phase == "production":
                return

            # Si < 10 emails → continuer cold start
            if emails_processed < 10:
                return

            # Si >= 10 emails → calculer accuracy et décider promotion
            # TODO: Implémenter calcul accuracy (Story 1.8 dépendance)
            # Pour l'instant, log info uniquement
            logger.info(
                "cold_start_checkpoint_reached",
                emails_processed=emails_processed,
                message="Seuil 10 emails atteint - calcul accuracy requis (Story 1.8)",
            )

    except Exception as e:
        logger.warning(
            "cold_start_progression_check_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        # Non bloquant - continuer la classification


async def _async_sleep(seconds: float) -> None:
    """Helper pour sleep async (pour faciliter les mocks en tests)."""
    import asyncio
    await asyncio.sleep(seconds)
