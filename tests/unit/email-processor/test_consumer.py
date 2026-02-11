"""
Tests unitaires pour Email Consumer
Story 2.1 - Subtask 6.2
Tests: fetch EmailEngine, retry backoff, DLQ, stockage BDD, notification Telegram
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

# Import du module à tester
import sys
from pathlib import Path
repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(repo_root))

from services.email_processor.consumer import EmailProcessorConsumer


@pytest.fixture
def consumer():
    """Instance consumer pour tests"""
    return EmailProcessorConsumer()


@pytest.fixture
def sample_event_payload():
    """Payload événement Redis Streams"""
    return {
        'account_id': 'account-test',
        'message_id': 'msg_123',
        'from_anon': '[EMAIL_1]',
        'subject_anon': 'Rendez-vous [PERSON_1]',
        'date': '2026-02-11T10:30:00Z',
        'has_attachments': 'False',
        'body_preview_anon': 'Bonjour [PERSON_1]...'
    }


@pytest.fixture
def sample_email_full():
    """Email complet depuis EmailEngine API"""
    return {
        'id': 'msg_123',
        'from': {'address': 'john.doe@example.com', 'name': 'John Doe'},
        'to': [{'address': 'me@example.com', 'name': 'Me'}],
        'subject': 'Rendez-vous Dr Smith',
        'text': 'Bonjour, je confirme le rendez-vous médical...',
        'date': '2026-02-11T10:30:00Z',
        'attachments': []
    }


class TestFetchEmailWithRetry:
    """Tests fetch email avec retry backoff exponentiel"""

    @pytest.mark.asyncio
    async def test_fetch_success_first_try(self, consumer, sample_email_full):
        """Fetch réussi au premier essai"""
        consumer.http_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_email_full
        consumer.http_client.get = AsyncMock(return_value=mock_response)

        result = await consumer.fetch_email_from_emailengine('account-test', 'msg_123')

        assert result == sample_email_full
        assert consumer.http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_retry_backoff_exponential(self, consumer):
        """Retry doit utiliser backoff exponentiel: 1s, 2s, 4s, 8s, 16s, 32s"""
        consumer.http_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500  # Échec serveur
        consumer.http_client.get = AsyncMock(return_value=mock_response)

        # Mock asyncio.sleep pour vérifier les délais
        with patch('asyncio.sleep') as mock_sleep:
            mock_sleep.return_value = None

            result = await consumer.fetch_email_from_emailengine('account-test', 'msg_123', max_retries=6)

            # Doit échouer après max_retries
            assert result is None

            # Vérifier appels sleep : 1, 2, 4, 8, 16, 32 secondes
            expected_sleeps = [1, 2, 4, 8, 16, 32]
            actual_sleeps = [call[0][0] for call in mock_sleep.call_args_list]
            assert actual_sleeps == expected_sleeps

    @pytest.mark.asyncio
    async def test_fetch_success_after_retry(self, consumer, sample_email_full):
        """Fetch réussi après quelques retries"""
        consumer.http_client = AsyncMock()

        # Simuler 2 échecs puis succès
        mock_responses = [
            MagicMock(status_code=500),  # Échec 1
            MagicMock(status_code=500),  # Échec 2
            MagicMock(status_code=200, json=lambda: sample_email_full)  # Succès 3
        ]
        consumer.http_client.get = AsyncMock(side_effect=mock_responses)

        with patch('asyncio.sleep'):
            result = await consumer.fetch_email_from_emailengine('account-test', 'msg_123', max_retries=6)

        assert result == sample_email_full
        assert consumer.http_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_fetch_max_retries_exceeded(self, consumer):
        """Échec après max_retries doit retourner None"""
        consumer.http_client = AsyncMock()
        mock_response = MagicMock(status_code=500)
        consumer.http_client.get = AsyncMock(return_value=mock_response)

        with patch('asyncio.sleep'):
            result = await consumer.fetch_email_from_emailengine('account-test', 'msg_123', max_retries=3)

        assert result is None
        assert consumer.http_client.get.call_count == 4  # 1 initial + 3 retries


class TestDeadLetterQueue:
    """Tests Dead-Letter Queue (DLQ)"""

    @pytest.mark.asyncio
    async def test_send_to_dlq_publishes_event(self, consumer, sample_event_payload):
        """Envoi DLQ doit publier dans stream emails:failed"""
        consumer.redis = AsyncMock()
        consumer.redis.xadd = AsyncMock(return_value='dlq-123')

        with patch.object(consumer, 'send_telegram_alert_dlq', new=AsyncMock()):
            await consumer.send_to_dlq('event-456', sample_event_payload, error='Fetch failed')

        # Vérifier XADD appelé avec bon stream
        consumer.redis.xadd.assert_called_once()
        call_args = consumer.redis.xadd.call_args
        assert call_args[0][0] == 'emails:failed'

        # Vérifier payload DLQ contient original + erreur
        dlq_payload = call_args[0][1]
        assert dlq_payload['original_event_id'] == 'event-456'
        assert dlq_payload['error'] == 'Fetch failed'
        assert dlq_payload['retry_count'] == '6'

    @pytest.mark.asyncio
    async def test_send_to_dlq_sends_telegram_alert(self, consumer, sample_event_payload):
        """Envoi DLQ doit alerter Telegram topic System"""
        consumer.redis = AsyncMock()
        consumer.redis.xadd = AsyncMock(return_value='dlq-123')

        with patch.object(consumer, 'send_telegram_alert_dlq', new=AsyncMock()) as mock_alert:
            await consumer.send_to_dlq('event-456', sample_event_payload, error='Fetch failed')

            mock_alert.assert_called_once()
            call_kwargs = mock_alert.call_args[1]
            assert call_kwargs['message_id'] == 'msg_123'
            assert call_kwargs['error'] == 'Fetch failed'


class TestStoreEmailDatabase:
    """Tests stockage email dans PostgreSQL"""

    @pytest.mark.asyncio
    async def test_store_email_inserts_anonymized(self, consumer):
        """Store doit insérer email anonymisé dans ingestion.emails"""
        consumer.db = AsyncMock()
        consumer.db.fetchval = AsyncMock(return_value='uuid-email-123')
        consumer.db.execute = AsyncMock()

        email_id = await consumer.store_email_in_database(
            account_id='account-test',
            message_id='msg_123',
            from_anon='[EMAIL_1]',
            subject_anon='Rdv [PERSON_1]',
            body_anon='Bonjour [PERSON_1]...',
            category='medical',
            confidence=0.9,
            received_at='2026-02-11T10:30:00Z',
            has_attachments=False,
            from_raw='john.doe@example.com',
            to_raw='me@example.com',
            subject_raw='Rdv Dr Smith',
            body_raw='Bonjour John...'
        )

        assert email_id == 'uuid-email-123'

        # Vérifier INSERT ingestion.emails appelé
        assert consumer.db.fetchval.called
        fetchval_call = consumer.db.fetchval.call_args[0][0]
        assert 'INSERT INTO ingestion.emails' in fetchval_call

    @pytest.mark.asyncio
    async def test_store_email_inserts_encrypted_raw(self, consumer):
        """Store doit insérer email raw chiffré dans ingestion.emails_raw"""
        consumer.db = AsyncMock()
        consumer.db.fetchval = AsyncMock(return_value='uuid-email-123')
        consumer.db.execute = AsyncMock()

        await consumer.store_email_in_database(
            account_id='account-test',
            message_id='msg_123',
            from_anon='[EMAIL_1]',
            subject_anon='Rdv [PERSON_1]',
            body_anon='Bonjour [PERSON_1]...',
            category='medical',
            confidence=0.9,
            received_at='2026-02-11T10:30:00Z',
            has_attachments=False,
            from_raw='john.doe@example.com',
            to_raw='me@example.com',
            subject_raw='Rdv Dr Smith',
            body_raw='Bonjour John...'
        )

        # Vérifier INSERT ingestion.emails_raw appelé avec pgp_sym_encrypt
        assert consumer.db.execute.called
        execute_call = consumer.db.execute.call_args[0][0]
        assert 'INSERT INTO ingestion.emails_raw' in execute_call
        assert 'pgp_sym_encrypt' in execute_call


class TestTelegramNotification:
    """Tests notification Telegram"""

    @pytest.mark.asyncio
    async def test_send_notification_success(self, consumer):
        """Notification Telegram réussie"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock(status_code=200)
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            await consumer.send_telegram_notification(
                account_id='account-test',
                from_anon='[EMAIL_1]',
                subject_anon='Rdv [PERSON_1]',
                category='medical'
            )

            # Vérifier que POST Telegram API appelé
            mock_client.return_value.__aenter__.return_value.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_notification_skips_if_not_configured(self, consumer):
        """Notification skip si TELEGRAM_BOT_TOKEN non configuré"""
        with patch.dict('os.environ', {}, clear=True):
            # Pas d'exception, juste skip
            await consumer.send_telegram_notification(
                account_id='account-test',
                from_anon='[EMAIL_1]',
                subject_anon='Rdv [PERSON_1]',
                category='medical'
            )

    @pytest.mark.asyncio
    async def test_send_notification_no_emojis(self, consumer):
        """Notification NE DOIT PAS contenir d'emojis"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock(status_code=200)
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            await consumer.send_telegram_notification(
                account_id='account-test',
                from_anon='[EMAIL_1]',
                subject_anon='Rdv [PERSON_1]',
                category='medical'
            )

            # Vérifier que le texte ne contient PAS d'emojis
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            notification_text = call_args[1]['json']['text']

            # Vérifier pas d'emojis courants
            assert '📬' not in notification_text
            assert '✅' not in notification_text
            assert '❌' not in notification_text


class TestProcessEmailEvent:
    """Tests process_email_event complet"""

    @pytest.mark.asyncio
    async def test_process_event_success_flow(self, consumer, sample_event_payload, sample_email_full):
        """Process complet success: fetch → anonymize → store → notify → XACK"""
        # Mock toutes les dépendances
        consumer.redis = AsyncMock()
        consumer.db = AsyncMock()
        consumer.http_client = AsyncMock()

        # Mock fetch
        mock_response = MagicMock(status_code=200, json=lambda: sample_email_full)
        consumer.http_client.get = AsyncMock(return_value=mock_response)

        # Mock anonymize
        with patch('services.email_processor.consumer.anonymize_text', return_value='[ANONYMIZED]'):
            # Mock store
            consumer.db.fetchval = AsyncMock(return_value='uuid-123')
            consumer.db.execute = AsyncMock()

            # Mock telegram
            with patch.object(consumer, 'send_telegram_notification', new=AsyncMock()):
                # Process
                await consumer.process_email_event('event-123', sample_event_payload)

        # Vérifier XACK appelé (success)
        consumer.redis.xack.assert_called_once_with('emails:received', 'email-processor-group', 'event-123')

    @pytest.mark.asyncio
    async def test_process_event_fetch_fail_sends_dlq(self, consumer, sample_event_payload):
        """Fetch fail après retries → DLQ + XACK"""
        consumer.redis = AsyncMock()

        # Mock fetch fail
        mock_response = MagicMock(status_code=500)
        consumer.http_client = AsyncMock()
        consumer.http_client.get = AsyncMock(return_value=mock_response)

        with patch('asyncio.sleep'):
            with patch.object(consumer, 'send_to_dlq', new=AsyncMock()) as mock_dlq:
                await consumer.process_email_event('event-123', sample_event_payload)

                # Vérifier DLQ appelé
                mock_dlq.assert_called_once()

                # Vérifier XACK appelé (retire du PEL)
                consumer.redis.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_event_exception_no_xack(self, consumer, sample_event_payload):
        """Exception durant process → PAS de XACK (reste dans PEL)"""
        consumer.redis = AsyncMock()

        # Mock fetch success mais exception après
        mock_response = MagicMock(status_code=200, json=lambda: {'id': 'msg_123'})
        consumer.http_client = AsyncMock()
        consumer.http_client.get = AsyncMock(return_value=mock_response)

        # Mock anonymize fail
        with patch('services.email_processor.consumer.anonymize_text', side_effect=Exception("Anonymize fail")):
            await consumer.process_email_event('event-123', sample_event_payload)

        # Vérifier PAS de XACK (message reste dans PEL)
        consumer.redis.xack.assert_not_called()
