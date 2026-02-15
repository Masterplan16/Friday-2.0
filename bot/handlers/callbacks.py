"""
Bot Telegram Friday 2.0 - Callback Handlers (Approve/Reject)

Story 1.10: Inline Buttons & Validation (AC1-AC5).
Gere les callbacks des boutons [Approve] et [Reject] pour actions trust=propose.
Le bouton [Correct] est gere par corrections.py (Story 1.7).

Security:
- BUG-1.10.4: Verification OWNER_USER_ID obligatoire
- BUG-1.10.2: SELECT FOR UPDATE pour eviter race conditions
- BUG-1.10.16: Rate limiting logs via compteur + TTL (H3 fix)
"""

import os
import time
import uuid as uuid_mod
from typing import Optional

import asyncpg
import structlog
from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

logger = structlog.get_logger(__name__)

# H3 fix: Rate limit avec TTL et taille max (plus de dict unbounded)
_unauthorized_attempts: dict[int, tuple[int, float]] = {}  # user_id -> (count, last_time)
_MAX_LOG_WARNINGS_PER_USER = 10
_ATTEMPTS_TTL_SECONDS = 3600  # Reset apres 1h
_MAX_TRACKED_USERS = 1000  # Limite taille dict


def _cleanup_stale_attempts() -> None:
    """Nettoie les entrees perimees du dict _unauthorized_attempts (H3 fix)."""
    now = time.monotonic()
    stale = [
        uid for uid, (_, ts) in _unauthorized_attempts.items() if now - ts > _ATTEMPTS_TTL_SECONDS
    ]
    for uid in stale:
        del _unauthorized_attempts[uid]


class CallbacksHandler:
    """Handler pour callbacks inline buttons (Approve/Reject).

    Responsable de :
    - Valider l'identite du Mainteneur (OWNER_USER_ID)
    - Verrouiller le receipt en DB (SELECT FOR UPDATE)
    - Mettre a jour le statut (approved/rejected) + validated_by
    - Executer l'action si approve (via ActionExecutor)
    - Editer le message Telegram (confirmation visuelle)
    - Notifier le topic Metrics & Logs
    """

    def __init__(self, db_pool: asyncpg.Pool, action_executor=None):
        """
        Initialise le handler de callbacks.

        Args:
            db_pool: Pool de connexions PostgreSQL
            action_executor: Instance ActionExecutor (C1 fix: execution des actions)
        """
        self.db_pool = db_pool
        self.action_executor = action_executor
        self._owner_user_id = int(os.getenv("OWNER_USER_ID", "0"))
        self._metrics_topic_id = int(os.getenv("TOPIC_METRICS_ID", "0"))
        self._supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))

    def _is_authorized(self, user_id: int) -> bool:
        """Verifie que l'utilisateur est le Mainteneur (BUG-1.10.4)."""
        return user_id == self._owner_user_id

    async def _check_authorization(self, query, user_id: int) -> bool:
        """
        Verifie autorisation et repond au callback si non autorise.

        Returns:
            True si autorise, False sinon
        """
        if self._is_authorized(user_id):
            return True

        # H3 fix: Rate limit avec TTL et nettoyage periodique
        if len(_unauthorized_attempts) > _MAX_TRACKED_USERS:
            _cleanup_stale_attempts()

        now = time.monotonic()
        prev_count, prev_time = _unauthorized_attempts.get(user_id, (0, now))

        # Reset si TTL depasse
        if now - prev_time > _ATTEMPTS_TTL_SECONDS:
            prev_count = 0

        count = prev_count + 1
        _unauthorized_attempts[user_id] = (count, now)

        if count <= _MAX_LOG_WARNINGS_PER_USER:
            logger.warning(
                "Unauthorized callback attempt",
                user_id=user_id,
                owner_user_id=self._owner_user_id,
                attempt_count=count,
            )

        await query.answer("Non autorise", show_alert=True)
        return False

    @staticmethod
    def _parse_receipt_id(callback_data: str) -> Optional[str]:
        """
        L1 fix: Parse defensif du receipt_id depuis callback_data.

        Args:
            callback_data: Format "action_receipt-uuid"

        Returns:
            receipt_id ou None si format invalide
        """
        parts = callback_data.split("_", 1)
        if len(parts) != 2 or not parts[1]:
            return None
        return parts[1]

    async def _load_and_lock_receipt(self, conn, receipt_id: str) -> dict | None:
        """Charge et verrouille un receipt par ID (BUG-1.10.2: race condition)."""
        # Conversion str→UUID pour asyncpg
        try:
            receipt_uuid = uuid_mod.UUID(receipt_id)
        except ValueError:
            return None
        return await conn.fetchrow(
            "SELECT id, status, module, action_type, input_summary, output_summary "
            "FROM core.action_receipts "
            "WHERE id = $1 FOR UPDATE",
            receipt_uuid,
        )

    async def _notify_metrics_topic(self, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        """Envoie une notification dans le topic Metrics & Logs."""
        if not self._metrics_topic_id or not self._supergroup_id:
            return
        try:
            await context.bot.send_message(
                chat_id=self._supergroup_id,
                message_thread_id=self._metrics_topic_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as notif_err:
            logger.warning(
                "Failed to send metrics notification",
                error=str(notif_err),
            )

    async def handle_approve_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handler pour bouton [Approve] (AC2).

        Workflow:
        1. Verifier autorisation owner (BUG-1.10.4)
        2. Verrouiller receipt (SELECT FOR UPDATE, BUG-1.10.2)
        3. Verifier status='pending' (double-click prevention)
        4. UPDATE status='approved' + validated_by (H4 fix)
        5. Executer l'action via ActionExecutor (C1 fix)
        6. Editer message Telegram (confirmation visuelle, AC5)
        7. Notifier topic Metrics & Logs
        """
        query = update.callback_query

        # 1. Verifier autorisation (BUG-1.10.4)
        if not await self._check_authorization(query, query.from_user.id):
            return

        await query.answer()

        # L1 fix: Parsing defensif du receipt_id
        receipt_id = self._parse_receipt_id(query.data)
        if not receipt_id:
            logger.error("Invalid callback_data format", data=query.data)
            return

        try:
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    # 2. Charger et verrouiller receipt (BUG-1.10.2)
                    row = await self._load_and_lock_receipt(conn, receipt_id)

                    if not row:
                        await query.answer("Receipt introuvable", show_alert=True)
                        return

                    # 3. Double-click prevention (AC5)
                    if row["status"] != "pending":
                        await query.answer(
                            f"Action deja traitee ({row['status']})", show_alert=True
                        )
                        return

                    # 4. UPDATE status='approved' + validated_by (H4 fix: audit trail)
                    await conn.execute(
                        "UPDATE core.action_receipts "
                        "SET status = 'approved', "
                        "    validated_by = $2, "
                        "    updated_at = NOW() "
                        "WHERE id = $1",
                        receipt_id,
                        query.from_user.id,
                    )

            # 5. C1 fix: Executer l'action via ActionExecutor
            execution_success = False
            if self.action_executor:
                try:
                    execution_success = await self.action_executor.execute(receipt_id)
                except Exception as exec_err:
                    logger.error(
                        "Action execution failed after approve",
                        receipt_id=receipt_id,
                        error=str(exec_err),
                        exc_info=True,
                    )

            # 6. Editer message Telegram (AC5: confirmation visuelle)
            original_text = query.message.text or ""
            await query.edit_message_reply_markup(reply_markup=None)

            if execution_success:
                status_text = "Approuve et execute"
            elif self.action_executor:
                status_text = "Approuve (execution echouee)"
            else:
                status_text = "Approuve"

            # Pas de parse_mode: le texte original peut contenir des
            # caracteres speciaux qui cassent le Markdown Telegram
            await query.edit_message_text(
                original_text + f"\n\n✅ {status_text}",
            )

            # 7. Notifier topic Metrics & Logs (AC2)
            await self._notify_metrics_topic(
                context,
                f"Action approuvee\n"
                f"Module: {row['module']}.{row['action_type']}\n"
                f"Receipt: `{receipt_id[:8]}...`\n"
                f"Executee: {'oui' if execution_success else 'non'}",
            )

            logger.info(
                "Action approved",
                receipt_id=receipt_id,
                module=row["module"],
                action_type=row["action_type"],
                user_id=query.from_user.id,
                executed=execution_success,
            )

        except Exception as e:
            logger.error(
                "Error handling approve callback",
                receipt_id=receipt_id,
                error=str(e),
                exc_info=True,
            )
            try:
                await query.edit_message_text(f"Erreur lors de l'approbation: {str(e)[:200]}")
            except Exception:
                pass

    async def handle_reject_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handler pour bouton [Reject] (AC3).

        Workflow:
        1. Verifier autorisation owner (BUG-1.10.4)
        2. Verrouiller receipt (SELECT FOR UPDATE, BUG-1.10.2)
        3. Verifier status='pending' (double-click prevention)
        4. UPDATE status='rejected' + validated_by (action NON executee)
        5. Editer message Telegram (confirmation visuelle, AC5)
        6. Notifier topic Metrics & Logs
        """
        query = update.callback_query

        # 1. Verifier autorisation (BUG-1.10.4)
        if not await self._check_authorization(query, query.from_user.id):
            return

        await query.answer()

        # L1 fix: Parsing defensif
        receipt_id = self._parse_receipt_id(query.data)
        if not receipt_id:
            logger.error("Invalid callback_data format", data=query.data)
            return

        try:
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    # 2. Charger et verrouiller receipt
                    row = await self._load_and_lock_receipt(conn, receipt_id)

                    if not row:
                        await query.answer("Receipt introuvable", show_alert=True)
                        return

                    # 3. Double-click prevention
                    if row["status"] != "pending":
                        await query.answer(
                            f"Action deja traitee ({row['status']})", show_alert=True
                        )
                        return

                    # 4. UPDATE status='rejected' + validated_by (H4 fix)
                    await conn.execute(
                        "UPDATE core.action_receipts "
                        "SET status = 'rejected', "
                        "    validated_by = $2, "
                        "    updated_at = NOW() "
                        "WHERE id = $1",
                        receipt_id,
                        query.from_user.id,
                    )

            # 5. Editer message Telegram (AC5)
            original_text = query.message.text or ""
            await query.edit_message_reply_markup(reply_markup=None)
            # Pas de parse_mode: le texte original peut contenir des
            # caracteres speciaux qui cassent le Markdown Telegram
            await query.edit_message_text(
                original_text + "\n\n❌ Rejete",
            )

            # 6. Notifier topic Metrics & Logs (AC3)
            await self._notify_metrics_topic(
                context,
                f"Action rejetee\n"
                f"Module: {row['module']}.{row['action_type']}\n"
                f"Receipt: `{receipt_id[:8]}...`",
            )

            logger.info(
                "Action rejected",
                receipt_id=receipt_id,
                module=row["module"],
                action_type=row["action_type"],
                user_id=query.from_user.id,
            )

        except Exception as e:
            logger.error(
                "Error handling reject callback",
                receipt_id=receipt_id,
                error=str(e),
                exc_info=True,
            )
            try:
                await query.edit_message_text(f"Erreur lors du rejet: {str(e)[:200]}")
            except Exception:
                pass


def register_callbacks_handlers(
    application, db_pool: asyncpg.Pool, action_executor=None
) -> CallbacksHandler:
    """
    Enregistre les handlers de callbacks dans l'application Telegram.

    Args:
        application: Application Telegram
        db_pool: Pool connexions PostgreSQL
        action_executor: Instance ActionExecutor (C1 fix)

    Returns:
        Instance CallbacksHandler creee
    """
    handler = CallbacksHandler(db_pool, action_executor=action_executor)

    # Handler [Approve] button
    application.add_handler(
        CallbackQueryHandler(handler.handle_approve_callback, pattern=r"^approve_[a-f0-9\-]+$")
    )

    # Handler [Reject] button
    application.add_handler(
        CallbackQueryHandler(handler.handle_reject_callback, pattern=r"^reject_[a-f0-9\-]+$")
    )

    logger.info("Callbacks handlers registered (approve/reject)")
    return handler
