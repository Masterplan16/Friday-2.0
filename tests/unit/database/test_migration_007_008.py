"""Tests pour migrations 007 (knowledge.nodes/edges) et 008 (pgvector).

Test Strategy:
- Vérifier que migration 007 crée tables nodes/edges avec bonnes contraintes
- Vérifier compatibilité migration 008 (pgvector) après 007
- Vérifier que les 10 types de nœuds sont validés
- Vérifier que les 14 types de relations sont validés
"""

import asyncio
import pytest
import asyncpg
from pathlib import Path


@pytest.fixture
async def test_db():
    """Crée une base de données de test temporaire."""
    # Connexion à postgres pour créer la BDD test
    conn = await asyncpg.connect(
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        database="postgres"
    )

    test_db_name = "friday_test_migrations_007_008"

    # Drop si existe déjà
    await conn.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
    await conn.execute(f"CREATE DATABASE {test_db_name}")
    await conn.close()

    # Connexion à la BDD test
    test_conn = await asyncpg.connect(
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        database=test_db_name
    )

    yield test_conn

    # Cleanup
    await test_conn.close()

    # Drop BDD test
    conn = await asyncpg.connect(
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        database="postgres"
    )
    await conn.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
    await conn.close()


@pytest.mark.asyncio
async def test_migration_007_creates_schema(test_db):
    """Test que migration 007 crée schema knowledge avec uuid support."""
    # Créer extension uuid-ossp
    await test_db.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    # Créer schema knowledge
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS knowledge")

    # Créer schema core pour fonction update_updated_at
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS core")
    await test_db.execute("""
        CREATE OR REPLACE FUNCTION core.update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Lire et appliquer migration 007
    migration_path = Path(__file__).parent.parent.parent.parent / "database" / "migrations" / "007_knowledge_nodes_edges.sql"
    migration_sql = migration_path.read_text()

    await test_db.execute(migration_sql)

    # Vérifier que tables existent
    nodes_exists = await test_db.fetchval(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema='knowledge' AND table_name='nodes')"
    )
    assert nodes_exists, "Table knowledge.nodes doit exister"

    edges_exists = await test_db.fetchval(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema='knowledge' AND table_name='edges')"
    )
    assert edges_exists, "Table knowledge.edges doit exister"


@pytest.mark.asyncio
async def test_migration_007_node_types_validation(test_db):
    """Test que les 10 types de nœuds sont validés par contrainte CHECK."""
    # Setup schemas et migration
    await test_db.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS core")
    await test_db.execute("""
        CREATE OR REPLACE FUNCTION core.update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    migration_path = Path(__file__).parent.parent.parent.parent / "database" / "migrations" / "007_knowledge_nodes_edges.sql"
    migration_sql = migration_path.read_text()
    await test_db.execute(migration_sql)

    # Test types valides (10 types)
    valid_types = ['person', 'email', 'document', 'event', 'task',
                   'entity', 'conversation', 'transaction', 'file', 'reminder']

    for node_type in valid_types:
        node_id = await test_db.fetchval(
            "INSERT INTO knowledge.nodes (type, name) VALUES ($1, $2) RETURNING id",
            node_type, f"Test {node_type}"
        )
        assert node_id is not None, f"Type {node_type} doit être accepté"

    # Test type invalide
    with pytest.raises(asyncpg.CheckViolationError):
        await test_db.execute(
            "INSERT INTO knowledge.nodes (type, name) VALUES ($1, $2)",
            "invalid_type", "Test invalide"
        )


@pytest.mark.asyncio
async def test_migration_007_relation_types_validation(test_db):
    """Test que les 14 types de relations sont validés par contrainte CHECK."""
    # Setup
    await test_db.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS core")
    await test_db.execute("""
        CREATE OR REPLACE FUNCTION core.update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    migration_path = Path(__file__).parent.parent.parent.parent / "database" / "migrations" / "007_knowledge_nodes_edges.sql"
    migration_sql = migration_path.read_text()
    await test_db.execute(migration_sql)

    # Créer 2 nœuds de test
    node1_id = await test_db.fetchval(
        "INSERT INTO knowledge.nodes (type, name) VALUES ($1, $2) RETURNING id",
        "person", "John Doe"
    )
    node2_id = await test_db.fetchval(
        "INSERT INTO knowledge.nodes (type, name) VALUES ($1, $2) RETURNING id",
        "email", "Test email"
    )

    # Test types de relations valides (14 types)
    valid_relations = [
        'sent_by', 'received_by', 'attached_to', 'mentions', 'related_to',
        'assigned_to', 'created_from', 'scheduled', 'references', 'part_of',
        'paid_with', 'belongs_to', 'reminds_about', 'supersedes'
    ]

    for relation_type in valid_relations:
        edge_id = await test_db.fetchval(
            "INSERT INTO knowledge.edges (from_node_id, to_node_id, relation_type) VALUES ($1, $2, $3) RETURNING id",
            node1_id, node2_id, relation_type
        )
        assert edge_id is not None, f"Relation {relation_type} doit être acceptée"

        # Cleanup pour éviter violation contrainte unique
        await test_db.execute("DELETE FROM knowledge.edges WHERE id = $1", edge_id)

    # Test type de relation invalide
    with pytest.raises(asyncpg.CheckViolationError):
        await test_db.execute(
            "INSERT INTO knowledge.edges (from_node_id, to_node_id, relation_type) VALUES ($1, $2, $3)",
            node1_id, node2_id, "invalid_relation"
        )


@pytest.mark.asyncio
async def test_migration_008_compatible_with_007(test_db):
    """Test que migration 008 (pgvector) s'applique correctement après 007."""
    # Setup schemas + migration 007
    await test_db.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS core")
    await test_db.execute("""
        CREATE OR REPLACE FUNCTION core.update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    migration_007_path = Path(__file__).parent.parent.parent.parent / "database" / "migrations" / "007_knowledge_nodes_edges.sql"
    migration_007_sql = migration_007_path.read_text()
    await test_db.execute(migration_007_sql)

    # Appliquer migration 008
    migration_008_path = Path(__file__).parent.parent.parent.parent / "database" / "migrations" / "008_knowledge_embeddings.sql"
    migration_008_sql = migration_008_path.read_text()
    await test_db.execute(migration_008_sql)

    # Vérifier que table embeddings existe
    embeddings_exists = await test_db.fetchval(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema='knowledge' AND table_name='embeddings')"
    )
    assert embeddings_exists, "Table knowledge.embeddings doit exister après migration 008"

    # Vérifier que extension vector est créée
    vector_exists = await test_db.fetchval(
        "SELECT EXISTS (SELECT FROM pg_extension WHERE extname='vector')"
    )
    assert vector_exists, "Extension vector doit exister"


@pytest.mark.asyncio
async def test_migration_007_indexes_created(test_db):
    """Test que tous les index sont créés correctement."""
    # Setup
    await test_db.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS core")
    await test_db.execute("""
        CREATE OR REPLACE FUNCTION core.update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    migration_path = Path(__file__).parent.parent.parent.parent / "database" / "migrations" / "007_knowledge_nodes_edges.sql"
    migration_sql = migration_path.read_text()
    await test_db.execute(migration_sql)

    # Vérifier index nodes
    expected_nodes_indexes = [
        'idx_nodes_type',
        'idx_nodes_created_at',
        'idx_nodes_valid_to',
        'idx_nodes_source',
        'idx_nodes_metadata'
    ]

    for index_name in expected_nodes_indexes:
        index_exists = await test_db.fetchval(
            "SELECT EXISTS (SELECT FROM pg_indexes WHERE schemaname='knowledge' AND tablename='nodes' AND indexname=$1)",
            index_name
        )
        assert index_exists, f"Index {index_name} doit exister"

    # Vérifier index edges
    expected_edges_indexes = [
        'idx_edges_from_node',
        'idx_edges_to_node',
        'idx_edges_relation_type',
        'idx_edges_created_at',
        'idx_edges_valid_to',
        'idx_edges_metadata'
    ]

    for index_name in expected_edges_indexes:
        index_exists = await test_db.fetchval(
            "SELECT EXISTS (SELECT FROM pg_indexes WHERE schemaname='knowledge' AND tablename='edges' AND indexname=$1)",
            index_name
        )
        assert index_exists, f"Index {index_name} doit exister"


@pytest.mark.asyncio
async def test_migration_007_trigger_updated_at(test_db):
    """Test que trigger updated_at fonctionne sur knowledge.nodes."""
    # Setup
    await test_db.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    await test_db.execute("CREATE SCHEMA IF NOT EXISTS core")
    await test_db.execute("""
        CREATE OR REPLACE FUNCTION core.update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    migration_path = Path(__file__).parent.parent.parent.parent / "database" / "migrations" / "007_knowledge_nodes_edges.sql"
    migration_sql = migration_path.read_text()
    await test_db.execute(migration_sql)

    # Créer un nœud
    node_id = await test_db.fetchval(
        "INSERT INTO knowledge.nodes (type, name) VALUES ($1, $2) RETURNING id",
        "person", "Test Person"
    )

    # Récupérer updated_at initial
    initial_updated_at = await test_db.fetchval(
        "SELECT updated_at FROM knowledge.nodes WHERE id = $1",
        node_id
    )

    # Attendre 1 seconde
    await asyncio.sleep(1)

    # Mettre à jour le nœud
    await test_db.execute(
        "UPDATE knowledge.nodes SET name = $1 WHERE id = $2",
        "Updated Person", node_id
    )

    # Récupérer updated_at après mise à jour
    updated_updated_at = await test_db.fetchval(
        "SELECT updated_at FROM knowledge.nodes WHERE id = $1",
        node_id
    )

    # Vérifier que updated_at a changé
    assert updated_updated_at > initial_updated_at, "updated_at doit être mis à jour automatiquement"
