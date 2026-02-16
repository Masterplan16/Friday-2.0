"""
Tests d'intégration pour Migration 037: Multi-Casquettes Context & Calendar Conflicts

Story 7.3: Multi-casquettes & Conflits Calendrier
Tests:
- Migration sur DB vierge
- Migration sur DB avec entités EVENT existantes
- Seed initial core.user_context
- Contraintes CHECK
- Trigger last_updated_at
- Rollback complet
"""

import asyncio
import asyncpg
import pytest
from datetime import datetime, timedelta
from uuid import uuid4


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def db_pool():
    """Connexion PostgreSQL pour tests."""
    pool = await asyncpg.create_pool(
        host="localhost",
        port=5432,
        database="friday_test",
        user="postgres",
        password="postgres",
        min_size=1,
        max_size=5
    )
    yield pool
    await pool.close()


@pytest.fixture
async def clean_db(db_pool):
    """Nettoie les tables avant chaque test."""
    async with db_pool.acquire() as conn:
        # Rollback migration 037 si existe
        await conn.execute("DROP TABLE IF EXISTS knowledge.calendar_conflicts CASCADE")
        await conn.execute("DROP TRIGGER IF EXISTS trigger_update_user_context_timestamp ON core.user_context")
        await conn.execute("DROP FUNCTION IF EXISTS core.update_user_context_timestamp() CASCADE")
        await conn.execute("DROP TABLE IF EXISTS core.user_context CASCADE")
    yield
    # Cleanup après test
    async with db_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS knowledge.calendar_conflicts CASCADE")
        await conn.execute("DROP TABLE IF EXISTS core.user_context CASCADE")


@pytest.fixture
async def applied_migration(db_pool, clean_db):
    """Applique migration 037."""
    async with db_pool.acquire() as conn:
        # Lire et exécuter migration
        with open("database/migrations/037_context_conflicts.sql", "r", encoding="utf-8") as f:
            migration_sql = f.read()
        await conn.execute(migration_sql)
    yield
    # Rollback après test
    async with db_pool.acquire() as conn:
        with open("database/migrations/037_context_conflicts_rollback.sql", "r", encoding="utf-8") as f:
            rollback_sql = f.read()
        await conn.execute(rollback_sql)


# ============================================================================
# Tests Migration 037
# ============================================================================

@pytest.mark.asyncio
async def test_migration_037_creates_user_context_table(db_pool, applied_migration):
    """Test: Table core.user_context créée avec seed initial."""
    async with db_pool.acquire() as conn:
        # Vérifier table existe
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'core'
                AND table_name = 'user_context'
            )
        """)
        assert table_exists is True, "Table core.user_context non créée"

        # Vérifier seed initial (id=1, casquette=NULL, updated_by='system')
        row = await conn.fetchrow("SELECT * FROM core.user_context WHERE id = 1")
        assert row is not None, "Seed initial core.user_context manquant"
        assert row["id"] == 1
        assert row["current_casquette"] is None  # Auto-detect par défaut
        assert row["updated_by"] == "system"
        assert row["last_updated_at"] is not None


@pytest.mark.asyncio
async def test_migration_037_creates_calendar_conflicts_table(db_pool, applied_migration):
    """Test: Table knowledge.calendar_conflicts créée avec index."""
    async with db_pool.acquire() as conn:
        # Vérifier table existe
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'knowledge'
                AND table_name = 'calendar_conflicts'
            )
        """)
        assert table_exists is True, "Table knowledge.calendar_conflicts non créée"

        # Vérifier index idx_conflicts_unresolved existe
        index_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'knowledge'
                AND tablename = 'calendar_conflicts'
                AND indexname = 'idx_conflicts_unresolved'
            )
        """)
        assert index_exists is True, "Index idx_conflicts_unresolved non créé"

        # Vérifier index unique idx_conflicts_unique_pair existe
        unique_index_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'knowledge'
                AND tablename = 'calendar_conflicts'
                AND indexname = 'idx_conflicts_unique_pair'
            )
        """)
        assert unique_index_exists is True, "Index idx_conflicts_unique_pair non créé"


@pytest.mark.asyncio
async def test_user_context_singleton_constraint(db_pool, applied_migration):
    """Test: Contrainte singleton user_context (seulement id=1 possible)."""
    async with db_pool.acquire() as conn:
        # Tentative INSERT id=2 → doit échouer
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("""
                INSERT INTO core.user_context (id, current_casquette, updated_by)
                VALUES (2, 'medecin', 'system')
            """)

        # UPDATE id=1 → doit réussir
        await conn.execute("""
            UPDATE core.user_context
            SET current_casquette = 'enseignant', updated_by = 'manual'
            WHERE id = 1
        """)

        row = await conn.fetchrow("SELECT * FROM core.user_context WHERE id = 1")
        assert row["current_casquette"] == "enseignant"
        assert row["updated_by"] == "manual"


@pytest.mark.asyncio
async def test_user_context_check_constraint_casquette(db_pool, applied_migration):
    """Test: Contrainte CHECK casquette valeurs autorisées."""
    async with db_pool.acquire() as conn:
        # Valeur invalide → doit échouer
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("""
                UPDATE core.user_context
                SET current_casquette = 'invalid_value'
                WHERE id = 1
            """)

        # Valeurs valides → doivent réussir
        for casquette in ["medecin", "enseignant", "chercheur", None]:
            await conn.execute("""
                UPDATE core.user_context
                SET current_casquette = $1
                WHERE id = 1
            """, casquette)

            row = await conn.fetchrow("SELECT current_casquette FROM core.user_context WHERE id = 1")
            assert row["current_casquette"] == casquette


@pytest.mark.asyncio
async def test_user_context_trigger_last_updated_at(db_pool, applied_migration):
    """Test: Trigger update_user_context_timestamp met à jour last_updated_at."""
    async with db_pool.acquire() as conn:
        # Récupérer timestamp initial
        row1 = await conn.fetchrow("SELECT last_updated_at FROM core.user_context WHERE id = 1")
        timestamp_before = row1["last_updated_at"]

        # Attendre 1 seconde
        await asyncio.sleep(1)

        # UPDATE contexte
        await conn.execute("""
            UPDATE core.user_context
            SET current_casquette = 'medecin'
            WHERE id = 1
        """)

        # Vérifier last_updated_at a changé
        row2 = await conn.fetchrow("SELECT last_updated_at FROM core.user_context WHERE id = 1")
        timestamp_after = row2["last_updated_at"]

        assert timestamp_after > timestamp_before, "Trigger last_updated_at non déclenché"


@pytest.mark.asyncio
async def test_calendar_conflicts_check_different_events(db_pool, applied_migration):
    """Test: Contrainte CHECK event1_id != event2_id."""
    async with db_pool.acquire() as conn:
        # Créer 2 événements test dans knowledge.entities
        event_id = uuid4()

        # Tentative INSERT même event1 = event2 → doit échouer
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("""
                INSERT INTO knowledge.calendar_conflicts (event1_id, event2_id, overlap_minutes)
                VALUES ($1, $1, 60)
            """, event_id)


@pytest.mark.asyncio
async def test_calendar_conflicts_check_overlap_minutes_positive(db_pool, applied_migration):
    """Test: Contrainte CHECK overlap_minutes > 0."""
    async with db_pool.acquire() as conn:
        event1_id = uuid4()
        event2_id = uuid4()

        # Tentative INSERT overlap_minutes <= 0 → doit échouer
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("""
                INSERT INTO knowledge.calendar_conflicts (event1_id, event2_id, overlap_minutes)
                VALUES ($1, $2, 0)
            """, event1_id, event2_id)

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("""
                INSERT INTO knowledge.calendar_conflicts (event1_id, event2_id, overlap_minutes)
                VALUES ($1, $2, -10)
            """, event1_id, event2_id)


@pytest.mark.asyncio
async def test_calendar_conflicts_unique_pair_constraint(db_pool, applied_migration):
    """Test: Index unique idx_conflicts_unique_pair prévient doublons conflits."""
    async with db_pool.acquire() as conn:
        # Créer 2 événements test
        event1_id = uuid4()
        event2_id = uuid4()

        # Créer entités EVENT dans knowledge.entities
        await conn.execute("""
            INSERT INTO knowledge.entities (id, entity_type, properties)
            VALUES
                ($1, 'EVENT', '{}'::jsonb),
                ($2, 'EVENT', '{}'::jsonb)
        """, event1_id, event2_id)

        # INSERT conflit (event1, event2)
        await conn.execute("""
            INSERT INTO knowledge.calendar_conflicts (event1_id, event2_id, overlap_minutes)
            VALUES ($1, $2, 60)
        """, event1_id, event2_id)

        # Tentative INSERT même conflit (event2, event1) → doit échouer (unique pair)
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute("""
                INSERT INTO knowledge.calendar_conflicts (event1_id, event2_id, overlap_minutes)
                VALUES ($1, $2, 60)
            """, event2_id, event1_id)


@pytest.mark.asyncio
async def test_migration_037_rollback(db_pool, clean_db):
    """Test: Rollback migration 037 supprime toutes les tables/index/triggers."""
    async with db_pool.acquire() as conn:
        # Appliquer migration
        with open("database/migrations/037_context_conflicts.sql", "r", encoding="utf-8") as f:
            migration_sql = f.read()
        await conn.execute(migration_sql)

        # Vérifier tables existent
        user_context_exists = await conn.fetchval("""
            SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'user_context')
        """)
        conflicts_exists = await conn.fetchval("""
            SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'knowledge' AND table_name = 'calendar_conflicts')
        """)
        assert user_context_exists is True
        assert conflicts_exists is True

        # Appliquer rollback
        with open("database/migrations/037_context_conflicts_rollback.sql", "r", encoding="utf-8") as f:
            rollback_sql = f.read()
        await conn.execute(rollback_sql)

        # Vérifier tables n'existent plus
        user_context_exists_after = await conn.fetchval("""
            SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'user_context')
        """)
        conflicts_exists_after = await conn.fetchval("""
            SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'knowledge' AND table_name = 'calendar_conflicts')
        """)
        assert user_context_exists_after is False, "Rollback: table user_context existe encore"
        assert conflicts_exists_after is False, "Rollback: table calendar_conflicts existe encore"

        # Vérifier fonction trigger n'existe plus
        function_exists = await conn.fetchval("""
            SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_user_context_timestamp')
        """)
        assert function_exists is False, "Rollback: fonction update_user_context_timestamp existe encore"


@pytest.mark.asyncio
async def test_migration_037_with_existing_events(db_pool, applied_migration):
    """Test: Migration 037 fonctionne avec entités EVENT existantes."""
    async with db_pool.acquire() as conn:
        # Créer entités EVENT dans knowledge.entities
        event1_id = uuid4()
        event2_id = uuid4()

        await conn.execute("""
            INSERT INTO knowledge.entities (id, entity_type, properties)
            VALUES
                ($1, 'EVENT', '{"casquette": "medecin", "start_datetime": "2026-02-17T14:30:00"}'::jsonb),
                ($2, 'EVENT', '{"casquette": "enseignant", "start_datetime": "2026-02-17T14:00:00"}'::jsonb)
        """, event1_id, event2_id)

        # Créer conflit référençant ces événements
        conflict_id = await conn.fetchval("""
            INSERT INTO knowledge.calendar_conflicts (event1_id, event2_id, overlap_minutes)
            VALUES ($1, $2, 60)
            RETURNING id
        """, event1_id, event2_id)

        assert conflict_id is not None, "Conflit non créé avec entités EVENT existantes"

        # Vérifier conflit créé correctement
        row = await conn.fetchrow("SELECT * FROM knowledge.calendar_conflicts WHERE id = $1", conflict_id)
        assert row["event1_id"] == event1_id
        assert row["event2_id"] == event2_id
        assert row["overlap_minutes"] == 60
        assert row["resolved"] is False


# ============================================================================
# Tests Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_calendar_conflicts_cascade_delete(db_pool, applied_migration):
    """Test: Suppression événement CASCADE delete conflits associés."""
    async with db_pool.acquire() as conn:
        # Créer 2 événements
        event1_id = uuid4()
        event2_id = uuid4()

        await conn.execute("""
            INSERT INTO knowledge.entities (id, entity_type, properties)
            VALUES
                ($1, 'EVENT', '{}'::jsonb),
                ($2, 'EVENT', '{}'::jsonb)
        """, event1_id, event2_id)

        # Créer conflit
        conflict_id = await conn.fetchval("""
            INSERT INTO knowledge.calendar_conflicts (event1_id, event2_id, overlap_minutes)
            VALUES ($1, $2, 60)
            RETURNING id
        """, event1_id, event2_id)

        # Supprimer event1 → conflit doit être CASCADE supprimé
        await conn.execute("DELETE FROM knowledge.entities WHERE id = $1", event1_id)

        # Vérifier conflit supprimé
        conflict_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM knowledge.calendar_conflicts WHERE id = $1)",
            conflict_id
        )
        assert conflict_exists is False, "Conflit pas CASCADE supprimé avec événement"


@pytest.mark.asyncio
async def test_calendar_conflicts_resolution_fields(db_pool, applied_migration):
    """Test: Champs resolved, resolved_at, resolution_action."""
    async with db_pool.acquire() as conn:
        # Créer 2 événements
        event1_id = uuid4()
        event2_id = uuid4()

        await conn.execute("""
            INSERT INTO knowledge.entities (id, entity_type, properties)
            VALUES
                ($1, 'EVENT', '{}'::jsonb),
                ($2, 'EVENT', '{}'::jsonb)
        """, event1_id, event2_id)

        # Créer conflit non résolu
        conflict_id = await conn.fetchval("""
            INSERT INTO knowledge.calendar_conflicts (event1_id, event2_id, overlap_minutes)
            VALUES ($1, $2, 60)
            RETURNING id
        """, event1_id, event2_id)

        # Vérifier valeurs par défaut
        row = await conn.fetchrow("SELECT * FROM knowledge.calendar_conflicts WHERE id = $1", conflict_id)
        assert row["resolved"] is False
        assert row["resolved_at"] is None
        assert row["resolution_action"] is None

        # Résoudre conflit (action='cancel')
        await conn.execute("""
            UPDATE knowledge.calendar_conflicts
            SET resolved = TRUE, resolved_at = NOW(), resolution_action = 'cancel'
            WHERE id = $1
        """, conflict_id)

        # Vérifier résolution
        row2 = await conn.fetchrow("SELECT * FROM knowledge.calendar_conflicts WHERE id = $1", conflict_id)
        assert row2["resolved"] is True
        assert row2["resolved_at"] is not None
        assert row2["resolution_action"] == "cancel"
