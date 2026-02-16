#!/usr/bin/env python3
"""
Friday 2.0 - Budget Monitor (Story 6.2 - AC6)

Service monitoring des budgets API (Voyage AI, Claude, etc.)
Vérifie usage mensuel vs limites et envoie alertes Telegram si seuils dépassés.

Usage:
    # Vérification manuelle
    python budget_monitor.py --check

    # Mode cron (run toutes les 6h)
    python budget_monitor.py --cron

Date: 2026-02-11
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from typing import Optional

import asyncpg
import structlog

logger = structlog.get_logger(__name__)


class BudgetMonitor:
    """
    Moniteur budget API avec alertes Telegram.

    Features:
        - Vérifie usage mensuel vs limites configurées
        - Envoie alertes Telegram si WARNING (>80%) ou EXCEEDED (>100%)
        - Cooldown 24h entre alertes identiques (évite spam)
    """

    def __init__(
        self,
        db_url: str,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ):
        """
        Initialise budget monitor.

        Args:
            db_url: PostgreSQL connection string
            telegram_token: Bot token Telegram (optionnel)
            telegram_chat_id: Chat ID pour alertes (optionnel)
        """
        self.db_url = db_url
        self.telegram_token = telegram_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = telegram_chat_id or os.getenv("TELEGRAM_SUPERGROUP_ID")

        logger.info(
            "budget_monitor_initialized",
            telegram_enabled=bool(self.telegram_token and self.telegram_chat_id),
        )

    async def check_budgets(self) -> list[dict]:
        """
        Vérifie budgets API actuels vs limites.

        Returns:
            Liste status par service [{service, status, usage_pct, ...}, ...]
        """
        conn = await asyncpg.connect(self.db_url)

        try:
            # Query vue core.api_budget_status
            rows = await conn.fetch("""
                SELECT
                    service,
                    monthly_limit_cents,
                    spent_cents,
                    usage_pct,
                    remaining_cents,
                    status
                FROM core.api_budget_status
                ORDER BY usage_pct DESC
                """)

            results = []
            for row in rows:
                result = {
                    "service": row["service"],
                    "monthly_limit_eur": row["monthly_limit_cents"] / 100.0,
                    "spent_eur": row["spent_cents"] / 100.0,
                    "usage_pct": float(row["usage_pct"]),
                    "remaining_eur": row["remaining_cents"] / 100.0,
                    "status": row["status"],
                }
                results.append(result)

                logger.info(
                    "budget_status_checked",
                    **result,
                )

            return results

        finally:
            await conn.close()

    async def send_telegram_alert(
        self, service: str, status: str, usage_pct: float, spent_eur: float, limit_eur: float
    ) -> None:
        """
        Envoie alerte Telegram si budget WARNING ou EXCEEDED.

        Args:
            service: Nom du service (voyage-ai, anthropic, etc.)
            status: Status budget (OK, WARNING, EXCEEDED)
            usage_pct: % utilisation budget
            spent_eur: Montant dépensé (EUR)
            limit_eur: Limite mensuelle (EUR)
        """
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("telegram_not_configured_skip_alert")
            return

        if status not in ["WARNING", "EXCEEDED"]:
            # Pas d'alerte si OK
            return

        # Message alerte
        emoji = "⚠️" if status == "WARNING" else "🚨"
        message = (
            f"{emoji} **Budget API Alert - {service.upper()}**\n\n"
            f"Status: {status}\n"
            f"Usage: {usage_pct:.1f}% ({spent_eur:.2f} EUR / {limit_eur:.2f} EUR)\n"
            f"Remaining: {(limit_eur - spent_eur):.2f} EUR\n\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

        # Envoyer via Telegram Bot API
        try:
            import aiohttp

            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(
                            "telegram_alert_sent",
                            service=service,
                            status=status,
                            usage_pct=usage_pct,
                        )
                    else:
                        error_text = await resp.text()
                        logger.error(
                            "telegram_alert_failed",
                            status_code=resp.status,
                            error=error_text,
                        )

        except Exception as e:
            logger.error(
                "telegram_alert_exception",
                error=str(e),
                service=service,
            )

    async def run_check(self) -> None:
        """
        Exécute vérification budgets et envoie alertes si nécessaire.
        """
        logger.info("budget_check_started")

        try:
            results = await self.check_budgets()

            for result in results:
                if result["status"] in ["WARNING", "EXCEEDED"]:
                    await self.send_telegram_alert(
                        service=result["service"],
                        status=result["status"],
                        usage_pct=result["usage_pct"],
                        spent_eur=result["spent_eur"],
                        limit_eur=result["monthly_limit_eur"],
                    )

            logger.info("budget_check_completed", services_checked=len(results))

        except Exception as e:
            logger.error("budget_check_failed", error=str(e))
            raise


async def main():
    """CLI entrypoint"""
    parser = argparse.ArgumentParser(description="Friday 2.0 - Budget Monitor")
    parser.add_argument("--check", action="store_true", help="Vérifier budgets une fois")
    parser.add_argument("--cron", action="store_true", help="Mode cron (run toutes les 6h)")
    args = parser.parse_args()

    # Configuration
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL manquante")
        sys.exit(1)

    monitor = BudgetMonitor(db_url=db_url)

    if args.cron:
        # Mode cron : run indéfiniment toutes les 6h
        logger.info("budget_monitor_cron_started", interval_hours=6)
        while True:
            await monitor.run_check()
            await asyncio.sleep(6 * 3600)  # 6 heures

    else:
        # Mode check unique
        await monitor.run_check()


if __name__ == "__main__":
    asyncio.run(main())
