"""
Handler Telegram pour creation evenements via message naturel

Story 7.4 AC1: Detection intention evenement dans messages texte
Story 7.4 AC2: Notification proposition evenement avec inline buttons
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from agents.src.agents.calendar.message_event_detector import (
    CONFIDENCE_THRESHOLD,
    detect_event_intention,
    extract_event_from_message,
)
from agents.src.agents.calendar.models import EventExtractionError
from bot.handlers.event_proposal_notifications import send_event_proposal_notification

logger = structlog.get_logger(__name__)

# Owner user ID (securite: seul le mainteneur peut creer des evenements)
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0"))

# Topic IDs
TOPIC_ACTIONS_ID = int(os.getenv("TOPIC_ACTIONS_ID", "0"))
TOPIC_CHAT_ID = int(os.getenv("TOPIC_CHAT_PROACTIVE_ID", "0"))
TELEGRAM_SUPERGROUP_ID = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))


async def handle_natural_event_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handler pour detection et creation d'evenements via message naturel.

    Integre dans la chaine de handlers texte (block=False).
    Retourne True si un evenement a ete detecte et traite, False sinon.

    Pipeline:
    1. Check OWNER_USER_ID (securite)
    2. Detect intention evenement (regex rapide)
    3. Extract event via Claude Sonnet 4.5
    4. Si confidence >= 0.70: Creer entite EVENT + notification inline buttons
    5. Si confidence < 0.70: Message erreur Topic Chat
    6. Si pas d'intention: Ignorer (retourne False)

    Args:
        update: Telegram Update
        context: Bot context

    Returns:
        True si evenement detecte et traite, False si message non-evenement
    """
    if not update.message or not update.message.text:
        return False

    message_text = update.message.text.strip()
    user_id = update.effective_user.id if update.effective_user else 0

    # Securite: seul le mainteneur (OWNER_USER_ID)
    if OWNER_USER_ID and user_id != OWNER_USER_ID:
        return False

    # Detection rapide intention (regex - pas d'appel LLM si pas pertinent)
    if not detect_event_intention(message_text):
        return False

    logger.info(
        "Event intention detected in message",
        extra={"user_id": user_id, "message_length": len(message_text)},
    )

    # Extraire evenement via Claude
    try:
        db_pool = context.bot_data.get("db_pool")

        result = await extract_event_from_message(
            message=message_text,
            user_id=user_id,
            db_pool=db_pool,
        )

        if not result.event_detected or result.event is None:
            # Confidence trop basse ou pas d'evenement
            if result.confidence > 0 and result.confidence < CONFIDENCE_THRESHOLD:
                # Message erreur Topic Chat
                await _send_low_confidence_message(update, context, message_text, result.confidence)
            return False

        # Evenement detecte avec confidence suffisante
        event = result.event

        # Creer entite EVENT dans PostgreSQL (status='proposed')
        event_id = None
        if db_pool:
            event_id = await _create_event_entity(db_pool, event, message_text)

        # Envoyer notification proposition avec inline buttons (AC2)
        await send_event_proposal_notification(
            bot=context.bot,
            event=event,
            event_id=event_id,
            confidence=result.confidence,
            source="Message Telegram",
            supergroup_id=TELEGRAM_SUPERGROUP_ID,
            topic_id=TOPIC_ACTIONS_ID,
        )

        logger.info(
            "Event proposal sent",
            extra={
                "user_id": user_id,
                "event_title": event.title,
                "event_id": str(event_id) if event_id else "N/A",
                "confidence": result.confidence,
            },
        )

        return True

    except EventExtractionError as e:
        logger.error(
            "Event extraction error",
            extra={"user_id": user_id, "error": str(e)},
        )
        return False
    except Exception as e:
        logger.error(
            "Unexpected error in natural event handler",
            extra={"user_id": user_id, "error": str(e), "error_type": type(e).__name__},
        )
        return False


async def _send_low_confidence_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message_text: str,
    confidence: float,
) -> None:
    """Envoie message Topic Chat si confidence trop basse."""
    try:
        if TELEGRAM_SUPERGROUP_ID and TOPIC_CHAT_ID:
            await context.bot.send_message(
                chat_id=TELEGRAM_SUPERGROUP_ID,
                message_thread_id=TOPIC_CHAT_ID,
                text=(
                    f"Je n'ai pas bien compris l'evenement.\n"
                    f"Confiance: {confidence:.0%}\n\n"
                    f"Reformulez ou utilisez /creer_event pour saisie guidee."
                ),
            )
    except Exception as e:
        logger.error(
            "Failed to send low confidence message",
            extra={"error": str(e)},
        )


async def _create_event_entity(
    db_pool,
    event,
    source_message: str,
) -> Optional[str]:
    """
    Cree entite EVENT dans knowledge.entities (status='proposed').

    Args:
        db_pool: Pool asyncpg
        event: Event Pydantic model
        source_message: Message Telegram source

    Returns:
        UUID de l'entite creee, ou None si erreur
    """
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    properties = {
        "start_datetime": event.start_datetime.isoformat() if event.start_datetime else None,
        "end_datetime": event.end_datetime.isoformat() if event.end_datetime else None,
        "location": event.location,
        "participants": event.participants,
        "event_type": event.event_type.value if event.event_type else "other",
        "casquette": event.casquette.value,
        "confidence": event.confidence,
        "status": "proposed",
        "source": "telegram_message",
        "source_message": source_message[:200],
    }

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge.entities (id, entity_type, name, properties, created_at, updated_at)
                VALUES ($1, 'EVENT', $2, $3, $4, $4)
                """,
                uuid.UUID(event_id),
                event.title,
                json.dumps(properties),
                now,
            )

        logger.info(
            "Event entity created",
            extra={"event_id": event_id, "title": event.title, "status": "proposed"},
        )
        return event_id

    except Exception as e:
        logger.error(
            "Failed to create event entity",
            extra={"error": str(e), "event_title": event.title},
        )
        return None
