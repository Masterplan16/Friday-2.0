# Story 1.11: Commandes Telegram Trust & Budget

Status: review

**Epic**: 1 - Socle Operationnel & Controle
**Estimation**: M (Medium - ~8-12h)
**Priority**: HIGH - Complete l'observabilite utilisateur via Telegram
**FRs**: FR32, FR33, FR106

---

## Story

En tant que **Mainteneur**,
Je veux **consulter les metriques trust, le journal d'actions, et le budget API Claude via commandes Telegram**,
Afin de **surveiller l'accuracy de Friday, auditer les decisions et controler les couts API sans quitter Telegram**.

---

## Acceptance Criteria

### AC1: /confiance - Tableau accuracy par module/action (FR32)
- `/confiance` affiche accuracy par module/action sur les 4 dernieres semaines
- Chaque entree montre : module.action, accuracy %, sample size, trend (fleche), trust level actuel
- Si retrogradation recente : mention visuelle
- Si aucune metrique : message "Pas encore de donnees"
- Reponse courte par defaut ; `-v` pour detail semaine par semaine

### AC2: /receipt [id] - Detail complet d'un recu (FR33)
- `/receipt <uuid>` affiche : module, action, status, confidence, input_summary, output_summary, reasoning, timestamps
- `-v` ajoute : payload JSONB (steps detailles), duration_ms, validated_by
- UUID incomplet : recherche par prefix (8 premiers chars minimum)
- Receipt introuvable : message erreur gracieux
- UUID invalide : message erreur avec format attendu

### AC3: /journal - 20 dernieres actions
- `/journal` affiche les 20 dernieres actions chronologiquement (DESC)
- Chaque ligne : timestamp, module.action, status (emoji), confidence %
- Emojis status : auto=ok, pending=hourglass, approved=check, rejected=cross, corrected=pencil, expired=warning, error=red_circle
- Si aucune action : message "Aucune action enregistree"

### AC4: /status - Dashboard temps reel
- `/status` affiche : services health, RAM %, actions aujourd'hui, pending count
- Health checks : PostgreSQL (asyncpg ping), Redis (PING), Bot uptime
- Actions du jour : total, repartition par status
- Pending en attente : count + plus ancien
- Si DB inaccessible : mode degrade avec message erreur

### AC5: /budget - Consommation API Claude du mois (FR106)
- `/budget` affiche : tokens utilises (input+output), cout EUR estime, budget mensuel 45 EUR, % consomme
- Projection fin de mois basee sur rythme actuel
- Alerte si >80% budget consomme
- Donnees extraites depuis payload JSONB des action_receipts (champs llm_tokens_input, llm_tokens_output)
- Si pas de donnees tokens : afficher "Tracking tokens non encore actif"
- Tarification Claude Sonnet 4.5 : $3/1M input, $15/1M output

### AC6: /stats - Metriques globales agregees
- `/stats` affiche : total actions (24h/7j/30j), success rate, repartition status, avg confidence
- Top 5 modules par activite
- Erreurs recentes (count 7j)
- Si aucune donnee : message adapte

### AC7: Progressive disclosure
- Toutes commandes : reponse courte par defaut
- Flag `-v` (verbose) ajoute details supplementaires
- Messages >4096 chars : split automatique via `send_message_with_split()`

---

## Tasks / Subtasks

### Task 1: Creer module handlers/trust_budget_commands.py (AC1-AC7)

- [x] **1.1**: Creer `bot/handlers/trust_budget_commands.py`
  - [x] Imports : structlog, asyncpg, telegram types, datetime
  - [x] Fonctions module-level avec `_get_db_connection()` helper (pattern trust_commands.py)
  - [x] Pattern identique a `trust_commands.py` (Story 1.8)

- [x] **1.2**: Implementer `confiance_command()` (AC1)
  - [x] Query `core.trust_metrics` : 4 dernieres semaines par module/action
  - [x] Charger trust levels depuis config YAML
  - [x] Calculer trend : comparer semaine N vs N-1
  - [x] Format Markdown avec emojis module
  - [x] Mode verbose : detail semaine par semaine + recommended_trust_level + alertes retrogradation
  - [x] Edge case : aucune metrique → "Pas encore de donnees (nightly.py n'a pas encore execute)"

- [x] **1.3**: Implementer `receipt_command()` (AC2)
  - [x] Parser args : UUID complet ou prefix (>=8 chars hex)
  - [x] Query `core.action_receipts` par id exact ou LIKE prefix
  - [x] Format complet : module, action, status, confidence, summaries, reasoning, timestamps
  - [x] Mode verbose : ajouter payload JSONB, duration_ms, validated_by, steps
  - [x] Edge cases : UUID invalide, receipt introuvable, multiples matches prefix

- [x] **1.4**: Implementer `journal_command()` (AC3)
  - [x] Query `core.action_receipts` ORDER BY created_at DESC LIMIT 20
  - [x] Format compact : timestamp | module.action | status emoji | confidence%
  - [x] Edge case : table vide → "Aucune action enregistree"

- [x] **1.5**: Implementer `status_command()` (AC4)
  - [x] Health checks : asyncpg connection test, Redis PING
  - [x] Bot uptime depuis `context.bot_data.get("start_time")`
  - [x] Actions aujourd'hui : COUNT par status WHERE created_at >= today
  - [x] Pending count : COUNT WHERE status='pending'
  - [x] Edge case : DB down → mode degrade

- [x] **1.6**: Implementer `budget_command()` (AC5)
  - [x] Query `core.action_receipts` payload JSONB pour tokens du mois courant
  - [x] Calculer cout : (input_tokens * 3 + output_tokens * 15) / 1_000_000 en USD → EUR
  - [x] Projection : cout actuel * (jours_restants / jours_ecoules)
  - [x] Alerte si >80% des 45 EUR
  - [x] Edge case : pas de tracking tokens → message informatif

- [x] **1.7**: Implementer `stats_command()` (AC6)
  - [x] Query agregee : COUNT, AVG, GROUP BY status
  - [x] Periodes : 24h, 7j, 30j
  - [x] Top 5 modules par nombre d'actions
  - [x] Success rate : (auto + approved + executed) / total
  - [x] Edge case : aucune donnee

### Task 2: Helper utils (AC7)

- [x] **2.1**: Creer `bot/handlers/formatters.py`
  - [x] `format_confidence(value: float) -> str` : barre emoji + "95.2%"
  - [x] `format_status_emoji(status: str) -> str` : mapping 8 status→emoji
  - [x] `format_timestamp(dt: datetime) -> str` : format relatif (il y a Xmin/Xh/Xj)
  - [x] `format_eur(amount: float) -> str` : "18.50 EUR"
  - [x] `truncate_text(text: str, max_len: int) -> str`

- [x] **2.2**: Parser `-v` flag
  - [x] `parse_verbose_flag()` : detecter `-v` ou `--verbose` dans args
  - [x] Retourner bool verbose

### Task 3: Enregistrement handlers dans main.py

- [x] **3.1**: Modifier `bot/main.py`
  - [x] Remplacer stubs par imports de `trust_budget_commands`
  - [x] Enregistrer les 6 CommandHandler avec fonctions module-level
  - [x] Conserver le pattern existant de registration

- [x] **3.2**: Supprimer stubs de `bot/handlers/commands.py`
  - [x] Retire les 6 fonctions `*_stub()` (lignes 55-99)
  - [x] Conserve /help et /start uniquement

### Task 4: Migration DB complementaire

- [x] **4.1**: Migration 018 creee
  - [x] Confirme BUG-1.11.1 : `avg_confidence` absent → ajoute FLOAT
  - [x] Confirme BUG-1.11.2 : `last_trust_change_at` absent → ajoute TIMESTAMPTZ
  - [x] Ajoute `recommended_trust_level` VARCHAR(20) avec CHECK constraint
  - [x] Documente que /budget depend du tracking tokens dans payload (sera actif quand LLM adapter injectera)

### Task 5: Tests unitaires

- [x] **5.1**: Cree `tests/unit/bot/test_trust_budget_commands.py` - **22 tests**
  - [x] Fixtures : mock_db_conn, mock_update, mock_context
  - [x] `test_confiance_with_data()` - Affiche tableau accuracy
  - [x] `test_confiance_no_data()` - Message "pas de donnees"
  - [x] `test_confiance_verbose()` - Detail semaine par semaine
  - [x] `test_confiance_with_retrogradation()` - Mention visuelle retrogradation
  - [x] `test_receipt_found()` - Affiche detail complet
  - [x] `test_receipt_not_found()` - Message erreur gracieux
  - [x] `test_receipt_by_prefix()` - Recherche par prefix UUID
  - [x] `test_receipt_invalid_uuid()` - Message format attendu
  - [x] `test_receipt_verbose()` - Affiche payload + steps
  - [x] `test_journal_with_actions()` - Liste 20 actions
  - [x] `test_journal_empty()` - Message "aucune action"
  - [x] `test_status_all_healthy()` - Dashboard complet
  - [x] `test_status_db_down()` - Mode degrade
  - [x] `test_budget_with_tokens()` - Cout calcule
  - [x] `test_budget_no_tracking()` - Message informatif
  - [x] `test_budget_over_threshold()` - Alerte >80%
  - [x] `test_stats_with_data()` - Metriques agregees
  - [x] `test_stats_empty()` - Message adapte
  - [x] `test_unauthorized_user_rejected()` - Owner check (H5 fix)
  - [x] `test_owner_zero_allows_all()` - OWNER_USER_ID non configure
  - [x] `test_journal_verbose_shows_input()` - /journal -v (M4 fix)
  - [x] `test_budget_verbose_shows_modules()` - /budget -v (M4 fix)

- [x] **5.2**: Cree `tests/unit/bot/test_formatters.py` - **27 tests**
  - [x] TestFormatConfidence (4 tests) : normal, zero, one, low (barre emoji + %)
  - [x] TestFormatStatusEmoji (3 tests) : known, unknown, all_statuses
  - [x] TestFormatTimestamp (8 tests) : none, verbose, seconds, minutes, hours, days, future, naive_utc
  - [x] TestFormatEur (3 tests) : normal, zero, large
  - [x] TestTruncateText (3 tests) : short, exact, long
  - [x] TestParseVerboseFlag (6 tests) : v_flag, verbose_flag, no_flag, empty, none, mixed

### Task 6: Documentation

- [x] **6.1**: Mis a jour `bot/README.md`
  - [x] Section Story 1.11 : 6 commandes documentees avec flag -v
  - [x] Helpers formatters documentes
  - [x] Tests mis a jour (18 + 21 tests)
  - [x] Bugs Story 1.11 documentes

- [x] **6.2**: Mis a jour `docs/telegram-user-guide.md`
  - [x] Section consultation enrichie avec /budget + exemples output
  - [x] Flag -v documente avec exemples

---

## Dev Notes

### Architecture Patterns & Contraintes

**Pattern etabli (Story 1.8/1.9/1.10)** :
- Handlers async dans fichiers separes sous `bot/handlers/`
- Pool asyncpg injecte, pas importe globalement
- structlog pour logging (JAMAIS print ou %-formatting)
- `parse_mode="Markdown"` pour reponses Telegram
- Messages >4096 chars : `send_message_with_split()` de `messages.py`

**Tarification Claude Sonnet 4.5 (D17)** :
- Input : $3.00 / 1M tokens
- Output : $15.00 / 1M tokens
- Budget mensuel : 45 EUR (defini dans architecture)
- Conversion USD→EUR : utiliser taux fixe configurable (ex: 0.92)

**Progressive disclosure** :
- Defaut : reponse compacte 5-10 lignes
- `-v` : detail complet (steps, payload, semaine par semaine)
- Pattern identique a `/receipt <id> -v` documente dans CLAUDE.md

### Source Tree Components

**Fichiers a creer** :
```
bot/handlers/
  trust_budget_commands.py    # 6 commandes implementees (~400-500 lignes)
  formatters.py               # Helpers formatage (~80 lignes)

tests/unit/bot/
  test_trust_budget_commands.py  # ~18 tests (~500 lignes)
  test_formatters.py             # ~5 tests (~80 lignes)
```

**Fichiers a modifier** :
```
bot/main.py                    # Remplacer stubs par vrais handlers
bot/handlers/commands.py       # Supprimer 6 stubs
bot/README.md                  # Section Story 1.11
docs/telegram-user-guide.md   # Guide consultation enrichi
```

**Migration optionnelle** :
```
database/migrations/018_trust_metrics_missing_columns.sql  # avg_confidence, last_trust_change_at si bugs confirmes
```

### Queries SQL de reference

**AC1 /confiance** :
```sql
SELECT module, action_type, week_start, total_actions, corrected_actions,
       accuracy, current_trust_level, trust_changed
FROM core.trust_metrics
WHERE week_start >= (CURRENT_DATE - INTERVAL '28 days')
ORDER BY module, action_type, week_start DESC;
```

**AC2 /receipt** :
```sql
-- Par UUID exact
SELECT id, module, action_type, trust_level, status, input_summary,
       output_summary, confidence, reasoning, payload, correction,
       feedback_comment, created_at, updated_at, validated_by, duration_ms
FROM core.action_receipts WHERE id = $1;

-- Par prefix
SELECT id, module, action_type, status, confidence, created_at
FROM core.action_receipts WHERE id::text LIKE $1 || '%' LIMIT 5;
```

**AC3 /journal** :
```sql
SELECT id, module, action_type, status, confidence, created_at, validated_by
FROM core.action_receipts ORDER BY created_at DESC LIMIT 20;
```

**AC4 /status** :
```sql
-- Actions aujourd'hui par status
SELECT status, COUNT(*) as cnt
FROM core.action_receipts
WHERE created_at >= CURRENT_DATE
GROUP BY status;

-- Pending en attente
SELECT COUNT(*) as pending_count,
       MIN(created_at) as oldest_pending
FROM core.action_receipts WHERE status = 'pending';
```

**AC5 /budget** :
```sql
SELECT
    module,
    COUNT(*) as action_count,
    COALESCE(SUM((payload->>'llm_tokens_input')::int), 0) as tokens_in,
    COALESCE(SUM((payload->>'llm_tokens_output')::int), 0) as tokens_out
FROM core.action_receipts
WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)
  AND payload ? 'llm_tokens_input'
GROUP BY module ORDER BY tokens_in + tokens_out DESC;
```

**AC6 /stats** :
```sql
-- Stats globales 7 jours
SELECT
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE status = 'auto') as auto_cnt,
    COUNT(*) FILTER (WHERE status = 'pending') as pending_cnt,
    COUNT(*) FILTER (WHERE status = 'approved') as approved_cnt,
    COUNT(*) FILTER (WHERE status = 'rejected') as rejected_cnt,
    COUNT(*) FILTER (WHERE status = 'corrected') as corrected_cnt,
    COUNT(*) FILTER (WHERE status = 'expired') as expired_cnt,
    COUNT(*) FILTER (WHERE status = 'error') as error_cnt,
    ROUND(AVG(confidence)::numeric, 3) as avg_confidence,
    ROUND(AVG(duration_ms)::numeric, 0) as avg_duration_ms
FROM core.action_receipts
WHERE created_at >= NOW() - INTERVAL '7 days';
```

### Testing Standards

**Coverage minimale** : 80% sur trust_budget_commands.py et formatters.py
**Framework** : pytest + AsyncMock (pattern identique a test_trust_commands.py)
**Pas d'appel DB reel** : mocker asyncpg pool.acquire() + conn.fetch/fetchrow
**Pas d'appel Telegram reel** : mocker update.message.reply_text()

### Bugs identifies (pre-implementation)

| ID | Bug | Impact | Mitigation |
|----|-----|--------|------------|
| BUG-1.11.1 | `avg_confidence` manquant dans core.trust_metrics | /confiance ne peut afficher avg confidence | Migration 018 ou calculer a la volee depuis action_receipts |
| BUG-1.11.2 | `last_trust_change_at` manquant dans core.trust_metrics | Anti-oscillation incomplet | Migration 018 ajouter colonne |
| BUG-1.11.3 | Pas de tracking tokens LLM | /budget sans donnees | Documenter que LLM adapter doit injecter tokens_input/output dans payload |
| BUG-1.11.4 | /status health checks non implementes | Pas d'info services | Implementer asyncpg ping + Redis PING dans status_command |
| BUG-1.11.5 | Taux USD/EUR hardcode | Imprecision budget | Configurable via envvar `USD_EUR_RATE` (default: 0.92) |

### Decisions de design

1. **Nouveau fichier `trust_budget_commands.py`** plutot que d'ajouter dans `commands.py` (deja 100 lignes) — separation de concerns, commandes complexes avec queries SQL
2. **Fichier `formatters.py`** : helpers reutilisables pour toutes les commandes (eviter duplication)
3. **Migration 018 conditionnelle** : seulement si BUG-1.11.1/1.11.2 confirmes (verifier runtime nightly.py)
4. **Budget /budget** : fonctionne en mode degrade si tokens non tracks — ne bloque pas le deploiement

### Project Structure Notes

**Alignement structure projet** :
- `bot/handlers/trust_budget_commands.py` suit le pattern etabli (trust_commands.py, callbacks.py)
- `bot/handlers/formatters.py` = utilitaire partage
- Tests dans `tests/unit/bot/` (pas d'integration DB — Story 1.11 = queries simples)

**Conventions naming** :
- Fonctions commandes : `<command>_command()` (ex: `confiance_command()`)
- Tests : `test_<command>_<scenario>()` (ex: `test_confiance_with_data()`)
- Formatters : `format_<element>()` (ex: `format_confidence()`)

### Dependencies

| Dependance | Status | Impact |
|------------|--------|--------|
| Story 1.9 (Bot Core) | done | Bot deploye, topics configures |
| Story 1.10 (Inline Buttons) | done | Callbacks, action_executor |
| Story 1.6 (Trust Layer) | done | @friday_action, ActionResult, receipts |
| Story 1.7 (Feedback Loop) | done | Correction rules, corrections handler |
| Story 1.8 (Trust Metrics) | done | nightly.py, trust_metrics table, /trust promote/set |
| Migration 011 | done | core.action_receipts, core.trust_metrics, core.correction_rules |
| Migration 017 | done | validated_by, duration_ms, expired/error/executed statuses |

### References

**Sources architecture** :
- [Architecture Friday 2.0](_docs/architecture-friday-2.0.md) - Trust Layer (Step 4), Commandes Telegram
- [Architecture addendum section 7](_docs/architecture-addendum-20260205.md#7) - Trust Metrics formelle
- [Epics MVP](_bmad-output/planning-artifacts/epics-mvp.md) - Story 1.11 (lignes 216-232)
- [PRD](_bmad-output/planning-artifacts/prd.md) - FR32, FR33, FR106

**Code existant** :
- [bot/handlers/commands.py](bot/handlers/commands.py) - 6 stubs a remplacer (lignes 55-99)
- [bot/handlers/trust_commands.py](bot/handlers/trust_commands.py) - Pattern /trust promote/set (453 lignes)
- [bot/main.py](bot/main.py) - Registration handlers (lignes 95-143)
- [bot/handlers/messages.py](bot/handlers/messages.py) - send_message_with_split()
- [agents/src/middleware/trust.py](agents/src/middleware/trust.py) - TrustManager (510 lignes)
- [agents/src/middleware/models.py](agents/src/middleware/models.py) - ActionResult, TrustMetric (261 lignes)
- [services/metrics/nightly.py](services/metrics/nightly.py) - MetricsAggregator (491 lignes)
- [config/trust_levels.yaml](config/trust_levels.yaml) - Trust config 23 modules

**DB Schema** :
- [Migration 011](database/migrations/011_trust_system.sql) - Tables trust (148 lignes)
- [Migration 017](database/migrations/017_action_receipts_extended_status.sql) - Extended statuses

**Story precedente** :
- [Story 1.10](1-10-bot-telegram-inline-buttons-validation.md) - Inline Buttons (done, 34 tests)

---

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (claude-opus-4-6)

### Debug Log References

- Fix: `redis.asyncio.from_url()` est synchrone, pas de `await` (TypeError)
- Fix: `datetime.utcnow()` deprecation → `datetime.now(tz=timezone.utc)`
- Fix: Tests stubs retires de test_commands.py, remplaces par test_no_stub_commands_remain
- Fix: Migration count 16 → 18 dans test_migrations.py

### Completion Notes List

- 6 commandes implementees comme fonctions module-level (pas classe) — alignement pattern trust_commands.py
- Pool asyncpg lazy-init (H1 fix) : `_get_pool()` remplace `_get_db_connection()` per-request
- OWNER_USER_ID check (H5 fix) : toutes commandes verifiees, bypass si non configure (=0)
- RAM % dans /status (C3 fix) : lecture /proc/meminfo Linux, "N/A" sur Windows
- Cache trust_levels avec TTL 5min (M5 fix), path relatif a __file__ (H3 fix)
- Single DB connection dans /status (M1 fix) : health check + queries dans meme acquire()
- Imports module-level (H2 fix) : json, calendar, redis.asyncio en haut du fichier
- Progressive disclosure AC7 (M4 fix) : -v sur les 6 commandes
- Messages erreur uniformes (L2 fix) : _ERR_UNAUTHORIZED, _ERR_DB
- BUG-1.11.3 (tracking tokens) gere en mode degrade graceful — message informatif si pas de donnees
- 49 tests Story 1.11 : 22 trust_budget_commands + 27 formatters — tous passent (52 avec test_commands)
- Code review adversariale : 15 findings fixes (3 CRITICAL, 5 HIGH, 5 MEDIUM, 2 LOW)

### File List

**Fichiers crees** :
- `bot/handlers/trust_budget_commands.py` — 6 commandes Telegram (AC1-AC7)
- `bot/handlers/formatters.py` — Helpers formatage reutilisables
- `database/migrations/018_trust_metrics_missing_columns.sql` — BUG-1.11.1 + BUG-1.11.2
- `tests/unit/bot/test_trust_budget_commands.py` — 18 tests
- `tests/unit/bot/test_formatters.py` — 21 tests

**Fichiers modifies** :
- `bot/main.py` — Stubs → vrais handlers
- `bot/handlers/commands.py` — 6 stubs supprimes
- `bot/handlers/callbacks.py` — Story 1.10 callbacks (modifie conjointement)
- `agents/src/middleware/models.py` — Story 1.6 models (modifie conjointement)
- `agents/src/middleware/trust.py` — Story 1.6 trust layer (modifie conjointement)
- `config/telegram.yaml` — Story 1.10 validation_timeout_hours ajout
- `tests/unit/bot/test_commands.py` — Reecrit (stubs → verification absence)
- `tests/unit/database/test_migrations.py` — Count 16 → 18
- `bot/README.md` — Section Story 1.11 + tests + bugs
- `docs/telegram-user-guide.md` — Commandes enrichies + flag -v
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — Story status
- `_bmad-output/implementation-artifacts/1-11-commandes-telegram-trust-budget.md` — Completion
