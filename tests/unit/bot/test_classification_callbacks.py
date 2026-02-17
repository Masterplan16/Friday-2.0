"""
Tests unitaires callbacks classification documents (Story 3.2 Task 5.6).

Tests inline buttons : Approve, Correct, Reject, Reclassify, Finance perimeter
"""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def set_owner_user_id():
    """Patch OWNER_USER_ID pour tous les tests (user.id = 12345)."""
    with patch.dict(os.environ, {"OWNER_USER_ID": "12345"}):
        yield


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg pool."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.execute.return_value = "UPDATE 1"
    conn.fetchrow.return_value = {
        "payload": {"document_id": "doc-123", "category": "pro"},
        "module": "archiviste",
        "action_type": "classify",
        "output_summary": "pro",
        "confidence": 0.92,
    }
    return pool


@pytest.fixture
def mock_update():
    """Mock Telegram Update."""
    update = MagicMock()
    update.callback_query = AsyncMock()
    update.callback_query.from_user = MagicMock()
    update.callback_query.from_user.id = 12345
    update.callback_query.from_user.first_name = "Antonio"
    update.callback_query.message.text = "Original message"
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram context."""
    context = MagicMock()
    context.bot = AsyncMock()
    return context


# ==================== Tests Approve ====================


@pytest.mark.asyncio
@patch.dict(
    "os.environ", {"OWNER_USER_ID": "12345", "TOPIC_METRICS_ID": "0", "TELEGRAM_SUPERGROUP_ID": "0"}
)
async def test_approve_callback_success(mock_update, mock_context, mock_db_pool):
    """Test approbation classification réussie."""
    from bot.handlers.classification_callbacks import handle_classify_approve

    receipt_id = str(uuid.uuid4())
    mock_update.callback_query.data = f"classify_approve:{receipt_id}"

    await handle_classify_approve(mock_update, mock_context, mock_db_pool)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once()
    call_text = mock_update.callback_query.edit_message_text.call_args[0][0]
    assert "Classification approuvée" in call_text


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "99999"})
async def test_approve_callback_unauthorized(mock_update, mock_context, mock_db_pool):
    """Test approbation par utilisateur non autorisé."""
    from bot.handlers.classification_callbacks import handle_classify_approve

    mock_update.callback_query.data = f"classify_approve:{uuid.uuid4()}"

    await handle_classify_approve(mock_update, mock_context, mock_db_pool)

    mock_update.callback_query.answer.assert_called_with("Non autorisé", show_alert=True)


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_approve_callback_already_processed(mock_update, mock_context, mock_db_pool):
    """Test double-click : action déjà traitée."""
    from bot.handlers.classification_callbacks import handle_classify_approve

    # Simuler UPDATE 0 (pas de ligne affectée)
    conn = await mock_db_pool.acquire().__aenter__()
    conn.execute.return_value = "UPDATE 0"

    receipt_id = str(uuid.uuid4())
    mock_update.callback_query.data = f"classify_approve:{receipt_id}"

    await handle_classify_approve(mock_update, mock_context, mock_db_pool)

    mock_update.callback_query.answer.assert_any_call(
        "Action déjà traitée ou introuvable", show_alert=True
    )


# ==================== Tests Reject ====================


@pytest.mark.asyncio
@patch.dict(
    "os.environ", {"OWNER_USER_ID": "12345", "TOPIC_METRICS_ID": "0", "TELEGRAM_SUPERGROUP_ID": "0"}
)
async def test_reject_callback_success(mock_update, mock_context, mock_db_pool):
    """Test rejet classification réussi."""
    from bot.handlers.classification_callbacks import handle_classify_reject

    receipt_id = str(uuid.uuid4())
    mock_update.callback_query.data = f"classify_reject:{receipt_id}"

    await handle_classify_reject(mock_update, mock_context, mock_db_pool)

    mock_update.callback_query.answer.assert_called_once()
    call_text = mock_update.callback_query.edit_message_text.call_args[0][0]
    assert "rejetée" in call_text


# ==================== Tests Correct ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_correct_callback_shows_categories(mock_update, mock_context, mock_db_pool):
    """Test correction affiche la liste des catégories."""
    from bot.handlers.classification_callbacks import handle_classify_correct

    receipt_id = str(uuid.uuid4())
    mock_update.callback_query.data = f"classify_correct:{receipt_id}"

    await handle_classify_correct(mock_update, mock_context, mock_db_pool)

    mock_update.callback_query.edit_message_text.assert_called_once()
    call_kwargs = mock_update.callback_query.edit_message_text.call_args
    assert call_kwargs.kwargs.get("reply_markup") is not None


# ==================== Tests Reclassify ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_reclassify_finance_shows_perimeters(mock_update, mock_context, mock_db_pool):
    """Test reclassification finance affiche les périmètres."""
    from bot.handlers.classification_callbacks import handle_classify_reclassify

    receipt_id = str(uuid.uuid4())
    mock_update.callback_query.data = f"classify_reclassify:{receipt_id}:finance"

    await handle_classify_reclassify(mock_update, mock_context, mock_db_pool)

    call_kwargs = mock_update.callback_query.edit_message_text.call_args
    assert "périmètre finance" in call_kwargs[0][0].lower()
    assert call_kwargs.kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_reclassify_non_finance_applies_directly(mock_update, mock_context, mock_db_pool):
    """Test reclassification non-finance appliquée directement."""
    from bot.handlers.classification_callbacks import handle_classify_reclassify

    receipt_id = str(uuid.uuid4())
    mock_update.callback_query.data = f"classify_reclassify:{receipt_id}:pro"

    await handle_classify_reclassify(mock_update, mock_context, mock_db_pool)

    call_text = mock_update.callback_query.edit_message_text.call_args[0][0]
    assert "corrigée" in call_text.lower()


# ==================== Tests Finance Perimeter ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_finance_perimeter_valid(mock_update, mock_context, mock_db_pool):
    """Test sélection périmètre finance valide."""
    from bot.handlers.classification_callbacks import handle_classify_finance

    receipt_id = str(uuid.uuid4())
    mock_update.callback_query.data = f"classify_finance:{receipt_id}:selarl"

    await handle_classify_finance(mock_update, mock_context, mock_db_pool)

    call_text = mock_update.callback_query.edit_message_text.call_args[0][0]
    assert "SELARL" in call_text


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_finance_perimeter_invalid_rejected(mock_update, mock_context, mock_db_pool):
    """Test AC6 : périmètre finance invalide rejeté."""
    from bot.handlers.classification_callbacks import handle_classify_finance

    receipt_id = str(uuid.uuid4())
    mock_update.callback_query.data = f"classify_finance:{receipt_id}:invalid"

    await handle_classify_finance(mock_update, mock_context, mock_db_pool)

    mock_update.callback_query.answer.assert_any_call(
        "Périmètre invalide : invalid", show_alert=True
    )


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_all_five_finance_perimeters_accepted(mock_update, mock_context, mock_db_pool):
    """Test AC6 : les 5 périmètres finance valides sont acceptés."""
    from bot.handlers.classification_callbacks import handle_classify_finance

    valid_perimeters = ["selarl", "scm", "sci_ravas", "sci_malbosc", "personal"]

    for perimeter in valid_perimeters:
        receipt_id = str(uuid.uuid4())
        mock_update.callback_query.data = f"classify_finance:{receipt_id}:{perimeter}"
        mock_update.callback_query.answer.reset_mock()
        mock_update.callback_query.edit_message_text.reset_mock()

        # Reset mock DB pour éviter UPDATE 0
        conn = await mock_db_pool.acquire().__aenter__()
        conn.execute.return_value = "UPDATE 1"

        await handle_classify_finance(mock_update, mock_context, mock_db_pool)

        # Pas d'alerte "Périmètre invalide"
        for call in mock_update.callback_query.answer.call_args_list:
            if call.args:
                assert "invalide" not in call.args[0].lower()


# ==================== Tests Notification Formatting ====================


def test_format_classification_message_pro():
    """Test formatage message notification pro."""
    from bot.handlers.classification_notifications import _format_classification_message

    data = {
        "document_id": "doc-123",
        "category": "pro",
        "subcategory": None,
        "path": "pro/administratif",
        "confidence": 0.92,
        "reasoning": "Courrier ARS",
    }

    message = _format_classification_message(data)

    assert "Document classifié" in message
    assert "doc-123" in message
    assert "Professionnel" in message
    assert "92%" in message


def test_format_classification_message_finance():
    """Test formatage message notification finance avec subcategory."""
    from bot.handlers.classification_notifications import _format_classification_message

    data = {
        "document_id": "doc-456",
        "category": "finance",
        "subcategory": "selarl",
        "path": "finance/selarl",
        "confidence": 0.94,
        "reasoning": "Facture Cerba",
    }

    message = _format_classification_message(data)

    assert "Finance" in message
    assert "SELARL" in message
    assert "94%" in message


def test_html_escape():
    """Test échappement HTML."""
    from bot.handlers.classification_notifications import _html_escape

    assert _html_escape("<script>") == "&lt;script&gt;"
    assert _html_escape("a & b") == "a &amp; b"
    assert _html_escape('"hello"') == "&quot;hello&quot;"


def test_create_classification_keyboard():
    """Test création keyboard avec 3 boutons."""
    from bot.handlers.classification_notifications import _create_classification_keyboard

    keyboard = _create_classification_keyboard("test-receipt-123")

    buttons = []
    for row in keyboard.inline_keyboard:
        for btn in row:
            buttons.append(btn)

    assert len(buttons) == 3
    assert any("Approuver" in b.text for b in buttons)
    assert any("Corriger" in b.text for b in buttons)
    assert any("Rejeter" in b.text for b in buttons)


def test_create_finance_perimeter_keyboard():
    """Test création keyboard périmètres finance."""
    from bot.handlers.classification_notifications import _create_finance_perimeter_keyboard

    keyboard = _create_finance_perimeter_keyboard("test-receipt-123")

    buttons = []
    for row in keyboard.inline_keyboard:
        for btn in row:
            buttons.append(btn)

    # 5 périmètres + 1 bouton retour
    assert len(buttons) == 6
    labels = [b.text for b in buttons]
    assert "SELARL" in labels
    assert "SCM" in labels
    assert "SCI Ravas" in labels
    assert "SCI Malbosc" in labels
    assert "Personnel" in labels
