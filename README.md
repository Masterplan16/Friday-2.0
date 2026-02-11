# Friday 2.0 - Second Cerveau Personnel

**Système d'intelligence personnelle multi-agents**

---

## 🎯 Vision

Friday 2.0 est un système d'IA personnel qui agit comme un **second cerveau** proactif, poussant l'information au bon moment plutôt que d'attendre qu'on la cherche. Il combine 23 modules spécialisés couvrant tous les aspects de la vie professionnelle et personnelle de l'utilisateur.

---

## 📊 Vue d'ensemble

| Aspect | Détail |
|--------|--------|
| **Utilisateur** | Utilisateur principal (extension famille envisageable) |
| **Modules** | 23 agents spécialisés (médecin, enseignant, financier, personnel) |
| **Tech Stack** | Python 3.12 + LangGraph + n8n + Claude Sonnet 4.5 + PostgreSQL 16 + Redis 7 |
| **Budget** | ~73€/mois (VPS OVH VPS-4 ~25€ + Claude API ~45€ + veille ~3€) |
| **Philosophie** | KISS Day 1, évolutibilité by design (5 adaptateurs) |
| **Hébergement** | VPS-4 OVH France — 48 Go RAM / 12 vCores / 300 Go SSD |
| **Stockage** | Hybride : VPS (cerveau, index, métadonnées) + PC (fichiers) + NAS (Phase 2 - PostgreSQL local + documents) |
| **Agent local** | Claude Code CLI (Phase 1: PC, Phase 2: NAS QNAP TS-264-8G) [D23] |
| **Sécurité** | Tailscale (zéro exposition Internet) + Presidio (RGPD) + age/SOPS |
| **Interface** | Telegram (canal unique, 100% Day 1) |
| **Contrôle** | Observability & Trust Layer (receipts, trust levels, feedback loop) |

---

## 🏗️ Architecture

### Couches techniques

```
┌─────────────────────────────────────────────────────────┐
│  OBSERVABILITY & TRUST LAYER (transversal)               │
│  @friday_action · receipts · trust levels · feedback     │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  ACTION                                                  │
│  Agenda · Briefing · Notifications · Brouillons mail    │
└─────────────────────────────────────────────────────────┘
                           ▲
┌─────────────────────────────────────────────────────────┐
│  AGENTS SPÉCIALISÉS (23 modules)                        │
│  Thèse · Droit · Finance · Santé · Menus · Coach · ... │
└─────────────────────────────────────────────────────────┘
                           ▲
┌─────────────────────────────────────────────────────────┐
│  INTELLIGENCE                                            │
│  Mémoire éternelle · Graphe de connaissances · RAG      │
└─────────────────────────────────────────────────────────┘
                           ▲
┌─────────────────────────────────────────────────────────┐
│  INGESTION                                               │
│  Moteur Vie · Archiviste · Plaud · Photos · Scanner    │
└─────────────────────────────────────────────────────────┘
```

### Tech Stack

| Composant | Technologie | Version |
|-----------|-------------|---------|
| **Langage principal** | Python | 3.12+ |
| **Framework agents IA** | LangGraph | ==0.2.45 |
| **Orchestration workflows** | n8n | 1.69.2 |
| **LLM** | Claude Sonnet 4.5 (Anthropic API) | claude-sonnet-4-5-20250929 (D17 : modèle unique, zéro routing) |
| **Base de données** | PostgreSQL | 16.6 |
| **Cache + Pub/Sub** | Redis | 7.4 |
| **Vectoriel** | pgvector (extension PostgreSQL) | D19 : intégré dans PG16, réévaluation Qdrant si >300k vecteurs |
| **Mémoire graphe** | PostgreSQL + pgvector (via memorystore.py) | Abstraction (migration Graphiti/Neo4j envisageable) |
| **API Gateway** | FastAPI | 0.115+ |
| **Bot conversationnel** | python-telegram-bot | 21.7+ |
| **Reverse proxy** | Caddy | 2.8 |
| **Réseau sécurisé** | Tailscale | Latest |
| **OCR** | Surya + Marker | Latest |
| **STT** | Faster-Whisper | Latest (fallback Deepgram) |
| **TTS** | Kokoro | Latest (fallback Piper) |
| **NER** | spaCy fr + GLiNER | spaCy 3.8+ |
| **Anonymisation** | Presidio | 2.2.355+ |

---

## 🛡️ Observability & Trust Layer

Composant transversal garantissant la confiance utilisateur. Chaque action de Friday est tracée et contrôlable.

| Niveau de confiance | Comportement | Exemples |
|---------------------|-------------|----------|
| 🟢 **AUTO** | Exécute + notifie après coup | OCR, renommage, indexation |
| 🟡 **PROPOSE** | Prépare + attend validation Telegram | Classification email, création tâche |
| 🔴 **BLOQUÉ** | Analyse uniquement, jamais d'action | Envoi mail, conseil médical, analyse juridique |

**Commandes Telegram :** `/status` `/journal` `/receipt` `/confiance` `/stats`

---

## ✨ Features Implémentées

### 📧 Classification Email Automatique (Story 2.2) ✅

**Claude Sonnet 4.5 classifie automatiquement les emails entrants en 8 catégories**

| Feature | Description |
|---------|-------------|
| **Modèle** | Claude Sonnet 4.5 (temperature 0.1, déterministe) |
| **Catégories** | 🏥 medical · 💰 finance · 🎓 faculty · 🔬 research · 👤 personnel · 🚨 urgent · 🗑️ spam · ❓ unknown |
| **Correction rules** | Injection max 50 règles prioritaires dans prompt (feedback loop) |
| **Cold start** | Calibrage sur 10-20 premiers emails (validation obligatoire) |
| **Accuracy** | >= 85% global, >= 80% par catégorie (testé sur dataset 100 emails) |
| **Latence** | <8s moyenne (Presidio 2s + Claude 5s + BDD 1s) |
| **Trust Layer** | Mode propose par défaut, auto après 90% accuracy |
| **Interface** | Telegram inline buttons pour corrections (8 catégories) |
| **Pattern detection** | Détection automatique ≥2 corrections similaires → proposition règle |

**Workflow** :

```
EmailEngine → Gateway → Presidio (RGPD) → Redis Stream → Consumer
  ↓
  Fetch correction rules (max 50)
  ↓
  Build prompt (contexte médecin + règles + 8 catégories)
  ↓
  Claude API (temperature 0.1, 300 tokens max)
  ↓
  Parse JSON → EmailClassification (Pydantic)
  ↓
  UPDATE ingestion.emails (category, confidence)
  ↓
  Trust Layer (@friday_action) → Telegram notification
```

**Commandes Telegram** :
- `/correct email-123 finance` — Corriger classification via commande
- Bouton `[Correct]` sur notification → Inline keyboard 8 catégories

**Documentation** : [docs/email-classification.md](docs/email-classification.md)

---

### 🌟 Détection VIP & Urgence (Story 2.3) ✅

**Système automatique de détection des emails prioritaires avec notifications push**

| Feature | Description |
|---------|-------------|
| **VIP Detection** | Lookup hash SHA256 rapide (<100ms) sans accès PII |
| **Urgence Multi-facteurs** | VIP (0.5) + Keywords (0.3) + Deadline (0.2) → Seuil 0.6 |
| **RGPD** | Emails VIP anonymisés via Presidio avant stockage |
| **Latence VIP** | <5s réception → notification (avant classification ~10s) |
| **Accuracy** | 100% recall emails urgents (0% faux négatifs AC5) |
| **Faux positifs** | <10% (précision >= 90%) |
| **Keywords** | 10 keywords français seed + apprentissage futur |
| **Notifications** | VIP → Topic Email, URGENT → Topic Actions (push) |
| **Priority** | urgent/high/normal dans DB + CHECK constraint |

**Algorithme urgence** :
```
urgency_score = 0.5*is_vip + 0.3*keywords_matched + 0.2*has_deadline
is_urgent = urgency_score >= 0.6

Exemples:
- VIP seul (0.5) → PAS urgent
- VIP + keyword "deadline" (0.8) → URGENT
- Non-VIP + "URGENT" + "avant demain" (0.8) → URGENT
```

**Commandes Telegram** :
```
/vip add <email> <label>    Ajouter expéditeur VIP
/vip list                    Lister tous les VIPs actifs
/vip remove <email>          Retirer un VIP (soft delete)
```

**Tests E2E** :
- Dataset 31 emails (12 VIP, 5 urgents, 6 edge cases)
- 100% recall VIP (12/12 détectés)
- 100% recall urgence (5/5 détectés)
- Précision >= 90% (faux positifs <10%)
- Latence <1s par email (AC5 validé)

**Documentation** : [docs/vip-urgency-detection.md](docs/vip-urgency-detection.md) | [docs/telegram-user-guide.md](docs/telegram-user-guide.md#commandes-vip--urgence-story-23)

---

## 🛡️ Self-Healing ✅

Friday 2.0 intègre un système de **self-healing automatique** en 4 tiers pour garantir une disponibilité 24/7 sans intervention manuelle.

| Tier | Capacité | RTO | Automatisation |
|------|----------|-----|----------------|
| **Tier 1** | Docker restart policies (`unless-stopped`) | < 30s | ✅ 100% auto |
| **Tier 2** | Auto-recovery RAM (seuil 91%, kill services lourds prioritaires) | < 2min | ✅ 100% auto |
| **Tier 2** | OS security updates automatiques (unattended-upgrades, reboot 03:30) | N/A | ✅ 100% auto |
| **Tier 2** | Crash loop detection (>3 restarts/1h → stop service + alerte) | < 30s | ✅ 100% auto |
| **Tier 3-4** | Monitoring externe + ML patterns (Epic 12 - Sprint 2+) | TBD | 🔜 Roadmap |

**Seuils RAM (VPS-4 48 Go)** :
- 🟡 **85%** (40.8 Go) → Alerte Telegram System
- 🔴 **91%** (43.7 Go) → Auto-recovery : kill services lourds (TTS → STT → OCR)
- 🚨 **95%** (45.6 Go) → Emergency : kill tous services lourds

**Services protégés** : postgres, redis, friday-gateway, friday-bot, n8n, emailengine, presidio

**Commande Telegram :** `/recovery` (liste événements) · `/recovery -v` (détails) · `/recovery stats` (métriques)

**Scripts disponibles** :
- `scripts/monitor-ram.sh` — Monitoring RAM + alertes (cron */5min)
- `scripts/auto-recover-ram.sh` — Auto-recovery RAM (n8n workflow)
- `scripts/detect-crash-loop.sh` — Détection crash loops (n8n workflow */10min)
- `scripts/setup-unattended-upgrades.sh` — Setup OS updates automatiques

**Documentation complète** : [docs/self-healing-runbook.md](docs/self-healing-runbook.md)

---

## 🐳 Docker Image Monitoring ✅

Friday 2.0 surveille automatiquement les mises à jour d'images Docker via **Watchtower en mode monitor-only**. **Aucun auto-update** - le Mainteneur décide manuellement quand mettre à jour.

| Aspect | Configuration |
|--------|--------------|
| **Mode** | MONITOR_ONLY (notifications seulement, JAMAIS d'auto-update) |
| **Schedule** | Quotidien 03h00 (après backup, avant OS updates) |
| **Notifications** | Telegram topic System via Shoutrrr |
| **Security** | Docker socket read-only (:ro) |
| **Resource usage** | ~100 MB RAM, <5% CPU spike |

**Workflow manuel update** :
1. Réception notification Telegram (service name, current tag, new tag)
2. Évaluation release notes + breaking changes
3. Update : `docker compose pull <service> && docker compose up -d <service>`
4. Validation healthcheck : `curl http://localhost:8000/api/v1/health`
5. Rollback si nécessaire

**Commandes utiles** :
```bash
# Vérifier Watchtower logs
docker logs watchtower --tail 50

# Trigger manuel check (debug uniquement)
docker exec watchtower /watchtower --run-once

# Vérifier resource usage
docker stats watchtower
```

**Documentation complète** : [docs/watchtower-monitoring.md](docs/watchtower-monitoring.md)

---

## 🤖 Agent Local Desktop Search (Claude CLI) [D23]

Friday 2.0 utilise **Claude Code CLI** comme agent local pour la recherche sémantique dans les documents locaux (PDF, Docx, articles, thèses).

| Aspect | Configuration |
|--------|--------------|
| **Phase 1 (actuel)** | Claude CLI sur PC Mainteneur (PC allumé requis) |
| **Phase 2 (roadmap)** | Migration Claude CLI vers NAS QNAP TS-264-8G (disponibilité 24/7) |
| **Communication** | Telegram → VPS → Redis Streams → Claude CLI PC/NAS → Résultat |
| **Wrapper** | Python léger (~120 lignes) vs agent custom (~1250 lignes) = **−40% dev time** |
| **Interface** | Telegram `/search <requête>` (quotidien) + SSH (admin/debug) |
| **Simplification** | Story 3.3 réduite : L (20-30h) → M (12-18h) économie 8-12h dev |

### Architecture

```
Utilisateur → Telegram (/search "contrat bail 2024")
    ↓
☁️ VPS Gateway (FastAPI)
    ↓
Redis Stream (desktop.search.request)
    ↓
🏠 PC/NAS Claude CLI (via wrapper Python)
    ↓
PostgreSQL pgvector (recherche sémantique)
    ↓
Redis Stream (desktop.search.result)
    ↓
📱 Telegram (topic Email & Communications)
    "✅ Trouvé : Bail_Cabinet_2024-06-15.pdf (page 3, clause résiliation)"
```

### NAS recommandé (Phase 2)

| Modèle | Prix total | CPU | RAM | M.2 NVMe | Verdict |
|--------|------------|-----|-----|----------|---------|
| **QNAP TS-264-8G** | **721€** | Intel N5105 (6 800 Passmark) | 8 Go DDR4 | 2× | **Recommandé** |
| UGREEN DXP2800 | 683€ | Intel N100 (5 500 Passmark) | 8 Go DDR5 | 2× | Budget optimal |
| ASUSTOR AS5402T | 708€ | Intel N5105 (6 800 Passmark) | 4 Go DDR4 (+upgrade) | 4× | Alternative |

**QNAP TS-264-8G choisi** :
- ✅ 8 Go DDR4 natif (zéro upgrade nécessaire)
- ✅ Intel Celeron N5105 (bon pour pgvector calculs vectoriels)
- ✅ QTS mature + Docker natif + Tailscale facile
- ✅ 2× M.2 NVMe slots (PostgreSQL sur SSD)
- ✅ Prix total 721€ (NAS 403€ + 2× IronWolf 4To 318€)

**Bénéfices vs BeeStation (retiré MVP)** :
- ✅ CPU x86_64 compatible Docker (vs ARM incompatible)
- ✅ Tailscale natif (vs limitations BeeStation)
- ✅ 24/7 disponibilité sans PC allumé

### Commandes Telegram

```bash
# Recherche documents locaux
/search contrat bail cabinet 2024

# Recherche avec filtres
/search thèse doctorant Julie méthodologie

# Statut agent local
/agent status
```

---

## 🧹 Cleanup & RGPD ✅

Friday 2.0 implémente un système de **cleanup automatisé** pour gérer l'espace disque et garantir la **compliance RGPD** (droit à l'oubli).

| Opération | Retention | Schedule |
|-----------|-----------|----------|
| **Purge mappings Presidio** | 30 jours | Quotidien 03:05 |
| **Rotation logs Docker** | 7 jours | Quotidien 03:05 |
| **Rotation logs journald** | 7 jours | Quotidien 03:05 |
| **Rotation backups VPS** | 30 jours (keep_7_days policy) | Quotidien 03:05 |
| **Cleanup zone transit** | 24 heures | Quotidien 03:05 |

**RGPD Compliance** :
- ✅ Mappings Presidio (`core.action_receipts.encrypted_mapping`) purgés après 30 jours (droit à l'oubli)
- ✅ Audit trail via colonnes `purged_at`, `deleted_at` (traçabilité suppressions)
- ✅ Texte anonymisé conservé pour analyse Trust Layer (sans PII)

**Timeline nuit** :
- 03:00 — Backup PostgreSQL + Watchtower check images
- **03:05** — **Cleanup disk** (5 min après backup pour éviter conflit fichiers)
- 03:30 — OS unattended-upgrades (reboot si kernel update)

**Notification Telegram (topic System)** :
```
🧹 Cleanup Quotidien - 2026-02-10 03:05

✅ Status: Success

📊 Espace libéré:
  • Presidio mappings: 125 enregistrements purgés
  • Logs Docker: 1.2 GB
  • Logs journald: 450 MB
  • Backups VPS: 3.8 GB (2 fichiers)
  • Zone transit: 85 MB

💾 Total libéré: 5.5 GB
⏱️  Durée: 42s
```

**Scripts disponibles** :
```bash
# Test dry-run (preview sans suppression)
bash scripts/cleanup-disk.sh --dry-run

# Validation finale VPS (6 vérifications)
bash scripts/validate-cleanup.sh

# Voir logs cleanup
tail -f /var/log/friday/cleanup-disk.log
```

**Déploiement VPS** :
- [DEPLOY_CLEANUP_VPS.md](DEPLOY_CLEANUP_VPS.md) — Guide déploiement complet (5 étapes)
- `scripts/deploy-cleanup-to-vps.sh` — Déploiement automatisé via SSH
- `scripts/install-cron-cleanup.sh` — Installation cron VPS

**Documentation complète** : [docs/cleanup-rgpd-spec.md](docs/cleanup-rgpd-spec.md)

---

## 🗂️ Structure du projet

```
friday-2.0/
├── README.md                    # Ce fichier
├── CLAUDE.md                    # Instructions pour AI agents
├── _docs/
│   ├── architecture-friday-2.0.md           # Architecture complète (~2500 lignes)
│   ├── architecture-addendum-20260205.md    # Addendum technique (Presidio, RAM, OpenClaw)
│   └── friday-2.0-analyse-besoins.md        # Analyse besoins initiale
│
├── docker-compose.yml           # Services principaux
├── docker-compose.dev.yml       # Override dev
├── docker-compose.services.yml  # Services lourds (tous résidents VPS-4)
├── .env.example
├── Makefile
│
├── agents/                      # Python 3.12 - LangGraph
│   ├── src/
│   │   ├── supervisor/          # Superviseur (routage + monitoring RAM)
│   │   ├── agents/              # 23 modules agents (flat structure Day 1)
│   │   ├── middleware/          # @friday_action, ActionResult, trust levels
│   │   ├── memory/              # Helpers mémoire (legacy placeholder, utiliser adapters/memorystore.py)
│   │   ├── tools/               # Outils partagés (OCR, STT, TTS, NER, anonymize)
│   │   ├── adapters/            # Adaptateurs (LLM, vectorstore, memorystore, filesync, email)
│   │   ├── models/              # Pydantic schemas globaux
│   │   ├── config/              # Configuration
│   │   └── utils/               # Utilitaires
│   └── pyproject.toml
│
├── bot/                         # Telegram bot
│   ├── handlers/                # Dispatcher (message, voice, document, callback)
│   ├── commands/                # Commandes trust (/status, /journal, /receipt, etc.)
│   ├── keyboards/               # Claviers inline (actions, validation trust)
│   └── media/transit/
│
├── services/                    # Services Docker custom
│   ├── gateway/                 # FastAPI Gateway
│   ├── alerting/                # Listener Redis → alertes Telegram
│   ├── metrics/                 # Calcul nightly trust metrics
│   ├── stt/                     # Faster-Whisper
│   ├── tts/                     # Kokoro
│   └── ocr/                     # Surya + Marker
│
├── n8n-workflows/               # Workflows n8n (JSON)
├── database/migrations/         # Migrations SQL numérotées (001-011+)
├── config/                      # Config externe (Tailscale, Syncthing, Caddy, profiles RAM, trust_levels.yaml)
├── tests/                       # Tests (unit, integration, e2e)
├── scripts/                     # Scripts automation (setup, backup, deploy, monitor-ram)
├── docs/                        # Documentation technique
└── logs/                        # Logs (gitignored)
```

---

## 🔐 Sécurité & RGPD

| Aspect | Solution |
|--------|----------|
| **Exposition Internet** | Aucune (Tailscale mesh VPN) |
| **Données sensibles en base** | Chiffrement pgcrypto (colonnes médicales, financières) |
| **Secrets (.env, API keys)** | age/SOPS (chiffrement dans git) |
| **Anonymisation avant LLM cloud** | Presidio obligatoire (pipeline RGPD) |
| **Hébergement** | OVH France (RGPD compliant) |
| **LLM** | Claude Sonnet 4.5 (Anthropic API) — Presidio anonymise AVANT tout appel (D17) |
| **SSH** | Uniquement via Tailscale (pas de port 22 ouvert) |
| **Branch Protection** | Master branch protected - PR required, status checks enforced |
| **Dependency Scanning** | Dependabot automated updates (weekly) |

### 🔑 Secrets Management

Tous les secrets sont chiffrés avec **age + SOPS** avant d'être commitées :
- ✅ `.env.enc` contient secrets chiffrés (commitable en toute sécurité)
- ✅ `.env.example` structure complète avec valeurs fictives
- ✅ Clé privée age stockée localement uniquement (`~/.age/friday-key.txt`)
- ✅ Rotation tokens régulière (tous les 3-6 mois)

📘 **Documentation complète** : [docs/secrets-management.md](docs/secrets-management.md)

### 🛡️ Security Policy

Rapporter une vulnérabilité : Voir [SECURITY.md](SECURITY.md) pour procédure complète.

- **Réponse** : Accusé réception sous 48h
- **Correction** : 7 jours (critique), 14 jours (high), 30 jours (medium)
- **Divulgation** : Coordonnée avec publication du fix

### 🔍 Security Audit

Audit mensuel automatisé via git-secrets :
- ✅ Scan historique Git complet
- ✅ Détection tokens API, credentials, clés privées
- ✅ Validation .gitignore et SOPS encryption

📘 **Procédures d'audit** : [docs/security-audit.md](docs/security-audit.md)

### 🚀 Branch Protection & CI/CD

- **Master branch** : Protected (PR obligatoire, 1 review minimum)
- **Status checks** : lint, test-unit, test-integration, build-validation
- **Dependabot** : Mises à jour automatiques hebdomadaires (lundi 8h UTC)
- **E2E Security Tests** : 6 tests automatisés ([tests/e2e/test_repo_security.sh](tests/e2e/test_repo_security.sh))

---

## 🎯 Principes de développement

### KISS Day 1

- Structure flat `agents/src/agents/` (23 modules, 1 fichier agent.py chacun Day 1)
- Pas d'ORM (asyncpg brut)
- Pas de Celery (n8n + FastAPI BackgroundTasks)
- Pas de Prometheus Day 1 (monitoring via Trust Layer + scripts/monitor-ram.sh)
- Refactoring si douleur réelle, pas par anticipation

### Évolutibilité by design

- 5 adaptateurs (LLM, vectorstore, memorystore, filesync, email) = remplaçables sans refactoring massif
- Event-driven (Redis Pub/Sub) = découplage maximal
- Configuration externe (profiles.py, health_checks.py) = ajout sans modifier code

### Contraintes matérielles

- VPS-4 OVH : 48 Go RAM / 12 vCores / 300 Go SSD (~25€ TTC/mois)
- Tous services lourds résidents en simultané (Whisper + Kokoro + Surya = ~8 Go)
- Marge disponible : ~32-34 Go (cohabitation Jarvis Friday possible)
- Orchestrator simplifié : moniteur RAM, plus d'exclusion mutuelle

---

## 🚀 Setup & Prérequis

### Prérequis système

- **Linux/macOS/Windows** : Git Bash ou WSL requis pour exécuter scripts `.sh`
- **Python** : 3.12+
- **Docker** : 24+
- **Docker Compose** : 2.20+
- **age** (secrets encryption) : https://github.com/FiloSottile/age

### Rendre scripts exécutables

```bash
# Linux/macOS/Git Bash Windows
chmod +x scripts/*.py scripts/*.sh
```

### Configuration secrets (one-time setup)

**Générer clé age pour chiffrement secrets :**

```bash
# Générer clé age (sauvegardée localement)
age-keygen -o ~/.config/sops/age/keys.txt

# Extraire la clé publique (utiliser dans .sops.yaml)
age-keygen -y ~/.config/sops/age/keys.txt
# Output: age1xxx... (copier cette valeur dans .sops.yaml)
```

**Chiffrer `.env` (voir [docs/secrets-management.md](docs/secrets-management.md) pour détails) :**

```bash
# Créer .env.enc depuis .env template
sops -e .env.example > .env.enc

# Déchiffrer avant lancement (automatique via docker-compose avec init script)
sops -d .env.enc > .env
```

**Variables d'environnement requises** (structure complète dans [`.env.example`](.env.example)) :

| Variable | Description | Exemple |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Token du bot Telegram (@BotFather) | `1234567890:ABCdef...` |
| `TELEGRAM_SUPERGROUP_ID` | ID du supergroup Telegram | `-1001234567890` |
| `OWNER_USER_ID` | ID utilisateur Telegram principal | `123456789` |
| `TOPIC_*_ID` | Thread IDs des 5 topics Telegram | `2`, `3`, `4`, `5`, `6` |
| `ANTHROPIC_API_KEY` | Clé API Claude (Anthropic) | `sk-ant-...` |
| `DATABASE_URL` | URL PostgreSQL complète | `postgresql://user:pass@host:5432/db` |
| `REDIS_URL` | URL Redis complète | `redis://:pass@host:6379/0` |
| `LOG_LEVEL` | Niveau de logging | `INFO` |

📋 **Note** : Toutes les valeurs sensibles DOIVENT être chiffrées avec SOPS. Voir [docs/secrets-management.md](docs/secrets-management.md) pour le workflow complet.

### Dépendances verrouillées

Les dépendances Python sont lockées dans `agents/requirements-lock.txt` pour garantir des builds reproductibles (NFR23).

```bash
# Générer requirements-lock.txt (reproduceabilité production)
python -m venv venv
source venv/bin/activate  # ou: venv\Scripts\activate (Windows)
pip install -e agents/
pip freeze > agents/requirements-lock.txt
```

**Note** : Le fichier `requirements-lock.txt` est automatiquement utilisé par le workflow CI/CD.

### Déploiement

Pour déployer Friday 2.0 sur le VPS-4 OVH, voir le guide complet :

📘 **[Deployment Runbook](docs/deployment-runbook.md)** — Procédure déploiement, troubleshooting, rollback manuel

**Quick start déploiement :**
```bash
# Déploiement automatisé via Tailscale VPN
./scripts/deploy.sh
```

---

## 💰 Budget

| Poste | Coût mensuel |
|-------|-------------|
| VPS OVH VPS-4 48 Go (France, sans engagement) | ~25€ TTC |
| Claude Sonnet 4.5 API (Anthropic) | ~45€ |
| Divers (domaine, ntfy) | ~2-3€ |
| Benchmark veille mensuel | ~3€ |
| **Total estimé** | **~75-76€/mois** |

**Note budget:** Budget max ~75€/mois. Premiers mois potentiellement plus chers (migration 110k emails ~$45 one-shot).

---

## 📊 Status du projet

<!-- LOW #16 FIX: Badge visible après Story 1.17 (repo public) -->
![CI Status](https://github.com/Masterplan16/Friday-2.0/workflows/CI/badge.svg)

> **Note** : Le badge CI sera visible après la Story 1.17 (Préparation repository public).

| Phase | Status |
|-------|--------|
| Analyse des besoins | ✅ Terminée + Mise à jour contraintes techniques |
| Architecture complète | ✅ Terminée (~2500 lignes) + Analyse adversariale complète ✅ |
| Observability & Trust Layer | ✅ Conçu + Spécifié en détail |
| Workflows n8n critiques | ✅ Spécifiés (Email Ingestion, Briefing Daily, Backup Daily) |
| Stratégie tests IA | ✅ Documentée (pyramide, datasets, métriques) |
| 21 clarifications techniques | ✅ Toutes ajoutées dans l'architecture |
| Story 1 : Infrastructure de base | 🔄 Partiellement implémentée (Docker, migrations 001-010, scripts créés) |
| Story 1.5 : Trust Layer | 🔄 Partiellement implémentée (migration 011, config trust, docs créées) |
| Story 2+ : Modules métier | ⏳ En attente |

**Next step** : Implémenter Story 1 (Docker Compose, PostgreSQL, Redis, FastAPI Gateway, Tailscale)

---

## 📚 Documentation

### Documents principaux

- **Architecture complète** : [_docs/architecture-friday-2.0.md](_docs/architecture-friday-2.0.md) (~2500 lignes)
  - Source de vérité unique
  - Inclut graphe de connaissances, anonymisation réversible, Trust Layer, clarifications complètes

- **Addendum technique** : [_docs/architecture-addendum-20260205.md](_docs/architecture-addendum-20260205.md)
  - Benchmarks Presidio, algorithme pattern detection, profils RAM sources, critères OpenClaw, migration graphe

- **Analyse besoins** : [_docs/friday-2.0-analyse-besoins.md](_docs/friday-2.0-analyse-besoins.md)
  - Vision produit, 23 modules, contraintes techniques (mise à jour 2026-02-05)

- **Instructions AI agents** : [CLAUDE.md](CLAUDE.md)
  - Règles de développement, standards, anti-patterns, checklist

### Documents techniques

- **Workflows n8n** : [docs/n8n-workflows-spec.md](docs/n8n-workflows-spec.md)
  - 3 workflows critiques Day 1 spécifiés (nodes, triggers, tests)

- **Tests IA** : [docs/testing-strategy-ai.md](docs/testing-strategy-ai.md)
  - Pyramide de tests, datasets validation, métriques qualité

---

## 📄 Licence

Ce projet est sous licence [MIT](LICENSE).

Copyright (c) 2026 Friday 2.0 Project

---

**Version** : 1.5.0 (2026-02-10)

**Dernières mises à jour** :
- ✅ D23 : Claude Code CLI comme agent local Desktop Search (Phase 1: PC, Phase 2: NAS QNAP TS-264-8G)
- ✅ BeeStation retiré du scope MVP (ARM incompatible, limitations Tailscale)
- ✅ Story 3.3 réduite : L (20-30h) → M (12-18h) = économie 8-12h dev (~40%)
- ✅ Comparaison NAS factuelle (QNAP TS-264-8G 721€ recommandé vs alternatives)
