# Architecture Friday 2.0 - Addendum Technique

**Date** : 2026-02-05
**Version** : 1.0
**Complément à** : [architecture-friday-2.0.md](architecture-friday-2.0.md)

Ce document contient les clarifications techniques supplémentaires issues de l'analyse adversariale méta du 2026-02-05.

---

## 1. Presidio Pipeline - Performance & Benchmark

### 1.1 Problématique

Pipeline Presidio est **obligatoire** avant tout LLM cloud (RGPD), mais impact latence non évalué.

### 1.2 Benchmarks attendus

| Texte type | Taille | Entités PII | Latence Presidio | Latence LLM | Total |
|------------|--------|-------------|------------------|-------------|-------|
| Email court | 500 chars | 2-3 | ~200-300ms | ~800ms | ~1s |
| Email long | 2000 chars | 5-10 | ~500-800ms | ~1.2s | ~2s |
| Document | 5000 chars | 10-20 | ~1-1.5s | ~2s | ~3.5s |

**Sources** :
- Presidio benchmark officiel : ~400-600ms pour 1000 chars (CPU i7, 8 threads)
- VPS-4 OVH (12 vCores) : performance similaire attendue

### 1.3 Stratégies d'optimisation

Si latence Presidio >1s devient problématique :

1. **Cache anonymisation** : Textes identiques → réutiliser mapping (gain ~80%)
2. **Async pipeline** : Presidio en background pour actions non-urgentes
3. **Batch processing** : Grouper 10 emails → Presidio batch (gain ~30%)
4. **Downgrade détection** : Désactiver entités rares (IBAN, CRYPTO) si non critiques

### 1.4 Tests de performance

```python
# tests/performance/test_presidio_latency.py
@pytest.mark.performance
async def test_presidio_latency_email_500chars():
    text = generate_email_with_pii(length=500, pii_count=3)
    start = time.time()
    anonymized, tokens = await anonymize_text(text, "test")
    latency = time.time() - start

    assert latency < 0.5, f"Presidio trop lent: {latency}s (seuil: 0.5s)"
```

**Seuils acceptables** :
- Email court (500 chars) : <500ms
- Email long (2000 chars) : <1s
- Document (5000 chars) : <2s

---

## 2. Pattern Detection - Algorithme Feedback Loop

### 2.1 Problématique

L'architecture dit "Friday détecte les patterns récurrents automatiquement" mais **aucun algorithme spécifié**.

### 2.2 Algorithme de détection

**Étapes** :

1. **Collecte corrections** (via Trust Layer)
   - Antonio corrige une action → `core.action_receipts.correction` rempli
   - Exemple: Correction email #1 : "URSSAF → finance (était: professional)"
   - Exemple: Correction email #2 : "Cotisations URSSAF → finance (était: professional)"

2. **Clustering sémantique** (nightly cron)
   ```python
   # services/metrics/pattern_detector.py
   async def detect_correction_patterns():
       # Récupérer corrections de la semaine
       corrections = await db.fetch("""
           SELECT module, action_type, input_summary, correction, created_at
           FROM core.action_receipts
           WHERE correction IS NOT NULL
           AND created_at > NOW() - INTERVAL '7 days'
       """)

       # Grouper par module/action
       grouped = group_by(corrections, key=lambda x: (x['module'], x['action_type']))

       for (module, action), corr_list in grouped.items():
           # Calculer similarité entre corrections (embeddings)
           embeddings = await mistral_embed([c['correction'] for c in corr_list])
           similarity_matrix = cosine_similarity(embeddings)

           # Détecter clusters (seuil 0.85)
           clusters = find_clusters(similarity_matrix, threshold=0.85)

           for cluster in clusters:
               if len(cluster) >= 2:  # Pattern = 2+ corrections similaires
                   # Extraire pattern commun
                   pattern = extract_common_pattern(cluster)

                   # Proposer règle à Antonio via Telegram
                   await propose_rule_to_antonio(module, action, pattern, cluster)
   ```

3. **Proposition règle** (Telegram inline buttons)
   ```
   📋 PATTERN DÉTECTÉ (email.classify)

   2 corrections similaires :
   - "URSSAF → finance"
   - "Cotisations URSSAF → finance"

   Règle proposée :
   IF email contient "URSSAF" OR "cotisations"
   THEN category = "finance", priority = "high"

   [✅ Créer règle] [✏️ Modifier] [❌ Ignorer]
   ```

4. **Validation Antonio** → Insertion `core.correction_rules`

### 2.3 Extraction pattern commun

```python
def extract_common_pattern(corrections: list[dict]) -> dict:
    """
    Extrait le pattern commun de plusieurs corrections
    Méthode: Détection mots-clés récurrents + catégorie cible
    """
    # Mots-clés communs
    all_keywords = []
    for corr in corrections:
        keywords = extract_keywords(corr['input_summary'])
        all_keywords.extend(keywords)

    # Fréquence mots-clés
    keyword_freq = Counter(all_keywords)
    common_keywords = [kw for kw, freq in keyword_freq.items() if freq >= 2]

    # Catégorie/output cible (majorité)
    target_outputs = [parse_correction(c['correction']) for c in corrections]
    target_category = Counter([o['category'] for o in target_outputs]).most_common(1)[0][0]

    return {
        'conditions': {
            'keywords': common_keywords,
            'min_match': 1  # Au moins 1 keyword doit matcher
        },
        'output': {
            'category': target_category,
            'confidence_boost': 0.1  # Boost confiance si règle match
        }
    }
```

### 2.4 Faux positifs - Mitigation

**Risque** : 2 corrections différentes confondues par l'algo.

**Solution** :
- Seuil de similarité élevé (0.85 sur embeddings)
- Validation manuelle Antonio avant activation règle
- Option "Ignorer ce pattern" → Blacklist

---

## 3. Profils RAM - Sources & Benchmarks

### 3.1 Problématique

Estimations RAM (Ollama 8 Go, Whisper 4 Go) sans source citée → risque sous-estimation.

### 3.2 Sources par service

| Service | RAM estimée | Source | Notes |
|---------|-------------|--------|-------|
| **Ollama Nemo 12B** | ~8 Go | [Ollama Model Library](https://ollama.com/library/mistral-nemo) (quantized Q4) | ✅ Officiel |
| **Faster-Whisper** | ~4 Go | [Faster-Whisper GitHub](https://github.com/SYSTRAN/faster-whisper) (large-v3 model) | ✅ Officiel |
| **Kokoro TTS** | ~2 Go | Estimation basée sur modèles TTS similaires (Piper ~1.5 Go) | ⚠️ À valider Story 1 |
| **Surya OCR** | ~2 Go | [Surya GitHub](https://github.com/VikParuchuri/surya) (detection + recognition models) | ✅ Officiel |
| **Presidio + spaCy-fr** | ~1.5 Go | spaCy fr_core_news_lg (~500 Mo) + Presidio overhead (~1 Go) | ✅ Benchmark interne |
| **PostgreSQL 16** | ~1-1.5 Go | Config `shared_buffers=512MB` + working memory | ✅ Configuration |
| **Redis 7** | ~200 Mo | Base install + AOF overhead | ✅ Benchmark |
| **Qdrant** | ~1-2 Go | Dépend du nb vecteurs (10k docs = ~500 Mo, 100k = ~2 Go) | ⚠️ Variable |
| **n8n** | ~500 Mo | [n8n Docker docs](https://docs.n8n.io/hosting/installation/docker/) | ✅ Officiel |
| **FastAPI Gateway** | ~200 Mo | Python asyncio + uvicorn workers | ✅ Estimation standard |
| **Telegram Bot** | ~100 Mo | python-telegram-bot lib | ✅ Estimation standard |
| **Caddy** | ~50 Mo | Caddy 2 reverse proxy | ✅ Officiel |
| **Zep** | ~500 Mo | Estimation basée sur services Go similaires | ⚠️ À valider |

### 3.3 Marge d'erreur

**Estimations ✅ validées** (sources officielles) : ±10%
**Estimations ⚠️ à valider** (extrapolations) : ±30%

**Total RAM optimiste** : ~21 Go
**Total RAM pessimiste** : ~27 Go
**VPS-4 disponible** : 48 Go
**Marge sécurité** : ~21-27 Go (44-56% de réserve)

### 3.4 Validation lors Story 1

```bash
# scripts/monitor-ram.sh (ajout logging détaillé)
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}" \
  | tee logs/ram_usage_baseline.log

# Comparer avec estimations
python scripts/compare_ram_estimates.py \
  --baseline logs/ram_usage_baseline.log \
  --estimates config/profiles.py
```

**Action si écart >20%** : Mise à jour `config/profiles.py` + alerte dans documentation.

---

## 4. OpenClaw - Critères précis de réévaluation

### 4.1 Problématique

Architecture dit "réévaluation post-socle backend" mais critères vagues ("maturité suffisante").

### 4.2 Critères obligatoires (Go/No-Go)

| # | Critère | Seuil | Vérification |
|---|---------|-------|--------------|
| 1 | **Temps en production** | ≥6 mois version stable | GitHub releases + changelog |
| 2 | **CVE critiques** | 0 CVE CVSS >7.0 non patchées | CVE database + GitHub Security Advisories |
| 3 | **Audit sécurité externe** | Rapport public d'audit tiers | Blog officiel OpenClaw |
| 4 | **Sandboxing durci** | Validation filePath + jail filesystem | Code review manuel `src/sandbox/` |
| 5 | **Streaming Mistral stable** | Issue #5769 fermée + fix confirmé 2+ semaines | GitHub issues + tests utilisateurs |
| 6 | **Documentation complète** | API docs + exemples Mistral + Skills best practices | Docs officielles |

### 4.3 Critères souhaitables (Nice-to-have)

- Instances actives <10 000 (vs 42 665 actuellement) = adoption plus raisonnée
- Rate de fermeture issues <30 jours (vs 45+ actuellement)
- Skills vérifié ClawHub (certification qualité/sécurité)

### 4.4 Processus de réévaluation

**Trigger** : 6 mois après Story 1 (estimation août 2026)

**Étapes** :
1. Checklist critères Go/No-Go (Antonio + Claude)
2. Test POC OpenClaw sur VPS-test (pas prod)
3. Si OK → Proposal détaillée (coûts, bénéfices, migration)
4. Décision Antonio (Go/No-Go)

**Si Go** : Migration progressive (1 module test → 5 modules → all-in)
**Si No-Go** : Réévaluation dans 6 mois

---

## 5. Configuration n8n - Obtention variables d'environnement

### 5.1 Problématique

Workflows n8n mentionnent `${TELEGRAM_CHAT_ID}` mais aucun doc n'explique comment obtenir ces valeurs.

### 5.2 Guide complet obtention variables

#### **TELEGRAM_BOT_TOKEN**

**Étapes** :
1. Ouvrir Telegram → Rechercher [@BotFather](https://t.me/botfather)
2. Envoyer `/newbot`
3. Choisir nom (ex: "Friday 2.0") + username (ex: @friday_antonio_bot)
4. BotFather répond avec token : `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`
5. Copier token → `.env` : `TELEGRAM_BOT_TOKEN=1234567890:ABC...`

#### **TELEGRAM_CHAT_ID** (Antonio)

**Méthode 1 - Via bot @userinfobot** (plus simple) :
1. Ouvrir Telegram → Rechercher [@userinfobot](https://t.me/userinfobot)
2. Envoyer `/start`
3. Bot répond : "Your ID: `123456789`"
4. Copier → `.env` : `TELEGRAM_CHAT_ID=123456789`

**Méthode 2 - Via API Telegram** :
1. Envoyer message à votre bot Friday
2. Appeler API : `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Chercher `"chat":{"id":123456789}` dans la réponse JSON
4. Copier ID

#### **EMAILENGINE_TOKEN**

**Étapes** :
1. Lancer EmailEngine : `docker compose up -d emailengine`
2. Accéder UI : `http://friday.local/emailengine` (via Caddy) ou `http://localhost:3000`
3. Premier lancement → Créer compte admin
4. Settings → API → "Generate new token"
5. Copier token → `.env` : `EMAILENGINE_TOKEN=ee_...`

#### **MISTRAL_API_KEY**

**Étapes** :
1. Créer compte sur [console.mistral.ai](https://console.mistral.ai/)
2. Billing → Ajouter carte (5€ minimum)
3. API Keys → "Create new key"
4. Copier → `.env` : `MISTRAL_API_KEY=...`

#### **DEEPGRAM_API_KEY** (fallback STT)

**Étapes** :
1. Créer compte sur [deepgram.com](https://deepgram.com/)
2. Console → API Keys → "Create a key"
3. Copier → `.env` : `DEEPGRAM_API_KEY=...`

### 5.3 Script de vérification

```bash
# scripts/verify_env.sh
# Vérifie que toutes les variables requises sont définies

required_vars=(
  "TELEGRAM_BOT_TOKEN"
  "TELEGRAM_CHAT_ID"
  "MISTRAL_API_KEY"
  "EMAILENGINE_TOKEN"
  "POSTGRES_PASSWORD"
  "REDIS_PASSWORD"
)

for var in "${required_vars[@]}"; do
  if [ -z "${!var}" ]; then
    echo "❌ Variable manquante: $var"
    exit 1
  fi
done

echo "✅ Toutes les variables requises sont définies"
```

---

## 6. Graphe de connaissances - Population initiale (Migration)

### 6.1 Problématique

L'architecture spécifie comment peupler le graphe **au fil de l'eau** (nouveaux emails → création nœuds/relations) mais PAS la **migration initiale** de 55 000 emails existants + documents déjà archivés.

### 6.2 Stratégie migration graphe

**Décision** : La migration emails inclut **AUSSI** la population graphe initiale.

**Workflow migration enrichi** :

```python
# scripts/migrate_emails.py (enrichi)
async def migrate_email(self, email: dict):
    # 1. Classification (déjà implémenté)
    classification = await self.classify_email(email)

    # 2. Insertion PostgreSQL (déjà implémenté)
    await self.db.execute(...)

    # 3. NOUVEAU : Population graphe
    await self.populate_graph_from_email(email, classification)

    # 4. Publish event Redis
    # ...

async def populate_graph_from_email(self, email: dict, classification: dict):
    """
    Crée nœuds + relations dans Zep/Graphiti pour un email
    """
    # Créer nœud Email
    email_node = await graphiti.create_node(
        type="Email",
        properties={
            "message_id": email['message_id'],
            "subject": email['subject'],
            "date": email['received_at'],
            "category": classification['category'],
            "priority": classification['priority']
        }
    )

    # Créer nœud Person (sender) si n'existe pas
    sender_node = await graphiti.get_or_create_node(
        type="Person",
        properties={"email": email['sender']}
    )

    # Créer relation SENT_BY
    await graphiti.create_edge(
        from_node=email_node,
        to_node=sender_node,
        type="SENT_BY",
        properties={"timestamp": email['received_at']}
    )

    # Extraction entités NER
    entities = await extract_entities_ner(email['body_text'])
    for entity in entities:
        entity_node = await graphiti.get_or_create_node(
            type="Entity",
            properties={
                "name": entity.text,
                "entity_type": entity.label_
            }
        )
        await graphiti.create_edge(
            from_node=email_node,
            to_node=entity_node,
            type="MENTIONS",
            properties={"context": entity.context}
        )
```

### 6.3 Ordre population

**Séquence optimale** :

1. **PostgreSQL d'abord** (rapide, 9h)
2. **Graphe ensuite** (plus lent, ~15-20h supplémentaires)
3. **Vectoriel en dernier** (Qdrant embeddings, parallélisable)

**Rationale** : Si la migration graphe échoue, PostgreSQL est déjà peuplé. On peut retry la population graphe sans tout recommencer.

### 6.4 Durée totale migration

| Phase | Durée | Parallélisable ? |
|-------|-------|------------------|
| Classification + Insert PostgreSQL | ~9h | Non (rate limit Mistral) |
| Population graphe (nœuds + relations) | ~15-20h | Oui (batch 100 emails) |
| Embeddings Qdrant | ~6-8h | Oui (batch 1000 docs) |
| **TOTAL** | **~30-37h** | Nuit + week-end |

**Stratégie exécution** :
- Vendredi soir : Lancer migration
- Samedi matin : Checkpoint + vérification progression
- Dimanche soir : Migration terminée + validation

### 6.5 Checkpointing graphe

```python
# Extension checkpoint pour graphe
checkpoint_data = {
    'postgres_processed': 55000,
    'graph_processed': 42000,  # NOUVEAU
    'qdrant_processed': 30000,  # NOUVEAU
    'last_email_id': 'abc123'
}
```

**Resume partiel** : Si graphe crash à 42k/55k, reprendre à 42k (pas besoin de refaire PostgreSQL).

### 6.6 Validation post-migration

```python
# scripts/validate_migration.py
async def validate_graph_population():
    # Vérifier cohérence PostgreSQL vs Graphe
    email_count_postgres = await db.fetchval("SELECT COUNT(*) FROM ingestion.emails")
    email_count_graph = await graphiti.count_nodes(type="Email")

    assert email_count_graph == email_count_postgres, \
        f"Graphe incomplet: {email_count_graph}/{email_count_postgres}"

    # Vérifier relations SENT_BY
    edges_count = await graphiti.count_edges(type="SENT_BY")
    assert edges_count == email_count_postgres, \
        "Relations SENT_BY manquantes"

    print(f"✅ Graphe validé: {email_count_graph} emails + {edges_count} relations")
```

---

**Créé le** : 2026-02-05
**Version** : 1.0
