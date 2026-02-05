# Politique utilisation modèles IA - Friday 2.0

**Date** : 2026-02-05
**Version** : 1.0.0

---

## Vue d'ensemble

Friday 2.0 utilise des modèles IA externes (Mistral, Gemini, Claude) et locaux (Ollama).
Cette politique définit les règles de versionnage, upgrade, et monitoring des modèles.

---

## Règles de versionnage

### Environnements

| Environnement | Stratégie | Justification |
|--------------|-----------|---------------|
| **Dev/Test** | Suffixe `-latest` | Tester nouveaux modèles en continu |
| **Staging** | Version explicite | Valider performance avant prod |
| **Production** | Version explicite | Stabilité et reproductibilité |

### Exemples

**Mistral** :
- Dev : `mistral-large-latest` (suit automatiquement les releases)
- Staging : `mistral-large-2411` (fixer version candidate)
- Production : `mistral-large-2411` (après validation accuracy)

**Gemini** :
- Dev : `gemini-2.0-flash-latest`
- Staging : `gemini-2.0-flash-001`
- Production : `gemini-2.0-flash-001`

**Claude** :
- Dev : `claude-3-5-sonnet-latest`
- Staging : `claude-3-5-sonnet-20241022`
- Production : `claude-3-5-sonnet-20241022`

**Ollama (local)** :
- Dev : `nemotron:12b-instruct` (pas de suffixe -latest pour Ollama)
- Staging : `nemotron:12b-instruct`
- Production : `nemotron:12b-instruct`

---

## Procédure d'upgrade

### Phase 1 : Test en dev

1. **Activer `-latest` en dev**
   ```python
   # agents/src/config/settings.py
   LLM_MODEL = os.getenv("LLM_MODEL", "mistral-large-latest")  # Dev uniquement
   ```

2. **Tester pendant 1 semaine**
   - Exécuter tests unitaires + intégration
   - Valider accuracy sur datasets de référence (tests/fixtures/)
   - Surveiller métriques :
     ```python
     {
         "llm.accuracy.email_classification": 0.95,
         "llm.latency.p99_ms": 1200,
         "llm.cost.per_1k_tokens": 0.03
     }
     ```

3. **Identifier nouvelle version stable**
   ```bash
   # Exemple : -latest pointe maintenant vers mistral-large-2501
   curl https://api.mistral.ai/v1/models | jq '.data[] | select(.id | contains("large"))'
   # Output : "id": "mistral-large-2501"
   ```

### Phase 2 : Validation staging

4. **Déployer version explicite en staging**
   ```python
   # agents/src/config/settings.py (staging)
   LLM_MODEL = os.getenv("LLM_MODEL", "mistral-large-2501")  # Version candidate
   ```

5. **Tests approfondis (2 semaines)**
   - Rejouer 100+ emails réels (archive tests/fixtures/email_classification.json)
   - Comparer accuracy avec version actuelle production
   - Critères validation :
     - Accuracy >= version actuelle (pas de régression)
     - Latency p99 <= +20% max
     - Cost <= +30% max (sauf si accuracy +10%)

6. **Décision Go/No-Go**
   - Go : Accuracy maintenue OU améliorée
   - No-Go : Régression >3% → Rester sur version actuelle

### Phase 3 : Déploiement production

7. **Mise à jour progressive**
   ```bash
   # 1. Backup config actuelle
   cp .env.prod .env.prod.bak

   # 2. Update LLM_MODEL
   sed -i 's/mistral-large-2411/mistral-large-2501/g' .env.prod

   # 3. Redémarrer agents (rolling restart)
   docker compose up -d --no-deps agents
   ```

8. **Monitoring renforcé (72h)**
   - Alertes sur accuracy <90% (seuil normal : <85%)
   - Alertes sur latency p99 >2000ms
   - Surveillance corrections manuelles Antonio (feedback loop)

9. **Rollback si problème**
   ```bash
   # Restaurer version précédente
   cp .env.prod.bak .env.prod
   docker compose up -d --no-deps agents

   # Documenter dans Decision Log
   echo "Rollback mistral-large-2501 → 2411 : accuracy drop 92% → 88%" >> docs/DECISION_LOG.md
   ```

---

## Surveillance continue

### Métriques par modèle

**Stockage PostgreSQL** :
```sql
-- Table : core.llm_metrics
CREATE TABLE core.llm_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id TEXT NOT NULL,                -- "mistral-large-2411"
    module TEXT NOT NULL,                  -- "email", "archiviste", etc.
    action TEXT NOT NULL,                  -- "classify", "summarize", etc.
    accuracy DECIMAL(5,4),                 -- 0.9523 (calculé depuis corrections)
    latency_p50_ms INT,
    latency_p95_ms INT,
    latency_p99_ms INT,
    cost_per_1k_tokens DECIMAL(8,6),
    window_start TIMESTAMPTZ NOT NULL,    -- Fenêtre hebdomadaire
    window_end TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_llm_metrics_model ON core.llm_metrics(model_id, module, action, window_start);
```

**Calcul nightly** :
```python
# services/metrics/nightly.py
async def compute_llm_metrics():
    """Agrège métriques LLM par modèle/module/action sur fenêtre glissante 7j"""
    for model_id in ["mistral-large-2411", "mistral-small-latest"]:
        for module in ["email", "archiviste", "financial"]:
            accuracy = await calculate_accuracy(model_id, module, days=7)
            latency = await calculate_latency_percentiles(model_id, module, days=7)
            cost = await calculate_cost(model_id, module, days=7)

            await db.execute("""
                INSERT INTO core.llm_metrics
                (model_id, module, action, accuracy, latency_p99_ms, cost_per_1k_tokens, window_start, window_end)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, model_id, module, "all", accuracy, latency["p99"], cost, start, end)
```

### Dashboard Telegram `/confiance`

```
📊 Confiance modèles IA (7 derniers jours)

🤖 mistral-large-2411
  • Email classification : 95.2% (✅ stable)
  • Email summarize : 93.8% (⚠️ -1.2% vs semaine dernière)
  • Latency p99 : 1150ms
  • Cost : 0.028€/1k tokens

🤖 mistral-small-latest
  • Archiviste categorize : 88.5% (❌ <90%, rétrogradé à propose)
  • Latency p99 : 480ms
  • Cost : 0.012€/1k tokens

📈 Tendances
  • Accuracy globale : 93.1% (-0.5% vs semaine dernière)
  • Total corrections Antonio : 12 cette semaine
```

---

## Gestion des coûts

### Budgets mensuels

| Modèle | Usage | Budget max/mois | Alertes |
|--------|-------|-----------------|---------|
| Mistral Large | Classification emails, résumés | 20€ | Si >15€ |
| Mistral Small | Embeddings, queries simples | 5€ | Si >4€ |
| Gemini Flash | OCR post-processing | 10€ | Si >8€ |
| Ollama local | Données ultra-sensibles (médical) | 0€ (électricité VPS) | - |

### Optimisations

**Règles automatiques** :
- Si coût >budget → Basculer sur modèle moins cher (Large → Small)
- Si accuracy baisse <85% après bascule → Revenir modèle cher + alerte Antonio

**Stratégies manuelles** :
- Batch processing (traiter 10 emails → 1 appel LLM)
- Cache aggressive (résumés identiques)
- Ollama local pour use cases tolérants latence (+500ms)

---

## Matrix de décision modèle

### Quand utiliser Mistral Large ?

| Critère | Seuil |
|---------|-------|
| Complexité tâche | Classification multi-label (>10 classes) |
| Accuracy requise | >95% |
| Données sensibles | Non (sinon Ollama local) |
| Budget disponible | >50% budget mensuel restant |

**Exemples** : Email classification (urgent/important), Financial categorization

### Quand utiliser Mistral Small ?

| Critère | Seuil |
|---------|-------|
| Complexité tâche | Classification binaire/simple |
| Accuracy acceptable | >90% |
| Volume élevé | >100 requêtes/jour |
| Budget serré | <30% budget mensuel restant |

**Exemples** : Spam detection, Simple summaries, Embeddings

### Quand utiliser Ollama local ?

| Critère | Seuil |
|---------|-------|
| Données sensibles | RGPD strict (médical, financier, juridique) |
| Latency tolérable | >2 secondes OK |
| Accuracy acceptable | >85% |
| Zéro coût API | Requis |

**Exemples** : Analyse dossier médical, Extraction données bancaires, Contrats juridiques

---

## Anti-patterns (INTERDITS)

### 1. Hardcoder model IDs sans env var

```python
# ❌ INCORRECT
response = mistral.chat(model="mistral-large-2411", messages=...)

# ✅ CORRECT
response = mistral.chat(model=settings.LLM_MODEL, messages=...)
```

### 2. Utiliser `-latest` en production

```python
# ❌ INCORRECT (prod)
LLM_MODEL = "mistral-large-latest"  # Version non déterministe

# ✅ CORRECT (prod)
LLM_MODEL = "mistral-large-2411"  # Version fixe
```

### 3. Ignorer accuracy drops

```python
# ❌ INCORRECT
if accuracy < 0.80:
    logger.warning("Accuracy faible")  # Pas d'action

# ✅ CORRECT
if accuracy < 0.85:
    await downgrade_trust_level(module, action)
    await alert_telegram(f"⚠️ Accuracy {module}.{action} : {accuracy:.1%}")
```

---

## Références

### Documentation API

- **Mistral AI** : https://docs.mistral.ai/api/
- **Gemini** : https://ai.google.dev/gemini-api/docs
- **Claude** : https://docs.anthropic.com/claude/reference
- **Ollama** : https://ollama.com/library

### Model cards

| Modèle | Context window | Output max | Prix (input/output) |
|--------|---------------|------------|---------------------|
| mistral-large-2411 | 128k tokens | 4k tokens | 0.002€ / 0.006€ per 1k tokens |
| mistral-small-2412 | 32k tokens | 8k tokens | 0.0002€ / 0.0006€ per 1k tokens |
| gemini-2.0-flash-001 | 1M tokens | 8k tokens | 0.00001€ / 0.00003€ per 1k tokens |
| nemotron:12b-instruct | Illimité (local) | Illimité | 0€ (électricité VPS) |

---

## Changelog

| Date | Change | Raison |
|------|--------|--------|
| 2026-02-05 | Création document | Code review adversarial v2 finding #25 |
| 2026-02-05 | Ajout matrix décision modèle | Clarifier règles usage Large vs Small vs Ollama |

---

**Version** : 1.0.0
**Prochaine révision** : Après Story 2 (Email Agent) en production
