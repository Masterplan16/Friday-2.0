"""
Extraction evenements depuis messages Telegram via Claude Sonnet 4.5

Story 7.4 AC1: Extraction evenement depuis message naturel Telegram
Story 7.4 AC5: Influence contexte casquette (bias subtil)
Story 7.4 AC1: Anonymisation Presidio AVANT appel Claude (RGPD)

Reutilise 80% du pattern Story 7.1 event_detector.py
Difference: Input = message Telegram court (pas email IMAP)
"""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

import structlog

if TYPE_CHECKING:
    from agents.src.core.models import Casquette

import asyncpg
from agents.src.agents.calendar.message_prompts import (
    MESSAGE_EVENT_SYSTEM_PROMPT,
    build_message_event_prompt,
    sanitize_message_text,
)
from agents.src.agents.calendar.models import Event, EventExtractionError, EventType
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action
from agents.src.tools.anonymize import anonymize_text
from anthropic import APIError, AsyncAnthropic, RateLimitError
from pydantic import BaseModel, Field, ValidationError

# ============================================================================
# CONFIGURATION
# ============================================================================

# Model LLM (Decision D17)
LLM_MODEL = "claude-sonnet-4-5-20250929"
LLM_TEMPERATURE = 0.1  # Extraction structuree
LLM_MAX_TOKENS = 1024  # Output JSON evenement unique (plus court que email multi-events)

# Retry & Circuit Breaker (NFR17)
MAX_RETRIES = 3
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_RESET_TIMEOUT = 60  # Seconds before half-open (allow retry)

# Confidence threshold (AC1 - plus bas que Story 7.1 car intent utilisateur plus clair)
CONFIDENCE_THRESHOLD = 0.70

# Patterns detection intention evenement (AC1)
EVENT_INTENT_VERBS = re.compile(
    r"\b(ajoute|ajout|crée|cree|creer|créer|planifie|planifier|réserve|reserve|reserver|"
    r"note|noter|programme|programmer|prévois|prevois|prevoir|prévoir|"
    r"mets|mettre|inscris|inscrire|fixe|fixer|cale|caler|bloque|bloquer)\b",
    re.IGNORECASE,
)

EVENT_INTENT_TIME = re.compile(
    r"\b(demain|après-demain|apres-demain|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
    r"prochain|prochaine|dans\s+\d+\s+(jours?|semaines?|mois)|"
    r"\d{1,2}[h:]\d{0,2}|\d{1,2}/\d{1,2}(/\d{2,4})?|"
    r"\d{1,2}\s+(janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|"
    r"septembre|octobre|novembre|decembre|décembre))\b",
    re.IGNORECASE,
)

EVENT_INTENT_CONTEXT = re.compile(
    r"\b(réunion|reunion|rendez-vous|rdv|consultation|cours|séminaire|seminaire|"
    r"conférence|conference|colloque|congrès|congres|examen|soutenance|garde|"
    r"formation|atelier|workshop|diner|dîner|déjeuner|dejeuner|"
    r"entretien|visite|permanence)\b",
    re.IGNORECASE,
)

# Logging
logger = structlog.get_logger(__name__)


# ============================================================================
# RESULT MODEL
# ============================================================================


class MessageEventResult(BaseModel):
    """Resultat extraction evenement depuis message Telegram."""

    event_detected: bool = Field(..., description="True si evenement detecte")
    event: Optional[Event] = Field(None, description="Evenement extrait (si detecte)")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence extraction")
    processing_time_ms: int = Field(0, ge=0, description="Temps traitement LLM ms")
    model_used: str = Field(default=LLM_MODEL, description="Model LLM utilise")
    source_message: Optional[str] = Field(None, description="Message source (tronque pour logs)")


# ============================================================================
# CIRCUIT BREAKER STATE
# ============================================================================

_circuit_breaker_failures = 0
_circuit_breaker_last_failure: float = 0.0
_circuit_breaker_lock = asyncio.Lock()


# ============================================================================
# DETECTION INTENTION (AC1)
# ============================================================================


def detect_event_intention(message: str) -> bool:
    """
    Detecte si un message Telegram contient une intention de creation d'evenement.

    Patterns detecteurs:
    - Verbes declencheurs: "ajoute", "cree", "planifie", "reserve", "note", "programme"
    - Indicateurs temporels: "demain", "lundi", dates explicites
    - Contexte evenement: "reunion", "rdv", "consultation", "cours"

    Args:
        message: Message Telegram brut

    Returns:
        True si intention evenement detectee (au moins verbe + temps OU contexte + temps)
    """
    if not message or len(message.strip()) < 5:
        return False

    has_verb = bool(EVENT_INTENT_VERBS.search(message))
    has_time = bool(EVENT_INTENT_TIME.search(message))
    has_context = bool(EVENT_INTENT_CONTEXT.search(message))

    # Intention = verbe + temps OU contexte + temps OU verbe + contexte
    return (has_verb and has_time) or (has_context and has_time) or (has_verb and has_context)


# ============================================================================
# FONCTION PRINCIPALE EXTRACTION (AC1, AC5)
# ============================================================================


async def extract_event_from_message(
    message: str,
    user_id: Optional[int] = None,
    current_date: Optional[str] = None,
    anthropic_client: Optional[AsyncAnthropic] = None,
    db_pool: Optional[asyncpg.Pool] = None,
    current_casquette: Optional["Casquette"] = None,
    context_manager: Optional[Any] = None,
) -> MessageEventResult:
    """
    Extrait un evenement depuis un message Telegram via Claude Sonnet 4.5.

    Pipeline:
    1. Fetch contexte casquette via ContextManager (AC5)
    2. Anonymisation Presidio (AC1 - RGPD)
    3. Sanitize prompt injection
    4. Appel Claude avec few-shot prompt (7 exemples)
    5. Parsing JSON response
    6. Validation Pydantic Event
    7. Deanonymisation participants

    Args:
        message: Message Telegram brut (peut contenir PII)
        user_id: ID utilisateur Telegram
        current_date: Date actuelle ISO 8601 (auto si None)
        anthropic_client: Client Anthropic (auto-cree si None)
        db_pool: Pool asyncpg pour fetch contexte casquette
        current_casquette: Casquette actuelle (si None, fetch depuis ContextManager ou DB)
        context_manager: ContextManager Story 7.3 (si fourni, priorite sur db_pool)

    Returns:
        MessageEventResult avec event extrait et confidence

    Raises:
        EventExtractionError: Si erreur extraction (retry epuise, circuit breaker)
    """
    global _circuit_breaker_failures, _circuit_breaker_last_failure

    # Verifier circuit breaker (half-open apres RESET_TIMEOUT)
    async with _circuit_breaker_lock:
        if _circuit_breaker_failures >= CIRCUIT_BREAKER_THRESHOLD:
            elapsed = time.time() - _circuit_breaker_last_failure
            if elapsed < CIRCUIT_BREAKER_RESET_TIMEOUT:
                logger.error(
                    "Circuit breaker OUVERT - %d echecs consecutifs (reset dans %ds)",
                    _circuit_breaker_failures,
                    int(CIRCUIT_BREAKER_RESET_TIMEOUT - elapsed),
                    extra={
                        "circuit_breaker_failures": _circuit_breaker_failures,
                        "seconds_until_reset": int(CIRCUIT_BREAKER_RESET_TIMEOUT - elapsed),
                    },
                )
                raise EventExtractionError(
                    f"Circuit breaker ouvert apres {_circuit_breaker_failures} echecs"
                )
            # Half-open: reset et laisser passer une tentative
            logger.info(
                "Circuit breaker HALF-OPEN - tentative apres %ds",
                int(elapsed),
                extra={"elapsed_seconds": int(elapsed)},
            )
            _circuit_breaker_failures = 0
            _circuit_breaker_last_failure = 0.0

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

    current_time = datetime.now(timezone.utc).strftime("%H:%M:%S")

    # AC5: Fetch casquette contexte via ContextManager (Story 7.3 - 5 regles priorite)
    context_source = None
    if current_casquette is None and context_manager is not None:
        try:
            user_context = await context_manager.get_current_context()
            current_casquette = user_context.casquette
            context_source = user_context.source.value if user_context.source else "unknown"
            if current_casquette:
                logger.info(
                    "Context casquette from ContextManager",
                    extra={
                        "user_id": user_id,
                        "casquette": current_casquette.value,
                        "source": context_source,
                    },
                )
        except Exception as e:
            logger.warning(
                "ContextManager failed, falling back to DB query",
                extra={"error": str(e)},
            )

    # Fallback: fetch direct depuis DB si ContextManager non disponible
    if current_casquette is None and db_pool is not None:
        current_casquette = await _fetch_current_casquette(db_pool)
        context_source = "db_fallback"
        if current_casquette:
            logger.debug(
                "Context casquette fetched via DB fallback",
                extra={"user_id": user_id, "casquette": current_casquette.value},
            )

    # AC1: Anonymisation Presidio AVANT appel Claude (RGPD)
    logger.debug(
        "Anonymisation message Telegram via Presidio",
        extra={"user_id": user_id, "text_length": len(message)},
    )

    try:
        anonymization_result = await anonymize_text(message)
        message_anonymized = anonymization_result.anonymized_text
        presidio_mapping = anonymization_result.mapping
    except Exception as e:
        logger.error(
            "Echec anonymisation Presidio message",
            extra={"user_id": user_id, "error": str(e)},
        )
        raise EventExtractionError(f"Erreur anonymisation Presidio: {e}")

    # Sanitize APRES anonymisation (protection prompt injection)
    message_sanitized = sanitize_message_text(message_anonymized)

    # Construire prompt avec few-shot examples + contexte casquette (AC5)
    prompt = build_message_event_prompt(
        message_text=message_sanitized,
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
                "Appel Claude Sonnet 4.5 message extraction (tentative %d/%d)",
                attempt,
                MAX_RETRIES,
                extra={"user_id": user_id, "model": LLM_MODEL, "attempt": attempt},
            )

            response = await anthropic_client.messages.create(
                model=LLM_MODEL,
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
                system=MESSAGE_EVENT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text

            # Reset circuit breaker
            async with _circuit_breaker_lock:
                _circuit_breaker_failures = 0
            break

        except RateLimitError as e:
            logger.warning(
                "RateLimitError Claude API message extraction (tentative %d/%d)",
                attempt,
                MAX_RETRIES,
                extra={
                    "user_id": user_id,
                    "error": str(e),
                    "retry_after": getattr(e, "retry_after", None),
                },
            )
            if attempt == MAX_RETRIES:
                async with _circuit_breaker_lock:
                    _circuit_breaker_failures += 1
                    _circuit_breaker_last_failure = time.time()
                raise EventExtractionError(f"RateLimitError apres {MAX_RETRIES} tentatives")
            await asyncio.sleep(2**attempt)

        except APIError as e:
            logger.error(
                "APIError Claude message extraction (tentative %d/%d)",
                attempt,
                MAX_RETRIES,
                extra={
                    "user_id": user_id,
                    "error": str(e),
                    "status_code": getattr(e, "status_code", None),
                },
            )
            if attempt == MAX_RETRIES:
                async with _circuit_breaker_lock:
                    _circuit_breaker_failures += 1
                    _circuit_breaker_last_failure = time.time()
                raise EventExtractionError(f"APIError Claude: {e}")
            await asyncio.sleep(2)

    processing_time_ms = int((time.time() - start_time) * 1000)

    if response_text is None:
        raise EventExtractionError("Aucune reponse Claude apres retries")

    # Parser reponse JSON
    try:
        response_json = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(
            "Erreur parsing JSON Claude message",
            extra={
                "user_id": user_id,
                "response_text": response_text[:500],
                "error": str(e),
            },
        )
        raise EventExtractionError(f"JSON invalide Claude: {e}")

    # Verifier si evenement detecte
    event_detected = response_json.get("event_detected", False)
    if not event_detected:
        return MessageEventResult(
            event_detected=False,
            event=None,
            confidence=response_json.get("confidence", 0.0),
            processing_time_ms=processing_time_ms,
            model_used=LLM_MODEL,
            source_message=message[:100],
        )

    # Verifier confidence
    confidence = response_json.get("confidence", 0.0)
    if confidence < CONFIDENCE_THRESHOLD:
        logger.debug(
            "Message event confidence <%s",
            CONFIDENCE_THRESHOLD,
            extra={
                "user_id": user_id,
                "confidence": confidence,
                "message": message[:50],
            },
        )
        return MessageEventResult(
            event_detected=False,
            event=None,
            confidence=confidence,
            processing_time_ms=processing_time_ms,
            model_used=LLM_MODEL,
            source_message=message[:100],
        )

    # Parser Event avec Pydantic
    try:
        event = Event(
            title=response_json["title"],
            start_datetime=response_json["start_datetime"],
            end_datetime=response_json.get("end_datetime"),
            location=response_json.get("location"),
            participants=response_json.get("participants", []),
            event_type=response_json.get("event_type", "other"),
            casquette=response_json["casquette"],
            confidence=confidence,
            context=message[:200],
        )
    except (ValidationError, KeyError) as e:
        logger.warning(
            "Validation Pydantic Event message echouee",
            extra={
                "user_id": user_id,
                "response_json": response_json,
                "error": str(e),
            },
        )
        return MessageEventResult(
            event_detected=False,
            event=None,
            confidence=0.0,
            processing_time_ms=processing_time_ms,
            model_used=LLM_MODEL,
            source_message=message[:100],
        )

    # Deanonymiser participants si Presidio mapping existe
    if presidio_mapping and event.participants:
        event.participants = _deanonymize_participants(event.participants, presidio_mapping)

    logger.info(
        "Message event extraction terminee",
        extra={
            "user_id": user_id,
            "event_detected": True,
            "event_title": event.title,
            "casquette_input": current_casquette.value if current_casquette else "none",
            "casquette_output": event.casquette.value,
            "context_source": context_source or "explicit",
            "confidence": confidence,
            "processing_time_ms": processing_time_ms,
        },
    )

    return MessageEventResult(
        event_detected=True,
        event=event,
        confidence=confidence,
        processing_time_ms=processing_time_ms,
        model_used=LLM_MODEL,
        source_message=message[:100],
    )


# ============================================================================
# WRAPPER @friday_action (Story 1.6 - Trust Layer)
# ============================================================================


@friday_action(module="calendar", action="create_event_from_message", trust_default="propose")
async def create_event_from_message_action(
    message: str,
    user_id: Optional[int] = None,
    current_date: Optional[str] = None,
    anthropic_client: Optional[AsyncAnthropic] = None,
    **kwargs,
) -> ActionResult:
    """
    Wrapper @friday_action pour extract_event_from_message.

    Trust level = propose (Day 1): validation Telegram requise avant creation.

    Args:
        message: Message Telegram brut
        user_id: ID utilisateur Telegram
        current_date: Date actuelle ISO 8601
        anthropic_client: Client Anthropic
        **kwargs: Args injectes par decorateur

    Returns:
        ActionResult avec event extrait et confidence
    """
    db_pool = kwargs.get("db_pool")

    result = await extract_event_from_message(
        message=message,
        user_id=user_id,
        current_date=current_date,
        anthropic_client=anthropic_client,
        db_pool=db_pool,
    )

    message_short = message[:50] if message else "N/A"

    if result.event_detected and result.event:
        event = result.event
        return ActionResult(
            input_summary=f"Message Telegram: '{message_short}'",
            output_summary=f"Evenement detecte: {event.title} ({event.casquette.value})",
            confidence=result.confidence,
            reasoning=(
                f"Extraction Claude Sonnet 4.5 - {result.processing_time_ms}ms. "
                f"Casquette: {event.casquette.value}. "
                f"Type: {event.event_type.value}"
            ),
            payload={
                "event": event.model_dump(mode="json"),
                "processing_time_ms": result.processing_time_ms,
                "model_used": result.model_used,
            },
        )
    else:
        return ActionResult(
            input_summary=f"Message Telegram: '{message_short}'",
            output_summary="Aucun evenement detecte",
            confidence=result.confidence,
            reasoning=f"Extraction Claude Sonnet 4.5 - {result.processing_time_ms}ms. Aucun evenement detecte.",
            payload={
                "event_detected": False,
                "processing_time_ms": result.processing_time_ms,
            },
        )


# ============================================================================
# HELPERS
# ============================================================================


def _deanonymize_participants(
    participants: list[str], presidio_mapping: Dict[str, str]
) -> list[str]:
    """
    Deanonymise participants via mapping Presidio.

    Args:
        participants: Liste placeholders Presidio (ex: ["PERSON_1"])
        presidio_mapping: Mapping placeholder -> vraie valeur

    Returns:
        Liste participants deanonymises
    """
    deanonymized = []
    for participant in participants:
        if participant in presidio_mapping:
            deanonymized.append(presidio_mapping[participant])
        else:
            deanonymized.append(participant)
    return deanonymized


async def _fetch_current_casquette(
    db_pool: asyncpg.Pool,
) -> Optional["Casquette"]:
    """
    Fetch casquette actuelle depuis core.user_context.

    Args:
        db_pool: Pool asyncpg

    Returns:
        Casquette actuelle ou None si non definie
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

            try:
                return Casquette(row["current_casquette"])
            except ValueError:
                logger.warning(
                    "Casquette value invalide dans user_context",
                    extra={"casquette_value": row["current_casquette"]},
                )
                return None

    except Exception as e:
        logger.warning(
            "Echec fetch contexte casquette message",
            extra={"error": str(e), "fallback": "no_context_bias"},
        )
        return None
