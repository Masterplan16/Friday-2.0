"""
Middleware Trust Layer pour Friday 2.0.

Ce module implémente le décorateur @friday_action qui :
1. Charge les correction_rules du module
2. Injecte les règles dans le contexte de l'action
3. Exécute l'action avec observabilité complète
4. Crée un receipt dans core.action_receipts
5. Applique le trust level (auto/propose/blocked)
"""

import functools
import logging
import os
import time
from typing import Any, Callable, Optional

import asyncpg
import yaml
from agents.src.middleware.models import ActionResult, CorrectionRule
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


class TrustManager:
    """
    Gestionnaire du Trust Layer.

    Responsable de :
    - Charger les trust levels depuis config/trust_levels.yaml
    - Charger les correction_rules depuis PostgreSQL
    - Créer des receipts dans core.action_receipts
    - Gérer les validations Telegram pour trust=propose
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        telegram_bot: Optional[Bot] = None,
        telegram_topic_id: Optional[int] = None,
    ):
        """
        Initialise le TrustManager.

        Args:
            db_pool: Pool de connexions PostgreSQL (asyncpg)
            telegram_bot: Instance Bot Telegram (optionnel, chargé depuis env si None)
            telegram_topic_id: ID du topic Telegram "Actions & Validations" (optionnel)
        """
        self.db_pool = db_pool
        self.trust_levels: dict[str, dict[str, str]] = {}
        self._loaded = False

        # Telegram configuration (Story 1.7 - inline buttons validation)
        self.telegram_bot = telegram_bot or self._init_telegram_bot()
        self.telegram_topic_id = telegram_topic_id or int(os.getenv("TOPIC_ACTIONS_ID", "0"))
        self.telegram_supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID", "0"))

    def _init_telegram_bot(self) -> Optional[Bot]:
        """
        Initialise le Bot Telegram depuis variables d'environnement.

        Returns:
            Instance Bot ou None si TOKEN manquant
        """
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN not set, Telegram validation disabled")
            return None
        return Bot(token=token)

    async def load_trust_levels(self, config_path: str = "config/trust_levels.yaml") -> None:
        """
        Charge les trust levels depuis le fichier YAML.

        Args:
            config_path: Chemin vers trust_levels.yaml
        """
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                self.trust_levels = config.get("modules", {})
                self._loaded = True
                logger.info("Trust levels loaded for %d modules", len(self.trust_levels))
        except FileNotFoundError:
            logger.error("Trust levels config not found: %s", config_path)
            raise
        except yaml.YAMLError as e:
            logger.error("Failed to parse trust levels YAML: %s", e)
            raise

    def get_trust_level(self, module: str, action: str) -> str:
        """
        Récupère le trust level actuel pour un module/action.

        Args:
            module: Nom du module (ex: 'email')
            action: Nom de l'action (ex: 'classify')

        Returns:
            Trust level : 'auto', 'propose', ou 'blocked'

        Raises:
            ValueError: Si module/action inconnu
        """
        if not self._loaded:
            raise RuntimeError("Trust levels not loaded. Call load_trust_levels() first.")

        if module not in self.trust_levels:
            raise ValueError(f"Unknown module: {module}")

        module_config = self.trust_levels[module]
        if action not in module_config:
            raise ValueError(f"Unknown action '{action}' for module '{module}'")

        return module_config[action]

    async def load_correction_rules(
        self, module: str, action: Optional[str] = None
    ) -> list[CorrectionRule]:
        """
        Charge les correction_rules actives pour un module/action depuis PostgreSQL.

        Args:
            module: Nom du module
            action: Nom de l'action (None = toutes les actions du module)

        Returns:
            Liste des CorrectionRule triées par priorité (1=max priorité)
        """
        query = """
            SELECT id, module, action_type, scope, priority, conditions, output,
                   source_receipts, hit_count, active, created_at, created_by
            FROM core.correction_rules
            WHERE module = $1
              AND active = true
              AND (action_type = $2 OR action_type IS NULL)
            ORDER BY priority ASC
            LIMIT 50
        """

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, module, action)

        rules = [
            CorrectionRule(
                id=row["id"],
                module=row["module"],
                action_type=row["action_type"],
                scope=row["scope"],
                priority=row["priority"],
                conditions=row["conditions"],
                output=row["output"],
                source_receipts=row["source_receipts"] or [],
                hit_count=row["hit_count"],
                active=row["active"],
                created_at=row["created_at"],
                created_by=row["created_by"],
            )
            for row in rows
        ]

        logger.info("Loaded %d correction rules for %s.%s", len(rules), module, action)
        return rules

    def format_rules_for_prompt(self, rules: list[CorrectionRule]) -> str:
        """
        Formate les règles de correction pour injection dans un prompt LLM.

        Args:
            rules: Liste de CorrectionRule

        Returns:
            String formatée pour le prompt (vide si aucune règle)
        """
        if not rules:
            return ""

        formatted = "RÈGLES DE CORRECTION PRIORITAIRES (à appliquer strictement) :\n\n"
        for rule in rules:
            formatted += f"- {rule.format_for_prompt()}\n"

        return formatted

    async def create_receipt(self, result: ActionResult) -> str:
        """
        Crée un receipt dans core.action_receipts.

        Args:
            result: ActionResult de l'action exécutée

        Returns:
            ID du receipt créé (UUID string)
        """
        query = """
            INSERT INTO core.action_receipts (
                id, module, action_type, input_summary, output_summary,
                confidence, reasoning, payload, duration_ms, trust_level, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
        """

        receipt_data = result.model_dump_receipt()

        async with self.db_pool.acquire() as conn:
            receipt_id = await conn.fetchval(
                query,
                receipt_data["id"],
                receipt_data["module"],
                receipt_data["action_type"],
                receipt_data["input_summary"],
                receipt_data["output_summary"],
                receipt_data["confidence"],
                receipt_data["reasoning"],
                receipt_data["payload"],
                receipt_data["duration_ms"],
                receipt_data["trust_level"],
                receipt_data["status"],
            )

        logger.info("Receipt created: %s (%s.%s)", receipt_id, result.module, result.action_type)
        return str(receipt_id)

    async def send_telegram_validation(self, result: ActionResult) -> str:
        """
        Envoie une demande de validation Telegram avec inline buttons (AC1, Task 2.2).

        Envoie un message au topic "Actions & Validations" avec 3 inline buttons :
        - [✅ Approve] : Approuver l'action
        - [❌ Reject] : Rejeter l'action
        - [📝 Correct] : Corriger l'action (saisie texte)

        Args:
            result: ActionResult en attente de validation (trust=propose)

        Returns:
            Message ID Telegram pour tracking (ou "PENDING_TELEGRAM" si bot indisponible)
        """
        if not self.telegram_bot:
            logger.warning(
                "Telegram bot not configured, cannot send validation for %s.%s",
                result.module,
                result.action_type,
            )
            return "PENDING_TELEGRAM"

        if not self.telegram_supergroup_id or not self.telegram_topic_id:
            logger.error(
                "Telegram supergroup_id or topic_id not configured, cannot send validation"
            )
            return "PENDING_TELEGRAM"

        # Préparer le message de validation
        message_text = (
            f"🤖 **Action en attente de validation**\n\n"
            f"**Module** : `{result.module}`\n"
            f"**Action** : `{result.action_type}`\n"
            f"**Confidence** : {result.confidence:.2f}\n\n"
            f"**Input** : {result.input_summary}\n"
            f"**Output** : {result.output_summary}\n\n"
            f"**Reasoning** : {result.reasoning[:200]}...\n\n"
            f"Que veux-tu faire ?"
        )

        # Créer inline buttons [Approve] [Reject] [Correct]
        receipt_id = result.payload.get("receipt_id", result.action_id)
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{receipt_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{receipt_id}"),
                InlineKeyboardButton("📝 Correct", callback_data=f"correct_{receipt_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            # Envoyer le message au topic "Actions & Validations"
            message = await self.telegram_bot.send_message(
                chat_id=self.telegram_supergroup_id,
                message_thread_id=self.telegram_topic_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )

            logger.info(
                "Telegram validation sent for %s.%s (receipt=%s, message_id=%d)",
                result.module,
                result.action_type,
                receipt_id,
                message.message_id,
            )
            return str(message.message_id)

        except Exception as e:
            logger.error(
                "Failed to send Telegram validation for %s.%s: %s",
                result.module,
                result.action_type,
                e,
                exc_info=True,
            )
            return "PENDING_TELEGRAM"


# Instance globale (initialisée au démarrage de l'app)
_trust_manager: Optional[TrustManager] = None


def init_trust_manager(
    db_pool: asyncpg.Pool,
    telegram_bot: Optional[Bot] = None,
    telegram_topic_id: Optional[int] = None,
) -> TrustManager:
    """
    Initialise le TrustManager global.

    À appeler au démarrage de l'application (après init DB).

    Args:
        db_pool: Pool de connexions PostgreSQL
        telegram_bot: Instance Bot Telegram (optionnel)
        telegram_topic_id: ID du topic "Actions & Validations" (optionnel)

    Returns:
        Instance TrustManager initialisée
    """
    global _trust_manager
    _trust_manager = TrustManager(db_pool, telegram_bot, telegram_topic_id)
    return _trust_manager


def get_trust_manager() -> TrustManager:
    """
    Récupère l'instance globale du TrustManager.

    Returns:
        Instance TrustManager

    Raises:
        RuntimeError: Si TrustManager pas encore initialisé
    """
    if _trust_manager is None:
        raise RuntimeError("TrustManager not initialized. Call init_trust_manager() first.")
    return _trust_manager


def friday_action(
    module: str,
    action: str,
    trust_default: Optional[str] = None,
) -> Callable:
    """
    Décorateur pour observer et contrôler les actions des modules Friday.

    Usage:
        @friday_action(module="email", action="classify", trust_default="propose")
        async def classify_email(email: Email) -> ActionResult:
            # ... logique de classification ...
            return ActionResult(...)

    Args:
        module: Nom du module (ex: 'email', 'archiviste')
        action: Nom de l'action (ex: 'classify', 'draft')
        trust_default: Trust level par défaut si absent de trust_levels.yaml (optionnel)

    Returns:
        Décorateur de fonction
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> ActionResult:
            trust_manager = get_trust_manager()
            start_time = time.time()

            # 1. Charger le trust level actuel
            try:
                trust_level = trust_manager.get_trust_level(module, action)
            except (ValueError, RuntimeError) as e:
                if trust_default:
                    logger.warning(
                        "Using default trust level '%s' for %s.%s: %s",
                        trust_default,
                        module,
                        action,
                        e,
                    )
                    trust_level = trust_default
                else:
                    raise

            # 2. Charger les correction_rules actives
            rules = await trust_manager.load_correction_rules(module, action)
            rules_prompt = trust_manager.format_rules_for_prompt(rules)

            # 3. Injecter les règles dans le contexte (kwargs)
            kwargs["_correction_rules"] = rules
            kwargs["_rules_prompt"] = rules_prompt

            # 4. Exécuter l'action
            try:
                result = await func(*args, **kwargs)
                # Assigner module et action_type (remplis par décorateur)
                result.module = module
                result.action_type = action
            except Exception as e:
                # En cas d'erreur, créer un ActionResult d'erreur
                duration_ms = int((time.time() - start_time) * 1000)
                result = ActionResult(
                    module=module,
                    action_type=action,
                    input_summary=f"Args count: {len(args)}, Kwargs: {list(kwargs.keys())[:5]}",
                    output_summary=f"ERROR: {type(e).__name__}: {str(e)[:200]}",
                    confidence=0.0,
                    reasoning=f"Exception raised during execution: {str(e)}",
                    payload={"error_type": type(e).__name__, "error_message": str(e)},
                    duration_ms=duration_ms,
                    trust_level=trust_level,
                    status="rejected",  # Action failed due to exception
                )
                logger.error(
                    "Action %s.%s failed: %s",
                    module,
                    action,
                    e,
                    exc_info=True,
                )
                # On crée quand même un receipt pour traçabilité
                await trust_manager.create_receipt(result)
                raise

            # 5. Ajouter métadonnées de traçabilité
            duration_ms = int((time.time() - start_time) * 1000)
            result.duration_ms = duration_ms
            result.trust_level = trust_level

            # 6. Appliquer le trust level
            if trust_level == "auto":
                result.status = "auto"
                # Exécuté automatiquement, notifie après coup
                logger.info(
                    "Action %s.%s executed automatically (trust=auto, confidence=%.2f)",
                    module,
                    action,
                    result.confidence,
                )
            elif trust_level == "propose":
                result.status = "pending"
                # Attend validation Telegram
                logger.info(
                    "Action %s.%s requires validation (trust=propose)",
                    module,
                    action,
                )
                await trust_manager.send_telegram_validation(result)
            elif trust_level == "blocked":
                result.status = "blocked"
                # Analyse uniquement, jamais d'action
                logger.info(
                    "Action %s.%s blocked (trust=blocked, analysis only)",
                    module,
                    action,
                )
            else:
                raise ValueError(f"Invalid trust level: {trust_level}")

            # 7. Créer receipt dans core.action_receipts
            receipt_id = await trust_manager.create_receipt(result)
            result.payload["receipt_id"] = receipt_id

            return result

        return wrapper

    return decorator
