"""
Module extraction pièces jointes emails.

Story 2.4 - Extraction Pièces Jointes
[D25] : IMAP direct (aioimaplib) remplace EmailEngine pour l'accès emails.
Le paramètre emailengine_client est conservé pour compatibilité (AdapterEmailCompat).

Workflow :
1. Query email adapter pour liste attachments d'un email
2. Pour chaque attachment :
   - Valider MIME type (whitelist/blacklist)
   - Valider taille (configurable via env vars)
   - Télécharger fichier via adapter (IMAP FETCH)
   - Sanitizer nom fichier (sécurité path traversal)
   - Stocker en zone transit VPS
   - INSERT métadonnées dans ingestion.attachments
   - Publier événement Redis Streams document.received
3. UPDATE ingestion.emails SET has_attachments=TRUE
4. Retourner ActionResult avec stats extraction
"""

import os
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
import asyncpg
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agents.src.config.mime_types import validate_mime_type
from agents.src.middleware.trust import friday_action
from agents.src.models.attachment import AttachmentExtractResult, MAX_ATTACHMENT_SIZE_BYTES

logger = structlog.get_logger(__name__)

# Zone transit VPS
TRANSIT_BASE_DIR = "/var/friday/transit/attachments"
MAX_FILENAME_LENGTH = 200

# Limites taille PJ (configurables via env vars, A.8)
_max_attachment_size_mb = int(os.getenv("MAX_ATTACHMENT_SIZE_MB", "50"))
_max_total_attachments_mb = int(os.getenv("MAX_TOTAL_ATTACHMENTS_MB", "200"))
MAX_SINGLE_ATTACHMENT_BYTES = _max_attachment_size_mb * 1024 * 1024
MAX_TOTAL_ATTACHMENTS_BYTES = _max_total_attachments_mb * 1024 * 1024


def sanitize_filename(filename: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """
    Sécurise un nom de fichier contre path traversal et caractères dangereux.

    Applique :
    - Normalisation Unicode (supprime accents)
    - Suppression caractères dangereux (garde alphanum + _ - . espaces)
    - Normalisation espaces multiples
    - Extensions lowercase
    - Limite longueur max
    - Suppression . _ - en début/fin
    - Fallback "unnamed_file" si vide après sanitization

    Args:
        filename: Nom fichier original
        max_length: Longueur max (default 200)

    Returns:
        Nom fichier sécurisé

    Examples:
        >>> sanitize_filename("../../etc/passwd")
        'etc_passwd'
        >>> sanitize_filename("Mon Document   Final.PDF")
        'Mon_Document_Final.pdf'
        >>> sanitize_filename("file; rm -rf /")
        'file_rm_rf'
    """
    if not filename or not filename.strip():
        return "unnamed_file"

    # 1. Normalisation Unicode (NFD → supprimer accents)
    filename = unicodedata.normalize('NFKD', filename).encode('ASCII', 'ignore').decode('ASCII')

    # 2. Suppression caractères dangereux (garde alphanum + _ - . espaces)
    filename = re.sub(r'[^\w\s\-\.]', '_', filename)

    # 3. Normalisation espaces multiples → underscore unique
    filename = re.sub(r'\s+', '_', filename)

    # 4. Suppression underscores multiples consécutifs
    filename = re.sub(r'_+', '_', filename)

    # 5. Extensions lowercase
    name, ext = os.path.splitext(filename)
    if ext:
        filename = f"{name}{ext.lower()}"

    # 6. Limite longueur (conserver extension)
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        name = name[:max_length - len(ext)]
        filename = f"{name}{ext}"

    # 7. Suppression . _ - en début/fin
    filename = filename.strip('._- ')

    # 8. Fallback si vide après sanitization
    if not filename:
        return "unnamed_file"

    return filename


@friday_action(module="email", action="extract_attachments", trust_default="auto")
async def extract_attachments(
    email_id: str,
    db_pool: asyncpg.Pool,
    emailengine_client: Any,
    redis_client: Any,
    **kwargs
) -> AttachmentExtractResult:
    """
    Extrait pièces jointes d'un email via adapter IMAP (D25).

    Workflow :
    1. Query adapter pour liste attachments d'un email
    2. Pour chaque attachment :
       - Valider MIME type (whitelist/blacklist)
       - Valider taille (configurable via env vars)
       - Télécharger via adapter (IMAP FETCH)
       - Sanitizer filename
       - Stocker zone transit /var/friday/transit/attachments/YYYY-MM-DD/
       - INSERT ingestion.attachments
       - Publier événement Redis Streams document.received
    3. UPDATE ingestion.emails SET has_attachments=TRUE
    4. Retourner ActionResult

    Args:
        email_id: ID email source
        db_pool: Pool asyncpg
        emailengine_client: Email adapter compat (AdapterEmailCompat, D25)
        redis_client: Client Redis (pour publication événements)
        **kwargs: Args additionnels (fournis par @friday_action)

    Returns:
        AttachmentExtractResult (ActionResult-compatible)

    Trust Level:
        auto (extraction = opération déterministe, pas d'ambiguïté)
    """
    log = logger.bind(email_id=email_id)
    log.info("attachment_extraction_started")

    # 1. Query email adapter pour liste attachments
    try:
        email_data = await emailengine_client.get_message(email_id)
    except Exception as e:
        log.error("email_adapter_get_message_failed", error=str(e))
        raise

    attachments = email_data.get('attachments', [])
    attachments_total = len(attachments)

    if attachments_total == 0:
        log.info("no_attachments_found")
        result = AttachmentExtractResult(
            extracted_count=0,
            failed_count=0,
            total_size_mb=0.0,
            filepaths=[]
        )
        result.generate_summaries(email_id=email_id, attachments_total=0)
        return result

    log.info("attachments_found", count=attachments_total)

    extracted_count = 0
    failed_count = 0
    total_size = 0
    filepaths = []

    # Créer répertoire zone transit (date du jour)
    date_dir = datetime.now().strftime('%Y-%m-%d')
    transit_dir = Path(TRANSIT_BASE_DIR) / date_dir
    transit_dir.mkdir(parents=True, exist_ok=True)

    # 2. Pour chaque attachment
    for idx, attachment in enumerate(attachments):
        attachment_id = attachment.get('id')
        mime_type = attachment.get('content_type', '').lower()
        size = attachment.get('size', 0)
        original_filename = attachment.get('filename', f'attachment_{idx}')

        log_ctx = log.bind(
            attachment_id=attachment_id,
            mime_type=mime_type,
            size=size,
            filename=original_filename
        )

        # Validation MIME type
        is_valid, reason = validate_mime_type(mime_type)

        if not is_valid:
            log_ctx.warning(
                "attachment_mime_rejected",
                reason=reason,
                mime_type=mime_type
            )
            failed_count += 1
            continue

        # Validation taille individuelle (A.8 : configurable via MAX_ATTACHMENT_SIZE_MB)
        if size > MAX_SINGLE_ATTACHMENT_BYTES:
            size_mb = size / (1024 * 1024)
            log_ctx.warning(
                "attachment_too_large",
                size_mb=round(size_mb, 2),
                max_mb=_max_attachment_size_mb,
            )
            failed_count += 1
            continue

        # Validation taille totale par email (A.8 : configurable via MAX_TOTAL_ATTACHMENTS_MB)
        if total_size + size > MAX_TOTAL_ATTACHMENTS_BYTES:
            size_mb = size / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            log_ctx.warning(
                "attachment_total_size_exceeded",
                current_total_mb=round(total_mb, 2),
                attachment_mb=round(size_mb, 2),
                max_total_mb=_max_total_attachments_mb,
                remaining_skipped=attachments_total - idx,
            )
            failed_count += attachments_total - idx
            break

        # Sanitization nom fichier
        sanitized_filename = sanitize_filename(original_filename)

        # Téléchargement via email adapter (D25: IMAP FETCH)
        try:
            file_content = await emailengine_client.download_attachment(
                email_id,
                attachment_id
            )
        except Exception as e:
            log_ctx.error("attachment_download_failed", error=str(e))
            failed_count += 1
            continue

        # Nom fichier sécurisé : {email_id}_{index}_{sanitized_filename}
        filename_safe = f"{email_id}_{idx}_{sanitized_filename}"
        filepath = transit_dir / filename_safe

        # Stockage fichier zone transit
        try:
            async with aiofiles.open(filepath, 'wb') as f:
                await f.write(file_content)

            log_ctx.info(
                "attachment_saved_transit",
                filepath=filepath.as_posix(),
                size_bytes=size
            )
        except Exception as e:
            log_ctx.error("attachment_save_failed", error=str(e), filepath=filepath.as_posix())
            failed_count += 1
            continue

        # INSERT métadonnées DB
        try:
            attachment_uuid = uuid.uuid4()

            await db_pool.execute(
                """
                INSERT INTO ingestion.attachments
                (id, email_id, filename, filepath, size_bytes, mime_type, status, extracted_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'pending', NOW())
                """,
                attachment_uuid,
                uuid.UUID(email_id),
                original_filename,  # Nom original (pas sanitisé) pour traçabilité
                filepath.as_posix(),
                size,
                mime_type
            )

            log_ctx.info(
                "attachment_metadata_inserted",
                attachment_uuid=str(attachment_uuid)
            )
        except Exception as e:
            log_ctx.error("attachment_db_insert_failed", error=str(e))
            # Supprimer fichier si INSERT échoue (cleanup)
            try:
                os.remove(filepath)
            except Exception:
                pass
            failed_count += 1
            continue

        # Publier événement Redis Streams document.received
        try:
            await _publish_document_received(
                attachment_id=str(attachment_uuid),
                email_id=email_id,
                filename=sanitized_filename,
                filepath=filepath.as_posix(),
                mime_type=mime_type,
                size_bytes=size,
                redis_client=redis_client
            )

            log_ctx.info("document_received_event_published")
        except Exception as e:
            log_ctx.error("redis_publish_failed", error=str(e))
            # Continue quand même (événement perdu, mais fichier + métadonnées OK)

        # Success
        extracted_count += 1
        total_size += size
        filepaths.append(filepath.as_posix())

    # 3. UPDATE ingestion.emails SET has_attachments=TRUE (si >=1 extraite)
    if extracted_count > 0:
        try:
            await db_pool.execute(
                "UPDATE ingestion.emails SET has_attachments=TRUE WHERE id=$1",
                uuid.UUID(email_id)
            )

            log.info("email_has_attachments_updated", extracted_count=extracted_count)
        except Exception as e:
            log.error("email_update_failed", error=str(e))

    # 4. Retourner ActionResult
    total_size_mb = round(total_size / (1024 * 1024), 2)

    result = AttachmentExtractResult(
        extracted_count=extracted_count,
        failed_count=failed_count,
        total_size_mb=total_size_mb,
        filepaths=filepaths
    )

    result.generate_summaries(
        email_id=email_id,
        attachments_total=attachments_total
    )

    log.info(
        "attachment_extraction_complete",
        extracted=extracted_count,
        failed=failed_count,
        total_size_mb=total_size_mb
    )

    return result


@retry(
    stop=stop_after_attempt(3),  # 1 original + 2 retries
    wait=wait_exponential(multiplier=1, min=1, max=2),  # Backoff: 1s, 2s
    retry=retry_if_exception_type(Exception),
    reraise=True
)
async def _publish_document_received(
    attachment_id: str,
    email_id: str,
    filename: str,
    filepath: str,
    mime_type: str,
    size_bytes: int,
    redis_client: Any
) -> None:
    """
    Publie événement document.received dans Redis Streams avec retry logic.

    Stream: document.received
    Consumer group: document-processor (Epic 3 - Archiviste)
    Maxlen: 10000 (rétention 10k events)

    Retry policy:
        - 3 tentatives max (1 original + 2 retries)
        - Backoff exponentiel : 1s, 2s
        - Retry sur toutes exceptions

    Args:
        attachment_id: UUID attachment (PK ingestion.attachments)
        email_id: UUID email source
        filename: Nom fichier sanitisé
        filepath: Chemin complet zone transit
        mime_type: Type MIME
        size_bytes: Taille bytes
        redis_client: Client Redis

    Raises:
        Exception si publication échoue après 3 tentatives
    """
    event_payload = {
        'attachment_id': attachment_id,
        'email_id': email_id,
        'filename': filename,
        'filepath': filepath,
        'mime_type': mime_type,
        'size_bytes': str(size_bytes),  # Redis Streams stocke strings
        'source': 'email'
    }

    # Publier dans Redis Streams avec maxlen (rétention 10k events)
    await redis_client.xadd(
        'document.received',
        event_payload,
        maxlen=10000
    )

    logger.info(
        "document_received_published",
        attachment_id=attachment_id,
        stream='document.received'
    )
