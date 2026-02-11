"""
Tests unitaires pour config/mime_types.py.

Valide :
- Whitelist ALLOWED_MIME_TYPES
- Blacklist BLOCKED_MIME_TYPES
- Helper functions (is_mime_allowed, is_mime_blocked, validate_mime_type, get_mime_category)
"""

import pytest
from agents.src.config.mime_types import (
    ALLOWED_MIME_TYPES,
    BLOCKED_MIME_TYPES,
    is_mime_allowed,
    is_mime_blocked,
    validate_mime_type,
    get_mime_category
)


class TestMimeTypesWhitelist:
    """Tests ALLOWED_MIME_TYPES whitelist."""

    def test_allowed_pdf(self):
        """PDF autorisé."""
        assert 'application/pdf' in ALLOWED_MIME_TYPES

    def test_allowed_images(self):
        """Images autorisées (JPEG, PNG, GIF, WebP)."""
        assert 'image/jpeg' in ALLOWED_MIME_TYPES
        assert 'image/jpg' in ALLOWED_MIME_TYPES
        assert 'image/png' in ALLOWED_MIME_TYPES
        assert 'image/gif' in ALLOWED_MIME_TYPES
        assert 'image/webp' in ALLOWED_MIME_TYPES

    def test_allowed_office_modern(self):
        """Office moderne (DOCX/XLSX/PPTX) autorisé."""
        assert 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in ALLOWED_MIME_TYPES
        assert 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' in ALLOWED_MIME_TYPES
        assert 'application/vnd.openxmlformats-officedocument.presentationml.presentation' in ALLOWED_MIME_TYPES

    def test_allowed_office_legacy(self):
        """Office legacy (DOC/XLS/PPT) autorisé."""
        assert 'application/msword' in ALLOWED_MIME_TYPES
        assert 'application/vnd.ms-excel' in ALLOWED_MIME_TYPES
        assert 'application/vnd.ms-powerpoint' in ALLOWED_MIME_TYPES

    def test_allowed_text_files(self):
        """Text files (TXT, CSV, HTML) autorisés."""
        assert 'text/plain' in ALLOWED_MIME_TYPES
        assert 'text/csv' in ALLOWED_MIME_TYPES
        assert 'text/html' in ALLOWED_MIME_TYPES

    def test_allowed_opendocument(self):
        """OpenDocument (ODT/ODS/ODP) autorisé."""
        assert 'application/vnd.oasis.opendocument.text' in ALLOWED_MIME_TYPES
        assert 'application/vnd.oasis.opendocument.spreadsheet' in ALLOWED_MIME_TYPES
        assert 'application/vnd.oasis.opendocument.presentation' in ALLOWED_MIME_TYPES


class TestMimeTypesBlacklist:
    """Tests BLOCKED_MIME_TYPES blacklist."""

    def test_blocked_executables_windows(self):
        """Exécutables Windows bloqués (.exe)."""
        assert 'application/x-msdownload' in BLOCKED_MIME_TYPES
        assert 'application/x-msdos-program' in BLOCKED_MIME_TYPES
        assert 'application/vnd.microsoft.portable-executable' in BLOCKED_MIME_TYPES

    def test_blocked_executables_unix(self):
        """Exécutables Unix bloqués (ELF, .so)."""
        assert 'application/x-executable' in BLOCKED_MIME_TYPES
        assert 'application/x-sharedlib' in BLOCKED_MIME_TYPES

    def test_blocked_scripts(self):
        """Scripts bloqués (.sh, .py, .js)."""
        assert 'application/x-sh' in BLOCKED_MIME_TYPES
        assert 'application/x-bash' in BLOCKED_MIME_TYPES
        assert 'application/x-python-code' in BLOCKED_MIME_TYPES
        assert 'application/javascript' in BLOCKED_MIME_TYPES
        assert 'text/x-python' in BLOCKED_MIME_TYPES

    def test_blocked_archives(self):
        """Archives bloquées (.zip, .rar, .7z, .tar, .gz)."""
        assert 'application/zip' in BLOCKED_MIME_TYPES
        assert 'application/x-zip-compressed' in BLOCKED_MIME_TYPES
        assert 'application/x-rar-compressed' in BLOCKED_MIME_TYPES
        assert 'application/x-7z-compressed' in BLOCKED_MIME_TYPES
        assert 'application/x-tar' in BLOCKED_MIME_TYPES
        assert 'application/gzip' in BLOCKED_MIME_TYPES
        assert 'application/x-bzip2' in BLOCKED_MIME_TYPES

    def test_blocked_videos(self):
        """Vidéos lourdes bloquées (.mp4, .avi, .mkv, .mov)."""
        assert 'video/mp4' in BLOCKED_MIME_TYPES
        assert 'video/mpeg' in BLOCKED_MIME_TYPES
        assert 'video/x-msvideo' in BLOCKED_MIME_TYPES
        assert 'video/x-matroska' in BLOCKED_MIME_TYPES
        assert 'video/quicktime' in BLOCKED_MIME_TYPES

    def test_blocked_other_risky(self):
        """Autres types à risque bloqués (.jar, .apk)."""
        assert 'application/x-java-archive' in BLOCKED_MIME_TYPES
        assert 'application/vnd.android.package-archive' in BLOCKED_MIME_TYPES


class TestIsMimeAllowed:
    """Tests helper is_mime_allowed()."""

    def test_is_mime_allowed_pdf(self):
        """PDF autorisé."""
        assert is_mime_allowed('application/pdf') is True

    def test_is_mime_allowed_image(self):
        """Images autorisées."""
        assert is_mime_allowed('image/jpeg') is True
        assert is_mime_allowed('image/png') is True

    def test_is_mime_allowed_case_insensitive(self):
        """is_mime_allowed() case insensitive."""
        assert is_mime_allowed('APPLICATION/PDF') is True
        assert is_mime_allowed('Image/JPEG') is True
        assert is_mime_allowed('TEXT/PLAIN') is True

    def test_is_mime_allowed_whitespace_trimmed(self):
        """is_mime_allowed() trim espaces."""
        assert is_mime_allowed('  application/pdf  ') is True
        assert is_mime_allowed('\timage/png\n') is True

    def test_is_mime_allowed_blocked_type(self):
        """Type bloqué retourne False."""
        assert is_mime_allowed('application/zip') is False
        assert is_mime_allowed('application/x-msdownload') is False

    def test_is_mime_allowed_unknown_type(self):
        """Type inconnu retourne False (sécurité)."""
        assert is_mime_allowed('application/unknown') is False
        assert is_mime_allowed('video/mp4') is False  # Vidéo = blocked


class TestIsMimeBlocked:
    """Tests helper is_mime_blocked()."""

    def test_is_mime_blocked_executable(self):
        """Exécutables bloqués."""
        assert is_mime_blocked('application/x-msdownload') is True
        assert is_mime_blocked('application/x-executable') is True

    def test_is_mime_blocked_archive(self):
        """Archives bloquées."""
        assert is_mime_blocked('application/zip') is True
        assert is_mime_blocked('application/x-rar-compressed') is True

    def test_is_mime_blocked_case_insensitive(self):
        """is_mime_blocked() case insensitive."""
        assert is_mime_blocked('APPLICATION/ZIP') is True
        assert is_mime_blocked('Video/MP4') is True

    def test_is_mime_blocked_allowed_type(self):
        """Type autorisé retourne False."""
        assert is_mime_blocked('application/pdf') is False
        assert is_mime_blocked('image/jpeg') is False

    def test_is_mime_blocked_unknown_type(self):
        """Type inconnu retourne False (pas explicitement bloqué)."""
        assert is_mime_blocked('application/unknown') is False


class TestValidateMimeType:
    """Tests helper validate_mime_type()."""

    def test_validate_mime_type_allowed(self):
        """Type autorisé retourne (True, 'allowed')."""
        is_valid, reason = validate_mime_type('application/pdf')
        assert is_valid is True
        assert reason == 'allowed'

        is_valid, reason = validate_mime_type('image/jpeg')
        assert is_valid is True
        assert reason == 'allowed'

    def test_validate_mime_type_blocked(self):
        """Type bloqué retourne (False, 'blocked')."""
        is_valid, reason = validate_mime_type('application/zip')
        assert is_valid is False
        assert reason == 'blocked'

        is_valid, reason = validate_mime_type('application/x-msdownload')
        assert is_valid is False
        assert reason == 'blocked'

    def test_validate_mime_type_unknown(self):
        """Type inconnu retourne (False, 'unknown')."""
        is_valid, reason = validate_mime_type('application/unknown-type')
        assert is_valid is False
        assert reason == 'unknown'

    def test_validate_mime_type_priority_blocked_over_allowed(self):
        """Blacklist prioritaire sur whitelist (sécurité)."""
        # Si un type est dans BOTH (hypothétique), blacklist gagne
        # Test avec type effectivement bloqué
        is_valid, reason = validate_mime_type('video/mp4')
        assert is_valid is False
        assert reason == 'blocked'


class TestGetMimeCategory:
    """Tests helper get_mime_category()."""

    def test_get_mime_category_pdf(self):
        """PDF → catégorie 'pdf'."""
        assert get_mime_category('application/pdf') == 'pdf'

    def test_get_mime_category_images(self):
        """Images → catégorie 'image'."""
        assert get_mime_category('image/jpeg') == 'image'
        assert get_mime_category('image/png') == 'image'
        assert get_mime_category('image/gif') == 'image'

    def test_get_mime_category_office(self):
        """Office docs → catégorie 'office'."""
        assert get_mime_category('application/vnd.openxmlformats-officedocument.wordprocessingml.document') == 'office'
        assert get_mime_category('application/msword') == 'office'
        assert get_mime_category('application/vnd.oasis.opendocument.text') == 'office'

    def test_get_mime_category_text(self):
        """Text files → catégorie 'text'."""
        assert get_mime_category('text/plain') == 'text'
        assert get_mime_category('text/csv') == 'text'
        assert get_mime_category('text/html') == 'text'

    def test_get_mime_category_archive(self):
        """Archives → catégorie 'archive'."""
        assert get_mime_category('application/zip') == 'archive'
        assert get_mime_category('application/x-rar-compressed') == 'archive'
        assert get_mime_category('application/x-7z-compressed') == 'archive'

    def test_get_mime_category_executable(self):
        """Exécutables → catégorie 'executable'."""
        assert get_mime_category('application/x-msdownload') == 'executable'
        assert get_mime_category('application/x-executable') == 'executable'
        assert get_mime_category('application/x-sh') == 'executable'

    def test_get_mime_category_video(self):
        """Vidéos → catégorie 'video'."""
        assert get_mime_category('video/mp4') == 'video'
        assert get_mime_category('video/mpeg') == 'video'
        assert get_mime_category('video/quicktime') == 'video'

    def test_get_mime_category_unknown(self):
        """Type inconnu → catégorie 'unknown'."""
        assert get_mime_category('application/unknown-type') == 'unknown'
        assert get_mime_category('foo/bar') == 'unknown'
