"""
Service de calcul de métriques nightly pour Friday 2.0.

Exécute chaque nuit (3h du matin) :
1. Agrégation des action_receipts de la semaine
2. Calcul de l'accuracy par module/action
3. Détection des rétrogradations nécessaires (accuracy <90%)
4. Stockage dans core.trust_metrics
5. Alertes Telegram si rétrogradation détectée
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import asyncpg
import redis.asyncio as aioredis
import schedule
import structlog

from services.feedback.pattern_detector import PatternDetector
from services.feedback.rule_proposer import RuleProposer

# Configuration structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

logger = structlog.get_logger()


class MetricsAggregator:
    """Agrégateur de métriques trust hebdomadaires."""

    def __init__(self):
        """Initialise l'agrégateur de métriques."""
        self.db_url = os.getenv(
            "DATABASE_URL",
            "postgresql://friday:friday_dev_password@localhost:5432/friday",
        )
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.db_pool: asyncpg.Pool | None = None
        self.redis_client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Connecte à PostgreSQL et Redis."""
        self.db_pool = await asyncpg.create_pool(self.db_url)
        self.redis_client = await aioredis.from_url(
            self.redis_url, decode_responses=True
        )
        logger.info("Connected to PostgreSQL and Redis")

    async def disconnect(self) -> None:
        """Déconnecte proprement."""
        if self.db_pool:
            await self.db_pool.close()
        if self.redis_client:
            await self.redis_client.close()
        logger.info("Disconnected from PostgreSQL and Redis")

    async def aggregate_weekly_metrics(self) -> list[dict[str, Any]]:
        """
        Agrège les métriques de la semaine en cours pour chaque module/action.

        Returns:
            Liste de métriques agrégées
        """
        if not self.db_pool:
            raise RuntimeError("Not connected to database")

        # Calculer le début de la semaine (lundi 00:00)
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday())
        week_start_dt = datetime.combine(week_start, datetime.min.time())

        query = """
            WITH weekly_actions AS (
                SELECT
                    module,
                    action_type,
                    COUNT(*) as total_actions,
                    COUNT(*) FILTER (WHERE status = 'corrected') as corrected_actions,
                    AVG(confidence) as avg_confidence
                FROM core.action_receipts
                WHERE created_at >= $1
                  AND status != 'blocked'
                GROUP BY module, action_type
            )
            SELECT
                module,
                action_type,
                total_actions,
                corrected_actions,
                CASE
                    WHEN total_actions > 0 THEN 1.0 - (corrected_actions::float / total_actions)
                    ELSE 1.0
                END as accuracy,
                COALESCE(avg_confidence, 0.0) as avg_confidence
            FROM weekly_actions
            WHERE total_actions >= 1
        """

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, week_start_dt)

        metrics = [
            {
                "module": row["module"],
                "action_type": row["action_type"],
                "week_start": week_start_dt,
                "total_actions": row["total_actions"],
                "corrected_actions": row["corrected_actions"],
                "accuracy": float(row["accuracy"]),
                "avg_confidence": float(row["avg_confidence"]),
            }
            for row in rows
        ]

        logger.info("Aggregated weekly metrics", metrics_count=len(metrics))
        return metrics

    async def load_current_trust_levels(self) -> dict[str, dict[str, str]]:
        """
        Charge les trust levels actuels depuis config/trust_levels.yaml.

        Returns:
            Dict {module: {action: trust_level}}
        """
        import yaml

        config_path = "config/trust_levels.yaml"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                trust_levels = config.get("modules", {})
                logger.info("Loaded trust levels", modules_count=len(trust_levels))
                return trust_levels
        except FileNotFoundError:
            logger.error("Trust levels config not found", path=config_path)
            return {}

    async def save_metrics(self, metrics: list[dict[str, Any]]) -> None:
        """
        Sauvegarde les métriques dans core.trust_metrics.

        Args:
            metrics: Liste de métriques à sauvegarder
        """
        if not self.db_pool:
            raise RuntimeError("Not connected to database")

        # Charger trust levels actuels
        trust_levels = await self.load_current_trust_levels()

        query = """
            INSERT INTO core.trust_metrics (
                module, action_type, week_start, total_actions, corrected_actions,
                accuracy, avg_confidence, current_trust_level, recommended_trust_level
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (module, action_type, week_start)
            DO UPDATE SET
                total_actions = EXCLUDED.total_actions,
                corrected_actions = EXCLUDED.corrected_actions,
                accuracy = EXCLUDED.accuracy,
                avg_confidence = EXCLUDED.avg_confidence,
                current_trust_level = EXCLUDED.current_trust_level,
                recommended_trust_level = EXCLUDED.recommended_trust_level
        """

        async with self.db_pool.acquire() as conn:
            for metric in metrics:
                module = metric["module"]
                action_type = metric["action_type"]
                accuracy = metric["accuracy"]
                total = metric["total_actions"]

                # Déterminer trust level actuel
                current_trust = trust_levels.get(module, {}).get(action_type, "propose")

                # Calculer recommendation (rétrogradation si accuracy <90% et sample >=10)
                if total >= 10 and accuracy < 0.90 and current_trust == "auto":
                    recommended_trust = "propose"
                else:
                    recommended_trust = current_trust

                await conn.execute(
                    query,
                    module,
                    action_type,
                    metric["week_start"],
                    total,
                    metric["corrected_actions"],
                    accuracy,
                    metric["avg_confidence"],
                    current_trust,
                    recommended_trust,
                )

        logger.info("Metrics saved to database", count=len(metrics))

    async def detect_retrogradations(self, metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Détecte les rétrogradations nécessaires et envoie des alertes.

        Args:
            metrics: Liste de métriques

        Returns:
            Liste des rétrogradations détectées
        """
        trust_levels = await self.load_current_trust_levels()
        retrogradations = []

        for metric in metrics:
            module = metric["module"]
            action_type = metric["action_type"]
            accuracy = metric["accuracy"]
            total = metric["total_actions"]

            current_trust = trust_levels.get(module, {}).get(action_type, "propose")

            # Règle de rétrogradation : accuracy <90% sur 1 semaine + sample >=10
            if total >= 10 and accuracy < 0.90 and current_trust == "auto":
                retrogradations.append(
                    {
                        "module": module,
                        "action": action_type,
                        "accuracy": accuracy,
                        "total_actions": total,
                        "old_level": current_trust,
                        "new_level": "propose",
                    }
                )

        if retrogradations:
            logger.warning("Retrogradations detected", count=len(retrogradations))
            await self.send_retrogradation_alerts(retrogradations)

        return retrogradations

    async def send_retrogradation_alerts(self, retrogradations: list[dict[str, Any]]) -> None:
        """
        Envoie des alertes Redis pour les rétrogradations détectées.

        Args:
            retrogradations: Liste des rétrogradations
        """
        if not self.redis_client:
            raise RuntimeError("Not connected to Redis")

        for retro in retrogradations:
            event_data = {
                "module": retro["module"],
                "action": retro["action"],
                "old_level": retro["old_level"],
                "new_level": retro["new_level"],
                "accuracy": retro["accuracy"],
                "total_actions": retro["total_actions"],
                "reason": "accuracy < 90% on 1 week with sample >= 10",
            }

            await self.redis_client.xadd(
                "friday:events:trust.level.changed", event_data
            )

        logger.info("Retrogradation alerts sent", count=len(retrogradations))

    async def run_pattern_detection(self) -> None:
        """
        Exécute la détection de patterns et proposition de règles (Story 1.7, AC3, AC4).

        Workflow:
        1. PatternDetector détecte clusters de corrections similaires
        2. RuleProposer envoie propositions Telegram avec inline buttons

        Exécuté après metrics aggregation (03h15).
        """
        logger.info("Starting pattern detection")

        try:
            # 1. Détecter patterns
            detector = PatternDetector(db_pool=self.db_pool)
            patterns = await detector.detect_patterns(days=7)

            if not patterns:
                logger.info("No patterns detected, skipping rule proposals")
                return

            # 2. Proposer rules via Telegram
            proposer = RuleProposer(db_pool=self.db_pool)
            message_ids = await proposer.propose_rules_from_patterns(patterns)

            logger.info(
                "Pattern detection completed",
                patterns_detected=len(patterns),
                proposals_sent=len(message_ids),
            )

        except Exception as e:
            # MED-4 fix: Logging CRITICAL + alerte Redis pour Antonio
            logger.critical(
                "Pattern detection FAILED - feedback loop interrompu",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )

            # Envoyer alerte Redis Streams pour notification Antonio
            try:
                await self.redis_client.xadd(
                    "friday:events:nightly.pattern_detection.failed",
                    {
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "timestamp": datetime.utcnow().isoformat(),
                        "severity": "critical",
                    },
                )
            except Exception as redis_err:
                logger.error("Échec envoi alerte Redis", error=str(redis_err))

    async def run_nightly_aggregation(self) -> None:
        """Exécute l'agrégation nightly complète."""
        logger.info("Starting nightly metrics aggregation")

        try:
            # 1. Agréger métriques hebdomadaires
            metrics = await self.aggregate_weekly_metrics()

            # 2. Sauvegarder dans core.trust_metrics
            await self.save_metrics(metrics)

            # 3. Détecter rétrogradations
            retrogradations = await self.detect_retrogradations(metrics)

            # 4. Détecter patterns et proposer règles (Story 1.7, AC3, AC4)
            await self.run_pattern_detection()

            logger.info(
                "Nightly aggregation completed",
                metrics_count=len(metrics),
                retrogradations_count=len(retrogradations),
            )

        except Exception as e:
            logger.error("Nightly aggregation failed", error=str(e), exc_info=True)

    async def run_scheduler(self) -> None:
        """Lance le scheduler pour exécution quotidienne à 3h du matin."""
        await self.connect()

        # Programmer l'exécution quotidienne à 3h
        schedule.every().day.at("03:00").do(
            lambda: asyncio.create_task(self.run_nightly_aggregation())
        )

        logger.info("Metrics scheduler started (daily at 03:00 UTC)")

        # Boucle infinie
        while True:
            schedule.run_pending()
            await asyncio.sleep(60)  # Vérifier chaque minute


async def main() -> None:
    """Point d'entrée principal."""
    aggregator = MetricsAggregator()
    await aggregator.run_scheduler()


if __name__ == "__main__":
    asyncio.run(main())
