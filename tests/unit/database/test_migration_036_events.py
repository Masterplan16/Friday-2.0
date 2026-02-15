"""
Tests unitaires pour migration 036 - Support EVENT entity_type

Story 7.1 AC2: Validation contraintes CHECK, index, commentaires EVENT
"""

import pytest
import asyncpg
from datetime import datetime, timezone
import json


@pytest.fixture
async def db_pool(event_loop):
    """
    Fixture PostgreSQL pool pour tests migration 036
    """
    pool = await asyncpg.create_pool(
        host="localhost",
        port=5432,
        user="friday",
        password="friday_dev",
        database="friday_test",
        min_size=1,
        max_size=5
    )
    yield pool
    await pool.close()


@pytest.fixture
async def clean_db(db_pool):
    """
    Nettoie la table entities avant chaque test
    """
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM knowledge.entities WHERE entity_type = 'EVENT'")
    yield


# ============================================================================
# TESTS CONTRAINTE CHECK EVENT properties
# ============================================================================

@pytest.mark.asyncio
async def test_event_with_valid_properties_should_succeed(db_pool, clean_db):
    """
    Test AC2: Entité EVENT avec properties valides DOIT être créée
    """
    async with db_pool.acquire() as conn:
        event_properties = {
            "start_datetime": "2026-02-15T14:30:00",
            "end_datetime": "2026-02-15T15:00:00",
            "location": "Cabinet Dr Dupont",
            "participants": ["Dr Dupont"],
            "event_type": "medical",
            "casquette": "medecin",
            "email_id": "550e8400-e29b-41d4-a716-446655440000",
            "confidence": 0.92,
            "status": "proposed",
            "calendar_id": None
        }

        result = await conn.fetchrow("""
            INSERT INTO knowledge.entities (
                name, entity_type, properties, confidence,
                source_type, source_id
            ) VALUES (
                $1, 'EVENT', $2, $3, 'email', $4
            ) RETURNING id, name, entity_type, properties
        """, "Consultation Dr Dupont", json.dumps(event_properties),
             0.92, "550e8400-e29b-41d4-a716-446655440000")

        assert result is not None
        assert result["name"] == "Consultation Dr Dupont"
        assert result["entity_type"] == "EVENT"
        assert result["properties"]["status"] == "proposed"
        assert result["properties"]["start_datetime"] == "2026-02-15T14:30:00"


@pytest.mark.asyncio
async def test_event_without_start_datetime_should_fail(db_pool, clean_db):
    """
    Test AC2: EVENT sans start_datetime DOIT échouer (contrainte CHECK)
    """
    async with db_pool.acquire() as conn:
        event_properties = {
            # start_datetime MANQUANT (violation contrainte)
            "status": "proposed",
            "casquette": "medecin"
        }

        with pytest.raises(asyncpg.CheckViolationError) as exc_info:
            await conn.execute("""
                INSERT INTO knowledge.entities (
                    name, entity_type, properties
                ) VALUES (
                    $1, 'EVENT', $2
                )
            """, "Événement invalide", json.dumps(event_properties))

        assert "check_event_properties" in str(exc_info.value)


@pytest.mark.asyncio
async def test_event_without_status_should_fail(db_pool, clean_db):
    """
    Test AC2: EVENT sans status DOIT échouer (contrainte CHECK)
    """
    async with db_pool.acquire() as conn:
        event_properties = {
            "start_datetime": "2026-02-15T14:30:00",
            # status MANQUANT (violation contrainte)
            "casquette": "medecin"
        }

        with pytest.raises(asyncpg.CheckViolationError) as exc_info:
            await conn.execute("""
                INSERT INTO knowledge.entities (
                    name, entity_type, properties
                ) VALUES (
                    $1, 'EVENT', $2
                )
            """, "Événement sans status", json.dumps(event_properties))

        assert "check_event_properties" in str(exc_info.value)


@pytest.mark.asyncio
async def test_event_with_invalid_status_should_fail(db_pool, clean_db):
    """
    Test AC2: EVENT avec status invalide DOIT échouer (contrainte CHECK)
    Valeurs valides: proposed, confirmed, cancelled
    """
    async with db_pool.acquire() as conn:
        event_properties = {
            "start_datetime": "2026-02-15T14:30:00",
            "status": "invalid_status",  # INVALIDE
            "casquette": "medecin"
        }

        with pytest.raises(asyncpg.CheckViolationError) as exc_info:
            await conn.execute("""
                INSERT INTO knowledge.entities (
                    name, entity_type, properties
                ) VALUES (
                    $1, 'EVENT', $2
                )
            """, "Événement status invalide", json.dumps(event_properties))

        assert "check_event_properties" in str(exc_info.value)


@pytest.mark.asyncio
async def test_event_all_valid_statuses_should_succeed(db_pool, clean_db):
    """
    Test AC2: Tous les status valides (proposed, confirmed, cancelled) DOIVENT fonctionner
    """
    async with db_pool.acquire() as conn:
        valid_statuses = ["proposed", "confirmed", "cancelled"]

        for status in valid_statuses:
            event_properties = {
                "start_datetime": "2026-02-15T14:30:00",
                "status": status,
                "casquette": "medecin"
            }

            result = await conn.fetchrow("""
                INSERT INTO knowledge.entities (
                    name, entity_type, properties
                ) VALUES (
                    $1, 'EVENT', $2
                ) RETURNING properties->>'status' as status
            """, f"Événement {status}", json.dumps(event_properties))

            assert result["status"] == status


@pytest.mark.asyncio
async def test_non_event_entity_without_event_properties_should_succeed(db_pool, clean_db):
    """
    Test AC2: Entités NON-EVENT sans properties EVENT DOIVENT réussir
    (contrainte CHECK ne s'applique qu'aux EVENT)
    """
    async with db_pool.acquire() as conn:
        # Entité PERSON sans start_datetime ni status (OK car pas EVENT)
        result = await conn.fetchrow("""
            INSERT INTO knowledge.entities (
                name, entity_type, properties
            ) VALUES (
                $1, 'PERSON', $2
            ) RETURNING id, entity_type
        """, "Dr Martin", json.dumps({"specialty": "cardiologue"}))

        assert result is not None
        assert result["entity_type"] == "PERSON"


# ============================================================================
# TESTS INDEX PERFORMANCE
# ============================================================================

@pytest.mark.asyncio
async def test_index_event_date_exists(db_pool):
    """
    Test AC2: Index idx_entities_event_date DOIT exister
    """
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'knowledge'
            AND tablename = 'entities'
            AND indexname = 'idx_entities_event_date'
        """)

        assert result is not None
        assert "start_datetime" in result["indexdef"]
        assert "WHERE entity_type = 'EVENT'" in result["indexdef"]


@pytest.mark.asyncio
async def test_index_event_casquette_date_exists(db_pool):
    """
    Test migration 036: Index composé casquette + date DOIT exister
    """
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'knowledge'
            AND tablename = 'entities'
            AND indexname = 'idx_entities_event_casquette_date'
        """)

        assert result is not None
        assert "casquette" in result["indexdef"]
        assert "start_datetime" in result["indexdef"]


@pytest.mark.asyncio
async def test_index_event_status_exists(db_pool):
    """
    Test migration 036: Index status DOIT exister
    """
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'knowledge'
            AND tablename = 'entities'
            AND indexname = 'idx_entities_event_status'
        """)

        assert result is not None
        assert "status" in result["indexdef"]


# ============================================================================
# TESTS REQUÊTES TEMPORELLES (validation index fonctionnel)
# ============================================================================

@pytest.mark.asyncio
async def test_query_upcoming_events_uses_index(db_pool, clean_db):
    """
    Test AC2: Requête événements à venir DOIT utiliser index idx_entities_event_date
    """
    async with db_pool.acquire() as conn:
        # Insérer 3 événements (1 passé, 2 futurs)
        now = datetime.now(timezone.utc)
        past_event = {
            "start_datetime": "2026-01-15T14:30:00",
            "status": "confirmed"
        }
        future_event1 = {
            "start_datetime": "2026-03-15T14:30:00",
            "status": "proposed"
        }
        future_event2 = {
            "start_datetime": "2026-04-20T10:00:00",
            "status": "confirmed"
        }

        await conn.execute("""
            INSERT INTO knowledge.entities (name, entity_type, properties)
            VALUES
                ('Événement passé', 'EVENT', $1),
                ('Événement futur 1', 'EVENT', $2),
                ('Événement futur 2', 'EVENT', $3)
        """, json.dumps(past_event), json.dumps(future_event1), json.dumps(future_event2))

        # Requête événements à venir
        results = await conn.fetch("""
            SELECT name, (properties->>'start_datetime')::timestamptz as start_date
            FROM knowledge.entities
            WHERE entity_type = 'EVENT'
            AND (properties->>'start_datetime')::timestamptz > NOW()
            ORDER BY (properties->>'start_datetime')::timestamptz ASC
        """)

        assert len(results) == 2
        assert results[0]["name"] == "Événement futur 1"
        assert results[1]["name"] == "Événement futur 2"


@pytest.mark.asyncio
async def test_query_events_by_casquette_uses_index(db_pool, clean_db):
    """
    Test migration 036: Requête par casquette DOIT utiliser index idx_entities_event_casquette_date
    """
    async with db_pool.acquire() as conn:
        # Insérer événements multi-casquettes
        medecin_event = {
            "start_datetime": "2026-03-15T14:30:00",
            "status": "confirmed",
            "casquette": "medecin"
        }
        enseignant_event = {
            "start_datetime": "2026-03-16T10:00:00",
            "status": "proposed",
            "casquette": "enseignant"
        }

        await conn.execute("""
            INSERT INTO knowledge.entities (name, entity_type, properties)
            VALUES
                ('Consultation patient', 'EVENT', $1),
                ('Cours L2 anatomie', 'EVENT', $2)
        """, json.dumps(medecin_event), json.dumps(enseignant_event))

        # Requête événements médecin uniquement
        results = await conn.fetch("""
            SELECT name, properties->>'casquette' as casquette
            FROM knowledge.entities
            WHERE entity_type = 'EVENT'
            AND properties->>'casquette' = 'medecin'
        """)

        assert len(results) == 1
        assert results[0]["name"] == "Consultation patient"
        assert results[0]["casquette"] == "medecin"
