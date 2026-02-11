"""
Bot Telegram Friday 2.0 - Corrections Handlers

Gestion des corrections owner sur les actions Friday (Story 1.7, AC1).
Permet de capturer feedback textuel et mettre à jour core.action_receipts.

Story 2.2 AC5: Inline buttons pour corrections email classification.

HIGH-2 fix: Anonymise PII via Presidio avant stockage (RGPD compliance).
"""

import json
import os
import re
import sys

import asyncpg
import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

# HIGH-2 fix: Import Presidio pour anonymisation PII
# Path hack pour import depuis agents/src/tools (E402: import après sys.path nécessaire)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../agents/src"))
from tools.anonymize import anonymize_text  # noqa: E402

logger = structlog.get_logger(__name__)


class CorrectionsHandler:
    """Handler pour corrections owner via Telegram inline buttons."""

    # Story 2.2 AC5: Catégories email avec emojis
    EMAIL_CATEGORIES = {
        "medical": "🏥 Medical",
        "finance": "💰 Finance",
        "faculty": "🎓 Faculty",
        "research": "🔬 Research",
        "personnel": "👤 Personnel",
        "urgent": "🚨 Urgent",
        "spam": "🗑️ Spam",
        "unknown": "❓ Unknown",
    }

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

        Story 2.2 AC5: Si email.classify → affiche inline buttons catégories.
        Sinon → demande texte libre.

        Workflow:
        1. owner clique [Correct] sur notification trust=propose
        2. Si email.classify → affiche inline buttons 8 catégories (AC5)
        3. Sinon → demande texte correction ("URSSAF → finance")
        4. Bot stocke correction dans core.action_receipts

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

        # Story 2.2 AC5: Charger receipt pour déterminer module/action
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, module, action_type, input_summary, output_summary "
                    "FROM core.action_receipts "
                    "WHERE id = $1",
                    receipt_id,
                )

            if not row:
                await query.message.reply_text(
                    f"❌ **Erreur**\n\nReceipt `{receipt_id[:8]}` introuvable.",
                    parse_mode="Markdown",
                )
                return

            # AC5: Si email.classify → inline buttons catégories
            if row["module"] == "email" and row["action_type"] == "classify":
                await self._handle_email_classification_correction(query, receipt_id, row)
            else:
                # Comportement par défaut : demander texte libre
                await query.message.reply_text(
                    f"📝 **Correction action `{receipt_id[:8]}`**\n\n"
                    "Quelle est la correction à appliquer ?\n"
                    "Exemple : `URSSAF → finance` ou `category: medical`\n\n"
                    "Envoie ton message de correction :",
                    parse_mode="Markdown",
                )
                # Stocker receipt_id dans user_data pour next_step_handler
                context.user_data["awaiting_correction_for"] = receipt_id

        except Exception as e:
            logger.error(
                "Erreur lors du chargement du receipt",
                receipt_id=receipt_id,
                error=str(e),
                exc_info=True,
            )
            await query.message.reply_text(
                f"❌ **Erreur**\n\n{str(e)[:200]}",
                parse_mode="Markdown",
            )

    async def _handle_email_classification_correction(
        self, query, receipt_id: str, row: dict
    ) -> None:
        """
        Affiche inline buttons pour correction classification email (Story 2.2 AC5).

        Args:
            query: CallbackQuery Telegram
            receipt_id: ID du receipt
            row: Données du receipt (module, action_type, output_summary)
        """
        # Construire inline keyboard avec 8 catégories (2 par ligne)
        keyboard = []
        categories = list(self.EMAIL_CATEGORIES.items())

        for i in range(0, len(categories), 2):
            row_buttons = []
            for cat_key, cat_label in categories[i:i + 2]:
                callback_data = f"correct_email_cat_{cat_key}_{receipt_id}"
                row_buttons.append(
                    InlineKeyboardButton(cat_label, callback_data=callback_data)
                )
            keyboard.append(row_buttons)

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            f"📝 **Correction classification email**\n\n"
            f"Receipt : `{receipt_id[:8]}`\n"
            f"Classification actuelle : {row['output_summary']}\n\n"
            f"**Quelle est la bonne catégorie ?**",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def handle_category_correction(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handler pour correction catégorie email sélectionnée (Story 2.2 AC5).

        Callback format: "correct_email_cat_{category}_{receipt_id}"

        Workflow:
        1. Extraire nouvelle catégorie et receipt_id depuis callback_data
        2. Charger receipt et extraire catégorie originale depuis output_summary
        3. UPDATE status='corrected', correction JSON, feedback_comment
        4. Confirmer à owner

        Args:
            update: Update Telegram
            context: Context bot
        """
        query = update.callback_query
        await query.answer()

        # Parse callback_data: "correct_email_cat_{category}_{receipt_id}"
        parts = query.data.split("_")
        if len(parts) < 5:
            logger.error("Invalid callback_data format", data=query.data)
            return

        new_category = parts[3]  # "correct_email_cat_finance_..." → "finance"
        receipt_id = "_".join(parts[4:])  # Rejoindre au cas où receipt_id contient "_"

        logger.info(
            "Correction catégorie email reçue",
            receipt_id=receipt_id,
            new_category=new_category,
            user_id=query.from_user.id,
        )

        try:
            async with self.db_pool.acquire() as conn:
                # Charger receipt pour extraire catégorie originale
                row = await conn.fetchrow(
                    "SELECT id, module, action_type, output_summary "
                    "FROM core.action_receipts "
                    "WHERE id = $1",
                    receipt_id,
                )

                if not row:
                    await query.answer("Receipt introuvable", show_alert=True)
                    return

                # Extraire catégorie originale depuis output_summary
                # Format attendu: "→ medical (0.92)" ou "→ medical (confidence=0.92)"
                original_category = self._extract_category_from_output(row["output_summary"])

                # Construire correction JSON (AC5)
                correction_data = {
                    "correct_category": new_category,
                    "original_category": original_category,
                }
                correction_json = json.dumps(correction_data)

                # UPDATE receipt (AC5)
                await conn.execute(
                    """
                    UPDATE core.action_receipts
                    SET correction = $1,
                        status = 'corrected',
                        feedback_comment = $2,
                        updated_at = NOW()
                    WHERE id = $3
                    """,
                    correction_json,
                    f"Email reclassified by owner: {original_category} → {new_category}",
                    receipt_id,
                )

            # Confirmer à owner (AC5)
            emoji = self.EMAIL_CATEGORIES.get(new_category, "")
            await query.message.edit_text(
                f"✅ **Correction enregistrée**\n\n"
                f"Receipt : `{receipt_id[:8]}`\n"
                f"Catégorie originale : {original_category}\n"
                f"Nouvelle catégorie : {emoji} {new_category}\n\n"
                f"Friday apprendra de cette correction lors du pattern detection nightly.",
                parse_mode="Markdown",
            )

            logger.info(
                "Correction catégorie stockée avec succès",
                receipt_id=receipt_id,
                original_category=original_category,
                new_category=new_category,
            )

        except Exception as e:
            logger.error(
                "Erreur stockage correction catégorie",
                receipt_id=receipt_id,
                new_category=new_category,
                error=str(e),
                exc_info=True,
            )
            await query.message.edit_text(
                f"❌ **Erreur lors de l'enregistrement**\n\n"
                f"Erreur : {str(e)[:200]}\n\n"
                f"Contacte le développeur si le problème persiste.",
                parse_mode="Markdown",
            )

    @staticmethod
    def _extract_category_from_output(output_summary: str) -> str:
        """
        Extrait la catégorie depuis output_summary.

        Formats supportés:
        - "→ medical (0.92)"
        - "→ medical (confidence=0.92)"
        - "→ medical"

        Args:
            output_summary: Output summary du receipt

        Returns:
            Nom de la catégorie (medical, finance, etc.) ou "unknown"
        """
        # Regex pour extraire catégorie après "→"
        match = re.search(r"→\s*([a-z_]+)", output_summary)
        if match:
            return match.group(1)

        # Fallback si format inattendu
        logger.warning(
            "Failed to extract category from output_summary",
            output_summary=output_summary,
        )
        return "unknown"

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

    Story 2.2 AC5: Ajout handler catégorie email.

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

    # Story 2.2 AC5: Handler sélection catégorie email
    application.add_handler(
        CallbackQueryHandler(
            handler.handle_category_correction,
            pattern=r"^correct_email_cat_[a-z_]+_[a-f0-9\-]+$",
        )
    )

    # Handler texte correction
    # NOTE: Enregistré dans groupe -1 (priorité haute) pour capturer corrections
    # avant le handler général de messages. Le handler vérifie user_data et
    # retourne None si pas de correction en attente (laisse passer).
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handler.handle_correction_text),
        group=-1,
    )

    logger.info("Corrections handlers enregistrés (text + email category)")
    return handler
