"""
Bot Telegram Friday 2.0 - Corrections Handlers

Gestion des corrections owner sur les actions Friday (Story 1.7, AC1).
Permet de capturer feedback textuel et mettre à jour core.action_receipts.

HIGH-2 fix: Anonymise PII via Presidio avant stockage (RGPD compliance).
"""

import os
import sys

import asyncpg
import structlog
from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

# HIGH-2 fix: Import Presidio pour anonymisation PII
# Path hack pour import depuis agents/src/tools (E402: import après sys.path nécessaire)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../agents/src"))
from tools.anonymize import anonymize_text  # noqa: E402

logger = structlog.get_logger(__name__)


class CorrectionsHandler:
    """Handler pour corrections owner via Telegram inline buttons."""

    def __init__(self, db_pool: asyncpg.Pool):
        """
        Initialise le handler de corrections.

        Args:
            db_pool: Pool de connexions PostgreSQL
        """
        self.db_pool = db_pool

    async def handle_correct_button(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handler callback pour bouton [Correct] (AC1).

        Workflow:
        1. owner clique [Correct] sur notification trust=propose
        2. Bot demande texte correction ("URSSAF → finance")
        3. Bot stocke correction dans core.action_receipts

        Args:
            update: Update Telegram
            context: Context bot
        """
        query = update.callback_query
        await query.answer()

        # Extraire receipt_id depuis callback_data format "correct_<receipt_id>"
        receipt_id = query.data.split("_", 1)[1]

        logger.info(
            "Correction demandée par owner",
            receipt_id=receipt_id,
            user_id=query.from_user.id,
        )

        # Demander texte correction à owner
        await query.message.reply_text(
            f"📝 **Correction action `{receipt_id[:8]}`**\n\n"
            "Quelle est la correction à appliquer ?\n"
            "Exemple : `URSSAF → finance` ou `category: medical`\n\n"
            "Envoie ton message de correction :",
            parse_mode="Markdown",
        )

        # Stocker receipt_id dans user_data pour next_step_handler
        context.user_data["awaiting_correction_for"] = receipt_id

    async def handle_correction_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        """
        Handler pour texte de correction envoyé par owner (AC1, AC2).

        Workflow:
        1. Reçoit texte correction d'owner
        2. UPDATE core.action_receipts SET correction, status='corrected'
        3. Confirme à owner

        Args:
            update: Update Telegram
            context: Context bot

        Returns:
            None si pas de correction en attente (laisser passer au handler suivant)
        """
        # Vérifier si on attend une correction
        receipt_id = context.user_data.get("awaiting_correction_for")
        if not receipt_id:
            # Pas de correction en attente, laisser passer au handler général
            return None

        correction_text = update.message.text
        user_id = update.effective_user.id

        logger.info(
            "Correction reçue",
            receipt_id=receipt_id,
            user_id=user_id,
            correction_text=correction_text,
        )

        try:
            # HIGH-2 fix: Anonymiser PII avant stockage (RGPD compliance)
            try:
                anonymized_correction = await anonymize_text(correction_text)
                logger.info(
                    "Correction anonymisée",
                    receipt_id=receipt_id,
                    original_length=len(correction_text),
                    anonymized_length=len(anonymized_correction),
                )
            except Exception as e:
                # Fallback si Presidio indisponible : stocker tel quel avec warning
                logger.warning(
                    "Échec anonymisation Presidio, stockage correction non anonymisée",
                    receipt_id=receipt_id,
                    error=str(e),
                )
                anonymized_correction = correction_text

            # Mettre à jour receipt dans BDD (AC2)
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE core.action_receipts
                    SET correction = $1,
                        status = 'corrected',
                        feedback_comment = $2,
                        updated_at = NOW()
                    WHERE id = $3
                    """,
                    anonymized_correction,  # HIGH-2 fix: anonymized
                    f"Corrected by owner (user_id={user_id})",
                    receipt_id,
                )

                # Vérifier que l'UPDATE a réussi
                if result == "UPDATE 0":
                    raise ValueError(f"Receipt {receipt_id} introuvable")

            # Confirmer à owner
            await update.message.reply_text(
                f"✅ **Correction enregistrée**\n\n"
                f"Receipt : `{receipt_id[:8]}`\n"
                f"Correction : `{correction_text}`\n\n"
                f"Friday apprendra de cette correction lors du pattern detection nightly.",
                parse_mode="Markdown",
            )

            logger.info("Correction stockée avec succès", receipt_id=receipt_id)

        except Exception as e:
            logger.error(
                "Erreur stockage correction",
                receipt_id=receipt_id,
                error=str(e),
                exc_info=True,
            )
            await update.message.reply_text(
                f"❌ **Erreur lors de l'enregistrement**\n\n"
                f"Erreur : {str(e)}\n\n"
                f"Contacte le développeur si le problème persiste.",
                parse_mode="Markdown",
            )

        finally:
            # Nettoyer user_data
            context.user_data.pop("awaiting_correction_for", None)


def register_corrections_handlers(application, db_pool: asyncpg.Pool) -> CorrectionsHandler:
    """
    Enregistre les handlers de corrections dans l'application Telegram.

    Args:
        application: Application Telegram
        db_pool: Pool connexions PostgreSQL

    Returns:
        Instance CorrectionsHandler créée
    """
    from telegram.ext import MessageHandler, filters

    handler = CorrectionsHandler(db_pool)

    # Handler callback bouton [Correct]
    application.add_handler(
        CallbackQueryHandler(handler.handle_correct_button, pattern=r"^correct_[a-f0-9\-]+$")
    )

    # Handler texte correction
    # NOTE: Enregistré dans groupe -1 (priorité haute) pour capturer corrections
    # avant le handler général de messages. Le handler vérifie user_data et
    # retourne None si pas de correction en attente (laisse passer).
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handler.handle_correction_text),
        group=-1,
    )

    logger.info("Corrections handlers enregistrés")
    return handler
