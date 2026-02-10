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
| **Stockage** | Hybride : VPS (cerveau, index, métadonnées) + PC (fichiers) |
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

![CI Status](https://github.com/Masterplan16/Friday-2.0/workflows/CI/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

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

**Version** : 1.4.0 (2026-02-05)
**Dernière mise à jour** : Code review adversarial complet (22 issues fixes) + Fichiers critiques créés (migrations, docs, scripts)

<!-- CI validation test - Story 1.16 subtask 5.2 -->
