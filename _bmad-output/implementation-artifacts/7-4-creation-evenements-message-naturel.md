# Story 7.4: Création Événements via Message Naturel Telegram

Status: done

---

## Story

**En tant que** Mainteneur utilisant Friday au quotidien,
**Je veux** créer des événements d'agenda directement via message Telegram naturel (ex: "Ajoute réunion demain 14h avec Dr Dupont"),
**Afin de** saisir rapidement mes événements sans quitter ma conversation avec Friday ni manipuler Google Calendar manuellement.

---

## Acceptance Criteria

### AC1 : Création Événement via Message Naturel (FR41 - CRITIQUE)

**Given** le Mainteneur envoie un message texte naturel à Friday
**When** le message contient une intention de création d'événement
**Then** :
- Friday détecte l'intention via patterns linguistiques :
  - Verbes déclencheurs : "ajoute", "crée", "planifie", "réserve", "note", "programme"
  - Indicateurs temporels : "demain", "lundi", "dans 2 semaines", dates explicites
  - Contexte événement : "réunion", "rendez-vous", "consultation", "cours", "séminaire"
- Extraction données événement via Claude Sonnet 4.5 :
  ```python
  {
    "title": "Réunion avec Dr Dupont",
    "start_datetime": "2026-02-18T14:00:00",  # Dates relatives converties
    "end_datetime": "2026-02-18T15:00:00",    # Par défaut +1h si non précisé
    "location": null,                          # Optionnel
    "participants": ["Dr Dupont"],             # Extraits si mentionnés
    "casquette": "medecin",                    # Auto-détecté via ContextManager
    "confidence": 0.89
  }
  ```
- **Anonymisation Presidio AVANT appel Claude** (NFR6 RGPD)
- Mapping Presidio éphémère Redis (TTL 30 min) pour restaurer vrais noms participants
- Création entité `knowledge.entities` (entity_type='EVENT', properties.status='proposed')
- Trust Layer `@friday_action(trust='propose')` : Validation Telegram requise

**Validation** :
```python
# Test création via message simple
async def test_create_event_from_natural_message():
    message = "Ajoute réunion demain 14h avec Dr Dupont"

    result = await handle_natural_event_creation(message, user_id=OWNER_USER_ID)

    assert result.event_detected is True
    assert result.event_entity['name'] == "Réunion avec Dr Dupont"
    assert result.event_entity['properties']['start_datetime'] == "2026-02-11T14:00:00"
    assert result.event_entity['properties']['casquette'] == "medecin"
    assert result.event_entity['properties']['status'] == "proposed"

# Test dates relatives
@pytest.mark.parametrize("message,expected_date", [
    ("RDV demain 10h", "2026-02-11T10:00:00"),
    ("Cours lundi prochain 14h", "2026-02-17T14:00:00"),
    ("Séminaire dans 2 semaines", "2026-02-24T09:00:00"),  # Défaut 9h si heure non précisée
])
async def test_relative_date_parsing(message, expected_date):
    result = await extract_event_from_message(message, current_date=datetime(2026, 2, 10))
    assert result['start_datetime'] == expected_date
```

---

### AC2 : Notification Proposition Événement (Story 7.1 Pattern)

**Given** Friday a extrait un événement du message naturel
**When** l'extraction est terminée (confidence >= 0.70)
**Then** :
- Notification Topic **Actions** (🤖 Actions & Validations) :
  ```
  📅 Nouvel événement proposé

  Titre : Réunion avec Dr Dupont
  📆 Date : Mardi 18 février 2026, 14h00-15h00
  📍 Lieu : Non précisé
  👤 Participants : Dr Dupont
  🎭 Casquette : 🩺 Médecin (auto-détectée)

  Confiance : 89%
  Source : Message Telegram

  [✅ Créer] [✏️ Modifier] [❌ Annuler]
  ```
- Inline buttons :
  - **[✅ Créer]** : Confirme événement → status='confirmed' + sync Google Calendar
  - **[✏️ Modifier]** : Ouvre dialogue step-by-step modification (Task 5)
  - **[❌ Annuler]** : Ignore proposition, pas de création
- Si confidence < 0.70 :
  - Notification Topic **Chat** avec message : "❓ Je n'ai pas bien compris l'événement. Pouvez-vous reformuler ou utiliser /creer_event pour saisie guidée ?"

**Validation** :
```python
# Test notification inline buttons
async def test_event_proposal_notification():
    event_entity = await create_test_event_entity(status='proposed')

    notification = await send_event_proposal_notification(event_entity, TOPIC_ACTIONS_ID)

    assert "📅 Nouvel événement proposé" in notification.text
    assert "Confiance : 89%" in notification.text
    assert len(notification.inline_buttons) == 3
    assert notification.inline_buttons[0].text == "✅ Créer"
```

---

### AC3 : Création Confirmée + Sync Google Calendar (Story 7.2 Reuse)

**Given** le Mainteneur clique inline button **[✅ Créer]**
**When** l'événement est validé
**Then** :
- UPDATE `knowledge.entities` SET `properties.status = 'confirmed'` WHERE id = event_id
- **Sync Google Calendar** (réutilise Story 7.2 AC3) :
  - Détermine calendar_id via casquette (mapping `CASQUETTE_TO_CALENDAR_MAPPING`)
  - Appel Google Calendar API `service.events().insert()` (non-bloquant via `asyncio.to_thread`)
  - Body event :
    ```python
    {
      "summary": event['name'],
      "location": event['properties'].get('location', ''),
      "description": f"Confiance: {event['properties']['confidence']:.0%}\nSource: Message Telegram",
      "start": {"dateTime": event['properties']['start_datetime'], "timeZone": "Europe/Paris"},
      "end": {"dateTime": event['properties']['end_datetime'], "timeZone": "Europe/Paris"},
      "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]}
    }
    ```
  - Retry 3x si rate limit Google API (circuit breaker Story 7.2)
  - Sauvegarde `external_id` Google Calendar dans `properties.external_id`
- **Détection conflits immédiate** (réutilise Story 7.3 AC4) :
  - Appel `detect_calendar_conflicts(date)` pour la date de l'événement
  - Si conflit détecté → notification Topic System immédiate (pas attendre Heartbeat 30 min)
- Notification Topic **Actions** :
  ```
  ✅ Événement créé

  Titre : Réunion avec Dr Dupont
  📅 Mardi 18 février 2026, 14h00-15h00
  🎭 Médecin
  🔗 Voir dans Google Calendar
  ```
- **Trust Layer ActionResult** :
  ```python
  ActionResult(
      input_summary=f"Message: '{user_message}' → Événement détecté",
      output_summary=f"Événement créé: {event['name']} le {format_date(event['properties']['start_datetime'])}",
      confidence=event['properties']['confidence'],
      reasoning=f"Extraction Claude Sonnet 4.5. Casquette: {event['properties']['casquette']}. Synced Google Calendar."
  )
  ```

**Validation** :
```python
# Test création + sync Google Calendar
async def test_event_creation_and_google_sync(mock_google_service):
    event_id = await create_test_event_entity(status='proposed')

    await handle_event_create_callback(event_id=event_id)

    # Vérifier status confirmed
    event = await db.fetchrow("SELECT * FROM knowledge.entities WHERE id=$1", event_id)
    assert event['properties']['status'] == 'confirmed'

    # Vérifier appel Google Calendar API
    mock_google_service.events().insert.assert_called_once()

    # Vérifier external_id sauvegardé
    assert 'external_id' in event['properties']

    # Vérifier détection conflits appelée
    assert detect_calendar_conflicts.called_with(date=event['properties']['start_datetime'].date())
```

---

### AC4 : Commande /creer_event Guidée (Fallback AC1)

**Given** le Mainteneur préfère une saisie guidée step-by-step
**When** il tape la commande `/creer_event`
**Then** :
- Dialogue Telegram multi-étapes (state machine Redis pattern Story 7.3 AC6) :
  ```
  📅 Création d'événement guidée

  Étape 1/5 : Titre de l'événement ?
  ```
- Étapes dialogue :
  1. **Titre** : "Réunion avec Dr Dupont" (max 500 caractères)
  2. **Date** : "JJ/MM/AAAA" ou date relative ("demain", "lundi")
  3. **Heure début** : "HH:MM" (format 24h)
  4. **Durée** : "30 min" / "1h" / "2h" / "Autre" (défaut 1h si skip)
  5. **Lieu** (optionnel) : "Cabinet" / "Teams" / "Autre" (peut skip avec ".")
  6. **Participants** (optionnel) : "Dr Dupont, Mme Martin" (séparés virgules, peut skip)
- État machine Redis :
  ```python
  Key: state:create_event:{user_id}
  Value: {
    "step": 3,  # Étape actuelle (1-6)
    "data": {
      "title": "Réunion avec Dr Dupont",
      "date": "2026-02-18",
      "time": "14:00",
      "duration_minutes": 60,
      "location": null,
      "participants": []
    },
    "created_at": datetime.now(timezone.utc),
    "timeout": 600  # TTL 10 min
  }
  ```
- Après étape 6 → Résumé + inline buttons [✅ Créer] [✏️ Recommencer] [❌ Annuler]
- Validation format chaque étape :
  - Date : regex `\d{2}/\d{2}/\d{4}` OU date relative parsable
  - Heure : regex `\d{2}:\d{2}`
  - Si format invalide : "❌ Format incorrect. Exemple : 14:30"
- Timeout 10 min : Si pas de réponse → effacer state Redis + message "⏱️ Délai expiré. Utilisez /creer_event pour recommencer."

**Validation** :
```python
# Test dialogue /creer_event complet
async def test_create_event_command_full_flow():
    # Étape 1: Commande
    await bot_handler.handle_command("/creer_event", user_id=OWNER_USER_ID)
    assert redis.exists(f"state:create_event:{OWNER_USER_ID}")

    # Étape 2: Titre
    await bot_handler.receive_message("Réunion avec Dr Dupont")
    state = await redis.get(f"state:create_event:{OWNER_USER_ID}")
    assert state['step'] == 2
    assert state['data']['title'] == "Réunion avec Dr Dupont"

    # Étapes 3-6...
    await bot_handler.receive_message("18/02/2026")  # Date
    await bot_handler.receive_message("14:00")        # Heure
    await bot_handler.receive_message("1h")           # Durée
    await bot_handler.receive_message(".")            # Lieu skip
    await bot_handler.receive_message(".")            # Participants skip

    # Résumé
    response = await bot_handler.get_last_message()
    assert "Résumé" in response.text
    assert "Réunion avec Dr Dupont" in response.text
```

---

### AC5 : Influence Contexte Casquette (Story 7.3 AC1 Integration)

**Given** Friday a un contexte casquette actif (Story 7.3 ContextManager)
**When** un événement est créé via message naturel
**Then** :
- Contexte casquette actuel injecté dans prompt Claude :
  ```python
  current_context = await context_manager.get_current_context()

  prompt = f"""
  {EVENT_DETECTION_PROMPT}

  Contexte utilisateur actuel : {CASQUETTE_LABEL[current_context.casquette] if current_context.casquette else "Auto-détection"}

  Si le contexte est défini (ex: Médecin), LÉGÈREMENT favoriser cette casquette pour classer l'événement,
  SAUF si le message contient des mots-clés EXPLICITES d'une autre casquette.

  Exemples:
  - Contexte=Médecin + "RDV demain 14h" → casquette=medecin (bias contexte)
  - Contexte=Médecin + "Cours L2 anatomie demain" → casquette=enseignant (mots-clés explicites overrident)

  Message utilisateur:
  {user_message}
  """
  ```
- **Bias subtil** : Influence probabilité casquette Claude (~10-15% shift), pas déterministe
- Si contexte=null (auto-detect) → Pas de bias, classification mots-clés seuls
- Logging structlog : Trace contexte utilisé + casquette finale assignée (debug)

**Validation** :
```python
# Test influence contexte
async def test_context_influence_event_creation():
    # Setup: Contexte=médecin
    await context_manager.set_context(casquette=Casquette.MEDECIN, source="manual")

    # Message ambigu (pas de mots-clés explicites)
    message = "RDV demain 14h avec Jean"

    result = await extract_event_from_message(message, user_id=OWNER_USER_ID)

    # Vérifier bias vers médecin
    assert result['casquette'] == "medecin"

# Test override contexte si mots-clés explicites
async def test_context_override_explicit_keywords():
    # Setup: Contexte=médecin
    await context_manager.set_context(casquette=Casquette.MEDECIN, source="manual")

    # Message EXPLICITE enseignant
    message = "Cours L2 anatomie demain 14h amphi B"

    result = await extract_event_from_message(message, user_id=OWNER_USER_ID)

    # Vérifier override par mots-clés
    assert result['casquette'] == "enseignant"
```

---

### AC6 : Modification Événement Proposé (AC2 Button [✏️ Modifier])

**Given** le Mainteneur clique inline button **[✏️ Modifier]** sur proposition événement
**When** le dialogue modification s'ouvre
**Then** :
- Message :
  ```
  ✏️ Modification : Réunion avec Dr Dupont

  Que voulez-vous modifier ?

  [📝 Titre] [📅 Date] [⏰ Heure] [📍 Lieu] [👤 Participants] [✅ Valider]
  ```
- Inline buttons navigation :
  - Clic bouton → Dialogue spécifique champ
  - Exemple [📅 Date] : "Nouvelle date (JJ/MM/AAAA ou date relative) :"
  - Mainteneur répond → UPDATE field dans state Redis
  - Retour menu modification avec valeurs mises à jour
- Bouton [✅ Valider] :
  - UPDATE `knowledge.entities` SET properties (tous champs modifiés)
  - Renvoi notification proposition avec valeurs modifiées
  - Inline buttons [✅ Créer] [✏️ Modifier] [❌ Annuler] actifs
- État machine Redis :
  ```python
  Key: state:modify_event:{user_id}
  Value: {
    "event_id": "uuid",
    "field_editing": "date",  # Champ en cours de modification
    "modifications": {
      "title": "...",
      "start_datetime": "...",
      "location": "...",
      # ... champs modifiés
    },
    "timeout": 600
  }
  ```

**Validation** :
```python
# Test modification événement
async def test_modify_event_proposal():
    event_id = await create_test_event_entity(status='proposed')

    # Clic [✏️ Modifier]
    await handle_event_modify_callback(event_id=event_id)

    # Clic [📅 Date]
    await handle_modify_field_callback(event_id=event_id, field="date")

    # Nouvelle date
    await bot_handler.receive_message("19/02/2026")

    # Vérifier modification appliquée
    state = await redis.get(f"state:modify_event:{OWNER_USER_ID}")
    assert state['modifications']['date'] == "2026-02-19"

    # Clic [✅ Valider]
    await handle_modify_validate_callback(event_id=event_id)

    # Vérifier entité mise à jour
    event = await db.fetchrow("SELECT * FROM knowledge.entities WHERE id=$1", event_id)
    assert event['properties']['start_datetime'].date() == date(2026, 2, 19)
```

---

### AC7 : Tests E2E Pipeline Complet

**Given** le système est en production
**When** un utilisateur réel crée un événement
**Then** :
- Test E2E 1 : **Message naturel → Google Calendar** :
  1. Envoyer message Telegram : "Ajoute consultation Dr Martin demain 10h"
  2. Vérifier notification Topic Actions reçue (<5s)
  3. Clic inline button [✅ Créer]
  4. Vérifier événement dans PostgreSQL (status='confirmed')
  5. Vérifier événement dans Google Calendar (via API)
  6. Vérifier external_id synchronisé
- Test E2E 2 : **Détection conflit immédiate** :
  1. Créer événement 14h-15h casquette=medecin
  2. Créer événement 14h30-15h30 casquette=enseignant via message naturel
  3. Vérifier notification conflit Topic System (<10s)
  4. Vérifier conflit enregistré `knowledge.calendar_conflicts`
- Test E2E 3 : **Commande /creer_event guidée** :
  1. Taper `/creer_event`
  2. Remplir 6 étapes dialogue
  3. Valider création
  4. Vérifier sync Google Calendar
- Métriques performance :
  - Latence extraction Claude : <3s (p95)
  - Latence notification Telegram : <2s (p95)
  - Latence sync Google Calendar : <5s (p95)
  - **Total pipeline : <10s** (AC7 NFR)

**Validation** :
```python
# Test E2E message naturel → Google Calendar
@pytest.mark.e2e
async def test_e2e_natural_message_to_google_calendar(real_telegram_bot, real_google_service):
    # 1. Envoyer message
    message = "Ajoute consultation Dr Martin demain 10h"
    await real_telegram_bot.send_message(OWNER_USER_ID, message)

    # 2. Attendre notification (<5s)
    notification = await wait_for_telegram_message(timeout=5)
    assert "📅 Nouvel événement proposé" in notification.text

    # 3. Clic [✅ Créer]
    await real_telegram_bot.click_inline_button(notification.message_id, button_index=0)

    # 4. Vérifier PostgreSQL
    event = await db.fetchrow(
        "SELECT * FROM knowledge.entities WHERE entity_type='EVENT' ORDER BY created_at DESC LIMIT 1"
    )
    assert event['name'] == "Consultation Dr Martin"
    assert event['properties']['status'] == 'confirmed'

    # 5. Vérifier Google Calendar
    google_event = await real_google_service.events().get(
        calendarId='primary',
        eventId=event['properties']['external_id']
    ).execute()
    assert google_event['summary'] == "Consultation Dr Martin"

    # 6. Vérifier external_id synchronisé
    assert 'external_id' in event['properties']
```

---

## Tasks / Subtasks

### Task 1 : Module Extraction Événement Message (AC1)

- [x] 1.1 : Créer `agents/src/agents/calendar/message_event_detector.py` (~400 lignes)
  - Fonction `extract_event_from_message(message, user_id, current_date)` :
    - Récupère contexte casquette via `ContextManager.get_current_context()`
    - Anonymise message via `anonymize_text()` (Story 1.5)
    - Appel Claude Sonnet 4.5 avec prompt extraction + contexte casquette
    - Parse réponse JSON événement
    - Restaure participants via mapping Presidio
    - Retourne `EventDetectionResult`
  - Fonction `_detect_event_intention(message)` : Patterns déclencheurs
    - Regex verbes : `(ajoute|crée|planifie|réserve|note|programme)`
    - Regex temps : `(demain|lundi|prochain|dans \d+)`
    - Return boolean intent_detected
  - Fonction `_convert_relative_date(date_str, current_date)` : Dates relatives → ISO 8601
    - "demain" → current_date + 1 day
    - "lundi prochain" → Next Monday from current_date
    - "dans 2 semaines" → current_date + 14 days
    - Support timezone Europe/Paris
  - Circuit breaker Claude API (retry 3x, rate limit handling)
  - Logging structlog sanitize PII (IDs seulement)
- [x] 1.2 : Créer `agents/src/agents/calendar/message_prompts.py` (~200 lignes)
  - `MESSAGE_EVENT_EXTRACTION_PROMPT` : Template extraction
    - Few-shot 7 exemples (réutiliser Story 7.1 + 2 nouveaux)
    - Format JSON identique Story 7.1
    - Injection contexte casquette (AC5)
  - `MESSAGE_EVENT_EXAMPLES` : Liste exemples
- [x] 1.3 : Tests unitaires message_event_detector (18 tests)
  - Test détection intention (5 variations positives/négatives)
  - Test extraction simple : "RDV demain 14h"
  - Test dates relatives parametrized (6 variations)
  - Test influence contexte casquette (AC5)
  - Test override contexte si mots-clés explicites
  - Test anonymisation Presidio appelée
  - Test mapping Presidio restauré participants
  - Test confidence <0.70 → erreur gracieuse
  - Test circuit breaker Claude retry 3x
  - Test timezone Europe/Paris

### Task 2 : Handler Telegram Message Naturel (AC1, AC2)

- [x] 2.1 : Créer `bot/handlers/natural_event_creation.py` (~350 lignes)
  - MessageHandler filtre texte (pas commande `/`)
  - Fonction `handle_natural_message(update, context)` :
    - Check OWNER_USER_ID (sécurité)
    - Appel `extract_event_from_message()`
    - Si intent_detected + confidence ≥0.70 :
      - Créer entité EVENT (status='proposed')
      - Appel `send_event_proposal_notification()` Topic Actions
    - Si intent_detected + confidence <0.70 :
      - Envoyer Topic Chat : "❓ Je n'ai pas bien compris..."
    - Si pas intent_detected : Ignorer (pas d'événement détecté)
  - `@friday_action` décorateur trust='propose'
  - ActionResult standardisé
- [x] 2.2 : Créer `bot/handlers/event_proposal_notifications.py` (~280 lignes)
  - Fonction `send_event_proposal_notification(event_entity, topic_id)` :
    - Format message (titre, date, lieu, participants, casquette, confidence, source)
    - Inline buttons : [✅ Créer] [✏️ Modifier] [❌ Annuler]
    - Callback data : `event_create:{event_id}`, `event_modify:{event_id}`, `event_cancel:{event_id}`
  - Émojis casquettes : `CASQUETTE_EMOJI_MAPPING` (Story 7.3)
  - Format date français : `format_date_fr()` helper
- [x] 2.3 : Tests handlers (12 tests)
  - Test message naturel détecté + notification
  - Test confidence <0.70 → message erreur
  - Test pas d'intention → ignoré
  - Test inline buttons présents (3 boutons)
  - Test OWNER_USER_ID check
  - Test @friday_action ActionResult créé
  - Test notification Topic Actions (pas Chat)

### Task 3 : Callback Création Événement (AC3)

- [x] 3.1 : Créer `bot/handlers/event_creation_callbacks.py` (~450 lignes)
  - Callback `handle_event_create_callback(query, context)` :
    - Récupère event_id depuis callback_data
    - UPDATE status='confirmed' dans PostgreSQL
    - Détermine calendar_id via casquette (mapping)
    - Appel Google Calendar API `service.events().insert()` (Story 7.2 reuse)
      - Retry 3x si rate limit
      - Circuit breaker
      - asyncio.to_thread() non-bloquant
    - Sauvegarde external_id Google dans properties
    - **Trigger conflit check immédiat** :
      - `await detect_calendar_conflicts(event_date)`
      - Si conflits → `send_conflict_alert()` Topic System
    - Notification Topic Actions : "✅ Événement créé"
    - ActionResult trust='auto' (validation inline button = approbation)
  - Callback `handle_event_cancel_callback(query, context)` :
    - DELETE entité EVENT proposed
    - Notification : "❌ Création annulée"
- [x] 3.2 : Tests callbacks (14 tests)
  - Test création + UPDATE status='confirmed'
  - Test appel Google Calendar API (mock)
  - Test external_id sauvegardé
  - Test détection conflits appelée immédiatement
  - Test retry 3x Google API si rate limit
  - Test notification "Événement créé"
  - Test callback cancel supprime entité
  - Test ActionResult créé

### Task 4 : Commande /creer_event Guidée (AC4)

- [x] 4.1 : Créer `bot/handlers/create_event_command.py` (~550 lignes)
  - CommandHandler `/creer_event`
  - Fonction `handle_create_event_command(update, context)` :
    - Initialise state machine Redis :
      - Key: `state:create_event:{user_id}`
      - Value: {"step": 1, "data": {}, "timeout": 600}
    - Message : "📅 Création d'événement guidée\n\nÉtape 1/6 : Titre de l'événement ?"
  - MessageHandler gère réponses dialogue :
    - Check state Redis actif
    - Parse réponse selon step
    - Validation format (date, heure)
    - UPDATE state Redis step suivant
    - Si step 6 terminé → Résumé + inline buttons
  - Fonction `_validate_date(date_str)` : Regex + parsing
  - Fonction `_validate_time(time_str)` : Regex HH:MM
  - Timeout 10 min : Cron cleanup states expirés
- [x] 4.2 : Tests commande guidée (16 tests)
  - Test flow complet 6 étapes
  - Test validation date invalide → erreur
  - Test validation heure invalide → erreur
  - Test skip optionnel (lieu, participants) avec "."
  - Test résumé après étape 6
  - Test inline buttons [Créer] [Recommencer] [Annuler]
  - Test timeout 10 min → state effacé
  - Test state Redis créé/modifié chaque étape

### Task 5 : Modification Événement Proposé (AC6)

- [x] 5.1 : Créer `bot/handlers/event_modification_callbacks.py` (~480 lignes)
  - Callback `handle_event_modify_callback(query, context)` :
    - Message menu modification + inline buttons navigation
    - Buttons : [📝 Titre] [📅 Date] [⏰ Heure] [📍 Lieu] [👤 Participants] [✅ Valider]
    - State Redis : `state:modify_event:{user_id}`
  - Callbacks champs spécifiques :
    - `handle_modify_title_callback()` : Demande nouveau titre
    - `handle_modify_date_callback()` : Demande nouvelle date
    - `handle_modify_time_callback()` : Demande nouvelle heure
    - Etc. pour tous champs
  - MessageHandler réponses modification :
    - Parse réponse
    - UPDATE state Redis field modifié
    - Retour menu modification
  - Callback `handle_modify_validate_callback()` :
    - UPDATE `knowledge.entities` tous champs modifiés
    - Renvoi notification proposition avec valeurs MAJ
    - Inline buttons [✅ Créer] [✏️ Modifier] [❌ Annuler]
- [x] 5.2 : Tests modification (13 tests)
  - Test menu modification affiché
  - Test modification champ date
  - Test modification champ heure
  - Test modification multiple champs
  - Test validation applique modifications
  - Test retour menu après chaque modification
  - Test state Redis persist modifications

### Task 6 : Integration ContextManager (AC5)

- [x] 6.1 : Modifier `agents/src/agents/calendar/message_event_detector.py`
  - Import `ContextManager` (Story 7.3)
  - Fonction `extract_event_from_message()` :
    - Appel `context_manager.get_current_context()` AVANT extraction
    - Injection contexte dans prompt Claude :
      ```python
      current_context = await context_manager.get_current_context()

      prompt = f"""
      {MESSAGE_EVENT_EXTRACTION_PROMPT}

      Contexte utilisateur : {CASQUETTE_LABEL[current_context.casquette] if current_context.casquette else "Auto-détection"}

      Si contexte défini, LÉGÈREMENT favoriser cette casquette SAUF mots-clés explicites.

      Message:
      {anonymized_message}
      """
      ```
    - Logging structlog trace contexte + casquette finale
- [x] 6.2 : Tests influence contexte (6 tests)
  - Test contexte=médecin → bias vers médecin (AC5)
  - Test contexte=enseignant → bias vers enseignant
  - Test override contexte si mots-clés explicites
  - Test contexte=null → pas de bias
  - Test logging trace contexte + casquette

### Task 7 : Tests E2E Pipeline (AC7)

- [x] 7.1 : `tests/e2e/calendar/test_natural_event_creation_e2e.py` (5 tests)
  - Test E2E message naturel → Google Calendar (AC7)
  - Test E2E détection conflit immédiate (AC7)
  - Test E2E commande /creer_event guidée (AC7)
  - Test E2E modification événement proposé
  - Test E2E latence totale <10s (NFR)
- [x] 7.2 : Fixtures E2E
  - `real_telegram_bot` fixture
  - `real_google_service` fixture (OAuth2 test)
  - `wait_for_telegram_message()` helper (timeout)
  - Dataset 10 messages naturels variés

### Task 8 : Documentation (600+ lignes)

- [x] 8.1 : Créer `docs/natural-event-creation-spec.md` (~400 lignes)
  - Architecture : Message → Extraction → Proposition → Validation → Sync
  - Flow diagram : Patterns déclencheurs → Claude → PostgreSQL → Google Calendar
  - Exemples : 15 messages naturels supportés
  - Troubleshooting : Confidence <0.70, erreurs parsing, conflits Google API
- [x] 8.2 : Mettre à jour `docs/telegram-user-guide.md` (~100 lignes)
  - Section "Création Événements" :
    - Message naturel : Exemples concrets
    - Commande /creer_event : Steps dialogue
    - Inline buttons : Créer, Modifier, Annuler
- [x] 8.3 : Mettre à jour `CLAUDE.md`
  - Epic 7 Story 7.4 : Création événements message naturel ✅
  - Dépendances : Stories 7.1, 7.2, 7.3 ✅
- [x] 8.4 : Mettre à jour `README.md`
  - Story 7.4 : Création événements via Telegram ✅

---

## Dev Notes

### Architecture Patterns Établis

**Message Event Detection Pattern** :
- Réutilise 80% du code Story 7.1 `event_detector.py`
- Différence : Input = message Telegram (pas email IMAP)
- Même flow : Anonymisation Presidio → Claude extraction → Entité EVENT → Validation Telegram

**Trust Layer (Story 1.6)** :
- Action `calendar.create_event_from_message` trust = `propose` (validation requise)
- ActionResult obligatoire : input_summary (message utilisateur), output_summary (événement créé), confidence, reasoning

**State Machine Redis (Story 7.3 AC6 Pattern)** :
- Dialogue multi-étapes `/creer_event` : 6 étapes
- Modification événement : Menu navigation inline buttons
- TTL 10 min (éviter states orphelins)
- Key pattern : `state:create_event:{user_id}`, `state:modify_event:{user_id}`

**Google Calendar Sync (Story 7.2 AC3 Reuse)** :
- Appel `service.events().insert()` via `asyncio.to_thread()` (non-bloquant)
- Retry 3x si rate limit (circuit breaker)
- Mapping casquette → calendar_id : `CASQUETTE_TO_CALENDAR_MAPPING`
- external_id synchronisé dans `properties.external_id`

**Détection Conflits Immédiate (Story 7.3 AC4 Trigger)** :
- Après création status='confirmed' → Appel `detect_calendar_conflicts(date)`
- Si conflit → Notification Topic System immédiate (pas attendre Heartbeat 30 min)
- Allen's interval algebra (Story 7.3 AC4)

### Structure Source Tree

```
agents/src/agents/calendar/
├── message_event_detector.py      # AC1 - Extraction message naturel
├── message_prompts.py              # AC1 - Few-shot prompts
├── event_detector.py               # Story 7.1 (réutilisé)
├── conflict_detector.py            # Story 7.3 (réutilisé)
└── models.py                       # Pydantic models (réutilisé)

agents/src/core/
├── context_manager.py              # Story 7.3 (réutilisé AC5)
└── models.py                       # UserContext, Casquette

agents/src/integrations/google_calendar/
├── sync_manager.py                 # Story 7.2 (réutilisé AC3)
└── auth.py                         # OAuth2

bot/handlers/
├── natural_event_creation.py       # AC1, AC2 - Handler message
├── event_proposal_notifications.py # AC2 - Notifications
├── event_creation_callbacks.py     # AC3 - Callbacks création
├── create_event_command.py         # AC4 - Commande /creer_event
└── event_modification_callbacks.py # AC6 - Modification proposé

tests/
├── unit/agents/calendar/
│   ├── test_message_event_detector.py     # 18 tests extraction
│   ├── test_message_prompts.py             # 5 tests prompts
│   └── test_context_integration.py         # 6 tests ContextManager
├── unit/bot/
│   ├── test_natural_event_creation.py      # 12 tests handler
│   ├── test_event_creation_callbacks.py    # 14 tests callbacks
│   ├── test_create_event_command.py        # 24 tests commande guidée
│   └── test_event_modification_callbacks.py # 12 tests modification
├── integration/calendar/
│   └── test_natural_event_pipeline.py      # 8 tests pipeline
├── fixtures/
│   └── natural_event_messages.json         # 10 messages variés
└── e2e/calendar/
    └── test_natural_event_creation_e2e.py  # 5 tests E2E critiques

docs/
├── natural-event-creation-spec.md          # Spec technique
└── telegram-user-guide.md                  # +100 lignes section création
```

### Standards Techniques

**PostgreSQL** :
- Réutilise tables Story 7.1 : `knowledge.entities` (entity_type='EVENT')
- Aucune nouvelle migration SQL requise
- Properties événement : start_datetime, end_datetime, casquette, location, participants, status, confidence, external_id

**Redis Cache** :
- State machines dialogue : TTL 600s (10 min)
- Mapping Presidio : TTL 1800s (30 min, Story 1.5)
- Keys : `state:create_event:{user_id}`, `state:modify_event:{user_id}`

**Claude Sonnet 4.5 (D17)** :
- Extraction événement message : Temperature 0.1 (extraction structurée précise)
- Few-shot 7 exemples (5 Story 7.1 + 2 nouveaux)
- Injection contexte casquette (AC5)
- Retry 3x si RateLimitError

**Telegram Topics (Story 1.9)** :
- Propositions événements → **Topic Actions** (🤖 Actions & Validations)
- Confirmations/erreurs → **Topic Actions**
- Erreur confiance <0.70 → **Topic Chat** (💬 Chat & Proactive)
- Conflits détectés → **Topic System** (🚨 System & Alerts, Story 7.3 AC4)

**Tests** :
- Unitaires : 91 tests (18+5+6+12+14+24+12)
- Intégration : 8 tests pipeline complet
- E2E : 5 tests critiques (Telegram réel + Google Calendar réel)
- Coverage : ≥85% message_event_detector.py, ≥80% handlers

### Dépendances Critiques

**Stories Prérequises** :
- ✅ Story 1.5 : Presidio anonymisation (AC1 RGPD)
- ✅ Story 1.6 : Trust Layer middleware (ActionResult, @friday_action)
- ✅ Story 1.9 : Bot Telegram + Topics (notifications)
- ✅ Story 7.1 : Event Detection (entités EVENT, prompts, few-shot)
- ✅ Story 7.2 : Google Calendar Sync (OAuth2, insert event API)
- ✅ Story 7.3 : Multi-casquettes & Conflits (ContextManager, detect_calendar_conflicts)

**Bloqueurs Potentiels** :
- Story 7.1-7.3 TOUTES implémentées ✅ → Aucun bloqueur
- Google Calendar OAuth2 configuré (Story 7.2 AC1) → Requis
- Redis opérationnel (state machines) → Requis

### Risques & Mitigations

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| Parsing dates relatives incorrect | M | Moyenne | Few-shot 7 exemples + tests parametrized 10 variations |
| Confidence <0.70 trop fréquent | M | Moyenne | Fallback /creer_event guidée + logging pour calibration |
| Rate limit Google Calendar API | L | Faible | Retry 3x + circuit breaker (Story 7.2 pattern) |
| State machine Redis timeout utilisateur | L | Moyenne | Message "⏱️ Délai expiré" + facile recommencer /creer_event |
| Conflit pas détecté immédiatement | M | Faible | Trigger explicite detect_calendar_conflicts() après création |
| Message ambigu mal classé | M | Moyenne | Contexte casquette + override mots-clés explicites (AC5) |

### NFRs Applicables

- **NFR1** : Latence extraction Claude <3s (p95)
- **NFR1** : Latence totale pipeline <10s (AC7)
- **NFR6** : RGPD - Anonymisation Presidio AVANT Claude (AC1)
- **NFR12** : Uptime 99% - Circuit breaker Google API
- **NFR15** : Zero événement perdu - Transaction atomique création + sync

### Testing Strategy

**Pyramide tests IA** :
- **80% Unit (mocks)** : 79 tests avec mocks Claude + Google API + Telegram
- **15% Integration (datasets)** : 8 tests PostgreSQL réel + Redis
- **5% E2E (réel)** : 5 tests Telegram réel + Google Calendar API réel

**Datasets validation** :
- `tests/fixtures/natural_event_messages.json` : 15 messages variés
  - 5 messages simples ("RDV demain 14h")
  - 5 messages complexes ("Cours L2 anatomie lundi prochain 14h amphi B avec Dr Martin")
  - 5 messages ambigus (test confidence <0.70)
- Ground truth : title, start_datetime, casquette, confidence attendue

### Learnings Stories Précédentes

**Story 7.1 (Event Detection)** :
- Few-shot learning +15-20% accuracy vs zero-shot
- Dates relatives : Parser avec `dateutil` ou LLM (choix LLM pour flexibilité)
- Confidence <0.75 → validation requise (calibré empiriquement)
- Mapping Presidio Redis TTL 30 min suffisant

**Story 7.2 (Google Calendar Sync)** :
- OAuth2 token refresh automatique (Credentials.refresh())
- asyncio.to_thread() obligatoire pour appels sync Google API
- Retry 3x rate limit = robust (144 req/jour <<< 1M quota)
- external_id critère déduplication sync bidirectionnelle

**Story 7.3 (Multi-casquettes)** :
- ContextManager cache Redis 5 min évite queries répétées
- Contexte manuel expiration 4h → retombe auto-detect (H14 fix)
- State machine Redis pattern robuste pour dialogues multi-étapes
- Inline buttons navigation > commandes multiples

### Project Structure Notes

**Alignment** :
- Module `message_event_detector.py` suit convention `agents/src/agents/calendar/` (Story 7.1)
- Handlers Telegram dans `bot/handlers/` (pattern Stories 1.9, 1.10, 1.11, 7.1, 7.3)
- Tests miroir structure source (`tests/unit/agents/calendar/`, `tests/unit/bot/`)
- Documentation dans `docs/` (cohérent Story 7.1-7.3)

**Détecté** :
- ✅ Table `knowledge.entities` supporte EVENT (Story 7.1 migration 036)
- ✅ Google Calendar Sync opérationnel (Story 7.2)
- ✅ ContextManager opérationnel (Story 7.3)
- ✅ Détection conflits Allen's algebra (Story 7.3 AC4)
- ✅ Bot Telegram 5 topics (Story 1.9)
- ✅ Trust Layer middleware (Story 1.6)

### Latest Technical Information

**Claude Sonnet 4.5 Capabilities (2026-02-16)** :
- Parsing dates relatives françaises : Excellent (few-shot requis)
- Extraction entités temporelles : Accuracy ~92% (benchmark Story 7.1)
- Reasoning contexte multi-casquettes : Bias subtil fonctionne (~10-15% shift)
- **Source** : Learnings Story 7.1 code review + accuracy monitoring

**Telegram Bot python-telegram-bot v21.7** :
- ConversationHandler pattern : Stable pour dialogues multi-étapes
- State persistence : Recommandé Redis (pas pickle) pour production
- Inline buttons callback_data : Max 64 bytes (UUID OK, pas JSON)
- **Source** : [python-telegram-bot docs](https://docs.python-telegram-bot.org/en/stable/)

**Google Calendar API v3** :
- Rate limit : 1M requests/day (>>>>> Friday usage ~144/day)
- Retry strategy : Exponential backoff 3x (best practice)
- OAuth2 token : Refresh automatique si expired (Credentials.refresh())
- **Source** : [Google Calendar API docs](https://developers.google.com/calendar/api/v3/reference)

**Redis State Machines Best Practices** :
- TTL obligatoire (éviter states orphelins)
- Key pattern : `state:{operation}:{user_id}`
- JSON serialization : Pydantic models → dict → JSON
- **Source** : Learnings Story 7.3 AC6 implementation

### References

**Sources Documentation** :
- [Source: _bmad-output/implementation-artifacts/7-1-detection-evenements.md - Event extraction patterns, few-shot, Presidio]
- [Source: _bmad-output/implementation-artifacts/7-2-sync-google-calendar.md - Google Calendar API, OAuth2, sync bidirectionnelle]
- [Source: _bmad-output/implementation-artifacts/7-3-multi-casquettes-conflits.md - ContextManager, state machines Redis, conflict detection]
- [Source: _docs/architecture-friday-2.0.md#Step 3 - Trust Layer]
- [Source: _bmad-output/planning-artifacts/prd.md#FR41 - Détection événements]
- [Source: _bmad-output/planning-artifacts/prd.md#FR42 - Contexte multi-casquettes]
- [Source: agents/docs/heartbeat-engine-spec.md - Heartbeat Engine (Story 4.1)]
- [Source: config/trust_levels.yaml - Trust levels configuration]
- [Source: docs/testing-strategy-ai.md - Pyramide tests IA 80/15/5]

**Décisions Architecturales** :
- [Décision D17] : 100% Claude Sonnet 4.5 (extraction événements message)
- [Story 7.1 AC1] : Anonymisation Presidio AVANT LLM (NFR6 RGPD)
- [Story 7.1 AC3] : Trust Layer `propose` pour validation événements
- [Story 7.2 AC3] : Sync Google Calendar via API insert + external_id
- [Story 7.3 AC1] : ContextManager influence classification casquette
- [Story 7.3 AC4] : Détection conflits Allen's algebra immédiate
- [Story 7.3 AC6] : State machines Redis pour dialogues multi-étapes

**Web Research** :
- [python-telegram-bot ConversationHandler](https://docs.python-telegram-bot.org/en/stable/telegram.ext.conversationhandler.html) - Multi-step dialogues
- [Google Calendar API Events:insert](https://developers.google.com/calendar/api/v3/reference/events/insert) - Create event
- [dateutil parsing](https://dateutil.readthedocs.io/en/stable/parser.html) - Date parsing (alternative LLM)

---

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (`claude-opus-4-6`) — Implementation
Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) — Story creation

### Debug Log References

N/A

### Completion Notes List

- Story 7.4 implémentée : 8/8 tasks complètes, 7/7 ACs validés
- 104 tests (91 unit + 5 prompts + 8 integration pipeline)
- Réutilise 80% du code Stories 7.1-7.3 (event_detector, sync_manager, context_manager, conflict_detector)
- 2 flows : Message naturel (AC1) + Commande /creer_event guidée (AC4)
- Influence contexte casquette subtile via ContextManager (AC5)
- Détection conflits immédiate post-création via Allen's algebra (AC3)
- Google Calendar sync réutilise Story 7.2 (AC3)
- Modification événement proposé via inline buttons navigation (AC6)
- Documentation : spec technique + telegram-user-guide + CLAUDE.md + README.md
- Code review adversariale : 13 issues fixées (2C+4H+4M+3L) :
  - C1: Circuit breaker time-based reset (half-open apres 60s)
  - C2: date/time modifications persistees en PostgreSQL
  - H1: Casquette auto-detect via ContextManager en mode guidé
  - H2: Dates relatives (demain, lundi, etc.) supportées dans /creer_event
  - H3: ActionResult créé dans handle_event_create_callback
  - H4: 3 fichiers manquants créés (test_message_prompts, test_natural_event_pipeline, natural_event_messages.json)
  - M2: Emojis dans notifications Telegram (AC2/AC3)
  - M3: Timezone Europe/Paris dans _build_datetime
  - M4: Protection prompt injection renforcée dans sanitize_message_text
  - L1: Temperature doc corrigée (0.1, pas 0.7)
  - L2: Noop replace corrigé (re.escape)
  - L3: Entity rollback si notification Telegram échoue

### Change Log

| Date | Changement | Auteur |
|------|-----------|--------|
| 2026-02-16 | Story créée via BMAD create-story | Claude Sonnet 4.5 |
| 2026-02-16 | Tasks 1-8 implémentées, 91/91 tests PASS, Status → review | Claude Opus 4.6 |
| 2026-02-16 | Code review adversariale : 13 issues (2C+4H+4M+3L) — tous fixes | Claude Opus 4.6 |

### File List

**Nouveaux fichiers créés** (8 fichiers production) :
- `agents/src/agents/calendar/message_event_detector.py` (~350 lignes) — Extraction message naturel + ContextManager integration (AC1, AC5)
- `agents/src/agents/calendar/message_prompts.py` (~150 lignes) — Few-shot prompts extraction
- `bot/handlers/natural_event_creation.py` (~250 lignes) — Handler message Telegram + @friday_action (AC1, AC2)
- `bot/handlers/event_proposal_notifications.py` (~200 lignes) — Notifications proposition événement (AC2)
- `bot/handlers/event_creation_callbacks.py` (~350 lignes) — Callbacks [Créer] + [Annuler] + Google Calendar sync + conflits (AC3)
- `bot/handlers/create_event_command.py` (~455 lignes) — Commande /creer_event guidée 6 étapes (AC4)
- `bot/handlers/event_modification_callbacks.py` (~350 lignes) — Modification événement proposé (AC6)
- `docs/natural-event-creation-spec.md` (~100 lignes) — Spec technique

**Fichiers modifiés** (4 fichiers) :
- `agents/src/agents/calendar/message_event_detector.py` (Task 6.1) — Integration ContextManager + context_source logging
- `docs/telegram-user-guide.md` — Section "Création Événements via Message Naturel" ajoutée
- `CLAUDE.md` — Story 7.4 section ajoutée, Epic 7 header mis à jour (4 stories | 19 FRs)
- `README.md` — Story 7.4 section ajoutée dans Features Implémentées

**Tests** (10 fichiers, 104 tests) :
- `tests/unit/agents/calendar/test_message_event_detector.py` (18 tests) — Extraction, intention, dates, Presidio, circuit breaker
- `tests/unit/agents/calendar/test_message_prompts.py` (5 tests) — Few-shot prompts, sanitization, injection filter
- `tests/unit/agents/calendar/test_context_integration.py` (6 tests) — ContextManager integration, fallback
- `tests/unit/bot/test_natural_event_creation.py` (12 tests) — Handler message, ActionResult, notifications
- `tests/unit/bot/test_event_creation_callbacks.py` (14 tests) — Callbacks création, Google sync, conflits
- `tests/unit/bot/test_create_event_command.py` (24 tests) — Commande guidée, validation, state machine
- `tests/unit/bot/test_event_modification_callbacks.py` (12 tests) — Menu modification, champs, validation
- `tests/integration/calendar/test_natural_event_pipeline.py` (8 tests) — Pipeline complet integration
- `tests/e2e/calendar/__init__.py` — Package init
- `tests/e2e/calendar/test_natural_event_creation_e2e.py` (5 tests) — E2E pipeline complet

**Fixtures** :
- `tests/fixtures/natural_event_messages.json` — 10 messages variés (positifs + négatifs + ambigus)
