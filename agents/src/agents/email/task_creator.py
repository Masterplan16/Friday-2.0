"""
Module de création de tâches depuis emails avec Trust Layer (Story 2.7)

AC2 : Création tâches dans core.tasks avec référence email
AC3 : Trust level propose + validation Telegram
"""

import json
import logging
from typing import List
from uuid import UUID

import asyncpg
from agents.src.agents.email.models import TaskDetected
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action

logger = logging.getLogger(__name__)


@friday_action(module="email", action="extract_task", trust_default="propose")
async def create_tasks_with_validation(
    tasks: List[TaskDetected],
    email_id: str,
    email_subject: str,
    db_pool: asyncpg.Pool,
    bot=None,  # M5 fix: Bot pour notifications (optionnel pour tests)
    **kwargs,  # Accept decorator-injected args (_correction_rules, _rules_prompt)
) -> ActionResult:
    """
    Créer tâches depuis email avec validation Trust Layer

    AC3 : Trust level = propose → Validation Telegram requise Day 1

    Args:
        tasks: Liste tâches détectées (confidence >=0.7)
        email_id: UUID email source (ingestion.emails_raw.id)
        email_subject: Sujet email (sera anonymisé)
        db_pool: Pool connexion PostgreSQL

    Returns:
        ActionResult avec receipt pour validation Telegram

    Notes:
        - Decorator @friday_action crée automatiquement receipt
        - Status receipt = 'pending' → Attend validation Mainteneur
        - Notifications Telegram envoyées automatiquement par middleware
        - Après validation approve → Tâches conservées
        - Après validation reject → Tâches supprimées (status='cancelled')
    """
    from agents.src.tools.anonymize import anonymize_text

    # =========================================================================
    # ÉTAPE 1 : ANONYMISER SUJET EMAIL (RGPD)
    # =========================================================================

    subject_result = await anonymize_text(email_subject, language="fr")
    subject_anon = subject_result.anonymized_text

    # =========================================================================
    # ÉTAPE 2 : CRÉER TÂCHES DANS core.tasks
    # =========================================================================

    task_ids_created = []
    priority_map = {"high": 3, "normal": 2, "low": 1}

    async with db_pool.acquire() as conn:
        for task in tasks:
            # Convertir priorité texte → INT
            priority_int = priority_map.get(task.priority, 2)

            # Insérer tâche
            task_id = await conn.fetchval(
                """
                INSERT INTO core.tasks (
                    name, type, status, priority, due_date, payload
                ) VALUES (
                    $1, 'email_task', 'pending', $2, $3, $4
                ) RETURNING id
                """,
                task.description[:255],  # Max 255 chars
                priority_int,
                task.due_date,
                json.dumps(
                    {
                        "email_id": email_id,
                        "email_subject": subject_anon,
                        "confidence": task.confidence,
                        "context": task.context,
                        "priority_keywords": task.priority_keywords or [],
                    }
                ),
            )

            task_ids_created.append(str(task_id))

            logger.info(
                "task_created_from_email",
                task_id=str(task_id),
                email_id=email_id,
                description=task.description,
                priority=task.priority,
                confidence=task.confidence,
            )

        # =========================================================================
        # ÉTAPE 3 : RÉFÉRENCE BIDIRECTIONNELLE email → task_ids (H1 fix: validation)
        # =========================================================================

        # H1 fix: Vérifier que email existe avant UPDATE
        email_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM ingestion.emails_raw WHERE id = $1)", UUID(email_id)
        )

        if not email_exists:
            logger.error(
                "email_not_found_for_task_reference", email_id=email_id, task_ids=task_ids_created
            )
            raise ValueError(f"Email {email_id} not found in ingestion.emails_raw")

        # UPDATE référence bidirectionnelle
        await conn.execute(
            """
            UPDATE ingestion.emails_raw
            SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb),
                '{task_ids}',
                COALESCE(metadata->'task_ids', '[]'::jsonb) || $1::jsonb
            )
            WHERE id = $2
            """,
            json.dumps(task_ids_created),
            UUID(email_id),
        )

    # =========================================================================
    # ÉTAPE 4 : RETOURNER ActionResult POUR TRUST LAYER
    # =========================================================================

    # Calculer confidence moyenne
    confidence_avg = sum(t.confidence for t in tasks) / len(tasks) if tasks else 0.0

    # Résumé des tâches pour notification
    tasks_summary = [
        f"{task.description} (priorité: {task.priority}, confiance: {int(task.confidence * 100)}%)"
        for task in tasks
    ]

    action_result = ActionResult(
        input_summary=f"Email de [SENDER_ANON]: {subject_anon}",
        output_summary=f"{len(tasks)} tâche(s) détectée(s): {', '.join(t.description[:50] for t in tasks)}",
        confidence=confidence_avg,
        reasoning=f"Tâches implicites détectées. Confidence moyenne: {int(confidence_avg * 100)}%",
        payload={
            "task_ids": task_ids_created,
            "email_id": email_id,
            "tasks_detected": [
                {
                    "description": t.description,
                    "priority": t.priority,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                    "confidence": t.confidence,
                    "context": t.context,
                }
                for t in tasks
            ],
        },
    )

    # =========================================================================
    # ÉTAPE 5 : NOTIFICATIONS TELEGRAM (M5 fix: AC3 + AC4)
    # =========================================================================

    # M5 fix: Envoyer notifications dual-topic si bot fourni
    # Note: Receipt créé automatiquement par @friday_action, on doit le récupérer
    if bot:
        try:
            # Récupérer le receipt_id du dernier receipt créé pour cette action
            # (le middleware @friday_action l'a créé juste avant de retourner)
            async with db_pool.acquire() as conn:
                receipt_id = await conn.fetchval("""
                    SELECT id FROM core.action_receipts
                    WHERE module = 'email' AND action_type = 'extract_task'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """)

            if receipt_id:
                from bot.handlers.email_task_notifications import (
                    send_email_task_summary_notification,
                    send_task_detected_notification,
                )

                # Notification topic Actions (AC3)
                await send_task_detected_notification(
                    bot=bot,
                    receipt_id=str(receipt_id),
                    tasks=tasks,
                    sender_anon="[SENDER_ANON]",  # Déjà anonymisé upstream
                    subject_anon=subject_anon,
                )

                # Notification topic Email (AC4)
                await send_email_task_summary_notification(
                    bot=bot,
                    receipt_id=str(receipt_id),
                    tasks_count=len(tasks),
                    sender_anon="[SENDER_ANON]",
                    subject_anon=subject_anon,
                )

                logger.info(
                    "task_notifications_sent", receipt_id=str(receipt_id), tasks_count=len(tasks)
                )
            else:
                logger.warning("receipt_not_found_for_notifications", email_id=email_id)

        except Exception as e:
            logger.error(
                "task_notifications_failed", email_id=email_id, error=str(e), exc_info=True
            )
            # Ne pas bloquer la création des tâches si notifications échouent

    return action_result
