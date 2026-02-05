# Friday 2.0 - Roadmap d'implémentation

**Date** : 2026-02-05
**Version** : 1.1 (corrigé review cohérence documentaire)
**Status** : Architecture complète ✅ - Prêt pour implémentation

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
| **2** | Moteur Vie (Email) | 5-7j | Story 1.5 | ⏳ En attente |
| **3** | Archiviste (OCR + Renommage) | 4-6j | Story 1.5 | ⏳ En attente |
| **4** | Briefing matinal | 2-3j | Story 2, 3 | ⏳ En attente |
| **5** | Plaud Note (Transcription) | 3-4j | Story 1.5, 2 | ⏳ En attente |
| **6** | Suivi Financier | 4-5j | Story 1.5, 3 | ⏳ En attente |
| **7** | Tuteur Thèse | 5-6j | Story 1.5 | ⏳ En attente |
| **8** | Veilleur Droit | 3-4j | Story 1.5 | ⏳ En attente |
| **9** | Agenda (multi-casquettes) | 3-4j | Story 2, 5 | ⏳ En attente |
| **10+** | Modules restants (Coach, Menus, etc.) | Variable | Variable | ⏳ En attente |

**Durée totale estimée** : ~35-50 jours de développement (Stories 1-9)

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

#### **1.4 Tailscale**
- [ ] Installation Tailscale VPS
- [ ] Hostname `friday-vps`
- [ ] Firewall : AUCUN port ouvert sur Internet public (SSH via Tailscale uniquement)
- [ ] Caddy configuré pour HTTPS interne mesh Tailscale

#### **1.5 Tests**
- [ ] Tests unitaires `scripts/apply_migrations.py`
- [ ] Test E2E `tests/e2e/test_story1_sanity.sh` (tous services démarrent + healthcheck OK)

### **Acceptance Criteria**

- AC1 : `docker compose up -d` démarre tous les services sans erreur
- AC2 : `GET /api/v1/health` retourne 200 avec statut de tous services
- AC3 : PostgreSQL avec 3 schemas créés (core, ingestion, knowledge) + 10 migrations appliquées
- AC4 : Tailscale mesh opérationnel (VPS accessible via hostname `friday-vps`)
- AC5 : Tests E2E passent (healthcheck OK)

### **Livrables**
- Infrastructure Docker Compose complète
- Base de données initialisée (10 migrations)
- Gateway API fonctionnel
- Tailscale configuré
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

#### **1.5.2 Middleware Trust**
- [ ] Migration SQL `011_trust_system.sql` (tables : action_receipts, correction_rules, trust_metrics)
- [ ] `agents/src/middleware/trust.py` :
  - Décorateur `@friday_action`
  - Modèle Pydantic `ActionResult`
  - Gestion trust levels (auto/propose/blocked)
- [ ] `config/trust_levels.yaml` (configuration initiale 23 modules) ✅ **CRÉÉ**

#### **1.5.3 Bot Telegram**
- [ ] Structure `bot/`
  - `handlers/` (message, voice, document, callback)
  - `commands/` (start, status, journal, receipt, confiance, stats, trust)
  - `keyboards/` (inline buttons pour validation actions)
  - `media/transit/` (fichiers temporaires)
- [ ] Commandes implémentées :
  - `/status` : Dashboard temps réel (services, RAM, dernières actions)
  - `/journal [module]` : Liste 20 dernières actions (filtrable par module)
  - `/receipt <id> [-v]` : Détail action (-v = steps techniques)
  - `/confiance` : Tableau accuracy par module/action
  - `/stats` : Métriques globales semaine
  - `/trust set <module> <action> <level>` : Ajuster trust level manuellement

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

## 📦 **Stories 4-9 : Modules métier**

*(Spécifications détaillées créées au fur et à mesure, selon priorisation Antonio)*

**Séquence suggérée** :
1. **Story 4** : Briefing matinal (agrégation données modules 2-3)
2. **Story 5** : Plaud Note (transcription → cascade actions)
3. **Story 6** : Suivi Financier (CSV import → classification → anomalies)
4. **Story 7** : Tuteur Thèse (analyse Google Docs → commentaires)
5. **Story 8** : Veilleur Droit (analyse contrats)
6. **Story 9** : Agenda (extraction événements emails/Plaud)

---

## 🚀 **Migration & Mise en production**

### **Migration données existantes**

**Timing** : Après Story 2 (Email agent opérationnel)

**Script** : `scripts/migrate_emails.py` ✅ **CRÉÉ**

**Contenu** :
- 55 000 emails existants (4 comptes via EmailEngine)
- Checkpointing tous les 100 emails
- Retry exponentiel sur erreur
- Resume depuis dernier checkpoint
- Anonymisation Presidio avant classification (RGPD)
- **Durée estimée** : ~10-12h (incluant Presidio overhead + retry/backoff)
- **Coût estimé** : ~$10-12 USD (Mistral API)

**Calcul détaillé** (corrigé suite code review adversarial 2026-02-05) :
- 55k emails × ~600 tokens avg (500 input + 100 output) = 33M tokens
- Mistral Nemo pricing : $0.15/1M tokens input + $0.15/1M tokens output
- Coût classification : 33M tokens × $0.30/1M = **$9.90 USD**
- Rate limit Mistral : 200 RPM → 55k / 200 = **275 minutes = 4.6h (classification seule)**
- Presidio overhead : ~150-200ms par email → 55k × 0.15s = **2.3h supplémentaires**
- Retry + backoff (estimation 5% échecs temporaires) : ~30-45 min
- **Durée totale réaliste** : 4.6h + 2.3h + 0.5h + marge sécurité = **~10-12h**
- **Coût total avec marge** : $9.90 + 20% buffer = **~$10-12 USD**

**Validation** :
- Test dry-run d'abord (`--dry-run`)
- Backup PostgreSQL avant migration
- Vérification post-migration (sample 100 emails)

### **Backup & Disaster Recovery**

**Workflow** : `n8n-workflows/backup-daily.json` (cron 03:00)

**Note** : Nightly metrics à 02:00, backup à 03:00 — pas de chevauchement.

**Test** : `tests/e2e/test_backup_restore.sh` ✅ **CRÉÉ**

**Frequence tests** : Mensuel (premier dimanche du mois)

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

---

**Version** : 1.1
**Dernière mise à jour** : 2026-02-05
