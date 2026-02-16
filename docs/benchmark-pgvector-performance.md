# Friday 2.0 - Benchmark Performance pgvector

**Story**: 3.3 - Task 10.4
**Date**: 2026-02-16
**pgvector**: 0.8.0
**Index**: HNSW

---

## Configuration

### Materiel (VPS-4 OVH)

| Composant | Specification |
|-----------|--------------|
| CPU | 12 vCores |
| RAM | 48 Go |
| SSD | 300 Go NVMe |
| OS | Ubuntu 22.04 |
| PostgreSQL | 16 |
| pgvector | 0.8.0 |

### Parametres HNSW

```sql
-- Index creation
CREATE INDEX idx_embeddings_hnsw ON knowledge.embeddings
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Runtime
SET maintenance_work_mem = '2GB';  -- Build HNSW rapide
SET hnsw.ef_search = 40;           -- Default (trade-off recall/speed)
```

| Parametre | Valeur | Impact |
|-----------|--------|--------|
| `m` | 16 | Connexions par noeud. Plus = meilleur recall, plus lent build |
| `ef_construction` | 64 | Qualite build. Plus = meilleur recall, build plus lent |
| `ef_search` | 40 | Qualite search runtime. Plus = meilleur recall, query plus lent |
| `maintenance_work_mem` | 2 GB | Memoire pour build index. 48 Go RAM permet 2 GB confortablement |

### Embeddings

| Parametre | Valeur |
|-----------|--------|
| Modele | Voyage AI voyage-4-large |
| Dimensions | 1024 |
| Distance | Cosinus (`<=>` operator) |
| Score | `1 - (distance / 2)` normalise [0, 1] |

---

## Benchmarks Theoriques (pgvector 0.8.0 documentation)

| Documents | Query Latency (top-5) | Index Size | Build Time |
|-----------|-----------------------|------------|------------|
| 1k | ~1-2 ms | ~4 MB | ~5s |
| 10k | ~2-5 ms | ~40 MB | ~50s |
| 100k | ~10-20 ms | ~400 MB | ~10min |
| 1M | ~50-100 ms | ~4 GB | ~2h |

**Recall** (HNSW m=16, ef_construction=64, ef_search=40) :
- 1k docs : ~99%
- 10k docs : ~98%
- 100k docs : ~95-97%

---

## Benchmarks Cibles (AC6 Story 3.3)

| Metrique | Cible | Marge |
|----------|-------|-------|
| Latence query top-5 | < 2s | Large (pgvector < 20ms pour 100k) |
| Latence embedding generation | < 1s | Depend API Voyage AI (~200-400ms) |
| Latence E2E (query -> resultats) | < 3s | Inclut anonymisation + embedding + pgvector + formatting |

**Decomposition latence E2E estimee** :

```
Presidio anonymisation :    ~50-100 ms
Voyage AI embedding :       ~200-400 ms
pgvector HNSW query :       ~10-20 ms (100k docs)
DB jointure metadata :      ~1-5 ms
Formatting resultats :      ~1-5 ms
---
Total estime :              ~262-530 ms
```

**Budget latence restant** : ~2.5s de marge sur 3s AC1.

---

## Impact Filtres (hnsw.iterative_scan)

pgvector 0.8.0 introduit `hnsw.iterative_scan` pour eviter l'overfiltering :

```sql
SET LOCAL hnsw.iterative_scan = on;

SELECT ... FROM knowledge.embeddings e
INNER JOIN ingestion.document_metadata dm ON e.document_id = dm.document_id
WHERE dm.classification_category = 'finance'
ORDER BY e.embedding <=> $1
LIMIT 5;
```

| Scenario | Sans iterative_scan | Avec iterative_scan |
|----------|--------------------|--------------------|
| 100k docs, filtre 10% match | Possible 0 resultats (overfiltering) | Scan iteratif, toujours top-5 |
| 100k docs, filtre 90% match | OK | OK (meme performance) |
| Latence avec filtre | ~10-20 ms | ~15-30 ms (+50% worst case) |

**Recommendation** : Toujours activer `iterative_scan` quand des filtres WHERE sont presents.

---

## Dimensionnement Stockage

| Documents | Taille embeddings | Taille index HNSW | Total |
|-----------|-------------------|-------------------|-------|
| 1k | ~4 MB | ~4 MB | ~8 MB |
| 10k | ~40 MB | ~40 MB | ~80 MB |
| 100k | ~400 MB | ~400 MB | ~800 MB |

**VPS-4 SSD 300 Go** : Largement suffisant pour 100k documents (< 1 Go).

**Seuil reevaluation Qdrant** (D19) : > 300k vecteurs OU latence mediane > 100ms.

---

## Script Benchmark (a executer sur VPS)

```sql
-- 1. Compter documents indexes
SELECT COUNT(*) FROM knowledge.embeddings;

-- 2. Taille index
SELECT pg_size_pretty(pg_relation_size('knowledge.idx_embeddings_hnsw'));

-- 3. Latence query (run 10x, prendre mediane)
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT
    e.document_id,
    1 - (e.embedding <=> '[0.1,0.1,...,0.1]'::vector) / 2 AS score
FROM knowledge.embeddings e
ORDER BY e.embedding <=> '[0.1,0.1,...,0.1]'::vector
LIMIT 5;

-- 4. Latence avec filtre + jointure
SET LOCAL hnsw.iterative_scan = on;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT
    e.document_id,
    dm.original_filename,
    1 - (e.embedding <=> '[0.1,0.1,...,0.1]'::vector) / 2 AS score
FROM knowledge.embeddings e
INNER JOIN ingestion.document_metadata dm ON e.document_id = dm.document_id
WHERE dm.classification_category = 'finance'
ORDER BY e.embedding <=> '[0.1,0.1,...,0.1]'::vector
LIMIT 5;
```

---

## Monitoring Continu

### SearchMetrics (agents/src/tools/search_metrics.py)

```python
search_metrics.record_query(
    query_duration_ms=150.0,
    results_count=5,
    top_score=0.92,
)

stats = search_metrics.get_stats()
# {
#     "total_queries": 100,
#     "median_latency_ms": 145.0,
#     "p95_latency_ms": 320.0,
#     "p99_latency_ms": 450.0,
#     "min_latency_ms": 80.0,
#     "max_latency_ms": 520.0,
# }
```

### Alertes

| Seuil | Action |
|-------|--------|
| Mediane > 2500 ms | Alerte Telegram System |
| p99 > 5000 ms | Log warning, investigation |
| Index rebuild > 30 min | Log warning |

### Commande Telegram

```
/stats search
```

Affiche : queries/jour, latence p50/p95/p99, top queries recentes.
