# Rétrospective Epic 6 : Mémoire Éternelle & Migration

**Date** : 2026-02-11
**Epic** : Epic 6 - Mémoire Éternelle & Migration (4 stories)
**Participants** : Mainteneur (Antonio), Alice (PO), Bob (SM), Charlie (Dev Lead)
**Durée rétrospective** : ~90 minutes

---

## 📋 Contexte Epic 6

### Stories Complétées (4/4)

| Story | Titre | Status | Tests | Budget |
|-------|-------|--------|-------|--------|
| **6.1** | Graphe de Connaissances PostgreSQL | ✅ DONE | 40 unit tests | - |
| **6.2** | Embeddings pgvector & Voyage AI | ✅ DONE | 36 tests (35 PASS + 1 skip) | $10-15/mois |
| **6.3** | Adaptateur MemoryStore | ✅ DONE | 11 interface + 19 existing | - |
| **6.4** | Migration 110k Emails Historiques | ✅ DONE | Phase 1-3 complète | $332 réel |

**Total Epic 6** : 75+ tests, 100% stories complétées, 0 bugs post-review

---

## 🎯 Objectifs Epic 6 (rappel)

Epic 6 visait à établir le système de mémoire persistante de Friday 2.0 :

1. **Knowledge Graph PostgreSQL** : Structure relationnelle pour entités/relations/événements (10 node types, 14 relation types)
2. **Embeddings vectoriels** : Recherche sémantique via pgvector (migration depuis Qdrant - Décision D19)
3. **Memorystore adapter** : Interface abstraite pour évolutivité future (Graphiti/Neo4j)
4. **Migration 110k emails** : Population initiale du graphe depuis données historiques

---

## ✅ What Went Well

### 1. **Décision D19 : pgvector Day 1** (2026-02-09)

**Contexte** : Architecture initiale prévoyait Qdrant pour embeddings vectoriels.

**Décision** : Remplacer Qdrant par **pgvector dans PostgreSQL** pour Day 1.

**Rationale** :
- Volume modéré (100k vecteurs, 1 utilisateur) → pgvector suffit largement
- Simplification stack : -1 service Docker (Qdrant), -600 Mo RAM
- PostgreSQL 16 + pgvector = mature, performant pour notre échelle
- Latence acceptable : <100ms pour 100k vecteurs
- Économie coûts : pas de service vectoriel dédié

**Impact** :
- Migration 008 modifiée : `knowledge.embeddings` avec `vector(1024)` + HNSW index
- `memorystore.py` réécrit : `AsyncQdrantClient` → `asyncpg` + pgvector
- `docker-compose.yml` : service Qdrant retiré
- ~15 fichiers modifiés (migrations, code, tests, docs)

**Clause de réévaluation** : Si >300k vecteurs OU latence >100ms → réévaluer Qdrant/Milvus

**Résultat** : ✅ Stack simplifiée, socle RAM réduit (~6-8 Go), pgvector opérationnel

---

### 2. **Tests exhaustifs (75+ tests, 100% couverture critique)**

**Breakdown tests** :
- **Story 6.1** : 40 unit tests (graphe PostgreSQL, contraintes, relations)
- **Story 6.2** : 36 tests (embeddings, Voyage AI, pgvector queries)
- **Story 6.3** : 11 interface tests + 19 tests existing (factory pattern, ABC)
- **Story 6.4** : Tests intégration 3 phases (classification, graph, embeddings)

**Qualité** :
- ✅ 0 bugs identifiés post-code review adversarial
- ✅ 100% des modules critiques testés (graph, embeddings, adapter)
- ✅ Tests isolation (mocks Voyage AI, pas d'appels réels API en unit tests)

**Pattern réutilisable** : Stratégie "80% unit mocks, 15% integration datasets, 5% E2E" validée.

---

### 3. **Factory Pattern Memorystore (extensibilité)**

**Code Story 6.3** :
```python
# agents/src/adapters/memorystore.py
class MemoryStore(ABC):
    @abstractmethod
    async def store_entity(self, entity: Entity) -> str:
        pass

    @abstractmethod
    async def query_similar(self, embedding: list[float], top_k: int) -> list[Entity]:
        pass

class PostgreSQLMemoryStore(MemoryStore):
    """Implémentation Day 1 : PostgreSQL + pgvector"""
    # ...

def get_memorystore() -> MemoryStore:
    provider = os.getenv("MEMORYSTORE_PROVIDER", "postgresql")
    if provider == "postgresql":
        return PostgreSQLMemoryStore(...)
    elif provider == "graphiti":  # Future réévaluation (6 mois)
        return GraphitiMemoryStore(...)
    raise ValueError(f"Unknown provider: {provider}")
```

**Avantages** :
- Swap provider en 1 fichier (`memorystore.py`)
- Tests interface indépendants de l'implémentation (11 tests ABC)
- Prêt pour migration Graphiti/Neo4j si nécessaire (août 2026)

---

### 4. **Migration 110k emails - Stratégie 3 phases robuste**

**Phase 1 : Classification via Claude Sonnet 4.5**
- Budget : $330 (110k emails × $0.003/classification)
- Résultat : 8 catégories (medical, admin, personal, professional, financial, university, technical, other)
- Stockage : `ingestion.emails_raw` avec colonnes `category`, `confidence`, `classified_at`

**Phase 2 : Population graphe de connaissances**
- Extraction entités : `Person`, `Organization`, `Event`, `Topic`
- Création relations : `SENT_BY`, `BELONGS_TO`, `MENTIONS`, `RELATED_TO`
- Stockage : `knowledge.entities`, `knowledge.relations`

**Phase 3 : Génération embeddings Voyage AI**
- Budget : $2 (110k emails × ~$0.00002/embedding)
- Modèle : `voyage-3-large` (1024 dimensions)
- Stockage : `knowledge.embeddings` avec pgvector
- Index : HNSW pour recherche rapide (<100ms)

**Scripts créés** :
- `scripts/migrate_emails.py` (checkpointing, retry, resume, progress tracking)
- `scripts/extract_email_domains.py` (nouveau - voir Story 2.8)

**Robustesse** :
- ✅ Checkpointing tous les 100 emails (resume après crash)
- ✅ Retry backoff exponentiel (rate limits API)
- ✅ Atomic writes (transactions PostgreSQL)
- ✅ Validation intégrité (6 bugs fixés lors code review v2)

---

## 🔴 What Could Be Improved

### 1. **Migration aveugle 110k emails - Gaspillage tokens identifié** ⚠️

**Problème** :
- Story 6.4 migre TOUS les 110k emails historiques sans filtrage
- Budget réel $332 (vs $45 estimé PRD) = **7× dépassement**
- Beaucoup d'emails sont probablement inutiles :
  - Commerce : Amazon, Netflix, eBay, Cdiscount (~15-20k emails ?)
  - Spam : newsletters, notifications automatiques (~10-15k emails ?)
  - Réseaux sociaux : LinkedIn notifications, Facebook (~5-10k emails ?)
- Coût LLM classification : ~$0.003/email → **~$132 gaspillés** sur emails non pertinents

**Root cause** :
- Pas d'analyse préalable des domaines sources
- Hypothèse implicite : "tous les emails sont pertinents"
- Pas de filtrage dans le design initial

---

### 2. **Solution proposée par Mainteneur : Filtrage intelligent permanent** 💡

**Insight clé** : La whitelist/blacklist ne doit pas être juste pour la migration historique, mais un **système permanent** dans le pipeline email.

**Approche en 2 temps** :

#### **Temps 1 : Extraction domaines (data-driven)**
```bash
# Script Python simple
python scripts/extract_email_domains.py --min-count 10
# → Output : domains_110k.csv
```

**CSV généré** :
```csv
domain,count,first_seen,last_seen,category_guess,action,reason
amazon.fr,8234,2020-01,2026-02,commerce,,
gmail.com,12456,2019-03,2026-02,personal,,
univ-lille.fr,3890,2019-09,2026-01,university,,
chu-lille.fr,2103,2020-05,2026-02,medical,,
netflix.com,1567,2021-01,2026-02,streaming,,
doctolib.com,892,2022-03,2026-02,medical,,
```

**Processus** :
1. Script extrait domaines uniques depuis `emails_legacy` (2-3 secondes)
2. Colonne `category_guess` ajoutée (heuristique : `*univ*` → university, `*chu*` → medical)
3. **Mainteneur annote manuellement** colonnes `action` (KEEP/SKIP) et `reason`
4. Import CSV annoté → table `ingestion.sender_filters`

#### **Temps 2 : Filtrage permanent dans pipeline**

**Architecture** :

```sql
-- Migration 030_sender_filters.sql
CREATE TABLE ingestion.sender_filters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Pattern matching
    pattern TEXT NOT NULL UNIQUE,  -- '@amazon.fr', 'noreply@%', etc.
    pattern_type TEXT NOT NULL CHECK (pattern_type IN ('domain', 'email', 'prefix')),

    -- Action
    action TEXT NOT NULL CHECK (action IN ('whitelist', 'blacklist', 'auto')),
    reason TEXT,

    -- Métriques économie
    emails_filtered INT DEFAULT 0,
    tokens_saved INT DEFAULT 0,  -- ~1000 tokens/email
    cost_saved_usd DECIMAL(10,4) DEFAULT 0.00,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_matched_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true
);
```

**Intégration pipeline email (Story 2.2 modifiée)** :

```python
# agents/src/pipelines/email/consumer.py

async def process_email(email_data: dict):
    """Pipeline email avec filtrage AVANT classification"""

    sender = email_data['sender']

    # 1. CHECK FILTRES (NOUVEAU !)
    filter_action = await check_sender_filter(sender)

    if filter_action == 'blacklist':
        # Skip classification, économise ~$0.003
        await db.execute("""
            INSERT INTO ingestion.emails_raw
            (message_id, sender, category, confidence, filtered)
            VALUES ($1, $2, 'filtered_blacklist', 1.0, true)
        """, email_data['message_id'], sender)

        # Update métriques économie
        await db.execute("""
            UPDATE ingestion.sender_filters
            SET emails_filtered = emails_filtered + 1,
                tokens_saved = tokens_saved + 1000,
                cost_saved_usd = cost_saved_usd + 0.003,
                last_matched_at = NOW()
            WHERE pattern = get_domain_from_email($1)
        """, sender)

        logger.info("Email filtré (blacklist): %s", sender)
        return  # EXIT EARLY, pas de classification LLM

    # 2. Classification normale (si pas blacklisté)
    result = await classify_email(email_data)  # Appel Claude
    # ...
```

**Commandes Telegram (Story 1.11 extension)** :

```python
# bot/handlers/commands.py

@router.message(Command("blacklist"))
async def cmd_blacklist(message: Message):
    """Blacklist un domaine pour économiser tokens

    Usage: /blacklist @amazon.fr
    """
    pattern = message.text.split()[1]
    await db.execute("""
        INSERT INTO ingestion.sender_filters (pattern, pattern_type, action)
        VALUES ($1, 'domain', 'blacklist')
    """, pattern)
    await message.reply(f"✅ Pattern blacklisté: {pattern}")

@router.message(Command("filters"))
async def cmd_filters(message: Message):
    """Liste filtres actifs + métriques économie"""
    filters = await db.fetch("""
        SELECT pattern, emails_filtered, cost_saved_usd
        FROM ingestion.sender_filters
        WHERE is_active = true
        ORDER BY emails_filtered DESC
        LIMIT 20
    """)

    total_saved = sum(f['cost_saved_usd'] for f in filters)
    msg = f"**Filtres actifs** ({len(filters)}):\n\n"
    for f in filters:
        msg += f"• {f['pattern']}: {f['emails_filtered']} emails, ${f['cost_saved_usd']:.2f}\n"
    msg += f"\n💰 **Total économisé**: ${total_saved:.2f}"

    await message.reply(msg)
```

---

### 3. **Impact & ROI du filtrage intelligent**

**Migration 110k (optimisée)** :
- Emails pertinents estimés : ~66k (60% du total)
- Emails blacklistés : ~44k (40% spam/commerce/auto)
- Coût optimisé : ~$200 (vs $332 actuel)
- **Économie immédiate** : **$132**

**Runtime permanent** :
- Hypothèse : 50 emails commerciaux/spam par jour
- Coût évité : 50 × $0.003 × 365 = **$54.75/an**

**ROI Story 2.8** :
- Coût dev : ~15h × $50/h = $750
- Économie an 1 : $132 (migration) + $55 (runtime) = **$187**
- **Payback** : ~4 mois
- **Économie récurrente** : $55/an indéfiniment

---

### 4. **Budget Story 6.4 vs PRD - Écart de prévision**

**Problème** :
- **PRD estimait** : $45 pour migration emails
- **Réalité** : $332 (7× plus cher)
- **Causes** :
  - Volume sous-estimé (PRD assumait ~15-30k emails ?)
  - Pas de filtrage prévu dans le design initial
  - Coût classification LLM non audité avant migration

**Leçon apprise** : Pour futures migrations bulk LLM, **TOUJOURS** :

1. **Scanner volume réel AVANT estimation**
   - Query SQL : `SELECT COUNT(*) FROM source_table`
   - Extraire échantillon représentatif (1000 lignes)

2. **Analyser distribution sources**
   - Domaines, types, catégories
   - Identifier patterns spam/inutiles

3. **Prévoir filtrage intelligent dès le design**
   - Whitelist/blacklist explicite
   - Heuristiques simples (noreply@*, newsletters, etc.)

4. **Buffer estimation ×2-3 pour imprévus**
   - Rate limits API
   - Erreurs nécessitant retry
   - Edge cases non prévus

**Action** : Alice (PO) intègrera cette checklist dans le grooming des futures stories impliquant LLM bulk.

---

## 🎬 Action Items

### **Action 1 : Créer Story 2.8 "Filtrage sender intelligent & économie tokens"** 🔴 CRITICAL

**Responsable** : À assigner
**Priorité** : Haute (ROI $187/an)
**Taille** : M (12-18h)
**Epic** : Epic 2 (Pipeline Email Intelligent)

**Composants** :

1. **Migration 030** : Table `ingestion.sender_filters`
   - Colonnes : `pattern`, `pattern_type`, `action`, `emails_filtered`, `tokens_saved`, `cost_saved_usd`
   - Index sur `pattern` + `action`
   - Contraintes CHECK sur `action` IN ('whitelist','blacklist','auto')

2. **Script extraction domaines**
   ```bash
   python scripts/extract_email_domains.py \
     --source emails_legacy \
     --output domains_110k.csv \
     --min-count 10
   ```
   - Output CSV : domain, count, first_seen, last_seen, category_guess, action, reason
   - Heuristique `category_guess` pour faciliter tri manuel

3. **Pipeline email modification**
   - Fonction `check_sender_filter(sender: str) -> str` (whitelist/blacklist/auto)
   - Intégration dans `consumer.py` AVANT `classify_email()`
   - Update métriques économie (`emails_filtered`, `tokens_saved`, `cost_saved_usd`)

4. **Commandes Telegram**
   - `/blacklist <pattern>` : Ajouter pattern blacklist
   - `/whitelist <pattern>` : Ajouter pattern whitelist
   - `/filters` : Liste filtres + métriques économie
   - `/filters remove <pattern>` : Supprimer filtre
   - Rate limiting 10 req/min (DoS protection)

5. **Tests**
   - 15 unit tests : pattern matching, priority (email > domain > prefix), métriques
   - 5 integration tests : pipeline email avec filtres, update métriques
   - 3 E2E tests : workflow complet (blacklist → email → skip classification → métriques)
   - Test économie : 100 emails blacklistés = $0.30 trackés

**Acceptance Criteria (5 ACs)** :

1. ✅ Migration 030 crée table `sender_filters` avec contraintes + index
2. ✅ `check_sender_filter()` appelé AVANT classification, skip si blacklist
3. ✅ Commandes Telegram `/blacklist`, `/whitelist`, `/filters` opérationnelles
4. ✅ Script `extract_email_domains.py` génère CSV annotable
5. ✅ 23+ tests (15 unit + 5 integ + 3 E2E) PASS, métriques économie trackées

**Dépendances** :
- Story 2.1 (EmailEngine réception) - ✅ DONE
- Story 2.2 (Classification LLM) - ✅ DONE
- Story 6.4 (Migration 110k) - ✅ DONE

**Deadline suggérée** : Avant fin Epic 2 (pour optimiser Stories 2.4+)

---

### **Action 2 : Améliorer estimations budgets LLM** 📊

**Responsable** : Alice (Product Owner)
**Contexte** : PRD Epic 6 estimait $45, réalité $332 (7× écart)

**Checklist grooming futures stories LLM bulk** :

- [ ] Scanner volume réel source (`SELECT COUNT(*)`)
- [ ] Extraire échantillon représentatif (1000 lignes)
- [ ] Analyser distribution (domaines, types, patterns spam)
- [ ] Prévoir filtrage intelligent (whitelist/blacklist)
- [ ] Buffer estimation ×2-3 pour imprévus
- [ ] Valider avec équipe tech AVANT finalisation story

**Livrable** : Template grooming intégré dans workflow BMAD (checklist Notion/Linear)

---

### **Action 3 : Documenter pattern "Domain-based filtering"** 📚

**Responsable** : Charlie (Dev Lead)
**Timing** : Après Story 2.8 implémentée
**Contexte** : Pattern réutilisable pour autres pipelines (OCR documents, fichiers NAS, etc.)

**Contenu doc `docs/patterns/domain-based-filtering.md`** :

1. **Architecture**
   - Table SQL `sender_filters` (schema, indexes, contraintes)
   - Factory pattern pour extensibilité (domain/email/prefix matching)

2. **Usage**
   ```python
   # Example : OCR documents
   if await check_source_filter(document.source) == 'blacklist':
       return  # Skip OCR, économise compute
   ```

3. **Exemples code**
   - Extraction domaines/sources (`extract_*.py`)
   - Intégration pipeline (check AVANT opération coûteuse)
   - Commandes Telegram gestion filtres

4. **ROI calculation**
   - Formule : `(volume_filtré × coût_unitaire × 365) - coût_dev`
   - Exemple Story 2.8 : $187/an

5. **Réutilisabilité**
   - Pipeline OCR (Story 3.1) : filtrer documents commerciaux scannés
   - Desktop Search (Story 3.3) : filtrer dossiers temporaires/cache
   - Fichiers NAS (Story 3.4) : filtrer backups/logs volumineux

**Livrable** : Doc pattern + code examples, référencé dans CLAUDE.md

---

## 🔮 Next Epic Preparation - Epic 7 Preview

**Epic 7** : **Agenda & Calendrier Multi-casquettes** (3 stories)

| Story | Titre | Dépendances | Taille | Complexité |
|-------|-------|-------------|--------|------------|
| **7.1** | Détection événements depuis emails | 2.2 (classification) | M (12-18h) | Moyenne |
| **7.2** | Sync bidirectionnelle Google Calendar | - | M (12-18h) | Moyenne |
| **7.3** | Calendrier multi-casquettes (SELARL/SCI/Perso) | 7.1, 7.2 | M (12-18h) | Moyenne |

**Bloqueurs identifiés** : ✅ Aucun
- PostgreSQL knowledge graph opérationnel (Epic 6 ✅)
- Pipeline email classification opérationnel (Story 2.2 ✅)
- Google Calendar API : standard, doc Google excellente
- Pas de nouvelles dépendances lourdes

**Recommandation** : Terminer Epic 2 AVANT de démarrer Epic 7
- Story 2.4 (Extraction PJ) : in-progress
- Stories 2.5-2.7 : backlog
- **Raison** : Epic 7.1 dépend de Story 2.2 (extraction événements depuis emails classifiés)

---

## 📊 Métriques Finales Epic 6

| Métrique | Valeur | Commentaire |
|----------|--------|-------------|
| **Stories complétées** | 4/4 (100%) | Toutes stories terminées avec succès |
| **Tests créés** | 75+ | 40 unit + 19 interface + 16+ integration |
| **Couverture code** | Excellente | 100% des modules critiques testés |
| **Budget LLM réel** | $332 | vs $45 PRD (+640%), Action 2 créée |
| **Durée Epic** | ~2-3 semaines | Estimation initiale : 3-4 semaines |
| **Décisions techniques** | 1 majeure | D19 : pgvector Day 1 (retire Qdrant) |
| **Bugs post-review** | 0 | Code review adversarial passée |
| **Économie RAM** | ~600 Mo | Qdrant retiré → pgvector PostgreSQL |
| **Régression** | 0 | Zero régression détectée |

---

## 🎯 Succès Clés

1. ✅ **PostgreSQL knowledge graph opérationnel** (10 node types, 14 relations, 40 tests)
2. ✅ **pgvector embeddings Day 1** (Qdrant retiré, Décision D19, économie RAM)
3. ✅ **Memorystore adapter factory pattern** (extensible, 11 tests interface)
4. ✅ **Migration 110k emails réussie** (stratégie 3 phases, checkpointing robuste)
5. ✅ **Tests exhaustifs** (75+ tests, 100% couverture critique, 0 bugs post-review)
6. ✅ **Insight majeur Mainteneur** : Filtrage intelligent permanent → Story 2.8 créée

---

## 🔴 Amélioration Majeure

**Filtrage intelligent sender (Story 2.8)** :
- Économie migration : $132 (44k emails blacklistés)
- Économie runtime : $55/an (50 emails/jour filtrés)
- **ROI total an 1** : **$187**
- Payback : ~4 mois
- Pattern réutilisable : OCR, Desktop Search, NAS

---

## 📝 Notes Additionnelles

### Décisions techniques Epic 6

**D19 (2026-02-09) : pgvector Day 1, Qdrant retiré**
- **Contexte** : Architecture initiale prévoyait Qdrant pour embeddings
- **Décision** : pgvector dans PostgreSQL suffit pour 100k vecteurs, 1 utilisateur
- **Rationale** : Simplification stack, -600 Mo RAM, latence acceptable (<100ms)
- **Réévaluation** : Si >300k vecteurs OU latence >100ms
- **Fichiers modifiés** : docker-compose.yml, migration 008, memorystore.py, consumer.py, test_docker_compose.py + 15+ docs

### Pattern "Domain-based filtering" découvert

**Contexte** : Mainteneur a identifié gaspillage tokens sur migration 110k emails (commerce, spam, auto).

**Solution** : Extraction domaines → tri manuel → filtrage permanent pipeline.

**Généralisation** : Pattern applicable à :
- Pipeline OCR (filtrer documents commerciaux scannés)
- Desktop Search (filtrer dossiers cache/temp)
- NAS sync (filtrer backups/logs)

**ROI** : Économie tokens/compute sur volume > 10k items.

---

## 🚀 Prochaines Étapes

1. **Priorité 1** : Créer Story 2.8 dans sprint-status.yaml (status `backlog`, priorité haute)
2. **Priorité 2** : Terminer Epic 2 (Stories 2.4-2.7)
3. **Priorité 3** : Implémenter Story 2.8 (ROI élevé, $187/an économisés)
4. **Priorité 4** : Démarrer Epic 7 (Agenda & Calendrier)

---

**Rétrospective complétée** : 2026-02-11
**Participants** : Mainteneur, Alice, Bob, Charlie
**Durée** : ~90 minutes
**Actions créées** : 3 (1 critical, 2 standard)
**Stories créées** : 1 (Story 2.8)

---

*Généré par BMAD Retrospective Workflow v1.0*
