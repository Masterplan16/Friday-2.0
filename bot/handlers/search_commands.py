#!/usr/bin/env python3
"""
Friday 2.0 - Telegram Search Commands (Story 3.3 - Task 5)

Commande /search pour recherche sémantique documents.

Commands:
    /search <query> - Recherche sémantique documents
    /search <query> --category=finance --after=2026-01-01 - Avec filtres

Date: 2026-02-16
Story: 3.3 - Task 5
"""

from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, CommandHandler, ContextTypes
import structlog

from agents.src.agents.archiviste.semantic_search import SemanticSearcher

logger = structlog.get_logger(__name__)


# ============================================================
# /search Command Handler
# ============================================================


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler commande /search <query> (Task 5.2).

    Format:
        /search facture plombier 2026
        /search diabète SGLT2 --category=recherche

    Args:
        update: Telegram update
        context: Callback context
    """
    # Vérifier query fournie
    if not context.args:
        await update.message.reply_text(
            "❌ *Usage:* `/search <query>`\n\n"
            "*Exemples:*\n"
            "• `/search facture plombier 2026`\n"
            "• `/search diabète inhibiteurs SGLT2`\n"
            "• `/search contrat assurance --category=perso`\n\n"
            "*Filtres disponibles:*\n"
            "• `--category=<cat>` : pro, finance, universite, recherche, perso\n"
            "• `--after=YYYY-MM-DD` : Documents après date\n"
            "• `--before=YYYY-MM-DD` : Documents avant date",
            parse_mode="Markdown",
        )
        return

    # Extraire query et filtres (Task 5.2, 7.4)
    args_text = " ".join(context.args)
    query, filters = _parse_query_and_filters(args_text)

    if not query:
        await update.message.reply_text(
            "❌ Query vide. Utilisez `/search <query>`",
            parse_mode="Markdown",
        )
        return

    # Récupérer db_pool depuis context
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text(
            "⚠️ Service indisponible (DB pool non initialisé)",
        )
        return

    try:
        # Message "Recherche en cours..."
        status_msg = await update.message.reply_text(
            f"\ud83d\udd0d Recherche en cours pour : *{query}*...",
            parse_mode="Markdown",
        )

        # Recherche sémantique (Task 5.2)
        searcher = SemanticSearcher(db_pool=db_pool)
        results = await searcher.search(
            query=query,
            top_k=5,  # Top-5 par défaut
            filters=filters,
        )

        # Supprimer message status
        await status_msg.delete()

        # Format réponse (Task 5.3)
        if not results:
            await update.message.reply_text(
                f"\ud83d\udd0d Aucun résultat trouvé pour : *{query}*",
                parse_mode="Markdown",
            )
            return

        # Construire réponse formatée avec TOUS les résultats (Task 5.3)
        response_text = f"\ud83d\udd0d *Résultats pour:* {query}\n\n"
        response_text += f"\ud83d\udcca *{len(results)} documents trouvés*\n\n"

        for i, result in enumerate(results, 1):
            score_pct = int(result.score * 100)
            response_text += (
                f"*{i}. {result.title}*\n"
                f"\ud83c\udfaf Score: {score_pct}%\n"
                f"\ud83d\udcc1 Catégorie: {result.metadata.get('category', 'inconnu')}\n"
                f"\ud83d\udcdd {result.excerpt}\n\n"
            )

        # Inline buttons pour le meilleur résultat (Task 5.4)
        top_result = results[0]
        keyboard = [
            [
                InlineKeyboardButton(
                    "\ud83d\udcc2 Ouvrir",
                    url=f"file:///{top_result.path.replace(chr(92), '/')}",
                ),
                InlineKeyboardButton(
                    "\u2139\ufe0f Détails",
                    callback_data=f"search:details:{top_result.document_id}",
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            response_text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

        logger.info(
            "Search command executed",
            user_id=update.effective_user.id,
            query=query,
            results_count=len(results),
        )

    except ValueError as e:
        # Erreur validation query/filtres (Task 5.6)
        await update.message.reply_text(
            f"❌ Erreur : {str(e)}",
        )
        logger.warning(
            "Search validation error",
            query=query,
            error=str(e),
        )

    except Exception as e:
        # Erreur technique (Task 5.6)
        await update.message.reply_text(
            "\u26a0\ufe0f Erreur lors de la recherche. Réessayez plus tard.",
        )
        logger.error(
            "Search command failed",
            query=query,
            error=str(e),
        )


# ============================================================
# Query Parsing Helpers
# ============================================================


def _parse_query_and_filters(args_text: str) -> tuple[str, dict]:
    """
    Parse query et filtres depuis args (Task 7.4).

    Format:
        "facture plombier --category=finance --after=2026-01-01"
        → query="facture plombier", filters={"category": "finance", "after": "2026-01-01"}

    Args:
        args_text: Texte complet arguments

    Returns:
        (query, filters)
    """
    parts = args_text.split("--")
    query = parts[0].strip()

    filters = {}
    if len(parts) > 1:
        for filter_part in parts[1:]:
            if "=" in filter_part:
                key, value = filter_part.split("=", 1)
                filters[key.strip()] = value.strip()

    return query, filters


# ============================================================
# Callback Query Handler (inline buttons)
# ============================================================


async def search_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler inline button "Détails" (Task 5.4).

    Affiche métadonnées complètes du document.

    Callback data: search:details:<document_id>
    """
    query = update.callback_query
    await query.answer()

    # Extract document_id
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "search":
        await query.edit_message_text("⚠️ Callback invalide")
        return

    try:
        document_id = UUID(parts[2])
    except ValueError:
        await query.edit_message_text("⚠️ ID document invalide")
        return

    # Récupérer métadonnées document
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await query.edit_message_text("⚠️ Service indisponible")
        return

    try:
        row = await db_pool.fetchrow(
            """
            SELECT
                original_filename,
                final_path,
                classification_category,
                classification_subcategory,
                classification_confidence,
                created_at
            FROM ingestion.document_metadata
            WHERE document_id = $1
            """,
            document_id,
        )

        if not row:
            await query.edit_message_text("⚠️ Document introuvable")
            return

        # Format métadonnées
        details_text = (
            f"\ud83d\udcc4 *Détails document*\n\n"
            f"*Nom:* {row['original_filename']}\n"
            f"*Chemin:* `{row['final_path']}`\n"
            f"*Catégorie:* {row['classification_category']}"
        )

        if row["classification_subcategory"]:
            details_text += f" / {row['classification_subcategory']}"

        details_text += (
            f"\n*Confidence:* {int(row['classification_confidence'] * 100)}%\n"
            f"*Créé:* {row['created_at'].strftime('%Y-%m-%d %H:%M')}"
        )

        await query.edit_message_text(
            details_text,
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(
            "Search details callback failed",
            document_id=document_id,
            error=str(e),
        )
        await query.edit_message_text("⚠️ Erreur chargement détails")


# ============================================================
# Register Handlers
# ============================================================


def register_search_handlers(application) -> None:
    """
    Enregistre handlers search dans Telegram application.

    Args:
        application: Telegram Application instance
    """
    application.add_handler(CommandHandler("search", search_command))

    # Callback query handler pour inline buttons sera ajouté dans bot/main.py
    # car il partage le dispatcher avec autres handlers

    logger.info("Search command handlers registered")
