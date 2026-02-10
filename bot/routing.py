"""
Bot Telegram Friday 2.0 - Event Routing

Implémente l'algorithme de routage séquentiel pour router les événements
vers les topics Telegram appropriés (AC4).
"""

import structlog
from bot.models import BotConfig, TelegramEvent

logger = structlog.get_logger(__name__)


class EventRouter:
    """
    Routeur d'événements vers topics Telegram.

    Implémente l'algorithme séquentiel (ordre prioritaire):
    1. Heartbeat/proactive → Chat & Proactive
    2. Email/desktop_search → Email & Communications
    3. Actions (pending/corrected/trust_changed) → Actions & Validations
    4. Critical/Warning → System & Alerts
    5. Default → Metrics & Logs
    """

    def __init__(self, config: BotConfig):
        """
        Initialise le routeur avec la configuration des topics.

        Args:
            config: Configuration du bot contenant les thread IDs
        """
        self.config = config
        self.topics = config.topics

        # Cache des thread IDs pour accès rapide
        self.chat_proactive_thread_id = self.topics["chat_proactive"].thread_id
        self.email_thread_id = self.topics["email"].thread_id
        self.actions_thread_id = self.topics["actions"].thread_id
        self.system_thread_id = self.topics["system"].thread_id
        self.metrics_thread_id = self.topics["metrics"].thread_id

        logger.info("EventRouter initialisé", topics_count=len(self.topics))

    def route_event(self, event: TelegramEvent) -> int:
        """
        Route un événement vers le topic Telegram approprié.

        Args:
            event: Événement à router

        Returns:
            int: Thread ID du topic cible

        Raises:
            ValueError: Si event.type est invalide (BUG-1.9.12 fix)
        """
        # BUG-1.9.12 fix: Validation event.type
        if not event.type or not isinstance(event.type, str):
            logger.warning(
                "Event type invalide, routage vers Metrics par défaut",
                event_type=repr(event.type),
            )
            return self.metrics_thread_id

        # 1. Heartbeat/proactive → Chat & Proactive
        if event.source in ["heartbeat", "proactive"]:
            logger.debug(
                "Event routé vers Chat & Proactive",
                event_type=event.type,
                source=event.source,
            )
            return self.chat_proactive_thread_id

        # 2. Email/desktop_search → Email & Communications
        if event.module in ["email", "desktop_search"]:
            logger.debug(
                "Event routé vers Email & Communications",
                event_type=event.type,
                module=event.module,
            )
            return self.email_thread_id

        # 3. Actions (pending/corrected/trust_changed) → Actions & Validations
        if event.type.startswith("action."):
            logger.debug(
                "Event routé vers Actions & Validations",
                event_type=event.type,
            )
            return self.actions_thread_id

        # 4. Critical/Warning → System & Alerts
        #    BUG-1.9.11 fix: Cette règle peut intercepter des events email.urgent
        #    avec priority=critical. C'est intentionnel - les alertes critiques
        #    ont priorité sur le module source.
        if event.priority in ["critical", "warning"]:
            logger.debug(
                "Event routé vers System & Alerts",
                event_type=event.type,
                priority=event.priority,
            )
            return self.system_thread_id

        # 5. Default → Metrics & Logs
        logger.debug(
            "Event routé vers Metrics & Logs (défaut)",
            event_type=event.type,
        )
        return self.metrics_thread_id

    def get_topic_name(self, thread_id: int) -> str:
        """
        Retourne le nom du topic pour un thread_id donné.

        Args:
            thread_id: Thread ID du topic

        Returns:
            str: Nom du topic (ex: "💬 Chat & Proactive")
        """
        for topic in self.topics.values():
            if topic.thread_id == thread_id:
                return f"{topic.icon} {topic.name}" if topic.icon else topic.name

        return f"Unknown Topic ({thread_id})"
