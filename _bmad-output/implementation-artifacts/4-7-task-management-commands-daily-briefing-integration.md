# Story 4.7: Task Management Commands & Daily Briefing Integration

Status: ready-for-dev

## Story

En tant que Mainteneur,
Je veux pouvoir consulter, rechercher et compléter mes tâches via des commandes Telegram,
afin d'avoir un système de gestion de tâches complet et intégré au briefing matinal.

## Contexte

### Gap critique identifié

Le système Friday 2.0 possède actuellement :
- **Story 4.6** : Agent conversationnel capable de CRÉER des tâches depuis langage naturel
- **Table `core.tasks`** : Stockage des tâches avec statuts (pending/running/completed/failed/cancelled)

**MAIS** : Aucun moyen de CONSULTER ou LISTER les tâches créées. C'est un trou noir fonctionnel critique.

### Besoin utilisateur explicite

L'utilisateur (Mainteneur) a demandé :
1. Des commandes Telegram pour **consulter** les tâches existantes
2. L'intégration avec le **briefing matinal 8h** (Story 4.2) pour voir les tâches du jour
3. La capacité de **marquer une tâche comme complétée** via Telegram
4. Des commandes de **recherche et filtrage** (overdue, urgent, completed)

Ce besoin est apparu lors de l'implémentation de Story 4.6 — l'utilisateur a réalisé qu'on peut créer des tâches mais pas les voir ni les gérer.

## Acceptance Criteria

### AC1: Commandes de consultation de base

**GIVEN** des tâches existantes dans `core.tasks`
**WHEN** l'utilisateur tape `/taches`
**THEN** Friday affiche les 10 tâches actives les plus récentes (status IN ('pending', 'running'))
**AND** chaque ligne contient : ID, description courte (max 60 chars), priorité si > 0, due_date si définie

Format attendu :
```
📋 Tâches actives (10)

• #42 - Appeler comptable (urgent) - Échéance: aujourd'hui
• #38 - CT voiture - Échéance: dans 2 jours
• #35 - Rappeler Julie thèse
• #33 - Répondre email doyen
...

💡 Utilise /taches -v pour détails complets
```

### AC2: Commandes de filtrage

**GIVEN** des tâches avec différents statuts et dates
**WHEN** l'utilisateur tape `/taches -done`
**THEN** Friday affiche les 10 dernières tâches complétées avec timestamps completion

**WHEN** l'utilisateur tape `/taches -overdue`
**THEN** Friday affiche toutes les tâches en retard (due_date < NOW AND status != 'completed')

**WHEN** l'utilisateur tape `/taches -urgent`
**THEN** Friday affiche toutes les tâches avec priority >= 3 (échelle 0-5)

**WHEN** l'utilisateur tape `/taches search <query>`
**THEN** Friday recherche dans les descriptions (ILIKE %query%) et affiche les résultats

### AC3: Détail d'une tâche spécifique

**GIVEN** une tâche avec ID 42
**WHEN** l'utilisateur tape `/taches 42`
**THEN** Friday affiche :
- ID, description complète, statut, priorité
- Timestamps (created_at, scheduled_at, started_at, completed_at si applicable)
- Payload JSON formaté
- Lien vers receipt si la tâche a été créée par un agent

Format attendu :
```
📋 Tâche #42

Description: Appeler le comptable pour facture S1234
Statut: pending
Priorité: 4/5 (urgent)
Créée le: 2026-02-10 à 09h15
Échéance: 2026-02-10 à 17h00

Contexte:
- Source: email de compta@example.com
- Reference: facture S1234
- Créée par: conversational_agent (receipt #156)

/tache complete 42 pour marquer comme terminée
```

### AC4: Complétion d'une tâche avec Trust Layer

**GIVEN** une tâche active (ID 42)
**WHEN** l'utilisateur tape `/tache complete 42`
**THEN** l'action passe par `@friday_action` middleware (Trust Layer)
**AND** un receipt est créé dans `core.action_receipts`
**AND** la tâche est marquée status='completed', completed_at=NOW()
**AND** Friday répond "✅ Tâche #42 marquée comme complétée: Appeler comptable"

**Trust level** : auto (low risk) — marquer une tâche comme complétée ne nécessite pas de validation.

### AC5: Suppression d'une tâche avec confirmation

**GIVEN** une tâche quelconque (ID 42)
**WHEN** l'utilisateur tape `/tache delete 42`
**THEN** Friday envoie un inline button [Confirmer suppression] [Annuler]
**AND** clic sur Confirmer → tâche supprimée (soft delete ou hard delete selon implémentation)
**AND** receipt créé via @friday_action
**AND** Friday confirme "🗑️ Tâche #42 supprimée"

**Trust level** : auto (après confirmation explicite).

### AC6: Intégration briefing matinal 8h (Story 4.2) — **CRITIQUE**

**GIVEN** le briefing matinal est généré à 8h00 (Story 4.2)
**WHEN** Friday construit le briefing
**THEN** il inclut une section "📋 Tâches du jour" AVANT les autres sections
**AND** cette section liste :
- Tâches avec `due_date::date = CURRENT_DATE`
- Tâches en retard (`due_date < CURRENT_DATE AND status != 'completed'`)

Format attendu dans le briefing :
```
📋 Tâches du jour (3)

⚠️ EN RETARD:
• #39 - Rappeler Dr Dupont (depuis hier)

AUJOURD'HUI:
• #42 - Appeler comptable (urgent)
• #45 - CT voiture avant 17h

💡 /taches pour voir toutes tes tâches
```

**Impact sur Story 4.2** : Modifier le générateur de briefing (`agents/src/agents/proactive/briefing.py` probable) pour inclure cette section.

### AC7: Progressive Disclosure

**GIVEN** plus de 20 tâches actives
**WHEN** l'utilisateur tape `/taches`
**THEN** Friday affiche les 10 premières avec message "20 autres tâches - /taches -v pour tout voir"

**WHEN** l'utilisateur tape `/taches -v`
**THEN** Friday affiche toutes les tâches actives avec détails complets (timestamps, payload, etc.)

**Règle** : Par défaut, afficher 10 lignes max (sauf -v flag). Pour les commandes de filtrage, afficher tout si < 20 résultats, sinon paginer.

### AC8: Tests obligatoires

**Unit tests** (bot/handlers/test_task_commands.py) :
- test_taches_command_lists_active_tasks
- test_taches_command_done_filter
- test_taches_command_overdue_filter
- test_taches_command_urgent_filter
- test_taches_command_search_query
- test_tache_detail_by_id
- test_tache_complete_creates_receipt
- test_tache_delete_confirmation_flow
- test_taches_command_pagination
- test_taches_verbose_flag
- test_taches_empty_state (aucune tâche)
- test_taches_search_no_results
- test_tache_complete_invalid_id
- test_tache_complete_already_completed
- test_tache_delete_invalid_id

**E2E tests** (tests/e2e/bot/test_task_management_e2e.py) :
- test_e2e_briefing_includes_tasks_section
- test_e2e_create_task_then_list_via_taches
- test_e2e_complete_task_workflow

Total : **15 unit + 3 E2E = 18 tests minimum**.

## Tasks / Subtasks

- [ ] T1: Ajouter colonne `due_date` à core.tasks (AC1, AC6)
  - [ ] T1.1: Créer migration 020_add_due_date_to_tasks.sql
  - [ ] T1.2: Ajouter index sur due_date
  - [ ] T1.3: Tester migration sur base vierge + rollback

- [ ] T2: Créer handler /taches (AC1, AC2, AC7)
  - [ ] T2.1: Implémenter bot/handlers/task_commands.py avec fonction taches_command()
  - [ ] T2.2: Parser arguments (-done, -overdue, -urgent, search, -v)
  - [ ] T2.3: Requêtes SQL pour chaque filtre
  - [ ] T2.4: Formatter la réponse (emojis, progressive disclosure)
  - [ ] T2.5: Enregistrer handler dans bot/main.py

- [ ] T3: Créer handler /taches <id> (AC3)
  - [ ] T3.1: Fonction tache_detail_command()
  - [ ] T3.2: Requête SQL avec LEFT JOIN vers action_receipts si applicable
  - [ ] T3.3: Formatter détails complets avec contexte

- [ ] T4: Créer handler /tache complete <id> (AC4)
  - [ ] T4.1: Fonction tache_complete_command()
  - [ ] T4.2: Décorateur @friday_action pour créer receipt
  - [ ] T4.3: UPDATE core.tasks SET status='completed', completed_at=NOW()
  - [ ] T4.4: Message confirmation

- [ ] T5: Créer handler /tache delete <id> (AC5)
  - [ ] T5.1: Fonction tache_delete_command()
  - [ ] T5.2: Inline buttons confirmation
  - [ ] T5.3: Callback handler pour suppression effective
  - [ ] T5.4: Décorateur @friday_action pour créer receipt

- [ ] T6: Intégration briefing matinal (AC6) — **CRITIQUE**
  - [ ] T6.1: Localiser fichier générateur briefing (agents/src/agents/proactive/briefing.py probable)
  - [ ] T6.2: Ajouter fonction query_daily_tasks()
  - [ ] T6.3: Intégrer section "Tâches du jour" en début de briefing
  - [ ] T6.4: Formatter section (emoji ⚠️ pour overdue)
  - [ ] T6.5: Modifier Story 4.2 acceptance criteria (doc update)

- [ ] T7: Mise à jour documentation (AC6)
  - [ ] T7.1: Ajouter commandes /taches dans bot/handlers/commands.py help text
  - [ ] T7.2: Mettre à jour docs/telegram-user-guide.md
  - [ ] T7.3: Documenter intégration briefing dans Story 4.2

- [ ] T8: Trust Layer configuration (AC4, AC5)
  - [ ] T8.1: Ajouter section task_management dans config/trust_levels.yaml
  - [ ] T8.2: Définir trust levels (complete=auto, delete=auto)

- [ ] T9: Tests unitaires (AC8)
  - [ ] T9.1: Créer tests/unit/bot/test_task_commands.py
  - [ ] T9.2: Implémenter 15 tests unitaires
  - [ ] T9.3: Mocker asyncpg queries

- [ ] T10: Tests E2E (AC8)
  - [ ] T10.1: Créer tests/e2e/bot/test_task_management_e2e.py
  - [ ] T10.2: Implémenter 3 tests E2E avec base PostgreSQL
  - [ ] T10.3: Vérifier intégration briefing

## Dev Notes

### Architecture Context

**Pattern établi** :
- Les commandes Telegram suivent le pattern de `bot/handlers/commands.py` (Story 1.11 complétée)
- Le pattern `@friday_action` est établi (Story 1.6) pour toute action créant un receipt
- Les inline buttons suivent le pattern de `bot/handlers/callbacks.py` (Story 1.10)

**Contraintes architecturales** :
- PostgreSQL avec asyncpg brut (PAS d'ORM)
- Logs structurés JSON avec structlog
- Progressive disclosure obligatoire (CLAUDE.md principe)
- Tous strings utilisateur passent par Presidio si sensibles (ici, peu probable)

### Schema `core.tasks` actuel

```sql
CREATE TABLE core.tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}',
    result JSONB,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Manque** : Colonne `due_date TIMESTAMPTZ` pour échéances. **DOIT être ajoutée** (migration 020).

**Champ `name`** : Utilisé comme description courte (max 255 chars). Pour le résumé dans `/taches`.

**Champ `payload`** : Contient contexte additionnel (source email, receipt source si créé par agent, etc.)

### Query patterns critiques

**Tâches actives** :
```sql
SELECT id, name, priority, due_date, created_at
FROM core.tasks
WHERE status IN ('pending', 'running')
ORDER BY
    CASE WHEN due_date IS NOT NULL AND due_date < NOW() THEN 0 ELSE 1 END,
    priority DESC,
    due_date ASC NULLS LAST,
    created_at DESC
LIMIT 10;
```

**Tâches du jour (briefing)** :
```sql
-- Overdue
SELECT * FROM core.tasks
WHERE due_date < CURRENT_DATE AND status != 'completed'
ORDER BY due_date ASC;

-- Today
SELECT * FROM core.tasks
WHERE due_date::date = CURRENT_DATE AND status IN ('pending', 'running')
ORDER BY priority DESC, due_date ASC;
```

**Search** :
```sql
SELECT id, name, priority, due_date, status
FROM core.tasks
WHERE name ILIKE '%' || $1 || '%'
ORDER BY created_at DESC
LIMIT 20;
```

### Trust Layer intégration

```python
# bot/handlers/task_commands.py
from agents.src.middleware.trust import friday_action
from agents.src.middleware.models import ActionResult

@friday_action(module="task_management", action="complete_task", trust_default="auto")
async def complete_task(task_id: str, db_pool) -> ActionResult:
    """
    Marque une tâche comme complétée.

    Trust level: auto (low risk).
    """
    async with db_pool.acquire() as conn:
        task = await conn.fetchrow(
            "SELECT id, name FROM core.tasks WHERE id = $1",
            task_id
        )
        if not task:
            raise ValueError(f"Tâche {task_id} introuvable")

        if task['status'] == 'completed':
            raise ValueError(f"Tâche {task_id} déjà complétée")

        await conn.execute(
            "UPDATE core.tasks SET status = 'completed', completed_at = NOW() "
            "WHERE id = $1",
            task_id
        )

        return ActionResult(
            input_summary=f"Compléter tâche #{task_id}",
            output_summary=f"Tâche marquée complétée: {task['name']}",
            confidence=1.0,  # Action déterministe
            reasoning="Action utilisateur explicite via /tache complete"
        )
```

### Intégration Story 4.2 (Briefing)

**Fichier probable** : `agents/src/agents/proactive/briefing.py` (à créer si n'existe pas, Story 4.2 en backlog).

**Si Story 4.2 n'existe pas encore** : Créer un stub avec TODO pour l'intégration future.

**Pattern attendu** :
```python
async def generate_morning_briefing(db_pool) -> str:
    """Génère le briefing matinal 8h."""
    sections = []

    # NOUVELLE SECTION (Story 4.7)
    tasks_section = await generate_tasks_section(db_pool)
    if tasks_section:
        sections.append(tasks_section)

    # Sections existantes
    email_section = await generate_email_section(db_pool)
    # ...

    return "\n\n".join(sections)

async def generate_tasks_section(db_pool) -> str:
    """Section tâches du jour pour briefing."""
    async with db_pool.acquire() as conn:
        # Overdue tasks
        overdue = await conn.fetch(
            "SELECT id, name FROM core.tasks "
            "WHERE due_date < CURRENT_DATE AND status != 'completed' "
            "ORDER BY due_date ASC"
        )

        # Today's tasks
        today = await conn.fetch(
            "SELECT id, name, priority FROM core.tasks "
            "WHERE due_date::date = CURRENT_DATE AND status IN ('pending', 'running') "
            "ORDER BY priority DESC, due_date ASC"
        )

    if not overdue and not today:
        return ""  # Pas de section si aucune tâche

    lines = ["📋 Tâches du jour"]

    if overdue:
        lines.append("\n⚠️ EN RETARD:")
        for task in overdue:
            lines.append(f"• #{task['id'][:8]} - {task['name']}")

    if today:
        lines.append("\nAUJOURD'HUI:")
        for task in today:
            urgent = " (urgent)" if task['priority'] >= 3 else ""
            lines.append(f"• #{task['id'][:8]} - {task['name']}{urgent}")

    lines.append("\n💡 /taches pour voir toutes tes tâches")

    return "\n".join(lines)
```

### Formatter helper

```python
def format_task_summary(task: dict) -> str:
    """
    Formate une tâche en ligne résumée.

    Args:
        task: Dict avec keys id, name, priority, due_date, status

    Returns:
        Ligne formatée, ex: "• #42abc - Appeler comptable (urgent) - Échéance: aujourd'hui"
    """
    task_id_short = str(task['id'])[:8]
    name = task['name'][:60]  # Tronquer si trop long

    # Priority indicator
    priority_text = ""
    if task['priority'] >= 4:
        priority_text = " (urgent)"
    elif task['priority'] >= 2:
        priority_text = " (important)"

    # Due date
    due_text = ""
    if task['due_date']:
        due_date = task['due_date']
        if due_date.date() == datetime.now().date():
            due_text = " - Échéance: aujourd'hui"
        elif due_date.date() == (datetime.now() + timedelta(days=1)).date():
            due_text = " - Échéance: demain"
        elif due_date < datetime.now():
            days_overdue = (datetime.now().date() - due_date.date()).days
            due_text = f" - ⚠️ Retard: {days_overdue}j"
        else:
            days_until = (due_date.date() - datetime.now().date()).days
            due_text = f" - Échéance: dans {days_until}j"

    return f"• #{task_id_short} - {name}{priority_text}{due_text}"
```

### Project Structure Notes

**Nouveaux fichiers** :
- `database/migrations/020_add_due_date_to_tasks.sql`
- `bot/handlers/task_commands.py`
- `tests/unit/bot/test_task_commands.py`
- `tests/e2e/bot/test_task_management_e2e.py`

**Fichiers modifiés** :
- `bot/handlers/commands.py` (ajouter /taches dans help text)
- `bot/main.py` (enregistrer nouveaux handlers)
- `config/trust_levels.yaml` (section task_management)
- `docs/telegram-user-guide.md` (documentation commandes)
- Story 4.2 acceptance criteria (ajouter section tâches dans briefing)

**Alignement** : Suit l'arborescence flat de Epic 1, pattern établi par Stories 1.9-1.11.

### Libraries & Dependencies

**Aucune nouvelle dépendance**. Utilise :
- `python-telegram-bot` (déjà présent, Story 1.9)
- `asyncpg` (déjà présent, socle PostgreSQL)
- `structlog` (logs structurés, standard Friday 2.0)
- `pydantic` (ActionResult, middleware models Story 1.6)

### Testing Strategy

**Unit tests** :
- Mocker `db_pool.acquire()` et `conn.fetch()` / `conn.execute()`
- Tester chaque flag (-done, -overdue, -urgent, search, -v) séparément
- Cas edge : liste vide, tâche déjà complétée, ID invalide, query vide

**E2E tests** :
- Base PostgreSQL réelle (test_database)
- Workflow complet : créer tâche (Story 4.6) → lister `/taches` → compléter `/tache complete`
- Vérifier briefing contient section tâches

**Coverage attendue** : >90% sur task_commands.py.

### References

- [CLAUDE.md](_docs/architecture-friday-2.0.md) — Principes Progressive Disclosure, Trust Layer
- [Story 1.6](_bmad-output/implementation-artifacts/1-6-trust-layer-middleware.md) — Pattern @friday_action
- [Story 1.9](_bmad-output/implementation-artifacts/1-9-bot-telegram-core-topics.md) — Architecture bot Telegram
- [Story 1.10](_bmad-output/implementation-artifacts/1-10-bot-telegram-inline-buttons-validation.md) — Pattern inline buttons
- [Story 1.11](_bmad-output/implementation-artifacts/1-11-commandes-telegram-trust-budget.md) — Pattern commandes consultation
- [Story 4.2 (backlog)](c:\Users\lopez\Desktop\Friday 2.0\_bmad-output\planning-artifacts\epics-mvp.md#story-42--briefing-matinal-8h) — Briefing matinal 8h (sera modifié)
- [Story 4.6 (ready-for-dev)](_bmad-output/implementation-artifacts/4-6-agent-conversationnel-task-dispatcher.md) — Création tâches via agent conversationnel
- [Migration 003](database/migrations/003_core_config.sql) — Schema core.tasks actuel
- [docs/telegram-user-guide.md](docs/telegram-user-guide.md) — Documentation utilisateur

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)

### Completion Notes List

- Story créée suite à gap critique identifié par Mainteneur
- Dépend de Story 4.6 (création tâches) et Story 4.2 (briefing — en backlog)
- Migration 020 nécessaire pour ajouter `due_date`
- Pattern établi par Stories 1.9-1.11 suivi
- Trust Layer intégré (AC4, AC5)
- 18 tests minimum (15 unit + 3 E2E)

### File List

**À créer** :
- database/migrations/020_add_due_date_to_tasks.sql
- bot/handlers/task_commands.py
- tests/unit/bot/test_task_commands.py
- tests/e2e/bot/test_task_management_e2e.py

**À modifier** :
- bot/handlers/commands.py
- bot/main.py
- config/trust_levels.yaml
- docs/telegram-user-guide.md
- _bmad-output/planning-artifacts/epics-mvp.md (Story 4.2 AC update)
