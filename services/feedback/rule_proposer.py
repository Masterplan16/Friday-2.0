"""
Rule Proposer pour Friday 2.0 (Story 1.7, AC4).

Propose automatiquement des correction_rules depuis les patterns détectés.
Envoie notifications Telegram avec inline buttons [Créer règle] [Modifier] [Ignorer].
"""

import os
import uuid
from typing import Any

import asyncpg
import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from services.feedback.pattern_detector import PatternCluster

logger = structlog.get_logger(__name__)


class RuleProposer:
    """
    Propose des correction_rules depuis patterns détectés.

    Workflow:
    1. Reçoit PatternCluster depuis PatternDetector
    2. Formate en JSONB conditions + output
    3. Envoie message Telegram avec inline buttons
    4. Handler callback crée règle dans core.correction_rules
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        telegram_bot: Bot | None = None,
        telegram_topic_id: int | None = None,
    ):
        """
        Initialise le RuleProposer.

        Args:
            db_pool: Pool connexions PostgreSQL
            telegram_bot: Instance Bot Telegram (optionnel, chargé depuis env si None)
            telegram_topic_id: ID topic "Actions & Validations" (optionnel)
        """
        self.db_pool = db_pool
        self.telegram_bot = telegram_bot or self._init_telegram_bot()

        # HIGH-4 fix: Raise explicit error si envvars manquantes (pas fallback "0" dangereux)
        topic_id_str = os.getenv("TOPIC_ACTIONS_ID")
        if not topic_id_str:
            raise ValueError(
                "TOPIC_ACTIONS_ID envvar manquante - requis pour propositions règles Telegram"
            )
        self.telegram_topic_id = int(topic_id_str)

        supergroup_id_str = os.getenv("TELEGRAM_SUPERGROUP_ID")
        if not supergroup_id_str:
            raise ValueError(
                "TELEGRAM_SUPERGROUP_ID envvar manquante - requis pour envoi Telegram"
            )
        self.telegram_supergroup_id = int(supergroup_id_str)

    def _init_telegram_bot(self) -> Bot | None:
        """
        Initialise Bot Telegram depuis variables d'environnement.

        Returns:
            Instance Bot ou None si TOKEN manquant
        """
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN not set, Telegram proposals disabled")
            return None
        return Bot(token=token)

    def format_rule_proposal(self, cluster: PatternCluster) -> dict[str, Any]:
        """
        Formate un PatternCluster en proposition de règle (conditions + output).

        Args:
            cluster: Cluster détecté par PatternDetector

        Returns:
            Dict avec rule_name, conditions (JSONB), output (JSONB), scope, priority
        """
        # Générer nom de règle unique
        rule_name = (
            f"pattern_{cluster.module}_{cluster.action_type}_"
            f"{uuid.uuid4().hex[:8]}"
        )

        # Conditions : mots-clés récurrents
        conditions = {
            "keywords": cluster.common_keywords,
            "min_match": 1,  # Au moins 1 keyword doit matcher
        }

        # Output : catégorie cible si détectée
        output: dict[str, Any] = {}
        if cluster.target_category:
            output["category"] = cluster.target_category
            output["confidence_boost"] = 0.1  # Boost confidence si règle match

        # Scope : specific (module + action_type)
        scope = "specific"

        # Priority : 50 (milieu échelle 1-100)
        priority = 50

        return {
            "rule_name": rule_name,
            "module": cluster.module,
            "action_type": cluster.action_type,
            "conditions": conditions,
            "output": output,
            "scope": scope,
            "priority": priority,
            "source_receipts": [str(rid) for rid in cluster.receipt_ids],
        }

    async def send_telegram_proposal(
        self, cluster: PatternCluster, rule_proposal: dict[str, Any]
    ) -> str | None:
        """
        Envoie proposition de règle via Telegram avec inline buttons (AC4).

        Args:
            cluster: Cluster détecté
            rule_proposal: Règle formatée depuis format_rule_proposal()

        Returns:
            Message ID Telegram ou None si échec
        """
        if not self.telegram_bot:
            logger.warning(
                "Telegram bot not configured, cannot send proposal for %s.%s",
                cluster.module,
                cluster.action_type,
            )
            return None

        if not self.telegram_supergroup_id or not self.telegram_topic_id:
            logger.error(
                "Telegram supergroup_id or topic_id not configured, cannot send proposal"
            )
            return None

        # Préparer message de proposition
        message_text = (
            f"📋 **PATTERN DÉTECTÉ**\n\n"
            f"**Module** : `{cluster.module}.{cluster.action_type}`\n"
            f"**Corrections** : {len(cluster.corrections)} similaires\n"
            f"**Similarité** : {cluster.similarity_score:.0%}\n\n"
            f"**Pattern extrait** :\n"
            f"• Mots-clés : {', '.join(cluster.common_keywords[:5])}\n"
            f"• Catégorie cible : `{cluster.target_category or 'N/A'}`\n\n"
            f"**Exemples** :\n"
        )

        # Ajouter 3 premiers exemples
        for i, correction in enumerate(cluster.corrections[:3], 1):
            message_text += f"{i}. `{correction}`\n"

        message_text += (
            f"\n**Règle proposée** :\n"
            f"SI {rule_proposal['conditions']} ALORS {rule_proposal['output']}\n\n"
            f"Que veux-tu faire ?"
        )

        # Créer inline buttons [Créer règle] [Modifier] [Ignorer]
        # On encode rule_proposal en tant que cluster_id temporaire
        cluster_id = str(uuid.uuid4())  # ID temporaire pour tracking
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Créer règle", callback_data=f"create_rule_{cluster_id}"
                ),
                InlineKeyboardButton(
                    "✏️ Modifier", callback_data=f"modify_rule_{cluster_id}"
                ),
                InlineKeyboardButton(
                    "❌ Ignorer", callback_data=f"ignore_pattern_{cluster_id}"
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            # Envoyer message au topic "Actions & Validations"
            message = await self.telegram_bot.send_message(
                chat_id=self.telegram_supergroup_id,
                message_thread_id=self.telegram_topic_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )

            # Stocker rule_proposal en cache (Redis ou mémoire) pour callback handler
            # TODO: Implémenter cache Redis pour rule_proposals
            # await self.cache_rule_proposal(cluster_id, rule_proposal)

            logger.info(
                "Rule proposal sent to Telegram",
                cluster_id=cluster_id,
                module=cluster.module,
                action_type=cluster.action_type,
                message_id=message.message_id,
            )
            return str(message.message_id)

        except Exception as e:
            logger.error(
                "Failed to send Telegram proposal for %s.%s: %s",
                cluster.module,
                cluster.action_type,
                e,
                exc_info=True,
            )
            return None

    async def create_rule_from_proposal(
        self, rule_proposal: dict[str, Any], created_by: str = "auto-detected"
    ) -> str:
        """
        Crée une correction_rule depuis une proposition (AC4).

        Appelé par callback handler Telegram après validation Antonio.

        Args:
            rule_proposal: Règle formatée depuis format_rule_proposal()
            created_by: Créateur de la règle (défaut: "auto-detected")

        Returns:
            UUID de la règle créée
        """
        query = """
            INSERT INTO core.correction_rules (
                module, action_type, rule_name, conditions, output,
                scope, priority, source_receipts, active, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
        """

        async with self.db_pool.acquire() as conn:
            rule_id = await conn.fetchval(
                query,
                rule_proposal["module"],
                rule_proposal["action_type"],
                rule_proposal["rule_name"],
                rule_proposal["conditions"],  # JSONB
                rule_proposal["output"],  # JSONB
                rule_proposal["scope"],
                rule_proposal["priority"],
                rule_proposal["source_receipts"],  # UUID[]
                True,  # active
                created_by,
            )

        logger.info(
            "Correction rule created",
            rule_id=str(rule_id),
            rule_name=rule_proposal["rule_name"],
            module=rule_proposal["module"],
            action_type=rule_proposal["action_type"],
        )
        return str(rule_id)

    async def propose_rules_from_patterns(
        self, patterns: list[PatternCluster]
    ) -> list[str]:
        """
        Pipeline complet : propose rules depuis patterns détectés (AC4).

        Workflow:
        1. Pour chaque PatternCluster
        2. Formater en rule_proposal
        3. Envoyer message Telegram avec inline buttons
        4. Retourner liste message_ids

        Args:
            patterns: Liste de PatternCluster depuis PatternDetector

        Returns:
            Liste de message_ids Telegram envoyés
        """
        message_ids: list[str] = []

        for pattern in patterns:
            # Formater règle
            rule_proposal = self.format_rule_proposal(pattern)

            # Envoyer proposition Telegram
            message_id = await self.send_telegram_proposal(pattern, rule_proposal)

            if message_id:
                message_ids.append(message_id)

        logger.info(
            "Rule proposals completed",
            patterns_count=len(patterns),
            proposals_sent=len(message_ids),
        )

        return message_ids
