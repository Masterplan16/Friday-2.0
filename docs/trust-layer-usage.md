# Trust Layer - Guide d'utilisation

**Version** : 1.0 (2026-02-09)
**Story** : 1.6 - Trust Layer Middleware

---

## 📋 Table des matières

1. [Introduction](#introduction)
2. [Quick Start](#quick-start)
3. [Décorateur @friday_action](#décorateur-friday_action)
4. [ActionResult - Modèle standardisé](#actionresult---modèle-standardisé)
5. [Trust Levels](#trust-levels)
6. [Correction Rules](#correction-rules)
7. [Receipts](#receipts)
8. [Feedback Loop](#feedback-loop)
9. [Exemples complets](#exemples-complets)
10. [Troubleshooting](#troubleshooting)

---

## Introduction

Le **Trust Layer** est le système d'observabilité et de contrôle de Friday 2.0. Il garantit que **chaque action de module** :
- Est tracée avec un receipt complet
- Respecte le trust level (auto/propose/blocked)
- Peut être corrigée via feedback loop
- Produit des métriques pour promotion/rétrogradation

### Principes fondamentaux

1. **Observabilité complète** : Chaque action produit un `ActionResult` standardisé
2. **Trust-based execution** : Les actions sont exécutées, proposées ou bloquées selon leur trust level
3. **Feedback loop explicite** : Les corrections deviennent des règles SQL, pas du RAG
4. **Progression automatique** : Les trust levels évoluent selon l'accuracy

---

## Quick Start

### 1. Initialiser le TrustManager au démarrage

```python
# main.py ou startup.py
import asyncpg
from agents.src.middleware.trust import init_trust_manager

# Créer pool PostgreSQL
db_pool = await asyncpg.create_pool(
    host="localhost",
    database="friday",
    user="friday",
    password="friday_password",
)

# Initialiser Trust Manager global
trust_manager = init_trust_manager(db_pool)
await trust_manager.load_trust_levels("config/trust_levels.yaml")
```

### 2. Décorer vos fonctions de module

```python
from agents.src.middleware.trust import friday_action
from agents.src.middleware.models import ActionResult

@friday_action(module="email", action="classify", trust_default="auto")
async def classify_email(email: Email, **kwargs) -> ActionResult:
    # Vos règles de correction sont dans kwargs["_rules_prompt"]
    rules_prompt = kwargs.get("_rules_prompt", "")

    # Votre logique de classification
    category = await llm.classify(email.subject, rules=rules_prompt)

    # Retourner ActionResult standardisé
    return ActionResult(
        input_summary=f"Email de {email.sender}: {email.subject[:50]}",
        output_summary=f"→ Category: {category}",
        confidence=0.95,
        reasoning="Mots-clés détectés: urgent, facture",
        payload={"category": category},
    )
```

### 3. Utiliser la fonction

```python
# L'action est automatiquement tracée et contrôlée
result = await classify_email(email)

# Le receipt est créé dans core.action_receipts
print(f"Receipt ID: {result.payload['receipt_id']}")
print(f"Status: {result.status}")  # auto/pending/blocked
```

---

## Décorateur @friday_action

### Signature

```python
def friday_action(
    module: str,           # Nom du module (ex: "email", "archiviste")
    action: str,           # Nom de l'action (ex: "classify", "draft")
    trust_default: str = None,  # Trust level par défaut si absent de YAML
) -> Callable
```

### Comportement

Le décorateur effectue **automatiquement** :

1. **Charge le trust level** depuis `config/trust_levels.yaml`
2. **Charge les correction_rules** actives depuis PostgreSQL
3. **Injecte les règles** dans `kwargs["_rules_prompt"]`
4. **Exécute la fonction** décorée
5. **Applique le trust level** (auto/propose/blocked)
6. **Crée un receipt** dans `core.action_receipts`
7. **Retourne l'ActionResult** enrichi

### Paramètres injectés (kwargs)

```python
kwargs["_correction_rules"]  # Liste[CorrectionRule] : Règles actives
kwargs["_rules_prompt"]       # str : Règles formatées pour LLM
```

### Gestion des exceptions

Si la fonction raise une exception :
- Un `ActionResult` d'erreur est créé avec `status="rejected"`
- Un receipt est quand même créé pour traçabilité
- L'exception est re-raised après création du receipt

---

## ActionResult - Modèle standardisé

### Champs obligatoires

```python
ActionResult(
    # Résumés (10-500 chars)
    input_summary="Email de test@example.com: Facture janvier",
    output_summary="→ Category: finance",

    # Métriques (obligatoires)
    confidence=0.95,  # 0.0-1.0
    reasoning="Mots-clés détectés: facture, paiement, montant",

    # Optionnels
    payload={"category": "finance", "amount": 150.0},
    steps=[StepDetail(...)],  # Sous-étapes détaillées
)
```

### Champs remplis automatiquement

```python
# Remplis par le décorateur @friday_action
result.module = "email"
result.action_type = "classify"
result.trust_level = "auto"
result.status = "auto"
result.duration_ms = 125
result.action_id = UUID(...)
result.timestamp = datetime.now(UTC)
```

### StepDetail (optionnel)

Pour tracer des sous-étapes :

```python
from agents.src.middleware.models import StepDetail

step1 = StepDetail(
    step_number=1,
    description="Analyse du sujet",
    confidence=0.98,
    duration_ms=50,
    metadata={"tokens": 120},
)

step2 = StepDetail(
    step_number=2,
    description="Classification finale",
    confidence=0.95,
    duration_ms=30,
)

return ActionResult(
    input_summary="...",
    output_summary="...",
    confidence=min(step1.confidence, step2.confidence),  # MIN de tous
    reasoning="Classification en 2 étapes",
    steps=[step1, step2],
)
```

---

## Trust Levels

### 3 niveaux de confiance

| Trust Level | Comportement | Statut receipt | Notification |
|-------------|--------------|----------------|--------------|
| **auto** | Exécute immédiatement | `auto` | Telegram topic Metrics (après coup) |
| **propose** | Attend validation Telegram | `pending` | Telegram topic Actions (inline buttons) |
| **blocked** | Analyse seule, pas d'action | `blocked` | Telegram topic System (alerte) |

### Configuration (config/trust_levels.yaml)

```yaml
modules:
  email:
    classify: auto      # Confiance élevée
    draft: propose      # Nécessite validation
    send: blocked       # Trop risqué

  archiviste:
    ocr: auto
    classify: propose
```

### Promotion/Rétrogradation automatique

**Rétrogradation** (auto → propose) :
- Si `accuracy < 90%` sur 1 semaine
- ET `sample >= 10 actions`
- → Automatique via script nightly

**Promotion** (propose → auto) :
- Si `accuracy >= 95%` sur 3 semaines
- ET `validation manuelle Antonio`
- → Jamais automatique

**Anti-oscillation** :
- Minimum 2 semaines entre rétrogradation et promotion

---

## Correction Rules

### Structure

```sql
CREATE TABLE core.correction_rules (
    id UUID PRIMARY KEY,
    module TEXT NOT NULL,
    action_type TEXT,  -- NULL = toutes actions du module
    scope TEXT NOT NULL,  -- Ex: "classification", "drafting"
    priority INTEGER NOT NULL,  -- 1=max priorité
    conditions JSONB NOT NULL,
    output JSONB NOT NULL,
    source_receipts TEXT[],  -- IDs receipts ayant généré la règle
    hit_count INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT NOT NULL
);
```

### Exemple

```sql
INSERT INTO core.correction_rules (
    id, module, action_type, scope, priority,
    conditions, output, source_receipts, hit_count, active, created_by
) VALUES (
    gen_random_uuid(),
    'email',
    'classify',
    'classification-urgent',
    1,  -- Priorité max
    '{"sender_contains": "@urgent.com"}'::jsonb,
    '{"category": "urgent", "priority": "high"}'::jsonb,
    ARRAY[]::text[],
    0,
    true,
    'Antonio'
);
```

### Chargement et injection

```python
# Le décorateur charge automatiquement les règles
rules = await trust_manager.load_correction_rules("email", "classify")
# Retourne les règles triées par priorité (1=max)

# Format pour LLM
rules_prompt = trust_manager.format_rules_for_prompt(rules)
# Retourne : "RÈGLES DE CORRECTION PRIORITAIRES : \n- [Règle priorité 1] ..."

# Les règles sont injectées dans kwargs["_rules_prompt"]
```

---

## Receipts

### Structure (core.action_receipts)

```sql
CREATE TABLE core.action_receipts (
    id UUID PRIMARY KEY,
    module TEXT NOT NULL,
    action_type TEXT NOT NULL,
    input_summary TEXT NOT NULL,
    output_summary TEXT NOT NULL,
    confidence FLOAT NOT NULL,
    reasoning TEXT NOT NULL,
    payload JSONB DEFAULT '{}'::jsonb,  -- Inclut steps
    duration_ms INTEGER,
    trust_level TEXT NOT NULL,
    status TEXT NOT NULL,  -- auto/pending/approved/rejected/corrected
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Requêtes utiles

```sql
-- Derniers receipts
SELECT * FROM core.action_receipts
ORDER BY created_at DESC
LIMIT 20;

-- Receipts par module
SELECT module, action_type, COUNT(*), AVG(confidence)
FROM core.action_receipts
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY module, action_type;

-- Receipts en attente de validation
SELECT * FROM core.action_receipts
WHERE status = 'pending'
ORDER BY created_at DESC;
```

---

## Feedback Loop

### Workflow

1. **Antonio détecte une erreur** via Telegram `/journal`
2. **Antonio corrige manuellement** via `/correct <receipt_id>`
3. **Système détecte pattern** (2 occurrences identiques)
4. **Système propose règle** via Telegram
5. **Antonio valide** → Règle créée dans `core.correction_rules`
6. **Règle appliquée** aux prochaines actions

### Commandes Telegram Trust

```
/status         # Dashboard temps réel
/journal        # 20 dernières actions
/receipt <id>   # Détail d'une action
/confiance      # Accuracy par module
/stats          # Métriques globales
```

---

## Exemples complets

### Exemple 1 : Classification email (trust=auto)

```python
@friday_action(module="email", action="classify", trust_default="auto")
async def classify_email(email: Email, **kwargs) -> ActionResult:
    # Charger règles de correction
    rules_prompt = kwargs.get("_rules_prompt", "")

    # Appel LLM avec règles
    prompt = f"""
    Classe cet email dans une catégorie.

    {rules_prompt}

    Email : {email.subject}
    De : {email.sender}
    """

    category = await llm_adapter.complete(prompt=prompt)

    return ActionResult(
        input_summary=f"Email de {email.sender}: {email.subject[:50]}",
        output_summary=f"→ Category: {category}",
        confidence=0.95,
        reasoning=f"Classification basée sur sujet et expéditeur",
        payload={"category": category, "email_id": email.id},
    )
```

### Exemple 2 : Brouillon email (trust=propose)

```python
@friday_action(module="email", action="draft", trust_default="propose")
async def draft_email_reply(email: Email, **kwargs) -> ActionResult:
    rules_prompt = kwargs.get("_rules_prompt", "")

    # Générer brouillon
    draft = await llm_adapter.complete(
        prompt=f"Rédige une réponse à cet email.\n\n{rules_prompt}\n\nEmail: {email.body}"
    )

    return ActionResult(
        input_summary=f"Email de {email.sender}: {email.subject[:50]}",
        output_summary=f"→ Brouillon créé ({len(draft)} chars)",
        confidence=0.85,
        reasoning="Brouillon généré, nécessite validation avant envoi",
        payload={"draft": draft, "email_id": email.id},
    )
    # Status sera "pending" → inline buttons Telegram
```

### Exemple 3 : Action médicale (trust=blocked)

```python
@friday_action(module="medical", action="analyze", trust_default="blocked")
async def analyze_medical_document(doc: Document, **kwargs) -> ActionResult:
    # Analyse uniquement, JAMAIS d'action
    analysis = await llm_adapter.complete(
        prompt=f"Analyse ce document médical (lecture seule): {doc.text}"
    )

    return ActionResult(
        input_summary=f"Document médical: {doc.name}",
        output_summary=f"→ Analyse effectuée (lecture seule)",
        confidence=0.90,
        reasoning="Analyse uniquement, aucune action entreprise (données sensibles)",
        payload={"analysis": analysis, "doc_id": doc.id},
    )
    # Status sera "blocked" → notification System topic
```

---

## Troubleshooting

### Erreur : "TrustManager not initialized"

```python
# Solution : Appeler init_trust_manager() au démarrage
from agents.src.middleware.trust import init_trust_manager

trust_manager = init_trust_manager(db_pool)
await trust_manager.load_trust_levels("config/trust_levels.yaml")
```

### Erreur : "Trust levels not loaded"

```python
# Solution : Charger le YAML avant utilisation
trust_manager = get_trust_manager()
await trust_manager.load_trust_levels("config/trust_levels.yaml")
```

### Erreur : ValidationError sur ActionResult

```python
# Vérifier les tailles minimales :
input_summary >= 10 chars
output_summary >= 10 chars
reasoning >= 20 chars
confidence entre 0.0 et 1.0
```

### Receipt pas créé

```python
# Vérifier que la migration 011_trust_system.sql est appliquée
psql friday -c "SELECT COUNT(*) FROM core.action_receipts;"
```

### Règles de correction pas chargées

```python
# Vérifier qu'elles existent et sont actives
SELECT * FROM core.correction_rules
WHERE module = 'email' AND active = true;
```

---

## Patterns avancés

### Pattern 1 : Actions avec sous-étapes (StepDetail)

```python
from agents.src.middleware.models import StepDetail

@friday_action(module="email", action="complex_analysis", trust_default="propose")
async def analyze_email_complex(email: Email, **kwargs) -> ActionResult:
    steps = []

    # Étape 1 : Analyse du sujet
    subject_analysis = await llm_adapter.analyze_subject(email.subject)
    steps.append(StepDetail(
        step_number=1,
        description="Analyse du sujet",
        confidence=subject_analysis.confidence,
        duration_ms=50,
        metadata={"tokens": 120, "category": subject_analysis.category}
    ))

    # Étape 2 : Analyse du corps
    body_analysis = await llm_adapter.analyze_body(email.body)
    steps.append(StepDetail(
        step_number=2,
        description="Analyse du corps",
        confidence=body_analysis.confidence,
        duration_ms=150,
        metadata={"tokens": 450, "entities": body_analysis.entities}
    ))

    # Étape 3 : Synthèse
    final_confidence = min(subject_analysis.confidence, body_analysis.confidence)
    steps.append(StepDetail(
        step_number=3,
        description="Synthèse finale",
        confidence=final_confidence,
        duration_ms=30
    ))

    return ActionResult(
        input_summary=f"Email de {email.sender}: {email.subject[:50]}",
        output_summary=f"→ Analyse complète en 3 étapes",
        confidence=final_confidence,  # MIN de tous les steps
        reasoning="Analyse multi-étapes : sujet + corps + synthèse",
        steps=steps,
        payload={
            "subject_category": subject_analysis.category,
            "body_entities": body_analysis.entities
        }
    )
```

### Pattern 2 : Retry automatique avec circuit breaker

```python
from functools import wraps

def with_retry(max_retries=3, backoff_seconds=1):
    """Décorateur pour retry automatique sur erreurs transitoires."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (ConnectionError, TimeoutError) as e:
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(backoff_seconds * (2 ** attempt))
            raise RuntimeError(f"Max retries ({max_retries}) exceeded")
        return wrapper
    return decorator

@friday_action(module="email", action="classify", trust_default="auto")
@with_retry(max_retries=3)
async def classify_email_with_retry(email: Email, **kwargs) -> ActionResult:
    # Cette fonction sera retryée automatiquement en cas d'erreur réseau
    category = await llm_adapter.classify(email.subject)
    return ActionResult(...)
```

### Pattern 3 : Agrégation de confidence multi-sources

```python
@friday_action(module="archiviste", action="classify_document", trust_default="propose")
async def classify_document_multi_source(doc: Document, **kwargs) -> ActionResult:
    # Source 1 : OCR confidence
    ocr_result = await ocr_engine.extract(doc.file_path)
    ocr_confidence = ocr_result.confidence

    # Source 2 : Classification LLM
    llm_result = await llm_adapter.classify(ocr_result.text)
    llm_confidence = llm_result.confidence

    # Source 3 : Vérification filename
    filename_match = check_filename_pattern(doc.filename, llm_result.category)
    filename_confidence = 1.0 if filename_match else 0.7

    # Confidence finale = moyenne pondérée
    final_confidence = (
        ocr_confidence * 0.4 +
        llm_confidence * 0.5 +
        filename_confidence * 0.1
    )

    return ActionResult(
        input_summary=f"Document: {doc.filename}",
        output_summary=f"→ Category: {llm_result.category}",
        confidence=final_confidence,
        reasoning=f"OCR: {ocr_confidence:.2f}, LLM: {llm_confidence:.2f}, Filename: {filename_confidence:.2f}",
        payload={
            "category": llm_result.category,
            "ocr_confidence": ocr_confidence,
            "llm_confidence": llm_confidence,
            "filename_confidence": filename_confidence
        }
    )
```

---

## Best Practices

### ✅ DO

1. **Toujours retourner ActionResult** depuis fonctions décorées
2. **Utiliser MIN confidence** si plusieurs steps
3. **Résumés concis** : input/output_summary 10-500 chars
4. **Reasoning détaillé** : expliquer le "pourquoi" (20-2000 chars)
5. **Payload pour données techniques** : pas dans les résumés
6. **Tester avec mocks** : ne jamais appeler LLM réel en tests unitaires
7. **Trust level approprié** : auto (low risk), propose (medium), blocked (high)
8. **Charger TrustManager au démarrage** : init_trust_manager() une seule fois

### ❌ DON'T

1. **Ne PAS appeler create_receipt() manuellement** : le décorateur le fait
2. **Ne PAS modifier trust_level après création** : le décorateur le remplit
3. **Ne PAS oublier kwargs** dans la signature : nécessaire pour injection règles
4. **Ne PAS mettre PII dans résumés** : anonymiser avec Presidio AVANT
5. **Ne PAS créer ActionResult sans décorateur** : pas de traçabilité
6. **Ne PAS utiliser print()** : utiliser logger structuré
7. **Ne PAS hardcoder trust levels** : toujours via trust_levels.yaml
8. **Ne PAS ignorer ValidationError** : corriger les champs invalides

---

## Intégration avec autres modules

### Avec Presidio (anonymisation)

```python
from agents.src.tools.anonymize import anonymize_text, deanonymize_text

@friday_action(module="medical", action="analyze", trust_default="blocked")
async def analyze_medical_email(email: Email, **kwargs) -> ActionResult:
    # 1. Anonymiser AVANT appel LLM cloud
    anonymized_body, mapping = await anonymize_text(email.body)

    # 2. Analyse sur texte anonymisé
    analysis = await llm_adapter.analyze(anonymized_body)

    # 3. Dé-anonymiser le résultat
    result_text = await deanonymize_text(analysis, mapping)

    return ActionResult(
        input_summary=f"Email médical de {email.sender} (anonymisé)",
        output_summary=f"→ Analyse effectuée sur texte anonymisé",
        confidence=0.90,
        reasoning="Analyse médicale avec anonymisation Presidio complète",
        payload={"analysis": result_text, "pii_detected": len(mapping)}
    )
```

### Avec Redis Streams (événements)

```python
import redis.asyncio as redis

@friday_action(module="email", action="classify", trust_default="auto")
async def classify_email_with_event(email: Email, **kwargs) -> ActionResult:
    category = await llm_adapter.classify(email.subject)

    # Publier événement Redis Streams (critique)
    await redis_client.xadd(
        "email.classified",
        {
            "email_id": email.id,
            "category": category,
            "confidence": 0.95
        }
    )

    return ActionResult(
        input_summary=f"Email de {email.sender}: {email.subject[:50]}",
        output_summary=f"→ Category: {category}",
        confidence=0.95,
        reasoning="Classification + événement publié sur Redis Streams",
        payload={"category": category, "event_published": True}
    )
```

### Avec n8n workflows

```python
@friday_action(module="archiviste", action="process_document", trust_default="propose")
async def process_document_trigger_n8n(doc: Document, **kwargs) -> ActionResult:
    # 1. Traiter localement
    result = await ocr_and_classify(doc)

    # 2. Trigger n8n workflow pour actions suivantes
    await n8n_client.trigger_workflow(
        "document-processing-pipeline",
        {
            "doc_id": doc.id,
            "category": result.category,
            "confidence": result.confidence
        }
    )

    return ActionResult(
        input_summary=f"Document: {doc.filename}",
        output_summary=f"→ Traité + n8n workflow déclenché",
        confidence=result.confidence,
        reasoning="OCR + classification + déclenchement workflow n8n",
        payload={
            "category": result.category,
            "n8n_workflow": "document-processing-pipeline"
        }
    )
```

---

## FAQ

**Q : Puis-je utiliser @friday_action sur des fonctions sync (non-async) ?**
R : Non, le décorateur nécessite des fonctions `async`. Convertir votre fonction en async ou wrapper dans une coroutine.

**Q : Comment tester une fonction avec @friday_action ?**
R : Mocker `get_trust_manager()` et les dépendances DB. Voir `tests/unit/middleware/test_trust.py` pour exemples.

**Q : Que se passe-t-il si je ne retourne pas ActionResult ?**
R : ValidationError de Pydantic. Le décorateur attend toujours un ActionResult.

**Q : Comment changer le trust level d'une action ?**
R : Modifier `config/trust_levels.yaml` puis redémarrer l'app. Le TrustManager recharge le YAML au démarrage.

**Q : Les receipts sont-ils purgés automatiquement ?**
R : Non Day 1. Prévu dans Story 1.15 (Cleanup & Purge RGPD) avec retention 90 jours.

**Q : Puis-je avoir plusieurs @friday_action sur la même fonction ?**
R : Non, un seul décorateur par fonction. Utiliser des wrappers si besoin de composition.

**Q : Comment débugger un receipt qui n'est pas créé ?**
R : Vérifier logs structurés + `SELECT * FROM core.action_receipts ORDER BY created_at DESC`. Si vide, vérifier migration 011 appliquée.

**Q : La confidence peut-elle être calculée automatiquement ?**
R : Non, c'est à votre fonction de calculer la confidence appropriée. Si plusieurs steps, utiliser `min([step.confidence for step in steps])`.

---

## Métriques et monitoring

### Requêtes PostgreSQL utiles

```sql
-- Top 10 actions par volume (7 derniers jours)
SELECT module, action_type, COUNT(*) as total
FROM core.action_receipts
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY module, action_type
ORDER BY total DESC
LIMIT 10;

-- Moyenne confidence par module
SELECT module,
       AVG(confidence)::numeric(4,2) as avg_confidence,
       COUNT(*) as total_actions
FROM core.action_receipts
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY module
ORDER BY avg_confidence DESC;

-- Actions avec confidence faible (<0.80)
SELECT module, action_type, input_summary, confidence, created_at
FROM core.action_receipts
WHERE confidence < 0.80
  AND created_at > NOW() - INTERVAL '7 days'
ORDER BY confidence ASC
LIMIT 20;

-- Distribution des trust levels
SELECT trust_level, status, COUNT(*) as total
FROM core.action_receipts
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY trust_level, status
ORDER BY trust_level, status;

-- Temps d'exécution moyen par action
SELECT module, action_type,
       AVG(duration_ms)::integer as avg_ms,
       MAX(duration_ms) as max_ms,
       MIN(duration_ms) as min_ms
FROM core.action_receipts
WHERE duration_ms IS NOT NULL
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY module, action_type
ORDER BY avg_ms DESC;
```

---

## Voir aussi

- [Architecture Friday 2.0](../_docs/architecture-friday-2.0.md) - Document complet
- [Addendum Section 7](../_docs/architecture-addendum-20260205.md#7) - Formules Trust Layer
- [Diagramme de séquence](./trust-layer-sequence.md) - Flow complet
- [Migration 011](../database/migrations/011_trust_system.sql) - Tables SQL
- [Testing Strategy](./testing-strategy-ai.md) - Tests IA

---

**Dernière mise à jour** : 2026-02-09
**Version** : 1.0
**Mainteneur** : Friday 2.0 Team
