"""
Bot Telegram Friday 2.0 - Configuration Loader

Charge la configuration du bot depuis les variables d'environnement et config/telegram.yaml.
"""

import os
from pathlib import Path
from typing import Any

import structlog
import yaml
from bot.models import BotConfig, TopicConfig

logger = structlog.get_logger(__name__)


class ConfigurationError(Exception):
    """Exception levée si la configuration est invalide ou incomplète."""


def load_bot_config() -> BotConfig:
    """
    Charge la configuration complète du bot Telegram.

    Returns:
        BotConfig: Configuration validée du bot

    Raises:
        ConfigurationError: Si la configuration est invalide ou incomplète
    """
    # 1. Charger variables d'environnement requises
    required_env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_SUPERGROUP_ID",
        "TOPIC_CHAT_PROACTIVE_ID",
        "TOPIC_EMAIL_ID",
        "TOPIC_ACTIONS_ID",
        "TOPIC_SYSTEM_ID",
        "TOPIC_METRICS_ID",
    ]

    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ConfigurationError(f"Variables d'environnement manquantes: {', '.join(missing_vars)}")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    supergroup_id_str = os.getenv("TELEGRAM_SUPERGROUP_ID", "0")

    # Validation token non-vide (BUG-1.9.6 fix)
    if not token.strip():
        raise ConfigurationError("TELEGRAM_BOT_TOKEN est vide")

    # Parse supergroup_id
    try:
        supergroup_id = int(supergroup_id_str)
    except ValueError:
        raise ConfigurationError(f"TELEGRAM_SUPERGROUP_ID invalide: {supergroup_id_str}")

    # 2. Charger thread IDs des topics
    topics = {}
    topic_configs = [
        ("chat_proactive", "Chat & Proactive", "TOPIC_CHAT_PROACTIVE_ID", "💬"),
        ("email", "Email & Communications", "TOPIC_EMAIL_ID", "📬"),
        ("actions", "Actions & Validations", "TOPIC_ACTIONS_ID", "🤖"),
        ("system", "System & Alerts", "TOPIC_SYSTEM_ID", "🚨"),
        ("metrics", "Metrics & Logs", "TOPIC_METRICS_ID", "📊"),
    ]

    for key, name, env_var, icon in topic_configs:
        thread_id_str = os.getenv(env_var, "0")
        try:
            thread_id = int(thread_id_str)
        except ValueError:
            raise ConfigurationError(f"{env_var} invalide: {thread_id_str}")

        # Validation thread_id > 0 (BUG-1.9.5 fix)
        if thread_id <= 0:
            raise ConfigurationError(f"{env_var} doit être >0, reçu: {thread_id}")

        topics[key] = TopicConfig(name=name, thread_id=thread_id, icon=icon)

    # 3. Charger config additionnelle depuis telegram.yaml (si existe)
    # MED-1 fix: Envvar pour config path avec default
    config_path = Path(os.getenv("TELEGRAM_CONFIG_PATH", "config/telegram.yaml"))
    yaml_config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(
                "Erreur lecture config/telegram.yaml, utilisation defaults", error=str(e)
            )

    # 4. Construire BotConfig avec validation Pydantic
    try:
        bot_config = BotConfig(
            token=token,
            supergroup_id=supergroup_id,
            topics=topics,
            heartbeat_interval_sec=yaml_config.get("heartbeat_interval_sec", 60),
            rate_limit_msg_per_sec=yaml_config.get("rate_limit_msg_per_sec", 25),
            max_message_length=yaml_config.get("max_message_length", 4096),
        )
    except Exception as e:
        raise ConfigurationError(f"Configuration invalide: {e}")

    logger.info(
        "Configuration bot chargée",
        topics_count=len(topics),
        heartbeat_interval=bot_config.heartbeat_interval_sec,
    )

    return bot_config


async def validate_bot_permissions(bot: Any, supergroup_id: int) -> None:
    """
    Valide que le bot a les permissions admin nécessaires dans le supergroup.

    Args:
        bot: Instance du bot Telegram
        supergroup_id: ID du supergroup

    Raises:
        ConfigurationError: Si le bot n'a pas les permissions requises
    """
    # BUG-1.9.7 fix + CRIT-3 fix: Vérifier droits admin au démarrage (ASYNC)
    try:
        member = await bot.get_chat_member(chat_id=supergroup_id, user_id=bot.id)
        if member.status not in ["administrator", "creator"]:
            raise ConfigurationError(
                f"Bot n'est pas admin dans le supergroup (status: {member.status})"
            )

        # Vérifier permissions spécifiques (None = "tous les droits" pour admin, True = explicite)
        required_perms = ["can_post_messages", "can_manage_topics"]
        missing_perms = [perm for perm in required_perms if getattr(member, perm, None) is False]
        if missing_perms:
            raise ConfigurationError(f"Permissions admin manquantes: {', '.join(missing_perms)}")

        logger.info("Permissions bot validées", status=member.status, perms_checked=required_perms)

    except Exception as e:
        raise ConfigurationError(f"Impossible de valider permissions bot: {e}")
