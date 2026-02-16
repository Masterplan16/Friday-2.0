"""
Bot Telegram Friday 2.0 - Main Entry Point

Point d'entrée principal du bot :
- Connexion au bot Telegram
- Heartbeat toutes les 60s
- Gestion reconnexion automatique
- Graceful shutdown
"""

import asyncio
import os
import signal
import sys
import time

import asyncpg
import structlog
from bot.config import ConfigurationError, load_bot_config, validate_bot_permissions
from bot.handlers import (
    arborescence_commands,
    backup_commands,
    batch_commands,
    casquette_commands,
    commands,
    conflict_commands,
    dedup_commands,
    draft_commands,
    email_status_commands,
    messages,
    pipeline_control,
    recovery_commands,
    sender_filter_commands,
    trust_budget_commands,
    trust_commands,
    vip_commands,
    warranty_commands,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

logger = structlog.get_logger(__name__)


class FridayBot:
    """Bot Telegram Friday 2.0 avec heartbeat et reconnexion automatique."""

    def __init__(self):
        self.config = None
        self.application: Application | None = None
        self.db_pool: asyncpg.Pool | None = None
        self.redis_client = None
        self.is_running = False
        self.heartbeat_task = None
        self.email_monitoring_task = None
        self.last_heartbeat_success = time.time()
        self.last_email_health_status = None

    async def init(self) -> None:
        """
        Initialise le bot (charge config, teste connexion).

        Raises:
            ConfigurationError: Si configuration invalide
            Exception: Si connexion initiale échoue après retries
        """
        # Charger configuration avec validation (BUG-1.9.6 fix)
        logger.info("Chargement configuration bot...")
        self.config = load_bot_config()

        # Tentatives de connexion avec retry (BUG-1.9.2 fix)
        max_retries = 3
        backoff_base = 2  # secondes

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    "Tentative connexion bot Telegram", attempt=attempt, max_retries=max_retries
                )

                # Construire application avec token (BUG-1.9.1 fix: validation token)
                self.application = ApplicationBuilder().token(self.config.token).build()

                # Tester connexion en récupérant info bot
                bot_info = await self.application.bot.get_me()
                logger.info(
                    "Connexion bot réussie", bot_username=bot_info.username, bot_id=bot_info.id
                )

                # Valider permissions admin (BUG-1.9.7 fix + CRIT-3 fix: async)
                await validate_bot_permissions(self.application.bot, self.config.supergroup_id)

                # Créer pool PostgreSQL (H1 fix: DB pool pour /vip commands)
                database_url = os.getenv("DATABASE_URL")
                if database_url:
                    try:
                        self.db_pool = await asyncpg.create_pool(
                            database_url,
                            min_size=2,
                            max_size=10,
                        )
                        logger.info("PostgreSQL pool créé", min_size=2, max_size=10)
                    except Exception as db_err:
                        logger.warning(
                            "Impossible de créer le pool DB, commandes /vip désactivées",
                            error=str(db_err),
                        )
                        self.db_pool = None
                else:
                    logger.warning("DATABASE_URL non configurée, commandes /vip désactivées")
                    self.db_pool = None

                # Initialiser Redis client (C1 fix: avant register_handlers)
                redis_url = os.getenv("REDIS_URL")
                if redis_url:
                    try:
                        import redis.asyncio as redis_async

                        self.redis_client = redis_async.from_url(redis_url)
                        await self.redis_client.ping()
                        logger.info("Redis client initialisé")
                    except Exception as redis_err:
                        logger.warning(
                            "Impossible de connecter Redis",
                            error=str(redis_err),
                        )
                        self.redis_client = None

                return  # Succès

            except Exception as e:
                logger.error(
                    "Échec connexion bot",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(e),
                    error_type=type(e).__name__,
                )

                if attempt < max_retries:
                    backoff = backoff_base**attempt
                    logger.info("Retry après backoff", backoff_sec=backoff)
                    await asyncio.sleep(backoff)
                else:
                    raise Exception(
                        f"Impossible de se connecter au bot après {max_retries} tentatives: {e}"
                    )

    def register_handlers(self) -> None:
        """Enregistre tous les handlers de messages et commandes."""
        if not self.application:
            raise RuntimeError("Application not initialized, call init() first")

        # Commandes
        self.application.add_handler(CommandHandler("help", commands.help_command))
        self.application.add_handler(CommandHandler("start", commands.start_command))

        # Commandes Story 1.11 - Trust & Budget (AC1-AC7)
        self.application.add_handler(CommandHandler("status", trust_budget_commands.status_command))
        self.application.add_handler(
            CommandHandler("journal", trust_budget_commands.journal_command)
        )
        self.application.add_handler(
            CommandHandler("receipt", trust_budget_commands.receipt_command)
        )
        self.application.add_handler(
            CommandHandler("confiance", trust_budget_commands.confiance_command)
        )
        self.application.add_handler(CommandHandler("stats", trust_budget_commands.stats_command))
        self.application.add_handler(CommandHandler("budget", trust_budget_commands.budget_command))
        self.application.add_handler(
            CommandHandler("pending", trust_budget_commands.pending_command)
        )
        # Callback: bouton [Tout rejeter] de /pending
        from telegram.ext import CallbackQueryHandler as _CQH

        self.application.add_handler(
            _CQH(
                trust_budget_commands.reject_all_pending_callback,
                pattern=r"^reject_all_pending$",
            )
        )

        # Commande Story 1.12 - Backup & Sync
        self.application.add_handler(CommandHandler("backup", backup_commands.backup_command))

        # Commande Story 1.13 - Self-Healing Recovery Events
        self.application.add_handler(CommandHandler("recovery", recovery_commands.recovery_command))

        # Commande Story 2.5 - Draft Reply Email (H1 fix)
        self.application.add_handler(CommandHandler("draft", draft_commands.draft_command))

        # Commandes Story 1.8 - Trust management (AC4, AC5, AC6)
        self.application.add_handler(CommandHandler("trust", trust_commands.trust_command_router))

        # Commandes Story 2.3 - VIP Management (Task 5)
        self.application.add_handler(CommandHandler("vip", vip_commands.vip_command_router))

        # Commandes Story 2.8 - Sender Filter Management
        self.application.add_handler(
            CommandHandler("blacklist", sender_filter_commands.blacklist_command)
        )
        self.application.add_handler(
            CommandHandler("whitelist", sender_filter_commands.whitelist_command)
        )
        self.application.add_handler(
            CommandHandler("filters", sender_filter_commands.filters_command)
        )

        # Commandes Phase A.0 - Pipeline Control & Kill Switch
        self.application.add_handler(CommandHandler("pipeline", pipeline_control.pipeline_command))

        # Commande Email Pipeline Status Monitoring
        self.application.add_handler(
            CommandHandler("email_status", email_status_commands.email_status_command)
        )

        # Story 3.2 - Commande /arbo (gestion arborescence)
        self.application.add_handler(CommandHandler("arbo", arborescence_commands.arbo_command))

        # Story 7.3 - Commande /casquette (gestion contexte multi-casquettes)
        self.application.add_handler(
            CommandHandler("casquette", casquette_commands.handle_casquette_command)
        )

        # Story 7.3 - Commande /conflits (dashboard conflits calendrier)
        self.application.add_handler(
            CommandHandler("conflits", conflict_commands.handle_conflits_command)
        )

        # Story 3.4 - Commandes /warranties, /warranty_expiring, /warranty_stats
        self.application.add_handler(
            CommandHandler("warranties", warranty_commands.warranties_command)
        )
        self.application.add_handler(
            CommandHandler("warranty_expiring", warranty_commands.warranty_expiring_command)
        )
        self.application.add_handler(
            CommandHandler("warranty_stats", warranty_commands.warranty_stats_command)
        )

        # Story 1.10 - Inline buttons callbacks (Approve/Reject/Correct)
        from bot.action_executor import ActionExecutor
        from bot.handlers.callbacks import register_callbacks_handlers
        from bot.handlers.corrections import register_corrections_handlers

        # Note: db_pool sera initialise au demarrage (placeholder None pour l'instant)
        db_pool = getattr(self, "db_pool", None)
        if db_pool:
            # C1 fix: Creer ActionExecutor et le passer aux callbacks
            action_executor = ActionExecutor(db_pool)

            # C3 fix: Enregistrer action email.draft_reply (Story 2.5)
            # Story 2.6: Ajouter paramètre bot pour notifications
            # D25: Utilise adapter SMTP (plus besoin de http_client/emailengine params)
            from bot.action_executor_draft_reply import send_email_via_emailengine

            async def draft_reply_action(**kwargs):
                """Wrapper pour send_email_via_emailengine (Story 2.5 AC5 + Story 2.6 notifications)"""
                receipt_id = kwargs.get("receipt_id")
                if not receipt_id:
                    raise ValueError("receipt_id manquant dans payload")

                result = await send_email_via_emailengine(
                    receipt_id=receipt_id,
                    db_pool=db_pool,
                    bot=self.application.bot,  # Story 2.6: Passer bot pour notifications
                )
                return result

            action_executor.register_action("email.draft_reply", draft_reply_action)
            logger.info(
                "Action email.draft_reply registered in ActionExecutor (with notifications support)"
            )

            register_callbacks_handlers(self.application, db_pool, action_executor=action_executor)
            register_corrections_handlers(self.application, db_pool)
            logger.info("Story 1.10 callback handlers registered with ActionExecutor")

            # Story 7.1 - Event callbacks (AC3)
            from bot.handlers.event_callbacks_register import register_event_callbacks_handlers

            register_event_callbacks_handlers(self.application, db_pool)
            logger.info("Story 7.1 event callback handlers registered")

            # Story 3.2 - Classification callbacks (Approve/Correct/Reject)
            from bot.handlers.classification_callbacks_register import (
                register_classification_callbacks_handlers,
            )

            register_classification_callbacks_handlers(self.application, db_pool)
            logger.info("Story 3.2 classification callback handlers registered")

            # Story 3.4 - Warranty callbacks (Confirm/Edit/Delete)
            from bot.handlers.warranty_callbacks import register_warranty_callbacks_handlers

            register_warranty_callbacks_handlers(self.application, db_pool)
            logger.info("Story 3.4 warranty callback handlers registered")

            # Story 7.3 - Casquette callbacks (Médecin/Enseignant/Chercheur/Auto)
            from bot.handlers.casquette_callbacks_register import (
                register_casquette_callbacks_handlers,
            )

            if self.redis_client:
                register_casquette_callbacks_handlers(self.application, db_pool, self.redis_client)
                logger.info("Story 7.3 casquette callback handlers registered")
            else:
                logger.warning(
                    "redis_client not available, casquette callback handlers not registered"
                )

            # Story 7.3 - Conflict callbacks (Cancel/Move/Ignore conflits calendrier)
            from bot.handlers.conflict_callbacks_register import (
                register_conflict_callbacks_handlers,
            )

            if self.redis_client:
                register_conflict_callbacks_handlers(self.application, db_pool, self.redis_client)
                logger.info("Story 7.3 conflict callback handlers registered")
            else:
                logger.warning(
                    "redis_client not available, conflict callback handlers not registered"
                )
        else:
            logger.warning("db_pool not available, callback handlers not registered")

        # Story 3.6 - File Upload Handlers (Document + Photo)
        from bot.handlers import file_handlers

        self.application.add_handler(
            MessageHandler(filters.Document.ALL, file_handlers.handle_document)
        )
        self.application.add_handler(MessageHandler(filters.PHOTO, file_handlers.handle_photo))
        logger.info("Story 3.6 file upload handlers registered (Document + Photo)")

        # Story 3.6 - File Send Command (Intent Detection)
        from bot.handlers import file_send_commands

        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                file_send_commands.handle_file_send_request,
                block=False,  # Ne bloque pas les handlers suivants si intention non détectée
            )
        )
        logger.info("Story 3.6 file send intent handler registered")

        # Story 3.7 - Batch Processing Command (Intent Detection)
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                batch_commands.handle_batch_command,
                block=False,  # Ne bloque pas les handlers suivants si intention non détectée
            )
        )
        logger.info("Story 3.7 batch processing intent handler registered")

        # Story 3.7 - Batch Callback Handlers (Start/Cancel/Options/Pause/Details)
        from telegram.ext import CallbackQueryHandler

        self.application.add_handler(
            CallbackQueryHandler(
                batch_commands.handle_batch_start_callback,
                pattern=r"^batch_start_",
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                batch_commands.handle_batch_cancel_callback,
                pattern=r"^batch_cancel_",
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                batch_commands.handle_batch_options_callback,
                pattern=r"^batch_options_",
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                batch_commands.handle_batch_pause_callback,
                pattern=r"^batch_pause_",
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                batch_commands.handle_batch_details_callback,
                pattern=r"^batch_details_",
            )
        )
        logger.info("Story 3.7 batch callback handlers registered")

        # Story 3.8 - Commande /scan_dedup (Scan & Deduplication PC)
        self.application.add_handler(
            CommandHandler("scan_dedup", dedup_commands.scan_dedup_command)
        )

        # Story 3.8 - Dedup Callback Handlers (Report/Delete/Confirm/Cancel)
        self.application.add_handler(
            CallbackQueryHandler(
                dedup_commands.handle_dedup_report_callback,
                pattern=r"^dedup_report_",
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                dedup_commands.handle_dedup_delete_callback,
                pattern=r"^dedup_delete_",
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                dedup_commands.handle_dedup_confirm_callback,
                pattern=r"^dedup_confirm_",
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                dedup_commands.handle_dedup_cancel_callback,
                pattern=r"^dedup_cancel_",
            )
        )
        logger.info("Story 3.8 dedup scan handlers registered")

        # Messages texte libres (Chat & Proactive uniquement)
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, messages.handle_text_message)
        )

        # Onboarding nouveaux membres (AC6) - CRIT-1 fix
        from telegram.ext import ChatMemberHandler

        self.application.add_handler(
            ChatMemberHandler(messages.handle_new_member, ChatMemberHandler.CHAT_MEMBER)
        )

        logger.info("Handlers enregistrés")

    async def heartbeat_loop(self) -> None:
        """
        Boucle heartbeat toutes les N secondes (BUG-1.9.3 fix).

        Vérifie que la connexion bot est toujours active.
        """
        while self.is_running:
            try:
                # Test connexion en appelant getMe
                bot_info = await self.application.bot.get_me()
                self.last_heartbeat_success = time.time()
                logger.debug("Heartbeat OK", bot_username=bot_info.username)

            except Exception as e:
                logger.error("Heartbeat échec - connexion bot perdue", error=str(e))

                # Si heartbeat échoue >5min, alerter System topic
                time_since_last_success = time.time() - self.last_heartbeat_success
                if time_since_last_success > 300:  # 5 minutes
                    logger.critical(
                        "Bot déconnecté >5min, alerte System", downtime_sec=time_since_last_success
                    )
                    # MED-1 fix: Envoyer alerte via Redis Streams
                    try:
                        import redis.asyncio as redis_async

                        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                        redis_client = await redis_async.from_url(redis_url)
                        await redis_client.xadd(
                            "friday:events:bot.heartbeat.failed",
                            {
                                "bot_name": "friday-bot",
                                "last_success": str(self.last_heartbeat_success),
                                "threshold_seconds": "180",
                                "timestamp": str(time.time()),
                            },
                        )
                        await redis_client.close()
                        logger.info("Alerte heartbeat envoyée via Redis Streams")
                    except Exception as redis_err:
                        logger.error("Échec envoi alerte Redis", error=str(redis_err))

            # Attendre intervalle heartbeat
            await asyncio.sleep(self.config.heartbeat_interval_sec)

    async def email_monitoring_loop(self) -> None:
        """
        Boucle de monitoring du pipeline email toutes les 5 minutes.

        Vérifie l'état de tous les services et envoie des alertes si problème.
        """
        from services.email_healthcheck.monitor import (
            check_email_pipeline_health,
            format_status_message,
        )

        # Attendre 30s avant le premier check (laisser le temps aux services de démarrer)
        await asyncio.sleep(30)

        while self.is_running:
            try:
                # Check pipeline health
                health = await check_email_pipeline_health()

                # Détecter changements de statut (pour éviter spam)
                status_changed = (
                    self.last_email_health_status is None
                    or self.last_email_health_status != health.overall_status
                )

                # Envoyer alerte si problème ou changement de statut
                if health.overall_status != "healthy" or (
                    status_changed and health.overall_status == "healthy"
                ):
                    # Format message
                    message = format_status_message(health)

                    # Envoyer au topic System
                    system_topic_id = int(os.getenv("TOPIC_SYSTEM_ID", "0"))
                    supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))

                    if system_topic_id and supergroup_id:
                        try:
                            await self.application.bot.send_message(
                                chat_id=supergroup_id,
                                message_thread_id=system_topic_id,
                                text=message,
                                parse_mode="Markdown",
                            )
                            logger.info(
                                "Email pipeline status sent to Telegram",
                                status=health.overall_status,
                                alerts_count=len(health.alerts),
                            )
                        except Exception as send_err:
                            logger.error(
                                "Failed to send email pipeline alert to Telegram",
                                error=str(send_err),
                            )

                # Mettre à jour last status
                self.last_email_health_status = health.overall_status

                # Log status en debug
                logger.debug(
                    "Email pipeline monitoring check",
                    status=health.overall_status,
                    alerts=len(health.alerts),
                )

            except Exception as e:
                logger.error(
                    "Email monitoring loop error", error=str(e), error_type=type(e).__name__
                )

            # Attendre 5 minutes avant prochain check
            await asyncio.sleep(300)  # 5 minutes

    async def run(self) -> None:
        """Démarre le bot et la boucle heartbeat."""
        if not self.application:
            raise RuntimeError("Application not initialized, call init() first")

        self.is_running = True

        # Démarrer heartbeat en arrière-plan
        self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        logger.info("Heartbeat démarré", interval_sec=self.config.heartbeat_interval_sec)

        # Démarrer email pipeline monitoring en arrière-plan
        self.email_monitoring_task = asyncio.create_task(self.email_monitoring_loop())
        logger.info("Email pipeline monitoring démarré", interval_sec=300)

        # Passer db_pool via bot_data pour handlers (H1 fix)
        if self.db_pool:
            self.application.bot_data["db_pool"] = self.db_pool
            logger.info("DB pool disponible pour handlers via bot_data")

        # H5 fix: Clé consistante "redis_client" dans bot_data
        if self.redis_client:
            self.application.bot_data["redis_client"] = self.redis_client
            logger.info("Redis client disponible pour handlers via bot_data")

        # Démarrer polling Telegram
        logger.info("Démarrage polling Telegram...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

        logger.info("Bot Friday 2.0 opérationnel")  # MED-2 fix: pas d'emoji dans logs

    async def shutdown(self) -> None:
        """Arrête le bot proprement (graceful shutdown)."""
        logger.info("Arrêt du bot...")
        self.is_running = False

        # Arrêter heartbeat
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

        # Arrêter email monitoring
        if self.email_monitoring_task:
            self.email_monitoring_task.cancel()
            try:
                await self.email_monitoring_task
            except asyncio.CancelledError:
                pass

        # Fermer pool DB (H1 fix)
        if self.db_pool:
            await self.db_pool.close()
            logger.info("PostgreSQL pool fermé")

        # Fermer Redis client
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis client fermé")

        # Arrêter application
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

        logger.info("Bot arrêté proprement")  # MED-2 fix: pas d'emoji dans logs


# Instance globale pour gestion signaux
bot_instance: FridayBot | None = None
shutdown_event = asyncio.Event()


def handle_signal(signum, frame):
    """Handler pour SIGTERM/SIGINT (graceful shutdown) - CRIT-4 fix."""
    logger.info("Signal reçu, arrêt du bot", signal=signum)
    # Set flag pour arrêt propre depuis la boucle async (pas create_task depuis sync)
    shutdown_event.set()


async def main() -> None:
    """Point d'entrée principal."""
    global bot_instance

    # Configurer logging
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    try:
        # Créer et initialiser bot
        bot_instance = FridayBot()
        await bot_instance.init()

        # Enregistrer handlers
        bot_instance.register_handlers()

        # Enregistrer handlers signaux pour graceful shutdown
        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        # Démarrer bot
        await bot_instance.run()

        # Garder le bot en vie jusqu'au signal shutdown
        while bot_instance.is_running and not shutdown_event.is_set():
            await asyncio.sleep(1)

        # Graceful shutdown si signal reçu (CRIT-4 fix)
        if shutdown_event.is_set():
            await bot_instance.shutdown()

    except ConfigurationError as e:
        logger.critical("Configuration invalide, impossible de démarrer le bot", error=str(e))
        sys.exit(1)

    except Exception as e:
        logger.critical("Erreur fatale, arrêt du bot", error=str(e), error_type=type(e).__name__)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
