"""
Telegram commands for dedup scan & deletion (Story 3.8).

Commands:
- /scan_dedup : Start PC-wide scan for duplicates
- Inline buttons: [Voir rapport] [Lancer suppression] [Annuler]
- Callback handlers for confirmation workflow

AC4: Telegram notifications with inline buttons
AC5: Validation suppression avec previsualisation
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

# Report directory
REPORTS_DIR = Path(os.getenv("DEDUP_REPORTS_DIR", r"C:\Users\lopez\BeeStation\Friday\Reports"))

# Rate limiting: 1 scan at a time
_active_scan: Optional[str] = None  # dedup_id of active scan


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.1f} Go"
    elif size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.1f} Mo"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} Ko"
    return f"{size_bytes} o"


def _format_duration(seconds: int) -> str:
    """Format duration in human-readable format."""
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    elif minutes > 0:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _log_task_exception(task: asyncio.Task) -> None:
    """Log exceptions from fire-and-forget tasks."""
    if not task.cancelled() and task.exception():
        logger.error("background_task_failed", error=str(task.exception()))


async def scan_dedup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /scan_dedup command - Start PC-wide dedup scan.

    AC1: Scan PC-wide recursif
    AC4: Progress updates Telegram
    """
    global _active_scan

    # Owner check
    owner_id = int(os.getenv("OWNER_USER_ID", "0"))
    if update.effective_user.id != owner_id:
        await update.message.reply_text("Acces refuse. Commande reservee au Mainteneur.")
        return

    # Rate limiting: 1 scan max
    if _active_scan is not None:
        await update.message.reply_text(
            f"Un scan est deja en cours (ID: {_active_scan[:8]}...). "
            "Attendez sa fin ou annulez-le."
        )
        return

    dedup_id = str(uuid.uuid4())
    _active_scan = dedup_id

    # Send initial message with progress
    metrics_topic_id = int((os.getenv("TOPIC_METRICS_ID", "0") or "0").split("#")[0].strip() or "0")
    msg = await update.message.reply_text(
        "Scan deduplication PC en cours...\n" "Initialisation du scanner...",
        message_thread_id=metrics_topic_id or None,
    )

    try:
        from agents.src.agents.dedup.models import ScanConfig
        from agents.src.agents.dedup.priority_engine import PriorityEngine
        from agents.src.agents.dedup.report_generator import ReportGenerator
        from agents.src.agents.dedup.scanner import DedupScanner

        # Configure scan
        config = ScanConfig(root_path=Path(os.getenv("DEDUP_ROOT_PATH", r"C:\Users\lopez")))

        # Progress callback updates Telegram
        last_update_time = [0.0]

        def progress_update(stats):
            now = time.time()
            if now - last_update_time[0] < 30:  # Throttle 30s
                return
            last_update_time[0] = now

            task = asyncio.create_task(
                _update_scan_progress(
                    context.bot,
                    update.effective_chat.id,
                    msg.message_id,
                    metrics_topic_id,
                    stats,
                    time.time() - scan_start,
                )
            )
            task.add_done_callback(_log_task_exception)

        scan_start = time.time()
        scanner = DedupScanner(config=config, progress_callback=progress_update)

        # Store scanner in bot_data for cancel support
        context.bot_data[f"dedup_scanner_{dedup_id}"] = scanner

        # Run scan
        result = await scanner.scan()

        # Apply priority rules
        engine = PriorityEngine()
        for group in result.groups:
            engine.select_keeper(group)

        # Generate CSV report
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        report_path = REPORTS_DIR / f"dedup_report_{timestamp}.csv"

        generator = ReportGenerator(priority_engine=engine)
        generator.generate_csv(result, report_path)

        # Store result in bot_data for deletion step
        context.bot_data[f"dedup_result_{dedup_id}"] = result
        context.bot_data[f"dedup_report_{dedup_id}"] = str(report_path)

        # Save to DB if available
        db_pool = context.bot_data.get("db_pool")
        if db_pool:
            await db_pool.execute(
                """
                INSERT INTO core.dedup_jobs
                    (dedup_id, scan_date, total_scanned, duplicate_groups,
                     csv_report_path, status)
                VALUES ($1, NOW(), $2, $3, $4, 'report_ready')
                """,
                uuid.UUID(dedup_id),
                result.total_scanned,
                result.duplicate_groups_count,
                str(report_path),
            )

        # Send final report with inline buttons
        elapsed = int(time.time() - scan_start)
        keyboard = [
            [
                InlineKeyboardButton(
                    "Voir rapport",
                    callback_data=f"dedup_report_{dedup_id}",
                ),
                InlineKeyboardButton(
                    "Lancer suppression",
                    callback_data=f"dedup_delete_{dedup_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "Annuler",
                    callback_data=f"dedup_cancel_{dedup_id}",
                ),
            ],
        ]

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg.message_id,
            text=(
                f"Scan termine\n\n"
                f"Fichiers scannes : {result.total_scanned:,}\n"
                f"Groupes doublons : {result.duplicate_groups_count:,}\n"
                f"Doublons detectes : {result.total_duplicates:,}\n"
                f"Espace recuperable : {result.space_reclaimable_gb:.1f} Go\n"
                f"Duree : {_format_duration(elapsed)}\n\n"
                f"Rapport CSV : {report_path.name}"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
            message_thread_id=metrics_topic_id or None,
        )

    except Exception as e:
        logger.error("dedup_scan_failed", dedup_id=dedup_id, error=str(e))
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg.message_id,
            text=f"Erreur scan dedup : {e}",
            message_thread_id=metrics_topic_id or None,
        )
    finally:
        _active_scan = None
        context.bot_data.pop(f"dedup_scanner_{dedup_id}", None)


async def _update_scan_progress(bot, chat_id, message_id, topic_id, stats, elapsed):
    """Update Telegram message with scan progress."""
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                f"Scan en cours : {stats.total_scanned:,} fichiers scannes\n"
                f"Doublons detectes : {stats.duplicate_groups} groupes\n"
                f"Temps ecoule : {_format_duration(int(elapsed))}\n"
                f"Dossier actuel : {stats.current_directory[-60:]}"
            ),
            message_thread_id=topic_id or None,
        )
    except Exception:
        pass  # Ignore edit errors (message identical, etc.)


async def handle_dedup_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle [Voir rapport] button - send CSV file."""
    query = update.callback_query
    await query.answer()

    dedup_id = query.data.replace("dedup_report_", "")
    report_path = context.bot_data.get(f"dedup_report_{dedup_id}")

    if not report_path or not Path(report_path).exists():
        await query.edit_message_text("Rapport non trouve.")
        return

    metrics_topic_id = int((os.getenv("TOPIC_METRICS_ID", "0") or "0").split("#")[0].strip() or "0")
    with open(report_path, "rb") as report_file:
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=report_file,
            filename=Path(report_path).name,
            caption="Rapport CSV deduplication",
            message_thread_id=metrics_topic_id or None,
        )


async def handle_dedup_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle [Lancer suppression] button - show confirmation preview."""
    query = update.callback_query
    await query.answer()

    dedup_id = query.data.replace("dedup_delete_", "")
    result = context.bot_data.get(f"dedup_result_{dedup_id}")

    if not result:
        await query.edit_message_text("Resultats de scan expirés. Relancez /scan_dedup.")
        return

    # Build preview
    keep_examples = []
    delete_examples = []
    for group in result.groups[:3]:  # First 3 groups as examples
        if group.keeper:
            keep_examples.append(
                f"  {group.keeper.file_path.name} ({_format_size(group.keeper.size_bytes)})"
            )
        for d in group.to_delete[:1]:
            delete_examples.append(f"  {d.file_path.name} ({_format_size(d.size_bytes)})")

    total_to_delete = sum(len(g.to_delete) for g in result.groups)
    keep_str = "\n".join(keep_examples[:5]) or "  (aucun)"
    delete_str = "\n".join(delete_examples[:5]) or "  (aucun)"

    keyboard = [
        [
            InlineKeyboardButton(
                "CONFIRMER",
                callback_data=f"dedup_confirm_{dedup_id}",
            ),
            InlineKeyboardButton(
                "Revoir CSV",
                callback_data=f"dedup_report_{dedup_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "ANNULER",
                callback_data=f"dedup_cancel_{dedup_id}",
            ),
        ],
    ]

    await query.edit_message_text(
        text=(
            "CONFIRMATION SUPPRESSION\n\n"
            f"Resume :\n"
            f"  {total_to_delete} fichiers a supprimer\n"
            f"  {result.space_reclaimable_gb:.1f} Go espace a recuperer\n"
            f"  {result.duplicate_groups_count} groupes de doublons\n\n"
            f"Fichiers a GARDER (exemples) :\n{keep_str}\n\n"
            f"Fichiers a SUPPRIMER (exemples) :\n{delete_str}\n\n"
            "Note : Les fichiers sont envoyes a la Corbeille (rollback possible)."
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_dedup_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle [CONFIRMER] button - start batch deletion."""
    query = update.callback_query
    await query.answer()

    dedup_id = query.data.replace("dedup_confirm_", "")
    result = context.bot_data.get(f"dedup_result_{dedup_id}")

    if not result:
        await query.edit_message_text("Resultats expirés. Relancez /scan_dedup.")
        return

    await query.edit_message_text("Suppression en cours...")

    try:
        from agents.src.agents.dedup.deleter import SafeDeleter

        start_time = time.time()
        last_update = [0.0]

        def deletion_progress(del_result):
            now = time.time()
            if now - last_update[0] < 10:
                return
            last_update[0] = now
            total = del_result.total_to_delete
            done = del_result.deleted + del_result.skipped + del_result.errors
            task = asyncio.create_task(
                context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=(
                        f"Suppression en cours : {done}/{total} fichiers\n"
                        f"Espace recupere : {del_result.space_reclaimed_gb:.1f} Go\n"
                        f"Temps ecoule : {_format_duration(int(now - start_time))}"
                    ),
                )
            )
            task.add_done_callback(_log_task_exception)

        deleter = SafeDeleter(progress_callback=deletion_progress)
        del_result = await deleter.delete_duplicates(result.groups)

        elapsed = int(time.time() - start_time)

        # Update DB
        db_pool = context.bot_data.get("db_pool")
        if db_pool:
            await db_pool.execute(
                """
                UPDATE core.dedup_jobs SET
                    files_deleted = $2,
                    files_skipped = $3,
                    files_errors = $4,
                    space_reclaimed_gb = $5,
                    status = 'completed'
                WHERE dedup_id = $1
                """,
                uuid.UUID(dedup_id),
                del_result.deleted,
                del_result.skipped,
                del_result.errors,
                del_result.space_reclaimed_gb,
            )

        # Skip reasons summary
        skip_summary = ""
        if del_result.skip_reasons:
            reasons_count: dict[str, int] = {}
            for _, reason in del_result.skip_reasons:
                reasons_count[reason] = reasons_count.get(reason, 0) + 1
            skip_lines = [
                f"  {count} fichiers : {reason}"
                for reason, count in sorted(reasons_count.items(), key=lambda x: -x[1])
            ]
            skip_summary = "\n\nFichiers skipped :\n" + "\n".join(skip_lines[:5])

        await query.edit_message_text(
            f"SUPPRESSION TERMINEE\n\n"
            f"Resultats :\n"
            f"  {del_result.deleted} fichiers supprimes\n"
            f"  {del_result.skipped} fichiers skipped (safety checks)\n"
            f"  {del_result.errors} erreurs\n"
            f"  {del_result.space_reclaimed_gb:.1f} Go espace recupere\n"
            f"  Duree : {_format_duration(elapsed)}"
            f"{skip_summary}\n\n"
            "Actions suggerees :\n"
            "  Vider la Corbeille pour finaliser la recuperation d'espace\n"
            "  Relancer /scan_dedup pour verifier les nouveaux doublons"
        )

    except Exception as e:
        logger.error("dedup_deletion_failed", dedup_id=dedup_id, error=str(e))
        await query.edit_message_text(f"Erreur suppression : {e}")


async def handle_dedup_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle [Annuler] button."""
    query = update.callback_query
    await query.answer()

    dedup_id = query.data.replace("dedup_cancel_", "")

    # Cancel active scanner if exists
    scanner = context.bot_data.get(f"dedup_scanner_{dedup_id}")
    if scanner:
        scanner.cancel()

    # Cleanup bot_data
    for key in [
        f"dedup_result_{dedup_id}",
        f"dedup_report_{dedup_id}",
        f"dedup_scanner_{dedup_id}",
    ]:
        context.bot_data.pop(key, None)

    await query.edit_message_text("Operation dedup annulee.")
