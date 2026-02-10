# services/monitoring/emailengine_health.py
# Healthcheck actif EmailEngine pour détecter token expiration
# Partie de Story 1.5 (fixe MOYEN #6 du code review adversarial)

import asyncio
import logging
from datetime import datetime
from typing import Dict, List

import aiohttp

logger = logging.getLogger(__name__)


class EmailEngineHealthMonitor:
    """
    Monitor actif pour détecter problèmes EmailEngine:
    - Token OAuth/IMAP expiré
    - Comptes déconnectés
    - Webhook non fonctionnel

    Exécution: Cron toutes les heures via systemd timer ou n8n workflow
    """

    def __init__(
        self,
        emailengine_url: str,
        emailengine_token: str,
        telegram_bot_token: str,
        telegram_chat_id: str,
    ):
        self.emailengine_url = emailengine_url.rstrip("/")
        self.emailengine_token = emailengine_token
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id

    async def check_accounts_health(self) -> Dict[str, str]:
        """
        Vérifie l'état de connexion de tous les comptes EmailEngine

        Returns:
            Dict mapping account_id -> state (connected, disconnected, error)
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.emailengine_token}"}

                async with session.get(
                    f"{self.emailengine_url}/v1/accounts",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"EmailEngine API error: {resp.status}")
                        await self._send_alert(
                            "🚨 EmailEngine API inaccessible",
                            f"Status: {resp.status}. Vérifier service EmailEngine.",
                        )
                        return {}

                    data = await resp.json()
                    accounts = data.get("accounts", [])

                    account_states = {}
                    for account in accounts:
                        account_id = account["account"]
                        state = account.get("state", "unknown")
                        account_states[account_id] = state

                        # Alerte si compte déconnecté
                        if state != "connected":
                            logger.warning(f"❌ Account {account_id} is {state}")
                            await self._send_alert(
                                f"🚨 Compte email {account_id} déconnecté !",
                                f"État: {state}\n\n"
                                f"Action requise:\n"
                                f"1. Vérifier token OAuth/IMAP dans EmailEngine UI\n"
                                f"2. Re-authentifier si nécessaire\n"
                                f"3. Vérifier logs EmailEngine pour cause détaillée",
                            )

                    logger.info(
                        f"✅ EmailEngine health check: {len(accounts)} accounts - "
                        f"{sum(1 for s in account_states.values() if s == 'connected')} connected"
                    )

                    return account_states

        except asyncio.TimeoutError:
            logger.error("❌ EmailEngine timeout")
            await self._send_alert(
                "🚨 EmailEngine timeout",
                "Service EmailEngine ne répond pas. Vérifier si le service est UP.",
            )
            return {}
        except Exception as e:
            logger.error(f"❌ EmailEngine health check error: {e}", exc_info=True)
            await self._send_alert(
                "🚨 Erreur healthcheck EmailEngine",
                f"Erreur: {str(e)}\n\nVérifier logs monitoring.",
            )
            return {}

    async def check_webhook_delivery(self) -> bool:
        """
        Vérifie que le webhook EmailEngine → n8n fonctionne

        Méthode: Vérifie derniers événements reçus via Redis ou PostgreSQL
        Si aucun événement email.received depuis >2h → Alerte

        Returns:
            True si webhook OK, False sinon
        """
        # TODO Story 2: Implémenter vérification événements récents
        # Query Redis: XREVRANGE email.received + -  COUNT 1
        # Si dernier événement > 2h → Alerte
        logger.info("📡 [TODO] Check webhook delivery (Story 2)")
        return True

    async def _send_alert(self, title: str, message: str):
        """Envoie alerte Telegram"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
                payload = {
                    "chat_id": self.telegram_chat_id,
                    "text": f"**{title}**\n\n{message}",
                    "parse_mode": "Markdown",
                }

                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"❌ Failed to send Telegram alert: {resp.status}")
                    else:
                        logger.info(f"✅ Telegram alert sent: {title}")

        except Exception as e:
            logger.error(f"❌ Failed to send Telegram alert: {e}", exc_info=True)


async def main():
    """
    Point d'entrée pour cron/systemd timer

    Usage:
    - Cron: 0 * * * * python services/monitoring/emailengine_health.py
    - Systemd timer: emailengine-health.timer (1 hour interval)
    """
    import os

    monitor = EmailEngineHealthMonitor(
        emailengine_url=os.getenv("EMAILENGINE_URL", "http://emailengine:3000"),
        emailengine_token=os.getenv("EMAILENGINE_TOKEN"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
    )

    # Vérifier état comptes
    account_states = await monitor.check_accounts_health()

    # Vérifier webhook delivery
    webhook_ok = await monitor.check_webhook_delivery()

    # Exit code
    all_connected = all(state == "connected" for state in account_states.values())
    if all_connected and webhook_ok:
        logger.info("✅ All checks passed")
        return 0
    else:
        logger.warning("⚠️  Some checks failed")
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    exit_code = asyncio.run(main())
    exit(exit_code)
