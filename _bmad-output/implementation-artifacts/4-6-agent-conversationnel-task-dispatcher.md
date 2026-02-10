# Story 4.6 - Agent Conversationnel & Task Dispatcher

**Epic** : Epic 4 - Intelligence Proactive & Briefings
**Status** : ready-for-dev
**Créé le** : 2026-02-10
**Workflow** : bmad:bmm:workflows:create-story

---

## Vue d'ensemble

### Gap Critique Identifié

Le topic Telegram "Chat & Proactive" est documenté comme "conversation bidirectionnelle" mais **il n'existe actuellement AUCUNE story** implémentant l'agent conversationnel qui traite les messages texte libres de l'utilisateur.

**État actuel** : `bot/handlers/messages.py` ligne 41 contient un placeholder :
```python
# Day 1: Echo simple pour tester réception.
# Story future: Intégration avec agent Friday pour réponses intelligentes.
```

Les messages sont reçus, stockés dans `ingestion.telegram_messages`, mais seul un echo est retourné. **Aucune compréhension, aucune action.**

### Besoin Utilisateur Réel

L'utilisateur (Mainteneur) veut taper :
- **"Friday, rappelle-moi de faire X"** → Friday comprend, crée une tâche dans `core.tasks`, confirme
- **"Friday, trouve la facture du plombier"** → Friday cherche dans le graphe de connaissances, retourne le résultat
- **"Friday, résume mes emails non lus"** → Friday analyse, génère un résumé, l'envoie
- **"Friday, qu'est-ce que j'ai de prévu demain ?"** → Friday consulte l'agenda, liste les événements

C'est un flux **langage naturel → détection d'intention → exécution d'action → confirmation**.

L'infrastructure existe (table `core.tasks`, Heartbeat Engine Story 4.1, Briefing Story 4.2, middleware Trust Layer), mais **la couche conversationnelle manque**.

### Positionnement dans l'Architecture

Cette story est **le chaînon manquant entre le bot Telegram (Story 1.9) et les modules métier existants**.

```
Utilisateur (Telegram)
    ↓ Message texte libre
bot/handlers/messages.py (Story 1.9) — ACTUELLEMENT: echo uniquement
    ↓
[MANQUANT] agents/src/agents/conversational/dispatcher.py — CETTE STORY
    ↓ Détection intention
    ↓ Routing vers module approprié
agents/src/agents/*/agent.py (modules métier existants/futures)
    ↓ Exécution via @friday_action
middleware/trust.py (Story 1.6) — Trust Layer
    ↓ Receipt + validation si propose
Telegram (confirmation utilisateur)
```

---

## Description Détaillée

Implémenter l'agent conversationnel Friday capable de comprendre les intentions en langage naturel et de router vers les actions appropriées.

**Capacités principales** :
1. **Détection d'intention** via Claude Sonnet 4.5 (structured output JSON)
2. **Extraction de paramètres** depuis le langage naturel (dates, priorités, descriptions)
3. **Création de tâches manuelles** dans `core.tasks`
4. **Routing vers modules existants** (recherche, agenda, email) si applicable
5. **Confirmation conversationnelle** à l'utilisateur
6. **Intégration Trust Layer** avec niveau `propose` Day 1 → `auto` après 2 semaines si accuracy >95%

**Exemples d'interactions cibles** :

| Input utilisateur | Intention détectée | Action | Output |
|-------------------|-------------------|--------|--------|
| "Friday, rappelle-moi de faire X" | `create_task` | Crée tâche dans `core.tasks` | "Tâche créée : X (aujourd'hui, priorité normale)" |
| "Trouve la facture du plombier" | `search_document` | Recherche sémantique pgvector | "J'ai trouvé 3 résultats : [liste]" |
| "Résume mes emails non lus" | `summarize_emails` | Appel module email (future story) | "Tu as 12 emails non lus. Résumé : ..." |
| "Qu'est-ce que j'ai demain ?" | `query_agenda` | Appel module agenda (Story 7.x) | "Demain : 3 événements [liste]" |
| "Envoie un message à Jean" | `draft_email` | Module email (Story 2.5) | "Brouillon créé, que veux-tu écrire ?" |

---

## Functional Requirements

### FR-4.6.1 : Détection d'Intention (CRITIQUE)

Friday **DOIT** analyser tout message texte libre dans le topic Chat & Proactive et détecter l'intention utilisateur parmi :
- `create_task` : Créer une tâche/rappel
- `search_document` : Rechercher un document/information
- `query_agenda` : Consulter l'agenda
- `summarize_emails` : Résumer les emails non lus
- `draft_email` : Rédiger un brouillon d'email
- `general_question` : Question générale (réponse conversationnelle)
- `unknown` : Intention non comprise → demander clarification

**Implémentation** : Claude Sonnet 4.5 avec structured output JSON.

**Format de sortie** :
```json
{
  "intent": "create_task",
  "confidence": 0.92,
  "parameters": {
    "description": "Faire X",
    "due_date": "2026-02-11",
    "priority": "normal"
  },
  "reasoning": "L'utilisateur demande explicitement un rappel"
}
```

### FR-4.6.2 : Création de Tâches Manuelles (HIGH)

Friday **DOIT** pouvoir créer des tâches dans `core.tasks` à partir du langage naturel.

**Extraction de paramètres** :
- **Description** : Texte de la tâche (obligatoire)
- **Date d'échéance** : Extraite depuis "demain", "lundi prochain", "dans 3 jours", date explicite, ou NULL si non spécifiée
- **Priorité** : `high`, `normal` (défaut), `low` — extraite depuis "urgent", "important", ou défaut `normal`
- **Type** : `reminder` (défaut pour tâches conversationnelles)

**Validation** :
- Si date ambiguë → demander confirmation ("Tu veux dire demain ou lundi prochain ?")
- Si description trop courte (<5 chars) → rejeter avec message d'erreur

**Trust Level** : `propose` (Day 1) → `auto` après 2 semaines si accuracy ≥95%

### FR-4.6.3 : Confirmation Conversationnelle (MEDIUM)

Après chaque action exécutée, Friday **DOIT** envoyer une confirmation conversationnelle à l'utilisateur.

**Format de confirmation** :
```
✅ Tâche créée : "Faire X"
📅 Échéance : Demain (11 février)
⚡ Priorité : Normal
```

Pour `trust=propose`, la confirmation inclut :
```
🤖 Action en attente de validation (envoyée au topic Actions & Validations)
```

### FR-4.6.4 : Gestion des Intentions Non Comprises (LOW)

Si l'intention est `unknown` ou `confidence < 0.7`, Friday **DOIT** demander une clarification au lieu d'échouer silencieusement.

**Exemple** :
```
Utilisateur: "Friday, gloubi-boulga"
Friday: "Je n'ai pas compris ta demande. Peux-tu reformuler ?
Voici ce que je sais faire :
- Créer des tâches/rappels
- Rechercher des documents
- Consulter l'agenda
- Résumer les emails
- Rédiger des brouillons"
```

### FR-4.6.5 : Intégration avec Modules Existants (MEDIUM)

Le dispatcher **DOIT** router les intentions vers les modules métier existants lorsqu'ils sont disponibles :
- `search_document` → `agents/src/agents/archiviste/search.py` (Story 3.3)
- `query_agenda` → `agents/src/agents/agenda/query.py` (Story 7.x)
- `summarize_emails` → `agents/src/agents/email/summarizer.py` (Story 2.x — future)
- `draft_email` → `agents/src/agents/email/draft.py` (Story 2.5)

Si le module n'existe pas encore → retourner message "Fonctionnalité à venir".

### FR-4.6.6 : Receipts et Traçabilité (CRITIQUE)

Chaque action conversationnelle **DOIT** passer par le middleware `@friday_action` (Story 1.6) pour créer un receipt dans `core.action_receipts`.

**Champs obligatoires** :
- `module` : `conversational`
- `action_type` : `create_task`, `general_question`, etc.
- `input_summary` : Message utilisateur (tronqué si >200 chars)
- `output_summary` : Action exécutée (ex: "Tâche créée : Faire X")
- `confidence` : Confidence de détection d'intention (0.0-1.0)
- `reasoning` : "Intention détectée : create_task. Paramètres extraits : ..."
- `payload` : JSON avec `intent`, `parameters`, `task_id` (si applicable)

---

## Acceptance Criteria

### AC1 : Détection d'Intention Fonctionnelle

**Given** : Un message texte libre dans le topic Chat & Proactive
**When** : Friday analyse le message via Claude Sonnet 4.5
**Then** :
- L'intention est détectée avec une confidence ≥0.7
- Les paramètres pertinents sont extraits (description, date, priorité)
- Un JSON structuré est retourné avec `intent`, `confidence`, `parameters`, `reasoning`

**Test** :
```python
async def test_intent_detection_create_task():
    message = "Friday, rappelle-moi d'appeler le comptable demain"
    result = await detect_intent(message)

    assert result.intent == "create_task"
    assert result.confidence >= 0.7
    assert result.parameters["description"] == "appeler le comptable"
    assert result.parameters["due_date"] == "2026-02-11"  # demain
    assert result.parameters["priority"] == "normal"
```

### AC2 : Création de Tâche dans core.tasks

**Given** : Une intention `create_task` détectée avec paramètres valides
**When** : Friday exécute l'action via `@friday_action`
**Then** :
- Une ligne est insérée dans `core.tasks` avec `type="reminder"`, `status="pending"`
- Un receipt est créé dans `core.action_receipts` avec `trust_level="propose"` (Day 1)
- Une demande de validation est envoyée au topic Actions & Validations (inline buttons)
- Une confirmation est envoyée à l'utilisateur dans le topic Chat & Proactive

**Test** :
```python
async def test_create_task_from_conversation():
    message = "Friday, rappelle-moi d'appeler le comptable demain"
    result = await conversational_agent.process_message(message, user_id=12345)

    # Vérifier task créée
    task = await db.fetchrow("SELECT * FROM core.tasks ORDER BY created_at DESC LIMIT 1")
    assert task["name"] == "appeler le comptable"
    assert task["type"] == "reminder"
    assert task["status"] == "pending"

    # Vérifier receipt créé
    receipt = await db.fetchrow("SELECT * FROM core.action_receipts ORDER BY created_at DESC LIMIT 1")
    assert receipt["module"] == "conversational"
    assert receipt["action_type"] == "create_task"
    assert receipt["trust_level"] == "propose"
    assert receipt["status"] == "pending"

    # Vérifier confirmation envoyée
    assert result.confirmation_sent is True
```

### AC3 : Gestion des Intentions Non Comprises

**Given** : Un message ambigu ou hors-scope
**When** : Friday détecte `intent="unknown"` ou `confidence < 0.7`
**Then** :
- Friday envoie un message de clarification avec liste des capacités
- Aucune action n'est exécutée
- Aucun receipt n'est créé

**Test** :
```python
async def test_unknown_intent_clarification():
    message = "Friday, gloubi-boulga"
    result = await conversational_agent.process_message(message, user_id=12345)

    assert result.intent == "unknown"
    assert "Je n'ai pas compris" in result.response
    assert "Voici ce que je sais faire" in result.response

    # Vérifier qu'aucune action n'a été exécutée
    task_count = await db.fetchval("SELECT COUNT(*) FROM core.tasks")
    assert task_count == 0  # Aucune tâche créée
```

### AC4 : Trust Level Promotion après 2 Semaines

**Given** : Le module conversational a été utilisé pendant 2 semaines avec accuracy ≥95%
**When** : Le nightly metrics script s'exécute (Story 1.8)
**Then** :
- Le trust level de `conversational.create_task` est promu de `propose` → `auto`
- Les futures tâches créées passent directement en `status="pending"` sans validation manuelle
- Une notification est envoyée dans le topic System

**Test** :
```python
async def test_trust_promotion_after_accuracy_threshold():
    # Simuler 2 semaines d'usage avec 95% accuracy
    await simulate_conversational_usage(weeks=2, accuracy=0.95, sample_size=20)

    # Exécuter nightly metrics
    await run_nightly_metrics()

    # Vérifier promotion
    trust_level = await get_trust_level("conversational", "create_task")
    assert trust_level == "auto"

    # Vérifier notification envoyée
    notification = await db.fetchrow(
        "SELECT * FROM core.events WHERE event_type='trust.level.changed' ORDER BY created_at DESC LIMIT 1"
    )
    assert notification["payload"]["new_level"] == "auto"
```

### AC5 : Anonymisation PII avant Appel LLM

**Given** : Un message contient des données sensibles (email, téléphone, nom)
**When** : Friday traite le message
**Then** :
- Le texte est anonymisé via Presidio **AVANT** l'appel à Claude Sonnet 4.5
- Les entités PII sont remplacées par des placeholders `[EMAIL_1]`, `[PHONE_1]`, etc.
- Le mapping est stocké en mémoire éphémère (Redis TTL court)
- La confirmation utilisateur contient les vraies valeurs (dé-anonymisées)

**Test** :
```python
async def test_pii_anonymization_in_conversation():
    message = "Friday, rappelle-moi d'appeler Jean Dupont au 06 12 34 56 78"

    # Vérifier que Presidio est appelé
    with patch("agents.src.tools.anonymize.anonymize_text") as mock_anonymize:
        mock_anonymize.return_value = "Friday, rappelle-moi d'appeler [PERSON_1] au [PHONE_1]"

        result = await conversational_agent.process_message(message, user_id=12345)

        # Vérifier que le texte anonymisé est envoyé au LLM
        assert mock_anonymize.called

        # Vérifier que la confirmation contient les vraies valeurs
        assert "Jean Dupont" in result.confirmation
        assert "06 12 34 56 78" in result.confirmation
```

### AC6 : Fallback pour Modules Non Implémentés

**Given** : Une intention `search_document` est détectée mais le module Archiviste n'est pas encore implémenté
**When** : Friday tente de router vers le module
**Then** :
- Friday retourne un message "Fonctionnalité à venir : Recherche documentaire (Story 3.3)"
- Aucune erreur n'est levée
- Un log d'information est créé

**Test** :
```python
async def test_fallback_for_unimplemented_module():
    message = "Friday, trouve la facture du plombier"

    with patch("agents.src.agents.archiviste.search.search_document") as mock_search:
        mock_search.side_effect = ModuleNotFoundError("Module archiviste not implemented")

        result = await conversational_agent.process_message(message, user_id=12345)

        assert "Fonctionnalité à venir" in result.response
        assert "Story 3.3" in result.response
```

---

## Technical Specifications

### Architecture

```
agents/src/agents/conversational/
├── __init__.py
├── agent.py                    # Point d'entrée principal
├── intent_detector.py          # Détection intention via Claude
├── task_creator.py             # Création tâches dans core.tasks
├── dispatcher.py               # Routing vers modules métier
├── models.py                   # Pydantic models (Intent, TaskParams)
└── prompts.py                  # Prompts LLM structurés

bot/handlers/
└── messages.py                 # À MODIFIER : remplacer echo par appel conversational.agent
```

### Flux de Données

```
1. bot/handlers/messages.py
   ↓ Message texte reçu
   ↓ Stocker dans ingestion.telegram_messages (déjà fait)

2. conversational/agent.py : process_message()
   ↓ Anonymiser via Presidio

3. conversational/intent_detector.py : detect_intent()
   ↓ Appel Claude Sonnet 4.5 avec structured output
   ↓ Retour JSON : {intent, confidence, parameters, reasoning}

4. conversational/dispatcher.py : route_intent()
   ↓ Switch selon intent :
   ↓   - create_task → task_creator.py
   ↓   - search_document → archiviste/search.py (si existe)
   ↓   - general_question → conversational/responder.py

5. conversational/task_creator.py : create_task_from_params()
   ↓ Décorateur @friday_action(module="conversational", action="create_task")
   ↓ Insérer dans core.tasks
   ↓ Créer receipt dans core.action_receipts
   ↓ Si trust=propose → envoyer validation Telegram

6. conversational/agent.py : format_confirmation()
   ↓ Dé-anonymiser les PII
   ↓ Retourner message de confirmation

7. bot/handlers/messages.py
   ↓ Envoyer confirmation au topic Chat & Proactive
```

### Modèles Pydantic

```python
# agents/src/agents/conversational/models.py

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class Intent(BaseModel):
    """Résultat de détection d'intention."""
    intent: str = Field(..., description="Type d'intention détectée")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence (0.0-1.0)")
    parameters: dict = Field(default_factory=dict, description="Paramètres extraits")
    reasoning: str = Field(..., description="Justification de la décision")

class TaskParams(BaseModel):
    """Paramètres extraits pour création de tâche."""
    description: str = Field(..., min_length=5, description="Description de la tâche")
    due_date: Optional[datetime] = Field(None, description="Date d'échéance")
    priority: str = Field(default="normal", pattern="^(high|normal|low)$")
    task_type: str = Field(default="reminder")

class ConversationalResponse(BaseModel):
    """Réponse du module conversationnel."""
    intent: str
    confidence: float
    action_executed: bool
    confirmation: str
    receipt_id: Optional[str] = None
    validation_required: bool = False
```

### Prompts LLM

```python
# agents/src/agents/conversational/prompts.py

INTENT_DETECTION_PROMPT = """
Tu es Friday, assistant IA personnel. Analyse le message suivant et détecte l'intention utilisateur.

**Intentions possibles** :
- create_task : Créer une tâche/rappel
- search_document : Rechercher un document/information
- query_agenda : Consulter l'agenda
- summarize_emails : Résumer les emails non lus
- draft_email : Rédiger un brouillon d'email
- general_question : Question générale
- unknown : Intention non comprise

**Message utilisateur** : {message}

**Instructions** :
1. Détecte l'intention principale avec une confidence (0.0-1.0)
2. Extrais tous les paramètres pertinents (dates, noms, priorités)
3. Justifie ta décision en 1-2 phrases
4. Si ambiguïté ou confidence <0.7 → intent="unknown"

**Format de sortie (JSON strict)** :
{{
  "intent": "create_task",
  "confidence": 0.92,
  "parameters": {{
    "description": "...",
    "due_date": "YYYY-MM-DD" ou null,
    "priority": "high|normal|low"
  }},
  "reasoning": "..."
}}
"""

TASK_EXTRACTION_PROMPT = """
Extrait les paramètres d'une tâche depuis ce message :

"{message}"

**Paramètres à extraire** :
- description (str, obligatoire, min 5 chars)
- due_date (datetime, null si non spécifié)
- priority (high/normal/low, défaut=normal)

**Règles de parsing de dates** :
- "demain" → date du jour + 1
- "lundi prochain" → premier lundi après aujourd'hui
- "dans 3 jours" → date du jour + 3
- Date explicite → parser directement

**Date du jour** : {current_date}

**Format de sortie (JSON)** :
{{
  "description": "...",
  "due_date": "YYYY-MM-DD" ou null,
  "priority": "normal"
}}
"""
```

### Intégration avec bot/handlers/messages.py

**Modification de la fonction `handle_text_message`** :

```python
# bot/handlers/messages.py (lignes 36-73 à modifier)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler pour messages texte libres dans Chat & Proactive (AC3).

    Story 4.6: Intégration avec agent conversationnel Friday.
    """
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    message_id = update.message.message_id
    text = update.message.text or ""
    thread_id = update.message.message_thread_id
    timestamp = update.message.date

    logger.info(
        "Message texte reçu",
        user_id=user_id,
        chat_id=chat_id,
        thread_id=thread_id,
        text_length=len(text),
    )

    # Stocker message dans ingestion.telegram_messages
    await store_telegram_message(user_id, chat_id, thread_id, message_id, text, timestamp)

    # Story 4.6 : Appel agent conversationnel
    try:
        from agents.src.agents.conversational.agent import ConversationalAgent

        agent = ConversationalAgent()
        result = await agent.process_message(text, user_id=user_id)

        response_text = result.confirmation

        if result.validation_required:
            response_text += "\n\n🤖 Action en attente de validation (topic Actions & Validations)"

    except Exception as e:
        logger.error("Erreur agent conversationnel", error=str(e), exc_info=True)
        response_text = "Désolé, j'ai rencontré une erreur. Peux-tu réessayer ?"

    # Envoyer réponse (split si >4096 chars)
    await send_message_with_split(update, response_text)
```

### Configuration Trust Level

**Ajout dans `config/trust_levels.yaml`** :

```yaml
conversational:
  create_task: propose      # Day 1 → auto après 2 semaines si accuracy ≥95%
  general_question: auto    # Réponses conversationnelles = auto Day 1
  search_document: auto     # Recherche = auto (lecture seule)
  draft_email: propose      # Brouillon email = propose (écriture)
```

### Dépendances

**Nouvelles dépendances Python** :
```txt
# Déjà présent (Story 1.x)
anthropic>=0.25.0
asyncpg>=0.29.0
pydantic>=2.0.0
structlog>=24.0.0
python-telegram-bot>=20.0
```

Aucune nouvelle dépendance requise — toutes les libs nécessaires sont déjà installées.

---

## Implementation Tasks

### Task 1 : Créer le Module Conversational (3h)

**Subtasks** :
1. Créer `agents/src/agents/conversational/__init__.py`
2. Créer `agents/src/agents/conversational/models.py` avec Pydantic models (Intent, TaskParams, ConversationalResponse)
3. Créer `agents/src/agents/conversational/prompts.py` avec prompts LLM structurés
4. Créer structure de base `agents/src/agents/conversational/agent.py` avec méthode `process_message()`

**Acceptance** : Structure de base créée, imports fonctionnels

### Task 2 : Implémenter Intent Detection (4h)

**Subtasks** :
1. Créer `agents/src/agents/conversational/intent_detector.py`
2. Implémenter `detect_intent(message: str) -> Intent` avec appel Claude Sonnet 4.5
3. Parser le JSON structured output (format strict)
4. Gérer les erreurs d'API (retry, timeout, fallback)
5. Écrire 10 tests unitaires couvrant toutes les intentions + cas limites

**Acceptance** :
- Détection d'intention fonctionnelle avec confidence ≥0.7
- Tests passent (10/10)
- AC1 validé

### Task 3 : Implémenter Task Creator (5h)

**Subtasks** :
1. Créer `agents/src/agents/conversational/task_creator.py`
2. Implémenter `create_task_from_params(params: TaskParams) -> ActionResult` avec `@friday_action`
3. Parser les dates relatives ("demain", "lundi prochain", "dans 3 jours")
4. Insérer dans `core.tasks` avec validation de schéma
5. Gérer les erreurs de base de données (contraintes, rollback)
6. Écrire 8 tests unitaires (création, dates relatives, validation)

**Acceptance** :
- Tâches créées correctement dans `core.tasks`
- Receipts créés via Trust Layer
- Tests passent (8/8)
- AC2 validé

### Task 4 : Implémenter Dispatcher (3h)

**Subtasks** :
1. Créer `agents/src/agents/conversational/dispatcher.py`
2. Implémenter `route_intent(intent: Intent) -> ActionResult` avec switch statement
3. Router `create_task` → `task_creator.py`
4. Router `search_document`, `query_agenda`, etc. → modules métier (avec fallback si non implémenté)
5. Gérer intent `unknown` avec message de clarification
6. Écrire 6 tests unitaires (routing, fallback, unknown)

**Acceptance** :
- Routing fonctionnel vers tous les modules
- Fallback pour modules non implémentés
- Tests passent (6/6)
- AC3 et AC6 validés

### Task 5 : Intégration Presidio PII (2h)

**Subtasks** :
1. Intégrer `agents/src/tools/anonymize.py` dans `agent.py`
2. Anonymiser message **AVANT** appel LLM (Claude)
3. Dé-anonymiser dans la confirmation utilisateur
4. Stocker mapping éphémère en Redis (TTL 5min)
5. Écrire 4 tests avec PII (email, téléphone, nom, adresse)

**Acceptance** :
- PII anonymisées avant LLM
- Confirmation contient vraies valeurs
- Tests passent (4/4)
- AC5 validé

### Task 6 : Modifier bot/handlers/messages.py (2h)

**Subtasks** :
1. Remplacer echo par appel `ConversationalAgent.process_message()`
2. Gérer les erreurs avec message fallback utilisateur-friendly
3. Splitter réponses longues (>4096 chars) via `send_message_with_split()`
4. Tester en local avec bot Telegram de développement
5. Écrire 3 tests d'intégration (message → agent → réponse)

**Acceptance** :
- Bot répond intelligemment aux messages libres
- Echo retiré
- Tests passent (3/3)

### Task 7 : Configuration Trust Levels (1h)

**Subtasks** :
1. Ajouter section `conversational:` dans `config/trust_levels.yaml`
2. Définir trust levels initiaux (propose/auto selon type d'action)
3. Documenter la stratégie de promotion (2 semaines, 95% accuracy)
4. Tester chargement configuration au démarrage

**Acceptance** : Configuration trust chargée correctement, tests passent

### Task 8 : Tests End-to-End (3h)

**Subtasks** :
1. Créer `tests/integration/conversational/test_full_flow.py`
2. Test E2E : Message → Intent → Task → Receipt → Confirmation
3. Test E2E : Trust promotion après 2 semaines
4. Test E2E : PII anonymisation + dé-anonymisation
5. Test E2E : Fallback module non implémenté
6. Test E2E : Intent unknown → clarification

**Acceptance** :
- 6 tests E2E passent
- Tous les AC validés (AC1-AC6)
- Aucune régression détectée

### Task 9 : Documentation (2h)

**Subtasks** :
1. Documenter l'architecture conversational dans `agents/docs/conversational-agent-spec.md`
2. Ajouter exemples d'usage dans `docs/telegram-user-guide.md`
3. Documenter les intentions supportées et paramètres extraits
4. Ajouter troubleshooting (erreurs courantes, fallback)
5. Mettre à jour `CLAUDE.md` avec mention Story 4.6

**Acceptance** : Documentation complète et à jour

---

## Tests

### Tests Unitaires (32 tests estimés)

#### Intent Detection (10 tests)

```python
# tests/unit/conversational/test_intent_detector.py

@pytest.mark.asyncio
async def test_detect_create_task_intent():
    """Intent: create_task détectée avec paramètres."""
    message = "Friday, rappelle-moi d'appeler le comptable demain"
    result = await detect_intent(message)

    assert result.intent == "create_task"
    assert result.confidence >= 0.7
    assert result.parameters["description"] == "appeler le comptable"
    assert result.parameters["due_date"] is not None

@pytest.mark.asyncio
async def test_detect_search_document_intent():
    """Intent: search_document détectée."""
    message = "Trouve la facture du plombier"
    result = await detect_intent(message)

    assert result.intent == "search_document"
    assert result.parameters["query"] == "facture du plombier"

@pytest.mark.asyncio
async def test_detect_unknown_intent_low_confidence():
    """Intent unknown si confidence <0.7."""
    message = "gloubi-boulga truc machin"
    result = await detect_intent(message)

    assert result.intent == "unknown" or result.confidence < 0.7

@pytest.mark.asyncio
async def test_extract_relative_date_tomorrow():
    """Parsing date relative : demain."""
    message = "Fais X demain"
    result = await detect_intent(message)

    expected_date = (datetime.now() + timedelta(days=1)).date()
    assert result.parameters["due_date"] == expected_date.isoformat()

@pytest.mark.asyncio
async def test_extract_priority_high():
    """Extraction priorité : urgent/important."""
    message = "C'est urgent : appeler Jean"
    result = await detect_intent(message)

    assert result.parameters["priority"] == "high"

# ... 5 autres tests (dates complexes, intentions multiples, etc.)
```

#### Task Creator (8 tests)

```python
# tests/unit/conversational/test_task_creator.py

@pytest.mark.asyncio
async def test_create_task_success(db_pool):
    """Création tâche dans core.tasks."""
    params = TaskParams(
        description="Appeler le comptable",
        due_date=datetime(2026, 2, 11),
        priority="normal"
    )

    result = await create_task_from_params(params)

    # Vérifier task créée
    task = await db_pool.fetchrow("SELECT * FROM core.tasks WHERE id = $1", result.payload["task_id"])
    assert task["name"] == "Appeler le comptable"
    assert task["status"] == "pending"

@pytest.mark.asyncio
async def test_create_task_receipt_created(db_pool):
    """Receipt créé dans core.action_receipts."""
    params = TaskParams(description="Faire X", priority="high")
    result = await create_task_from_params(params)

    receipt = await db_pool.fetchrow(
        "SELECT * FROM core.action_receipts WHERE id = $1",
        result.payload["receipt_id"]
    )
    assert receipt["module"] == "conversational"
    assert receipt["action_type"] == "create_task"
    assert receipt["trust_level"] == "propose"

@pytest.mark.asyncio
async def test_create_task_description_too_short():
    """Rejet si description <5 chars."""
    params = TaskParams(description="X")

    with pytest.raises(ValueError, match="Description trop courte"):
        await create_task_from_params(params)

# ... 5 autres tests (dates relatives parsing, validation, erreurs DB)
```

#### Dispatcher (6 tests)

```python
# tests/unit/conversational/test_dispatcher.py

@pytest.mark.asyncio
async def test_route_create_task():
    """Routing intent create_task vers task_creator."""
    intent = Intent(
        intent="create_task",
        confidence=0.9,
        parameters={"description": "Faire X"},
        reasoning="..."
    )

    result = await route_intent(intent)

    assert result.action_type == "create_task"
    assert result.status == "pending"

@pytest.mark.asyncio
async def test_route_unknown_intent_clarification():
    """Intent unknown → message de clarification."""
    intent = Intent(intent="unknown", confidence=0.5, parameters={}, reasoning="...")

    result = await route_intent(intent)

    assert "Je n'ai pas compris" in result.output_summary
    assert "Voici ce que je sais faire" in result.output_summary

@pytest.mark.asyncio
async def test_fallback_module_not_implemented():
    """Fallback si module métier non implémenté."""
    intent = Intent(intent="search_document", confidence=0.9, parameters={"query": "test"}, reasoning="...")

    with patch("agents.src.agents.archiviste.search.search_document") as mock:
        mock.side_effect = ModuleNotFoundError()

        result = await route_intent(intent)

        assert "Fonctionnalité à venir" in result.output_summary

# ... 3 autres tests
```

#### PII Anonymisation (4 tests)

```python
# tests/unit/conversational/test_anonymization.py

@pytest.mark.asyncio
async def test_anonymize_email_in_message():
    """Email anonymisé avant LLM."""
    message = "Envoie un email à jean@example.com"

    with patch("agents.src.tools.anonymize.anonymize_text") as mock_anon:
        mock_anon.return_value = "Envoie un email à [EMAIL_1]"

        agent = ConversationalAgent()
        result = await agent.process_message(message, user_id=12345)

        # Vérifier Presidio appelé
        assert mock_anon.called

        # Vérifier confirmation contient vraie valeur
        assert "jean@example.com" in result.confirmation

# ... 3 autres tests (phone, nom, adresse)
```

#### Integration Bot (3 tests)

```python
# tests/integration/bot/test_conversational_integration.py

@pytest.mark.asyncio
async def test_message_to_agent_to_response(telegram_update):
    """Message → Agent → Réponse."""
    update = telegram_update("Friday, rappelle-moi d'appeler Jean demain")

    await handle_text_message(update, context=None)

    # Vérifier message stocké
    msg = await db.fetchrow("SELECT * FROM ingestion.telegram_messages ORDER BY timestamp DESC LIMIT 1")
    assert msg["text"] == "Friday, rappelle-moi d'appeler Jean demain"

    # Vérifier tâche créée
    task = await db.fetchrow("SELECT * FROM core.tasks ORDER BY created_at DESC LIMIT 1")
    assert task["name"] == "appeler Jean"

# ... 2 autres tests
```

### Tests E2E (6 tests)

```python
# tests/e2e/test_conversational_full_flow.py

@pytest.mark.e2e
async def test_full_flow_create_task():
    """E2E : Message → Intent → Task → Receipt → Confirmation."""
    # Simuler message Telegram
    message = "Friday, rappelle-moi d'appeler le comptable demain"

    # Process via agent
    agent = ConversationalAgent()
    result = await agent.process_message(message, user_id=12345)

    # Vérifier intent détectée
    assert result.intent == "create_task"

    # Vérifier task créée
    task = await db.fetchrow("SELECT * FROM core.tasks WHERE id = $1", result.payload["task_id"])
    assert task["name"] == "appeler le comptable"

    # Vérifier receipt créé
    receipt = await db.fetchrow("SELECT * FROM core.action_receipts WHERE id = $1", result.receipt_id)
    assert receipt["status"] == "pending"

    # Vérifier confirmation envoyée
    assert "Tâche créée" in result.confirmation

@pytest.mark.e2e
async def test_trust_promotion_after_2_weeks():
    """E2E : Trust promotion propose → auto après 2 semaines."""
    # Simuler 2 semaines d'usage avec 96% accuracy
    for i in range(20):
        await create_task_from_params(TaskParams(description=f"Task {i}"))

    # Simuler 19 validations approve, 1 reject (95% accuracy)
    # ... (logique de simulation)

    # Exécuter nightly metrics
    await run_nightly_metrics()

    # Vérifier promotion
    trust_level = await get_trust_level("conversational", "create_task")
    assert trust_level == "auto"

# ... 4 autres tests E2E
```

---

## Risks & Mitigations

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| **Détection d'intention imprécise** | Actions incorrectes exécutées | MEDIUM | Trust=propose Day 1, promotion après 2 semaines accuracy ≥95%, correction_rules appliquées |
| **Parsing de dates relatives ambigu** | Tâches créées avec mauvaise échéance | MEDIUM | Demander confirmation si ambiguïté, tests exhaustifs (20+ cas) |
| **Presidio crash pendant anonymisation** | Pipeline bloqué (fail-explicit) | LOW | Self-healing restart, alertes System, tests smoke CI |
| **Claude API timeout** | Pas de réponse à l'utilisateur | MEDIUM | Retry 3x avec backoff exponentiel, message fallback "Réessaye dans 1 minute" |
| **Collision avec autres stories** | Modifications concurrentes dans messages.py | LOW | Review code avant merge, tests d'intégration |
| **Coût API Claude élevé** | Budget dépassé (~73€/mois) | LOW | Monitoring usage via /budget (Story 1.11), alertes si >80% budget |

---

## Dependencies

### Dépend de (BLOQUANT)

- **Story 1.6** : Trust Layer Middleware (`@friday_action`, ActionResult, receipts)
- **Story 1.9** : Bot Telegram Core (handlers, routing, topics)
- **Story 1.5** : Presidio Anonymisation (PII fail-explicit)
- **Migration 003** : Table `core.tasks` existante
- **Migration 011** : Tables Trust Layer (`core.action_receipts`, `core.correction_rules`)

### Requis par (DÉPENDANCE FUTURE)

- **Story 4.1** : Heartbeat Engine (peut créer des tâches via conversational)
- **Story 2.7** : Extraction Tâches depuis Emails (utilise même `core.tasks`)
- **Story 3.3** : Recherche Sémantique (routing `search_document`)
- **Story 7.1** : Détection Événements (routing `query_agenda`)

### Modules Optionnels (Fallback si Absents)

- `agents/src/agents/archiviste/search.py` (Story 3.3) — Message "Fonctionnalité à venir"
- `agents/src/agents/agenda/query.py` (Story 7.x) — Message "Fonctionnalité à venir"
- `agents/src/agents/email/summarizer.py` (Story 2.x) — Message "Fonctionnalité à venir"

---

## Constraints

### Architecturales

1. **Modèle LLM unique** : Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) — zéro routing multi-provider (D17)
2. **Anonymisation obligatoire** : Presidio **AVANT** tout appel LLM cloud (AC5, FR-4.6.6)
3. **Trust Layer obligatoire** : Toute action passe par `@friday_action` (Story 1.6)
4. **Fail-explicit** : Si Presidio crash → STOP pipeline, alerte System (NFR7)
5. **Structured output JSON** : Claude doit retourner JSON valide parsable par Pydantic

### Performance

1. **Latence ≤30s** : Détection intention + exécution action + confirmation (NFR4, X5)
2. **Confidence ≥0.7** : Seuil minimal pour exécuter une action (AC1)
3. **Budget API** : ~45€/mois Claude (surveillance via /budget, Story 1.11)

### Opérationnelles

1. **Trust promotion manuelle** : Seul Mainteneur peut promouvoir `propose → auto` (après 2 semaines accuracy ≥95%)
2. **Anti-oscillation** : Minimum 2 semaines entre rétrogradation et nouvelle promotion (Story 1.8)
3. **Receipts persistants** : Tous les receipts sont stockés dans `core.action_receipts` (traçabilité audit)

---

## Definition of Done

### Code

- [ ] Tous les fichiers listés dans Implementation Tasks créés
- [ ] `bot/handlers/messages.py` modifié (echo remplacé par appel conversational)
- [ ] 32 tests unitaires écrits et passent (10 intent + 8 task + 6 dispatcher + 4 PII + 3 integration + 1 bot)
- [ ] 6 tests E2E écrits et passent
- [ ] Aucune régression détectée (suite de tests existante passe à 100%)
- [ ] Code review adversarial complété (minimum 10 issues trouvées et fixées)

### Documentation

- [ ] `agents/docs/conversational-agent-spec.md` créé (~500+ lignes)
- [ ] `docs/telegram-user-guide.md` mis à jour avec exemples conversational
- [ ] `CLAUDE.md` mis à jour (mention Story 4.6)
- [ ] Docstrings complètes (all public functions)
- [ ] Troubleshooting documenté (erreurs courantes, fallback)

### Validation

- [ ] AC1 validé : Détection intention fonctionnelle (confidence ≥0.7)
- [ ] AC2 validé : Tâche créée dans `core.tasks` + receipt + validation Telegram
- [ ] AC3 validé : Intent unknown → message clarification
- [ ] AC4 validé : Trust promotion après 2 semaines accuracy ≥95%
- [ ] AC5 validé : PII anonymisées avant LLM, dé-anonymisées dans confirmation
- [ ] AC6 validé : Fallback pour modules non implémentés
- [ ] Tests locaux passés (bot Telegram dev)
- [ ] Tests CI passés (GitHub Actions)

### Déploiement

- [ ] `config/trust_levels.yaml` mis à jour avec section `conversational:`
- [ ] Variables d'environnement documentées (aucune nouvelle requise)
- [ ] Migration SQL non requise (table `core.tasks` existe déjà)
- [ ] Bot redémarré en production avec nouveau code
- [ ] Test E2E en production : message → intent → task → confirmation

---

## Notes

### Pourquoi cette Story est Critique

Cette story comble un **gap architectural majeur** : le bot Telegram (Story 1.9) reçoit des messages mais ne les comprend pas. L'utilisateur s'attend à une conversation naturelle, pas à un echo.

Sans Story 4.6, Friday est un système de notifications passif. Avec Story 4.6, Friday devient un assistant conversationnel proactif capable de comprendre et d'agir.

### Stratégie de Déploiement Incrémental

**Phase 1 (Day 1)** : Uniquement `create_task` implémenté
- Intent detection fonctionnelle pour toutes les intentions
- Routing fonctionnel mais fallback pour modules non implémentés
- Utilisateur peut créer des tâches en langage naturel
- Autres intentions retournent "Fonctionnalité à venir"

**Phase 2 (Post-Story 3.3)** : Ajouter `search_document`
- Routing vers `agents/src/agents/archiviste/search.py`
- Aucune modification du dispatcher (déjà préparé)

**Phase 3 (Post-Story 7.x)** : Ajouter `query_agenda`, `draft_email`, etc.
- Routing vers modules existants
- Architecture extensible par design

### Veille Technologique

**Claude Sonnet 4.5 alternatives** : Veille mensuelle (Story 1.8, D18) surveille les concurrents (Gemini 2.5, Mistral Large 3, GPT-4 Turbo). Seuil d'alerte : concurrent >10% supérieur sur ≥3 métriques (accuracy, latence, coût, structured output quality).

**Adaptateur swappable** : `agents/src/adapters/llm.py` permet de changer de provider en 1 fichier + 1 env var.

---

## Références

- **Architecture** : `_docs/architecture-friday-2.0.md` (Steps 1-8)
- **PRD** : `_bmad-output/planning-artifacts/prd.md` (User Journeys J1-J5)
- **Epic 4** : `_bmad-output/planning-artifacts/epics-mvp.md` (Epic 4 : Intelligence Proactive)
- **Story 1.6** : Trust Layer Middleware
- **Story 1.9** : Bot Telegram Core
- **Story 1.5** : Presidio Anonymisation
- **Story 1.11** : Commandes Telegram Trust & Budget
- **Decision D17** : 100% Claude Sonnet 4.5
- **Decision D19** : pgvector remplace Qdrant Day 1

---

**Créé par** : BMAD workflow create-story
**Date** : 2026-02-10
**Story ID** : 4.6
**Estimation** : L (25 heures, 1 développeur)
