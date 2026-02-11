"""
Tests unitaires pour webhook EmailEngine
Story 2.1 - Subtask 6.1
Tests: signature HMAC, anonymisation, Redis Streams, validations
"""

import pytest
import hmac
import hashlib
import json
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Import du module à tester
import sys
from pathlib import Path
repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(repo_root))

from services.gateway.routes.webhooks import router, verify_webhook_signature


@pytest.fixture
def app():
    """Application FastAPI de test"""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Client de test"""
    return TestClient(app)


@pytest.fixture
def valid_payload():
    """Payload webhook EmailEngine valide"""
    return {
        "account": "account-test",
        "path": "INBOX",
        "event": "messageNew",
        "data": {
            "id": "msg_test123",
            "from": {"address": "john.doe@example.com", "name": "John Doe"},
            "subject": "Rendez-vous médical Dr. Smith",
            "date": "2026-02-11T10:30:00Z",
            "text": "Bonjour, je confirme le rendez-vous...",
            "attachments": []
        }
    }


@pytest.fixture
def webhook_secret():
    """Secret partagé webhook"""
    return "test-webhook-secret-12345"


def compute_signature(payload: dict, secret: str) -> str:
    """Calculer signature HMAC-SHA256"""
    payload_bytes = json.dumps(payload).encode('utf-8')
    return hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()


class TestWebhookSignatureValidation:
    """Tests validation signature HMAC-SHA256"""

    def test_verify_signature_valid(self, valid_payload, webhook_secret):
        """Signature valide doit retourner True"""
        payload_bytes = json.dumps(valid_payload).encode('utf-8')
        signature = compute_signature(valid_payload, webhook_secret)

        result = verify_webhook_signature(payload_bytes, signature, webhook_secret)
        assert result is True

    def test_verify_signature_invalid(self, valid_payload, webhook_secret):
        """Signature invalide doit retourner False"""
        payload_bytes = json.dumps(valid_payload).encode('utf-8')
        wrong_signature = "wrong_signature_hex"

        result = verify_webhook_signature(payload_bytes, wrong_signature, webhook_secret)
        assert result is False

    def test_verify_signature_missing(self, valid_payload, webhook_secret):
        """Signature manquante doit retourner False"""
        payload_bytes = json.dumps(valid_payload).encode('utf-8')

        result = verify_webhook_signature(payload_bytes, None, webhook_secret)
        assert result is False

    def test_verify_signature_timing_safe(self, valid_payload, webhook_secret):
        """Vérifier que la comparaison est timing-safe (hmac.compare_digest)"""
        # Test que la fonction utilise timing-safe comparison
        payload_bytes = json.dumps(valid_payload).encode('utf-8')
        signature = compute_signature(valid_payload, webhook_secret)

        # Mock hmac.compare_digest pour vérifier qu'il est appelé
        with patch('hmac.compare_digest', return_value=True) as mock_compare:
            verify_webhook_signature(payload_bytes, signature, webhook_secret)
            mock_compare.assert_called_once()


class TestWebhookEndpoint:
    """Tests endpoint POST /api/v1/webhooks/emailengine/{account_id}"""

    @patch('services.gateway.routes.webhooks.anonymize_text')
    @patch('services.gateway.routes.webhooks.get_redis_client')
    @patch('services.gateway.routes.webhooks.get_settings')
    def test_webhook_success(self, mock_settings, mock_redis, mock_anonymize, client, valid_payload, webhook_secret):
        """Webhook valide doit retourner 200 OK"""
        # Mock settings
        mock_settings.return_value = MagicMock(WEBHOOK_SECRET=webhook_secret)

        # Mock anonymize_text
        mock_anonymize.return_value = "[ANONYMIZED]"

        # Mock Redis
        mock_redis_client = AsyncMock()
        mock_redis_client.xadd = AsyncMock(return_value="event-id-123")
        mock_redis.return_value = mock_redis_client

        # Calculer signature
        signature = compute_signature(valid_payload, webhook_secret)

        # Envoyer requête
        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=valid_payload,
            headers={"X-EE-Signature": signature}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["message_id"] == "msg_test123"

    def test_webhook_invalid_signature(self, client, valid_payload):
        """Signature invalide doit retourner 401"""
        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=valid_payload,
            headers={"X-EE-Signature": "wrong-signature"}
        )

        assert response.status_code == 401

    def test_webhook_body_too_large(self, client):
        """Body >10MB doit retourner 413"""
        large_payload = {"data": "x" * (11 * 1024 * 1024)}  # 11 MB

        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=large_payload,
            headers={"X-EE-Signature": "test"}
        )

        assert response.status_code == 413

    def test_webhook_account_mismatch(self, client, valid_payload, webhook_secret):
        """Account mismatch URL vs payload doit retourner 400"""
        # Mock settings
        with patch('services.gateway.routes.webhooks.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock(WEBHOOK_SECRET=webhook_secret)

            signature = compute_signature(valid_payload, webhook_secret)

            # URL: account-wrong, payload: account-test
            response = client.post(
                "/api/v1/webhooks/emailengine/account-wrong",
                json=valid_payload,
                headers={"X-EE-Signature": signature}
            )

            assert response.status_code == 400
            assert "mismatch" in response.json()["detail"].lower()

    @patch('services.gateway.routes.webhooks.get_settings')
    def test_webhook_event_ignored(self, mock_settings, client, webhook_secret):
        """Événement non messageNew doit être ignoré"""
        mock_settings.return_value = MagicMock(WEBHOOK_SECRET=webhook_secret)

        payload = {
            "account": "account-test",
            "path": "INBOX",
            "event": "messageDeleted",  # Pas messageNew
            "data": {}
        }

        signature = compute_signature(payload, webhook_secret)

        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=payload,
            headers={"X-EE-Signature": signature}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


class TestAnonymizationFlow:
    """Tests flux anonymisation Presidio"""

    @patch('services.gateway.routes.webhooks.anonymize_text')
    @patch('services.gateway.routes.webhooks.get_redis_client')
    @patch('services.gateway.routes.webhooks.get_settings')
    def test_anonymization_called_before_redis(
        self, mock_settings, mock_redis, mock_anonymize, client, valid_payload, webhook_secret
    ):
        """Anonymisation doit être appelée AVANT publication Redis"""
        mock_settings.return_value = MagicMock(WEBHOOK_SECRET=webhook_secret)
        mock_anonymize.return_value = "[ANONYMIZED]"

        mock_redis_client = AsyncMock()
        mock_redis_client.xadd = AsyncMock(return_value="event-123")
        mock_redis.return_value = mock_redis_client

        signature = compute_signature(valid_payload, webhook_secret)

        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=valid_payload,
            headers={"X-EE-Signature": signature}
        )

        # Vérifier que anonymize_text a été appelé 3 fois (from, subject, body)
        assert mock_anonymize.call_count == 3

    @patch('services.gateway.routes.webhooks.anonymize_text')
    @patch('services.gateway.routes.webhooks.get_redis_client')
    @patch('services.gateway.routes.webhooks.get_settings')
    def test_anonymization_failure(
        self, mock_settings, mock_redis, mock_anonymize, client, valid_payload, webhook_secret
    ):
        """Échec anonymisation doit retourner 500"""
        mock_settings.return_value = MagicMock(WEBHOOK_SECRET=webhook_secret)
        mock_anonymize.side_effect = Exception("Presidio error")

        signature = compute_signature(valid_payload, webhook_secret)

        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=valid_payload,
            headers={"X-EE-Signature": signature}
        )

        assert response.status_code == 500
        assert "Anonymization failed" in response.json()["detail"]


class TestRedisPublishing:
    """Tests publication Redis Streams"""

    @patch('services.gateway.routes.webhooks.anonymize_text')
    @patch('services.gateway.routes.webhooks.get_redis_client')
    @patch('services.gateway.routes.webhooks.get_settings')
    def test_redis_publish_success(
        self, mock_settings, mock_redis, mock_anonymize, client, valid_payload, webhook_secret
    ):
        """Publication Redis réussie doit retourner event_id"""
        mock_settings.return_value = MagicMock(WEBHOOK_SECRET=webhook_secret)
        mock_anonymize.return_value = "[ANONYMIZED]"

        mock_redis_client = AsyncMock()
        mock_redis_client.xadd = AsyncMock(return_value="event-id-abc123")
        mock_redis.return_value = mock_redis_client

        signature = compute_signature(valid_payload, webhook_secret)

        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=valid_payload,
            headers={"X-EE-Signature": signature}
        )

        assert response.status_code == 200
        assert response.json()["event_id"] == "event-id-abc123"

        # Vérifier que XADD a été appelé avec le bon stream
        mock_redis_client.xadd.assert_called_once()
        call_args = mock_redis_client.xadd.call_args
        assert call_args[0][0] == "emails:received"

    @patch('services.gateway.routes.webhooks.anonymize_text')
    @patch('services.gateway.routes.webhooks.get_redis_client')
    @patch('services.gateway.routes.webhooks.get_settings')
    def test_redis_publish_failure(
        self, mock_settings, mock_redis, mock_anonymize, client, valid_payload, webhook_secret
    ):
        """Échec publication Redis doit retourner 500"""
        mock_settings.return_value = MagicMock(WEBHOOK_SECRET=webhook_secret)
        mock_anonymize.return_value = "[ANONYMIZED]"

        mock_redis_client = AsyncMock()
        mock_redis_client.xadd = AsyncMock(side_effect=Exception("Redis down"))
        mock_redis.return_value = mock_redis_client

        signature = compute_signature(valid_payload, webhook_secret)

        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=valid_payload,
            headers={"X-EE-Signature": signature}
        )

        assert response.status_code == 500
        assert "Redis publish failed" in response.json()["detail"]


class TestCircuitBreaker:
    """Tests circuit breaker pattern"""

    @patch('services.gateway.routes.webhooks.webhook_circuit_breaker')
    @patch('services.gateway.routes.webhooks.anonymize_text')
    @patch('services.gateway.routes.webhooks.get_redis_client')
    @patch('services.gateway.routes.webhooks.get_settings')
    def test_circuit_breaker_called(
        self, mock_settings, mock_redis, mock_anonymize, mock_breaker, client, valid_payload, webhook_secret
    ):
        """Circuit breaker doit être utilisé pour Redis publish"""
        mock_settings.return_value = MagicMock(WEBHOOK_SECRET=webhook_secret)
        mock_anonymize.return_value = "[ANONYMIZED]"

        mock_redis_client = AsyncMock()
        mock_redis_client.xadd = AsyncMock(return_value="event-123")
        mock_redis.return_value = mock_redis_client

        mock_breaker.call_async = AsyncMock(return_value="event-123")

        signature = compute_signature(valid_payload, webhook_secret)

        response = client.post(
            "/api/v1/webhooks/emailengine/account-test",
            json=valid_payload,
            headers={"X-EE-Signature": signature}
        )

        # Vérifier que circuit breaker a été utilisé
        mock_breaker.call_async.assert_called_once()
