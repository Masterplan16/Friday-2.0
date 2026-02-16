# Story 7.2: Sync Google Calendar Bidirectionnelle

Status: ready-for-dev

---

## Story

**En tant que** Mainteneur,
**Je veux** que Friday synchronise bidirectionnellement mes événements avec Google Calendar,
**Afin de** avoir un agenda unifié accessible depuis tous mes appareils et permettre au Heartbeat Engine d'accéder au contexte agenda.

---

## Acceptance Criteria

### AC1 : OAuth2 Authentication Google Calendar API v3

**Given** Friday démarre pour la première fois (aucun token existant)
**When** l'utilisateur initie la synchronisation Google Calendar
**Then** :
- Friday lance le flux OAuth2 (`InstalledAppFlow`) avec les scopes Calendar appropriés
- Scopes requis :
  - `https://www.googleapis.com/auth/calendar` (lecture/écriture calendriers)
  - `https://www.googleapis.com/auth/calendar.events` (lecture/écriture événements)
- Credentials stockés dans `token.json` chiffré via SOPS/age (RGPD NFR9)
- Token refresh automatique si expiré (via `google.auth.transport.requests.Request`)
- **Fail-explicit** : Si OAuth2 échoue → `NotImplementedError` + alerte Telegram Topic System
- Variables d'environnement :
  ```bash
  GOOGLE_CLIENT_ID=<client_id>
  GOOGLE_CLIENT_SECRET=<client_secret>
  GOOGLE_CALENDAR_ENABLED=true
  ```

**Validation** :
```python
# Test OAuth2 flow complet
async def test_oauth2_authentication():
    # Simuler first-run (pas de token.json)
    auth_manager = GoogleCalendarAuth(credentials_path="test_token.json")

    # Mock InstalledAppFlow pour éviter interaction utilisateur
    with patch("google_auth_oauthlib.flow.InstalledAppFlow.run_local_server") as mock_flow:
        mock_flow.return_value = Mock(
            token="mock_token",
            refresh_token="mock_refresh",
            expiry=datetime.now() + timedelta(hours=1)
        )

        creds = await auth_manager.get_credentials()

        assert creds is not None
        assert creds.token == "mock_token"
        assert creds.refresh_token == "mock_refresh"
```

---

### AC2 : Lecture Événements Google Calendar (Multi-Calendriers)

**Given** Friday est authentifié avec Google Calendar API
**When** la synchronisation lecture démarre (cron quotidien 06:00 ou webhook Google)
**Then** :
- Friday récupère événements des **3 calendriers multi-casquettes** :
  - **Calendrier Médecin** : `calendar_id_medecin` (consultations, gardes, réunions service)
  - **Calendrier Enseignant** : `calendar_id_enseignant` (cours, examens, réunions pédagogiques)
  - **Calendrier Chercheur** : `calendar_id_chercheur` (conférences, séminaires, deadlines)
- Méthode API : `service.events().list()` avec paramètres :
  - `calendarId` : ID calendrier (depuis config `calendar_config.yaml`)
  - `timeMin` : Aujourd'hui - 7 jours (historique 1 semaine)
  - `timeMax` : Aujourd'hui + 90 jours (anticipation 3 mois)
  - `singleEvents=true` : Événements récurrents expansés
  - `orderBy='startTime'` : Tri chronologique
- Événements créés/mis à jour dans `knowledge.entities` (type='EVENT') :
  - `name` : `event['summary']`
  - `properties.start_datetime` : `event['start']['dateTime']` (ISO 8601)
  - `properties.end_datetime` : `event['end']['dateTime']`
  - `properties.location` : `event.get('location', '')`
  - `properties.casquette` : Déterminée par `calendar_id` (médecin/enseignant/chercheur)
  - `properties.status` : `"confirmed"` (vient de Google Calendar)
  - `properties.calendar_id` : ID calendrier Google
  - `properties.external_id` : `event['id']` (pour sync bidirectionnelle)
  - `source_type` : `"google_calendar"`
- Déduplication : Si `external_id` existe déjà → UPDATE au lieu de INSERT
- Transaction atomique : Toutes les entités créées/mises à jour dans 1 transaction

**Validation** :
```python
# Test lecture multi-calendriers
async def test_sync_read_multi_calendars():
    sync_manager = GoogleCalendarSync()

    # Mock API response avec 3 calendriers
    mock_events = {
        "calendar_medecin": [
            {"id": "evt1", "summary": "Consultation cardio", "start": {"dateTime": "2026-02-17T14:00:00+01:00"}},
            {"id": "evt2", "summary": "Garde urgences", "start": {"dateTime": "2026-02-18T08:00:00+01:00"}}
        ],
        "calendar_enseignant": [
            {"id": "evt3", "summary": "Cours L2 anatomie", "start": {"dateTime": "2026-02-17T10:00:00+01:00"}}
        ],
        "calendar_chercheur": [
            {"id": "evt4", "summary": "Congrès cardiologie Lyon", "start": {"dateTime": "2026-03-10T09:00:00+01:00"}}
        ]
    }

    with patch.object(sync_manager, "_fetch_calendar_events", side_effect=lambda cal_id: mock_events[cal_id]):
        await sync_manager.sync_from_google()

    # Vérifier entités créées
    events = await db.fetch("SELECT * FROM knowledge.entities WHERE source_type='google_calendar' ORDER BY created_at")
    assert len(events) == 4
    assert events[0]["name"] == "Consultation cardio"
    assert events[0]["properties"]["casquette"] == "medecin"
    assert events[1]["properties"]["casquette"] == "medecin"
    assert events[2]["properties"]["casquette"] == "enseignant"
    assert events[3]["properties"]["casquette"] == "chercheur"
```

---

### AC3 : Écriture Événements vers Google Calendar (Trust = propose)

**Given** un événement détecté par Story 7.1 est validé par le Mainteneur (inline button "Ajouter à l'agenda")
**When** le callback `handle_event_approve()` est déclenché
**Then** :
- Friday crée l'événement dans Google Calendar via `service.events().insert()` :
  - `calendarId` : Déterminé par `properties.casquette` (mapping config)
  - `body` :
    ```python
    {
        "summary": event.name,
        "location": event.properties.get("location", ""),
        "description": f"Source: {event.source_type} | Confidence: {event.confidence}",
        "start": {
            "dateTime": event.properties["start_datetime"],
            "timeZone": "Europe/Paris"
        },
        "end": {
            "dateTime": event.properties["end_datetime"],
            "timeZone": "Europe/Paris"
        },
        "attendees": [{"email": p} for p in event.properties.get("participants", []) if "@" in p],
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 30}
            ]
        }
    }
    ```
- Google Calendar API retourne `event_id` → stocké dans `properties.external_id`
- Status entité EVENT passe de `"proposed"` → `"confirmed"`
- Notification Telegram Topic Actions :
  ```
  ✅ Événement ajouté à Google Calendar (Médecin)

  Titre : Consultation Dr Dupont
  📆 Lundi 15 février 2026, 14h30-15h00
  🔗 https://calendar.google.com/calendar/event?eid=<event_id>
  ```
- Transaction atomique : UPDATE PostgreSQL + INSERT Google Calendar + Notification

**Trust Layer** : Action `calendar.sync_write` trust = `propose` Day 1 (validation requise)

**Validation** :
```python
# Test écriture événement vers Google Calendar
async def test_sync_write_to_google():
    # Créer événement local (status='proposed')
    event_id = await create_test_event(status="proposed", casquette="medecin")

    sync_manager = GoogleCalendarSync()

    # Mock Google Calendar API insert
    mock_event = {"id": "google_evt_123", "htmlLink": "https://calendar.google.com/..."}
    with patch.object(sync_manager.service.events(), "insert", return_value=Mock(execute=lambda: mock_event)):
        result = await sync_manager.write_event_to_google(event_id)

    # Vérifier entité mise à jour
    event = await db.fetchrow("SELECT * FROM knowledge.entities WHERE id=$1", event_id)
    assert event["properties"]["status"] == "confirmed"
    assert event["properties"]["external_id"] == "google_evt_123"
```

---

### AC4 : Synchronisation Bidirectionnelle (Détection Modifications)

**Given** un événement existe dans PostgreSQL ET dans Google Calendar (même `external_id`)
**When** Friday détecte une modification côté Google Calendar (heure changée, titre modifié)
**Then** :
- Friday met à jour l'entité PostgreSQL avec les nouvelles valeurs :
  - Comparaison `updated_at` Google vs PostgreSQL
  - Si Google `updated_at` > PostgreSQL → UPDATE PostgreSQL
  - Champs synchronisés : `name`, `start_datetime`, `end_datetime`, `location`
- Notification Telegram Topic Email & Communications :
  ```
  🔄 Événement modifié dans Google Calendar

  Consultation Dr Dupont
  ⏰ Heure changée : 14h30 → 15h00
  📅 Lundi 15 février 2026

  [Voir détails]
  ```
- Direction inverse : Si événement modifié dans PostgreSQL (via Telegram "Modifier") → UPDATE Google Calendar via `service.events().patch()`

**Stratégie Conflits** :
- Google Calendar = source de vérité (priorité lecture)
- Modifications PostgreSQL via Telegram → Immédiatement sync vers Google Calendar
- Last-write-wins (timestamp `updated_at`)

**Validation** :
```python
# Test sync bidirectionnelle
async def test_bidirectional_sync():
    # Créer événement dans les 2 systèmes
    event_id = await create_test_event(external_id="google_evt_123")

    sync_manager = GoogleCalendarSync()

    # Mock modification Google Calendar (heure changée)
    mock_updated_event = {
        "id": "google_evt_123",
        "summary": "Consultation Dr Dupont",
        "start": {"dateTime": "2026-02-15T15:00:00+01:00"},  # Changé de 14h30 → 15h00
        "updated": "2026-02-16T10:00:00Z"
    }

    with patch.object(sync_manager, "_fetch_calendar_events", return_value=[mock_updated_event]):
        await sync_manager.sync_from_google()

    # Vérifier entité mise à jour
    event = await db.fetchrow("SELECT * FROM knowledge.entities WHERE id=$1", event_id)
    assert event["properties"]["start_datetime"] == "2026-02-15T15:00:00+01:00"
```

---

### AC5 : Configuration Multi-Calendriers (calendar_config.yaml)

**Given** Friday démarre avec synchronisation Google Calendar activée
**When** le système lit la configuration calendriers
**Then** :
- Fichier `config/calendar_config.yaml` existe avec structure :
  ```yaml
  google_calendar:
    enabled: true
    sync_interval_minutes: 30  # Sync toutes les 30 min
    calendars:
      - id: "primary"
        name: "Calendrier principal"
        casquette: "medecin"
        color: "#ff0000"
      - id: "<calendar_id_enseignant>"
        name: "Enseignement"
        casquette: "enseignant"
        color: "#00ff00"
      - id: "<calendar_id_chercheur>"
        name: "Recherche"
        casquette: "chercheur"
        color: "#0000ff"
    sync_range:
      past_days: 7
      future_days: 90
    default_reminders:
      - method: "popup"
        minutes: 30
  ```
- Configuration chargée au démarrage via Pydantic `BaseSettings`
- Validation : Au moins 1 calendrier configuré, sinon erreur au démarrage
- **Fail-fast** : Si `calendar_id` invalide → alerte System au démarrage

**Validation** :
```python
# Test configuration multi-calendriers
def test_calendar_config_validation():
    config = CalendarConfig.from_yaml("config/calendar_config.yaml")

    assert config.google_calendar.enabled is True
    assert len(config.google_calendar.calendars) == 3
    assert config.google_calendar.calendars[0].casquette == "medecin"
    assert config.google_calendar.calendars[1].casquette == "enseignant"
    assert config.google_calendar.calendars[2].casquette == "chercheur"
    assert config.google_calendar.sync_interval_minutes == 30
```

---

### AC6 : Heartbeat Engine Context Provider (Integration Story 4.1)

**Given** le Heartbeat Engine démarre une phase de contexte (Story 4.1)
**When** le `ContextProvider` demande les événements agenda du jour
**Then** :
- Module `agents/src/core/context.py` appel `calendar_manager.get_todays_events()` :
  ```python
  async def get_todays_events(casquette: str | None = None) -> list[Event]:
      query = """
          SELECT * FROM knowledge.entities
          WHERE entity_type='EVENT'
            AND (properties->>'start_datetime')::timestamptz::date = CURRENT_DATE
            AND (properties->>'status') = 'confirmed'
      """
      if casquette:
          query += f" AND (properties->>'casquette') = '{casquette}'"

      query += " ORDER BY (properties->>'start_datetime')::timestamptz ASC"

      rows = await db.fetch(query)
      return [Event.from_db(row) for row in rows]
  ```
- Retour : Liste événements du jour (start_datetime entre 00:00 et 23:59)
- Filtrage optionnel par casquette (ex: contexte "médecin" → seulement événements médicaux)
- Utilisé par Briefing Matinal (Story 4.2) : "Aujourd'hui : 3 consultations, 1 réunion pédagogique"

**Validation** :
```python
# Test ContextProvider événements
async def test_context_provider_todays_events():
    # Créer événements test (2 aujourd'hui, 1 demain)
    await create_test_event(start="2026-02-16T10:00:00", casquette="medecin")
    await create_test_event(start="2026-02-16T14:00:00", casquette="enseignant")
    await create_test_event(start="2026-02-17T10:00:00", casquette="chercheur")  # Demain

    context_provider = ContextProvider()
    events = await context_provider.get_todays_events()

    assert len(events) == 2  # Seulement événements du jour
    assert events[0].properties["casquette"] == "medecin"
    assert events[1].properties["casquette"] == "enseignant"
```

---

### AC7 : Webhook Google Calendar Push Notifications (Optionnel - Temps Réel)

**Given** Friday veut recevoir notifications en temps réel des modifications Google Calendar
**When** un événement est créé/modifié/supprimé dans Google Calendar
**Then** :
- Friday utilise `service.events().watch()` pour s'abonner aux notifications :
  ```python
  channel = {
      "id": str(uuid.uuid4()),
      "type": "web_hook",
      "address": "https://friday-vps.tailscale.net/api/v1/webhooks/google-calendar"
  }
  watch_response = service.events().watch(calendarId=calendar_id, body=channel).execute()
  ```
- Webhook endpoint FastAPI `POST /api/v1/webhooks/google-calendar` :
  - Reçoit notification Google avec `X-Goog-Resource-State` header
  - États : `sync`, `exists`, `not_exists`
  - Déclenche sync incrémentale (fetch uniquement événements modifiés via `syncToken`)
- **Sécurité** : Valider `X-Goog-Channel-Token` (secret partagé)
- Fallback : Si webhook échoue → sync polling quotidien (cron 06:00)

**Note** : Webhook optionnel Day 1, peut être activé plus tard via `GOOGLE_CALENDAR_WEBHOOK_ENABLED=true`

---

## Tasks / Subtasks

### Task 1 : OAuth2 Authentication Manager (AC1)

- [ ] 1.1 : Créer `agents/src/integrations/google_calendar/auth.py` (200 lignes)
  - Classe `GoogleCalendarAuth` avec méthodes :
    - `get_credentials()` : Charge token.json OU lance OAuth2 flow
    - `refresh_credentials()` : Refresh token si expiré
    - `save_credentials()` : Sauvegarde token.json chiffré (SOPS)
  - Scopes : `calendar`, `calendar.events`
  - Gestion erreurs : `RefreshError`, `InvalidClientSecretsError`
  - Fail-explicit : `NotImplementedError` si OAuth2 échoue
- [ ] 1.2 : Créer `config/google_client_secret.json.enc` (chiffré SOPS/age)
  - Télécharger depuis Google Cloud Console
  - Chiffrer via `sops -e config/google_client_secret.json > config/google_client_secret.json.enc`
  - JAMAIS commit version non chiffrée (`.gitignore`)
- [ ] 1.3 : Variables d'environnement `.env.enc` :
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_CLIENT_SECRET`
  - `GOOGLE_CALENDAR_ENABLED=true`
- [ ] 1.4 : Tests unitaires OAuth2 (5 tests)
  - Test first-run OAuth2 flow (mock `InstalledAppFlow`)
  - Test token refresh automatique
  - Test credentials expirées → re-authentication
  - Test SOPS decrypt token.json
  - Test fail-explicit si client_secret invalide

### Task 2 : Configuration Multi-Calendriers (AC5)

- [ ] 2.1 : Créer `config/calendar_config.yaml` (template)
  - 3 calendriers : médecin, enseignant, chercheur
  - Sync interval 30 min
  - Sync range : -7 jours / +90 jours
  - Default reminders : popup 30 min
- [ ] 2.2 : Créer `agents/src/integrations/google_calendar/config.py` (Pydantic models)
  - `CalendarSettings` : id, name, casquette, color
  - `GoogleCalendarConfig` : enabled, sync_interval, calendars[], sync_range
  - Validation : Au moins 1 calendrier, casquettes valides
- [ ] 2.3 : Charger config au démarrage (fail-fast si invalide)
- [ ] 2.4 : Tests configuration (3 tests)
  - Test chargement YAML valide
  - Test validation 3 calendriers
  - Test fail-fast si aucun calendrier

### Task 3 : Module Sync Google Calendar (AC2, AC3, AC4)

- [ ] 3.1 : Créer `agents/src/integrations/google_calendar/sync_manager.py` (500 lignes)
  - Classe `GoogleCalendarSync` avec méthodes :
    - `sync_from_google()` : Lecture événements Google → PostgreSQL (AC2)
    - `write_event_to_google(event_id)` : Écriture PostgreSQL → Google Calendar (AC3)
    - `sync_bidirectional()` : Détection modifications + update (AC4)
    - `_fetch_calendar_events(calendar_id)` : Appel API `events().list()`
    - `_create_or_update_event(event_data)` : Upsert PostgreSQL (déduplication)
    - `_detect_conflicts()` : Comparaison timestamps `updated_at`
  - Build service : `build('calendar', 'v3', credentials=creds)`
  - Gestion erreurs : `HttpError` (rate limit, quota exceeded)
  - Retry automatique (3x) si erreur réseau (NFR17)
- [ ] 3.2 : Créer `agents/src/integrations/google_calendar/models.py` (Pydantic models)
  - `GoogleCalendarEvent` : summary, location, start, end, attendees, id
  - `SyncResult` : events_created, events_updated, errors[]
- [ ] 3.3 : Intégration callback Story 7.1 `handle_event_approve()` :
  - Appeler `sync_manager.write_event_to_google(event_id)`
  - Notification Telegram Topic Actions après succès
- [ ] 3.4 : Logging structlog (sanitize PII)
- [ ] 3.5 : Tests unitaires sync (12 tests)
  - Test lecture multi-calendriers (AC2)
  - Test écriture événement vers Google (AC3)
  - Test déduplication `external_id` (UPDATE au lieu INSERT)
  - Test sync bidirectionnelle (Google modified → PostgreSQL update) (AC4)
  - Test sync inverse (PostgreSQL modified → Google update)
  - Test gestion conflits (last-write-wins)
  - Test retry RateLimitError
  - Test fail-explicit si OAuth2 invalide
  - Test mapping casquette → calendar_id
  - Test transaction atomique rollback
  - Test événements récurrents expansés
  - Test timezone Europe/Paris

### Task 4 : Cron Job Sync Quotidien

- [ ] 4.1 : Créer `services/calendar_sync/worker.py` (daemon sync)
  - Sync toutes les 30 min (depuis `calendar_config.yaml`)
  - Appel `sync_manager.sync_bidirectional()` (lecture + écriture)
  - Healthcheck : Redis key `calendar:last_sync` (TTL 1h)
  - Alerte System si sync échoue 3x consécutives
- [ ] 4.2 : Docker Compose service `friday-calendar-sync` :
  ```yaml
  friday-calendar-sync:
    build:
      context: ./services/calendar_sync
    restart: unless-stopped
    depends_on:
      - postgres
      - redis
    env_file: .env
    networks:
      - friday-network
  ```
- [ ] 4.3 : n8n workflow `calendar-sync.json` (backup cron quotidien 06:00)
  - Trigger : Cron 0 6 * * *
  - Action : HTTP POST `/api/v1/calendar/sync`
  - Notification Telegram System si échec
- [ ] 4.4 : Tests intégration daemon (3 tests)
  - Test cron sync 30 min
  - Test healthcheck Redis
  - Test alerte après 3 échecs

### Task 5 : ContextProvider Integration (AC6)

- [ ] 5.1 : Modifier `agents/src/core/context.py` (Story 4.1 dépendance)
  - Méthode `get_todays_events(casquette: str | None)` :
    - Query PostgreSQL `knowledge.entities` WHERE `entity_type='EVENT'` AND date=TODAY
    - Filtrage optionnel par casquette
    - Tri chronologique
  - Retour : `list[Event]` (Pydantic models)
- [ ] 5.2 : Tests ContextProvider (4 tests)
  - Test événements du jour (exclut hier/demain)
  - Test filtrage par casquette
  - Test tri chronologique
  - Test aucun événement → liste vide (pas d'erreur)

### Task 6 : Notifications Telegram

- [ ] 6.1 : Modifier `bot/handlers/event_notifications.py` :
  - Notification après création Google Calendar (AC3) :
    - Topic Actions : "✅ Événement ajouté à Google Calendar"
    - Lien direct Google Calendar `event.htmlLink`
  - Notification modification détectée (AC4) :
    - Topic Email & Communications : "🔄 Événement modifié dans Google Calendar"
    - Diff (ancien vs nouveau) : heure, lieu, titre
- [ ] 6.2 : Tests notifications (3 tests)
  - Test notification création réussie
  - Test notification modification détectée
  - Test Unicode emojis rendering

### Task 7 : Webhook Google Calendar (AC7 - Optionnel)

- [ ] 7.1 : Créer `services/gateway/routers/webhooks.py` :
  - Endpoint `POST /api/v1/webhooks/google-calendar`
  - Validation header `X-Goog-Channel-Token`
  - Parsing `X-Goog-Resource-State` : sync, exists, not_exists
  - Trigger sync incrémentale (fetch événements modifiés via `syncToken`)
- [ ] 7.2 : Setup watch channel :
  - Script `scripts/setup_google_calendar_webhook.py`
  - Appel `service.events().watch()` pour chaque calendrier
  - Stockage `channel_id` + `resource_id` dans Redis (TTL = expiration)
  - Renewal automatique avant expiration (7 jours max Google)
- [ ] 7.3 : Tests webhook (4 tests)
  - Test notification `sync` (initialisation)
  - Test notification `exists` (événement modifié)
  - Test notification `not_exists` (événement supprimé)
  - Test validation token invalide → 403

### Task 8 : Tests Intégration (8 tests)

- [ ] 8.1 : `tests/integration/calendar/test_google_calendar_sync.py`
  - Test pipeline complet : PostgreSQL → Google Calendar → PostgreSQL (round-trip)
  - Test multi-calendriers (3 calendriers, 5 événements chacun)
  - Test déduplication `external_id`
  - Test sync bidirectionnelle (modification Google → PostgreSQL)
  - Test sync inverse (modification PostgreSQL → Google)
  - Test transaction atomique rollback
  - Test gestion conflits last-write-wins
  - Test RGPD : Pas de PII dans logs Google Calendar API

### Task 9 : Tests E2E (3 tests critiques)

- [ ] 9.1 : `tests/e2e/calendar/test_google_calendar_real.py`
  - **Test E2E complet** : Story 7.1 detection → validation Telegram → sync Google Calendar → vérification web
  - Fixtures : Compte Google test avec 3 calendriers (médecin/enseignant/chercheur)
  - Assertions : Événement visible dans Google Calendar web UI
- [ ] 9.2 : **Test E2E sync quotidien** : Cron 06:00 → sync_manager → PostgreSQL updated
- [ ] 9.3 : **Test E2E webhook** : Modification Google Calendar web → webhook → PostgreSQL updated

### Task 10 : Documentation (600+ lignes)

- [ ] 10.1 : Créer `docs/google-calendar-sync.md` (450 lignes)
  - Architecture : OAuth2 flow, sync bidirectionnelle, multi-calendriers
  - Setup : Google Cloud Console (OAuth2 client), scopes, credentials
  - Configuration : `calendar_config.yaml`, mapping casquettes → calendar_id
  - Flow diagram : PostgreSQL ↔ Google Calendar sync
  - Troubleshooting :
    - OAuth2 échoue → vérifier client_secret.json
    - Rate limit Google Calendar API (quota 1M requests/day)
    - Conflits sync (last-write-wins)
    - Webhook expiration (renewal requis 7j)
- [ ] 10.2 : Mettre à jour `docs/telegram-user-guide.md` (40 lignes)
  - Section "Synchronisation Google Calendar"
  - Commandes : `/calendar sync` (force sync), `/calendar status`
  - Inline buttons : Ajouter → Google Calendar (casquette auto-détectée)
- [ ] 10.3 : Mettre à jour `CLAUDE.md` (30 lignes)
  - Epic 7 Story 7.2 marquée ready-for-dev
  - Dépendances : Story 7.1 (detection événements), Story 1.5 (RGPD)
- [ ] 10.4 : Créer `docs/google-oauth2-setup.md` (80 lignes)
  - Guide complet : Google Cloud Console configuration
  - OAuth2 consent screen (scope approval)
  - Download client_secret.json
  - First-run authentication flow
  - Token refresh + expiration (1h token, 7j refresh)

---

## Dev Notes

### Patterns Architecturaux Établis

**Story 7.1 Continuité** :
- Migration 036 : Support `entity_type='EVENT'` dans `knowledge.entities`
- Module `agents/src/agents/calendar/` déjà existant (event_detector.py, models.py, prompts.py)
- Trust Layer : `propose` Day 1 pour actions calendrier
- Inline buttons validation (Story 1.10) : [Ajouter] déclenche sync Google Calendar

**OAuth2 Security (NFR9)** :
- Credentials stockés dans `token.json.enc` (chiffré SOPS/age)
- JAMAIS commit `token.json` ou `client_secret.json` en clair
- Refresh token automatique (1h expiration)
- Scopes minimaux : `calendar` + `calendar.events` (moindre privilège)

**Multi-Calendriers Architecture** :
- 1 compte Google, 3 calendriers distincts (médecin, enseignant, chercheur)
- Mapping `casquette` → `calendar_id` dans `calendar_config.yaml`
- Sync parallèle des 3 calendriers (async/await)
- Isolation : Événement médical UNIQUEMENT dans calendrier médecin

**Sync Bidirectionnelle Strategy** :
- Google Calendar = source de vérité (priorité lecture)
- PostgreSQL modifications (Telegram) → Immédiat sync Google
- Déduplication via `external_id` (Google event ID)
- Conflits : Last-write-wins (timestamp `updated_at`)
- Webhook temps réel (optionnel) OU polling 30 min

### Structure Source Tree

```
agents/src/integrations/google_calendar/
├── __init__.py
├── auth.py                     # AC1 - OAuth2 authentication manager
├── sync_manager.py             # AC2, AC3, AC4 - Sync bidirectionnelle
├── models.py                   # Pydantic models GoogleCalendarEvent, SyncResult
└── config.py                   # AC5 - Configuration multi-calendriers

services/calendar_sync/
├── Dockerfile
├── requirements.txt
├── worker.py                   # Daemon sync 30 min
└── main.py                     # Entrypoint

config/
├── calendar_config.yaml        # AC5 - 3 calendriers configuration
├── google_client_secret.json.enc  # OAuth2 credentials (SOPS chiffré)
└── token.json.enc              # OAuth2 token (auto-généré, chiffré)

services/gateway/routers/
└── webhooks.py                 # AC7 - Webhook Google Calendar push

scripts/
└── setup_google_calendar_webhook.py  # AC7 - Setup watch channel

n8n/workflows/
└── calendar-sync.json          # Cron quotidien 06:00 backup sync

tests/
├── unit/integrations/google_calendar/
│   ├── test_auth.py            # 5 tests OAuth2
│   ├── test_sync_manager.py    # 12 tests sync
│   └── test_config.py          # 3 tests configuration
├── integration/calendar/
│   └── test_google_calendar_sync.py  # 8 tests pipeline complet
└── e2e/calendar/
    └── test_google_calendar_real.py  # 3 tests E2E Google API réel

docs/
├── google-calendar-sync.md     # 450 lignes spec complète
├── google-oauth2-setup.md      # 80 lignes setup Google Cloud
└── telegram-user-guide.md      # +40 lignes section Calendar
```

### Standards Techniques

**Google Calendar API v3** :
- Library : `google-api-python-client==2.150.0` (dernière stable 2026)
- Auth : `google-auth-oauthlib==1.2.1`
- Service : `build('calendar', 'v3', credentials=creds)`
- Methods :
  - `events().list()` : Lecture événements
  - `events().insert()` : Création événement
  - `events().patch()` : Modification partielle
  - `events().watch()` : Webhook push notifications

**OAuth2 Flow** :
- Type : Installed Application (Desktop app)
- Scopes :
  - `https://www.googleapis.com/auth/calendar` (lecture/écriture calendriers)
  - `https://www.googleapis.com/auth/calendar.events` (lecture/écriture événements)
- Token : 1h expiration, refresh automatique
- Storage : `token.json.enc` (chiffré SOPS/age)

**PostgreSQL** :
- Schema : `knowledge.entities` (entity_type='EVENT')
- Champs sync :
  - `properties.external_id` : Google Calendar event ID (déduplication)
  - `properties.calendar_id` : ID calendrier Google (mapping casquette)
  - `properties.status` : `"confirmed"` pour événements Google
  - `source_type` : `"google_calendar"`
- Index : `idx_entities_external_id` sur `(properties->>'external_id')`

**Sync Strategy** :
- Fréquence : 30 min (configurable `calendar_config.yaml`)
- Range : -7 jours / +90 jours
- Déduplication : `external_id` → UPSERT
- Transaction : Atomique (tous événements OU rollback)

**Tests** :
- Unitaires : 23 tests (5 auth + 12 sync + 3 config + 3 notifications)
- Intégration : 8 tests (pipeline complet, multi-calendriers, bidirectionnelle)
- E2E : 3 tests critiques (API Google réelle)
- Coverage : ≥80% sync_manager.py, ≥90% auth.py

### Dépendances Critiques

**Stories Prérequises** :
- ✅ Story 7.1 : Detection événements (entités EVENT, migration 036, inline buttons)
- ✅ Story 1.5 : Presidio anonymisation (RGPD logs Google Calendar API)
- ✅ Story 1.6 : Trust Layer middleware (trust=propose validation)
- ✅ Story 1.9 : Bot Telegram + Topics (notifications sync)
- ✅ Story 6.1 : Graphe connaissances PostgreSQL (entities + relations)

**Bloqueurs Potentiels** :
- Google Cloud Console : OAuth2 client créé + scopes approuvés (manuel)
- `client_secret.json` téléchargé + chiffré SOPS
- Story 4.1 (Heartbeat Engine) pas encore implémentée → AC6 stub OK, intégration plus tard
- Rate limit Google Calendar API : 1M requests/day (largement suffisant)

### Risques & Mitigations

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| OAuth2 consent screen non approuvé (Google) | H | Faible | Mode test (100 users max) suffit Day 1, approval production si public |
| Rate limit Google Calendar API (1M/day) | M | Très faible | Sync 30 min = 48 req/jour/calendrier × 3 = 144 req/jour |
| Token expiration 1h (pas de refresh) | H | Faible | Refresh automatique avant expiration, test `RefreshError` |
| Conflits sync (modifications simultanées) | M | Moyenne | Last-write-wins (timestamp), notification Mainteneur si conflit |
| Webhook expiration 7 jours (pas de renewal) | L | Moyenne | Fallback polling 30 min + script renewal automatique |
| Timezone handling (Europe/Paris vs UTC) | M | Faible | Toutes dates ISO 8601 avec timezone explicite |

### NFRs Applicables

- **NFR1** : Latence sync <30s par calendrier (async fetch parallèle)
- **NFR6** : RGPD - Pas de PII dans logs Google Calendar API (sanitize structlog)
- **NFR9** : Secrets chiffrés - `token.json.enc` + `client_secret.json.enc` (SOPS/age)
- **NFR15** : Zero événement perdu - Transaction atomique + retry 3x si erreur
- **NFR17** : Google API resilience - Retry `HttpError` rate limit, circuit breaker

### Testing Strategy (cf. docs/testing-strategy-ai.md)

**Pyramide tests IA** :
- **80% Unit (mocks)** : 23 tests avec mocks Google Calendar API (fixtures events.json)
- **15% Integration (datasets)** : 8 tests avec PostgreSQL réelle + mocks API
- **5% E2E (réel)** : 3 tests avec Google Calendar API réelle + compte test

**Datasets validation** :
- `tests/fixtures/google_calendar_events.json` : 15 événements variés
- 5 événements médecin, 5 enseignant, 5 chercheur
- 3 événements récurrents (expansés)
- Ground truth : `external_id`, `calendar_id`, `casquette`

**Google Calendar API Test Account** :
- Compte Gmail dédié : `friday-test@gmail.com`
- 3 calendriers créés : médecin, enseignant, chercheur
- OAuth2 client test mode (100 users max, pas d'approval requis)

### Learnings Stories Précédentes

**Story 7.1 (Detection Événements)** :
- Migration 036 : Contrainte CHECK `entity_type='EVENT'` + index optimisés
- Module calendar déjà structuré : models.py, prompts.py séparés
- Trust Layer `propose` Day 1 pour actions critiques
- Inline buttons validation : Pattern éprouvé Story 1.10

**Epic 2 Retrospective (Email)** :
- OAuth2 Gmail : App Passwords suffisent Day 1, OAuth2 préparé mais pas activé
- Adaptateur obligatoire pour services externes (email.py pattern)
- Secrets SOPS/age : JAMAIS credentials en clair
- Tests E2E critiques : Validation end-to-end obligatoire

**Story 2.1 (IMAP Direct)** :
- Retry automatique 3x si erreur réseau (NFR17)
- Circuit breaker après 3 échecs consécutifs → alerte System
- Healthcheck Redis key (TTL détection service down)

### Project Structure Notes

**Alignment** :
- Module `agents/src/integrations/google_calendar/` suit convention OAuth2 (externe)
- Service daemon `services/calendar_sync/` comme `services/email_processor/`
- Configuration YAML `config/calendar_config.yaml` comme `config/trust_levels.yaml`
- Tests mirror structure (`tests/unit/integrations/google_calendar/`)

**Détecté** :
- ✅ Migration 036 déjà appliquée (Story 7.1) → Support EVENT OK
- ✅ Inline buttons callbacks déjà enregistrés (Story 1.10) → `handle_event_approve()` stub OK
- ⚠️ Story 4.1 (Heartbeat Engine) pas encore implémentée → AC6 stub `get_todays_events()` OK, intégration complète plus tard
- ⚠️ n8n workflow `calendar-sync.json` à créer (backup cron 06:00)

### Latest Technical Information (Web Research)

**Google Calendar API v3 Best Practices (2026)** :

**OAuth2 Authentication** :
- **User-based flow** : `InstalledAppFlow.run_local_server()` pour desktop app
- **Token storage** : Sauvegarder credentials dans fichier sécurisé (SOPS/age)
- **Refresh token** : Automatique via `google.auth.transport.requests.Request`
- **Scopes** : Minimaux nécessaires (`calendar`, `calendar.events`)
- **Security** : JAMAIS commit `client_secret.json` ou `token.json` en clair

**Source** : [Using OAuth 2.0 to Access Google APIs](https://developers.google.com/identity/protocols/oauth2)

**API Methods** :
- **`events().insert()`** : Créer événement, body = `{summary, location, start, end, attendees}`
- **`events().update()`** : Mise à jour complète, remplace tout l'événement
- **`events().patch()`** : Mise à jour partielle (patch semantics), préféré pour sync
- **`events().list()`** : Liste événements, params = `calendarId, timeMin, timeMax, singleEvents, orderBy`
- **`events().watch()`** : Push notifications webhook, expire après 7 jours (renewal requis)

**Source** : [Google Calendar API v3 Events Reference](https://googleapis.github.io/google-api-python-client/docs/dyn/calendar_v3.events.html)

**Sync Best Practices** :
- **SyncToken** : Utiliser `syncToken` pour fetch incrémental (uniquement modifications)
- **Recurring events** : `singleEvents=true` pour expanser instances (simplification)
- **Timezone** : Toujours spécifier `timeZone` explicite dans `start`/`end` (Europe/Paris)
- **Deduplication** : Utiliser `iCalUID` OU custom `id` pour éviter doublons
- **Conflicts** : Last-write-wins OU custom merge logic

**Source** : [Create Events - Google Calendar API](https://developers.google.com/workspace/calendar/api/guides/create-events)

**Rate Limits (2026)** :
- **Quota** : 1,000,000 requests/day par projet
- **Per-user** : 1,000 requests/100 seconds per user
- **Burst** : 10 requests/second
- **Mitigation** : Exponential backoff retry, batch requests si possible

**Python Library Versions** :
- `google-api-python-client==2.150.0` (stable 2026)
- `google-auth-oauthlib==1.2.1` (OAuth2 flow)
- `google-auth-httplib2==0.2.0` (HTTP transport)

**Webhook Push Notifications** :
- **Channel expiration** : Maximum 7 jours, renewal requis
- **Security** : Valider `X-Goog-Channel-Token` header (secret partagé)
- **States** : `sync` (init), `exists` (modified), `not_exists` (deleted)
- **Fallback** : Polling toutes les 30 min si webhook échoue

**Source** : [Modifying Events - Google Calendar API](https://developers.googleblog.com/modifying-events-with-the-google-calendar-api/)

### References

**Sources Documentation** :
- [Source: _docs/architecture-friday-2.0.md#S3 - Google Calendar API v3]
- [Source: _bmad-output/planning-artifacts/epics-mvp.md#Epic 7 Story 7.2 - FR102 Sync Google Calendar]
- [Source: _bmad-output/implementation-artifacts/7-1-detection-evenements.md - Story précédente]
- [Source: database/migrations/036_events_support.sql - Migration EVENT entity_type]
- [Source: bot/handlers/event_callbacks.py - Inline buttons validation Story 7.1]
- [Source: config/trust_levels.yaml - Trust levels configuration]
- [Source: _bmad-output/implementation-artifacts/epic-2-retro-2026-02-15.md - OAuth2 patterns]

**Décisions Architecturales** :
- [Décision D17] : 100% Claude Sonnet 4.5 (pas utilisé ici, Google Calendar API uniquement)
- [Décision D25] : IMAP direct vs EmailEngine (pattern OAuth2 réutilisé)
- [Story 7.1 AC2] : Migration 036 support EVENT entity_type
- [Story 1.5 AC1] : Anonymisation Presidio logs (sanitize PII Google Calendar API)
- [Story 1.10 AC1] : Inline buttons validation → Trigger sync Google Calendar

**Web Research Sources** :
- [Using OAuth 2.0 to Access Google APIs](https://developers.google.com/identity/protocols/oauth2)
- [Google Calendar API v3 Python Quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)
- [Events Reference - Google Calendar API](https://googleapis.github.io/google-api-python-client/docs/dyn/calendar_v3.events.html)
- [Create Events Guide](https://developers.google.com/workspace/calendar/api/guides/create-events)
- [Modifying Events Blog](https://developers.googleblog.com/modifying-events-with-the-google-calendar-api/)

---

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`)

### Debug Log References

_Section remplie lors du développement_

### Completion Notes List

_Section remplie lors du développement_

### File List

_Section remplie lors du développement_
