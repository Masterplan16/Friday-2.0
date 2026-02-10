"""
Bot Telegram Friday 2.0 - Message Handlers

Handlers pour messages texte libres et événements de groupe (nouveaux membres).
"""

import os
from datetime import datetime

import asyncpg
import structlog
from telegram import ChatMember, Update
from telegram.constants import MessageLimit
from telegram.ext import ChatMemberHandler, ContextTypes

logger = structlog.get_logger(__name__)


# User ID owner (pour vérification onboarding) - LAZY LOAD pour tests (CRIT-1 fix)
def get_antonio_user_id() -> int:
    """
    Récupère OWNER_USER_ID depuis envvar (lazy load pour tests).

    Returns:
        User ID owner

    Raises:
        ValueError: Si OWNER_USER_ID envvar manquante
    """
    user_id = os.getenv("OWNER_USER_ID")
    if not user_id:
        raise ValueError("OWNER_USER_ID envvar manquante - requis pour onboarding")
    return int(user_id)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler pour messages texte libres dans Chat & Proactive (AC3).

    Day 1: Echo simple pour tester réception.
    Story future: Intégration avec agent Friday pour réponses intelligentes.

    Args:
        update: Update Telegram
        context: Context bot
    """
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    message_id = update.message.message_id
    text = update.message.text or ""
    thread_id = update.message.message_thread_id
    timestamp = update.message.date

    logger.info(
        "Message texte reçu",
        user_id=user_id,
        chat_id=chat_id,
        thread_id=thread_id,
        text_length=len(text),
    )

    # CRIT-2 fix: Stocker message dans ingestion.telegram_messages
    await store_telegram_message(user_id, chat_id, thread_id, message_id, text, timestamp)

    # Echo response Day 1 (test simple - AC3)
    response_text = f"Echo: {text}"

    # BUG-1.9.9 fix: Split message si trop long
    await send_message_with_split(update, response_text)


async def send_message_with_split(update: Update, text: str, parse_mode: str = None) -> None:
    """
    Envoie un message en le splittant si nécessaire (>4096 chars).

    Args:
        update: Update Telegram
        text: Texte à envoyer
        parse_mode: Mode parsing (Markdown, HTML, None)

    BUG-1.9.9 fix: Messages longs splittés automatiquement
    """
    max_length = MessageLimit.MAX_TEXT_LENGTH  # 4096

    if len(text) <= max_length:
        await update.message.reply_text(text, parse_mode=parse_mode)
        return

    # Splitter en chunks intelligemment
    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Trouver découpe propre (ligne > espace > caractère)
        split_pos = remaining.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = remaining.rfind(" ", 0, max_length)
        if split_pos == -1:
            split_pos = max_length

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip()

    # Envoyer chunks avec numérotation
    for i, chunk in enumerate(chunks, 1):
        prefix = f"[{i}/{len(chunks)}]\n" if len(chunks) > 1 else ""
        await update.message.reply_text(prefix + chunk, parse_mode=parse_mode)

    logger.info("Message long splitté", chunks_count=len(chunks))


async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler pour nouveaux membres ajoutés au supergroup (AC6).

    Envoie message d'onboarding la première fois qu'owner rejoint.
    Implémente idempotence (BUG-1.9.14 fix).

    Args:
        update: Update Telegram
        context: Context bot
    """
    if not update.chat_member:
        return

    new_member: ChatMember = update.chat_member.new_chat_member
    user_id = new_member.user.id

    # BUG-1.9.15 fix: Vérifier que c'est owner (CRIT-1: appel lazy)
    antonio_id = get_antonio_user_id()
    if antonio_id > 0 and user_id != antonio_id:
        logger.info(
            "Nouveau membre détecté (pas owner, onboarding ignoré)",
            user_id=user_id,
            username=new_member.user.username,
        )
        return

    # Vérifier si onboarding déjà envoyé (BUG-1.9.14 fix: idempotence)
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL non configurée, impossible de vérifier onboarding")
        return

    try:
        conn = await asyncpg.connect(db_url)

        # Vérifier flag onboarding_sent
        row = await conn.fetchrow(
            "SELECT onboarding_sent FROM core.user_settings WHERE user_id = $1",
            user_id,
        )

        if row and row["onboarding_sent"]:
            logger.info(
                "Onboarding déjà envoyé, ignoré (idempotence)",
                user_id=user_id,
            )
            await conn.close()
            return

        # Envoyer message onboarding (AC6)
        onboarding_message = """👋 **Bienvenue owner !**

Je suis Friday 2.0, ton assistant IA personnel.

📂 **Ce supergroup a 5 topics spécialisés :**
1. 💬 Chat & Proactive - Notre conversation (ici)
2. 📬 Email & Communications - Notifications email
3. 🤖 Actions & Validations - Actions nécessitant ton OK
4. 🚨 System & Alerts - Santé système
5. 📊 Metrics & Logs - Stats et métriques

💡 Tape `/help` pour voir toutes les commandes.

🎚️ Tu peux muter/unmuter chaque topic selon ton contexte (Focus, Deep Work, etc.)

📚 Guide complet: `docs/telegram-user-guide.md`
"""

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=onboarding_message,
            parse_mode="Markdown",
        )

        # Marquer onboarding_sent = TRUE (idempotence)
        await conn.execute(
            """
            INSERT INTO core.user_settings (user_id, username, full_name, onboarding_sent, onboarding_sent_at)
            VALUES ($1, $2, $3, TRUE, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET onboarding_sent = TRUE, onboarding_sent_at = NOW(), updated_at = NOW()
            """,
            user_id,
            new_member.user.username,
            f"{new_member.user.first_name or ''} {new_member.user.last_name or ''}".strip(),
        )

        await conn.close()

        logger.info(
            "Onboarding envoyé avec succès",
            user_id=user_id,
            username=new_member.user.username,
        )

    except asyncpg.PostgresError as e:
        # MED-5 fix: Différencier erreurs DB vs autres
        logger.error(
            "Erreur PostgreSQL envoi onboarding",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
    except Exception as e:
        logger.error(
            "Erreur inattendue envoi onboarding",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def store_telegram_message(
    user_id: int,
    chat_id: int,
    thread_id: int | None,
    message_id: int,
    text: str | None,
    timestamp: datetime,
) -> None:
    """
    Stocke un message Telegram reçu dans ingestion.telegram_messages.

    Args:
        user_id: User ID Telegram
        chat_id: Chat ID (supergroup)
        thread_id: Thread ID du topic (None si General)
        message_id: Message ID unique
        text: Contenu texte
        timestamp: Timestamp message
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL non configurée, message non stocké")
        return

    try:
        conn = await asyncpg.connect(db_url)

        await conn.execute(
            """
            INSERT INTO ingestion.telegram_messages
            (user_id, chat_id, thread_id, message_id, text, timestamp, processed)
            VALUES ($1, $2, $3, $4, $5, $6, FALSE)
            """,
            user_id,
            chat_id,
            thread_id,
            message_id,
            text,
            timestamp,
        )

        await conn.close()

        logger.debug(
            "Message Telegram stocké",
            user_id=user_id,
            message_id=message_id,
        )

    except asyncpg.PostgresError as e:
        # MED-5 fix: Différencier erreurs DB vs autres
        logger.error(
            "Erreur PostgreSQL stockage message Telegram",
            user_id=user_id,
            message_id=message_id,
            error=str(e),
            error_type=type(e).__name__,
        )
    except Exception as e:
        logger.error(
            "Erreur inattendue stockage message Telegram",
            user_id=user_id,
            message_id=message_id,
            error=str(e),
            error_type=type(e).__name__,
        )
