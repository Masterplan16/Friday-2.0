# Story 4.6 - Agent Conversationnel & Task Dispatcher — Résumé Exécutif

**Date de création** : 2026-02-10
**Status** : ready-for-dev
**Epic** : Epic 4 - Intelligence Proactive & Briefings
**Estimation** : L (25 heures)

---

## Résumé en 3 Points

1. **Gap Critique Identifié** : Le bot Telegram (Story 1.9) reçoit des messages texte libres mais ne fait qu'un echo. Il n'y a AUCUNE compréhension ni action. Cette story comble ce gap architectural majeur.

2. **Capacité Clé** : Comprendre les intentions en langage naturel ("Friday, rappelle-moi de faire X") et créer des tâches dans `core.tasks`, avec détection d'intention via Claude Sonnet 4.5 et extraction de paramètres (dates relatives, priorités).

3. **Intégration Trust Layer** : Trust level = `propose` Day 1 → `auto` après 2 semaines si accuracy ≥95%. Chaque action passe par `@friday_action` pour traçabilité complète.

---

## Contexte

### État Actuel (Placeholder)

```python
# bot/handlers/messages.py ligne 41
# Day 1: Echo simple pour tester réception.
# Story future: Intégration avec agent Friday pour réponses intelligentes.

response_text = f"Echo: {text}"  # ← PLACEHOLDER
```

Messages reçus → stockés dans DB → echo → **AUCUNE COMPRÉHENSION**.

### Besoin Utilisateur

L'utilisateur (Mainteneur) veut interagir en langage naturel :

| Input | Action Attendue |
|-------|-----------------|
| "Friday, rappelle-moi d'appeler le comptable demain" | Tâche créée dans `core.tasks` avec due_date=demain |
| "Trouve la facture du plombier" | Recherche sémantique pgvector (Story 3.3) |
| "Résume mes emails non lus" | Appel module email (Story 2.x) |
| "Qu'est-ce que j'ai demain ?" | Appel module agenda (Story 7.x) |

### Architecture Manquante

```
Utilisateur (Telegram)
    ↓ Message texte libre
bot/handlers/messages.py (Story 1.9) — ACTUELLEMENT: echo uniquement
    ↓
[MANQUANT] agents/src/agents/conversational/dispatcher.py — CETTE STORY
    ↓ Détection intention
    ↓ Routing vers module approprié
agents/src/agents/*/agent.py (modules métier)
    ↓ Exécution via @friday_action
middleware/trust.py (Story 1.6) — Trust Layer
```

---

## Fonctionnalités Principales

### 1. Détection d'Intention (FR-4.6.1)

Claude Sonnet 4.5 analyse le message et retourne JSON structuré :

```json
{
  "intent": "create_task",
  "confidence": 0.92,
  "parameters": {
    "description": "appeler le comptable",
    "due_date": "2026-02-11",
    "priority": "normal"
  },
  "reasoning": "L'utilisateur demande explicitement un rappel"
}
```

**Intentions supportées** :
- `create_task` : Créer une tâche/rappel
- `search_document` : Rechercher un document
- `query_agenda` : Consulter l'agenda
- `summarize_emails` : Résumer les emails non lus
- `draft_email` : Rédiger un brouillon d'email
- `general_question` : Question générale
- `unknown` : Non compris → clarification

### 2. Création de Tâches Manuelles (FR-4.6.2)

Extraction de paramètres depuis langage naturel :
- **Description** : Texte obligatoire (min 5 chars)
- **Date d'échéance** : "demain", "lundi prochain", "dans 3 jours", date explicite, ou NULL
- **Priorité** : `high` (urgent/important), `normal` (défaut), `low`

Insertion dans `core.tasks` avec `type="reminder"`, `status="pending"`.

### 3. Trust Layer (FR-4.6.6)

Chaque action passe par `@friday_action(module="conversational", action="create_task")` :
- Trust level = `propose` Day 1 → inline buttons validation Telegram
- Receipt créé dans `core.action_receipts`
- Promotion `propose → auto` après 2 semaines si accuracy ≥95%

### 4. Anonymisation PII (FR-4.6.5)

Message anonymisé via Presidio **AVANT** appel Claude :
```
Input:  "Friday, rappelle-moi d'appeler Jean Dupont au 06 12 34 56 78"
Anonymisé: "Friday, rappelle-moi d'appeler [PERSON_1] au [PHONE_1]"
Confirmation (dé-anonymisée): "Tâche créée : appeler Jean Dupont au 06 12 34 56 78"
```

### 5. Fallback pour Modules Non Implémentés (AC6)

Si l'intention route vers un module non encore développé :
```
Utilisateur: "Trouve la facture du plombier"
Friday: "Fonctionnalité à venir : Recherche documentaire (Story 3.3)"
```

Aucune erreur levée, log d'information créé.

---

## Acceptance Criteria (6 AC)

### AC1 : Détection d'Intention Fonctionnelle ✅

- Intention détectée avec confidence ≥0.7
- Paramètres extraits (description, date, priorité)
- JSON structuré retourné

### AC2 : Création de Tâche dans core.tasks ✅

- Ligne insérée dans `core.tasks` avec `type="reminder"`, `status="pending"`
- Receipt créé dans `core.action_receipts` avec `trust_level="propose"`
- Validation Telegram envoyée (topic Actions & Validations)
- Confirmation utilisateur envoyée (topic Chat & Proactive)

### AC3 : Gestion des Intentions Non Comprises ✅

- Intent `unknown` ou confidence <0.7 → message clarification
- Liste des capacités affichée
- Aucune action exécutée, aucun receipt créé

### AC4 : Trust Level Promotion après 2 Semaines ✅

- Après 2 semaines accuracy ≥95% → promotion `propose → auto`
- Nightly metrics script (Story 1.8) effectue la promotion
- Notification envoyée dans topic System

### AC5 : Anonymisation PII avant Appel LLM ✅

- PII anonymisées via Presidio avant Claude
- Mapping stocké en mémoire éphémère (Redis TTL court)
- Confirmation contient vraies valeurs (dé-anonymisées)

### AC6 : Fallback pour Modules Non Implémentés ✅

- Message "Fonctionnalité à venir : [nom module] (Story X.X)"
- Aucune erreur levée
- Log d'information créé

---

## Tests (38 tests)

### Tests Unitaires (32 tests)

- **Intent Detection** : 10 tests (toutes intentions + cas limites)
- **Task Creator** : 8 tests (création, dates relatives, validation)
- **Dispatcher** : 6 tests (routing, fallback, unknown)
- **PII Anonymisation** : 4 tests (email, phone, nom, adresse)
- **Integration Bot** : 3 tests (message → agent → réponse)
- **Bot Handler** : 1 test (modification messages.py)

### Tests E2E (6 tests)

1. Message → Intent → Task → Receipt → Confirmation
2. Trust promotion après 2 semaines accuracy ≥95%
3. PII anonymisation + dé-anonymisation
4. Fallback module non implémenté
5. Intent unknown → clarification
6. Dates relatives parsing (demain, lundi prochain, dans 3 jours)

---

## Implementation Tasks (9 tasks, 25h)

| Task | Subtasks | Durée |
|------|----------|-------|
| 1. Créer Module Conversational | 4 subtasks | 3h |
| 2. Implémenter Intent Detection | 5 subtasks | 4h |
| 3. Implémenter Task Creator | 6 subtasks | 5h |
| 4. Implémenter Dispatcher | 6 subtasks | 3h |
| 5. Intégration Presidio PII | 5 subtasks | 2h |
| 6. Modifier bot/handlers/messages.py | 5 subtasks | 2h |
| 7. Configuration Trust Levels | 4 subtasks | 1h |
| 8. Tests End-to-End | 6 subtasks | 3h |
| 9. Documentation | 5 subtasks | 2h |

---

## Dépendances

### Bloquantes (DOIT exister avant Story 4.6)

- **Story 1.5** : Presidio Anonymisation (PII fail-explicit)
- **Story 1.6** : Trust Layer Middleware (`@friday_action`, receipts)
- **Story 1.9** : Bot Telegram Core (handlers, topics)
- **Migration 003** : Table `core.tasks`
- **Migration 011** : Tables Trust Layer (`core.action_receipts`, `core.correction_rules`)

### Optionnelles (Fallback si absentes)

- Story 3.3 : Recherche Sémantique (routing `search_document`)
- Story 7.x : Agenda (routing `query_agenda`)
- Story 2.x : Email Summarizer (routing `summarize_emails`)

---

## Fichiers à Créer (7 fichiers)

```
agents/src/agents/conversational/
├── __init__.py
├── agent.py                    # Point d'entrée principal
├── intent_detector.py          # Détection intention via Claude
├── task_creator.py             # Création tâches dans core.tasks
├── dispatcher.py               # Routing vers modules métier
├── models.py                   # Pydantic models (Intent, TaskParams)
└── prompts.py                  # Prompts LLM structurés
```

## Fichiers à Modifier (2 fichiers)

- `bot/handlers/messages.py` : Remplacer echo par appel conversational
- `config/trust_levels.yaml` : Ajouter section `conversational:`

---

## Risques & Mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Détection d'intention imprécise | Actions incorrectes | Trust=propose Day 1, promotion après accuracy ≥95% |
| Parsing dates relatives ambigu | Tâches avec mauvaise échéance | Demander confirmation, 20+ tests |
| Presidio crash | Pipeline bloqué (fail-explicit) | Self-healing restart, alertes System |
| Claude API timeout | Pas de réponse utilisateur | Retry 3x backoff, message fallback |
| Coût API élevé | Budget dépassé | Monitoring via /budget (Story 1.11) |

---

## Pourquoi cette Story est Critique

**Sans Story 4.6** : Friday est un système de notifications passif. Le bot reçoit des messages mais ne les comprend pas.

**Avec Story 4.6** : Friday devient un assistant conversationnel capable de comprendre et d'agir. L'utilisateur peut créer des tâches en langage naturel, chercher des documents, interroger son agenda — tout cela via Telegram.

C'est le **chaînon manquant entre le bot Telegram (Story 1.9) et les modules métier**.

---

## Stratégie de Déploiement Incrémental

**Phase 1 (Day 1)** : Uniquement `create_task` implémenté
- Intent detection fonctionnelle pour toutes les intentions
- Routing avec fallback pour modules non implémentés
- Autres intentions → "Fonctionnalité à venir"

**Phase 2 (Post-Story 3.3)** : Ajouter `search_document`
- Routing vers `agents/src/agents/archiviste/search.py`
- Aucune modification du dispatcher (déjà préparé)

**Phase 3 (Post-Story 7.x)** : Ajouter `query_agenda`, `draft_email`, etc.
- Architecture extensible par design

---

## Références

- **Story complète** : `_bmad-output/implementation-artifacts/4-6-agent-conversationnel-task-dispatcher.md`
- **Architecture** : `_docs/architecture-friday-2.0.md` (Steps 1-8)
- **PRD** : `_bmad-output/planning-artifacts/prd.md` (User Journeys)
- **Epic 4** : `_bmad-output/planning-artifacts/epics-mvp.md`
- **Sprint Status** : `_bmad-output/implementation-artifacts/sprint-status.yaml`

---

**Créé par** : BMAD workflow create-story
**Date** : 2026-02-10
**Story ID** : 4.6
**Estimation** : L (25 heures)
