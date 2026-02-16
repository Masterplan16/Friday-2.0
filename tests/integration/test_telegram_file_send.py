"""
Tests intégration envoi fichiers Telegram (Story 3.6 Task 7.3).

Tests pipeline complet :
- Intent detection via Claude (mocké)
- Recherche sémantique pgvector (mocké)
- File retrieval + envoi Telegram

Environment :
- Filesystem tmpdir (fichiers test)
- Mocks : Claude API, pgvector, Telegram Bot API

Ces tests vérifient AC#3 : Envoi fichier via recherche sémantique.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_file_small(tmp_path):
    """Fixture fichier PDF <20 Mo."""
    file_path = tmp_path / "Facture_Plombier_2025.pdf"
    file_path.write_bytes(b"%PDF-1.4\n" + b"X" * 100)  # ~100 bytes
    return file_path


@pytest.fixture
def test_file_large(tmp_path):
    """Fixture fichier PDF >20 Mo."""
    file_path = tmp_path / "Gros_Fichier.pdf"
    file_path.write_bytes(b"%PDF-1.4\n" + b"X" * (21 * 1024 * 1024))  # 21 MB
    return file_path


@pytest.fixture
def mock_telegram_update():
    """Fixture Update Telegram avec message texte."""
    from telegram import Update, Message, User

    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456

    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.message.chat_id = -1001234567890
    update.message.message_thread_id = 100
    update.message.text = "Envoie-moi la facture du plombier"

    return update


@pytest.fixture
def mock_telegram_context():
    """Fixture Context Telegram."""
    context = MagicMock()
    context.bot = MagicMock()
    return context


# ============================================================================
# Test 1/3: Recherche → fichier trouvé → envoi Telegram réussi
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_and_send_file_found(
    test_file_small, mock_telegram_update, mock_telegram_context
):
    """
    Test 1/3: Recherche sémantique trouve fichier → envoi Telegram réussi.

    Vérifie que :
    - Intent détectée
    - Recherche sémantique exécutée
    - Fichier <20 Mo trouvé sur VPS
    - reply_document appelé avec caption complète
    - Notification confirmation envoyée
    """
    from bot.handlers.file_send_commands import handle_file_send_request

    # Mock intent detection
    with patch("bot.handlers.file_send_commands.detect_file_request_intent") as MockIntent:
        mock_intent = MagicMock()
        mock_intent.query = "facture plombier"
        mock_intent.doc_type = "facture"
        mock_intent.confidence = 0.95
        MockIntent.return_value = mock_intent

        # Mock semantic search
        with patch("bot.handlers.file_send_commands.search_documents_semantic") as MockSearch:
            mock_result = MagicMock()
            mock_result.filename = "Facture_Plombier_2025.pdf"
            mock_result.file_path = str(test_file_small)
            mock_result.similarity = 0.92
            mock_result.doc_type = "facture"
            mock_result.emitter = "Plomberie Dupont"
            mock_result.amount = 350.00
            MockSearch.return_value = [mock_result]

            # Mock file resolution (fichier trouvé sur VPS)
            with patch("bot.handlers.file_send_commands.resolve_file_path_vps") as MockResolve:
                MockResolve.return_value = test_file_small

                # Execute handler
                await handle_file_send_request(mock_telegram_update, mock_telegram_context)

                # Verify intent detection called
                MockIntent.assert_called_once_with("Envoie-moi la facture du plombier")

                # Verify semantic search called
                MockSearch.assert_called_once()
                assert MockSearch.call_args.kwargs["query"] == "facture plombier"

                # Verify file resolution called
                MockResolve.assert_called_once_with(str(test_file_small))

                # Verify reply_document called
                mock_telegram_update.message.reply_document.assert_called_once()

                # Verify caption contient metadata
                call_kwargs = mock_telegram_update.message.reply_document.call_args.kwargs
                assert "caption" in call_kwargs
                caption = call_kwargs["caption"]
                assert "Facture_Plombier_2025.pdf" in caption
                assert "Plomberie Dupont" in caption
                assert "350.00" in caption


# ============================================================================
# Test 2/3: Recherche → 0 résultat → top-3 alternatives proposées
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_file_not_found_alternatives(mock_telegram_update, mock_telegram_context):
    """
    Test 2/3: Recherche ne trouve rien → propose top-3 alternatives.

    Vérifie que :
    - Intent détectée
    - Recherche retourne résultats faible similarité (<70%)
    - Message avec alternatives envoyé
    - reply_document PAS appelé
    """
    from bot.handlers.file_send_commands import handle_file_send_request

    # Mock intent detection
    with patch("bot.handlers.file_send_commands.detect_file_request_intent") as MockIntent:
        mock_intent = MagicMock()
        mock_intent.query = "contrat inexistant"
        mock_intent.confidence = 0.85
        MockIntent.return_value = mock_intent

        # Mock semantic search : 3 résultats faible similarité
        with patch("bot.handlers.file_send_commands.search_documents_semantic") as MockSearch:
            mock_results = [
                MagicMock(
                    filename="Document_A.pdf",
                    file_path="/path/a.pdf",
                    similarity=0.65,
                    doc_type="contrat",
                    emitter="Société A",
                    amount=0.0,
                ),
                MagicMock(
                    filename="Document_B.pdf",
                    file_path="/path/b.pdf",
                    similarity=0.60,
                    doc_type="facture",
                    emitter="Société B",
                    amount=0.0,
                ),
                MagicMock(
                    filename="Document_C.pdf",
                    file_path="/path/c.pdf",
                    similarity=0.55,
                    doc_type="courrier",
                    emitter="Société C",
                    amount=0.0,
                ),
            ]
            MockSearch.return_value = mock_results

            # Execute handler
            await handle_file_send_request(mock_telegram_update, mock_telegram_context)

            # Verify message alternatives envoyé
            mock_telegram_update.message.reply_text.assert_called()
            reply_text = mock_telegram_update.message.reply_text.call_args[0][0]

            # Verify contient "Aucun résultat exact" ou similaire
            assert "Aucun" in reply_text or "Suggestions" in reply_text

            # Verify contient les 3 alternatives
            assert "Document_A.pdf" in reply_text
            assert "Document_B.pdf" in reply_text
            assert "Document_C.pdf" in reply_text

            # Verify similarités affichées
            assert "65" in reply_text or "60" in reply_text

            # Verify reply_document PAS appelé
            mock_telegram_update.message.reply_document.assert_not_called()


# ============================================================================
# Test 3/3: Fichier >20 Mo → notification limite
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.integration
async def test_send_file_too_large_notification(
    test_file_large, mock_telegram_update, mock_telegram_context
):
    """
    Test 3/3: Fichier >20 Mo trouvé → notification limite Telegram.

    Vérifie que :
    - Intent détectée
    - Recherche trouve fichier
    - Taille vérifiée : >20 Mo
    - Notification limite envoyée avec taille exacte
    - reply_document PAS appelé
    """
    from bot.handlers.file_send_commands import handle_file_send_request

    # Mock intent detection
    with patch("bot.handlers.file_send_commands.detect_file_request_intent") as MockIntent:
        mock_intent = MagicMock()
        mock_intent.query = "gros fichier"
        mock_intent.confidence = 0.90
        MockIntent.return_value = mock_intent

        # Mock semantic search
        with patch("bot.handlers.file_send_commands.search_documents_semantic") as MockSearch:
            mock_result = MagicMock()
            mock_result.filename = "Gros_Fichier.pdf"
            mock_result.file_path = str(test_file_large)
            mock_result.similarity = 0.88
            mock_result.doc_type = "document"
            mock_result.emitter = None
            mock_result.amount = 0.0
            MockSearch.return_value = [mock_result]

            # Mock file resolution
            with patch("bot.handlers.file_send_commands.resolve_file_path_vps") as MockResolve:
                MockResolve.return_value = test_file_large

                # Execute handler
                await handle_file_send_request(mock_telegram_update, mock_telegram_context)

                # Verify notification limite envoyée
                mock_telegram_update.message.reply_text.assert_called()
                reply_text = mock_telegram_update.message.reply_text.call_args[0][0]

                # Verify message contient "trop volumineux" et "20 Mo"
                assert "trop volumineux" in reply_text.lower() or "20" in reply_text
                assert "Mo" in reply_text

                # Verify taille fichier affichée (21 Mo)
                assert "21" in reply_text

                # Verify reply_document PAS appelé
                mock_telegram_update.message.reply_document.assert_not_called()
