# Calendar Event Detection - Story 7.1

**Date:** 2026-02-15
**Status:** Review
**Epic:** Epic 7 - Agenda & Calendrier Multi-casquettes

---

## 📋 Vue d'ensemble

La détection d'événements automatique permet à Friday d'extraire intelligemment les rendez-vous, réunions, deadlines et conférences mentionnés dans les emails, et de les proposer pour ajout à l'agenda multi-casquettes du Mainteneur.

### Fonctionnalités clés (AC1-AC7)

- ✅ **Détection automatique** depuis emails via Claude Sonnet 4.5
- ✅ **Classification multi-casquettes** : médecin, enseignant, chercheur
- ✅ **Conversion dates relatives** : "demain" → "2026-02-16T14:30:00"
- ✅ **Anonymisation RGPD** via Presidio AVANT appel LLM
- ✅ **Few-shot learning** : 5 exemples français pour accuracy +15-20%
- ✅ **Validation Telegram** : trust=propose Day 1, inline buttons
- ✅ **Storage PostgreSQL** : knowledge.entities avec properties JSONB

---

## 🏗️ Architecture

### Flow diagram

```
┌─────────────────┐
│ Email reçu IMAP │
└────────┬────────┘
         │
         ├─> [1] Classification (Story 2.2)
         │
         ├─> [2] Anonymisation Presidio (RGPD)
         │
         ├─> [3] Extraction événements Claude Sonnet 4.5
         │        - Few-shot 5 exemples
         │        - Conversion dates relatives
         │        - Classification casquettes
         │
         ├─> [4] Filtrage confidence ≥0.75
         │
         ├─> [5] Création entité EVENT (knowledge.entities)
         │        - properties JSONB (start, end, location...)
         │        - status = proposed
         │        - Relations EVENT→EMAIL, EVENT→PARTICIPANT
         │
         ├─> [6] Publication Redis Streams (calendar:event.detected)
         │
         └─> [7] Notification Telegram Topic Actions
                  - Format message émojis 📅 📆 📍 👤 🎭
                  - Inline buttons: [Ajouter] [Modifier] [Ignorer]
```

### Modules implémentés

```
agents/src/agents/calendar/
├── __init__.py                     # Exports publics
├── event_detector.py               # Extraction événements (AC1, AC4, AC5)
├── models.py                       # Pydantic Event, EventDetectionResult
├── prompts.py                      # Few-shot examples (AC7)
└── date_parser.py                  # Helper dates relatives (AC4)

bot/handlers/
├── event_notifications.py          # Envoi notifications Topic Actions (AC3)
├── event_callbacks.py              # Callbacks inline buttons
└── event_callbacks_register.py     # Enregistrement handlers

database/migrations/
├── 036_events_support.sql          # Support EVENT entity_type (AC2)
└── 036_events_support_rollback.sql # Rollback migration

config/
└── trust_levels.yaml               # calendar.detect_event = propose

services/email_processor/
└── consumer.py                     # Intégration pipeline email (Phase 6.8)
```

---

## 🎯 Acceptance Criteria

### AC1 : Détection Automatique Événements (CRITIQUE)

**Given** un email contient un événement
**When** l'email est traité
**Then** Friday détecte l'événement avec confidence ≥0.75

**Exemples supportés :**
- Rendez-vous médicaux : "Consultation Dr Dupont le 15/02 à 14h30"
- Réunions enseignement : "Réunion pédagogique mardi prochain 10h"
- Deadlines recherche : "Soumission article avant le 28 février"
- Conférences : "Congrès cardiologie 10-12 mars 2026, Lyon"
- Événements personnels : "Dîner samedi soir 20h chez Marie"

**RGPD** : Texte email anonymisé via Presidio **AVANT** appel Claude.

### AC2 : Création Entité EVENT

**Structure PostgreSQL :**
```sql
knowledge.entities:
  - entity_type = 'EVENT'
  - properties JSONB:
    {
      "start_datetime": "2026-02-15T14:30:00",
      "end_datetime": "2026-02-15T15:00:00",
      "location": "Cabinet Dr Dupont",
      "participants": ["Dr Dupont"],
      "event_type": "medical",
      "casquette": "medecin",
      "status": "proposed",
      "confidence": 0.92
    }
```

**Relations créées :**
- `EVENT → MENTIONED_IN → EMAIL`
- `EVENT → HAS_PARTICIPANT → PERSON`
- `EVENT → LOCATED_AT → LOCATION`

**Contraintes :**
- CHECK : status IN ('proposed', 'confirmed', 'cancelled')
- CHECK : start_datetime obligatoire pour EVENT
- INDEX : idx_entities_event_date (start_datetime)
- INDEX : idx_entities_event_casquette_date (casquette + date)
- INDEX : idx_entities_event_status (status)

### AC3 : Notification Telegram Topic Actions

**Format message :**
```
📅 Nouvel événement détecté

Titre : Consultation Dr Dupont
📆 Date : Lundi 15 février 2026, 14h30-15h00
📍 Lieu : Cabinet Dr Dupont
👤 Participants : Dr Dupont
🎭 Casquette : Médecin
📧 Source : Email de Jean (10/02/2026)

Confiance : 92%

[Ajouter à l'agenda] [Modifier] [Ignorer]
```

**Inline buttons :**
- **[Ajouter]** → status proposed → confirmed + Redis calendar:event.confirmed
- **[Modifier]** → dialogue Telegram (simplifié Story 7.1, complet Story 7.3)
- **[Ignorer]** → status proposed → cancelled

**Trust Level :** `propose` Day 1 (validation requise avant confirmation).

### AC4 : Conversion Dates Relatives → Absolues

**Conversions supportées :**
| Expression | Exemple conversion (current_date=2026-02-10) |
|-----------|----------------------------------------------|
| "demain" | 2026-02-11 |
| "après-demain" | 2026-02-12 |
| "lundi prochain" | 2026-02-17 (prochain lundi) |
| "dans 3 jours" | 2026-02-13 |
| "dans 2 semaines" | 2026-02-24 |
| "fin février" | 2026-02-28 |
| "début mars" | 2026-03-01 |

**Contexte fourni au LLM :**
```json
{
  "current_date": "2026-02-10",
  "current_time": "14:30:00",
  "timezone": "Europe/Paris"
}
```

### AC5 : Classification Multi-Casquettes

**3 casquettes (FR42) :**
- **`medecin`** : Consultations, gardes, réunions service, formations médicales
- **`enseignant`** : Cours, TD, réunions pédagogiques, examens, jurys
- **`chercheur`** : Réunions labo, conférences, soumissions, séminaires

**Classification basée sur :**
- Mots-clés : "consultation" → medecin, "cours" → enseignant
- Expéditeur : email @chu.fr → medecin, @univ.fr → enseignant
- Contexte : analyse sémantique Claude

### AC6 : Extraction Participants & Lieux (NER)

**Participants :**
- Extraction via NER (spaCy-fr + GLiNER)
- Anonymisés Presidio → placeholders PERSON_1, PERSON_2
- Mapping temporaire Redis (TTL 30 min)
- Vrais noms restaurés APRÈS réponse Claude

**Lieux :**
- Types : adresse postale, établissement, salle, ville
- Stocké dans properties.location (string)
- Relation EVENT → LOCATED_AT si lieu = entité connue

### AC7 : Few-Shot Learning (5 exemples français)

**Exemples dans prompt :**
1. Rendez-vous médical simple
2. Réunion récurrente
3. Deadline sans heure précise
4. Conférence multi-jours
5. Événement personnel informel

**Impact :** Accuracy +15-20% vs zero-shot (benchmark Story 2.7).

---

## 🔧 Configuration

### Variables d'environnement requises

```bash
# Claude API
ANTHROPIC_API_KEY=sk-ant-...

# PostgreSQL
DATABASE_URL=postgresql://friday:...@localhost:5432/friday

# Redis
REDIS_URL=redis://localhost:6379/0

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_SUPERGROUP_ID=...
TOPIC_ACTIONS_ID=...

# Presidio (optionnel, valeurs par défaut OK)
PRESIDIO_ANALYZER_URL=http://presidio-analyzer:3000
PRESIDIO_ANONYMIZER_URL=http://presidio-anonymizer:3001
```

### Configuration Trust Layer

```yaml
# config/trust_levels.yaml
calendar:
  detect_event: propose  # Validation Telegram requise Day 1
```

### Migration PostgreSQL

```bash
# Appliquer migration 036
python scripts/apply_migrations.py

# Vérifier contraintes EVENT
psql friday -c "SELECT * FROM pg_constraint WHERE conname LIKE '%event%'"
```

---

## 📊 Métriques & Monitoring

### Latence

- **Extraction événement** : <5s (AC1 NFR1)
- **Pipeline complet** : <30s (email → detection → DB → Telegram)

### Accuracy

- **Confidence threshold** : ≥0.75 (AC1)
- **Target accuracy** : ≥85% sur dataset validation
- **Few-shot impact** : +15-20% vs zero-shot

### Coûts LLM

- **Model** : claude-sonnet-4-5-20250929
- **Tokens input** : ~500-800 tokens/email (prompt + few-shot + email)
- **Tokens output** : ~200-400 tokens (JSON événements)
- **Coût estimé** : ~$0.004-0.006/email (~$2-3 pour 500 emails/mois)

### Logs structurés

```json
{
  "timestamp": "2026-02-15T14:30:00Z",
  "service": "event-detector",
  "level": "INFO",
  "message": "Detection evenements terminee",
  "context": {
    "email_id": "uuid-email",
    "events_count": 2,
    "confidence_overall": 0.88,
    "processing_time_ms": 3240
  }
}
```

---

## 🧪 Tests

### Couverture

- **Tests unitaires** : 18 tests (models.py + event_detector.py)
- **Tests intégration** : 3 tests (pipeline PostgreSQL + Redis)
- **Tests E2E** : 3 tests prévus (IMAP → PostgreSQL → Telegram)
- **Coverage target** : ≥80% event_detector.py, ≥90% models.py

### Exécuter les tests

```bash
# Tests unitaires
pytest tests/unit/agents/calendar/ -v

# Tests intégration (requiert PostgreSQL test)
pytest tests/integration/calendar/ -v --db-test

# Tests migration 036
pytest tests/unit/database/test_migration_036_events.py -v

# Coverage
pytest tests/unit/agents/calendar/ --cov=agents.src.agents.calendar --cov-report=html
```

### Datasets validation

**Fichier** : `tests/fixtures/calendar_events.json` (30 emails variés)

- 10 avec dates relatives
- 10 avec participants
- 10 avec lieux
- Ground truth : événements attendus (titre, date, casquette)

---

## 🚨 Troubleshooting

### Problème : Confidence faible (<0.75)

**Symptôme :** Événements détectés mais filtrés

**Causes :**
- Email ambigu (manque date/heure précise)
- Contexte insuffisant (snippet trop court)
- Few-shot examples pas assez variés

**Solutions :**
1. Vérifier que l'email contient date + heure explicites
2. Augmenter contexte email (inclure sujet + body complet)
3. Ajouter exemples few-shot similaires dans prompts.py

### Problème : Dates mal parsées

**Symptôme :** start_datetime incorrect pour dates relatives

**Causes :**
- current_date incorrect fourni à Claude
- Expression relative ambiguë ("jeudi" sans précision)
- Timezone non pris en compte

**Solutions :**
1. Vérifier current_date passé à extract_events_from_email()
2. Ajouter contexte dans email : "jeudi prochain" vs "jeudi dernier"
3. Vérifier timezone="Europe/Paris" dans prompt

### Problème : Participants manquants

**Symptôme :** participants = [] même si mentionnés dans email

**Causes :**
- NER spaCy-fr pas installé
- Presidio anonymise participants mais mapping perdu
- Claude ne détecte pas noms dans contexte

**Solutions :**
1. Installer spaCy : `python -m spacy download fr_core_news_md`
2. Vérifier mapping Presidio retourné et restauré
3. Améliorer prompt few-shot avec exemples participants

### Problème : Événements dupliqués

**Symptôme :** Même événement créé 2x dans knowledge.entities

**Causes :**
- Consumer traite même email 2x (pas de déduplication)
- Retry consumer sans XACK

**Solutions :**
1. Vérifier déduplication consumer (account_id + message_id)
2. Vérifier XACK appelé après traitement complet
3. Ajouter contrainte UNIQUE (source_type, source_id, name) si nécessaire

### Problème : Presidio crash

**Symptôme :** NotImplementedError ou PII non anonymisées

**Causes :**
- Service Presidio down
- Texte email format invalide (encoding)
- Fail-explicit activé (CORRECT behavior)

**Solutions :**
1. Vérifier Presidio services : `curl http://presidio-analyzer:3000/health`
2. Sanitize email text AVANT Presidio (remove null bytes, fix encoding)
3. Si fail-explicit, c'est VOULU → fixer Presidio, PAS contourner

---

## 📈 Évolutions futures

### Story 7.2 : Sync Google Calendar

- Sync bidirectionnel events confirmed ↔ Google Calendar
- OAuth2 Google Calendar API
- Gestion conflits (Friday vs Google)

### Story 7.3 : Multi-Casquettes Conflits

- Détection conflits événements (même créneau, casquettes différentes)
- Suggestions résolution (déplacer, déléguer, refuser)

### Story 9.x : Événements depuis transcriptions vocales

- Détection événements depuis Plaud Note transcriptions
- Même pipeline que emails

---

## 🔗 Références

**Architecture :**
- [architecture-friday-2.0.md](../_docs/architecture-friday-2.0.md#Step-4-Exigences-Techniques-S3)
- [epics-mvp.md](../_bmad-output/planning-artifacts/epics-mvp.md#Epic-7-Story-7.1)

**Stories liées :**
- Story 1.5 : Presidio anonymisation (dépendance AC1)
- Story 1.6 : Trust Layer middleware (dépendance AC3)
- Story 1.9 : Bot Telegram + Topics (dépendance AC3)
- Story 2.2 : Classification email (intégration consumer)
- Story 6.1 : Graphe connaissances PostgreSQL (dépendance AC2)

**Décisions architecturales :**
- [Décision D17](../_docs/DECISION_LOG.md#D17) : 100% Claude Sonnet 4.5
- [Décision D19](../_docs/DECISION_LOG.md#D19) : pgvector PostgreSQL (pas Qdrant Day 1)
- [Story 1.5 AC1] : Anonymisation Presidio OBLIGATOIRE avant LLM
- [Story 2.7 AC5] : Few-shot learning +15-20% accuracy

**Code :**
- [event_detector.py](../agents/src/agents/calendar/event_detector.py)
- [models.py](../agents/src/agents/calendar/models.py)
- [prompts.py](../agents/src/agents/calendar/prompts.py)
- [consumer.py](../services/email_processor/consumer.py#L659-L729)

---

**Version** : 1.0.0 (2026-02-15)
**Auteur** : Claude Sonnet 4.5
**Status** : Production Ready (pending code review)
