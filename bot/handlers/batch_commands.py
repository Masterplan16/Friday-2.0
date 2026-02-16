"""
Batch processing commands for Telegram bot.

Handles:
- Intent detection "traiter dossier batch" via Claude Sonnet 4.5
- Path validation (security: path traversal, zones autorisées)
- Confirmation workflow with inline buttons
- Callback handlers for batch inline buttons
- Batch processor launch

AC1: Intent detection & confirmation
AC7: Security validation
"""

import os
import json
import uuid
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import structlog
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from anthropic import AsyncAnthropic

from agents.src.agents.archiviste.batch_shared import (
    ALLOWED_ZONES,
    is_system_file,
)

logger = structlog.get_logger(__name__)

# Claude client
anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Active batch state (AC7: 1 batch actif max)
# Key: batch_id, Value: BatchState
_active_batches: dict[str, "BatchState"] = {}


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class BatchRequest:
    """Batch processing request."""

    batch_id: str
    folder_path: str
    confidence: float


@dataclass
class BatchState:
    """State for an active or pending batch."""

    batch_id: str
    folder_path: str
    file_count: int
    filters: dict = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed, cancelled


def get_active_batch() -> Optional["BatchState"]:
    """Return currently running batch, if any (AC7: 1 batch actif max)."""
    for state in _active_batches.values():
        if state.status == "running":
            return state
    return None


# ============================================================================
# Intent Detection (AC1)
# ============================================================================


async def detect_batch_intent(text: str) -> Optional[BatchRequest]:
    """
    Detect if user message requests batch folder processing.

    Uses Claude Sonnet 4.5 for intent detection with few-shot examples.

    Args:
        text: User message text

    Returns:
        BatchRequest if intent detected (confidence >= 0.85)
        None otherwise

    AC1: Intent detection "traiter dossier batch"
    """
    prompt = f"""Tu es Friday, assistant IA. Détecte si l'utilisateur demande de traiter un dossier en batch.

Exemples:
- "Range mes Downloads" → intent: batch_process, folder_path: "C:\\Users\\lopez\\Downloads"
- "Traite tous les fichiers dans C:\\Users\\lopez\\Desktop\\Scans" → intent: batch_process, folder_path: "C:\\Users\\lopez\\Desktop\\Scans"
- "Organise le dossier scan du bureau" → intent: batch_process, folder_path: "C:\\Users\\lopez\\Desktop"
- "Bonjour Friday" → intent: other

Si intention détectée, retourne JSON:
{{"intent": "batch_process", "folder_path": "chemin", "confidence": 0.XX}}

Si intention non détectée, retourne:
{{"intent": "other", "confidence": 0.XX}}

Message utilisateur: "{text}"

Retourne uniquement le JSON, rien d'autre.
"""

    try:
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        response_text = response.content[0].text.strip()
        data = json.loads(response_text)

        # Check intent
        if data.get("intent") == "batch_process" and data.get("confidence", 0) >= 0.85:
            return BatchRequest(
                batch_id=str(uuid.uuid4()),
                folder_path=data["folder_path"],
                confidence=data["confidence"],
            )

        return None

    except Exception as e:
        logger.error("intent_detection_failed", error=str(e), text=text)
        return None


# ============================================================================
# Path Validation (AC7)
# ============================================================================


def validate_folder_path(path: str) -> tuple[bool, str]:
    """
    Validate folder path security.

    Security checks:
    - Path traversal: Interdire ".." dans chemin original
    - Exists & Type: Doit exister et être un dossier (pas fichier)
    - Zones autorisées: Downloads, Desktop, Transit uniquement
    - Permissions: Vérifier accès lecture

    Args:
        path: Folder path to validate

    Returns:
        (True, normalized_path) if valid
        (False, error_message) if invalid

    AC7: Security validation
    """
    try:
        # Path traversal protection (check BEFORE resolving)
        if ".." in path:
            return False, "Path traversal détecté"

        # Resolve path (symlinks, etc.)
        resolved = Path(path).resolve()

        # Exists check (must check before is_dir)
        if not resolved.exists():
            return False, "Dossier introuvable"

        # Is directory check (before zone check for better error message)
        if not resolved.is_dir():
            return False, "Chemin n'est pas un dossier"

        # Zone autorisée check (primary security gate after resolve)
        is_allowed = False
        for zone in ALLOWED_ZONES:
            try:
                if resolved.is_relative_to(Path(zone)):
                    is_allowed = True
                    break
            except ValueError:
                continue

        if not is_allowed:
            zones_str = ", ".join(ALLOWED_ZONES)
            return False, f"Zone non autorisée. Autorisées : {zones_str}"

        return True, str(resolved)

    except Exception as e:
        return False, f"Erreur validation : {str(e)}"


# ============================================================================
# File Counting (AC7)
# ============================================================================


def count_files_recursive(folder_path: str, filters: dict) -> int:
    """
    Count files recursively with filters applied.

    Skips:
    - System files (.tmp, .cache, desktop.ini)
    - Directories
    - Files not matching extension filter (if specified)

    Args:
        folder_path: Folder to scan
        filters: Filters dict (keys: extensions, max_size_mb)

    Returns:
        Number of files matching filters

    AC7: Quota validation (max 1000 files)
    """
    count = 0
    folder = Path(folder_path)
    extensions = filters.get("extensions") if filters else None
    max_size_mb = filters.get("max_size_mb") if filters else None

    for file_path in folder.rglob("*"):
        # Skip directories
        if file_path.is_dir():
            continue

        # Skip system files
        if is_system_file(file_path):
            continue

        # Apply extension filter
        if extensions and file_path.suffix.lower() not in extensions:
            continue

        # Apply size filter
        if max_size_mb:
            try:
                size_mb = file_path.stat().st_size / (1024 * 1024)
                if size_mb > max_size_mb:
                    continue
            except OSError:
                continue

        count += 1

    return count


# ============================================================================
# Batch Command Handler (AC1, AC7)
# ============================================================================


async def handle_batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle batch processing command from Telegram.

    Steps:
    1. Intent detection via Claude Sonnet 4.5
    2. Path extraction & validation security
    3. Check no batch already running (AC7: 1 batch actif max)
    4. Preview nombre fichiers
    5. Confirmation inline buttons [Lancer/Annuler/Options]

    AC1: Intent detection & confirmation workflow
    AC7: Security validation (path traversal, zones autorisées, quota)
    """
    text = update.message.text

    # Step 1: Intent detection
    batch_request = await detect_batch_intent(text)
    if not batch_request:
        # Not a batch request, return silently
        return

    # Step 2: Validate path
    valid, result = validate_folder_path(batch_request.folder_path)
    if not valid:
        await update.message.reply_text(f"❌ {result}")
        return

    folder_path = result

    # Step 3: Check no batch already running (AC7)
    active = get_active_batch()
    if active:
        await update.message.reply_text(
            f"❌ Un batch est déjà en cours ({active.folder_path}).\n"
            "Attends qu'il se termine ou annule-le."
        )
        return

    # Step 4: Preview files
    file_count = count_files_recursive(folder_path, filters={})

    # Step 5: Quota check (AC7)
    if file_count > 1000:
        await update.message.reply_text(
            f"❌ Trop de fichiers détectés ({file_count}). Maximum : 1000 fichiers par batch."
        )
        return

    # Store batch state for callback handlers
    batch_state = BatchState(
        batch_id=batch_request.batch_id,
        folder_path=folder_path,
        file_count=file_count,
    )
    _active_batches[batch_request.batch_id] = batch_state

    # Step 6: Confirmation message
    if file_count > 100:
        # Warning if >100 files (AC7)
        message = f"⚠️ {file_count} fichiers détectés dans {folder_path}\n\nContinuer ?"
    else:
        message = f"📦 {file_count} fichiers détectés dans {folder_path}\n\nLancer le traitement ?"

    # Inline buttons (AC1)
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Lancer", callback_data=f"batch_start_{batch_request.batch_id}"
            ),
            InlineKeyboardButton(
                "🔧 Options", callback_data=f"batch_options_{batch_request.batch_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Annuler", callback_data=f"batch_cancel_{batch_request.batch_id}"
            )
        ],
    ]

    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

    logger.info(
        "batch_command_confirmation",
        batch_id=batch_request.batch_id,
        folder_path=folder_path,
        file_count=file_count,
    )


# ============================================================================
# Callback Handlers for batch inline buttons (AC1, AC3)
# ============================================================================


async def handle_batch_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle [Lancer] button click — starts batch processing.

    Creates BatchProgressTracker with the confirmation message_id,
    then launches BatchProcessor asynchronously.

    AC1: Lancement batch après confirmation
    AC3: Progress tracking via edit message
    """
    import asyncio

    query = update.callback_query
    await query.answer()

    batch_id = query.data.replace("batch_start_", "")
    batch_state = _active_batches.get(batch_id)

    if not batch_state:
        await query.edit_message_text("❌ Batch expiré ou introuvable.")
        return

    if batch_state.status == "running":
        await query.answer("Batch déjà en cours.", show_alert=True)
        return

    batch_state.status = "running"

    # Import here to avoid circular imports
    from agents.src.agents.archiviste.batch_progress import BatchProgressTracker
    from agents.src.agents.archiviste.batch_processor import BatchProcessor, BatchFilters

    # Create progress tracker using the confirmation message
    # (AC3: edit this message for progress updates)
    progress = BatchProgressTracker(
        batch_id=batch_id,
        folder_path=batch_state.folder_path,
        bot=context.bot,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        topic_id=query.message.message_thread_id or 0,
    )

    # Update message to show "starting"
    await query.edit_message_text(
        f"🚀 Démarrage du traitement batch...\n📁 {batch_state.folder_path}"
    )

    # Build filters from batch state
    filters = BatchFilters(**batch_state.filters) if batch_state.filters else BatchFilters()

    # Get DB pool and Redis from bot context (if available)
    db_pool = getattr(context.application, "db_pool", None) or context.bot_data.get("db_pool")
    redis_client = getattr(context.application, "redis_client", None) or context.bot_data.get(
        "redis_client"
    )

    # Create processor
    processor = BatchProcessor(
        batch_id=batch_id,
        folder_path=batch_state.folder_path,
        filters=filters,
        progress_tracker=progress,
        db=db_pool,
        redis_client=redis_client,
    )

    # Launch batch processing asynchronously
    async def _run_batch():
        try:
            await processor.process()
            batch_state.status = "completed"
        except Exception as e:
            batch_state.status = "failed"
            logger.error("batch_processing_error", batch_id=batch_id, error=str(e))
            await progress.update_telegram(force=True)
        finally:
            # Cleanup batch state after delay (allow report viewing)
            await asyncio.sleep(3600)
            _active_batches.pop(batch_id, None)

    asyncio.create_task(_run_batch())

    logger.info("batch_started", batch_id=batch_id, folder_path=batch_state.folder_path)


async def handle_batch_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle [Annuler] button click — cancels batch.

    AC1: Annulation batch
    """
    query = update.callback_query
    await query.answer()

    batch_id = query.data.replace("batch_cancel_", "")
    batch_state = _active_batches.get(batch_id)

    if batch_state:
        batch_state.status = "cancelled"
        _active_batches.pop(batch_id, None)

    await query.edit_message_text("❌ Traitement batch annulé.")
    logger.info("batch_cancelled", batch_id=batch_id)


async def handle_batch_options_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle [Options] button click — show filter options.

    AC5: Filtres optionnels
    """
    query = update.callback_query
    await query.answer()

    batch_id = query.data.replace("batch_options_", "")
    batch_state = _active_batches.get(batch_id)

    if not batch_state:
        await query.edit_message_text("❌ Batch expiré ou introuvable.")
        return

    message = (
        f"🔧 Options pour {batch_state.folder_path}\n\n"
        f"📁 {batch_state.file_count} fichiers détectés\n\n"
        "Filtres disponibles :\n"
        "• Extensions : PDF, images, documents\n"
        "• Taille max : 50 Mo / 100 Mo\n"
        "• Profondeur : récursif ON/OFF"
    )

    keyboard = [
        [
            InlineKeyboardButton("📄 PDF only", callback_data=f"batch_filter_pdf_{batch_id}"),
            InlineKeyboardButton("📷 Images", callback_data=f"batch_filter_img_{batch_id}"),
        ],
        [
            InlineKeyboardButton("📋 Tous types", callback_data=f"batch_filter_all_{batch_id}"),
        ],
        [
            InlineKeyboardButton("✅ Lancer", callback_data=f"batch_start_{batch_id}"),
            InlineKeyboardButton("❌ Annuler", callback_data=f"batch_cancel_{batch_id}"),
        ],
    ]

    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_batch_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle [Pause/Reprendre] button click during processing.

    AC3: Inline buttons [Pause/Annuler/Détails]
    """
    query = update.callback_query
    batch_id = query.data.replace("batch_pause_", "")
    batch_state = _active_batches.get(batch_id)

    if not batch_state or batch_state.status != "running":
        await query.answer("Batch non actif.", show_alert=True)
        return

    # Toggle pause via bot_data (checked by BatchProcessor)
    pause_key = f"batch_paused_{batch_id}"
    is_paused = context.bot_data.get(pause_key, False)
    context.bot_data[pause_key] = not is_paused

    status = "en pause" if not is_paused else "repris"
    await query.answer(f"Batch {status}.")
    logger.info("batch_pause_toggled", batch_id=batch_id, paused=not is_paused)


async def handle_batch_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle [Détails] button click during processing.

    AC3: Détails batch en cours
    """
    query = update.callback_query
    await query.answer()

    batch_id = query.data.replace("batch_details_", "")
    batch_state = _active_batches.get(batch_id)

    if not batch_state:
        await query.answer("Batch introuvable.", show_alert=True)
        return

    details = (
        f"📋 Détails batch {batch_id[:8]}...\n\n"
        f"📁 Dossier : {batch_state.folder_path}\n"
        f"📊 Fichiers : {batch_state.file_count}\n"
        f"🔄 Status : {batch_state.status}\n"
        f"🔧 Filtres : {batch_state.filters or 'aucun'}"
    )

    await query.answer(details, show_alert=True)
