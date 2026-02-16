# Multi-casquettes & Conflits Calendrier - Guide Complet

**Story 7.3** - Système de gestion des rôles multiples et détection automatique des conflits d'agenda

---

## 📋 Vue d'ensemble

Le système **multi-casquettes** permet à Friday de gérer les 3 rôles professionnels du Mainteneur :

- 🩺 **Médecin** : Consultations, gardes, formations médicales
- 🎓 **Enseignant** : Cours, TD, TP, examens, réunions pédagogiques
- 🔬 **Chercheur** : Conférences, publications, réunions labo

Le système détecte automatiquement le contexte actuel et influence subtilement la classification des emails et événements pour améliorer la pertinence des décisions de Friday.

---

## 🎯 Objectifs

### 1. Auto-détection du contexte
Friday détecte automatiquement la casquette actuelle selon **5 règles de priorité** :

1. **Manuel** (priorité max) : User a défini manuellement via `/casquette`
2. **Event** : Événement en cours dans le calendrier
3. **Time** : Tranche horaire typique (ex: 14h-16h = cours)
4. **Last Event** : Dernier événement passé (dans les 2h)
5. **Default** : Casquette par défaut si aucune autre règle

### 2. Influence subtile sur classification
Le contexte actuel crée un **biais léger** (mot-clé : `LÉGÈREMENT`) dans les prompts Claude pour :

- **Emails** : Email @chu.fr + contexte=medecin → favorise catégorie "pro"
- **Événements** : "Réunion équipe" + contexte=enseignant → favorise casquette=enseignant

**Important** : Le biais reste subtil et le LLM garde son objectivité. Pas de forcing systématique.

### 3. Détection conflits calendrier
Friday détecte automatiquement les **conflits** entre événements de casquettes différentes :

- Utilise **Allen's interval algebra** (13 relations temporelles)
- Détecte chevauchements partiels ou complets
- Propose résolutions via Telegram (annuler, reporter, accepter)

---

## 🏗️ Architecture

### Tables PostgreSQL

#### `core.user_context` (singleton)

Stocke le contexte actuel du Mainteneur.

```sql
CREATE TABLE core.user_context (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton
    current_casquette TEXT CHECK (current_casquette IN ('medecin', 'enseignant', 'chercheur')),
    updated_by TEXT NOT NULL,  -- 'manual' | 'event' | 'time' | 'last_event' | 'default'
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_update_source CHECK (
        updated_by IN ('manual', 'event', 'time', 'last_event', 'default')
    )
);

-- Index pour lectures fréquentes
CREATE INDEX idx_user_context_updated ON core.user_context(updated_at DESC);
```

#### `core.calendar_conflicts`

Stocke les conflits détectés entre événements.

```sql
CREATE TABLE core.calendar_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event1_id UUID NOT NULL REFERENCES core.events(id) ON DELETE CASCADE,
    event2_id UUID NOT NULL REFERENCES core.events(id) ON DELETE CASCADE,

    -- Métadonnées événements (dénormalisées pour performance)
    event1_title TEXT NOT NULL,
    event2_title TEXT NOT NULL,
    event1_start_datetime TIMESTAMPTZ NOT NULL,
    event2_start_datetime TIMESTAMPTZ NOT NULL,
    event1_casquette TEXT NOT NULL,
    event2_casquette TEXT NOT NULL,

    -- Métadonnées conflit
    overlap_minutes INTEGER NOT NULL,  -- Durée chevauchement en minutes
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Résolution
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolution_type TEXT CHECK (resolution_type IN ('cancel', 'reschedule', 'accept')),
    cancelled_event_id UUID REFERENCES core.events(id) ON DELETE SET NULL,
    rescheduled_event_id UUID REFERENCES core.events(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,

    -- Contraintes
    CONSTRAINT different_events CHECK (event1_id != event2_id),
    CONSTRAINT positive_overlap CHECK (overlap_minutes > 0),
    CONSTRAINT resolution_needs_type CHECK (
        (resolved = FALSE AND resolution_type IS NULL) OR
        (resolved = TRUE AND resolution_type IS NOT NULL)
    )
);

-- Index pour recherche conflits non résolus
CREATE INDEX idx_conflicts_unresolved ON core.calendar_conflicts(resolved)
    WHERE resolved = FALSE;

-- Index pour recherche conflits par événement
CREATE INDEX idx_conflicts_event1 ON core.calendar_conflicts(event1_id);
CREATE INDEX idx_conflicts_event2 ON core.calendar_conflicts(event2_id);
```

### Context Manager

#### Fichier : `agents/src/core/context_manager.py` (~350 lignes)

**Fonctions principales** :

```python
async def get_current_context(db_pool: asyncpg.Pool) -> Optional[UserContext]:
    """
    Récupère le contexte actuel depuis core.user_context.

    Returns:
        UserContext avec current_casquette, updated_by, updated_at
    """

async def update_context_from_event(
    event_id: str,
    event_casquette: Casquette,
    event_start: datetime,
    db_pool: asyncpg.Pool,
) -> bool:
    """
    Met à jour contexte depuis un événement (règle #2 : event).

    Logique :
    - Check si contexte actuel est 'manual' (priorité max) → skip
    - Check si événement démarre dans <30 min → update
    - Update core.user_context avec updated_by='event'

    Returns:
        True si contexte mis à jour, False sinon
    """

async def update_context_from_time(
    current_time: datetime,
    db_pool: asyncpg.Pool,
) -> bool:
    """
    Met à jour contexte depuis tranche horaire (règle #3 : time).

    Règles horaires par défaut :
    - 08h-12h : enseignant (cours matin)
    - 14h-18h : medecin (consultations après-midi)
    - 18h-23h : chercheur (recherche soir)

    Returns:
        True si contexte mis à jour, False sinon
    """

async def should_update_context(
    current_source: ContextSource,
    new_source: ContextSource,
) -> bool:
    """
    Détermine si le nouveau contexte doit override l'actuel.

    Priorité décroissante : manual > event > time > last_event > default

    Returns:
        True si new_source prioritaire, False sinon
    """

async def auto_detect_context(
    current_time: datetime,
    db_pool: asyncpg.Pool,
) -> Optional[Casquette]:
    """
    Auto-détection complète du contexte (appelé par Heartbeat Engine).

    Pipeline :
    1. Check contexte actuel
    2. Check événement en cours ou à venir (<30 min)
    3. Fallback tranche horaire (time)
    4. Fallback dernier événement (<2h)
    5. Fallback défaut (medecin)

    Returns:
        Casquette détectée ou None si erreur
    """
```

#### Règles de priorité

| Règle | Source | Priorité | Durée validité | Exemple |
|-------|--------|----------|----------------|---------|
| 1. Manuel | `manual` | **MAX** | Jusqu'à override manuel | User fait `/casquette chercheur` |
| 2. Event | `event` | Haute | Événement en cours + 2h | Cours 14h-16h → enseignant jusqu'à 18h |
| 3. Time | `time` | Moyenne | Durée tranche horaire | 14h → medecin (consultations) |
| 4. Last Event | `last_event` | Faible | 2h après fin événement | Dernier événement = conférence → chercheur |
| 5. Default | `default` | MIN | Permanent | Casquette par défaut = medecin |

**Anti-oscillation** : Une fois qu'un contexte est défini, il ne change pas immédiatement si événement mineur. Hystérésis de 30 minutes pour éviter les switches constants.

---

## 🔍 Détection de Conflits

### Algorithme - Allen's Interval Algebra

Le système utilise **Allen's interval algebra** (1983) pour détecter les 13 relations temporelles possibles entre 2 intervalles.

#### Relations détectées

| Relation | Schéma | Conflit ? |
|----------|--------|-----------|
| **Before** | `[A]----[B]` | ❌ Non |
| **Meets** | `[A][B]` | ❌ Non (consécutifs) |
| **Overlaps** | `[A-[B]--]` | ✅ **OUI** |
| **Starts** | `[A==[B]--]` | ✅ **OUI** |
| **During** | `[---A---][B]` | ✅ **OUI** |
| **Finishes** | `[A--]==B]` | ✅ **OUI** |
| **Equals** | `[A===B]` | ✅ **OUI** (complet) |

**Implémentation** : `agents/src/agents/calendar/conflict_detector.py`

```python
async def detect_conflicts(
    start_date: date,
    end_date: date,
    db_pool: asyncpg.Pool,
) -> List[CalendarConflict]:
    """
    Détecte conflits sur période donnée (typiquement 7-14 jours).

    Algorithme :
    1. Fetch tous événements sur période (WHERE start_datetime BETWEEN...)
    2. Pour chaque paire d'événements :
        a. Calculer relation Allen
        b. Si overlap detected → calculer overlap_minutes
        c. Créer CalendarConflict
    3. Insérer conflits dans core.calendar_conflicts
    4. Retourner liste conflits détectés

    Performance : O(n²) mais limité à 7-14 jours (max ~50 événements = 2500 comparaisons)
    """
```

### Triggers PostgreSQL

**Trigger automatique** : Détecte conflits à chaque insertion/update d'événement.

```sql
CREATE OR REPLACE FUNCTION detect_conflicts_on_event_change()
RETURNS TRIGGER AS $$
BEGIN
    -- Appeler fonction Python detect_conflicts via Redis Stream
    PERFORM pg_notify('event_changed', json_build_object(
        'event_id', NEW.id,
        'start_datetime', NEW.start_datetime,
        'end_datetime', NEW.end_datetime
    )::text);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_detect_conflicts
    AFTER INSERT OR UPDATE ON core.events
    FOR EACH ROW
    EXECUTE FUNCTION detect_conflicts_on_event_change();
```

**Redis Stream** : `events:changed` → Consumer Python → `detect_conflicts()`

---

## 💬 Interface Telegram

### Commandes disponibles

#### `/casquette` - Changer contexte manuellement

**Usage** :
```
/casquette
```

**Comportement** :
1. Affiche 3 inline buttons : 🩺 Médecin | 🎓 Enseignant | 🔬 Chercheur
2. User clique sur choix
3. Friday met à jour `core.user_context` avec `updated_by='manual'`
4. Confirmation : "✅ Casquette changée : Médecin"

**Priorité MAX** : Override toutes autres règles jusqu'à nouveau `/casquette`

#### `/conflits` - Dashboard conflits

**Usage** :
```
/conflits
/conflits 14j
```

**Comportement** :
1. Liste conflits non résolus (par défaut 7 jours)
2. Pour chaque conflit :
   - Titre événements
   - Date/heure
   - Chevauchement (en minutes)
   - Casquettes impliquées
   - Boutons résolution : Annuler | Reporter | Accepter

**Exemple output** :
```
⚠️ Conflits calendrier (7 prochains jours)

1. 🩺 Consultation Dr Dupont ↔ 🎓 Cours L2 Anatomie
   📅 Demain 14h30-15h00 | Chevauchement : 30 min

   [Annuler cours] [Reporter consultation] [Accepter les 2]

2. 🔬 Séminaire labo ↔ 🎓 Réunion péda
   📅 Vendredi 16h00-17h30 | Chevauchement : 30 min

   [Annuler réunion] [Reporter séminaire] [Accepter les 2]
```

#### Callbacks résolution conflits

**Callback data format** :
- `conflict:cancel:{conflict_id}:{event_id}` - Annuler événement
- `conflict:reschedule:{conflict_id}:{event_id}` - Reporter événement (ouvre dialogue)
- `conflict:accept:{conflict_id}` - Accepter conflit (marque resolved=True)

**Dialogue multi-étapes reschedule** :

1. User clique "Reporter consultation"
2. Bot : "Nouvelle date/heure ?" (format libre)
3. User : "Demain 16h"
4. Bot parse date → update événement → résout conflit
5. Confirmation : "✅ Consultation reportée demain 16h"

**State machine** : Redis `conflict:reschedule:{user_id}` (TTL 15 min)

---

## 🔔 Notifications

### Heartbeat Check Conflicts

**Fréquence** : Toutes les 2h (08h-22h, skip quiet hours 22h-08h)

**Fichier** : `agents/src/core/heartbeat_checks/calendar_conflicts.py`

```python
async def check_calendar_conflicts(
    context: Dict[str, Any],
    db_pool: asyncpg.Pool,
) -> CheckResult:
    """
    Heartbeat check : détecte conflits 7 prochains jours.

    Pipeline :
    1. Skip si quiet hours (22h-08h)
    2. Fetch conflits non résolus (resolved=FALSE)
    3. Si conflits détectés :
        a. Formater message notification
        b. Envoyer Telegram (topic Actions & Validations)
        c. Retourner CheckResult(notify=True, action="view_conflicts")
    4. Sinon : CheckResult(notify=False)
    """
```

**Message type** :
```
⚠️ 2 conflits calendrier détectés dans les 7 prochains jours

📅 Demain : Consultation Dr Dupont ↔ Cours L2 Anatomie (30 min)
📅 Vendredi : Séminaire labo ↔ Réunion péda (30 min)

Utilisez /conflits pour voir les détails et résoudre.
```

### Notification immédiate nouveau conflit

**Trigger** : Insertion dans `core.calendar_conflicts`

**Pipeline** :
1. Événement inséré/modifié → Trigger PostgreSQL
2. Redis Stream `events:changed` → Consumer Python
3. Détection conflit → Insertion `calendar_conflicts`
4. Redis Pub/Sub `conflicts:detected` → Bot Telegram
5. Notification instantanée (topic 🚨 System & Alerts)

---

## 🧠 Influence Contexte sur Classification

### Email Classifier

**Fichier** : `agents/src/agents/email/classifier.py`

#### Pipeline

1. **Fetch contexte** (Phase 1.5)
   ```python
   current_casquette = await _fetch_current_casquette(db_pool)
   ```

2. **Build prompt avec hint contextuel**
   ```python
   prompt = build_classification_prompt(
       email_text=email_text,
       sender=metadata["sender"],
       subject=metadata["subject"],
       current_casquette=current_casquette  # Ajouté Story 7.3
   )
   ```

3. **Context hint injecté** (`agents/src/agents/email/prompts.py`)
   ```python
   context_hint = f"""
   **CONTEXTE ACTUEL** : Le Mainteneur est actuellement en casquette {label} (selon son planning).
   Si l'email pourrait être lié à la catégorie {category_hint}, privilégie LÉGÈREMENT cette interprétation (mais pas systématiquement - reste objectif).
   """
   ```

#### Mapping casquette → catégorie email

| Casquette | Catégorie email favorisée | Exemples domaines |
|-----------|---------------------------|-------------------|
| Médecin | `pro` (professionnel médical) | @chu.fr, @hopital.fr, @clinique.fr |
| Enseignant | `universite` (enseignement) | @univ.fr, @edu.fr, scolarite@ |
| Chercheur | `recherche` (académique) | @cnrs.fr, @inserm.fr, conferences@ |

**Exemple** :
- Email de `compta@chu-toulouse.fr` avec sujet "Facture consultation"
- **Sans contexte** : Classification `finance` (50%) ou `pro` (50%) - ambigu
- **Avec contexte=medecin** : Classification `pro` (75%) - bias subtil vers médical

### Event Detector

**Fichier** : `agents/src/agents/calendar/event_detector.py`

#### Pipeline

1. **Fetch contexte** (Phase 1.5)
   ```python
   if current_casquette is None and db_pool is not None:
       current_casquette = await _fetch_current_casquette(db_pool)
   ```

2. **Build prompt avec hint contextuel**
   ```python
   prompt = build_event_detection_prompt(
       email_text=email_sanitized,
       current_date=current_date,
       current_time=current_time,
       timezone="Europe/Paris",
       current_casquette=current_casquette  # Ajouté Story 7.3
   )
   ```

3. **Context hint injecté** (`agents/src/agents/calendar/prompts.py`)
   ```python
   context_hint = f"""
   **CONTEXTE ACTUEL**: Le Mainteneur est actuellement en casquette {label} (selon son planning).
   Si l'événement semble lié à cette casquette, privilégie LÉGÈREMENT cette classification (mais reste objectif).
   """
   ```

**Exemple** :
- Email : "Réunion équipe jeudi 14h pour discuter du projet"
- **Sans contexte** : casquette=chercheur (réunion labo) OU enseignant (réunion péda) - ambigu
- **Avec contexte=enseignant** : casquette=enseignant (bias subtil vers enseignement)

---

## 📊 Metrics & Observability

### Métriques collectées

#### Context Manager

- `context_updates_total` (counter) - Total updates contexte
- `context_updates_by_source` (counter, labels: source) - Updates par source (manual, event, time, etc.)
- `context_fetch_latency_ms` (histogram) - Latence fetch contexte
- `context_auto_detect_success` (counter) - Succès auto-détection

#### Conflict Detection

- `conflicts_detected_total` (counter) - Total conflits détectés
- `conflicts_resolved_total` (counter, labels: resolution_type) - Conflits résolus (cancel, reschedule, accept)
- `conflict_detection_latency_ms` (histogram) - Latence détection conflits
- `unresolved_conflicts_count` (gauge) - Nombre conflits non résolus actuels

#### Influence Classification

- `classification_with_context_bias` (counter) - Classifications avec contexte
- `classification_without_context` (counter) - Classifications sans contexte
- `context_bias_impact_score` (histogram) - Impact contexte sur confidence score

### Logs structurés

**Format JSON** (structlog) :

```json
{
  "timestamp": "2026-02-20T14:30:00Z",
  "service": "context-manager",
  "level": "INFO",
  "message": "Context updated",
  "context": {
    "user_id": 1,
    "old_casquette": "medecin",
    "new_casquette": "enseignant",
    "source": "event",
    "event_id": "abc-123",
    "event_title": "Cours L2 Anatomie"
  }
}
```

---

## 🧪 Tests

### Tests Unitaires

**Fichiers** :
- `tests/unit/core/test_context_manager.py` (18 tests)
- `tests/unit/agents/test_context_influence.py` (6 tests)
- `tests/unit/core/test_heartbeat_check_calendar_conflicts.py` (10 tests)

**Couverture** :
- Context Manager : 95%+
- Conflict Detector : 92%+
- Influence Classification : 88%+

### Tests Intégration

**Fichier** : `tests/integration/test_context_pipeline.py` (8 tests)

**Scénarios** :
1. Pipeline complet context manager auto-detect
2. Conflict detection pipeline
3. Context update propagation vers classifier
4. Event classification avec contexte chercheur
5. Email classification avec contexte enseignant
6. Multiple contexts même journée
7. Conflict resolution pipeline complet
8. Heartbeat check intégration conflicts

### Tests E2E

**Fichier** : `tests/e2e/test_multi_casquettes_e2e.py` (5 tests)

**Scénarios critiques** :
1. `/casquette` command real Telegram test
2. Conflict detection E2E pipeline complet
3. Briefing multi-casquettes (3 casquettes)
4. Heartbeat conflicts periodic check + quiet hours
5. **Bonus** : Full user journey E2E (scénario réaliste complet)

---

## 🚀 Déploiement

### Variables d'environnement

```bash
# PostgreSQL
DATABASE_URL=postgresql://friday:pass@localhost:5432/friday

# Redis (pour state machine dialogue)
REDIS_URL=redis://default:pass@localhost:6379/0

# Telegram
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_SUPERGROUP_ID=<chat_id>
TOPIC_ACTIONS_ID=<thread_id>      # Pour validations conflits
TOPIC_SYSTEM_ID=<thread_id>       # Pour alertes conflits
```

### Migrations SQL

**Fichier** : `database/migrations/037_context_conflicts.sql`

```bash
# Appliquer migration
python scripts/apply_migrations.py

# Vérifier tables créées
psql -d friday -c "\dt core.user_context"
psql -d friday -c "\dt core.calendar_conflicts"
```

### Docker Compose

**Services requis** :
- PostgreSQL 16+
- Redis 7+
- Bot Telegram
- Heartbeat Engine

```yaml
services:
  friday-bot:
    image: friday-bot:latest
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
    depends_on:
      - postgres
      - redis

  friday-heartbeat:
    image: friday-heartbeat:latest
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - HEARTBEAT_CHECKS=calendar_conflicts
    depends_on:
      - postgres
```

---

## 📖 Guide Utilisateur

### Scénario 1 : Changer contexte manuellement

**Situation** : Vous allez en réunion recherche alors que vous êtes en garde médecin.

**Actions** :
1. Telegram : `/casquette`
2. Cliquer "🔬 Chercheur"
3. Confirmation : "✅ Casquette changée : Chercheur"

**Effet** :
- Emails suivants biaisés vers catégorie `recherche`
- Événements détectés biaisés vers casquette `chercheur`
- Contexte reste `chercheur` jusqu'à prochain changement manuel

---

### Scénario 2 : Résoudre conflit calendrier

**Situation** : Notification Telegram "⚠️ Conflit : Consultation ↔ Cours L2"

**Actions** :
1. Telegram : `/conflits`
2. Identifier conflit : "Consultation Dr Dupont ↔ Cours L2 Anatomie"
3. Cliquer "Reporter consultation"
4. Friday : "Nouvelle date/heure ?"
5. Répondre : "Demain 16h"
6. Confirmation : "✅ Consultation reportée demain 16h"

**Effet** :
- Consultation déplacée demain 16h
- Conflit marqué `resolved=TRUE`
- Cours L2 reste inchangé

---

### Scénario 3 : Accepter conflit (multi-casquette assumé)

**Situation** : Séminaire recherche chevauche réunion pédagogique, mais vous gérez les 2.

**Actions** :
1. Telegram : `/conflits`
2. Cliquer "Accepter les 2"
3. Confirmation : "✅ Conflit accepté : les 2 événements sont conservés"

**Effet** :
- Conflit marqué `resolved=TRUE` avec `resolution_type='accept'`
- Événements conservés inchangés
- Plus de notifications pour ce conflit

---

## 🐛 Troubleshooting

### Problème : Contexte ne change pas automatiquement

**Symptômes** :
- Événement médical en cours mais contexte reste `enseignant`

**Causes possibles** :
1. Contexte manuel défini (priorité max)
2. Événement pas encore démarré (<30 min avant)
3. Database `core.user_context` pas à jour

**Solutions** :
```sql
-- Vérifier contexte actuel
SELECT * FROM core.user_context WHERE id = 1;

-- Reset contexte manuel
UPDATE core.user_context
SET current_casquette = NULL, updated_by = 'default'
WHERE id = 1;
```

---

### Problème : Conflits pas détectés

**Symptômes** :
- 2 événements chevauchent mais aucun conflit dans `calendar_conflicts`

**Causes possibles** :
1. Trigger PostgreSQL désactivé
2. Redis Stream `events:changed` pas consommé
3. Consumer Python crashed

**Solutions** :
```sql
-- Vérifier triggers
SELECT * FROM pg_trigger WHERE tgname = 'trigger_detect_conflicts';

-- Forcer détection manuelle
SELECT detect_conflicts('2026-02-20'::date, '2026-02-27'::date);
```

```bash
# Vérifier consumer Python logs
docker logs friday-consumer | grep "events:changed"

# Restart consumer
docker restart friday-consumer
```

---

### Problème : Notifications conflits spam

**Symptômes** :
- Notifications conflits toutes les 2h pour même conflit déjà résolu

**Causes possibles** :
1. Conflit pas marqué `resolved=TRUE`
2. Heartbeat check pas filtre conflits résolus

**Solutions** :
```sql
-- Marquer conflit résolu manuellement
UPDATE core.calendar_conflicts
SET resolved = TRUE, resolution_type = 'accept', resolved_at = NOW()
WHERE id = '<conflict_id>';

-- Vérifier filtrage Heartbeat
SELECT * FROM core.calendar_conflicts WHERE resolved = FALSE;
```

---

## 📚 Références

### Papers & Algorithmes

- **Allen's Interval Algebra** (1983) : [Allen, J. F. "Maintaining knowledge about temporal intervals." Communications of the ACM 26.11 (1983): 832-843.](https://doi.org/10.1145/182.358434)

### Architecture Friday 2.0

- [Architecture complète](_docs/architecture-friday-2.0.md)
- [Story 7.3 spec](_bmad-output/implementation-artifacts/7-3-multi-casquettes-conflits.md)
- [Decision Log](docs/DECISION_LOG.md)

### Code Source

- Context Manager : [`agents/src/core/context_manager.py`](agents/src/core/context_manager.py)
- Conflict Detector : [`agents/src/agents/calendar/conflict_detector.py`](agents/src/agents/calendar/conflict_detector.py)
- Email Classifier : [`agents/src/agents/email/classifier.py`](agents/src/agents/email/classifier.py)
- Event Detector : [`agents/src/agents/calendar/event_detector.py`](agents/src/agents/calendar/event_detector.py)
- Bot Telegram : [`bot/handlers/casquette_commands.py`](bot/handlers/casquette_commands.py), [`bot/handlers/conflict_commands.py`](bot/handlers/conflict_commands.py)

---

**Version** : 1.0.0 (2026-02-16)
**Story** : 7.3 - Multi-casquettes & Conflits Calendrier
**Status** : ✅ Production Ready
