"""
Tests unitaires pour bot/handlers/file_send_commands.py

Story 3.6 - Tests upload fichiers Telegram (AC#3 : Envoi fichier).

Ces tests couvrent :
- Détection intention "envoyer fichier" via Claude
- Recherche sémantique pgvector
- Retrieve fichier PC/VPS
- Envoi Telegram <20 Mo
- Gestion fichier trop gros
- Gestion fichier non trouvé
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, Message, Update, User

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_update():
    """Fixture Update Telegram avec message texte."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 123456
    update.effective_user.username = "mainteneur"

    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.message.chat_id = -1001234567890
    update.message.message_thread_id = 100  # Chat & Proactive topic
    update.message.text = "Envoie-moi la facture du plombier"

    return update


@pytest.fixture
def mock_context():
    """Fixture Context Telegram."""
    context = MagicMock()
    context.bot = MagicMock()
    return context


# ============================================================================
# Test 1/8: Intent detection "Envoie-moi" → FileRequest
# ============================================================================
@pytest.mark.asyncio
async def test_detect_intent_envoie_moi():
    """
    Test 1/8: Détection intention "Envoie-moi la facture du plombier".

    Vérifie que :
    - Claude détecte l'intention
    - Requête extraite correctement
    - Type document détecté
    - Confidence > 0.8
    """
    from bot.handlers.file_send_commands import detect_file_request_intent

    # Mock Claude response (JSON avec intention détectée)
    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps(
        {
            "has_intent": True,
            "query": "facture plombier",
            "doc_type": "facture",
            "keywords": ["facture", "plombier"],
            "confidence": 0.95,
        }
    )

    with patch("bot.handlers.file_send_commands.ClaudeAdapter") as MockClaude:
        mock_claude = MockClaude.return_value
        mock_claude.complete_raw = AsyncMock(return_value=mock_llm_response)

        # Execute
        result = await detect_file_request_intent("Envoie-moi la facture du plombier")

        # Verify
        assert result is not None
        assert result.query == "facture plombier"
        assert result.doc_type == "facture"
        assert result.confidence == 0.95
        assert "facture" in result.keywords
        assert "plombier" in result.keywords

        # Verify Claude called
        mock_claude.complete_raw.assert_called_once()


# ============================================================================
# Test 2/8: Intent detection "Je veux" → FileRequest
# ============================================================================
@pytest.mark.asyncio
async def test_detect_intent_je_veux():
    """
    Test 2/8: Détection intention "Je veux le contrat SELARL".

    Vérifie intention détectée avec type "contrat".
    """
    from bot.handlers.file_send_commands import detect_file_request_intent

    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps(
        {
            "has_intent": True,
            "query": "contrat SELARL",
            "doc_type": "contrat",
            "keywords": ["contrat", "SELARL"],
            "confidence": 0.92,
        }
    )

    with patch("bot.handlers.file_send_commands.ClaudeAdapter") as MockClaude:
        mock_claude = MockClaude.return_value
        mock_claude.complete_raw = AsyncMock(return_value=mock_llm_response)

        result = await detect_file_request_intent("Je veux le contrat SELARL")

        assert result is not None
        assert result.query == "contrat SELARL"
        assert result.doc_type == "contrat"
        assert result.confidence == 0.92


# ============================================================================
# Test 3/8: Intent detection "Bonjour" → NO INTENT
# ============================================================================
@pytest.mark.asyncio
async def test_detect_intent_no_match():
    """
    Test 3/8: Message "Bonjour" ne doit PAS déclencher intention fichier.

    Vérifie que :
    - Claude retourne has_intent=false
    - detect_file_request_intent retourne None
    """
    from bot.handlers.file_send_commands import detect_file_request_intent

    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps(
        {
            "has_intent": False,
            "confidence": 0.1,
        }
    )

    with patch("bot.handlers.file_send_commands.ClaudeAdapter") as MockClaude:
        mock_claude = MockClaude.return_value
        mock_claude.complete_raw = AsyncMock(return_value=mock_llm_response)

        result = await detect_file_request_intent("Bonjour")

        assert result is None


# ============================================================================
# Test 4/8: Recherche sémantique → Fichier trouvé (similarité >70%)
# ============================================================================
@pytest.mark.asyncio
async def test_search_file_found_high_similarity():
    """
    Test 4/8: Recherche sémantique trouve fichier avec similarité 85%.

    Vérifie que :
    - Embedding query généré
    - Recherche pgvector appelée
    - JOIN avec document_metadata
    - Résultat retourné avec metadata complète
    """
    from bot.handlers.file_send_commands import DocumentSearchResult, search_documents_semantic

    # Mock DATABASE_URL environment variable
    with patch("os.getenv") as mock_getenv:
        mock_getenv.return_value = "postgresql://test:test@localhost:5432/test"

        # Mock Voyage AI embedding (patch dans agents.src.adapters.vectorstore)
        with patch("agents.src.adapters.vectorstore.VoyageAIAdapter") as MockVoyage:
            mock_voyage = MockVoyage.return_value
            mock_voyage.embed_query = AsyncMock(return_value=[0.1] * 1024)  # Mock embedding

            # Mock vectorstore search
            with patch(
                "bot.handlers.file_send_commands.get_vectorstore_adapter"
            ) as MockVectorstore:
                mock_vectorstore = AsyncMock()
                MockVectorstore.return_value = mock_vectorstore

                mock_search_result = MagicMock()
                mock_search_result.node_id = "node_123"
                mock_search_result.similarity = 0.85

                mock_vectorstore.search = AsyncMock(return_value=[mock_search_result])
                mock_vectorstore.close = AsyncMock()

                # Mock PostgreSQL JOIN
                with patch("bot.handlers.file_send_commands.asyncpg.connect") as MockConnect:
                    mock_conn = AsyncMock()
                    MockConnect.return_value = mock_conn

                    mock_conn.fetchrow = AsyncMock(
                        return_value={
                            "id": "doc_123",
                            "filename": "Facture_Plombier_2025.pdf",
                            "file_path": r"C:\Users\lopez\BeeStation\Friday\Archives\finance\Facture_Plombier_2025.pdf",
                            "doc_type": "facture",
                            "emitter": "Plomberie Dupont",
                            "amount": 350.00,
                            "classification_category": "finance",
                            "classification_subcategory": "selarl",
                        }
                    )

                    mock_conn.close = AsyncMock()

                    # Execute
                    results = await search_documents_semantic(query="facture plombier", top_k=3)

                    # Verify
                    assert len(results) == 1
                    assert results[0].filename == "Facture_Plombier_2025.pdf"
                    assert results[0].similarity == 0.85
                    assert results[0].doc_type == "facture"
                    assert results[0].emitter == "Plomberie Dupont"
                    assert results[0].amount == 350.00


# ============================================================================
# Test 5/8: Recherche sémantique → Aucun résultat
# ============================================================================
@pytest.mark.asyncio
async def test_search_file_not_found():
    """
    Test 5/8: Recherche sémantique ne trouve aucun fichier.

    Vérifie que :
    - Recherche pgvector retourne liste vide
    - Fonction retourne liste vide
    """
    from bot.handlers.file_send_commands import search_documents_semantic

    # Mock DATABASE_URL environment variable
    with patch("os.getenv") as mock_getenv:
        mock_getenv.return_value = "postgresql://test:test@localhost:5432/test"

        with patch("agents.src.adapters.vectorstore.VoyageAIAdapter") as MockVoyage:
            mock_voyage = MockVoyage.return_value
            mock_voyage.embed_query = AsyncMock(return_value=[0.1] * 1024)

            with patch(
                "bot.handlers.file_send_commands.get_vectorstore_adapter"
            ) as MockVectorstore:
                mock_vectorstore = AsyncMock()
                MockVectorstore.return_value = mock_vectorstore

                # Aucun résultat trouvé
                mock_vectorstore.search = AsyncMock(return_value=[])
                mock_vectorstore.close = AsyncMock()

                # Mock asyncpg.connect (même si pas de résultats, le code peut l'appeler)
                with patch("bot.handlers.file_send_commands.asyncpg.connect") as MockConnect:
                    mock_conn = AsyncMock()
                    MockConnect.return_value = mock_conn
                    mock_conn.close = AsyncMock()

                    # Execute
                    results = await search_documents_semantic(query="contrat inexistant")

                    # Verify
                    assert len(results) == 0


# ============================================================================
# Test 6/8: Envoi fichier <20 Mo → Succès
# ============================================================================
@pytest.mark.asyncio
async def test_send_file_success(mock_update, mock_context, tmp_path):
    """
    Test 6/8: Envoi fichier <20 Mo via Telegram réussit.

    Vérifie que :
    - Intention détectée
    - Fichier trouvé
    - Fichier <20 Mo vérifié
    - reply_document appelé
    - Notification confirmation envoyée
    """
    from bot.handlers.file_send_commands import handle_file_send_request

    # Créer fichier temporaire <20 Mo
    test_file = tmp_path / "facture_test.pdf"
    test_file.write_bytes(b"PDF content here")  # ~16 bytes

    # Mock intent detection
    with patch("bot.handlers.file_send_commands.detect_file_request_intent") as MockIntent:
        mock_intent = MagicMock()
        mock_intent.query = "facture plombier"
        mock_intent.doc_type = "facture"
        mock_intent.confidence = 0.95
        MockIntent.return_value = mock_intent

        # Mock search results
        with patch("bot.handlers.file_send_commands.search_documents_semantic") as MockSearch:
            mock_result = MagicMock()
            mock_result.filename = "facture_test.pdf"
            mock_result.file_path = str(test_file)
            mock_result.similarity = 0.85
            mock_result.doc_type = "facture"
            mock_result.emitter = "Plomberie"
            mock_result.amount = 350.0
            MockSearch.return_value = [mock_result]

            # Mock file resolution (fichier trouvé sur VPS)
            with patch("bot.handlers.file_send_commands.resolve_file_path_vps") as MockResolve:
                MockResolve.return_value = test_file

                # Execute
                await handle_file_send_request(mock_update, mock_context)

                # Verify reply_document called
                mock_update.message.reply_document.assert_called_once()

                # Verify caption contient metadata
                call_kwargs = mock_update.message.reply_document.call_args.kwargs
                assert "caption" in call_kwargs
                assert "facture_test.pdf" in call_kwargs["caption"]


# ============================================================================
# Test 7/8: Fichier >20 Mo → Notification limite
# ============================================================================
@pytest.mark.asyncio
async def test_send_file_too_large(mock_update, mock_context, tmp_path):
    """
    Test 7/10: Fichier >20 Mo rejeté avec message explicite.

    Vérifie que :
    - Intention détectée
    - Fichier trouvé
    - Fichier >20 Mo détecté
    - Notification limite envoyée
    - reply_document PAS appelé
    """
    from bot.handlers.file_send_commands import handle_file_send_request

    # Créer fichier temporaire >20 Mo (simulé)
    test_file = tmp_path / "gros_fichier.pdf"
    test_file.write_bytes(b"X" * (21 * 1024 * 1024))  # 21 MB

    # Mock intent detection
    with patch("bot.handlers.file_send_commands.detect_file_request_intent") as MockIntent:
        mock_intent = MagicMock()
        mock_intent.query = "gros fichier"
        mock_intent.confidence = 0.95
        MockIntent.return_value = mock_intent

        # Mock search results
        with patch("bot.handlers.file_send_commands.search_documents_semantic") as MockSearch:
            mock_result = MagicMock()
            mock_result.filename = "gros_fichier.pdf"
            mock_result.file_path = str(test_file)
            mock_result.similarity = 0.85
            mock_result.doc_type = "document"
            mock_result.emitter = None
            mock_result.amount = 0.0
            MockSearch.return_value = [mock_result]

            # Mock file resolution
            with patch("bot.handlers.file_send_commands.resolve_file_path_vps") as MockResolve:
                MockResolve.return_value = test_file

                # Execute
                await handle_file_send_request(mock_update, mock_context)

                # Verify notification limite envoyée
                mock_update.message.reply_text.assert_called()
                reply_text = mock_update.message.reply_text.call_args[0][0]
                assert "trop volumineux" in reply_text.lower() or "20 Mo" in reply_text.lower()

                # Verify reply_document PAS appelé
                mock_update.message.reply_document.assert_not_called()


# ============================================================================
# Test 8/8: Fichier pas sur VPS → Notification chemin PC
# ============================================================================
@pytest.mark.asyncio
async def test_send_file_not_on_vps(mock_update, mock_context):
    """
    Test 8/8: Fichier pas synchronisé sur VPS → notification chemin PC.

    Vérifie que :
    - Intention détectée
    - Recherche trouve fichier
    - resolve_file_path_vps retourne None (pas de miroir VPS)
    - Notification avec chemin PC envoyée
    - reply_document PAS appelé
    """
    from bot.handlers.file_send_commands import handle_file_send_request

    # Mock intent detection
    with patch("bot.handlers.file_send_commands.detect_file_request_intent") as MockIntent:
        mock_intent = MagicMock()
        mock_intent.query = "contrat SELARL"
        mock_intent.confidence = 0.95
        MockIntent.return_value = mock_intent

        # Mock search results
        with patch("bot.handlers.file_send_commands.search_documents_semantic") as MockSearch:
            mock_result = MagicMock()
            mock_result.filename = "Contrat_SELARL.pdf"
            mock_result.file_path = (
                r"C:\Users\lopez\BeeStation\Friday\Archives\pro\Contrat_SELARL.pdf"
            )
            mock_result.similarity = 0.90
            mock_result.doc_type = "contrat"
            mock_result.emitter = "SELARL Cabinet"
            mock_result.amount = 0.0
            MockSearch.return_value = [mock_result]

            # Mock file resolution (fichier PAS sur VPS)
            with patch("bot.handlers.file_send_commands.resolve_file_path_vps") as MockResolve:
                MockResolve.return_value = None  # Fichier pas accessible

                # Execute
                await handle_file_send_request(mock_update, mock_context)

                # Verify notification avec chemin PC
                mock_update.message.reply_text.assert_called()
                reply_text = mock_update.message.reply_text.call_args[0][0]
                assert "Fichier trouvé" in reply_text
                assert r"C:\Users\lopez\BeeStation" in reply_text
                assert "pas encore synchronisé" in reply_text or "VPS" in reply_text

                # Verify reply_document PAS appelé
                mock_update.message.reply_document.assert_not_called()
