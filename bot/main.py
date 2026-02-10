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

import structlog
from bot.config import ConfigurationError, load_bot_config, validate_bot_permissions
from bot.handlers import commands, messages, trust_budget_commands, trust_commands
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
        self.is_running = False
        self.heartbeat_task = None
        self.last_heartbeat_success = time.time()

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
        self.application.add_handler(CommandHandler("journal", trust_budget_commands.journal_command))
        self.application.add_handler(CommandHandler("receipt", trust_budget_commands.receipt_command))
        self.application.add_handler(CommandHandler("confiance", trust_budget_commands.confiance_command))
        self.application.add_handler(CommandHandler("stats", trust_budget_commands.stats_command))
        self.application.add_handler(CommandHandler("budget", trust_budget_commands.budget_command))

        # Commandes Story 1.8 - Trust management (AC4, AC5, AC6)
        self.application.add_handler(CommandHandler("trust", trust_commands.trust_command_router))

        # Story 1.10 - Inline buttons callbacks (Approve/Reject/Correct)
        from bot.action_executor import ActionExecutor
        from bot.handlers.callbacks import register_callbacks_handlers
        from bot.handlers.corrections import register_corrections_handlers

        # Note: db_pool sera initialise au demarrage (placeholder None pour l'instant)
        db_pool = getattr(self, "db_pool", None)
        if db_pool:
            # C1 fix: Creer ActionExecutor et le passer aux callbacks
            action_executor = ActionExecutor(db_pool)
            register_callbacks_handlers(self.application, db_pool, action_executor=action_executor)
            register_corrections_handlers(self.application, db_pool)
            logger.info("Story 1.10 callback handlers registered with ActionExecutor")
        else:
            logger.warning("db_pool not available, callback handlers not registered")

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

    async def run(self) -> None:
        """Démarre le bot et la boucle heartbeat."""
        if not self.application:
            raise RuntimeError("Application not initialized, call init() first")

        self.is_running = True

        # Démarrer heartbeat en arrière-plan
        self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        logger.info("Heartbeat démarré", interval_sec=self.config.heartbeat_interval_sec)

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
