"""
Shared constants and utilities for batch processing.

Used by both bot/handlers/batch_commands.py and
agents/src/agents/archiviste/batch_processor.py
to avoid code duplication.
"""

from pathlib import Path


# ============================================================================
# Configuration
# ============================================================================

ALLOWED_ZONES = [
    r"C:\Users\lopez\Downloads",
    r"C:\Users\lopez\Desktop",
    r"C:\Users\lopez\BeeStation\Friday\Transit",
]

SYSTEM_FILE_EXTENSIONS = {".tmp", ".cache", ".log", ".bak"}

SYSTEM_FILE_NAMES = {"desktop.ini", ".ds_store", "thumbs.db"}

SYSTEM_FOLDERS = {".git", ".svn", "__pycache__", "node_modules"}


# ============================================================================
# Shared Utilities
# ============================================================================


def is_system_file(file_path: Path) -> bool:
    """
    Check if file is system/temporary file.

    System files:
    - .tmp, .cache, .log, .bak
    - ~$* (Office temp files)
    - desktop.ini, .DS_Store, thumbs.db
    - Inside .git/, .svn/, __pycache__/

    Args:
        file_path: File to check

    Returns:
        True if system file

    AC2: Skip fichiers système
    """
    name = file_path.name.lower()

    # Check extensions
    if file_path.suffix.lower() in SYSTEM_FILE_EXTENSIONS:
        return True

    # Check exact names
    if name in SYSTEM_FILE_NAMES:
        return True

    # Office temp files
    if name.startswith("~$"):
        return True

    # Check parent folders
    parts_lower = {p.lower() for p in file_path.parts}
    if parts_lower & SYSTEM_FOLDERS:
        return True

    return False
