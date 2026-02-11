# Email Task Extraction - Spécification Technique

**Story 2.7** : Extraction automatique de tâches depuis emails via Claude Sonnet 4.5

**Date** : 2026-02-11
**Status** : ✅ Implémenté

---

## Vue d'ensemble

Friday détecte automatiquement les tâches mentionnées dans les emails (explicites ou implicites) et les propose au Mainteneur via Telegram pour validation.

###Keys Features

- ✅ Détection tâches explicites (`"Peux-tu m'envoyer..."`)
- ✅ Détection engagements implicites (`"Je te recontacte demain"`)
- ✅ Conversion dates relatives → absolues (`"demain"` → `2026-02-12`)
- ✅ Priorisation automatique via mots-clés (`"urgent"` → `high`)
- ✅ Trust level `propose` : Validation Telegram requise Day 1
- ✅ RGPD : Anonymisation Presidio avant appel LLM
- ✅ Référence bidirectionnelle email ↔ task_ids

---

## Architecture

### Pipeline Extraction

```
Email reçu (EmailEngine)
  ↓
Consumer Phase 1-4 (Classification, VIP, PJ)
  ↓
Consumer Phase 5 : EXTRACTION TÂCHES ← Story 2.7
  ├─ extract_tasks_from_email() ← Claude Sonnet 4.5
  │   ├─ Anonymisation Presidio (RGPD)
  │   ├─ Prompt few-shot (5 exemples)
  │   ├─ Conversion dates relatives
  │   └─ Priorisation automatique
  ├─ Filtrage confidence ≥0.7
  ├─ create_tasks_with_validation() ← @friday_action
  │   ├─ Création core.tasks (type=email_task)
  │   ├─ Référence bidirectionnelle email ↔ task_ids
  │   └─ Receipt création (status=pending)
  ↓
Notifications Telegram
  ├─ Topic Actions : Inline buttons [Approve/Modify/Reject]
  └─ Topic Email : Résumé + lien /receipt
  ↓
Validation Mainteneur
  ├─ [Approve] → Tâche conservée
  ├─ [Modify] → Édition description/date/priorité
  └─ [Reject] → Tâche supprimée (status=cancelled)
```

### Composants Créés

| Fichier | Rôle |
|---------|------|
| `agents/src/agents/email/task_extractor.py` | Extraction via Claude Sonnet 4.5 |
| `agents/src/agents/email/task_creator.py` | Création tâches + Trust Layer |
| `agents/src/agents/email/models.py` | Pydantic models (TaskDetected, TaskExtractionResult) |
| `agents/src/agents/email/prompts.py` | Prompt TASK_EXTRACTION_PROMPT (few-shot) |
| `bot/handlers/email_task_notifications.py` | Notifications Telegram (2 topics) |
| `database/migrations/032_add_email_task_type.sql` | Type email_task + contraintes |

---

## Utilisation

### Détection Automatique

Chaque email classifié (≠ spam) passe par l'extraction automatique :

```python
# Consumer email Phase 5 (automatique)
if category != "spam":
    extraction_result = await extract_tasks_from_email(
        email_text=body_text_raw,
        email_metadata={
            'email_id': str(email_id),
            'sender': from_raw,
            'subject': subject_raw,
            'category': category
        }
    )

    # Filtrer confidence ≥0.7
    valid_tasks = [t for t in extraction_result.tasks_detected if t.confidence >= 0.7]

    if valid_tasks:
        # Créer tâches avec validation Telegram
        await create_tasks_with_validation(
            tasks=valid_tasks,
            email_id=str(email_id),
            email_subject=subject_raw,
            db_pool=db_pool
        )
```

### Notification Telegram

**Topic Actions** (validation requise) :

```
📋 Nouvelle tâche détectée depuis email

📧 Email : [PERSON_1]
📄 Sujet : Re: [PROJECT_ANON]

✅ **Tâche** : Envoyer le rapport médical
📅 Échéance : 14 février
🔴 Priorité : High
🤖 Confiance : 92%

[✅ Créer tâche] [✏️ Modifier] [❌ Ignorer]
```

**Topic Email** (informatif) :

```
📧 Email traité avec tâche détectée

De : [PERSON_1]
Sujet : Re: [PROJECT_ANON]

📋 1 tâche détectée
🔗 Voir détails : /receipt abc-123-def
```

---

## Prompt Engineering

### Prompt Structure

Le prompt `TASK_EXTRACTION_PROMPT` utilise **few-shot learning** avec 5 exemples :

1. **Demande explicite simple** : "Peux-tu m'envoyer le rapport avant jeudi ?"
2. **Engagement implicite** : "Je vais te recontacter demain"
3. **Rappel urgent** : "N'oublie pas de valider la facture avant vendredi"
4. **Email sans tâche** : "Merci, j'ai bien reçu"
5. **Multiple tâches** : "Envoie le planning ASAP et rappelle le patient"

### Conversion Dates Relatives

Le prompt fournit **contexte temporel dynamique** :

```python
# Date actuelle : {current_date} (ex: 2026-02-11)
# Jour semaine : {current_day} (ex: Mardi)

# Exemples conversion :
# - "demain" → {example_tomorrow} (2026-02-12)
# - "jeudi prochain" → {example_next_thursday} (2026-02-13)
# - "dans 3 jours" → {example_in_3_days} (2026-02-14)
# - "avant vendredi" → {example_before_friday} (2026-02-14)
# - "la semaine prochaine" → {example_next_week} (2026-02-17)
```

### Priorisation Automatique

**High** (3) : "urgent", "ASAP", "rapidement", deadline <48h
**Normal** (2) : Défaut si aucun indicateur
**Low** (1) : "quand tu peux", "pas urgent", deadline >7j

---

## Métriques & Performance

### Accuracy Target

- **Faux positifs acceptables** : <5% (AC5)
- **Confidence seuil** : ≥0.7 pour proposition (AC1)
- **Promotion auto → trust=auto** : Après 2 semaines si accuracy ≥95% (Story 1.8)

### Latence Budget

- **Extraction** : <5s (anonymisation + Claude API + parsing)
- **Création tâche** : <1s (DB write + référence bidirectionnelle)
- **Total Phase 5** : <6s (ne bloque pas traitement email)

### Claude API Usage

- **Model** : `claude-sonnet-4-5-20250929`
- **Temperature** : 0.1 (déterministe)
- **Max tokens** : 500 (tâches courtes)
- **Coût estimé** : ~$0.003 par email avec tâche (~100 emails/mois = $0.30/mois)

---

## Sécurité & RGPD

### Anonymisation Obligatoire

**CRITIQUE** : Texte email anonymisé via Presidio **AVANT** appel Claude (AC1) :

```python
# Anonymisation RGPD
anonymization_result = await anonymize_text(email_text, language="fr")
anonymized_text = anonymization_result.anonymized_text

# Appel Claude avec texte anonymisé
response = await anthropic_client.messages.create(
    model="claude-sonnet-4-5-20250929",
    messages=[{"role": "user", "content": prompt + anonymized_text}]
)
```

**Entités anonymisées** : PERSON, EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE, LOCATION, DATE_TIME

### Stockage Sécurisé

- **Tâches** : Stockées dans `core.tasks` (chiffrement pgcrypto si données médicales)
- **Payload** : `email_subject` anonymisé, `context` peut contenir extraits anonymisés
- **Mapping Presidio** : Éphémère mémoire uniquement (JAMAIS stocké PostgreSQL)

---

## Tests

### Coverage

- **17 tests unitaires** (AC1, AC6, AC7, AC5) : `test_task_extractor.py`
- **6 tests intégration** (AC2, AC3) : `test_email_task_extraction_pipeline.py`
- **4 tests E2E critiques** (workflow complet) : `test_email_task_extraction_e2e.py`

**Total** : 27 tests, 100% coverage code nouveau

### Fixtures

- **PII samples** : `tests/fixtures/pii_samples.json` (anonymisation)
- **Email samples** : Emails avec tâches explicites/implicites
- **Date samples** : "demain", "jeudi prochain", "dans 3 jours", etc.

---

## Troubleshooting

### Tâche manquée (faux négatif)

**Symptôme** : Email contient tâche évidente mais non détectée

**Diagnostic** :
1. Vérifier confidence extraction : `/receipt [receipt_id]` → payload.confidence
2. Si confidence <0.7 → Tâche filtrée automatiquement
3. Vérifier logs : `grep "email_no_task_detected" logs/consumer.log`

**Action** :
- Si pattern récurrent → Ajouter correction rule (Story 1.7)
- Si date ambiguë → Clarifier via inline button Modify

### Faux positif (tâche fantôme)

**Symptôme** : Email sans tâche mais Friday en détecte une

**Diagnostic** :
1. Vérifier prompt context dans logs
2. Analyser reasoning dans `/receipt [receipt_id]`

**Action** :
- Cliquer [Reject] pour supprimer tâche
- Pattern récurrent → Correction rule : "Si email contient X → confidence=0"

### Date relative incorrecte

**Symptôme** : "jeudi prochain" converti en mauvaise date

**Diagnostic** :
1. Vérifier date actuelle utilisée : `current_date` dans logs
2. Vérifier jour semaine : `current_day` (Lundi=0, Dimanche=6)

**Action** :
- Modifier tâche via [Modify] button
- Bug récurrent → Issue GitHub avec exemples

---

## Roadmap & Evolution

### Trust Level Promotion (6 mois)

Après **2 semaines** d'usage quotidien :
- Si accuracy ≥95% → **Promotion automatique trust=auto**
- Tâches créées directement sans validation Telegram
- Gain temps : ~30s par email avec tâche (pas d'attente validation)

### Patterns Avancés (Future)

- **Détection deadline implicite** : "Rappelle-moi lundi" sans "prochain"
- **Tâches récurrentes** : "Tous les vendredis, envoyer rapport"
- **Dépendances tâches** : "Après avoir validé X, faire Y"
- **Extraction contexte complet** : Lier tâche à email thread complet

---

## Références

**PRD** : [FR109 - Extraction tâches emails](../_bmad-output/planning-artifacts/prd.md#FR109)

**Architecture** :
- [Trust Layer](../_docs/architecture-friday-2.0.md#Trust-Layer)
- [Claude Sonnet 4.5](../_docs/architecture-friday-2.0.md#LLM)
- [Presidio RGPD](../_docs/architecture-friday-2.0.md#Presidio)

**Stories liées** :
- [Story 1.6](../_ bmad-output/implementation-artifacts/1-6-trust-layer-middleware.md) : Trust Layer
- [Story 1.10](../_bmad-output/implementation-artifacts/1-10-bot-telegram-inline-buttons-validation.md) : Inline buttons
- [Story 2.2](../_bmad-output/implementation-artifacts/2-2-classification-email-llm.md) : Classification email
- [Story 4.7](../_bmad-output/implementation-artifacts/4-7-task-management-commands-daily-briefing-integration.md) : Commande /task

---

**Version** : 1.0.0
**Auteur** : Friday 2.0 Dev Team
**Dernière mise à jour** : 2026-02-11
