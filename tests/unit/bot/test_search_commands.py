#!/usr/bin/env python3
"""
Tests unitaires pour Telegram /search command (Story 3.3 - Task 5).

Tests:
- /search sans query → message usage
- /search avec query → résultats formatés
- /search avec filtres --category=finance
- Callback details inline button
- Parse query et filtres
- Aucun résultat → message approprié
- Erreur DB → message erreur

Date: 2026-02-16
Story: 3.3 - Task 5
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from bot.handlers.search_commands import (
    _parse_query_and_filters,
    search_command,
    search_details_callback,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_update():
    """Fixture Telegram Update mock."""
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Fixture Telegram CallbackContext mock."""
    context = MagicMock()
    context.args = []
    context.bot_data = {}
    return context


@pytest.fixture
def mock_search_results():
    """Fixture SearchResult list mock."""
    from agents.src.agents.archiviste.models import SearchResult

    return [
        SearchResult(
            document_id=str(uuid4()),
            title="2026-01-15_Facture_Plombier_350EUR.pdf",
            path=r"C:\Users\lopez\BeeStation\Friday\Archives\finance\selarl\facture.pdf",
            score=0.92,
            excerpt="Facture plomberie travaux salle de bain...",
            metadata={"category": "finance", "subcategory": "selarl"},
        ),
        SearchResult(
            document_id=str(uuid4()),
            title="2026-02-01_Facture_Electricien_200EUR.pdf",
            path=r"C:\Users\lopez\BeeStation\Friday\Archives\finance\selarl\elec.pdf",
            score=0.78,
            excerpt="Facture electricien installation prises...",
            metadata={"category": "finance", "subcategory": "selarl"},
        ),
    ]


# ============================================================
# Test 1: /search sans arguments → message usage
# ============================================================


@pytest.mark.asyncio
async def test_search_no_args_shows_usage(mock_update, mock_context):
    """Test /search sans query affiche message d'aide."""
    mock_context.args = []

    await search_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    message = call_args[0][0]
    assert "Usage" in message
    assert "/search" in message


# ============================================================
# Test 2: /search avec résultats
# ============================================================


@pytest.mark.asyncio
async def test_search_with_results(mock_update, mock_context, mock_search_results):
    """Test /search retourne tous les résultats formatés."""
    mock_context.args = ["facture", "plombier"]
    mock_context.bot_data = {"db_pool": AsyncMock()}

    status_msg = AsyncMock()
    mock_update.message.reply_text.side_effect = [status_msg, None]

    with patch(
        "bot.handlers.search_commands.SemanticSearcher"
    ) as MockSearcher:
        mock_searcher = AsyncMock()
        mock_searcher.search.return_value = mock_search_results
        MockSearcher.return_value = mock_searcher

        await search_command(mock_update, mock_context)

    # Status message supprimé
    status_msg.delete.assert_called_once()

    # Réponse finale avec résultats
    final_call = mock_update.message.reply_text.call_args_list[-1]
    response_text = final_call[0][0]

    # Vérifie TOUS les résultats affichés
    assert "Facture_Plombier" in response_text
    assert "Facture_Electricien" in response_text
    assert "92%" in response_text
    assert "78%" in response_text
    assert "2 documents" in response_text


# ============================================================
# Test 3: /search sans résultats
# ============================================================


@pytest.mark.asyncio
async def test_search_no_results(mock_update, mock_context):
    """Test /search sans résultats affiche message approprié."""
    mock_context.args = ["xyz", "introuvable"]
    mock_context.bot_data = {"db_pool": AsyncMock()}

    status_msg = AsyncMock()
    mock_update.message.reply_text.side_effect = [status_msg, None]

    with patch(
        "bot.handlers.search_commands.SemanticSearcher"
    ) as MockSearcher:
        mock_searcher = AsyncMock()
        mock_searcher.search.return_value = []
        MockSearcher.return_value = mock_searcher

        await search_command(mock_update, mock_context)

    status_msg.delete.assert_called_once()

    final_call = mock_update.message.reply_text.call_args_list[-1]
    response_text = final_call[0][0]
    assert "Aucun" in response_text


# ============================================================
# Test 4: /search sans db_pool → erreur service
# ============================================================


@pytest.mark.asyncio
async def test_search_no_db_pool(mock_update, mock_context):
    """Test /search sans db_pool affiche erreur service."""
    mock_context.args = ["facture"]
    mock_context.bot_data = {}  # Pas de db_pool

    await search_command(mock_update, mock_context)

    call_args = mock_update.message.reply_text.call_args
    assert "indisponible" in call_args[0][0]


# ============================================================
# Test 5: Parse query et filtres
# ============================================================


def test_parse_query_simple():
    """Test parse query simple sans filtres."""
    query, filters = _parse_query_and_filters("facture plombier 2026")
    assert query == "facture plombier 2026"
    assert filters == {}


def test_parse_query_with_category_filter():
    """Test parse query avec filtre --category."""
    query, filters = _parse_query_and_filters(
        "facture plombier --category=finance"
    )
    assert query == "facture plombier"
    assert filters == {"category": "finance"}


def test_parse_query_with_multiple_filters():
    """Test parse query avec filtres multiples."""
    query, filters = _parse_query_and_filters(
        "facture --category=finance --after=2026-01-01 --before=2026-12-31"
    )
    assert query == "facture"
    assert filters["category"] == "finance"
    assert filters["after"] == "2026-01-01"
    assert filters["before"] == "2026-12-31"


def test_parse_query_empty_returns_empty():
    """Test parse query vide."""
    query, filters = _parse_query_and_filters("--category=finance")
    assert query == ""
    assert filters == {"category": "finance"}


# ============================================================
# Test 6: Erreur recherche → message erreur technique
# ============================================================


@pytest.mark.asyncio
async def test_search_exception_shows_error(mock_update, mock_context):
    """Test exception technique affiche message erreur générique."""
    mock_context.args = ["facture"]
    mock_context.bot_data = {"db_pool": AsyncMock()}

    status_msg = AsyncMock()
    mock_update.message.reply_text.side_effect = [status_msg, None]

    with patch(
        "bot.handlers.search_commands.SemanticSearcher"
    ) as MockSearcher:
        mock_searcher = AsyncMock()
        mock_searcher.search.side_effect = Exception("DB connection lost")
        MockSearcher.return_value = mock_searcher

        await search_command(mock_update, mock_context)

    final_call = mock_update.message.reply_text.call_args_list[-1]
    response_text = final_call[0][0]
    assert "Erreur" in response_text


# ============================================================
# Test 7: Callback details avec UUID valide
# ============================================================


@pytest.mark.asyncio
async def test_details_callback_valid_uuid():
    """Test callback details avec UUID valide."""
    doc_id = uuid4()

    update = MagicMock()
    callback_query = AsyncMock()
    callback_query.data = f"search:details:{doc_id}"
    callback_query.answer = AsyncMock()
    callback_query.edit_message_text = AsyncMock()
    update.callback_query = callback_query

    context = MagicMock()
    db_pool = AsyncMock()
    db_pool.fetchrow.return_value = {
        "original_filename": "facture.pdf",
        "final_path": r"C:\Archives\facture.pdf",
        "classification_category": "finance",
        "classification_subcategory": "selarl",
        "classification_confidence": 0.95,
        "created_at": datetime(2026, 2, 16, 10, 30),
    }
    context.bot_data = {"db_pool": db_pool}

    await search_details_callback(update, context)

    callback_query.answer.assert_called_once()
    callback_query.edit_message_text.assert_called_once()

    details = callback_query.edit_message_text.call_args[0][0]
    assert "facture.pdf" in details
    assert "finance" in details
    assert "95%" in details


# ============================================================
# Test 8: Callback details avec UUID invalide
# ============================================================


@pytest.mark.asyncio
async def test_details_callback_invalid_uuid():
    """Test callback details avec UUID invalide."""
    update = MagicMock()
    callback_query = AsyncMock()
    callback_query.data = "search:details:not-a-uuid"
    callback_query.answer = AsyncMock()
    callback_query.edit_message_text = AsyncMock()
    update.callback_query = callback_query

    context = MagicMock()
    context.bot_data = {"db_pool": AsyncMock()}

    await search_details_callback(update, context)

    callback_query.edit_message_text.assert_called_once()
    msg = callback_query.edit_message_text.call_args[0][0]
    assert "invalide" in msg


# ============================================================
# Test 9: Callback details format invalide
# ============================================================


@pytest.mark.asyncio
async def test_details_callback_invalid_format():
    """Test callback avec format data invalide."""
    update = MagicMock()
    callback_query = AsyncMock()
    callback_query.data = "wrong:format"
    callback_query.answer = AsyncMock()
    callback_query.edit_message_text = AsyncMock()
    update.callback_query = callback_query

    context = MagicMock()

    await search_details_callback(update, context)

    callback_query.edit_message_text.assert_called_once()
    msg = callback_query.edit_message_text.call_args[0][0]
    assert "invalide" in msg


# ============================================================
# Test 10: Validation erreur → message erreur spécifique
# ============================================================


@pytest.mark.asyncio
async def test_search_validation_error(mock_update, mock_context):
    """Test ValueError affiche message erreur spécifique."""
    mock_context.args = ["facture"]
    mock_context.bot_data = {"db_pool": AsyncMock()}

    status_msg = AsyncMock()
    mock_update.message.reply_text.side_effect = [status_msg, None]

    with patch(
        "bot.handlers.search_commands.SemanticSearcher"
    ) as MockSearcher:
        mock_searcher = AsyncMock()
        mock_searcher.search.side_effect = ValueError("top_k must be between 1 and 100")
        MockSearcher.return_value = mock_searcher

        await search_command(mock_update, mock_context)

    final_call = mock_update.message.reply_text.call_args_list[-1]
    response_text = final_call[0][0]
    assert "top_k" in response_text
