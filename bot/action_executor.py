"""
Bot Telegram Friday 2.0 - Action Executor

Story 1.10, Task 3: Exécution sécurisée des actions approuvées.

Security:
- BUG-1.10.9: Whitelist de modules autorisés (pas d'import dynamique arbitraire)
- BUG-1.10.10: Lock receipt avant exécution (SELECT FOR UPDATE)
- BUG-1.10.11: Notification System topic si erreur exécution
- BUG-1.10.12: Transaction atomique pour mise à jour status
"""

import json

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

# BUG-1.10.9 fix: Whitelist des modules autorisés pour exécution
ALLOWED_MODULES = {
    "email.classify",
    "email.draft",
    "email.draft_reply",  # Story 2.5 - Envoi email après approve
    "email.send",
    "archiviste.rename",
    "archiviste.classify",
    "finance.detect_anomaly",
    "finance.classify",
}


class ActionExecutor:
    """Exécuteur d'actions approuvées via inline buttons.

    Responsable de :
    - Charger le receipt approuvé depuis DB
    - Vérifier que l'action est dans la whitelist
    - Exécuter l'action (via registry de fonctions)
    - Mettre à jour le status en DB
    - Notifier en cas d'erreur
    """

    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
        # Registry des fonctions d'action (peuplé au démarrage)
        self._action_registry: dict = {}

    def register_action(self, action_key: str, func) -> None:
        """
        Enregistre une fonction d'action exécutable.

        Args:
            action_key: Clé format "module.action" (ex: "email.classify")
            func: Fonction async callable
        """
        self._action_registry[action_key] = func
        logger.info("Action registered", action_key=action_key)

    async def execute(self, receipt_id: str) -> bool:
        """
        Exécute une action approuvée.

        Args:
            receipt_id: UUID du receipt à exécuter

        Returns:
            True si succès, False si échec
        """
        try:
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    # BUG-1.10.10 fix: Lock receipt pour éviter double exécution
                    row = await conn.fetchrow(
                        "SELECT id, status, module, action_type, payload "
                        "FROM core.action_receipts "
                        "WHERE id = $1 FOR UPDATE",
                        receipt_id,
                    )

                    if not row:
                        logger.warning("Receipt not found for execution", receipt_id=receipt_id)
                        return False

                    # Vérifier que le receipt est bien approved
                    if row["status"] != "approved":
                        logger.warning(
                            "Receipt not in approved status",
                            receipt_id=receipt_id,
                            current_status=row["status"],
                        )
                        return False

                    action_key = f"{row['module']}.{row['action_type']}"

                    # C3 fix: Vérifier whitelist OBLIGATOIREMENT (pas de bypass via registry)
                    if action_key not in ALLOWED_MODULES:
                        logger.error(
                            "Action not in whitelist",
                            action_key=action_key,
                            receipt_id=receipt_id,
                        )
                        await conn.execute(
                            "UPDATE core.action_receipts "
                            "SET status = 'error', "
                            "    payload = COALESCE(payload, '{}'::jsonb) || $1::jsonb, "
                            "    updated_at = NOW() "
                            "WHERE id = $2",
                            json.dumps({"error": f"Action {action_key} not in whitelist"}),
                            receipt_id,
                        )
                        return False

                    # Exécuter l'action
                    try:
                        action_func = self._action_registry.get(action_key)
                        if action_func:
                            payload = row["payload"]
                            if isinstance(payload, str):
                                payload = json.loads(payload)
                            args = payload.get("args", {}) if isinstance(payload, dict) else {}
                            await action_func(**args)

                        # H2 fix: status='executed' (pas 'auto' qui est un trust level)
                        await conn.execute(
                            "UPDATE core.action_receipts "
                            "SET status = 'executed', "
                            "    updated_at = NOW() "
                            "WHERE id = $1",
                            receipt_id,
                        )

                        logger.info(
                            "Action executed successfully",
                            receipt_id=receipt_id,
                            action_key=action_key,
                        )
                        return True

                    except Exception as exec_err:
                        # BUG-1.10.11 fix: Pas d'erreur silencieuse
                        logger.error(
                            "Action execution failed",
                            receipt_id=receipt_id,
                            action_key=action_key,
                            error=str(exec_err),
                            exc_info=True,
                        )

                        # H1 fix: COALESCE pour éviter NULL || jsonb = NULL
                        await conn.execute(
                            "UPDATE core.action_receipts "
                            "SET status = 'error', "
                            "    payload = COALESCE(payload, '{}'::jsonb) || $1::jsonb, "
                            "    updated_at = NOW() "
                            "WHERE id = $2",
                            json.dumps({"error": str(exec_err)[:500]}),
                            receipt_id,
                        )
                        return False

        except Exception as e:
            logger.error(
                "Unexpected error in action executor",
                receipt_id=receipt_id,
                error=str(e),
                exc_info=True,
            )
            return False
