# Trust Metrics & Rétrogradation - Spécification Technique

**Story** : 1.8 - Trust Metrics & Rétrogradation
**Version** : 1.0
**Date** : 2026-02-10
**Status** : Implémenté

---

## 📋 Vue d'ensemble

Ce document spécifie le système de **métriques trust** et de **rétrogradation/promotion automatique** des trust levels dans Friday 2.0.

### Objectifs

1. **Mesurer la performance** de chaque module/action via accuracy hebdomadaire
2. **Rétrograder automatiquement** les trust levels si accuracy < seuils
3. **Promouvoir manuellement** avec validation conditions (accuracy + anti-oscillation)
4. **Éviter l'oscillation** entre niveaux via délais minimums

### Architecture

```
┌─────────────────┐
│ core.           │
│ action_receipts │  ← Actions exécutées par Friday
└────────┬────────┘
         │
         ├── Nightly aggregation (03h00)
         │   └── services/metrics/nightly.py
         │
         ▼
┌─────────────────┐
│ core.           │
│ trust_metrics   │  ← Metrics hebdomadaires (accuracy, confidence)
└────────┬────────┘
         │
         ├── Détection rétrogradations
         │   └── detect_retrogradations()
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│ config/         │     │ Redis Streams   │
│ trust_levels.   │ ←→  │ trust.level.    │
│ yaml            │     │ changed         │
└─────────────────┘     └─────────────────┘
         │
         ├── Commandes Telegram
         │   └── /trust promote, /trust set
         │
         ▼
┌─────────────────┐
│ Notifications   │
│ Telegram        │
│ Topic System    │
└─────────────────┘
```

---

## 📐 Formule Accuracy

### Définition formelle (Addendum §7.2)

```python
accuracy(module, action, week) = 1 - (corrections / total_actions)

# Où :
# - corrections = COUNT(*) FILTER (WHERE status='corrected') sur période
# - total_actions = COUNT(*) WHERE status IN ('auto', 'approved') sur période
# - Exclut status='blocked' et 'pending' du calcul
```

### Exemples

| Période | Total actions | Corrections | Accuracy |
|---------|---------------|-------------|----------|
| Semaine 1 | 15 | 2 | 86.7% (13/15) |
| Semaine 2 | 24 | 1 | 95.8% (23/24) |
| Semaine 3 | 8 | 3 | 62.5% (5/8) |

### Granularité

- **Par module ET action** : `email.classify`, `finance.classify_transaction`
- **Fenêtre glissante** : 7 jours (pas semaine calendaire)
- **Recalcul** : Quotidien à 03h00 UTC (cron nightly)

---

## 🔄 Règles de Rétrogradation

### Règle 1 : auto → propose (AC2)

**Condition** : `accuracy < 90%` AND `total_actions >= 10` AND `current_trust = 'auto'`

**Action** :
1. Modifier `config/trust_levels.yaml` : `module.action: propose`
2. Envoyer événement Redis : `friday:events:trust.level.changed`
3. Notifier Telegram topic System : "⚠️ Module email.classify rétrogradé auto → propose (accuracy 87%, 15 actions)"
4. Mettre à jour `core.trust_metrics.last_trust_change_at`

**Exemple** :

```yaml
# Avant rétrogradation
modules:
  email:
    classify: auto  # accuracy 85% sur 12 actions

# Après rétrogradation automatique (nightly)
modules:
  email:
    classify: propose  # rétrogradé car <90%
```

---

### Règle 2 : propose → blocked (AC3)

**Condition** : `accuracy < 70%` AND `total_actions >= 5` AND `current_trust = 'propose'`

**Action** : Identique à Règle 1

**Exemple** :

```yaml
# Avant
modules:
  finance:
    classify_transaction: propose  # accuracy 65% sur 8 actions

# Après rétrogradation
modules:
  finance:
    classify_transaction: blocked  # rétrogradé car <70%
```

---

### Seuils échantillon minimum

| Transition | Seuil actions | Raison |
|------------|---------------|--------|
| auto → propose | ≥10 actions | Éviter rétrogradations sur échantillons trop petits |
| propose → blocked | ≥5 actions | Seuil plus bas car déjà en propose (alerte précoce) |

---

## ⬆️ Règles de Promotion

### Règle 3 : propose → auto (AC4)

**Condition** :
- `accuracy >= 95%` sur **2 semaines consécutives**
- `total_actions >= 20` sur ces 2 semaines
- Anti-oscillation : **14 jours min** depuis dernière rétrogradation
- **Manuelle** via `/trust promote email classify`

**Validation** :

```python
# Charger metrics 2 dernières semaines
metrics = await _get_metrics("email", "classify", weeks=2)

# Calculer accuracy agrégée
avg_accuracy = sum(m["accuracy"] for m in metrics) / len(metrics)
total_actions = sum(m["total_actions"] for m in metrics)

# Vérifier conditions
if avg_accuracy >= 0.95 and total_actions >= 20:
    # Vérifier anti-oscillation
    last_change = await _get_last_trust_change("email", "classify")
    if (datetime.utcnow() - last_change).days >= 14:
        # Promotion autorisée
        await _apply_trust_level_change("email", "classify", "auto", "promotion")
```

---

### Règle 4 : blocked → propose (AC5)

**Condition** :
- `accuracy >= 90%` sur **4 semaines consécutives**
- `total_actions >= 10` sur ces 4 semaines
- Anti-oscillation : **14 jours min** depuis dernière rétrogradation
- **Manuelle** via `/trust promote finance classify_transaction`

---

### Règle 5 : Override manuel (AC6)

**Condition** : **Aucune** (bypass tout)

**Usage** : `/trust set <module> <action> <level>`

**Exemple** :

```bash
# Forcer un module à blocked sans conditions
/trust set email classify blocked

# Réponse :
⚙️ Override manuel appliqué
Module : email.classify
Transition : auto → blocked
⚠️ Bypass des conditions (anti-oscillation, accuracy)
```

**Log WARNING** : Chaque override génère un log `WARNING` pour traçabilité :

```json
{
  "level": "warning",
  "event": "Manual trust override by Antonio",
  "module": "email",
  "action": "classify",
  "old_level": "auto",
  "new_level": "blocked"
}
```

---

## ⏱️ Anti-oscillation (AC7)

### Objectif

Éviter les oscillations rapides entre trust levels (ex: auto → propose → auto → propose en 1 semaine).

### Règles temporelles

| Après transition | Délai minimum | Avant transition |
|------------------|---------------|------------------|
| Rétrogradation | **14 jours** | Promotion |
| Promotion | **7 jours** | Rétrogradation |

### Implémentation

**Stockage** : Colonne `last_trust_change_at` dans `core.trust_metrics`

```sql
ALTER TABLE core.trust_metrics
ADD COLUMN last_trust_change_at TIMESTAMPTZ DEFAULT NULL;
```

**Vérification** :

```python
# Dans /trust promote
last_change = await _get_last_trust_change(module, action)

if last_change:
    days_since_change = (datetime.utcnow() - last_change).days
    if days_since_change < 14:
        # Bloquer promotion
        raise PromotionTooEarlyError(f"Attendre {14 - days_since_change} jours")
```

---

## 📊 Table `core.trust_metrics`

### Schema SQL

```sql
CREATE TABLE core.trust_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module VARCHAR(100) NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    week_start TIMESTAMPTZ NOT NULL,
    week_end TIMESTAMPTZ,  -- Calculé automatiquement : week_start + 7 jours
    total_actions INT NOT NULL,
    corrected_actions INT NOT NULL DEFAULT 0,
    accuracy NUMERIC(5,4) NOT NULL,
    avg_confidence NUMERIC(5,4),
    current_trust_level VARCHAR(20),
    previous_trust_level VARCHAR(20),
    trust_changed BOOLEAN DEFAULT FALSE,
    recommended_trust_level VARCHAR(20),
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    last_trust_change_at TIMESTAMPTZ DEFAULT NULL,  -- AC7 anti-oscillation

    CONSTRAINT uq_trust_metrics_week UNIQUE (module, action_type, week_start)
);

CREATE INDEX idx_trust_metrics_lookup ON core.trust_metrics(module, action_type);
CREATE INDEX idx_trust_metrics_week ON core.trust_metrics(week_start DESC);
CREATE INDEX idx_trust_metrics_last_change ON core.trust_metrics(module, action_type, last_trust_change_at DESC);
```

### Exemple données

```sql
SELECT module, action_type, total_actions, accuracy, current_trust_level, recommended_trust_level
FROM core.trust_metrics
WHERE week_start >= NOW() - INTERVAL '4 weeks'
ORDER BY week_start DESC;
```

| module | action_type | total_actions | accuracy | current_trust | recommended_trust |
|--------|-------------|---------------|----------|---------------|-------------------|
| email | classify | 15 | 0.8667 | auto | propose |
| finance | classify_transaction | 8 | 0.6250 | propose | blocked |
| tuteur_these | review | 24 | 0.9583 | propose | propose |

---

## 🤖 Commandes Telegram

### `/trust promote <module> <action>`

Promouvoir manuellement un trust level (AC4, AC5).

**Usage** :

```bash
/trust promote email classify
```

**Réponses possibles** :

```
✅ Promotion réussie
Module : email.classify
Transition : propose → auto
Accuracy : 97.0% (sur 2 semaines)
Actions : 24
```

```
❌ Promotion refusée : Accuracy insuffisante
Accuracy sur 2 semaines : 92%
Seuil requis : 95%
```

```
❌ Promotion refusée : Anti-oscillation
Dernière transition : 2026-02-05
Jours écoulés : 5/14 minimum
Attendre encore 9 jour(s).
```

---

### `/trust set <module> <action> <level>`

Override manuel (bypass conditions) - Reserved Mainteneur (AC6).

**Usage** :

```bash
/trust set finance classify_transaction blocked
```

**Réponse** :

```
⚙️ Override manuel appliqué
Module : finance.classify_transaction
Transition : propose → blocked
⚠️ Bypass des conditions (anti-oscillation, accuracy)
```

---

### `/trust` (sans arguments)

Affiche l'aide complète.

---

## 🔧 Troubleshooting

### Rétrogradation détectée mais trust_levels.yaml non modifié

**Symptôme** : Logs montrent "Retrogradations detected" mais fichier YAML inchangé.

**Cause** : Bug #1 corrigé en Story 1.8 (méthode `apply_retrogradations()` manquante).

**Solution** : Vérifier que `detect_retrogradations()` appelle bien `apply_retrogradations()` :

```python
if retrogradations:
    logger.warning("Retrogradations detected", count=len(retrogradations))
    await self.apply_retrogradations(retrogradations)  # ← Doit être présent
    await self.send_retrogradation_alerts(retrogradations)
```

---

### Metrics non calculées après 03h00

**Symptôme** : `core.trust_metrics` vide ou non mis à jour.

**Causes possibles** :

1. Service `nightly.py` non démarré
2. Crash lors de l'agrégation (vérifier logs)
3. Aucune action dans `core.action_receipts`

**Debug** :

```bash
# Vérifier service
docker ps | grep metrics-nightly

# Logs
docker logs friday-metrics-nightly --tail=100

# Tester manuellement
cd services/metrics
python nightly.py
```

---

### Promotion refusée malgré accuracy 96%

**Symptôme** : `/trust promote` refusé alors que accuracy >95%.

**Causes possibles** :

1. **Échantillon insuffisant** : Vérifier `total_actions >= 20` (propose→auto)
2. **Anti-oscillation** : Dernière rétrogradation <14 jours
3. **Période incorrecte** : Vérifier 2 semaines consécutives (pas 1 semaine)

**Debug** :

```sql
-- Vérifier metrics 2 dernières semaines
SELECT week_start, accuracy, total_actions
FROM core.trust_metrics
WHERE module = 'email' AND action_type = 'classify'
  AND week_start >= NOW() - INTERVAL '2 weeks'
ORDER BY week_start DESC;

-- Vérifier anti-oscillation
SELECT last_trust_change_at,
       NOW() - last_trust_change_at AS time_since_change
FROM core.trust_metrics
WHERE module = 'email' AND action_type = 'classify'
ORDER BY week_start DESC
LIMIT 1;
```

---

## 📚 Références

- **Architecture** : [`_docs/architecture-friday-2.0.md`](../_docs/architecture-friday-2.0.md)
- **Addendum Section 7** : [`_docs/architecture-addendum-20260205.md#7`](../_docs/architecture-addendum-20260205.md#7-trust-retrogradation---definition-formelle-des-metriques)
- **PRD** : FRs 30, 31, 122
- **Migrations** : `database/migrations/011_trust_system.sql`, `013_trust_metrics_columns.sql`, `014_trust_metrics_anti_oscillation.sql`
- **Tests** : `tests/unit/metrics/test_retrogradations.py`, `tests/unit/bot/test_trust_commands.py`, `tests/integration/test_trust_retrogradation.py`

---

**Dernière mise à jour** : 2026-02-10
**Auteur** : Workflow BMAD `dev-story`
**Version** : 1.0 (Story 1.8 implémentée)
