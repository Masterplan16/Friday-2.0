# Story 2.9: Migration Emails Progressive & Deploiement Pipeline

Status: in-progress

<!-- Tech-spec detaille : _docs/plan-deploiement-epic2-email.md (1600 lignes, 5 phases) -->

## Story

En tant que **Masterplan**,
Je veux **migrer les 108k emails historiques progressivement (par annee, du plus recent au plus ancien) et deployer le pipeline email en production**,
Afin de **donner a Friday la connaissance de mon historique email sans exploser le budget tokens**.

## Acceptance Criteria

1. **[AC1] Phase A — Corrections code pre-deploiement** (DONE)
   - Kill switch Redis (`/pipeline stop|start|status`) operationnel
   - Budget tracking via `core.llm_usage` table
   - Doublon bot Telegram supprime (garder `friday-bot`)
   - Credentials retires de la documentation
   - Classifier branche dans consumer.py (Claude Sonnet 4.5)
   - Semantique filtres corrigee (VIP/whitelist/blacklist)
   - Contraintes taille PJ (50 MB/PJ, 200 MB/email via env vars)
   - Validation credentials IMAP pre-deploiement

2. **[AC2] Phase B — Infrastructure VPS operationnelle** (PENDING)
   - SSH + Tailscale mesh (PC ↔ VPS via DNS Tailscale)
   - ProtonMail Bridge + supervision (`supervise-protonmail-bridge.ps1`)
   - Services socle (postgres, redis, caddy, gateway)
   - Migrations 001→034 appliquees

3. **[AC3] Phase C — Pipeline email live** (PENDING)
   - EmailEngine + 4 comptes IMAP configures
   - Webhooks EmailEngine → Gateway → Redis Streams
   - Bot Telegram + 5 topics operationnels
   - Consumer email-processor healthy
   - Test E2E : vrai email → classification → notification Telegram
   - Benchmark 100 emails (throughput mesuré)

4. **[AC4] Phase D — Migration historique progressive** (PENDING)
   - D.1 : Non-lus (139 emails) migres
   - D.2 : 2026 (~1500 emails) migres + validation integrite
   - D.3 : 2025 (~12000 emails) migres
   - D.4+ : Annees suivantes selon budget
   - Sample check 100 emails en mode propose AVANT chaque bulk auto
   - Validation integrite apres chaque etape annuelle

5. **[AC5] Scripts Story 2.9 operationnels** (DONE)
   - `migrate_emails.py` reecrit (API EmailEngine, 9 params CLI, checkpoint, graceful shutdown)
   - `extract_email_domains.py` reecrit (API EmailEngine, CSV strict, --apply)
   - `validate_migration.py` cree (compare EmailEngine vs PostgreSQL, seuil 5%)
   - `benchmark_consumer.py` cree (injection Redis Streams, mesure throughput)
   - `supervise-protonmail-bridge.ps1` cree (auto-restart + alertes Telegram)

6. **[AC6] Budget maitrise** (PENDING)
   - Budget recommande : $700 (baseline $390-450, realiste $585-675)
   - Point de decision apres D.3 si cout > $200
   - Plan B disponible (blacklist agressif, skip entites, skip embeddings, stop & evaluate)

## Tasks / Subtasks

### Phase A — Corrections code (DONE)

- [x] Task A.0: Safety Controls & Kill Switch
  - [x] A.0.1 Creer `bot/handlers/pipeline_control.py` (/pipeline stop|start|status, /budget)
  - [x] A.0.2 Enregistrer /pipeline dans bot/main.py + injecter Redis client
  - [x] A.0.3 Ajouter kill switch check dans consumer.py (`_is_pipeline_enabled()`)
  - [x] A.0.4 Env vars : PIPELINE_ENABLED, MAX_EMAILS_PER_HOUR, MAX_CLAUDE_COST_PER_DAY

- [x] Task A.1: Supprimer doublon bot docker-compose.yml
  - [x] A.1.1 Supprimer service `telegram-bot` (garder `friday-bot`)

- [x] Task A.2: Securiser _is_from_mainteneur()
  - [x] A.2.1 Remplacer emails placeholder par env var MAINTENEUR_EMAILS

- [x] Task A.3: Retirer credentials documentation
  - [x] A.3.1 Reecrire docs/emailengine-setup-4accounts.md (reference .env.email.enc)

- [x] Task A.4: Dockerfile + service email-processor
  - [x] A.4.1 Creer Dockerfile.email-processor
  - [x] A.4.2 Ajouter service email-processor dans docker-compose.yml (IP 172.20.0.26)
  - [x] A.4.3 Creer services/email_processor/healthcheck.py

- [x] Task A.5: Brancher classifier dans consumer.py
  - [x] A.5.1 Import classify_email depuis agents/src/agents/email/classifier.py
  - [x] A.5.2 Remplacer stub category="inbox" par appel classify_email()

- [x] Task A.6: Nouvelle semantique sender_filter
  - [x] A.6.1 Reecrire sender_filter.py (VIP=prioritaire, blacklist=skip analyse, whitelist=proceed)
  - [x] A.6.2 Reecrire sender_filter_commands.py (ajouter /vip, mise a jour semantique)
  - [x] A.6.3 Mettre a jour consumer.py (integration nouvelle semantique + _log_filter_savings)

- [x] Task A.7: Supprimer fix-ssh-port.sh
  - [x] A.7.1 Supprimer scripts/fix-ssh-port.sh (obsolete)

- [x] Task A.8: Contraintes taille PJ
  - [x] A.8.1 Ajouter MAX_SINGLE_ATTACHMENT_BYTES + MAX_TOTAL_ATTACHMENTS_BYTES (env vars)
  - [x] A.8.2 Modifier attachment_extractor.py (check individuel + check total dans boucle)
  - [x] A.8.3 Modifier attachment.py (MAX_ATTACHMENT_SIZE_BYTES = 50 Mo)

- [x] Task A.9: Script validation credentials IMAP
  - [x] A.9.1 Creer scripts/test_imap_connections.py (4 comptes, count messages, latence)

- [x] Task Mig033: Migration 033 sender_filters
  - [x] Mig033.1 CHECK constraint ('vip', 'whitelist', 'blacklist') — remplace ('whitelist', 'blacklist', 'neutral')
  - [x] Mig033.2 Index partiel VIP (idx_sender_filters_vip)

- [x] Task Mig034: Migration 034 llm_usage
  - [x] Mig034.1 Creer table core.llm_usage (remplace core.api_usage inexistante)
  - [x] Mig034.2 Index timestamp, provider+model, daily, context

### Phase B — Infrastructure VPS (PENDING — requiert VPS)

- [ ] Task B.1: Verifier SSH vers VPS
- [ ] Task B.2: Verifier Tailscale mesh (DNS pc-mainteneur ↔ vps-friday)
- [ ] Task B.3: ProtonMail Bridge + supervision
- [ ] Task B.4: Git pull sur VPS
- [ ] Task B.5: Secrets (cle age, dechiffrer .env.enc + .env.email.enc)
- [ ] Task B.6: Services socle (docker compose up -d postgres redis)
- [ ] Task B.7: Migrations (apply_migrations.py 001→034)
- [ ] Task B.8: Gateway + Caddy + healthcheck

### Phase C — Pipeline email live (PENDING — requiert Phase B)

- [ ] Task C.1: Services email (emailengine, presidio)
- [ ] Task C.2: Setup 4 comptes IMAP (setup_emailengine_4accounts.py)
- [ ] Task C.3: Webhooks EmailEngine
- [ ] Task C.4: Telegram supergroup + 5 topics
- [ ] Task C.5: Bot + Consumer (docker compose up -d)
- [ ] Task C.6: Test bot (/help)
- [ ] Task C.7: Test E2E (vrai email → classification → Telegram)
- [ ] Task C.7.5: Benchmark 100 emails (benchmark_consumer.py)
- [ ] Task C.8: Test filtres (/blacklist, /vip, /filters)
- [ ] Task C.9: Activer pipeline (PIPELINE_ENABLED=true)

### Phase D — Migration historique (PENDING — requiert Phase C)

- [ ] Task D.0: Scanner domaines (extract_email_domains.py → CSV → Telegram)
- [ ] Task D.1: Migrer non-lus (139 emails)
- [ ] Task D.2: Migrer 2026 (~1500 emails)
- [ ] Task D.3: Migrer 2025 (~12000 emails)
- [ ] Task D.4+: Annees suivantes (evaluer apres D.3)

### Story 2.9 — Scripts (DONE)

- [x] Task S1: Reecrire migrate_emails.py
  - [x] S1.1 Source API EmailEngine REST (remplace ingestion.emails_legacy)
  - [x] S1.2 9 params CLI (--since, --until, --unread-only, --limit, --trust-auto, --trust-propose, --resume, --reclassify, --account)
  - [x] S1.3 Checkpoint JSON (/tmp/migrate_checkpoint_{since}_{until}.json)
  - [x] S1.4 Graceful shutdown (SIGINT/SIGTERM → sauvegarde checkpoint)
  - [x] S1.5 Sample check obligatoire (100 emails propose avant bulk auto)

- [x] Task S2: Reecrire extract_email_domains.py
  - [x] S2.1 Source API EmailEngine REST (headers seulement, 0 token)
  - [x] S2.2 Format CSV strict (domain, email_count, suggestion, action)
  - [x] S2.3 Mode --apply (valide CSV + INSERT core.sender_filters)
  - [x] S2.4 Validation CSV (headers, domain format, action valide)

- [x] Task S3: Creer validate_migration.py
  - [x] S3.1 Compare count EmailEngine API vs PostgreSQL
  - [x] S3.2 Seuil alerte 5% difference
  - [x] S3.3 argparse --since/--until

- [x] Task S4: Creer benchmark_consumer.py
  - [x] S4.1 Injection 100 faux emails Redis Streams (bypass EmailEngine)
  - [x] S4.2 10 templates emails realistes (100-200 mots chacun)
  - [x] S4.3 Mesure throughput, latence, cout tokens
  - [x] S4.4 --cleanup pour nettoyage donnees benchmark

- [x] Task S5: Creer supervise-protonmail-bridge.ps1
  - [x] S5.1 Detection auto nom process Bridge (multi-versions)
  - [x] S5.2 Auto-restart si process down
  - [x] S5.3 Alertes Telegram (topic System)
  - [x] S5.4 Check toutes les 5 minutes

## Dev Notes

### Architecture Pipeline Email

```
EmailEngine (4 comptes IMAP)
  → Webhook → Gateway (FastAPI)
  → Redis Streams emails:received
  → Consumer (email-processor)
    → check_sender_filter()
      ├─ blacklist → skip analyse, category="blacklisted" [ECONOMIE $0.006]
      ├─ VIP → flag is_vip, classify prioritaire
      ├─ whitelist → classify normalement
      └─ non liste → classify normalement
    → Presidio anonymize
    → classify_email() (Claude Sonnet 4.5)
    → store DB (ingestion.emails)
    → extract_attachments() (si PJ)
    → Telegram notification (topic Email)
```

### Cout estimé migration 108k emails

```
108 386 emails totaux
  - blacklist (~30-40%) : ~35-40k emails skip → $0
  = ~65-75k emails traites
  × $0.006/email (classification + extraction entites + embeddings)
  = ~$390-450 cout baseline
  × 1.5 (marge erreur 50%)
  = ~$585-675 cout realiste
  Budget recommande : $700
```

### Fichiers crees/modifies Phase A

**Modifies (11) :**
- docker-compose.yml, consumer.py, sender_filter.py, attachment_extractor.py,
  attachment.py, sender_filter_commands.py, bot/main.py,
  emailengine-setup-4accounts.md, 033_sender_filters.sql,
  migrate_emails.py, extract_email_domains.py

**Crees (8) :**
- pipeline_control.py, Dockerfile.email-processor, healthcheck.py,
  034_llm_usage_tracking.sql, test_imap_connections.py,
  validate_migration.py, benchmark_consumer.py, supervise-protonmail-bridge.ps1

**Supprimes (2) :**
- fix-ssh-port.sh, 034_tokens_saved_by_filters.sql

### Tech-spec reference

Specification complete : `_docs/plan-deploiement-epic2-email.md` (v2.3, 1600 lignes)
- Review adversariale v4 completee (6 corrections finales)
- Phases B/C/D = operations VPS (pas de code a ecrire)

## File List

- `bot/handlers/pipeline_control.py` — /pipeline [stop|start|status], /budget (NEW)
- `bot/main.py` — Import pipeline_control, handler /pipeline, Redis client (MODIFIED)
- `docker-compose.yml` — Suppression telegram-bot, ajout email-processor (MODIFIED)
- `services/email_processor/consumer.py` — Kill switch, classifier, filter semantics (MODIFIED)
- `services/email_processor/healthcheck.py` — Healthcheck consumer (NEW)
- `Dockerfile.email-processor` — Docker image email-processor (NEW)
- `agents/src/agents/email/sender_filter.py` — VIP/blacklist/whitelist semantics (MODIFIED)
- `agents/src/agents/email/attachment_extractor.py` — Limites taille PJ env vars (MODIFIED)
- `agents/src/models/attachment.py` — MAX_ATTACHMENT_SIZE_BYTES 50 Mo (MODIFIED)
- `bot/handlers/sender_filter_commands.py` — /vip command, nouvelle semantique (MODIFIED)
- `database/migrations/033_sender_filters.sql` — VIP CHECK constraint (MODIFIED)
- `database/migrations/034_llm_usage_tracking.sql` — core.llm_usage table (NEW, remplace 034_tokens_saved)
- `docs/emailengine-setup-4accounts.md` — Credentials retires (MODIFIED)
- `scripts/migrate_emails.py` — Reecriture complete API EmailEngine (MODIFIED)
- `scripts/extract_email_domains.py` — Reecriture complete CSV strict (MODIFIED)
- `scripts/validate_migration.py` — Validation integrite migration (NEW)
- `scripts/test_imap_connections.py` — Validation credentials IMAP (NEW)
- `scripts/supervise-protonmail-bridge.ps1` — Supervision Bridge Windows (NEW)
- `tests/load/benchmark_consumer.py` — Benchmark 100 emails Redis Streams (NEW)
