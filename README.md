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
| **Budget** | ~36-42€/mois (VPS OVH VPS-4 + APIs cloud) |
| **Philosophie** | KISS Day 1, évolutibilité by design (5 adaptateurs) |
| **Hébergement** | VPS-4 OVH France — 48 Go RAM / 12 vCores / 300 Go NVMe |
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
| **Framework agents IA** | LangGraph | 0.2.45+ |
| **Orchestration workflows** | n8n | 1.69.2+ |
| **LLM cloud** | Mistral API | Nemo / Medium 3.1 / Large 3 / Embed |
| **LLM local (VPS)** | Ollama | Mistral Nemo 12B / Ministral 3B |
| **Base de données** | PostgreSQL | 16.6 |
| **Cache + Pub/Sub** | Redis | 7.4 |
| **Vectoriel** | Qdrant | 1.12.5 |
| **Mémoire graphe** | Zep + Graphiti | Latest (fallback Neo4j) |
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
│   │   ├── memory/              # Zep + Graphiti
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
| **LLM pour données sensibles** | Ollama local VPS (Mistral Nemo 12B / Ministral 3B) |
| **SSH** | Uniquement via Tailscale (pas de port 22 ouvert) |

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

- VPS-4 OVH : 48 Go RAM / 12 vCores / 300 Go NVMe (~25€ TTC/mois)
- Tous services lourds résidents en simultané (Ollama + Whisper + Kokoro + Surya = ~16 Go)
- Marge disponible : ~25 Go
- Orchestrator simplifié : moniteur RAM, plus d'exclusion mutuelle

---

## 💰 Budget

| Poste | Coût mensuel |
|-------|-------------|
| VPS OVH VPS-4 48 Go (France, sans engagement) | ~25€ TTC |
| Mistral API (Nemo + Medium + Large + Embed) | ~6-9€ |
| Deepgram STT fallback | ~3-5€ |
| Divers (domaine, ntfy) | ~2-3€ |
| **Total estimé** | **~36-42€/mois** |

Marge ~8-14€ sur budget max 50€/mois. Plan B : VPS-3 (24 Go, ~15€ TTC) si besoin de réduire.

---

## 📊 Status du projet

| Phase | Status |
|-------|--------|
| Analyse des besoins | ✅ Terminée + Mise à jour contraintes techniques |
| Architecture complète | ✅ Terminée (~2500 lignes) + Analyse adversariale complète ✅ |
| Observability & Trust Layer | ✅ Conçu + Spécifié en détail |
| Workflows n8n critiques | ✅ Spécifiés (Email Ingestion, Briefing Daily, Backup Daily) |
| Stratégie tests IA | ✅ Documentée (pyramide, datasets, métriques) |
| 21 clarifications techniques | ✅ Toutes ajoutées dans l'architecture |
| Story 1 : Infrastructure de base | 📋 Conçue, prête pour implémentation |
| Story 1.5 : Trust Layer | 📋 Conçue, prête pour implémentation |
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

Projet personnel d'Antonio. Tous droits réservés.

---

**Version** : 1.3.0 (2026-02-05)
**Dernière mise à jour** : Analyse adversariale complète + 21 clarifications techniques + review cohérence documentaire
