# Politique utilisation modeles IA - Friday 2.0

**Date** : 2026-02-09
**Version** : 2.0.0

---

## Vue d'ensemble

Friday 2.0 utilise **Claude Sonnet 4.5** (Anthropic) comme modele unique pour toutes les taches IA.

**Decision D17** : 100% Claude Sonnet 4.5 -- meilleur structured output, instruction following et consistance. Un seul modele, zero routing, budget API ~45 EUR/mois.

**Rationale** :
- **Structured output** : Reponses JSON fiables, parsing Pydantic natif sans retry
- **Instruction following** : Respect strict des prompts complexes (classification multi-label, regles injectees)
- **Consistance** : Resultats reproductibles entre appels, moins de variance que les alternatives
- **Simplicite operationnelle** : Un seul adaptateur, une seule API key, zero logique de routing
- **Anonymisation RGPD** : Pipeline Presidio AVANT tout appel (meme politique qu'avant, seul le modele change)

**Historique** : Le projet utilisait initialement une strategie multi-modeles (Mistral Large/Small, Gemini Flash, Ollama local). La decision D17 (2026-02-09) simplifie radicalement cette approche apres benchmarks internes montrant la superiorite de Claude Sonnet 4.5 sur tous les axes.

---

## Regles de versionnage

### Environnements

| Environnement | Strategie | Modele | Justification |
|--------------|-----------|--------|---------------|
| **Dev/Test** | Suffixe `-latest` | `claude-sonnet-4-5-20250929` | Tester en continu, suivre releases |
| **Production** | Version explicite | `claude-sonnet-4-5-20250929` | Stabilite et reproductibilite |

### Configuration

```python
# agents/src/config/settings.py
class Settings(BaseSettings):
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-sonnet-4-5-20250929"  # Version fixe prod
    ANTHROPIC_API_KEY: str  # Via age/SOPS, JAMAIS en clair

    # Seuils monitoring
    LLM_BUDGET_ALERT_EUR: float = 35.0  # Alerte si >35 EUR
    LLM_BUDGET_MAX_EUR: float = 45.0    # Budget max mensuel
```

### Adaptateur LLM

```python
# agents/src/adapters/llm.py
def get_llm_adapter() -> LLMAdapter:
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    if provider == "anthropic":
        return AnthropicAdapter(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("LLM_MODEL", "claude-sonnet-4-5-20250929"),
        )
    # Extensible : ajouter d'autres providers si veille D18 le recommande
    raise ValueError(f"Unknown LLM provider: {provider}")
```

**Swappabilite** : Changer de modele = modifier 1 fichier (`adapters/llm.py`) + 1 env var (`LLM_MODEL`). Zero impact sur le reste du code grace au pattern adaptateur.

---

## Procedure d'upgrade

### Veille mensuelle automatisee (Decision D18)

La veille mensuelle garantit que Friday utilise toujours le meilleur modele disponible sans changement impulsif.

#### Benchmark mensuel

**Frequence** : 1er de chaque mois (job n8n automatise)

**Protocole** :
1. **Benchmark modele actuel** (Claude Sonnet 4.5) sur datasets de reference
2. **Benchmark 2-3 concurrents** identifies (ex: Gemini, Mistral, GPT)
3. **Comparaison sur metriques standardisees** :

| Metrique | Poids | Mesure |
|----------|-------|--------|
| Accuracy classification email | 25% | Dataset `tests/fixtures/email_classification.json` |
| Structured output fiabilite | 25% | Taux de parsing JSON sans erreur |
| Instruction following | 20% | Score sur prompts complexes avec regles |
| Latency p99 | 15% | Temps reponse percentile 99 |
| Cout par 1k tokens | 15% | Prix input + output pondere |

**Seuil d'alerte** : Un concurrent est signale si >10% superieur sur >=3 metriques simultanement.

#### Rapport mensuel

```
-- Topic Telegram : Metrics & Logs --

Veille modeles IA - Fevrier 2026

Modele actuel : claude-sonnet-4-5-20250929
  Accuracy email : 95.2%
  Structured output : 99.1%
  Instruction following : 94.8%
  Latency p99 : 1100ms
  Cout : 0.015 EUR/1k tokens

Concurrents testes :
  gemini-2.5-pro : Accuracy 93.1%, SO 96.2%, IF 91.0%
  mistral-large-2502 : Accuracy 91.8%, SO 94.5%, IF 89.2%

Conclusion : Aucun concurrent ne depasse le seuil d'alerte.
Prochain benchmark : 1er mars 2026
```

#### Procedure de changement de modele

**Prerequis** : Un concurrent depasse le seuil d'alerte (>10% sur >=3 metriques).

1. **Phase validation (3 semaines)** :
   - Deployer le concurrent en dev/test
   - Rejouer 200+ cas reels depuis les archives
   - Confirmer la superiorite sur 3 semaines consecutives (pas de pic ponctuel)

2. **Phase migration (1 semaine)** :
   ```bash
   # 1. Backup config actuelle
   cp .env.prod .env.prod.bak

   # 2. Modifier adaptateur si nouveau provider
   # agents/src/adapters/llm.py (ajouter nouveau provider)

   # 3. Update env var
   # LLM_PROVIDER=nouveau_provider
   # LLM_MODEL=nouveau_modele_version_fixe

   # 4. Redemarrer agents
   docker compose up -d --no-deps agents
   ```

3. **Phase monitoring renforce (72h)** :
   - Alertes sur accuracy <90%
   - Alertes sur latency p99 >2000ms
   - Surveillance corrections manuelles Antonio

4. **Rollback si probleme** :
   ```bash
   cp .env.prod.bak .env.prod
   docker compose up -d --no-deps agents
   # Documenter dans Decision Log
   ```

**Regle des 3 mois** : Pas de changement de modele si le modele actuel est en production depuis moins de 3 mois, sauf regression critique (accuracy <80%).

---

## Matrix de decision modele

### Modele unique : Claude Sonnet 4.5

Avec la decision D17, il n'y a plus de routing entre modeles. Claude Sonnet 4.5 est utilise pour **toutes** les taches IA.

| Tache | Modele | Trust Level |
|-------|--------|-------------|
| Classification emails | Claude Sonnet 4.5 | propose (Day 1) |
| Resume emails | Claude Sonnet 4.5 | auto |
| Categorisation financiere | Claude Sonnet 4.5 | propose |
| OCR post-processing | Claude Sonnet 4.5 | auto |
| Renommage/classement documents | Claude Sonnet 4.5 | propose |
| Generation brouillons reponse | Claude Sonnet 4.5 | propose |
| Heartbeat (decisions proactives) | Claude Sonnet 4.5 | auto |
| Extraction entites (knowledge graph) | Claude Sonnet 4.5 | auto |
| Analyse these/recherche | Claude Sonnet 4.5 | blocked |
| Analyse medicale | Claude Sonnet 4.5 | blocked |

**Embeddings** : Utiliser le modele d'embeddings Anthropic ou un modele d'embeddings dedie (a definir en Story 3). Les embeddings ne passent PAS par le LLM de generation.

**Donnees ultra-sensibles** : Pipeline Presidio anonymise AVANT l'appel a Claude Sonnet 4.5. Pas de modele local (Ollama retire -- decision D12). Si anonymisation impossible pour un cas specifique, le trust level `blocked` empeche tout envoi au LLM.

---

## Gestion des couts

### Budget mensuel

| Poste | Budget | Alerte |
|-------|--------|--------|
| Claude Sonnet 4.5 (toutes taches) | ~45 EUR/mois | Si >35 EUR |

### Pricing Claude Sonnet 4.5

| Composante | Prix |
|-----------|------|
| Input tokens | $3 / 1M tokens (~2.75 EUR) |
| Output tokens | $15 / 1M tokens (~13.75 EUR) |
| Context window | 200k tokens |
| Output max | 8k tokens |

### Optimisations

**Strategies appliquees** :
- **Cache prompt** : Utiliser le caching Anthropic pour prefixes de prompt repetes (system prompts, regles de correction)
- **Batch processing** : Grouper emails similaires quand possible (ex: 5 emails meme expediteur)
- **Prompt concis** : Minimiser les tokens input en injectant uniquement les regles pertinentes
- **Early exit** : Ne pas appeler le LLM si une regle deterministe suffit (ex: regex pour spam connu)

**Monitoring cout** :
```python
# services/metrics/nightly.py
async def check_monthly_budget():
    """Verifie le budget mensuel et alerte si necessaire"""
    total_cost = await db.fetchval("""
        SELECT COALESCE(SUM(cost_eur), 0)
        FROM core.llm_metrics
        WHERE window_start >= date_trunc('month', NOW())
    """)

    if total_cost > settings.LLM_BUDGET_ALERT_EUR:
        await alert_telegram(
            topic="system",
            message=f"Budget LLM : {total_cost:.2f} EUR / {settings.LLM_BUDGET_MAX_EUR} EUR"
        )
```

---

## Surveillance continue

### Metriques par module

**Stockage PostgreSQL** :
```sql
-- Table : core.llm_metrics
CREATE TABLE core.llm_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id TEXT NOT NULL,                -- "claude-sonnet-4-5-20250929"
    module TEXT NOT NULL,                  -- "email", "archiviste", etc.
    action TEXT NOT NULL,                  -- "classify", "summarize", etc.
    accuracy DECIMAL(5,4),                 -- 0.9523 (calcule depuis corrections)
    latency_p50_ms INT,
    latency_p95_ms INT,
    latency_p99_ms INT,
    cost_eur DECIMAL(8,4),                -- Cout en EUR pour cette fenetre
    tokens_input INT,                     -- Tokens input consommes
    tokens_output INT,                    -- Tokens output consommes
    window_start TIMESTAMPTZ NOT NULL,    -- Fenetre hebdomadaire
    window_end TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_llm_metrics_model ON core.llm_metrics(model_id, module, action, window_start);
```

**Calcul nightly** :
```python
# services/metrics/nightly.py
async def compute_llm_metrics():
    """Agrege metriques LLM par module/action sur fenetre glissante 7j"""
    model_id = settings.LLM_MODEL  # Un seul modele

    for module in ["email", "archiviste", "financial"]:
        accuracy = await calculate_accuracy(model_id, module, days=7)
        latency = await calculate_latency_percentiles(model_id, module, days=7)
        cost = await calculate_cost(model_id, module, days=7)
        tokens = await calculate_tokens(model_id, module, days=7)

        await db.execute("""
            INSERT INTO core.llm_metrics
            (model_id, module, action, accuracy, latency_p50_ms, latency_p95_ms,
             latency_p99_ms, cost_eur, tokens_input, tokens_output, window_start, window_end)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """, model_id, module, "all", accuracy,
            latency["p50"], latency["p95"], latency["p99"],
            cost, tokens["input"], tokens["output"], start, end)

    # Verification budget mensuel
    await check_monthly_budget()
```

### Dashboard Telegram `/confiance`

```
Confiance modeles IA (7 derniers jours)

Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)
  Email classification : 95.2% (stable)
  Email summarize : 93.8% (-1.2% vs semaine derniere)
  Archiviste categorize : 91.5% (stable)
  Latency p99 : 1100ms
  Cout semaine : 8.50 EUR (projection mois : 36.20 EUR)

Tendances
  Accuracy globale : 93.5% (-0.3% vs semaine derniere)
  Total corrections Antonio : 8 cette semaine
  Tokens consommes : 1.2M input / 180k output

Prochaine veille mensuelle : 1er mars 2026
```

---

## Anti-patterns (INTERDITS)

### 1. Hardcoder model IDs sans env var

```python
# INCORRECT
response = client.messages.create(model="claude-sonnet-4-5-20250929", ...)

# CORRECT
response = client.messages.create(model=settings.LLM_MODEL, ...)
```

### 2. Appeler le LLM sans passer par l'adaptateur

```python
# INCORRECT
from anthropic import Anthropic
client = Anthropic()
response = client.messages.create(...)

# CORRECT
from agents.src.adapters.llm import get_llm_adapter
llm = get_llm_adapter()
response = await llm.chat(prompt=prompt)
```

### 3. Envoyer des PII au LLM sans anonymisation

```python
# INCORRECT
response = await llm.chat(prompt=text_with_pii)

# CORRECT
anonymized = await presidio_anonymize(text_with_pii)
response = await llm.chat(prompt=anonymized)
result = await presidio_deanonymize(response)
```

### 4. Ignorer accuracy drops

```python
# INCORRECT
if accuracy < 0.80:
    logger.warning("Accuracy faible")  # Pas d'action

# CORRECT
if accuracy < 0.85:
    await downgrade_trust_level(module, action)
    await alert_telegram(
        topic="system",
        message=f"Accuracy {module}.{action} : {accuracy:.1%} -- retrogradation trust"
    )
```

### 5. Changer de modele impulsivement

```
INCORRECT : Voir un benchmark favorable et migrer immediatement
CORRECT : Suivre la procedure de veille D18 (seuil >10% sur >=3 metriques + 3 semaines validation)
```

---

## References

### Documentation API

- **Anthropic (Claude)** : https://docs.anthropic.com/claude/reference

### Model card

| Modele | Context window | Output max | Prix input | Prix output |
|--------|---------------|------------|------------|-------------|
| claude-sonnet-4-5-20250929 | 200k tokens | 8k tokens | $3 / 1M tokens | $15 / 1M tokens |

### Fichiers lies

| Fichier | Role |
|---------|------|
| `agents/src/adapters/llm.py` | Adaptateur LLM (swappable) |
| `agents/src/config/settings.py` | Configuration modele + budget |
| `services/metrics/nightly.py` | Aggregation metriques + verification budget |
| `config/trust_levels.yaml` | Trust levels par module/action |
| `tests/fixtures/email_classification.json` | Dataset benchmark email |

---

## Changelog

| Date | Change | Raison |
|------|--------|--------|
| 2026-02-05 | v1.0.0 - Creation document | Code review adversarial v2 finding #25 |
| 2026-02-05 | Ajout matrix decision modele | Clarifier regles usage Large vs Small vs Ollama |
| 2026-02-09 | v2.0.0 - Reecriture complete | Decision D17 : 100% Claude Sonnet 4.5, suppression multi-modeles |
| 2026-02-09 | Ajout veille mensuelle | Decision D18 : benchmark mensuel automatise |

---

**Version** : 2.0.0
**Prochaine revision** : 1er mars 2026 (premiere veille mensuelle D18)
