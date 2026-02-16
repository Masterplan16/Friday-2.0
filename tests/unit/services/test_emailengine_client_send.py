"""
Tests unitaires pour services.email_processor.emailengine_client.send_message()

Tests la méthode send_message() pour envoi emails via EmailEngine API
avec retry logic et threading.

Story: 2.5 Brouillon Réponse Email - Task 4 Subtask 4.3
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from services.email_processor.emailengine_client import EmailEngineClient, EmailEngineError


@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient"""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def emailengine_client(mock_http_client):
    """EmailEngineClient instance avec mock http_client"""
    return EmailEngineClient(
        http_client=mock_http_client, base_url="http://localhost:3000", secret="test_secret_123"
    )


@pytest.fixture
def sample_send_response():
    """Réponse EmailEngine API send_message réussie"""
    return {
        "messageId": "<sent-msg-456@example.com>",
        "queueId": "queue-789",
        "response": "250 Message accepted",
    }


# ============================================================================
# Tests send_message
# ============================================================================


@pytest.mark.asyncio
async def test_send_message_success(emailengine_client, mock_http_client, sample_send_response):
    """
    Test 1: Envoi réussi (mock EmailEngine API)

    Vérifie que l'email est envoyé correctement avec tous les champs
    """
    # Setup mock
    mock_response = AsyncMock()
    mock_response.status_code = 200
    # json() doit être un Mock synchrone, pas AsyncMock
    mock_response.json = MagicMock(return_value=sample_send_response)
    mock_http_client.post.return_value = mock_response

    # Execute
    result = await emailengine_client.send_message(
        account_id="account_1",
        recipient_email="john@example.com",
        subject="Re: Your question",
        body_text="Bonjour,\n\nVoici ma réponse.\n\nCordialement,\nDr. Lopez",
    )

    # Assertions
    assert result == sample_send_response
    assert result["messageId"] == "<sent-msg-456@example.com>"

    # Vérifier appel HTTP
    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args

    # Vérifier URL
    assert "/v1/account/account_1/submit" in call_args[0][0]

    # Vérifier headers
    headers = call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer test_secret_123"
    assert headers["Content-Type"] == "application/json"

    # Vérifier payload
    payload = call_args[1]["json"]
    assert payload["to"] == [{"address": "john@example.com"}]
    assert payload["subject"] == "Re: Your question"
    assert payload["text"] == "Bonjour,\n\nVoici ma réponse.\n\nCordialement,\nDr. Lopez"


@pytest.mark.asyncio
async def test_send_message_retry_after_first_failure(
    emailengine_client, mock_http_client, sample_send_response
):
    """
    Test 2: Retry après 1er échec

    Vérifie que le client retry automatiquement après un échec temporaire
    """
    # Setup mock : 1ère tentative échoue, 2ème réussit
    mock_response_fail = AsyncMock()
    mock_response_fail.status_code = 500
    mock_response_fail.text = "Internal Server Error"

    mock_response_success = AsyncMock()
    mock_response_success.status_code = 200
    mock_response_success.json = MagicMock(return_value=sample_send_response)

    mock_http_client.post.side_effect = [
        mock_response_fail,  # 1ère tentative
        mock_response_success,  # 2ème tentative
    ]

    # Execute
    result = await emailengine_client.send_message(
        account_id="account_1",
        recipient_email="john@example.com",
        subject="Test",
        body_text="Test body",
        max_retries=3,
    )

    # Assertions
    assert result == sample_send_response

    # Vérifier qu'il y a eu 2 appels (1er échec + 1er retry réussi)
    assert mock_http_client.post.call_count == 2


@pytest.mark.asyncio
async def test_send_message_fail_after_max_retries(emailengine_client, mock_http_client):
    """
    Test 3: Fail après 3 échecs

    Vérifie que EmailEngineError est raised après max_retries
    """
    # Setup mock : toutes les tentatives échouent
    mock_response_fail = AsyncMock()
    mock_response_fail.status_code = 500
    mock_response_fail.text = "Internal Server Error"

    mock_http_client.post.return_value = mock_response_fail

    # Execute - devrait raise EmailEngineError
    with pytest.raises(EmailEngineError) as exc_info:
        await emailengine_client.send_message(
            account_id="account_1",
            recipient_email="john@example.com",
            subject="Test",
            body_text="Test body",
            max_retries=3,
        )

    # Vérifier message erreur
    assert "failed after 3 attempts" in str(exc_info.value)
    assert "500" in str(exc_info.value)

    # Vérifier qu'il y a eu 3 tentatives
    assert mock_http_client.post.call_count == 3


@pytest.mark.asyncio
async def test_send_message_threading_correct(
    emailengine_client, mock_http_client, sample_send_response
):
    """
    Test 4: Threading correct (inReplyTo + references)

    Vérifie que les champs threading sont passés correctement
    """
    # Setup mock
    mock_response = AsyncMock()
    mock_response.status_code = 200
    # json() doit être un Mock synchrone, pas AsyncMock
    mock_response.json = MagicMock(return_value=sample_send_response)
    mock_http_client.post.return_value = mock_response

    # Execute avec threading
    original_message_id = "<original-msg-123@example.com>"
    await emailengine_client.send_message(
        account_id="account_1",
        recipient_email="john@example.com",
        subject="Re: Your question",
        body_text="Réponse",
        in_reply_to=original_message_id,
        references=[original_message_id],
    )

    # Vérifier payload threading
    call_args = mock_http_client.post.call_args
    payload = call_args[1]["json"]

    assert payload["inReplyTo"] == original_message_id
    assert payload["references"] == [original_message_id]


@pytest.mark.asyncio
async def test_send_message_with_html_body(
    emailengine_client, mock_http_client, sample_send_response
):
    """
    Test bonus: Envoi avec corps HTML

    Vérifie que le champ html optionnel est passé correctement
    """
    # Setup mock
    mock_response = AsyncMock()
    mock_response.status_code = 200
    # json() doit être un Mock synchrone, pas AsyncMock
    mock_response.json = MagicMock(return_value=sample_send_response)
    mock_http_client.post.return_value = mock_response

    # Execute avec HTML
    html_body = "<p>Bonjour,</p><p>Voici ma réponse.</p><p>Cordialement,<br>Dr. Lopez</p>"
    await emailengine_client.send_message(
        account_id="account_1",
        recipient_email="john@example.com",
        subject="Test",
        body_text="Text version",
        body_html=html_body,
    )

    # Vérifier payload HTML
    call_args = mock_http_client.post.call_args
    payload = call_args[1]["json"]

    assert payload["html"] == html_body
    assert payload["text"] == "Text version"


# ============================================================================
# Tests determine_account_id
# ============================================================================


def test_determine_account_id_professional(emailengine_client):
    """
    Test 5a: Account ID correct déterminé (professional)

    Vérifie le mapping recipient → account_id
    """
    email_original = {
        "recipient_email": "antonio.lopez@example.com",
        "to": "antonio.lopez@example.com",
        "from": "john@example.com",
    }

    account_id = emailengine_client.determine_account_id(email_original)

    assert account_id == "account_professional"


def test_determine_account_id_medical(emailengine_client):
    """
    Test 5b: Account ID médical
    """
    email_original = {"recipient_email": "dr.lopez@hospital.fr", "to": "dr.lopez@hospital.fr"}

    account_id = emailengine_client.determine_account_id(email_original)

    assert account_id == "account_medical"


def test_determine_account_id_academic(emailengine_client):
    """
    Test 5c: Account ID académique
    """
    email_original = {"recipient_email": "lopez@university.fr", "to": "lopez@university.fr"}

    account_id = emailengine_client.determine_account_id(email_original)

    assert account_id == "account_academic"


def test_determine_account_id_fallback(emailengine_client):
    """
    Test 5d: Fallback compte par défaut si indéterminable
    """
    email_original = {"recipient_email": "unknown@unknown.com", "to": "unknown@unknown.com"}

    account_id = emailengine_client.determine_account_id(email_original)

    # Devrait fallback sur account_professional (défaut)
    assert account_id == "account_professional"


# ============================================================================
# Tests error handling
# ============================================================================


@pytest.mark.asyncio
async def test_send_message_timeout_error(emailengine_client, mock_http_client):
    """
    Test bonus: Gestion timeout errors

    Vérifie que TimeoutException est correctement gérée
    """
    # Setup mock : toutes les tentatives timeout
    mock_http_client.post.side_effect = httpx.TimeoutException("Request timeout")

    # Execute - devrait raise EmailEngineError
    with pytest.raises(EmailEngineError) as exc_info:
        await emailengine_client.send_message(
            account_id="account_1",
            recipient_email="john@example.com",
            subject="Test",
            body_text="Test body",
            max_retries=2,
        )

    # Vérifier message erreur
    assert "timeout" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_send_message_http_error(emailengine_client, mock_http_client):
    """
    Test bonus: Gestion HTTP errors génériques

    Vérifie que HTTPError est correctement gérée
    """
    # Setup mock : toutes les tentatives HTTPError
    mock_http_client.post.side_effect = httpx.HTTPError("Connection error")

    # Execute - devrait raise EmailEngineError
    with pytest.raises(EmailEngineError) as exc_info:
        await emailengine_client.send_message(
            account_id="account_1",
            recipient_email="john@example.com",
            subject="Test",
            body_text="Test body",
            max_retries=2,
        )

    # Vérifier message erreur
    assert "HTTP error" in str(exc_info.value)
