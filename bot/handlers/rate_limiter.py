"""
Rate limiter simple pour commandes Telegram (Story 2.3 Code Review Fix M1).

Protection DoS basique basée sur timestamp + cache mémoire.
"""

import time
from collections import defaultdict
from typing import Dict

import structlog

logger = structlog.get_logger(__name__)


class SimpleRateLimiter:
    """
    Rate limiter basique en mémoire pour commandes Telegram.

    Limite : N commandes par fenêtre de T secondes par user_id.
    Stockage : defaultdict en mémoire (reset au redémarrage bot).
    """

    def __init__(self, max_calls: int = 10, window_seconds: int = 60):
        """
        Initialise le rate limiter.

        Args:
            max_calls: Nombre max d'appels autorisés dans la fenêtre
            window_seconds: Durée de la fenêtre en secondes
        """
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        # Structure : {(user_id, command): [(timestamp1, timestamp2, ...)]}
        self.call_history: Dict[tuple, list] = defaultdict(list)

    def is_allowed(self, user_id: int, command: str) -> tuple[bool, int]:
        """
        Vérifie si l'utilisateur peut exécuter la commande.

        Args:
            user_id: ID Telegram utilisateur
            command: Nom de la commande (ex: "vip_add")

        Returns:
            (allowed: bool, retry_after: int)
            - allowed: True si autorisé, False si rate limited
            - retry_after: Secondes à attendre si rate limited (0 si allowed)
        """
        key = (user_id, command)
        now = time.time()

        # Nettoyer les appels en dehors de la fenêtre
        self.call_history[key] = [
            ts for ts in self.call_history[key] if now - ts < self.window_seconds
        ]

        # Vérifier si limite atteinte
        if len(self.call_history[key]) >= self.max_calls:
            # Rate limited
            oldest_call = min(self.call_history[key])
            retry_after = int(self.window_seconds - (now - oldest_call)) + 1

            logger.warning(
                "rate_limit_exceeded",
                user_id=user_id,
                command=command,
                calls_count=len(self.call_history[key]),
                max_calls=self.max_calls,
                retry_after=retry_after,
            )

            return False, retry_after

        # Autorisé : enregistrer l'appel
        self.call_history[key].append(now)

        logger.debug(
            "rate_limit_check_passed",
            user_id=user_id,
            command=command,
            calls_count=len(self.call_history[key]),
            max_calls=self.max_calls,
        )

        return True, 0

    def reset_user(self, user_id: int, command: str | None = None) -> None:
        """
        Reset le rate limit pour un utilisateur.

        Args:
            user_id: ID utilisateur
            command: Commande spécifique (None = reset toutes commandes)
        """
        if command:
            key = (user_id, command)
            if key in self.call_history:
                del self.call_history[key]
                logger.info("rate_limit_reset", user_id=user_id, command=command)
        else:
            # Reset toutes les commandes pour cet user
            keys_to_delete = [k for k in self.call_history.keys() if k[0] == user_id]
            for key in keys_to_delete:
                del self.call_history[key]
            logger.info("rate_limit_reset_all", user_id=user_id, commands_count=len(keys_to_delete))


# Instance globale (singleton) pour partage entre handlers
# Note : Stockage en mémoire = reset au redémarrage bot
# Pour production : envisager Redis avec TTL si nécessaire
vip_rate_limiter = SimpleRateLimiter(max_calls=10, window_seconds=60)  # 10 /vip par minute
