"""
Detection evenements depuis emails via Claude Sonnet 4.5

Story 7.1 AC1: Extraction evenements avec anonymisation Presidio
Story 7.1 AC4: Conversion dates relatives → absolues
Story 7.1 AC5: Classification multi-casquettes
Story 7.1 AC7: Few-shot learning (5 exemples)
Story 7.3 Task 9.2: Injection contexte casquette actuel (bias subtil)
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

import structlog

if TYPE_CHECKING:
    from agents.src.core.models import Casquette

import asyncpg
from agents.src.agents.calendar.models import Event, EventDetectionResult, EventExtractionError
from agents.src.agents.calendar.prompts import (
    EVENT_DETECTION_SYSTEM_PROMPT,
    build_event_detection_prompt,
    sanitize_email_text,
)
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action
from agents.src.tools.anonymize import anonymize_text
from anthropic import APIError, AsyncAnthropic, RateLimitError
from pydantic import ValidationError

# ============================================================================
# CONFIGURATION
# ============================================================================

# Model LLM (Decision D17)
LLM_MODEL = "claude-sonnet-4-5-20250929"
LLM_TEMPERATURE = 0.1  # Extraction structuree, peu de creativite
LLM_MAX_TOKENS = 2048  # Output JSON evenements

# Retry & Circuit Breaker (NFR17)
MAX_RETRIES = 3
CIRCUIT_BREAKER_THRESHOLD = 3  # Echecs consecutifs avant alerte

# Confidence threshold (AC1)
CONFIDENCE_THRESHOLD = 0.75

# Logging
logger = structlog.get_logger(__name__)


# ============================================================================
# CIRCUIT BREAKER STATE
# ============================================================================

_circuit_breaker_failures = 0
_circuit_breaker_lock = asyncio.Lock()


# ============================================================================
# FONCTION PRINCIPALE EXTRACTION (AC1, AC4, AC5, AC7)
# ============================================================================


async def extract_events_from_email(
    email_text: str,
    email_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    current_date: Optional[str] = None,
    anthropic_client: Optional[AsyncAnthropic] = None,
    db_pool: Optional[asyncpg.Pool] = None,
    current_casquette: Optional["Casquette"] = None,
) -> EventDetectionResult:
    """
    Extrait evenements depuis email via Claude Sonnet 4.5

    Pipeline:
    1. Anonymisation Presidio (AC1 - RGPD)
    2. Appel Claude avec few-shot prompt (AC7)
    3. Parsing JSON response
    4. Validation Pydantic
    5. Deanonymisation participants
    6. Conversion dates relatives (AC4)

    Args:
        email_text: Texte email brut (peut contenir PII)
        email_id: UUID email source (ingestion.emails_raw.id)
        metadata: Metadata email (sender, subject, date)
        current_date: Date actuelle ISO 8601 (ex: "2026-02-10", auto si None)
        anthropic_client: Client Anthropic (auto-cree si None)
        db_pool: Pool asyncpg pour fetch contexte casquette (Story 7.3 AC1)
        current_casquette: Casquette actuelle (si None, fetch depuis DB si db_pool fourni)

    Returns:
        EventDetectionResult avec events_detected[] et confidence_overall

    Raises:
        EventExtractionError: Si erreur extraction (retry epuise, circuit breaker)
        EventValidationError: Si erreur validation Pydantic

    Story 7.1 AC1: Anonymisation AVANT appel Claude (CRITIQUE RGPD)
    Story 7.1 AC4: Dates relatives converties en absolues
    Story 7.1 AC5: Classification multi-casquettes (medecin|enseignant|chercheur)
    Story 7.1 AC7: Few-shot learning 5 exemples
    """
    global _circuit_breaker_failures

    # Verifier circuit breaker (thread-safe)
    async with _circuit_breaker_lock:
        if _circuit_breaker_failures >= CIRCUIT_BREAKER_THRESHOLD:
            logger.error(
                "Circuit breaker OUVERT - %d echecs consecutifs",
                _circuit_breaker_failures,
                extra={"circuit_breaker_failures": _circuit_breaker_failures},
            )
            raise EventExtractionError(
                f"Circuit breaker ouvert apres {_circuit_breaker_failures} echecs"
            )

    # Initialiser client Anthropic si non fourni
    if anthropic_client is None:
        import os

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EventExtractionError("ANTHROPIC_API_KEY manquante")
        anthropic_client = AsyncAnthropic(api_key=api_key)

    # Date actuelle par defaut
    if current_date is None:
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Heure actuelle
    current_time = datetime.now(timezone.utc).strftime("%H:%M:%S")

    # === PHASE 1.5: Fetch current casquette context (Story 7.3 AC1) ===
    if current_casquette is None and db_pool is not None:
        current_casquette = await _fetch_current_casquette(db_pool)
        if current_casquette:
            logger.debug(
                "Context casquette fetched",
                extra={"email_id": email_id, "casquette": current_casquette.value},
            )

    # AC1: Anonymisation Presidio AVANT sanitize (NER sur texte brut)
    logger.debug(
        "Anonymisation email via Presidio",
        extra={"email_id": email_id, "text_length": len(email_text)},
    )

    try:
        anonymization_result = await anonymize_text(email_text)
        email_anonymized = anonymization_result.anonymized_text
        presidio_mapping = anonymization_result.mapping
    except Exception as e:
        logger.error("Echec anonymisation Presidio", extra={"email_id": email_id, "error": str(e)})
        raise EventExtractionError(f"Erreur anonymisation Presidio: {e}")

    # Sanitize APRES anonymisation (protection prompt injection)
    email_sanitized = sanitize_email_text(email_anonymized)

    # Construire prompt avec few-shot examples (AC7) + context hint (Story 7.3)
    prompt = build_event_detection_prompt(
        email_text=email_sanitized,
        current_date=current_date,
        current_time=current_time,
        timezone="Europe/Paris",
        current_casquette=current_casquette,
    )

    # Appeler Claude avec retry (NFR17)
    start_time = time.time()
    response_text = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(
                "Appel Claude Sonnet 4.5 (tentative %d/%d)",
                attempt,
                MAX_RETRIES,
                extra={"email_id": email_id, "model": LLM_MODEL, "attempt": attempt},
            )

            response = await anthropic_client.messages.create(
                model=LLM_MODEL,
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
                system=EVENT_DETECTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extraire texte reponse
            response_text = response.content[0].text

            # H15 fix: Reset circuit breaker sous lock
            async with _circuit_breaker_lock:
                _circuit_breaker_failures = 0
            break

        except RateLimitError as e:
            logger.warning(
                "RateLimitError Claude API (tentative %d/%d)",
                attempt,
                MAX_RETRIES,
                extra={
                    "email_id": email_id,
                    "error": str(e),
                    "retry_after": getattr(e, "retry_after", None),
                },
            )

            if attempt == MAX_RETRIES:
                async with _circuit_breaker_lock:
                    _circuit_breaker_failures += 1
                raise EventExtractionError(f"RateLimitError apres {MAX_RETRIES} tentatives")

            # Backoff exponentiel
            wait_time = 2**attempt
            await _async_sleep(wait_time)

        except APIError as e:
            logger.error(
                "APIError Claude (tentative %d/%d)",
                attempt,
                MAX_RETRIES,
                extra={
                    "email_id": email_id,
                    "error": str(e),
                    "status_code": getattr(e, "status_code", None),
                },
            )

            if attempt == MAX_RETRIES:
                async with _circuit_breaker_lock:
                    _circuit_breaker_failures += 1
                raise EventExtractionError(f"APIError Claude: {e}")

            await _async_sleep(2)

    processing_time_ms = int((time.time() - start_time) * 1000)

    # Parser reponse JSON
    if response_text is None:
        raise EventExtractionError("Aucune reponse Claude apres retries")

    try:
        response_json = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(
            "Erreur parsing JSON Claude",
            extra={"email_id": email_id, "response_text": response_text[:500], "error": str(e)},
        )
        raise EventExtractionError(f"JSON invalide Claude: {e}")

    # Valider structure JSON
    if "events_detected" not in response_json:
        raise EventExtractionError("JSON Claude manque champ 'events_detected'")

    if "confidence_overall" not in response_json:
        raise EventExtractionError("JSON Claude manque champ 'confidence_overall'")

    # Parser events avec Pydantic
    events_parsed = []

    for event_data in response_json["events_detected"]:
        try:
            # Valider Event avec Pydantic
            event = Event(**event_data)

            # Filtrer events confidence < threshold (AC1)
            if event.confidence < CONFIDENCE_THRESHOLD:
                logger.debug(
                    "Event confidence <%s ignore",
                    CONFIDENCE_THRESHOLD,
                    extra={
                        "email_id": email_id,
                        "event_title": event.title,
                        "confidence": event.confidence,
                    },
                )
                continue

            # Deanonymiser participants si Presidio mapping existe
            if presidio_mapping and event.participants:
                event.participants = await _deanonymize_participants(
                    event.participants, presidio_mapping
                )

            events_parsed.append(event)

        except ValidationError as e:
            logger.warning(
                "Validation Pydantic Event echouee",
                extra={"email_id": email_id, "event_data": event_data, "error": str(e)},
            )
            # Continuer avec autres events (ne pas fail tout)
            continue

    # Calculer confidence_overall (min de tous events.confidence)
    if events_parsed:
        confidence_overall = min(event.confidence for event in events_parsed)
    else:
        confidence_overall = 0.0

    # Construire EventDetectionResult
    result = EventDetectionResult(
        events_detected=events_parsed,
        confidence_overall=confidence_overall,
        email_id=email_id,
        processing_time_ms=processing_time_ms,
        model_used=LLM_MODEL,
    )

    logger.info(
        "Detection evenements terminee - %d events detectes",
        len(events_parsed),
        extra={
            "email_id": email_id,
            "events_count": len(events_parsed),
            "confidence_overall": confidence_overall,
            "processing_time_ms": processing_time_ms,
        },
    )

    return result


# ============================================================================
# WRAPPER @friday_action (Story 1.6 - Trust Layer)
# ============================================================================


@friday_action(module="calendar", action="detect_event", trust_default="propose")
async def detect_events_action(
    email_text: str,
    email_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    current_date: Optional[str] = None,
    anthropic_client: Optional[AsyncAnthropic] = None,
    **kwargs,
) -> ActionResult:
    """
    Wrapper @friday_action pour extract_events_from_email

    Trust level = propose (Day 1) : validation Telegram requise
    Retourne ActionResult standardise pour le Trust Layer

    Args:
        email_text: Texte email brut
        email_id: UUID email source
        metadata: Metadata email (sender, subject, date)
        current_date: Date actuelle ISO 8601
        anthropic_client: Client Anthropic
        **kwargs: Args injectes par decorateur (correction_rules, db_pool, etc.)

    Returns:
        ActionResult avec confidence et reasoning
    """
    # Extraire db_pool depuis kwargs (injecte par decorateur si disponible)
    db_pool = kwargs.get("db_pool")

    result = await extract_events_from_email(
        email_text=email_text,
        email_id=email_id,
        metadata=metadata,
        current_date=current_date,
        anthropic_client=anthropic_client,
        db_pool=db_pool,
    )

    subject = ""
    if metadata:
        subject = metadata.get("subject", "")[:50]

    email_short = (email_id or "unknown")[:8]

    events_summary = "; ".join(
        f"{e.title} ({e.casquette.value})" for e in result.events_detected[:3]
    )
    if len(result.events_detected) > 3:
        events_summary += f" ... +{len(result.events_detected) - 3}"

    return ActionResult(
        input_summary=f"Email {email_short}: {subject}",
        output_summary=(
            f"{len(result.events_detected)} evenement(s) detecte(s): {events_summary}"
            if result.events_detected
            else "Aucun evenement detecte"
        ),
        confidence=result.confidence_overall,
        reasoning=f"Detection via Claude Sonnet 4.5 - {result.processing_time_ms}ms - {len(result.events_detected)} events",
        payload={
            "events_detected": [e.model_dump() for e in result.events_detected],
            "processing_time_ms": result.processing_time_ms,
            "model_used": result.model_used,
        },
    )


# ============================================================================
# HELPERS
# ============================================================================


async def _deanonymize_participants(
    participants: list[str], presidio_mapping: Dict[str, str]
) -> list[str]:
    """
    Deanonymise participants via mapping Presidio

    Args:
        participants: Liste placeholders Presidio (ex: ["PERSON_1", "PERSON_2"])
        presidio_mapping: Mapping placeholder -> vraie valeur

    Returns:
        Liste participants deanonymises
    """
    deanonymized = []

    for participant in participants:
        # Si participant est un placeholder Presidio (ex: PERSON_1)
        if participant in presidio_mapping:
            deanonymized.append(presidio_mapping[participant])
        else:
            # Garder tel quel si pas un placeholder
            deanonymized.append(participant)

    return deanonymized


async def _fetch_current_casquette(
    db_pool: asyncpg.Pool,
) -> Optional["Casquette"]:
    """
    Fetch casquette actuelle depuis core.user_context

    Args:
        db_pool: Pool asyncpg

    Returns:
        Casquette actuelle ou None si non definie

    Story 7.3 AC1: Contexte influence detection evenements
    """
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT current_casquette, updated_by
                FROM core.user_context
                WHERE id = 1
                """
            )

            if not row or row["current_casquette"] is None:
                return None

            from agents.src.core.models import Casquette

            casquette_value = row["current_casquette"]

            try:
                casquette = Casquette(casquette_value)
                return casquette
            except ValueError:
                logger.warning(
                    "Casquette value invalide dans user_context",
                    extra={"casquette_value": casquette_value},
                )
                return None

    except Exception as e:
        logger.warning(
            "Echec fetch contexte casquette", extra={"error": str(e), "fallback": "no_context_bias"}
        )
        return None


async def _async_sleep(seconds: float):
    """
    Helper async sleep (asyncio.sleep)
    """
    await asyncio.sleep(seconds)
