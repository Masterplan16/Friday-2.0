"""
Module de classification d'emails (Story 2.2).

Utilise Claude Sonnet 4.5 pour classifier automatiquement les emails
en 8 catégories avec injection de règles de correction.

Story 7.3 Task 9.1: Injection contexte casquette actuel (bias subtil)
"""

from __future__ import annotations

import time
from json import JSONDecodeError  # L1 fix: Import specific exception
from typing import TYPE_CHECKING, Sequence, Optional

import asyncpg
import structlog

from agents.src.adapters.llm import ClaudeAdapter, get_llm_adapter  # H4 fix: Import type for hints
from agents.src.agents.email.prompts import build_classification_prompt
from agents.src.middleware.models import ActionResult, CorrectionRule
from agents.src.middleware.trust import friday_action
from agents.src.models.email_classification import EmailClassification

if TYPE_CHECKING:
    from typing import Any
    from agents.src.core.models import Casquette

logger = structlog.get_logger(__name__)

# H2 fix: Circuit breaker pour correction_rules fetch
# Tracks consecutive failures par composant
_circuit_breaker_failures: dict[str, int] = {}


class EmailClassifierError(Exception):
    """Erreur dans le processus de classification d'email."""

    pass


@friday_action(module="email", action="classify", trust_default="auto")
async def classify_email(
    email_id: str,
    email_text: str,
    db_pool: asyncpg.Pool,
    **kwargs,  # Accept decorator-injected args (_correction_rules, _rules_prompt)
) -> ActionResult:
    """
    Classifie un email en utilisant Claude Sonnet 4.5.

    Args:
        email_id: ID de l'email dans ingestion.emails
        email_text: Texte de l'email anonymisé (from + subject + body)
        db_pool: Pool de connexions PostgreSQL
        **kwargs: Decorator-injected arguments (e.g., _correction_rules)

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

        # === PHASE 1.5: Fetch current casquette context (Story 7.3 AC1) ===
        current_casquette = await _fetch_current_casquette(db_pool)
        if current_casquette:
            logger.info(
                "context_casquette_fetched",
                email_id=email_id,
                casquette=current_casquette.value,
            )

        # === PHASE 2: Build prompts ===
        system_prompt, user_prompt = build_classification_prompt(
            email_text=email_text,
            correction_rules=correction_rules,
            current_casquette=current_casquette,  # Story 7.3 AC1
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

        # Fallback: category=inconnu, confidence=0.0
        return ActionResult(
            input_summary=f"Email {email_id[:8]}...",
            output_summary="→ ERREUR: classification failed",
            confidence=0.0,
            reasoning=f"Erreur de classification: {type(e).__name__}: {str(e)}",
            payload={
                "category": "inconnu",
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
            # M1 fix: Exclure source_receipts (potentiellement volumineux) pour perf
            rows = await conn.fetch(
                """
                SELECT id, module, action_type, scope, priority,
                       conditions, output, hit_count, active
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

            # M1: source_receipts non chargé (optim perf), defaulté à []
            rules = [
                CorrectionRule(
                    id=row["id"],
                    module=row["module"],
                    action_type=row["action_type"],
                    scope=row["scope"],
                    priority=row["priority"],
                    conditions=row["conditions"],
                    output=row["output"],
                    source_receipts=[],  # M1 fix: Non chargé pour perf
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

            # H2 fix: Reset circuit breaker on success
            circuit_key = "correction_rules_fetch"
            if circuit_key in _circuit_breaker_failures:
                del _circuit_breaker_failures[circuit_key]

            return rules

    except Exception as e:
        # H2 fix: Circuit breaker - si >= 3 échecs consécutifs, raise au lieu de fallback
        circuit_key = "correction_rules_fetch"
        consecutive_failures = _circuit_breaker_failures.get(circuit_key, 0) + 1
        _circuit_breaker_failures[circuit_key] = consecutive_failures

        if consecutive_failures >= 3:
            logger.error(
                "correction_rules_fetch_circuit_breaker_open",
                consecutive_failures=consecutive_failures,
                error=str(e),
                error_type=type(e).__name__,
                message="Circuit breaker open: correction_rules fetch failed 3+ times consecutively",
            )
            raise EmailClassifierError(
                f"Circuit breaker ouvert: correction_rules fetch a échoué {consecutive_failures} fois consécutives"
            ) from e

        logger.warning(
            "correction_rules_fetch_failed",
            error=str(e),
            error_type=type(e).__name__,
            consecutive_failures=consecutive_failures,
            fallback="degraded_mode",
        )
        # Mode dégradé : continuer sans règles
        return []


async def _fetch_current_casquette(
    db_pool: asyncpg.Pool,
) -> Optional["Casquette"]:
    """
    Récupère la casquette actuelle du Mainteneur depuis core.user_context (Story 7.3 AC1).

    Args:
        db_pool: Pool de connexions PostgreSQL

    Returns:
        Casquette actuelle (médecin/enseignant/chercheur) ou None si auto-detect

    Notes:
        - Si erreur fetch → log warning + retourne None (mode dégradé)
        - Si updated_by='manual' → contexte forcé manuellement (prioritaire)
        - Si updated_by='system' → contexte auto-détecté
        - Si current_casquette IS NULL → auto-detect actif, retourne None

    Story 7.3 Task 9.1: Injection contexte casquette dans classification email
    """
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT current_casquette, updated_by
                FROM core.user_context
                WHERE id = 1
                """)

            if not row or row["current_casquette"] is None:
                # Auto-detect actif ou pas encore initialisé
                return None

            # Importer Casquette enum
            from agents.src.core.models import Casquette

            casquette_value = row["current_casquette"]

            try:
                casquette = Casquette(casquette_value)
                return casquette
            except ValueError:
                logger.warning(
                    "invalid_casquette_value",
                    casquette_value=casquette_value,
                    message="Casquette value invalide dans core.user_context",
                )
                return None

    except Exception as e:
        logger.warning(
            "context_casquette_fetch_failed",
            error=str(e),
            error_type=type(e).__name__,
            fallback="no_context_bias",
        )
        # Mode dégradé : pas de bias contextuel
        return None


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
    llm_adapter: ClaudeAdapter = get_llm_adapter(model="claude-sonnet-4-5-20250929")
    backoff_delays = [1, 2, 4]  # secondes
    start_time = time.time()  # M2 fix: Track latency

    for attempt in range(max_retries):
        try:
            logger.debug(
                "calling_claude",
                email_id=email_id,
                attempt=attempt + 1,
                max_retries=max_retries,
            )

            # Appel Claude avec anonymisation RGPD (C1 fix)
            # Combine system + user prompts dans le context pour anonymisation
            combined_context = f"{system_prompt}\n\n{user_prompt}"

            llm_response = await llm_adapter.complete_with_anonymization(
                prompt="Classifie cet email dans l'une des catégories disponibles selon les règles fournies.",
                context=combined_context,  # PII sera anonymisée automatiquement
                temperature=0.1,  # Classification déterministe
                max_tokens=300,  # Catégorie + confidence + reasoning
            )

            response = llm_response.content

            # Parse JSON response (L3 fix: Pydantic valide le JSON)
            # Strip markdown code blocks si Claude wrappe la reponse
            json_text = response.strip()
            if json_text.startswith("```"):
                # Retirer ```json\n...\n```
                lines = json_text.split("\n")
                # Retirer premiere ligne (```json) et derniere (```)
                if lines[-1].strip() == "```":
                    lines = lines[1:-1]
                elif lines[0].startswith("```"):
                    lines = lines[1:]
                json_text = "\n".join(lines).strip()
            classification = EmailClassification.model_validate_json(json_text)

            logger.info(
                "classification_success",
                email_id=email_id,
                category=classification.category,
                confidence=classification.confidence,
                keywords=classification.keywords,  # M2 fix: Add keywords for debugging
                latency_ms=round((time.time() - start_time) * 1000, 2),  # M2 fix: Add latency
                attempt=attempt + 1,
            )

            return classification

        except JSONDecodeError as e:  # L1 fix: Use imported JSONDecodeError
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
        # Verifier si email_id est un UUID valide
        # Le consumer passe parfois un IMAP UID (ex: "6118") au lieu d'un UUID DB
        # Dans ce cas, skip l'update (le consumer fait le store lui-meme)
        import uuid as uuid_mod

        try:
            uuid_mod.UUID(email_id)
        except ValueError:
            logger.debug(
                "email_update_skipped_not_uuid",
                email_id=email_id,
                message="email_id is not a valid UUID, skipping DB update (consumer handles store)",
            )
            return

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
                logger.warning(
                    "email_update_no_rows",
                    email_id=email_id,
                    category=category,
                    message="Email not found for update, may not be stored yet",
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
            # C3 fix: Incrémentation atomique avec RETURNING (évite race condition)
            row = await conn.fetchrow("""
                UPDATE core.cold_start_tracking
                SET
                    emails_processed = emails_processed + 1,
                    updated_at = NOW()
                WHERE module = 'email' AND action_type = 'classify'
                RETURNING phase, emails_processed, accuracy
                """)

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

            # H3 fix: Si >= 10 emails → calculer accuracy et décider promotion
            if phase == "cold_start":
                # Calculer accuracy depuis core.action_receipts
                accuracy_row = await conn.fetchrow("""
                    SELECT
                        COUNT(*) FILTER (WHERE status IN ('auto', 'approved', 'executed')) as correct,
                        COUNT(*) as total
                    FROM core.action_receipts
                    WHERE module = 'email' AND action_type = 'classify'
                      AND created_at >= (
                          SELECT created_at
                          FROM core.cold_start_tracking
                          WHERE module = 'email' AND action_type = 'classify'
                      )
                    """)

                if not accuracy_row or accuracy_row["total"] == 0:
                    logger.warning(
                        "cold_start_accuracy_no_data",
                        message="No action_receipts found for email.classify",
                    )
                    return

                correct = accuracy_row["correct"]
                total = accuracy_row["total"]
                accuracy = correct / total if total > 0 else 0.0

                logger.info(
                    "cold_start_accuracy_calculated",
                    emails_processed=emails_processed,
                    correct=correct,
                    total=total,
                    accuracy=round(accuracy, 3),
                )

                # Si accuracy >= 90% → promouvoir à 'calibrated'
                if accuracy >= 0.90:
                    await conn.execute(
                        """
                        UPDATE core.cold_start_tracking
                        SET phase = 'calibrated', accuracy = $1
                        WHERE module = 'email' AND action_type = 'classify'
                        """,
                        accuracy,
                    )
                    logger.info(
                        "cold_start_promoted_to_calibrated",
                        accuracy=round(accuracy, 3),
                        message="Email classifier promoted to calibrated phase (accuracy >= 90%)",
                    )
                else:
                    # Accuracy < 90% → rester en cold_start, mais update accuracy pour tracking
                    await conn.execute(
                        """
                        UPDATE core.cold_start_tracking
                        SET accuracy = $1
                        WHERE module = 'email' AND action_type = 'classify'
                        """,
                        accuracy,
                    )
                    logger.warning(
                        "cold_start_accuracy_below_threshold",
                        accuracy=round(accuracy, 3),
                        threshold=0.90,
                        message=f"Accuracy {accuracy:.1%} < 90% - staying in cold_start phase",
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
