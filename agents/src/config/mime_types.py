"""
Configuration MIME types pour validation pièces jointes.

Story 2.4 - Extraction Pièces Jointes

Whitelist : Types autorisés Day 1 (PDF, images, Office docs)
Blacklist : Types dangereux (exécutables, archives, vidéos lourdes)
"""

# =====================================================================
# ALLOWED MIME TYPES (Whitelist Day 1)
# =====================================================================
# Types autorisés couvrent ~95% des PJ emails Mainteneur :
# - Factures PDF
# - Scans/photos documents (JPG, PNG)
# - Courriers Office (DOCX, XLSX, PPTX)

ALLOWED_MIME_TYPES = {
    # PDF
    'application/pdf',

    # Images
    'image/jpeg',
    'image/jpg',  # Alias JPEG
    'image/png',
    'image/gif',
    'image/webp',

    # Microsoft Office (OpenXML format)
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOCX
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # XLSX
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # PPTX

    # Microsoft Office (Legacy format - si nécessaire)
    'application/msword',  # DOC
    'application/vnd.ms-excel',  # XLS
    'application/vnd.ms-powerpoint',  # PPT

    # Text files
    'text/plain',  # TXT
    'text/csv',  # CSV
    'text/html',  # HTML

    # OpenDocument (LibreOffice)
    'application/vnd.oasis.opendocument.text',  # ODT
    'application/vnd.oasis.opendocument.spreadsheet',  # ODS
    'application/vnd.oasis.opendocument.presentation',  # ODP
}

# =====================================================================
# BLOCKED MIME TYPES (Blacklist - Sécurité)
# =====================================================================
# Types dangereux JAMAIS acceptés :
# - Exécutables (malware risk)
# - Archives (peuvent contenir exécutables)
# - Scripts (injection risk)
# - Vidéos lourdes (>10 Mo, saturation disque)

BLOCKED_MIME_TYPES = {
    # Exécutables Windows
    'application/x-msdownload',  # .exe
    'application/x-msdos-program',  # .com
    'application/x-ms-dos-executable',  # .exe variants
    'application/vnd.microsoft.portable-executable',  # PE format

    # Exécutables Unix/Linux
    'application/x-executable',  # ELF binaries
    'application/x-sharedlib',  # .so libraries

    # Scripts
    'application/x-sh',  # Shell scripts (.sh)
    'application/x-bash',  # Bash scripts
    'application/x-python-code',  # Python bytecode
    'application/javascript',  # JS (risk XSS si exécuté)
    'text/x-python',  # Python scripts

    # Archives (peuvent contenir malware)
    'application/zip',  # .zip
    'application/x-zip-compressed',  # .zip variants
    'application/x-rar-compressed',  # .rar
    'application/x-7z-compressed',  # .7z
    'application/x-tar',  # .tar
    'application/gzip',  # .gz
    'application/x-bzip2',  # .bz2

    # Vidéos lourdes (saturation disque VPS)
    'video/mp4',  # .mp4
    'video/mpeg',  # .mpeg
    'video/x-msvideo',  # .avi
    'video/x-matroska',  # .mkv
    'video/quicktime',  # .mov

    # Autres types à risque
    'application/x-java-archive',  # .jar (peut contenir malware)
    'application/vnd.android.package-archive',  # .apk
    'application/x-ms-application',  # .application (ClickOnce)
}

# =====================================================================
# HELPER FUNCTIONS
# =====================================================================


def is_mime_allowed(mime_type: str) -> bool:
    """
    Vérifie si MIME type est autorisé (whitelist).

    Args:
        mime_type: Type MIME à vérifier (ex: "application/pdf")

    Returns:
        True si autorisé, False sinon
    """
    mime_normalized = mime_type.lower().strip()
    return mime_normalized in ALLOWED_MIME_TYPES


def is_mime_blocked(mime_type: str) -> bool:
    """
    Vérifie si MIME type est explicitement bloqué (blacklist).

    Args:
        mime_type: Type MIME à vérifier

    Returns:
        True si bloqué, False sinon
    """
    mime_normalized = mime_type.lower().strip()
    return mime_normalized in BLOCKED_MIME_TYPES


def validate_mime_type(mime_type: str) -> tuple[bool, str]:
    """
    Valide MIME type avec whitelist/blacklist.

    Args:
        mime_type: Type MIME à valider

    Returns:
        Tuple (is_valid, reason):
        - is_valid: True si autorisé, False sinon
        - reason: Raison du rejet ("allowed", "blocked", "unknown")
    """
    mime_normalized = mime_type.lower().strip()

    # Check blacklist (priorité haute - sécurité)
    if mime_normalized in BLOCKED_MIME_TYPES:
        return False, "blocked"

    # Check whitelist
    if mime_normalized in ALLOWED_MIME_TYPES:
        return True, "allowed"

    # Type inconnu (ni allowed ni blocked) → reject par défaut (sécurité)
    return False, "unknown"


def get_mime_category(mime_type: str) -> str:
    """
    Retourne catégorie MIME type (document, image, office, text).

    Args:
        mime_type: Type MIME

    Returns:
        Catégorie: "pdf", "image", "office", "text", "archive", "executable", "video", "unknown"
    """
    mime_normalized = mime_type.lower().strip()

    if mime_normalized == 'application/pdf':
        return "pdf"

    if mime_normalized.startswith('image/'):
        return "image"

    if 'word' in mime_normalized or 'excel' in mime_normalized or 'powerpoint' in mime_normalized:
        return "office"

    if 'opendocument' in mime_normalized:
        return "office"

    if mime_normalized.startswith('text/'):
        return "text"

    if 'zip' in mime_normalized or 'rar' in mime_normalized or 'tar' in mime_normalized or '7z' in mime_normalized:
        return "archive"

    if 'executable' in mime_normalized or 'msdownload' in mime_normalized or 'x-sh' in mime_normalized:
        return "executable"

    if mime_normalized.startswith('video/'):
        return "video"

    return "unknown"


# =====================================================================
# MIME TYPES STATS (Debug/Monitoring)
# =====================================================================

MIME_STATS = {
    "allowed_count": len(ALLOWED_MIME_TYPES),
    "blocked_count": len(BLOCKED_MIME_TYPES),
    "categories": {
        "pdf": 1,
        "images": 5,
        "office_modern": 3,
        "office_legacy": 3,
        "text": 3,
        "opendocument": 3,
    }
}
