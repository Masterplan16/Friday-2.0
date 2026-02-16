"""
Unit tests for batch commands handler.

Tests AC1 (Intent detection) and AC7 (Security validation).

Coverage:
- Intent detection via Claude Sonnet 4.5
- Path validation (traversal, zones autorisées)
- Confirmation workflow
- Filters options
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, User, Chat, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Import will fail initially (RED phase)
# from bot.handlers.batch_commands import (
#     detect_batch_intent,
#     validate_folder_path,
#     handle_batch_command,
#     count_files_recursive,
#     BatchRequest,
# )


# ============================================================================
# Test detect_batch_intent (AC1)
# ============================================================================


@pytest.mark.asyncio
@patch("bot.handlers.batch_commands.anthropic_client")
async def test_detect_batch_intent_downloads(mock_anthropic):
    """
    Test intent detection: "Range mes Downloads"

    AC1: détecte intention "traiter dossier batch"
    """
    # Mock Claude response
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"intent": "batch_process", "folder_path": "C:\\\\Users\\\\lopez\\\\Downloads", "confidence": 0.92}'
        )
    ]
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    # Import module (will fail in RED phase)
    from bot.handlers.batch_commands import detect_batch_intent

    # Test
    result = await detect_batch_intent("Range mes Downloads")

    # Assert
    assert result is not None
    assert result.folder_path == "C:\\Users\\lopez\\Downloads"
    assert result.confidence >= 0.85
    assert mock_anthropic.messages.create.called


@pytest.mark.asyncio
@patch("bot.handlers.batch_commands.anthropic_client")
async def test_detect_batch_intent_specific_path(mock_anthropic):
    """
    Test intent detection: chemin spécifique

    AC1: extraction chemin dossier
    """
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"intent": "batch_process", "folder_path": "C:\\\\Users\\\\lopez\\\\Desktop\\\\Scans", "confidence": 0.88}'
        )
    ]
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    from bot.handlers.batch_commands import detect_batch_intent

    result = await detect_batch_intent("Traite tous les fichiers dans C:\\Users\\lopez\\Desktop\\Scans")

    assert result is not None
    assert result.folder_path == "C:\\Users\\lopez\\Desktop\\Scans"
    assert result.confidence >= 0.85


@pytest.mark.asyncio
@patch("bot.handlers.batch_commands.anthropic_client")
async def test_detect_batch_intent_no_match(mock_anthropic):
    """
    Test intent detection: pas de match

    AC1: retourne None si intention non détectée
    """
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text='{"intent": "other", "confidence": 0.12}')
    ]
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    from bot.handlers.batch_commands import detect_batch_intent

    result = await detect_batch_intent("Bonjour, comment ça va ?")

    assert result is None


# ============================================================================
# Test validate_folder_path (AC7)
# ============================================================================


def test_validate_folder_path_allowed(tmp_path):
    """
    Test validation: path valide dans zone autorisée

    AC7: zones autorisées (Downloads, Desktop, Transit)
    """
    from bot.handlers.batch_commands import validate_folder_path

    # Create test folder
    test_folder = tmp_path / "Downloads"
    test_folder.mkdir()

    # Mock allowed zones to include tmp_path
    with patch("bot.handlers.batch_commands.ALLOWED_ZONES", [str(tmp_path)]):
        valid, result = validate_folder_path(str(test_folder))

    assert valid is True
    assert Path(result).exists()


def test_validate_folder_path_traversal():
    """
    Test validation: path traversal rejeté

    AC7: interdire ".." dans chemin
    """
    from bot.handlers.batch_commands import validate_folder_path

    path = "C:\\Users\\lopez\\Downloads\\..\\..\\Windows"
    valid, error = validate_folder_path(path)

    assert valid is False
    assert "traversal" in error.lower() or "autorisée" in error.lower()


def test_validate_folder_path_forbidden_zone():
    """
    Test validation: zone système rejetée

    AC7: interdire C:\\Windows\\
    """
    from bot.handlers.batch_commands import validate_folder_path

    path = "C:\\Windows\\System32"
    valid, error = validate_folder_path(path)

    assert valid is False
    assert "autorisée" in error.lower()


def test_validate_folder_path_not_exists():
    """
    Test validation: dossier introuvable

    AC7: vérifier accès lecture
    """
    from bot.handlers.batch_commands import validate_folder_path

    path = "C:\\Users\\lopez\\Downloads\\DOESNOTEXIST"
    valid, error = validate_folder_path(path)

    assert valid is False
    assert "introuvable" in error.lower()


def test_validate_folder_path_not_directory(tmp_path):
    """
    Test validation: chemin n'est pas un dossier

    AC7: doit être un dossier, pas un fichier
    """
    from bot.handlers.batch_commands import validate_folder_path

    # Create a file instead of folder
    test_file = tmp_path / "test.txt"
    test_file.write_text("test")

    valid, error = validate_folder_path(str(test_file))

    assert valid is False
    assert "dossier" in error.lower()


# ============================================================================
# Test handle_batch_command (AC1, AC7)
# ============================================================================


@pytest.mark.asyncio
@patch("bot.handlers.batch_commands.detect_batch_intent")
@patch("bot.handlers.batch_commands.validate_folder_path")
@patch("bot.handlers.batch_commands.count_files_recursive")
async def test_handle_batch_command_success(
    mock_count,
    mock_validate,
    mock_detect,
):
    """
    Test handler: commande batch réussie

    AC1: confirmation inline buttons [Lancer/Annuler/Options]
    """
    # Mocks
    mock_detect.return_value = MagicMock(
        folder_path="C:\\Users\\lopez\\Downloads",
        batch_id="batch_123",
        confidence=0.92,
    )
    mock_validate.return_value = (True, "C:\\Users\\lopez\\Downloads")
    mock_count.return_value = 42

    # Create mock update
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "Range mes Downloads"
    update.message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    # Import and call handler
    from bot.handlers.batch_commands import handle_batch_command

    await handle_batch_command(update, context)

    # Assert
    assert update.message.reply_text.called
    call_args = update.message.reply_text.call_args

    # Check message contains file count
    assert "42 fichiers" in call_args[0][0]

    # Check inline keyboard present
    assert "reply_markup" in call_args[1]
    keyboard = call_args[1]["reply_markup"]
    assert isinstance(keyboard, InlineKeyboardMarkup)


@pytest.mark.asyncio
@patch("bot.handlers.batch_commands.detect_batch_intent")
@patch("bot.handlers.batch_commands.validate_folder_path")
@patch("bot.handlers.batch_commands.count_files_recursive")
async def test_handle_batch_command_gt_1000_files(
    mock_count,
    mock_validate,
    mock_detect,
):
    """
    Test handler: quota 1000 fichiers dépassé

    AC7: max 1000 fichiers par batch
    """
    mock_detect.return_value = MagicMock(
        folder_path="C:\\Users\\lopez\\Downloads",
        batch_id="batch_123",
        confidence=0.92,
    )
    mock_validate.return_value = (True, "C:\\Users\\lopez\\Downloads")
    mock_count.return_value = 1234  # > 1000

    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "Range mes Downloads"
    update.message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    from bot.handlers.batch_commands import handle_batch_command

    await handle_batch_command(update, context)

    # Assert error message sent
    assert update.message.reply_text.called
    call_args = update.message.reply_text.call_args
    assert "1000" in call_args[0][0]
    assert "❌" in call_args[0][0]


@pytest.mark.asyncio
@patch("bot.handlers.batch_commands.detect_batch_intent")
@patch("bot.handlers.batch_commands.validate_folder_path")
@patch("bot.handlers.batch_commands.count_files_recursive")
async def test_handle_batch_command_gt_100_files_warning(
    mock_count,
    mock_validate,
    mock_detect,
):
    """
    Test handler: warning >100 fichiers

    AC7: confirmation explicite si >100 fichiers
    """
    mock_detect.return_value = MagicMock(
        folder_path="C:\\Users\\lopez\\Downloads",
        batch_id="batch_123",
        confidence=0.92,
    )
    mock_validate.return_value = (True, "C:\\Users\\lopez\\Downloads")
    mock_count.return_value = 234  # > 100 but < 1000

    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "Range mes Downloads"
    update.message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    from bot.handlers.batch_commands import handle_batch_command

    await handle_batch_command(update, context)

    # Assert warning message sent
    assert update.message.reply_text.called
    call_args = update.message.reply_text.call_args
    assert "234 fichiers" in call_args[0][0]
    assert "⚠️" in call_args[0][0]


@pytest.mark.asyncio
@patch("bot.handlers.batch_commands.detect_batch_intent")
@patch("bot.handlers.batch_commands.validate_folder_path")
async def test_handle_batch_command_invalid_path(
    mock_validate,
    mock_detect,
):
    """
    Test handler: path invalide

    AC7: rejeter path traversal
    """
    mock_detect.return_value = MagicMock(
        folder_path="C:\\Users\\lopez\\Downloads\\..\\..\\Windows",
        batch_id="batch_123",
        confidence=0.92,
    )
    mock_validate.return_value = (False, "Path traversal détecté")

    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "Range ../Windows"
    update.message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    from bot.handlers.batch_commands import handle_batch_command

    await handle_batch_command(update, context)

    # Assert error message sent
    assert update.message.reply_text.called
    call_args = update.message.reply_text.call_args
    assert "❌" in call_args[0][0]
    assert "traversal" in call_args[0][0].lower()


@pytest.mark.asyncio
@patch("bot.handlers.batch_commands.detect_batch_intent")
async def test_handle_batch_command_no_intent(mock_detect):
    """
    Test handler: pas d'intention batch détectée

    AC1: retourne sans action si pas intention batch
    """
    mock_detect.return_value = None

    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "Bonjour Friday"
    update.message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    from bot.handlers.batch_commands import handle_batch_command

    await handle_batch_command(update, context)

    # Assert no reply sent (handler returns early)
    assert not update.message.reply_text.called


# ============================================================================
# Test count_files_recursive (AC7)
# ============================================================================


def test_count_files_recursive_basic(tmp_path):
    """
    Test count: dossier avec fichiers

    AC7: scan récursif
    """
    from bot.handlers.batch_commands import count_files_recursive

    # Create test files
    (tmp_path / "file1.pdf").write_text("test")
    (tmp_path / "file2.png").write_text("test")
    subfolder = tmp_path / "subfolder"
    subfolder.mkdir()
    (subfolder / "file3.jpg").write_text("test")

    count = count_files_recursive(str(tmp_path), filters={})

    assert count == 3


def test_count_files_recursive_skip_system_files(tmp_path):
    """
    Test count: skip fichiers système

    AC2: skip .tmp, .cache, desktop.ini
    """
    from bot.handlers.batch_commands import count_files_recursive

    # Create test files
    (tmp_path / "valid.pdf").write_text("test")
    (tmp_path / "temp.tmp").write_text("test")
    (tmp_path / "cache.cache").write_text("test")
    (tmp_path / "desktop.ini").write_text("test")

    count = count_files_recursive(str(tmp_path), filters={})

    # Only valid.pdf should be counted
    assert count == 1
