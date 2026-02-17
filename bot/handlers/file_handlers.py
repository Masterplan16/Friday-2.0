"""
Bot Telegram Friday 2.0 - File Upload/Download Handlers

Story 3.6 - Envoi/réception fichiers via Telegram (AC#1, AC#4, AC#6, AC#7).
"""

import asyncio
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from bot.handlers.rate_limiter import SimpleRateLimiter
from redis import asyncio as aioredis
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)

# Extensions autorisées whitelist (AC#4)
ALLOWED_EXTENSIONS = {
    # Documents
    ".pdf",
    ".docx",
    ".xlsx",
    ".csv",
    # Images
    ".png",
    ".jpg",
    ".jpeg",
}

# MIME types autorisés (cohérent avec extensions)
ALLOWED_MIME_TYPES = {
    # Documents
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "text/csv",
    # Images
    "image/png",
    "image/jpeg",
}

# Taille max fichier Telegram Bot API (AC#7)
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024  # 20 MB

# Zone transit VPS (AC#1)
TRANSIT_DIR = Path("/var/friday/transit/telegram_uploads")

# Redis Streams event (dot notation CLAUDE.md)
DOCUMENT_RECEIVED_STREAM = "document.received"

# Retry config (AC#6)
MAX_RETRIES = 3
BACKOFF_BASE = 1  # 1s, 2s, 4s

# Dossier erreurs (AC#6)
ERRORS_DIR = Path("/var/friday/transit/telegram_uploads/errors")

# Topic Telegram pour notifications (AC#5)
TOPIC_EMAIL_COMMUNICATIONS = int(
    (os.getenv("TOPIC_EMAIL_ID", "0") or "0").split("#")[0].strip() or "0"
)
TOPIC_SYSTEM_ALERTS = int((os.getenv("TOPIC_SYSTEM_ID", "0") or "0").split("#")[0].strip() or "0")

# Magic numbers pour validation fichiers (AC#4)
MAGIC_NUMBERS = {
    ".pdf": b"%PDF",
    ".png": b"\x89PNG",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".docx": b"PK\x03\x04",  # ZIP-based (Office Open XML)
    ".xlsx": b"PK\x03\x04",  # ZIP-based (Office Open XML)
    # CSV = texte pur, pas de magic number
}


# ============================================================================
# Rate Limiter Instance (AC#7)
# ============================================================================

# Rate limiter : 20 fichiers/minute par utilisateur
file_upload_limiter = SimpleRateLimiter(max_calls=20, window_seconds=60)


# ============================================================================
# Validation Functions
# ============================================================================
def is_valid_file_type(mime_type: str, filename: str) -> bool:
    """
    Valide MIME type ET extension fichier (AC#4).

    Args:
        mime_type: Type MIME du fichier
        filename: Nom du fichier

    Returns:
        True si valide, False sinon
    """
    # Extraire extension
    extension = Path(filename).suffix.lower()

    # Vérifier whitelist extension
    if extension not in ALLOWED_EXTENSIONS:
        logger.warning(
            "file_validation.extension_rejected",
            filename=filename,
            extension=extension,
            allowed=list(ALLOWED_EXTENSIONS),
        )
        return False

    # Vérifier whitelist MIME type
    if mime_type not in ALLOWED_MIME_TYPES:
        logger.warning(
            "file_validation.mime_type_rejected",
            filename=filename,
            mime_type=mime_type,
            allowed=list(ALLOWED_MIME_TYPES),
        )
        return False

    return True


def validate_magic_number(file_path: Path) -> bool:
    """
    Valide magic number du fichier après téléchargement (AC#4).

    Vérifie que les premiers bytes correspondent au type déclaré par l'extension.
    CSV n'a pas de magic number (texte pur) → toujours valide.

    Args:
        file_path: Chemin fichier téléchargé

    Returns:
        True si magic number valide ou extension sans magic number, False sinon
    """
    extension = file_path.suffix.lower()
    expected_magic = MAGIC_NUMBERS.get(extension)

    # Pas de magic number pour cette extension (ex: .csv)
    if expected_magic is None:
        return True

    try:
        with open(file_path, "rb") as f:
            header = f.read(len(expected_magic))

        if header.startswith(expected_magic):
            return True

        logger.warning(
            "file_validation.magic_number_mismatch",
            file_path=str(file_path),
            extension=extension,
            expected=expected_magic.hex(),
            actual=header.hex() if header else "empty",
        )
        return False

    except OSError as e:
        logger.error("file_validation.magic_number_read_error", error=str(e))
        return False


def _move_to_errors_dir(file_path: Path, reason: str) -> None:
    """
    Déplace un fichier invalide vers le dossier errors/ (AC#6).

    Args:
        file_path: Chemin fichier à déplacer
        reason: Raison du déplacement (pour le log)
    """
    try:
        ERRORS_DIR.mkdir(parents=True, exist_ok=True)
        dest = ERRORS_DIR / file_path.name
        shutil.move(str(file_path), str(dest))
        logger.info(
            "file_moved_to_errors",
            source=str(file_path),
            destination=str(dest),
            reason=reason,
        )
    except OSError as e:
        logger.error(
            "file_move_to_errors_failed",
            file_path=str(file_path),
            error=str(e),
        )


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename pour sécurité filesystem.

    Remplace caractères dangereux : / \\ : * ? " < > |

    Args:
        filename: Nom fichier original

    Returns:
        Nom fichier sanitized
    """
    # Caractères interdits Windows/Linux
    dangerous_chars = r'\/:*?"<>|'
    sanitized = filename

    for char in dangerous_chars:
        sanitized = sanitized.replace(char, "_")

    # Limiter longueur (255 chars max sur la plupart des filesystems)
    if len(sanitized) > 255:
        # Garder extension
        stem = Path(sanitized).stem[:200]  # 200 chars pour nom
        suffix = Path(sanitized).suffix[:50]  # 50 chars pour extension
        sanitized = stem + suffix

    return sanitized


# ============================================================================
# Download Function with Retry (AC#6)
# ============================================================================
async def download_telegram_file(
    bot, file_id: str, destination_path: Path, max_retries: int = MAX_RETRIES
) -> Optional[Path]:
    """
    Télécharge fichier Telegram avec retry backoff exponentiel (AC#6).

    Args:
        bot: Bot Telegram instance
        file_id: ID fichier Telegram
        destination_path: Chemin destination
        max_retries: Nombre max tentatives

    Returns:
        Path du fichier téléchargé, ou None si échec après retry

    Raises:
        Exception si échec après max_retries
    """
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            # Get file object
            file = await bot.get_file(file_id)

            # Download
            await file.download_to_drive(str(destination_path))

            logger.info(
                "file_download.success",
                file_id=file_id,
                destination=str(destination_path),
                attempt=attempt,
            )

            return destination_path

        except Exception as e:
            last_error = e
            if attempt < max_retries:
                backoff = BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "file_download.retry",
                    file_id=file_id,
                    attempt=attempt,
                    max_retries=max_retries,
                    backoff=backoff,
                    error=str(e),
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(
                    "file_download.failed",
                    file_id=file_id,
                    attempts=max_retries,
                    error=str(e),
                )

    # Toutes tentatives échouées
    raise last_error


# ============================================================================
# Redis Streams Publish with Retry (AC#6)
# ============================================================================
async def publish_document_received(
    redis_client: aioredis.Redis,
    file_path: Path,
    filename: str,
    source: str,
    telegram_user_id: int,
    telegram_message_id: int,
    mime_type: str,
    file_size_bytes: int,
) -> None:
    """
    Publie événement document.received dans Redis Streams avec retry (AC#6).

    Args:
        redis_client: Client Redis async
        file_path: Chemin fichier sur VPS
        filename: Nom fichier original
        source: Source ("telegram")
        telegram_user_id: User ID Telegram
        telegram_message_id: Message ID Telegram
        mime_type: Type MIME
        file_size_bytes: Taille fichier bytes

    Raises:
        Exception si échec après max_retries
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Format plat Redis Streams (dot notation, string values)
            event_data = {
                "filename": filename,
                "file_path": str(file_path),
                "source": source,
                "telegram_user_id": str(telegram_user_id),
                "telegram_message_id": str(telegram_message_id),
                "mime_type": mime_type,
                "file_size_bytes": str(file_size_bytes),
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }

            # Publish Redis Streams
            await redis_client.xadd(
                DOCUMENT_RECEIVED_STREAM,
                event_data,
                maxlen=10000,
            )

            logger.info(
                "redis_publish.success",
                stream=DOCUMENT_RECEIVED_STREAM,
                filename=filename,
                attempt=attempt,
            )

            return  # Success

        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                backoff = BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "redis_publish.retry",
                    stream=DOCUMENT_RECEIVED_STREAM,
                    filename=filename,
                    attempt=attempt,
                    max_retries=MAX_RETRIES,
                    backoff=backoff,
                    error=str(e),
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(
                    "redis_publish.failed",
                    stream=DOCUMENT_RECEIVED_STREAM,
                    filename=filename,
                    attempts=MAX_RETRIES,
                    error=str(e),
                )

    # Toutes tentatives échouées
    raise last_error


# ============================================================================
# Handler: Document Telegram (PDF, Word, Excel, CSV)
# ============================================================================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler document Telegram (AC#1, AC#4, AC#6, AC#7).

    Steps:
    1. Rate limiting (20 fichiers/minute)
    2. Validation MIME type + extension whitelist
    3. Validation taille fichier (<20 Mo)
    4. Téléchargement vers zone transit VPS
    5. Publication Redis Streams document.received
    6. Notification utilisateur succès

    Args:
        update: Update Telegram
        context: Context bot
    """
    if not update.message or not update.effective_user:
        return

    document = update.message.document
    if not document:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "unknown"

    # ========================================================================
    # Rate Limiting (AC#7)
    # ========================================================================
    allowed, retry_after = file_upload_limiter.is_allowed(user_id, "file_upload")
    if not allowed:
        await update.message.reply_text(
            f"⚠️ Limite d'envoi atteinte.\n"
            f"Veuillez réessayer dans {retry_after} secondes.\n"
            f"(Limite: 20 fichiers par minute)"
        )
        logger.warning(
            "file_upload.rate_limited",
            user_id=user_id,
            username=username,
            retry_after=retry_after,
        )
        return

    # ========================================================================
    # Validation Taille Fichier (AC#7)
    # ========================================================================
    if document.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text(
            f"❌ Fichier trop volumineux: {document.file_size / 1024 / 1024:.1f} Mo\n"
            f"Limite: {MAX_FILE_SIZE_MB} Mo (Telegram Bot API)"
        )
        logger.warning(
            "file_upload.too_large",
            filename=document.file_name,
            file_size_mb=document.file_size / 1024 / 1024,
            max_size_mb=MAX_FILE_SIZE_MB,
        )
        return

    # ========================================================================
    # Validation Fichier Vide (Edge case)
    # ========================================================================
    if document.file_size == 0:
        await update.message.reply_text(
            f"❌ Fichier vide: {document.file_name}\n" f"Le fichier ne contient aucune donnée."
        )
        logger.warning(
            "file_upload.zero_bytes",
            filename=document.file_name,
        )
        return

    # ========================================================================
    # Validation MIME Type + Extension (AC#4)
    # ========================================================================
    if not is_valid_file_type(document.mime_type, document.file_name):
        await update.message.reply_text(
            f"❌ Type de fichier non supporté: {document.file_name}\n"
            f"Types acceptés: PDF, PNG, JPG, DOCX, XLSX, CSV"
        )
        logger.warning(
            "file_upload.invalid_type",
            filename=document.file_name,
            mime_type=document.mime_type,
        )
        return

    # ========================================================================
    # Téléchargement Fichier (AC#1, AC#6)
    # ========================================================================
    try:
        # Créer zone transit si n'existe pas
        TRANSIT_DIR.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        safe_filename = sanitize_filename(document.file_name)

        # Chemin destination unique (timestamp pour éviter collisions)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{timestamp}_{safe_filename}"
        destination_path = TRANSIT_DIR / unique_filename

        # Download avec retry
        await download_telegram_file(
            context.bot, document.file_id, destination_path, max_retries=MAX_RETRIES
        )

        # Validation magic number post-download (AC#4)
        if not validate_magic_number(destination_path):
            _move_to_errors_dir(destination_path, "magic_number_mismatch")
            await update.message.reply_text(
                f"❌ Fichier suspect : {document.file_name}\n"
                f"Le contenu du fichier ne correspond pas au type déclaré."
            )
            logger.warning(
                "file_upload.magic_number_failed",
                filename=document.file_name,
                mime_type=document.mime_type,
            )
            return

    except Exception as e:
        # Déplacer fichier vers errors/ si téléchargé partiellement
        if destination_path.exists():
            _move_to_errors_dir(destination_path, "download_error")
        await update.message.reply_text(
            "❌ Erreur lors du téléchargement du fichier.\n" "Veuillez réessayer plus tard."
        )
        logger.error(
            "file_upload.download_error",
            filename=document.file_name,
            error=str(e),
        )
        return

    # ========================================================================
    # Publication Redis Streams (AC#1, AC#6)
    # ========================================================================
    redis_client = context.bot_data.get("redis_client")
    if not redis_client:
        await update.message.reply_text(
            f"❌ Service indisponible (Redis).\n" f"Contactez l'administrateur."
        )
        logger.error("file_upload.redis_unavailable", filename=document.file_name)
        return

    try:
        await publish_document_received(
            redis_client=redis_client,
            file_path=destination_path,
            filename=document.file_name,
            source="telegram",
            telegram_user_id=user_id,
            telegram_message_id=update.message.message_id,
            mime_type=document.mime_type,
            file_size_bytes=document.file_size,
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Erreur lors de la publication de l'événement.\n"
            f"Le fichier a été téléchargé mais ne sera pas traité."
        )
        logger.error(
            "file_upload.redis_publish_error",
            filename=document.file_name,
            error=str(e),
        )
        return

    # ========================================================================
    # Notification Succès (AC#1, AC#5 topic Email & Communications)
    # ========================================================================
    await update.message.reply_text(
        f"✅ Fichier reçu: {document.file_name}\n"
        f"Taille: {document.file_size / 1024:.1f} Ko\n"
        f"Traitement en cours par le pipeline Archiviste...",
        message_thread_id=TOPIC_EMAIL_COMMUNICATIONS or None,
    )

    logger.info(
        "file_upload.success",
        filename=document.file_name,
        user_id=user_id,
        username=username,
        file_size_bytes=document.file_size,
        mime_type=document.mime_type,
    )


# ============================================================================
# Handler: Photo Telegram (JPG, PNG)
# ============================================================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler photo Telegram (AC#1, AC#4, AC#6, AC#7).

    Telegram envoie photos en plusieurs tailles, on prend la plus grande.

    Args:
        update: Update Telegram
        context: Context bot
    """
    if not update.message or not update.effective_user:
        return

    photos = update.message.photo
    if not photos:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "unknown"

    # ========================================================================
    # Rate Limiting (AC#7)
    # ========================================================================
    allowed, retry_after = file_upload_limiter.is_allowed(user_id, "file_upload")
    if not allowed:
        await update.message.reply_text(
            f"⚠️ Limite d'envoi atteinte.\n"
            f"Veuillez réessayer dans {retry_after} secondes.\n"
            f"(Limite: 20 fichiers par minute)"
        )
        logger.warning(
            "photo_upload.rate_limited",
            user_id=user_id,
            username=username,
            retry_after=retry_after,
        )
        return

    # ========================================================================
    # Extraire Plus Grande Photo
    # ========================================================================
    # Telegram envoie photos en plusieurs tailles (thumbnails + original)
    # On prend la dernière = la plus grande
    largest_photo = photos[-1]

    # ========================================================================
    # Validation Taille Photo (AC#7)
    # ========================================================================
    if largest_photo.file_size and largest_photo.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text(
            f"❌ Photo trop volumineuse: {largest_photo.file_size / 1024 / 1024:.1f} Mo\n"
            f"Limite: {MAX_FILE_SIZE_MB} Mo (Telegram Bot API)"
        )
        logger.warning(
            "photo_upload.too_large",
            file_size_mb=largest_photo.file_size / 1024 / 1024,
            max_size_mb=MAX_FILE_SIZE_MB,
        )
        return

    # ========================================================================
    # Téléchargement Photo (AC#1, AC#6)
    # ========================================================================
    try:
        # Créer zone transit
        TRANSIT_DIR.mkdir(parents=True, exist_ok=True)

        # Générer nom fichier unique
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        destination_path = TRANSIT_DIR / filename

        # Download avec retry
        await download_telegram_file(
            context.bot, largest_photo.file_id, destination_path, max_retries=MAX_RETRIES
        )

        # Validation magic number post-download (AC#4)
        if not validate_magic_number(destination_path):
            _move_to_errors_dir(destination_path, "magic_number_mismatch")
            await update.message.reply_text(
                "❌ Photo suspecte : le contenu ne correspond pas au type déclaré."
            )
            logger.warning("photo_upload.magic_number_failed")
            return

    except Exception as e:
        if destination_path.exists():
            _move_to_errors_dir(destination_path, "download_error")
        await update.message.reply_text(
            "❌ Erreur lors du téléchargement de la photo.\n" "Veuillez réessayer plus tard."
        )
        logger.error(
            "photo_upload.download_error",
            error=str(e),
        )
        return

    # ========================================================================
    # Publication Redis Streams (AC#1, AC#6)
    # ========================================================================
    redis_client = context.bot_data.get("redis_client")
    if not redis_client:
        await update.message.reply_text(
            f"❌ Service indisponible (Redis).\n" f"Contactez l'administrateur."
        )
        logger.error("photo_upload.redis_unavailable")
        return

    try:
        await publish_document_received(
            redis_client=redis_client,
            file_path=destination_path,
            filename=filename,
            source="telegram",
            telegram_user_id=user_id,
            telegram_message_id=update.message.message_id,
            mime_type="image/jpeg",  # Telegram compresse en JPEG
            file_size_bytes=largest_photo.file_size,
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Erreur lors de la publication de l'événement.\n"
            f"La photo a été téléchargée mais ne sera pas traitée."
        )
        logger.error(
            "photo_upload.redis_publish_error",
            error=str(e),
        )
        return

    # ========================================================================
    # Notification Succès (AC#1, AC#5 topic Email & Communications)
    # ========================================================================
    await update.message.reply_text(
        f"✅ Photo reçue\n"
        f"Taille: {largest_photo.file_size / 1024:.1f} Ko\n"
        f"Traitement en cours par le pipeline Archiviste...",
        message_thread_id=TOPIC_EMAIL_COMMUNICATIONS or None,
    )

    logger.info(
        "photo_upload.success",
        user_id=user_id,
        username=username,
        file_size_bytes=largest_photo.file_size,
    )
