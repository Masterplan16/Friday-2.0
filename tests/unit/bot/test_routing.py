"""
Tests unitaires pour bot/routing.py

Story 1.9 - Tests critiques de l'algorithme de routage (AC4).
"""

import pytest
from bot.routing import EventRouter
from bot.models import TelegramEvent, BotConfig, TopicConfig


@pytest.fixture
def mock_bot_config():
    """Fixture config bot avec 5 topics."""
    topics = {
        "chat_proactive": TopicConfig(name="Chat & Proactive", thread_id=100, icon="💬"),
        "email": TopicConfig(name="Email & Communications", thread_id=200, icon="📬"),
        "actions": TopicConfig(name="Actions & Validations", thread_id=300, icon="🤖"),
        "system": TopicConfig(name="System & Alerts", thread_id=400, icon="🚨"),
        "metrics": TopicConfig(name="Metrics & Logs", thread_id=500, icon="📊"),
    }

    return BotConfig(
        token="123456:ABC-DEF",
        supergroup_id=-1001234567890,
        topics=topics,
        heartbeat_interval_sec=60,
        rate_limit_msg_per_sec=25,
        max_message_length=4096,
    )


@pytest.fixture
def router(mock_bot_config):
    """Fixture router initialisé."""
    return EventRouter(mock_bot_config)


# ═══════════════════════════════════════════════════════════
# Tests de routage (6 tests requis - AC4)
# ═══════════════════════════════════════════════════════════


def test_routing_heartbeat(router):
    """
    Test 1/6: Event heartbeat → Chat & Proactive (règle 1).

    Vérifie que les événements avec source='heartbeat' sont routés
    vers le topic Chat & Proactive.
    """
    event = TelegramEvent(
        source="heartbeat",
        type="heartbeat.check",
        message="Heartbeat OK",
    )

    thread_id = router.route_event(event)

    assert thread_id == 100  # Chat & Proactive
    assert router.get_topic_name(thread_id) == "💬 Chat & Proactive"


def test_routing_email(router):
    """
    Test 2/6: Event email → Email & Communications (règle 2).

    Vérifie que les événements avec module='email' sont routés
    vers le topic Email & Communications.
    """
    event = TelegramEvent(
        module="email",
        type="email.classified",
        message="Email classé: medical",
    )

    thread_id = router.route_event(event)

    assert thread_id == 200  # Email & Communications
    assert router.get_topic_name(thread_id) == "📬 Email & Communications"


def test_routing_action(router):
    """
    Test 3/6: Event action.* → Actions & Validations (règle 3).

    Vérifie que les événements avec type='action.*' sont routés
    vers le topic Actions & Validations.
    """
    event = TelegramEvent(
        type="action.pending",
        message="Action nécessitant validation",
    )

    thread_id = router.route_event(event)

    assert thread_id == 300  # Actions & Validations
    assert router.get_topic_name(thread_id) == "🤖 Actions & Validations"


def test_routing_critical(router):
    """
    Test 4/6: Event priority=critical → System & Alerts (règle 4).

    Vérifie que les événements avec priority='critical' sont routés
    vers le topic System & Alerts, même si module est défini.

    Note (BUG-1.9.11): Cette règle peut intercepter des events comme
    email.urgent avec priority=critical. C'est intentionnel - les alertes
    critiques ont priorité sur le module source.
    """
    event = TelegramEvent(
        module="email",  # Module email défini
        type="email.urgent",
        priority="critical",  # Priority critical prend priorité (règle 4 > règle 2)
        message="Email URGENT - Patient critique",
    )

    thread_id = router.route_event(event)

    assert thread_id == 400  # System & Alerts (PAS Email & Communications)
    assert router.get_topic_name(thread_id) == "🚨 System & Alerts"


def test_routing_default(router):
    """
    Test 5/6: Event sans condition spécifique → Metrics & Logs (règle 5).

    Vérifie que les événements qui ne matchent aucune règle (1-4)
    sont routés vers Metrics & Logs par défaut.
    """
    event = TelegramEvent(
        type="generic.info",
        priority="info",
        message="Événement informationnel générique",
    )

    thread_id = router.route_event(event)

    assert thread_id == 500  # Metrics & Logs
    assert router.get_topic_name(thread_id) == "📊 Metrics & Logs"


def test_routing_ambiguous_event(router):
    """
    Test 6/6: Event ambigu (multiple règles matchent) - Edge case.

    Teste le comportement de l'algorithme séquentiel quand un événement
    matche potentiellement plusieurs règles. L'ordre des conditions
    dans route_event() détermine le résultat.

    Cas: Event avec source='heartbeat' (règle 1) ET module='email' (règle 2).
    Résultat attendu: Règle 1 (heartbeat) a priorité car testée avant.
    """
    event = TelegramEvent(
        source="heartbeat",  # Règle 1
        module="email",  # Règle 2
        type="heartbeat.check",
        message="Heartbeat check depuis module email",
    )

    thread_id = router.route_event(event)

    # Règle 1 (heartbeat) a priorité car testée en premier
    assert thread_id == 100  # Chat & Proactive
    assert router.get_topic_name(thread_id) == "💬 Chat & Proactive"


# ═══════════════════════════════════════════════════════════
# Tests de validation (BUG-1.9.12 fix)
# ═══════════════════════════════════════════════════════════


def test_routing_invalid_event_type(router):
    """
    Test: Event avec type invalide → Fallback Metrics & Logs.

    BUG-1.9.12 fix: Validation event.type, fallback silencieux avec warning log.
    """
    event = TelegramEvent(
        type="",  # Type vide (invalide)
        message="Event avec type invalide",
    )

    thread_id = router.route_event(event)

    # Fallback vers Metrics & Logs
    assert thread_id == 500
