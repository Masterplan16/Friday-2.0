"""
Module d'extraction de tâches depuis emails via Claude Sonnet 4.5 (Story 2.7)

AC1 : Détection automatique tâches implicites
AC6 : Extraction dates relatives → absolues
AC7 : Priorisation automatique depuis mots-clés
"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import structlog
from agents.src.agents.email.models import TaskExtractionResult
from agents.src.agents.email.prompts import TASK_EXTRACTION_PROMPT
from agents.src.tools.anonymize import anonymize_text
from anthropic import APIError, AsyncAnthropic, RateLimitError

logger = structlog.get_logger(__name__)

# C3 fix: Validation ANTHROPIC_API_KEY au démarrage (fail-fast)
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not _ANTHROPIC_API_KEY:
    raise ValueError(
        "ANTHROPIC_API_KEY environment variable is required for task extraction. "
        "Set it in .env or environment before starting the service."
    )

# Client Anthropic global
anthropic_client = AsyncAnthropic(api_key=_ANTHROPIC_API_KEY)


async def extract_tasks_from_email(
    email_text: str,
    email_metadata: Dict[str, Any],
    current_date: Optional[str] = None,
) -> TaskExtractionResult:
    """
    Extraire tâches implicites depuis email via Claude Sonnet 4.5

    Args:
        email_text: Texte brut de l'email (corps + métadonnées)
        email_metadata: Métadonnées email (email_id, sender, subject, category, etc.)
        current_date: Date actuelle ISO 8601 (YYYY-MM-DD), défaut = aujourd'hui

    Returns:
        TaskExtractionResult avec liste des tâches détectées + confidence globale

    Raises:
        ValueError: Si email_text vide
        Exception: Si appel Claude échoue après retries

    Notes:
        - AC1 : Détecte tâches explicites, implicites, rappels
        - AC6 : Convertit dates relatives → absolues
        - AC7 : Extrait priorité depuis mots-clés
        - RGPD : Anonymise via Presidio AVANT appel Claude
        - Model : claude-sonnet-4-5-20250929, temperature=0.1
    """
    # Validation input
    if not email_text or not email_text.strip():
        raise ValueError("email_text cannot be empty")

    # =========================================================================
    # ÉTAPE 1 : ANONYMISATION PRESIDIO (CRITIQUE RGPD)
    # =========================================================================

    anonymization_result = await anonymize_text(email_text, language="fr")
    anonymized_text = anonymization_result.anonymized_text

    logger.debug(
        "email_text_anonymized",
        email_id=email_metadata.get("email_id"),
        original_length=len(email_text),
        anonymized_length=len(anonymized_text),
    )

    # =========================================================================
    # ÉTAPE 2 : PRÉPARATION CONTEXTE TEMPOREL
    # =========================================================================

    if current_date is None:
        current_date = datetime.now().strftime("%Y-%m-%d")

    current_day = datetime.strptime(current_date, "%Y-%m-%d").strftime("%A")

    # Calculer exemples de dates pour le prompt
    current_dt = datetime.strptime(current_date, "%Y-%m-%d")
    example_tomorrow = (current_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    example_in_3_days = (current_dt + timedelta(days=3)).strftime("%Y-%m-%d")

    # Trouver prochain jeudi
    days_until_thursday = (3 - current_dt.weekday()) % 7
    if days_until_thursday == 0:
        days_until_thursday = 7  # Jeudi prochain, pas aujourd'hui
    example_next_thursday = (current_dt + timedelta(days=days_until_thursday)).strftime("%Y-%m-%d")

    # Trouver prochain vendredi
    days_until_friday = (4 - current_dt.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    example_before_friday = (current_dt + timedelta(days=days_until_friday)).strftime("%Y-%m-%d")

    # Trouver lundi de la semaine prochaine
    days_until_next_monday = (7 - current_dt.weekday()) % 7
    if days_until_next_monday == 0:
        days_until_next_monday = 7
    example_next_week = (current_dt + timedelta(days=days_until_next_monday)).strftime("%Y-%m-%d")

    # =========================================================================
    # ÉTAPE 3 : CONSTRUCTION PROMPT AVEC CONTEXTE
    # =========================================================================

    # Injecter contexte temporel dans le prompt
    prompt = TASK_EXTRACTION_PROMPT.format(
        current_date=current_date,
        current_day=current_day,
        example_tomorrow=example_tomorrow,
        example_next_thursday=example_next_thursday,
        example_in_3_days=example_in_3_days,
        example_before_friday=example_before_friday,
        example_next_week=example_next_week,
    )

    # M3 fix: Anonymiser metadata pour éviter prompt injection
    sender_safe = email_metadata.get("sender", "UNKNOWN")
    subject_safe = email_metadata.get("subject", "N/A")

    # Anonymiser sender et subject (peuvent contenir PII ou instructions malveillantes)
    try:
        sender_result = await anonymize_text(sender_safe, language="fr")
        sender_anon = sender_result.anonymized_text

        subject_result = await anonymize_text(subject_safe, language="fr")
        subject_anon = subject_result.anonymized_text
    except Exception:
        # Fallback: utiliser valeurs brutes si anonymisation échoue
        sender_anon = sender_safe
        subject_anon = subject_safe

    # Ajouter métadonnées email au prompt (anonymisées)
    user_prompt = f"""
**Contexte email** :
- De : {sender_anon}
- Sujet : {subject_anon}
- Catégorie : {email_metadata.get('category', 'N/A')}

**Email texte (anonymisé)** :
{anonymized_text}

Extraire toutes les tâches mentionnées (explicites ou implicites).
Convertir dates relatives en dates absolues ISO 8601.
Retourner JSON structuré avec confidence par tâche.
"""

    # =========================================================================
    # ÉTAPE 4 : APPEL CLAUDE SONNET 4.5 (H4 fix: retry avec backoff)
    # =========================================================================

    # H4 fix: NFR17 Anthropic resilience - Retry 3x avec backoff exponentiel
    max_retries = 3
    backoff_base = 2  # secondes

    for attempt in range(1, max_retries + 1):
        try:
            response = await anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,  # Tâches courtes attendues
                temperature=0.1,  # Déterministe
                system=prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Extraire texte réponse
            response_text = response.content[0].text.strip()

            logger.debug(
                "claude_task_extraction_response",
                email_id=email_metadata.get("email_id"),
                response_length=len(response_text),
                attempt=attempt,
            )

            break  # Succès, sortir de la boucle retry

        except (APIError, RateLimitError, TimeoutError) as e:
            logger.warning(
                "claude_task_extraction_retry",
                email_id=email_metadata.get("email_id"),
                attempt=attempt,
                max_retries=max_retries,
                error=str(e),
                error_type=type(e).__name__,
            )

            if attempt < max_retries:
                # Backoff exponentiel : 2^1=2s, 2^2=4s, 2^3=8s
                backoff = backoff_base**attempt
                await asyncio.sleep(backoff)
            else:
                # Dernier essai échoué, re-raise
                logger.error(
                    "claude_task_extraction_failed_after_retries",
                    email_id=email_metadata.get("email_id"),
                    error=str(e),
                    exc_info=False,  # M1 fix: Pas exc_info pour éviter leak API key
                )
                raise

        except Exception as e:
            # Autres erreurs (pas de retry)
            logger.error(
                "claude_task_extraction_failed",
                email_id=email_metadata.get("email_id"),
                error=str(e),
                exc_info=False,  # M1 fix: Pas exc_info pour éviter leak API key
            )
            raise

    # =========================================================================
    # ÉTAPE 5 : PARSING JSON + VALIDATION PYDANTIC
    # =========================================================================

    try:
        # Strip markdown code fences si Claude enveloppe en ```json...```
        cleaned = response_text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        if not cleaned:
            logger.warning(
                "claude_task_extraction_empty_response",
                email_id=email_metadata.get("email_id"),
            )
            return TaskExtractionResult(tasks_detected=[], confidence_overall=0.0)

        # Parser JSON response
        result_json = json.loads(cleaned)

        # Convertir dates string → datetime (H2 fix: error handling)
        if "tasks_detected" in result_json:
            for task in result_json["tasks_detected"]:
                if task.get("due_date"):
                    try:
                        # Convertir string ISO 8601 → datetime
                        task["due_date"] = datetime.fromisoformat(task["due_date"])
                    except (ValueError, TypeError) as e:
                        logger.warning(
                            "invalid_due_date_format",
                            email_id=email_metadata.get("email_id"),
                            due_date_raw=task.get("due_date"),
                            error=str(e),
                        )
                        # Fallback: date None (tâche sans échéance)
                        task["due_date"] = None

        # Valider avec Pydantic
        result = TaskExtractionResult(**result_json)

        logger.info(
            "tasks_extracted_from_email",
            email_id=email_metadata.get("email_id"),
            tasks_count=len(result.tasks_detected),
            confidence_overall=result.confidence_overall,
        )

        return result

    except json.JSONDecodeError as e:
        logger.error(
            "claude_task_extraction_invalid_json",
            email_id=email_metadata.get("email_id"),
            response_text=response_text[:500],  # Tronquer pour logs
            error=str(e),
        )
        # Fallback : retourner résultat vide avec confidence faible
        return TaskExtractionResult(tasks_detected=[], confidence_overall=0.0)

    except Exception as e:
        logger.error(
            "task_extraction_validation_failed",
            email_id=email_metadata.get("email_id"),
            error=str(e),
            exc_info=True,
        )
        # Fallback
        return TaskExtractionResult(tasks_detected=[], confidence_overall=0.0)
