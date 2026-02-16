"""
Handlers Callbacks Telegram - Inline Buttons Casquettes

Story 7.3: Multi-casquettes & Conflits Calendrier (AC2)

Callbacks:
- casquette:medecin → Force contexte médecin
- casquette:enseignant → Force contexte enseignant
- casquette:chercheur → Force contexte chercheur
- casquette:auto → Réactive auto-detect
"""

import os

import structlog
from agents.src.core.context_manager import ContextManager
from agents.src.core.models import CASQUETTE_EMOJI_MAPPING, CASQUETTE_LABEL_MAPPING, Casquette
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)


# ============================================================================
# Handler: Inline Buttons Casquette
# ============================================================================


async def handle_casquette_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler callbacks inline buttons casquette (AC2).

    Callback data format: "casquette:<casquette>"
    Exemples:
    - casquette:medecin
    - casquette:enseignant
    - casquette:chercheur
    - casquette:auto

    Args:
        update: Telegram Update
        context: Telegram context
    """
    query = update.callback_query
    if not query:
        return

    # H1 fix: Vérifier que l'utilisateur est le propriétaire
    owner_id = os.getenv("OWNER_USER_ID")
    if owner_id and str(query.from_user.id) != owner_id:
        return

    # Répondre immédiatement pour éviter timeout
    await query.answer()

    # Parser callback data
    callback_data = query.data
    if not callback_data or not callback_data.startswith("casquette:"):
        logger.warning("invalid_callback_data", data=callback_data)
        return

    casquette_arg = callback_data.split(":", 1)[1]  # "casquette:medecin" → "medecin"

    # Charger context_manager
    context_manager = await _get_context_manager(context)

    # Cas 1: casquette:auto → Réactive auto-detect
    if casquette_arg == "auto":
        await _handle_auto_detect(query, context_manager)
        return

    # Cas 2: casquette:<casquette> → Force contexte
    await _handle_set_casquette(query, context_manager, casquette_arg)


async def _handle_auto_detect(query, context_manager: ContextManager) -> None:
    """
    Réactive détection automatique contexte (callback button "Auto").

    Args:
        query: CallbackQuery
        context_manager: ContextManager instance
    """
    await context_manager.set_context(casquette=None, source="system")

    await query.edit_message_text(
        text="✅ **Détection automatique réactivée**\n\n"
        "Friday déterminera votre contexte selon vos événements et l'heure de la journée.\n\n"
        "_Utilisez `/casquette` pour voir le contexte actuel._",
        parse_mode="Markdown",
    )

    logger.info("casquette_button_auto", user_id=query.from_user.id)


async def _handle_set_casquette(query, context_manager: ContextManager, casquette_arg: str) -> None:
    """
    Force contexte casquette (callback button casquette spécifique).

    Args:
        query: CallbackQuery
        context_manager: ContextManager instance
        casquette_arg: 'medecin', 'enseignant', 'chercheur'
    """
    # Valider casquette
    try:
        casquette = Casquette(casquette_arg)
    except ValueError:
        await query.edit_message_text(
            text=f"❌ **Casquette invalide** : `{casquette_arg}`\n\n"
            "Casquettes disponibles: médecin, enseignant, chercheur",
            parse_mode="Markdown",
        )
        logger.warning("casquette_button_invalid", argument=casquette_arg)
        return

    # Force contexte
    await context_manager.set_context(casquette=casquette, source="manual")

    emoji = CASQUETTE_EMOJI_MAPPING[casquette]
    label = CASQUETTE_LABEL_MAPPING[casquette]

    await query.edit_message_text(
        text=f"✅ **Contexte changé** → {emoji} **{label}**\n\n"
        "Ce contexte restera actif jusqu'à ce que vous le changiez à nouveau.\n\n"
        "_Utilisez `/casquette` pour revenir au menu._",
        parse_mode="Markdown",
    )

    logger.info("casquette_button_set", user_id=query.from_user.id, casquette=casquette.value)


async def _get_context_manager(context: ContextTypes.DEFAULT_TYPE) -> ContextManager:
    """
    Récupère instance ContextManager depuis Telegram context.

    Args:
        context: Telegram context

    Returns:
        ContextManager instance
    """
    db_pool = context.bot_data.get("db_pool")
    redis_client = context.bot_data.get("redis_client")

    if not db_pool or not redis_client:
        raise RuntimeError("db_pool ou redis_client non initialisé dans bot_data")

    return ContextManager(db_pool=db_pool, redis_client=redis_client, cache_ttl=300)
