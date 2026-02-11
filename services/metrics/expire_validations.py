"""
Friday 2.0 - Expiration des validations en attente

Story 1.10, Task 4: Cron job nightly pour expirer les receipts pending
qui ont depasse le timeout configurable.

Usage (cron):
    python -m services.metrics.expire_validations

Config:
    config/telegram.yaml -> validation_timeout_hours (null = desactive)
"""

import asyncio
import os

import asyncpg
import structlog
import yaml

logger = structlog.get_logger(__name__)


async def expire_pending_validations(
    db_pool: asyncpg.Pool,
    timeout_hours: int | None = None,
) -> int:
    """
    Expire les receipts pending qui ont depasse le timeout.

    Args:
        db_pool: Pool de connexions PostgreSQL
        timeout_hours: Heures avant expiration (None = desactive)

    Returns:
        Nombre de receipts expires
    """
    # BUG-1.10.13 fix: Verifier timeout != null avant expiration
    if timeout_hours is None:
        logger.info("Validation timeout disabled (null), skipping expiration")
        return 0

    # L2 fix: keyword args structlog (pas de %-formatting)
    if timeout_hours <= 0:
        logger.warning("Invalid timeout_hours, skipping", timeout_hours=timeout_hours)
        return 0

    async with db_pool.acquire() as conn:
        # Trouver et expirer les receipts pending depasses
        expired_rows = await conn.fetch(
            "UPDATE core.action_receipts "
            "SET status = 'expired', updated_at = NOW() "
            "WHERE status = 'pending' "
            "  AND created_at < NOW() - INTERVAL '1 hour' * $1 "
            "RETURNING id, module, action_type, created_at",
            timeout_hours,
        )

    expired_count = len(expired_rows)

    if expired_count > 0:
        logger.info(
            "Expired pending validations",
            count=expired_count,
            timeout_hours=timeout_hours,
        )
        for row in expired_rows:
            logger.info(
                "Receipt expired",
                receipt_id=str(row["id"]),
                module=row["module"],
                action_type=row["action_type"],
                created_at=str(row["created_at"]),
            )
    else:
        logger.info("No pending validations to expire")

    return expired_count


async def notify_expiration_telegram(expired_count: int, timeout_hours: int) -> None:
    """
    H5 fix: Envoie une notification dans le topic System & Alerts
    quand des validations expirent (AC6).

    Args:
        expired_count: Nombre de receipts expires
        timeout_hours: Timeout configure en heures
    """
    if expired_count == 0:
        return

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    supergroup_id = os.getenv("TELEGRAM_SUPERGROUP_ID")
    system_topic_id = os.getenv("TOPIC_SYSTEM_ID")

    if not bot_token or not supergroup_id or not system_topic_id:
        logger.warning(
            "Telegram not configured, skipping expiration notification",
            bot_token_set=bool(bot_token),
            supergroup_id_set=bool(supergroup_id),
            system_topic_id_set=bool(system_topic_id),
        )
        return

    try:
        from telegram import Bot

        bot = Bot(token=bot_token)
        text = (
            f"Validations expirees\n"
            f"{expired_count} action(s) en attente expiree(s) apres {timeout_hours}h\n"
            f"Les actions n'ont pas ete executees."
        )
        await bot.send_message(
            chat_id=int(supergroup_id),
            message_thread_id=int(system_topic_id),
            text=text,
        )
        logger.info(
            "Expiration notification sent to System topic",
            expired_count=expired_count,
        )
    except Exception as e:
        logger.error(
            "Failed to send expiration notification",
            error=str(e),
        )


def load_timeout_config(config_path: str = "config/telegram.yaml") -> int | None:
    """
    Charge le timeout de validation depuis la config YAML.

    Args:
        config_path: Chemin vers telegram.yaml

    Returns:
        Timeout en heures ou None si desactive
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            return config.get("validation_timeout_hours")
    except FileNotFoundError:
        logger.warning("Config file not found", config_path=config_path)
        return None


async def main() -> None:
    """Point d'entree pour le cron job."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set")
        return

    timeout_hours = load_timeout_config()
    logger.info("Starting validation expiration", timeout_hours=timeout_hours)

    pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=2)
    try:
        expired = await expire_pending_validations(pool, timeout_hours)
        # H5 fix: Notifier Telegram si des validations ont expire
        if timeout_hours is not None:
            await notify_expiration_telegram(expired, timeout_hours)
        logger.info("Expiration complete", expired_count=expired)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
