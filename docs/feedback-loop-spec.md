# Feedback Loop & Correction Rules - Spécification

**Story 1.7** | **Statut** : Implémenté | **Date** : 2026-02-09

## Vue d'ensemble

Le **Feedback Loop** permet à Antonio de corriger Friday et à Friday d'apprendre automatiquement des patterns de correction via clustering sémantique.

### Cycle complet

```
Antonio corrige action
       ↓
UPDATE core.action_receipts (correction, status='corrected')
       ↓
Nightly (03h15) : Pattern Detection
       ↓
Clustering Levenshtein (≥0.85 similarité, ≥2 corrections)
       ↓
Proposition règle via Telegram (inline buttons)
       ↓
Antonio valide [Créer règle]
       ↓
INSERT core.correction_rules
       ↓
Actions futures : load_correction_rules() → injection prompt
       ↓
LLM applique règle automatiquement
```

## Algorithme Pattern Detection

### Étapes (Addendum Section 2)

1. **Récupération** : Corrections 7 jours glissants (`status='corrected'`)
2. **Groupement** : Par (module, action_type)
3. **Clustering** : Levenshtein distance pairwise
   - Seuil similarité : **0.85**
   - Minimum cluster : **2 corrections**
4. **Extraction pattern** :
   - Mots-clés récurrents (Counter, >50% occurrences)
   - Catégorie cible (parsing "X → Y", majoritaire)

### Formule similarité

```python
similarity = 1.0 - (levenshtein_distance / max_length)
```

## Format correction_rules (JSONB)

### Conditions

```json
{
  "keywords": ["urssaf", "cotisations"],
  "min_match": 1
}
```

### Output

```json
{
  "category": "finance",
  "confidence_boost": 0.1
}
```

## Commandes Telegram

### /rules list
Affiche règles actives triées par priorité.

### /rules show <id>
Détail complet règle (scope, conditions, output, hit_count).

### /rules delete <id>
Désactive règle (active=false).

## Tables SQL

### core.action_receipts
- `correction` TEXT : Texte correction Antonio
- `status` : 'auto' | 'pending' | 'approved' | 'rejected' | **'corrected'**

### core.correction_rules
- `conditions` JSONB : Conditions de match
- `output` JSONB : Output à appliquer
- `scope` : 'global' | 'module' | 'specific'
- `priority` INT : 1-100 (1 = max priorité)
- `source_receipts` UUID[] : Receipts origine
- `hit_count` INT : Nombre applications règle

### core.trust_metrics (migration 013)
- `recommended_trust_level` : Rétrogradation proposée
- `avg_confidence` FLOAT : Confidence moyenne

## Exemples

### Correction simple
Antonio : "URSSAF → finance"
→ Pattern détecté après 2-3 corrections similaires
→ Règle créée : SI keywords=[urssaf] ALORS category=finance

### Correction complexe
Antonio : "Email médical urgent → medical + priority=high"
→ Pattern multi-attributs détecté
→ Règle avec output multiple

## Troubleshooting (MED-2 fix - section étendue)

### Aucun pattern détecté (patterns = [])

**Symptômes** : Nightly log "No patterns detected"

**Causes** :
1. Moins de 2 corrections similaires (minimum cluster = 2)
2. Corrections >7 jours (fenêtre glissante)
3. Similarité <0.85 (corrections trop différentes)
4. Modules/actions différents (groupés séparément)

**Solutions** :
```sql
-- Vérifier corrections récentes
SELECT COUNT(*) FROM core.action_receipts
WHERE status='corrected' AND created_at >= NOW() - INTERVAL '7 days';

-- Voir groupement
SELECT module, action_type, COUNT(*)
FROM core.action_receipts
WHERE status='corrected' AND created_at >= NOW() - INTERVAL '7 days'
GROUP BY module, action_type;
```
- Baisser seuil à 0.80 si faux négatifs
- Vérifier module/action_type cohérents

### Proposition Telegram non reçue

**Causes** : Envvars manquantes (TELEGRAM_BOT_TOKEN, TOPIC_ACTIONS_ID, TELEGRAM_SUPERGROUP_ID)

**Solutions** :
- Vérifier logs `telegram_bot is not None`
- Re-extraire IDs : `python scripts/get_telegram_ids.py`
- Ajouter bot au supergroup

### Règle créée mais hit_count = 0

**Causes** : Conditions trop strictes, module/action incorrect, pas de `@friday_action`

**Solutions** :
- `/rules show <id>` : vérifier keywords
- Logs `TrustManager.load_correction_rules()` : "Loaded N rules"
- Vérifier decorator présent (Story 1.6)

### Performance lente (>5min)

**Causes** : >10k corrections (O(n²)), index manquant, Redis synchrone

**Solutions** :
```sql
CREATE INDEX idx_receipts_corrected_date
ON core.action_receipts(created_at)
WHERE status='corrected';
```
- Réduire fenêtre à 3 jours si >5k corrections
- Async Telegram : `disable_notification=True`

## Fichiers

- `services/feedback/pattern_detector.py` : Clustering Levenshtein
- `services/feedback/rule_proposer.py` : Propositions Telegram
- `bot/handlers/corrections.py` : Handler [Correct] button
- `bot/handlers/rules.py` : Commandes /rules CRUD
- `agents/src/middleware/trust.py` : send_telegram_validation()
- `services/metrics/nightly.py` : Intégration pattern detection (03h15)
