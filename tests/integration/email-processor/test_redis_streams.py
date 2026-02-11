"""
Tests intégration Redis Streams
Story 2.1 - Subtask 6.3
Tests: XADD, XREADGROUP, XACK, consumer groups, PEL, DLQ
"""

import pytest
import asyncio
import redis.asyncio as redis
from datetime import datetime


@pytest.fixture
async def redis_client():
    """Client Redis pour tests intégration"""
    client = redis.from_url('redis://localhost:6379', decode_responses=True)
    yield client
    await client.close()


@pytest.fixture
async def cleanup_streams(redis_client):
    """Nettoyer streams après tests"""
    yield
    # Cleanup
    try:
        await redis_client.delete('emails:received', 'emails:failed')
        await redis_client.xgroup_destroy('emails:received', 'test-group')
    except:
        pass


@pytest.mark.integration
class TestRedisStreamsBasics:
    """Tests basiques Redis Streams"""

    @pytest.mark.asyncio
    async def test_xadd_creates_event(self, redis_client, cleanup_streams):
        """XADD doit créer événement dans stream"""
        event_id = await redis_client.xadd(
            'emails:received',
            {'message_id': 'msg_test', 'account_id': 'test'}
        )

        assert event_id is not None
        assert '-' in event_id  # Format: timestamp-sequence

    @pytest.mark.asyncio
    async def test_xread_retrieves_events(self, redis_client, cleanup_streams):
        """XREAD doit récupérer événements"""
        # Ajouter événement
        await redis_client.xadd('emails:received', {'test': 'data'})

        # Lire depuis début
        events = await redis_client.xread({'emails:received': '0'}, count=10)

        assert len(events) > 0
        assert events[0][0] == 'emails:received'


@pytest.mark.integration
class TestConsumerGroups:
    """Tests consumer groups"""

    @pytest.mark.asyncio
    async def test_create_consumer_group(self, redis_client, cleanup_streams):
        """Création consumer group"""
        await redis_client.xgroup_create(
            'emails:received',
            'test-group',
            id='$',
            mkstream=True
        )

        # Vérifier groupe existe
        groups = await redis_client.xinfo_groups('emails:received')
        assert len(groups) == 1
        assert groups[0]['name'] == 'test-group'

    @pytest.mark.asyncio
    async def test_xreadgroup_consumes_events(self, redis_client, cleanup_streams):
        """XREADGROUP consomme événements uniquement pour ce consumer"""
        # Setup
        await redis_client.xgroup_create('emails:received', 'test-group', id='$', mkstream=True)

        # Ajouter événement
        await redis_client.xadd('emails:received', {'msg': 'test1'})

        # Consumer 1 lit
        events = await redis_client.xreadgroup(
            'test-group',
            'consumer-1',
            {'emails:received': '>'},
            count=10
        )

        assert len(events) == 1

        # Consumer 2 ne doit PAS voir le même événement
        events2 = await redis_client.xreadgroup(
            'test-group',
            'consumer-2',
            {'emails:received': '>'},
            count=10
        )

        assert len(events2) == 0  # Déjà consommé par consumer-1


@pytest.mark.integration
class TestPendingEntriesList:
    """Tests PEL (Pending Entries List)"""

    @pytest.mark.asyncio
    async def test_message_added_to_pel_after_xreadgroup(self, redis_client, cleanup_streams):
        """Message doit être dans PEL après XREADGROUP"""
        await redis_client.xgroup_create('emails:received', 'test-group', id='$', mkstream=True)

        # Ajouter événement
        event_id = await redis_client.xadd('emails:received', {'msg': 'test'})

        # Consumer lit (sans XACK)
        await redis_client.xreadgroup('test-group', 'consumer-1', {'emails:received': '>'})

        # Vérifier PEL
        pending = await redis_client.xpending('emails:received', 'test-group')
        assert pending['pending'] == 1

    @pytest.mark.asyncio
    async def test_xack_removes_from_pel(self, redis_client, cleanup_streams):
        """XACK doit retirer message du PEL"""
        await redis_client.xgroup_create('emails:received', 'test-group', id='$', mkstream=True)

        event_id = await redis_client.xadd('emails:received', {'msg': 'test'})

        # Consumer lit
        events = await redis_client.xreadgroup('test-group', 'consumer-1', {'emails:received': '>'})

        # XACK
        await redis_client.xack('emails:received', 'test-group', event_id)

        # Vérifier PEL vide
        pending = await redis_client.xpending('emails:received', 'test-group')
        assert pending['pending'] == 0

    @pytest.mark.asyncio
    async def test_crash_consumer_message_stays_in_pel(self, redis_client, cleanup_streams):
        """Si consumer crash (pas XACK), message reste dans PEL"""
        await redis_client.xgroup_create('emails:received', 'test-group', id='$', mkstream=True)

        event_id = await redis_client.xadd('emails:received', {'msg': 'test'})

        # Consumer lit puis crash (pas XACK)
        await redis_client.xreadgroup('test-group', 'consumer-crash', {'emails:received': '>'})

        # Message doit rester dans PEL
        pending = await redis_client.xpending('emails:received', 'test-group')
        assert pending['pending'] == 1


@pytest.mark.integration
class TestDeadLetterQueue:
    """Tests DLQ (Dead-Letter Queue)"""

    @pytest.mark.asyncio
    async def test_dlq_stream_creation(self, redis_client, cleanup_streams):
        """Stream DLQ doit être créé"""
        # Publier dans DLQ
        dlq_id = await redis_client.xadd(
            'emails:failed',
            {
                'original_event_id': 'event-123',
                'error': 'Max retries exceeded',
                'retry_count': '6'
            }
        )

        assert dlq_id is not None

        # Vérifier événement dans DLQ
        events = await redis_client.xread({'emails:failed': '0'})
        assert len(events) == 1
        assert events[0][0] == 'emails:failed'
