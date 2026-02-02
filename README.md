# Friday 2.0 - Second Cerveau Personnel

**Système d'intelligence personnelle multi-agents pour Antonio**

---

## 🎯 Vision

Friday 2.0 est un système d'IA personnel qui agit comme un **second cerveau** proactif, poussant l'information au bon moment plutôt que d'attendre qu'on la cherche. Il combine 23 modules spécialisés couvrant tous les aspects de la vie professionnelle et personnelle d'Antonio.

---

## 📊 Vue d'ensemble

| Aspect | Détail |
|--------|--------|
| **Utilisateur** | Antonio (extension famille envisageable) |
| **Modules** | 23 agents spécialisés (médecin, enseignant, financier, personnel) |
| **Tech Stack** | Python 3.12 + LangGraph + n8n + Mistral + PostgreSQL 16 + Redis 7 |
| **Budget** | 35-41€/mois (VPS OVH 16 Go + APIs cloud) |
| **Philosophie** | KISS Day 1, évolutibilité by design (5 adaptateurs) |
| **Hébergement** | VPS OVH France 16 Go (services lourds à la demande) |
| **Stockage** | Hybride : VPS (cerveau, index, métadonnées) + PC (fichiers) |
| **Sécurité** | Tailscale (zéro exposition Internet) + Presidio (RGPD) + age/SOPS |

---

## 🏗️ Architecture

### Couches techniques

```
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
| **Framework agents IA** | LangGraph | 1.2.0 |
| **Orchestration workflows** | n8n | 2.4.8 |
| **LLM cloud** | Mistral API | Nemo / Medium 3.1 / Large 3 / Embed |
| **LLM local (VPS)** | Ollama | Mistral Nemo 12B / Ministral 3B |
| **Base de données** | PostgreSQL | 16 |
| **Cache + Pub/Sub** | Redis | 7 |
| **Vectoriel** | Qdrant | Latest |
| **Mémoire graphe** | Zep + Graphiti | Latest (fallback Neo4j) |
| **API Gateway** | FastAPI | Latest |
| **Bot conversationnel** | python-telegram-bot | Latest |
| **Reverse proxy** | Caddy | Latest |
| **Réseau sécurisé** | Tailscale | Latest |
| **OCR** | Surya + Marker | Latest |
| **STT** | Faster-Whisper | Latest (fallback Deepgram) |
| **TTS** | Kokoro | Latest (fallback Piper) |
| **NER** | spaCy fr + GLiNER | Latest |
| **Anonymisation** | Presidio | Latest |

---

## 🗂️ Structure du projet

```
friday-2.0/
├── README.md                    # Ce fichier
├── CLAUDE.md                    # Instructions pour AI agents
├── _docs/
│   ├── architecture-friday-2.0.md     # Architecture complète (1700+ lignes)
│   └── friday-2.0-analyse-besoins.md  # Analyse besoins initiale
│
├── docker-compose.yml           # Services principaux
├── docker-compose.dev.yml       # Override dev
├── docker-compose.services.yml  # Services lourds à la demande
├── .env.example
├── Makefile
│
├── agents/                      # Python 3.12 - LangGraph
│   ├── src/
│   │   ├── supervisor/          # Superviseur (routage + orchestration RAM)
│   │   ├── agents/              # 23 modules agents (flat structure)
│   │   ├── memory/              # Zep + Graphiti
│   │   ├── tools/               # Outils partagés (OCR, STT, TTS, NER, anonymize)
│   │   ├── adapters/            # Adaptateurs (LLM, vectorstore, memorystore, filesync, email)
│   │   ├── models/              # Pydantic schemas globaux
│   │   ├── config/              # Configuration
│   │   └── utils/               # Utilitaires
│   └── pyproject.toml
│
├── bot/                         # Telegram bot
│   ├── handlers/
│   ├── keyboards/
│   └── media/transit/
│
├── services/                    # Services Docker custom
│   ├── gateway/                 # FastAPI Gateway
│   ├── stt/                     # Faster-Whisper
│   ├── tts/                     # Kokoro
│   └── ocr/                     # Surya + Marker
│
├── n8n-workflows/               # Workflows n8n (JSON)
├── database/migrations/         # Migrations SQL numérotées
├── tests/                       # Tests (unit, integration, e2e)
├── config/                      # Configuration (Tailscale, Syncthing, Caddy, logging, profiles RAM)
├── scripts/                     # Scripts automation (setup, backup, deploy, monitor-ram)
├── docs/                        # Documentation technique
└── logs/                        # Logs (gitignored)
```

---

## 📋 Les 23 modules

| # | Module | Priorité | Couche |
|---|--------|----------|--------|
| 1 | Moteur Vie (pipeline mail, desktop search) | 5/5 | Ingestion + Intelligence |
| 2 | Archiviste (OCR, renommage, classement) | 5/5 | Ingestion + Intelligence |
| 3 | Agenda (multi-casquettes) | 5/5 | Action |
| 4 | Briefing matinal | Auto | Action |
| 5 | Plaud Note (transcription → cascade actions) | 4/5 | Ingestion + Agents |
| 6 | Photos BeeStation | Auto | Ingestion + Intelligence |
| 7 | Aide en consultation (medic, posologies, recos HAS) | 4/5 | Agents spécialisés |
| 8 | Veilleur Droit (contrats, clauses, audit) | 5/5 | Agents spécialisés |
| 9 | Tuteur Thèse (pré-correction méthodologique) | 5/5 | Agents spécialisés |
| 10 | Check Thèse (anti-hallucination, sources) | 5/5 | Agents spécialisés |
| 11 | Générateur TCS | 3/5 | Agents spécialisés |
| 12 | Générateur ECOS | 3/5 | Agents spécialisés |
| 13 | Actualisateur de cours | 3/5 | Agents spécialisés |
| 14 | Suivi financier (5 périmètres) | 5/5 | Agents spécialisés |
| 15 | Détection d'anomalies financières | Auto | Agents spécialisés |
| 16 | Optimisation fiscale inter-structures | Nice to have | Agents spécialisés |
| 17 | Aide à l'investissement | 3/5 | Agents spécialisés |
| 18 | Menus & Courses | Auto | Agents spécialisés + Action |
| 19 | Coach remise en forme | Auto | Agents spécialisés + Action |
| 20 | Entretien cyclique | Auto | Action |
| 21 | Collection jeux vidéo | Auto | Agents spécialisés |
| 22 | CV académique | Nice to have | Agents spécialisés |
| 23 | Mode HS / Vacances | Auto | Action |

---

## 🔐 Sécurité & RGPD

| Aspect | Solution |
|--------|----------|
| **Exposition Internet** | Aucune (Tailscale mesh VPN) |
| **Données sensibles en base** | Chiffrement pgcrypto (colonnes médicales, financières) |
| **Secrets (.env, API keys)** | age/SOPS (chiffrement dans git) |
| **Anonymisation avant LLM cloud** | Presidio obligatoire (pipeline RGPD) |
| **Hébergement** | OVH France (RGPD compliant) |
| **LLM pour données sensibles** | Ollama local VPS (Mistral Nemo 12B / Ministral 3B) |
| **SSH** | Uniquement via Tailscale (pas de port 22 ouvert) |

---

## 🚀 Quick Start

**Prérequis :**
- Python 3.12+
- Docker + Docker Compose v2
- Tailscale installé
- VPS OVH 16 Go (ou équivalent)

**Installation :**

```bash
# 1. Cloner le repo
git clone <repo-url>
cd friday-2.0

# 2. Setup automatique (dev)
./scripts/dev-setup.sh

# 3. Configurer .env
cp .env.example .env
# Éditer .env avec vos API keys

# 4. Démarrer les services
docker compose up -d

# 5. Vérifier le healthcheck
curl http://localhost:8000/api/v1/health
```

**Commandes utiles :**

```bash
make up          # Démarrer tous les services
make down        # Arrêter tous les services
make logs        # Voir les logs
make migrate     # Exécuter les migrations SQL
make backup      # Backup manuel BDD + volumes
make test        # Lancer les tests
```

---

## 📚 Documentation

- **Architecture complète** : [_docs/architecture-friday-2.0.md](_docs/architecture-friday-2.0.md)
- **Analyse besoins** : [_docs/friday-2.0-analyse-besoins.md](_docs/friday-2.0-analyse-besoins.md)
- **Documentation technique** : `docs/` (à créer pendant l'implémentation)
- **Instructions AI agents** : [CLAUDE.md](CLAUDE.md)

---

## 🎯 Principes de développement

### KISS Day 1

- Structure flat `agents/src/agents/` (23 modules au même niveau)
- Pas d'ORM (asyncpg brut)
- Pas de Celery (n8n + FastAPI BackgroundTasks)
- Pas de Prometheus Day 1 (scripts/monitor-ram.sh suffit)
- Refactoring si douleur réelle, pas par anticipation

### Évolutibilité by design

- 5 adaptateurs (LLM, vectorstore, memorystore, filesync, email) = remplaçables sans refactoring massif
- Event-driven (Redis Pub/Sub) = découplage maximal
- Configuration externe (profiles.py, health_checks.py) = ajout sans modifier code

### Contraintes matérielles

- VPS 16 Go avec profils RAM gérés
- Services lourds mutuellement exclusifs (Ollama Nemo 12B ⊗ Faster-Whisper 4GB)
- Orchestrator LangGraph gère ordonnancement dynamique

---

## 💰 Budget

| Poste | Coût mensuel |
|-------|-------------|
| VPS OVH Elite 16 Go | ~24€ |
| Mistral API (Nemo + Medium + Large + Embed) | ~6-9€ |
| Deepgram STT fallback | ~3-5€ |
| Divers (domaine, ntfy) | ~2-3€ |
| **Total estimé** | **35-41€/mois** |

---

## 📄 Licence

Projet personnel d'Antonio. Tous droits réservés.

---

## 🙏 Remerciements

Architecture conçue collaborativement avec **BMAD (Business Modeling & Agile Development)** workflow :
- Mary (Business Analyst)
- Winston (Architect) - remplacé après Step 3
- Amelia (Developer)
- Murat (Test Architect)
- John (Product Manager)

Validation adversariale par Code Review Agent.

---

**Status actuel** : Architecture complétée ✅ - Prêt pour implémentation

**Next step** : Story 1 - Infrastructure de base (PostgreSQL, Redis, FastAPI Gateway, Tailscale)
