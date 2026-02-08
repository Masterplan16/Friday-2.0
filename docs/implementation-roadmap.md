# Friday 2.0 - Roadmap d'implémentation

**Date** : 2026-02-05
**Version** : 1.3.0 (ajout documents de référence, Story 1.7 Self-Healing, Story 2.5 Heartbeat)
**Status** : Architecture complète ✅ - Prêt pour implémentation

---

## 📚 **Documents de référence**

Ce PRD s'appuie sur la documentation suivante. Toute modification à ces documents DOIT être reflétée ici.

### Documents fondamentaux

| Document | Rôle | Contenu |
|----------|------|---------|
| [`_docs/architecture-friday-2.0.md`](_docs/architecture-friday-2.0.md) | Source de vérité architecturale | ~2500 lignes : infrastructure, stack tech, sécurité RGPD, graphe connaissances, Trust Layer |
| [`_docs/friday-2.0-analyse-besoins.md`](_docs/friday-2.0-analyse-besoins.md) | Vision produit | 23 modules fonctionnels, sources de données, interconnexions, contraintes |
| [`_docs/analyse-fonctionnelle-complete.md`](_docs/analyse-fonctionnelle-complete.md) | Validation architecture | ~1470 lignes : validation croisée besoins vs architecture |
| [`_docs/architecture-addendum-20260205.md`](_docs/architecture-addendum-20260205.md) | Clarifications techniques | Sections 1-11 : Presidio benchmark, pattern detection, RAM profiles, trust rétrogradation formelle, Telegram Topics |

### Guides techniques (par story)

| Document | Story associée | Contenu |
|----------|---------------|---------|
| [`docs/n8n-workflows-spec.md`](docs/n8n-workflows-spec.md) | Story 2, 4 | Spécifications 3 workflows Day 1 (Email, Briefing, Backup) |
| [`docs/testing-strategy-ai.md`](docs/testing-strategy-ai.md) | Toutes stories | Pyramide tests (80/15/5), métriques qualité, datasets |
| [`docs/secrets-management.md`](docs/secrets-management.md) | Story 1.4 | Guide age/SOPS : chiffrement, partage clés, rotation |
| [`docs/redis-streams-setup.md`](docs/redis-streams-setup.md) | Story 1.1 | Configuration Redis Streams : consumer groups, retry, recovery |
| [`docs/redis-acl-setup.md`](docs/redis-acl-setup.md) | Story 1.1 | Configuration Redis ACL : moindre privilège par service |
| [`docs/tailscale-setup.md`](docs/tailscale-setup.md) | Story 1.4 | Installation Tailscale, 2FA, device authorization |
| [`docs/presidio-mapping-decision.md`](docs/presidio-mapping-decision.md) | Story 1.5.1 | Décision mapping Presidio éphémère Redis (TTL 1h, pas PostgreSQL) |
| [`docs/ai-models-policy.md`](docs/ai-models-policy.md) | Story 2+ | Politique versionnage modèles IA, procédure upgrade, matrix décision |
| [`docs/pc-backup-setup.md`](docs/pc-backup-setup.md) | Backup | Guide setup PC Antonio pour rsync/Tailscale |
| [`docs/telegram-topics-setup.md`](docs/telegram-topics-setup.md) | Story 1.5.3 | Setup supergroup Telegram 5 topics, extraction script |
| [`docs/telegram-user-guide.md`](docs/telegram-user-guide.md) | Story 1.5.3 | Guide utilisateur commandes Telegram |
| [`docs/playwright-automation-spec.md`](docs/playwright-automation-spec.md) | Story 10+ | Spécification automatisation web (Carrefour Drive, etc.) |
| [`agents/docs/heartbeat-engine-spec.md`](agents/docs/heartbeat-engine-spec.md) | Story 2.5 | Spécification Heartbeat Engine (proactivité native) |

### Configuration et scripts

| Fichier | Story associée | Contenu |
|---------|---------------|---------|
| [`config/trust_levels.yaml`](config/trust_levels.yaml) | Story 1.5.2 | Configuration initiale trust levels 23 modules |
| [`tests/fixtures/README.md`](tests/fixtures/README.md) | Toutes stories | Guide création datasets tests IA |
| [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md) | Document vivant | Historique chronologique décisions architecturales |

---

## 📋 **Vue d'ensemble**

Friday 2.0 sera implémenté en **stories incrémentales** suivant le principe **KISS Day 1** : simple d'abord, refactoring seulement si douleur réelle.

**Philosophie** :
- Chaque story est **déployable** et apporte de la valeur
- Tests (unit + integ + E2E) inclus dans chaque story
- Trust Layer **AVANT** tout module métier (observabilité dès le début)

**Convention** : Les tâches `[ ]` sont à implémenter. Les `[x]` marquent les tâches effectivement terminées.

---

## 🎯 **Stories - Vue chronologique**

| Story | Nom | Durée | Dépendances | Status |
|-------|-----|-------|-------------|--------|
| **1** | Infrastructure de base | 3-5j | - | 📋 Conçue |
| **1.5** | Observability & Trust Layer | 3-4j | Story 1 | 📋 Conçue |
| **1.7** | Self-Healing Infrastructure | 1-2j | Story 1 | 📋 Conçue |
| **2** | Moteur Vie (Email) | 5-7j | Story 1.5, 1.7 | ⏳ En attente |
| **2.5** | Heartbeat Engine (Proactivité) | 1-2j | Story 2 | 📋 Conçue |
| **3** | Archiviste (OCR + Renommage) | 4-6j | Story 1.5 | ⏳ En attente |
| **4** | Briefing matinal | 2-3j | Story 2, 3 | ⏳ En attente |
| **5** | Plaud Note (Transcription) | 3-4j | Story 1.5, 2 | ⏳ En attente |
| **6** | Suivi Financier | 4-5j | Story 1.5, 3 | ⏳ En attente |
| **7** | Tuteur Thèse | 5-6j | Story 1.5 | ⏳ En attente |
| **8** | Veilleur Droit | 3-4j | Story 1.5 | ⏳ En attente |
| **9** | Agenda (multi-casquettes) | 3-4j | Story 2, 5 | ⏳ En attente |
| **10+** | Modules restants (Coach, Menus, Playwright, etc.) | Variable | Variable | ⏳ En attente |

**Durée totale estimée** : ~38-54 jours de développement (Stories 1-9 + 1.7 + 2.5)

---

## 📦 **Story 1 : Infrastructure de base**

### **Objectif**
Socle technique fonctionnel avec tous services Docker opérationnels.

### **Scope**

#### **1.1 Docker Compose**
- [ ] `docker-compose.yml` principal (PostgreSQL 16, Redis 7, Qdrant, n8n, Caddy)
- [ ] `docker-compose.dev.yml` (overrides dev)
- [ ] `docker-compose.services.yml` (services lourds résidents : Ollama, Whisper, Kokoro, Surya)
- [ ] `.env.example` avec toutes les variables requises
- [ ] `Makefile` (shortcuts : `make up`, `make logs`, `make restart`)
- **Réf.** : [`docs/redis-streams-setup.md`](docs/redis-streams-setup.md) (consumer groups), [`docs/redis-acl-setup.md`](docs/redis-acl-setup.md) (ACL moindre privilège)

#### **1.2 Base de données PostgreSQL**
- [ ] Migrations SQL 001-010 (alignées avec architecture Step 6) :
  - `001_init_schemas.sql` (schemas core, ingestion, knowledge)
  - `002_core_tables.sql` (users, config, jobs, audit, system_logs, tasks, events)
  - `003_ingestion_emails.sql` (table emails avec indexes)
  - `004_ingestion_documents.sql` (table documents)
  - `005_ingestion_files.sql` (table files)
  - `006_ingestion_transcriptions.sql` (table transcriptions)
  - `007_knowledge_entities.sql` (table entities)
  - `008_knowledge_relations.sql` (table relations)
  - `009_knowledge_embeddings.sql` (table embeddings metadata)
  - `010_pgcrypto.sql` (extension chiffrement pgcrypto + table anonymization_mappings)
- [ ] Script `scripts/apply_migrations.py` (exécution migrations)

#### **1.3 FastAPI Gateway**
- [ ] Structure `services/gateway/`
  - `main.py` (app FastAPI)
  - `routes/` (health, auth, emails, documents)
  - `schemas/` (Pydantic models)
  - `middleware/` (CORS, logging)
  - `config.py` (settings)
- [ ] Endpoint `/api/v1/health` (healthcheck étendu : PostgreSQL, Redis, Qdrant, n8n, services lourds)
- [ ] OpenAPI auto-générée (Swagger UI)

#### **1.4 Tailscale + Sécurité**
- [ ] Installation Tailscale VPS (script automatique)
- [ ] Hostname `friday-vps`
- [ ] ⚠️ **MANUEL** : Activer 2FA + device authorization dans dashboard Tailscale (https://login.tailscale.com/admin/settings/auth)
- [ ] Firewall : AUCUN port ouvert sur Internet public (SSH via Tailscale uniquement)
- [ ] Caddy configuré pour HTTPS interne mesh Tailscale
- [ ] Secrets chiffrés via age/SOPS (`.env.prod` jamais en clair dans git)
- **Réf.** : [`docs/tailscale-setup.md`](docs/tailscale-setup.md) (installation, 2FA), [`docs/secrets-management.md`](docs/secrets-management.md) (age/SOPS)

#### **1.5 Tests**
- [ ] Tests unitaires `scripts/apply_migrations.py`
- [ ] Test E2E `tests/e2e/test_story1_sanity.sh` (tous services démarrent + healthcheck OK)

### **Acceptance Criteria**

- AC1 : `docker compose up -d` démarre tous les services sans erreur
- AC2 : `GET /api/v1/health` retourne 200 avec statut de tous services
- AC3 : PostgreSQL avec 3 schemas créés (core, ingestion, knowledge) + 12 migrations appliquées (001-012 inclut emails_legacy)
- AC4 : Tailscale mesh opérationnel (VPS accessible via hostname `friday-vps`) + 2FA activé manuellement
- AC5 : Tests E2E passent (healthcheck OK)

### **Livrables**
- Infrastructure Docker Compose complète
- Base de données initialisée (12 migrations 001-012)
- Gateway API fonctionnel
- Tailscale configuré (2FA manuel activé)
- Tests E2E passent

---

## 📦 **Story 1.5 : Observability & Trust Layer**

### **Objectif**
Système de confiance et traçabilité opérationnel **AVANT tout module métier**.

### **Scope**

#### **1.5.1 Pipeline Presidio (RGPD - prérequis Story 2+)**
- [ ] Installation Presidio + spaCy-fr (`presidio-analyzer`, `presidio-anonymizer`, `fr_core_news_lg`)
- [ ] `agents/src/tools/anonymize.py` (fonctions `anonymize_text()` + `deanonymize_text()`)
- [ ] Tests unitaires anonymisation (dataset `tests/fixtures/pii_samples.json`)
- **Réf.** : [`docs/presidio-mapping-decision.md`](docs/presidio-mapping-decision.md) (mapping éphémère Redis TTL 1h, JAMAIS PostgreSQL)

#### **1.5.2 Middleware Trust**
- [ ] Migration SQL `011_trust_system.sql` (tables : action_receipts, correction_rules, trust_metrics)
- [ ] `agents/src/middleware/trust.py` :
  - Décorateur `@friday_action`
  - Modèle Pydantic `ActionResult`
  - Gestion trust levels (auto/propose/blocked)
- [ ] `config/trust_levels.yaml` (configuration initiale 23 modules) ✅ **CRÉÉ**

#### **1.5.3 Bot Telegram (Supergroup 5 Topics)**
- [ ] Structure `bot/`
  - `handlers/` (message, voice, document, callback)
  - `commands/` (start, status, journal, receipt, confiance, stats, trust)
  - `keyboards/` (inline buttons pour validation actions)
  - `media/transit/` (fichiers temporaires)
- [ ] Setup supergroup Telegram avec 5 topics spécialisés :
  - 💬 Chat & Proactive (DEFAULT) : Conversation bidirectionnelle, commandes, heartbeat
  - 📬 Email & Communications : Classifications, PJ, emails urgents
  - 🤖 Actions & Validations : Validations trust=propose, inline buttons
  - 🚨 System & Alerts : Santé système, RAM >85%, services down
  - 📊 Metrics & Logs : Actions auto, stats, logs
- [ ] Commandes implémentées :
  - `/status` : Dashboard temps réel (services, RAM, dernières actions)
  - `/journal [module]` : Liste 20 dernières actions (filtrable par module)
  - `/receipt <id> [-v]` : Détail action (-v = steps techniques)
  - `/confiance` : Tableau accuracy par module/action
  - `/stats` : Métriques globales semaine
  - `/trust set <module> <action> <level>` : Ajuster trust level manuellement
- **Réf.** : [`docs/telegram-topics-setup.md`](docs/telegram-topics-setup.md) (setup technique), [`docs/telegram-user-guide.md`](docs/telegram-user-guide.md) (guide utilisateur), [addendum §11](_docs/architecture-addendum-20260205.md) (spec complète)

#### **1.5.4 Validation inline Telegram**
- [ ] Trust=propose → Message Telegram avec boutons `[✅ Approuver] [❌ Rejeter] [✏️ Corriger]`
- [ ] Callback handlers (approve, reject, correct)
- [ ] Update `core.action_receipts.status` selon choix Antonio

#### **1.5.5 Alerting**
- [ ] `services/alerting/listener.py` (écoute Redis pub/sub)
- [ ] Events surveillés :
  - `pipeline.error` → Alerte Telegram immédiate
  - `service.down` → Alerte si service lourd down >5min
  - `trust.level.changed` → Notification rétrogradation auto
  - `ram.threshold.exceeded` → Alerte si RAM >85%

#### **1.5.6 Metrics nightly**
- [ ] `services/metrics/nightly.py` (calcul accuracy hebdomadaire)
- [ ] Cron 02:00 : Agrégation `core.trust_metrics`
- [ ] Auto-rétrogradation : accuracy <90% → trust level descend (auto → propose)

#### **1.5.7 Tests**
- [ ] Tests unitaires `@friday_action` decorator
- [ ] Tests intégration validation Telegram
- [ ] Tests auto-rétrogradation
- [ ] Tests Presidio anonymisation (dataset PII)
- [ ] Test E2E : action propose → validation Antonio → receipt updated
- **Réf.** : [`docs/testing-strategy-ai.md`](docs/testing-strategy-ai.md) (pyramide 80/15/5, datasets, métriques qualité)

### **Acceptance Criteria**

- AC1 : Décorateur `@friday_action` opérationnel (création receipts, gestion trust)
- AC2 : Bot Telegram répond aux 6 commandes trust (status, journal, receipt, confiance, stats, trust)
- AC3 : Action trust=propose → Telegram envoie inline buttons + attend validation
- AC4 : Alerting temps réel fonctionne (simulation `pipeline.error`)
- AC5 : Nightly metrics calcule accuracy + rétrograde si <90%
- AC6 : Presidio anonymise 100% des PII du dataset de test

### **Livrables**
- Pipeline Presidio opérationnel (prérequis RGPD)
- Middleware Trust complet
- Bot Telegram opérationnel (6 commandes)
- Système d'alerting temps réel
- Métriques et rétrogradation auto
- Tests passent

---

## 📦 **Story 1.7 : Self-Healing Infrastructure**

### **Objectif**
Automatiser la maintenance "contenant" (OS, Docker, monitoring) pour réduire charge opérationnelle de 4h/mois → 1h/mois.

### **Scope**

#### **1.7.1 Tier 1 : OS Auto-Maintenance**
- [ ] Config `unattended-upgrades` (auto-updates sécurité Linux + reboot 4h)
- [ ] Script `scripts/tier1-os/setup-unattended-upgrades.sh`
- [ ] Script `scripts/tier1-os/cleanup-disk.sh` (rotation logs Docker 7j, journald 30j, backups 30 dernières)
- [ ] Cron `0 3 * * *` pour cleanup-disk

#### **1.7.2 Tier 2 : Docker Auto-Recovery**
- [ ] Service `watchtower` dans `docker-compose.services.yml` (mode MONITOR_ONLY)
- [ ] Script `scripts/tier2-docker/monitor-restarts.sh` (alerte si >2 restarts/heure)
- [ ] Script `scripts/tier2-docker/auto-recover-ram.sh` (kill service lourd si RAM >90%)
- [ ] Script `scripts/tier2-docker/check-external-apis.sh` (healthcheck Mistral, EmailEngine, Qdrant)
- [ ] Crons :
  - `*/15 * * * *` : monitor-restarts
  - `*/5 * * * *` : auto-recover-ram
  - `*/30 * * * *` : check-external-apis

#### **1.7.3 Configuration centralisée**
- [ ] `config/crontab-friday.txt` (tous les crons Tier 1-2)
- [ ] `docker-compose.services.yml` : Ajout service watchtower
- [ ] Healthcheck avancés PostgreSQL/Redis (labels `com.friday.critical=true` + `max_restarts_per_hour`)

#### **1.7.4 Tests**
- [ ] Test unitaire `auto-recover-ram.sh` (simulation RAM >90% sans crasher VPS)
- [ ] Test E2E `test_self_healing.sh` :
  - Crash PostgreSQL → Auto-restart + Alerte Telegram
  - RAM 92% simulée → Kill Kokoro + Alerte
  - API Mistral down → Alerte (sans action)

### **Acceptance Criteria**

- AC1 : `unattended-upgrades` opérationnel (patch Linux auto + reboot 4h si nécessaire)
- AC2 : `cleanup-disk.sh` tourne daily (logs <7j, backups <30 dernières)
- AC3 : Watchtower détecte nouvelle version PostgreSQL → Telegram notif (pas de mise à jour auto)
- AC4 : PostgreSQL crash → Redémarre auto <30s + Alerte Telegram
- AC5 : RAM >90% → Service lourd (Kokoro/Surya/Ollama) tué + Alerte + Logs sauvegardés
- AC6 : Tous crons installés et fonctionnels (vérif `crontab -l`)

### **Livrables**
- Scripts Tier 1 (setup-unattended-upgrades, cleanup-disk)
- Scripts Tier 2 (monitor-restarts, auto-recover-ram, check-external-apis)
- Service watchtower configuré (MONITOR_ONLY)
- Crontab centralisé installé
- Tests E2E passent

### **Note : Tier 3-4 (futures stories)**
Tier 3 (détection connecteurs Playwright) et Tier 4 (pattern detection, trust drift) seront implémentés dans stories dédiées ultérieures.

**Philosophie** : Tier 1-2 = "contenant" (auto OK), Tier 3-4 = "contenu" (détection + validation humaine obligatoire)

---

## 📦 **Story 2 : Moteur Vie (Email Pipeline)**

### **Objectif**
Pipeline email complet : ingestion → classification → extraction → brouillons.

### **Scope**

#### **2.1 EmailEngine setup**
- [ ] Docker service EmailEngine
- [ ] Configuration 4 comptes IMAP Antonio
- [ ] Webhook vers n8n : `/webhook/emailengine`

#### **2.2 n8n Workflow Email Ingestion**
- [ ] `n8n-workflows/email-ingestion.json` (déjà spécifié)
- [ ] Nodes : Webhook → Validation → Classification → Insert PostgreSQL → Redis event
- [ ] Tests workflow (email test → vérif classification + insert)

#### **2.3 Agent Email (LangGraph)**
- [ ] `agents/src/agents/email/agent.py` :
  - `@friday_action(module="email", action="classify", trust_default="propose")`
  - Classification email (Mistral Nemo cloud)
  - Extraction tâches (détection TODO, deadlines)
  - Génération brouillon réponse (Mistral Medium, trust=blocked Day 1)
- [ ] Adaptateur LLM (`agents/src/adapters/llm.py`)
- [ ] Pipeline Presidio obligatoire avant classification (branché sur Story 1.5)
- **Réf.** : [`docs/ai-models-policy.md`](docs/ai-models-policy.md) (versionnage modèles : `-latest` dev, version explicite prod), [`docs/n8n-workflows-spec.md`](docs/n8n-workflows-spec.md) (workflow email-ingestion)

#### **2.4 Tests**
- [ ] Tests unitaires agent (mocks Mistral)
- [ ] Tests intégration classification (dataset `tests/fixtures/email_classification_dataset.json`) **REQUIS**
- [ ] Test E2E : Email webhook → Classification → Receipt créé → Telegram notif

### **Acceptance Criteria**

- AC1 : Email reçu → Webhook n8n → Classification → Insert PostgreSQL → Redis event
- AC2 : Classification accuracy ≥85% sur dataset validation
- AC3 : Brouillon réponse généré (trust=blocked, présentation seule)
- AC4 : Receipt créé avec trust=propose → Antonio valide via Telegram
- AC5 : Presidio anonymise PII avant LLM cloud (test avec dataset PII) **REQUIS**

### **Livrables**
- EmailEngine configuré (4 comptes)
- Workflow n8n Email Ingestion
- Agent Email LangGraph
- Pipeline Presidio intégré
- Tests passent (accuracy ≥85%)

---

## 📦 **Story 3 : Archiviste (OCR + Renommage)**

### **Objectif**
Pipeline document complet : upload → OCR → renommage intelligent → classement → indexation.

### **Scope**

#### **3.1 n8n Workflow File Processing**
- [ ] Watch dossier uploads → OCR Surya → Insert PostgreSQL → Redis event

#### **3.2 Agent Archiviste**
- [ ] `agents/src/agents/archiviste/agent.py` :
  - `@friday_action(module="archiviste", action="rename", trust_default="propose")`
  - Renommage intelligent (analyse OCR + Mistral)
  - Classification document (facture, contrat, article, etc.)
  - Extraction métadonnées (date, montant, vendeur)
- [ ] OCR integration (Surya + Marker)

#### **3.3 Tests**
- [ ] Tests intégration renommage (dataset `tests/fixtures/archiviste_dataset/`) **REQUIS**
- [ ] Test E2E : Upload PDF → OCR → Renommage → Receipt trust=propose

### **Acceptance Criteria**

- AC1 : Upload document via Telegram → OCR → Métadonnées extraites
- AC2 : Renommage accuracy ≥80% (exact match filename)
- AC3 : Classification document correcte
- AC4 : Receipt créé → Antonio valide nom → Document sync vers PC (Syncthing)

### **Livrables**
- Workflow n8n File Processing
- Agent Archiviste complet
- OCR Surya intégré
- Tests passent (accuracy ≥80%)

---

## 📦 **Story 2.5 : Heartbeat Engine (Proactivité native)**

### **Objectif**
Implémenter moteur de proactivité natif Friday (vs OpenClaw) : checks contextuels périodiques avec LLM décideur.

### **Scope**

#### **2.5.1 Core Heartbeat**
- [ ] Class `FridayHeartbeat` dans `agents/src/core/heartbeat.py` :
  - Interval configurable (default 30min)
  - LLM décide dynamiquement quoi vérifier (context-aware)
  - Quiet hours (22h-8h)
  - Registration checks avec priorités (high/medium/low)
- **Réf.** : [`agents/docs/heartbeat-engine-spec.md`](agents/docs/heartbeat-engine-spec.md) (spec complète Heartbeat Engine)

#### **2.5.2 Context Provider**
- [ ] `agents/src/core/context.py` :
  - `get_current_time_context()` : Heure, jour, weekend
  - `get_last_activity()` : Dernière interaction Antonio
  - `get_next_calendar_event()` : Prochain événement agenda

#### **2.5.3 Checks Day 1**
- [ ] `check_urgent_emails()` (priorité high) : Emails non lus >2h urgents
- [ ] `check_financial_alerts()` (priorité medium) : Anomalies financières
- [ ] `check_thesis_reminders()` (priorité low) : Deadlines thèses supervisées

#### **2.5.4 Configuration**
- [ ] `config/heartbeat.yaml` :
  - `interval_minutes: 30`
  - `quiet_hours: ["22:00", "08:00"]`
  - Activation par module (enabled: true/false)

#### **2.5.5 Intégration**
- [ ] `agents/src/main.py` : Démarrage Heartbeat au boot
- [ ] `/api/v1/heartbeat/status` : Endpoint monitoring (last run, next run, stats)
- [ ] Topic Telegram "💬 Chat & Proactive" : Messages heartbeat

#### **2.5.6 Tests**
- [ ] Tests unitaires context provider
- [ ] Tests intégration checks (mocks emails/finance)
- [ ] Test E2E : Heartbeat détecte email urgent → Notification Telegram Chat topic

### **Acceptance Criteria**

- AC1 : Heartbeat tourne interval 30min (pas pendant quiet hours 22h-8h)
- AC2 : LLM décide quels checks lancer selon contexte (ex: pas finance le weekend)
- AC3 : Email urgent non lu >2h → Heartbeat alerte dans topic "Chat & Proactive"
- AC4 : Endpoint `/api/v1/heartbeat/status` retourne stats (last_run, next_run, checks_executed)
- AC5 : Config `heartbeat.yaml` permet désactivation par module

### **Livrables**
- Heartbeat Engine opérationnel
- Context Provider
- 3 checks Day 1 (emails, finance, thesis)
- Configuration YAML
- Endpoint monitoring
- Tests passent

**Note** : Story 2.5 implémentée APRÈS Story 2 (Email Pipeline) car dépend module Email opérationnel.

---

## 📦 **Stories 4-9 : Modules métier**

*(Spécifications détaillées créées au fur et à mesure, selon priorisation Antonio)*

**Séquence suggérée** :
1. **Story 4** : Briefing matinal (agrégation données modules 2-3) — **Réf.** : [`docs/n8n-workflows-spec.md`](docs/n8n-workflows-spec.md) (workflow briefing-daily)
2. **Story 5** : Plaud Note (transcription → cascade actions)
3. **Story 6** : Suivi Financier (CSV import → classification → anomalies)
4. **Story 7** : Tuteur Thèse (analyse Google Docs → commentaires)
5. **Story 8** : Veilleur Droit (analyse contrats)
6. **Story 9** : Agenda (extraction événements emails/Plaud)
7. **Story 10+** : Modules restants (Coach sportif, Menus, Browser automation Playwright) — **Réf.** : [`docs/playwright-automation-spec.md`](docs/playwright-automation-spec.md)

---

## 🚀 **Migration & Mise en production**

### **Migration données existantes**

**Timing** : Après Story 2 (Email agent opérationnel)

**Script** : `scripts/migrate_emails.py` ✅ **CRÉÉ**

**Contenu** :
- 110 000 emails existants (4 comptes via EmailEngine)
- Checkpointing tous les 100 emails
- Retry exponentiel sur erreur
- Resume depuis dernier checkpoint
- Anonymisation Presidio avant classification (RGPD)
- **Durée estimée** : ~18-24h (incluant Presidio overhead + retry/backoff)
- **Coût estimé** : ~$20-24 USD (Mistral API)

**Calcul détaillé** (corrigé suite code review adversarial 2026-02-05 + volume réel 110k) :
- 110k emails × ~600 tokens avg (500 input + 100 output) = 66M tokens
- Mistral Nemo pricing : $0.15/1M tokens input + $0.15/1M tokens output
- Coût classification : 66M tokens × $0.30/1M = **$19.80 USD**
- Rate limit Mistral : 200 RPM → 110k / 200 = **550 minutes = 9.2h (classification seule)**
- Presidio overhead : ~150-200ms par email → 110k × 0.15s = **4.6h supplémentaires**
- Retry + backoff (estimation 5% échecs temporaires) : ~60-90 min
- **Durée totale réaliste** : 9.2h + 4.6h + 1.5h + marge sécurité = **~18-24h**
- **Coût total avec marge** : $19.80 + 20% buffer = **~$20-24 USD**

**Validation** :
- Test dry-run d'abord (`--dry-run`)
- Backup PostgreSQL avant migration
- Vérification post-migration (sample 100 emails)

### **Backup & Disaster Recovery**

**Workflow** : `n8n-workflows/backup-daily.json` (cron 03:00)

**Note** : Nightly metrics à 02:00, backup à 03:00 — pas de chevauchement.

**Test** : `tests/e2e/test_backup_restore.sh` ✅ **CRÉÉ**

**Frequence tests** : Mensuel (premier dimanche du mois)

**Réf.** : [`docs/pc-backup-setup.md`](docs/pc-backup-setup.md) (setup PC Antonio rsync/Tailscale, troubleshooting)

### **Fichiers restant a creer**

Les fichiers suivants sont references dans l'architecture mais n'existent pas encore. Ils devront etre crees dans leurs stories respectives :

| Fichier | Description | Story |
|---------|-------------|-------|
| `agents/src/tools/anonymize.py` | Integration Presidio (`anonymize_text()` + `deanonymize_text()`) | Story 1.5 |
| `agents/src/middleware/models.py` | Modele Pydantic `ActionResult` | Story 1.5 |
| `agents/src/middleware/trust.py` | Decorateur `@friday_action` | Story 1.5 |
| `scripts/apply_migrations.py` | Script d'execution des migrations SQL | Story 1 |
| `docker-compose.yml` | Services core (PostgreSQL, Redis, Qdrant, n8n, Caddy) | Story 1 |

> **Note** : Les fichiers deja crees sont marques **CREE** dans ce document : `config/trust_levels.yaml`, `scripts/migrate_emails.py`, `tests/e2e/test_backup_restore.sh`.

---

## 📊 **Suivi de progression**

### **Métriques Story**

| Story | Status | Tests | Coverage | Acceptance Criteria |
|-------|--------|-------|----------|---------------------|
| 1 | 📋 Conçue | - | - | 0/5 |
| 1.5 | 📋 Conçue | - | - | 0/6 |
| 2 | ⏳ En attente | - | - | 0/5 |
| ... | ... | ... | ... | ... |

**Légende** :
- 📋 Conçue : Specs complètes, prête pour implémentation
- 🚧 En cours : Développement actif
- ✅ Terminée : Tests passent + ACs validés + Déployée
- ⏳ En attente : Bloquée par dépendances

### **Dashboard progression**

```bash
# Afficher progression globale
python scripts/story_progress.py

# Output:
# Story 1: Infrastructure 📋 (0/5 ACs)
# Story 1.5: Trust Layer 📋 (0/6 ACs)
# Story 2: Moteur Vie ⏳ (0/5 ACs)
# ...
# TOTAL: 0/10 stories terminées (0%)
```

---

## 🎯 **Principes de développement**

### **KISS Day 1**
- Flat structure `agents/src/agents/` (1 fichier agent.py par module)
- Refactoring si >500 lignes OU 3+ modules partagent >100 lignes identiques
- Pas d'over-engineering prématuré

### **Tests obligatoires**
- Unit tests (mocks LLM) : 80%
- Integration tests (datasets réels) : 15%
- E2E tests (scénarios complets) : 5%

### **Trust Layer systématique**
- Chaque action = `@friday_action` + `ActionResult`
- Trust level défini dans `config/trust_levels.yaml`
- Receipts traçables via `/receipt <id>`

### **Documentation à jour**
- README.md mis à jour chaque story
- CLAUDE.md enrichi si nouvelles règles
- Architecture addendum si clarifications
- [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md) mis à jour à chaque décision architecturale

---

**Version** : 1.3.0
**Dernière mise à jour** : 2026-02-08
