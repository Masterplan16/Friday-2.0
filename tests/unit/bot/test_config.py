"""
Tests unitaires pour bot/config.py

Story 1.9 - Tests configuration bot (chargement variables, validation).
"""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from bot.config import load_bot_config, ConfigurationError


# ═══════════════════════════════════════════════════════════
# Tests chargement configuration (4 tests requis)
# ═══════════════════════════════════════════════════════════


@patch.dict(os.environ, {
    "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF1234567890abcdef",
    "TELEGRAM_SUPERGROUP_ID": "-1001234567890",
    "TOPIC_CHAT_PROACTIVE_ID": "100",
    "TOPIC_EMAIL_ID": "200",
    "TOPIC_ACTIONS_ID": "300",
    "TOPIC_SYSTEM_ID": "400",
    "TOPIC_METRICS_ID": "500",
}, clear=True)
def test_config_loading_valid():
    """
    Test 1/4: Configuration valide chargée correctement.

    Vérifie que load_bot_config() charge toutes les variables d'environnement
    et retourne un BotConfig valide avec les 5 topics.
    """
    config = load_bot_config()

    # Vérifier token et supergroup_id
    assert config.token == "123456:ABC-DEF1234567890abcdef"
    assert config.supergroup_id == -1001234567890

    # Vérifier 5 topics chargés
    assert len(config.topics) == 5
    assert "chat_proactive" in config.topics
    assert config.topics["chat_proactive"].thread_id == 100
    assert config.topics["email"].thread_id == 200
    assert config.topics["actions"].thread_id == 300
    assert config.topics["system"].thread_id == 400
    assert config.topics["metrics"].thread_id == 500

    # Vérifier valeurs par défaut
    assert config.heartbeat_interval_sec == 60
    assert config.rate_limit_msg_per_sec == 25
    assert config.max_message_length == 4096


@patch.dict(os.environ, {
    "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
    "TELEGRAM_SUPERGROUP_ID": "-1001234567890",
    # MANQUE: TOPIC_CHAT_PROACTIVE_ID
    "TOPIC_EMAIL_ID": "200",
    "TOPIC_ACTIONS_ID": "300",
    "TOPIC_SYSTEM_ID": "400",
    "TOPIC_METRICS_ID": "500",
}, clear=True)
def test_config_loading_missing_var():
    """
    Test 2/4: Erreur claire si variable manquante.

    BUG-1.9.6 fix: Vérifier que toutes les 7 variables d'environnement
    sont présentes, sinon lever ConfigurationError avec message explicite.
    """
    with pytest.raises(ConfigurationError) as exc_info:
        load_bot_config()

    # Vérifier message d'erreur mentionne la variable manquante
    assert "TOPIC_CHAT_PROACTIVE_ID" in str(exc_info.value)
    assert "manquantes" in str(exc_info.value).lower()


@patch.dict(os.environ, {
    "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
    "TELEGRAM_SUPERGROUP_ID": "-1001234567890",
    "TOPIC_CHAT_PROACTIVE_ID": "0",  # INVALIDE: thread_id doit être >0
    "TOPIC_EMAIL_ID": "200",
    "TOPIC_ACTIONS_ID": "300",
    "TOPIC_SYSTEM_ID": "400",
    "TOPIC_METRICS_ID": "500",
}, clear=True)
def test_config_validation_invalid_thread_id():
    """
    Test 3/4: Validation thread_id > 0 (BUG-1.9.5 fix).

    Vérifie que si un thread_id est <=0, ConfigurationError est levée
    avec un message explicite.
    """
    with pytest.raises(ConfigurationError) as exc_info:
        load_bot_config()

    # Vérifier message d'erreur mentionne thread_id invalide
    error_msg = str(exc_info.value).lower()
    assert "topic_chat_proactive_id" in error_msg
    assert ">0" in error_msg or "invalide" in error_msg


@patch.dict(os.environ, {
    "TELEGRAM_BOT_TOKEN": "INVALID_TOKEN_NO_COLON",  # Format invalide
    "TELEGRAM_SUPERGROUP_ID": "-1001234567890",
    "TOPIC_CHAT_PROACTIVE_ID": "100",
    "TOPIC_EMAIL_ID": "200",
    "TOPIC_ACTIONS_ID": "300",
    "TOPIC_SYSTEM_ID": "400",
    "TOPIC_METRICS_ID": "500",
}, clear=True)
def test_config_validation_invalid_token():
    """
    Test 4/4: Validation format token Telegram (BUG-1.9.1 fix).

    Vérifie que le token a le bon format (<bot_id>:<token>), sinon
    ConfigurationError est levée.
    """
    with pytest.raises(ConfigurationError) as exc_info:
        load_bot_config()

    # Vérifier message d'erreur mentionne token invalide
    error_msg = str(exc_info.value).lower()
    assert "token" in error_msg
    assert "invalide" in error_msg or "format" in error_msg


# ═══════════════════════════════════════════════════════════
# Tests validation permissions bot (BUG-1.9.7 fix)
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_validate_bot_permissions_not_admin():
    """
    Test: Bot n'est pas admin → ConfigurationError.

    BUG-1.9.7 fix: Vérifier que le bot a les droits admin au démarrage.
    """
    from bot.config import validate_bot_permissions

    # Mock bot sans droits admin
    mock_bot = MagicMock()
    mock_member = MagicMock()
    mock_member.status = "member"  # PAS "administrator"
    mock_bot.get_chat_member = AsyncMock(return_value=mock_member)

    with pytest.raises(ConfigurationError) as exc_info:
        await validate_bot_permissions(mock_bot, -1001234567890)

    assert "admin" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_validate_bot_permissions_missing_post_messages():
    """
    Test: Bot admin mais sans permission Post Messages → ConfigurationError.

    BUG-1.9.7 fix: Vérifier permissions spécifiques (post_messages, manage_topics).
    """
    from bot.config import validate_bot_permissions

    # Mock bot admin mais sans can_post_messages
    mock_bot = MagicMock()
    mock_member = MagicMock()
    mock_member.status = "administrator"
    mock_member.can_post_messages = False  # MANQUE permission
    mock_member.can_manage_topics = True
    mock_bot.get_chat_member = AsyncMock(return_value=mock_member)

    with pytest.raises(ConfigurationError) as exc_info:
        await validate_bot_permissions(mock_bot, -1001234567890)

    assert "can_post_messages" in str(exc_info.value)
