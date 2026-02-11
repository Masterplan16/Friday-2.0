# Guide de Migration Memorystore Provider

**Story 6.3** — Pattern abstraction pour évolutivité du graphe de connaissances Friday 2.0

**Date** : 2026-02-11
**Version** : 1.0.0

---

## Table des matières

1. [Philosophie abstraction](#1-philosophie-abstraction)
2. [Pattern actuel (PostgreSQL Day 1)](#2-pattern-actuel-postgresql-day-1)
3. [Swap vers Graphiti](#3-swap-vers-graphiti)
4. [Swap vers Neo4j](#4-swap-vers-neo4j)
5. [Swap vers Qdrant](#5-swap-vers-qdrant)
6. [Checklist compatibilité provider](#6-checklist-compatibilité-provider)

---

## 1. Philosophie abstraction

### Pourquoi une interface abstraite ?

**Problème** : Si Friday utilise directement PostgreSQL partout dans le code (imports directs de `PostgreSQLMemorystore`), alors :
- **Couplage fort** → Impossible de swap le backend sans refactoring massif
- **Tests difficiles** → Impossible de mocker facilement sans PostgreSQL réel
- **Évolution bloquée** → Si Graphiti devient mature ou si on dépasse 300k vecteurs, on est coincé

**Solution** : Interface abstraite `MemoryStore(ABC)` avec factory pattern :
- **Couplage faible** → Code métier dépend uniquement de l'interface
- **Tests faciles** → Mocker l'interface suffit, pas besoin de PostgreSQL
- **Évolution simple** → Ajouter backend = créer classe + 1 ligne factory + 1 variable env

### KISS Day 1, Split When Pain

**Principe** : Start Simple (PostgreSQL), Split When Pain (>300k vecteurs, latence >100ms, requêtes graphe complexes)

| Seuil | Déclencheur | Action |
|-------|-------------|--------|
| **< 100k nœuds** | Aucun | PostgreSQL + pgvector Day 1 ✅ |
| **> 300k vecteurs** | Latence recherche >100ms | Évaluer swap Qdrant (vectorstore séparé) |
| **Requêtes graphe complexes** | Besoin Cypher, shortest path multi-hop | Évaluer swap Neo4j |
| **Graphiti mature (août 2026)** | Documentation complète, stable | Évaluer Graphiti pour mémoire sémantique avancée |

**Note** : Un seul utilisateur (Antonio) → 100k nœuds = plusieurs années d'utilisation. PostgreSQL Day 1 est le bon choix.

---

## 2. Pattern actuel (PostgreSQL Day 1)

### Architecture

```mermaid
classDiagram
    class MemoryStore {
        <<interface>>
        +create_node() str
        +get_or_create_node() str
        +get_node_by_id() dict
        +get_nodes_by_type() list
        +create_edge() str
        +get_edges_by_type() list
        +get_related_nodes() list
        +get_node_with_relations() dict
        +query_path() list
        +query_temporal() list
        +semantic_search() list
    }

    class PostgreSQLMemorystore {
        -db_pool: asyncpg.Pool
        -_pgvector_initialized: bool
        +init_pgvector() None
        +create_node() str
        +get_node_by_id() dict
        +semantic_search() list
    }

    class GraphitiMemorystore {
        <<future>>
        -graphiti_client
        +create_node() str
    }

    class Neo4jMemorystore {
        <<future>>
        -neo4j_driver
        +query_path() list
    }

    MemoryStore <|.. PostgreSQLMemorystore
    MemoryStore <|.. GraphitiMemorystore
    MemoryStore <|.. Neo4jMemorystore
```

### Usage Day 1

**Code métier** (graph_populator, consumers, agents) :

```python
from agents.src.adapters.memorystore import get_memorystore_adapter

# Factory retourne interface MemoryStore (pas implémentation)
adapter = await get_memorystore_adapter()  # PostgreSQL par défaut

# Code métier dépend UNIQUEMENT de l'interface
node_id = await adapter.create_node("person", "Antonio Lopez", {...})
emails = await adapter.get_nodes_by_type("email", limit=50)
```

**Configuration** (`.env`) :

```bash
# Day 1: PostgreSQL
MEMORYSTORE_PROVIDER=postgresql
DATABASE_URL=postgresql://user:pass@localhost:5432/friday
```

**Bénéfices** :
- ✅ Aucun import direct de `PostgreSQLMemorystore` dans le code métier
- ✅ Swap backend = changer 1 variable env (pas de refactoring code)
- ✅ Tests mocks faciles (pas de PostgreSQL requis en tests unit)

---

## 3. Swap vers Graphiti

**Contexte** : Graphiti offre mémoire sémantique avancée (temporal reasoning, cross-document inference).

**Prérequis** :
- ✅ Graphiti stable (version 1.0+, documentation complète)
- ✅ Performance comparable à PostgreSQL (latence <100ms)
- ✅ Communauté active, maintenance régulière

**Réévaluation** : ~Août 2026 (6 mois après Decision D3)

### Étapes migration

#### Step 1 : Créer implémentation Graphiti

**Fichier** : `agents/src/adapters/graphiti_memorystore.py`

```python
from agents.src.adapters.memorystore_interface import MemoryStore, NodeType, RelationType
import graphiti  # Hypothèse : package Python Graphiti

class GraphitiMemorystore(MemoryStore):
    """
    Implémentation Graphiti de l'interface MemoryStore.

    Features:
        - Temporal reasoning avancé
        - Cross-document inference
        - Memory consolidation automatique
    """

    def __init__(self, graphiti_client):
        self.client = graphiti_client

    async def create_node(
        self,
        node_type: str,
        name: str,
        metadata: dict,
        embedding: list[float] | None = None,
        source: str | None = None,
    ) -> str:
        """Créer nœud via Graphiti API."""
        # Mapper vers format Graphiti
        node = await self.client.create_entity(
            entity_type=node_type,
            name=name,
            properties=metadata,
            embedding=embedding,
        )
        return node.id

    async def semantic_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        score_threshold: float = 0.7,
        source_type: str | None = None,
    ) -> list[dict]:
        """Recherche via Graphiti vector search."""
        results = await self.client.search_similar(
            query_vector=query_embedding,
            top_k=limit,
            threshold=score_threshold,
            filters={"type": source_type} if source_type else None,
        )

        return [
            {
                "node_id": r.entity_id,
                "score": r.similarity_score,
                "metadata": r.properties,
            }
            for r in results
        ]

    # Implémenter toutes les autres méthodes abstraites...
```

#### Step 2 : Ajouter case factory

**Fichier** : `agents/src/adapters/memorystore.py`

```python
async def get_memorystore_adapter(
    pool: asyncpg.Pool | None = None,
    provider: str | None = None,
) -> MemoryStore:
    """Factory pour créer adaptateur memorystore."""
    provider = provider or os.getenv("MEMORYSTORE_PROVIDER", "postgresql")

    if provider == "postgresql":
        # Existant...
        return PostgreSQLMemorystore(pool)

    elif provider == "graphiti":
        # Nouveau !
        from agents.src.adapters.graphiti_memorystore import GraphitiMemorystore
        import graphiti

        graphiti_url = os.getenv("GRAPHITI_URL")
        if not graphiti_url:
            raise ValueError("GRAPHITI_URL manquante")

        client = graphiti.Client(url=graphiti_url)

        logger.info(
            "memorystore_factory_created",
            provider="graphiti",
            backend="Graphiti temporal memory",
        )

        return GraphitiMemorystore(client)

    # Autres providers...
```

#### Step 3 : Migration données PostgreSQL → Graphiti

**Fichier** : `scripts/migrate_postgresql_to_graphiti.py`

```python
#!/usr/bin/env python3
"""
Migre données PostgreSQL → Graphiti.

Étapes :
1. Export PostgreSQL (knowledge.nodes + knowledge.edges)
2. Transform vers format Graphiti
3. Import dans Graphiti
4. Validation (count nodes, edges, sample queries)
"""

import asyncpg
import graphiti

async def export_postgresql(db_pool):
    """Export tous les nœuds et edges depuis PostgreSQL."""
    nodes = await db_pool.fetch("SELECT * FROM knowledge.nodes")
    edges = await db_pool.fetch("SELECT * FROM knowledge.edges")

    return {
        "nodes": [dict(n) for n in nodes],
        "edges": [dict(e) for e in edges],
    }

async def import_graphiti(data, graphiti_client):
    """Import nœuds et edges dans Graphiti."""
    # Créer tous les nœuds
    node_mapping = {}  # PostgreSQL UUID → Graphiti ID

    for node in data["nodes"]:
        graphiti_node = await graphiti_client.create_entity(
            entity_type=node["type"],
            name=node["name"],
            properties=node["metadata"],
        )
        node_mapping[node["id"]] = graphiti_node.id

    # Créer toutes les relations
    for edge in data["edges"]:
        await graphiti_client.create_relation(
            from_entity_id=node_mapping[edge["from_node_id"]],
            to_entity_id=node_mapping[edge["to_node_id"]],
            relation_type=edge["relation_type"],
            properties=edge["metadata"],
        )
```

#### Step 4 : Tests compatibilité

**Fichier** : `tests/integration/test_graphiti_compatibility.py`

```python
import pytest
from agents.src.adapters.memorystore import get_memorystore_adapter

@pytest.mark.integration
@pytest.mark.asyncio
async def test_graphiti_implements_all_methods():
    """Graphiti doit implémenter toutes les méthodes interface."""
    adapter = await get_memorystore_adapter(provider="graphiti")

    # Vérifier que toutes les méthodes sont disponibles
    required_methods = [
        "create_node", "get_or_create_node", "create_edge",
        "semantic_search", "query_path", "query_temporal",
    ]

    for method in required_methods:
        assert hasattr(adapter, method)
        assert callable(getattr(adapter, method))

@pytest.mark.integration
@pytest.mark.asyncio
async def test_graphiti_feature_parity():
    """Graphiti doit avoir feature parity avec PostgreSQL."""
    # Créer node via Graphiti
    adapter = await get_memorystore_adapter(provider="graphiti")

    node_id = await adapter.create_node(
        "person",
        "Antonio Lopez",
        {"email": "antonio@example.com"},
    )

    # Vérifier création
    node = await adapter.get_node_by_id(node_id)
    assert node is not None
    assert node["name"] == "Antonio Lopez"
```

#### Step 5 : Rollback PostgreSQL si problème

**Si Graphiti échoue** (performance dégradée, bugs, etc.) :

```bash
# Rollback instantané
MEMORYSTORE_PROVIDER=postgresql  # 1 ligne .env changée

# Restaurer données si corruption
./scripts/restore_postgresql_backup.sh backup-2026-02-11.sql.gz
```

---

## 4. Swap vers Neo4j

**Contexte** : Neo4j pour requêtes graphe complexes (Cypher, shortest path multi-hop, pattern matching).

**Déclencheurs** :
- Besoin requêtes Cypher avancées (MATCH patterns complexes)
- Recherche chemins multi-hop (>3 niveaux profondeur)
- Visualisation graphe interactive (Neo4j Browser)

### Étapes migration

#### Step 1 : Créer implémentation Neo4j

```python
from neo4j import AsyncGraphDatabase
from agents.src.adapters.memorystore_interface import MemoryStore

class Neo4jMemorystore(MemoryStore):
    """Implémentation Neo4j de l'interface MemoryStore."""

    def __init__(self, neo4j_driver):
        self.driver = neo4j_driver

    async def create_node(self, node_type, name, metadata, **kwargs) -> str:
        """Créer nœud Neo4j."""
        async with self.driver.session() as session:
            result = await session.run(
                f"CREATE (n:{node_type} {{name: $name, metadata: $metadata}}) RETURN id(n)",
                name=name,
                metadata=metadata,
            )
            return str(result.single()[0])

    async def query_path(self, from_node_id, to_node_id, max_depth=3):
        """Shortest path via Cypher."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH path = shortestPath((a)-[*..""" + str(max_depth) + """]->(b))
                WHERE id(a) = $from AND id(b) = $to
                RETURN path
                """,
                from_=int(from_node_id),
                to=int(to_node_id),
            )
            # Parser path...
```

#### Step 2 : Migration données

```bash
# Export PostgreSQL → Neo4j CSV
./scripts/export_postgresql_to_csv.sh

# Import via neo4j-admin
neo4j-admin database import full \
  --nodes=nodes.csv \
  --relationships=edges.csv \
  friday-knowledge-graph
```

---

## 5. Swap vers Qdrant

**Contexte** : Qdrant vectorstore séparé si >300k vecteurs ou latence pgvector >100ms.

**Decision D19** : pgvector Day 1, Qdrant si pain réel.

### Quand swapper ?

| Critère | Seuil | Action |
|---------|-------|--------|
| **Nombre vecteurs** | >300k | Benchmark latence pgvector vs Qdrant |
| **Latence recherche** | >100ms p95 | Évaluer index HNSW Qdrant |
| **Filtres complexes** | Impossibles pgvector | Qdrant payload filters |

### Étapes migration

#### Step 1 : Créer implémentation Qdrant

```python
from qdrant_client import AsyncQdrantClient
from agents.src.adapters.memorystore_interface import MemoryStore

class QdrantMemorystore(MemoryStore):
    """
    Implémentation Qdrant UNIQUEMENT pour vectorstore.

    Note : Nœuds et edges restent dans PostgreSQL.
           Seuls les embeddings passent dans Qdrant.
    """

    def __init__(self, db_pool, qdrant_client):
        self.db_pool = db_pool  # PostgreSQL pour nœuds/edges
        self.qdrant = qdrant_client  # Qdrant pour embeddings

    async def semantic_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        score_threshold: float = 0.7,
        source_type: str | None = None,
    ) -> list[dict]:
        """Recherche via Qdrant."""
        results = await self.qdrant.search(
            collection_name="friday_embeddings",
            query_vector=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
            query_filter={"source_type": source_type} if source_type else None,
        )

        return [
            {
                "node_id": r.payload["node_id"],
                "score": r.score,
                "metadata": r.payload,
            }
            for r in results
        ]
```

---

## 6. Checklist compatibilité provider

Avant de déclarer un nouveau provider "production-ready", vérifier :

### Fonctionnalités requises

- [ ] **Node Operations**
  - [ ] `create_node()` : Créer nœud avec metadata
  - [ ] `get_or_create_node()` : Déduplication (person/email/source_id)
  - [ ] `get_node_by_id()` : Récupération par UUID
  - [ ] `get_nodes_by_type()` : Filtrage par type

- [ ] **Edge Operations**
  - [ ] `create_edge()` : Créer relation avec metadata
  - [ ] `get_edges_by_type()` : Filtrage par relation_type
  - [ ] `get_related_nodes()` : Direction out/in/both

- [ ] **Graph Queries**
  - [ ] `query_path()` : Shortest path BFS (max_depth=3)
  - [ ] `query_temporal()` : Filtrage dates
  - [ ] `get_node_with_relations()` : Récupération avec edges

- [ ] **Semantic Search**
  - [ ] `semantic_search()` : Cosine similarity, score_threshold, filters

### Performance

- [ ] Latence `create_node()` : <50ms p95
- [ ] Latence `semantic_search()` : <100ms p95
- [ ] Throughput : >=100 ops/sec

### Tests

- [ ] 19 tests unitaires memorystore PASS
- [ ] 11 tests interface PASS
- [ ] Tests intégration spécifiques provider PASS
- [ ] Tests E2E pipeline Email→Graph PASS

### Documentation

- [ ] Guide installation provider
- [ ] Guide migration données (export/import)
- [ ] Guide rollback (si échec)
- [ ] Checklist troubleshooting

### Production readiness

- [ ] Backup/restore testé
- [ ] Monitoring latence/erreurs
- [ ] Alertes Telegram si provider down
- [ ] Runbook opérations (restart, upgrade, rollback)

---

## Conclusion

**Pattern abstraction = évolutivité sans refactoring massif.**

- **Day 1** : PostgreSQL + pgvector (Decision D19) ✅
- **Futur** : Graphiti (si mature ~août 2026), Neo4j (si graphe complexe), Qdrant (si >300k vecteurs)
- **Swap** : 1 variable env changée, zéro refactoring code métier

**Philosophie** : Start Simple, Split When Pain.
