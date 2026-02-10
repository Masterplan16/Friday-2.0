# CLAUDE.md - Friday 2.0

Instructions pour Claude Code lors du développement de Friday 2.0.

---

## 🌍 Langue de travail

**IMPORTANT : Tous les échanges doivent se faire en français.**

---

## 📚 Source de vérité architecturale

**RÈGLE ABSOLUE : Le document [_docs/architecture-friday-2.0.md](_docs/architecture-friday-2.0.md) est la référence unique pour toutes décisions architecturales.**

En cas de doute ou conflit, se référer aux Steps 1-8 du document d'architecture.

---

## 🎯 Principes architecturaux (NON NÉGOCIABLES)

### 1. KISS Day 1 - Start Simple, Split When Pain

**Toujours partir simple, refactorer seulement si douleur réelle.**

| Principe | Application |
|----------|-------------|
| **Structure flat** | `agents/src/agents/` = 23 modules au même niveau Day 1 |
| **Refactoring trigger** | Module >500 lignes OU 3+ modules partagent >100 lignes identiques OU tests impossibles à maintenir |
| **Pattern** | Extract interface → Create adapter → Replace implementation |
| **JAMAIS** | Big bang refactoring, sur-organisation prématurée |

**Exemple :**
```python
# ✅ CORRECT Day 1 (flat)
agents/src/agents/email/agent.py          # 450 lignes OK

# ❌ INCORRECT Day 1 (sur-organisation prématurée)
agents/src/agents/email/
  ├── agent.py
  ├── classifier.py
  └── summarizer.py
```

---

### 2. Évolutibilité by design - Pattern adaptateur

**Chaque composant externe DOIT avoir un adaptateur.**

| Adaptateur | Fichier | Remplaçable par |
|------------|---------|-----------------|
| LLM | `adapters/llm.py` | Claude Sonnet 4.5 (D17) → tout autre provider (1 fichier) |
| Vectorstore | `adapters/memorystore.py` | pgvector dans PostgreSQL (D19 Day 1) → Qdrant/Milvus si >300k vecteurs |
| Memorystore | `adapters/memorystore.py` | PostgreSQL+pgvector (Day 1, D19) → Graphiti/Neo4j (si maturité atteinte) |
| Filesync | `adapters/filesync.py` | Syncthing → rsync/rclone |
| Email | `adapters/email.py` | EmailEngine → IMAP direct |

**Factory pattern obligatoire :**
```python
def get_llm_adapter() -> LLMAdapter:
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    if provider == "anthropic":
        return AnthropicAdapter(api_key=os.getenv("ANTHROPIC_API_KEY"))
    # Extensible : ajouter d'autres providers si veille D18 le justifie
    raise ValueError(f"Unknown LLM provider: {provider}")
```

---

### 3. Contraintes matérielles - VPS-4 OVH 48 Go RAM

**Tous services lourds résidents en simultané. Plus d'exclusion mutuelle.**

| Service lourd | RAM | Mode |
|---------------|-----|------|
| Faster-Whisper | ~4 Go | Résident |
| Kokoro TTS | ~2 Go | Résident |
| Surya OCR | ~2 Go | Résident |
| **Total services lourds** | **~8 Go** | Ollama retiré (D12), LLM = Claude Sonnet 4.5 API (D17) |
| **Socle permanent (corrigé)** | **~6-8 Go** | Inclut PG (+pgvector D19), Redis, n8n, Presidio, EmailEngine, Caddy, OS (SANS Zep - fermé 2024, SANS Qdrant - D19) |
| **Marge disponible** | **~32-34 Go** | Cohabitation Jarvis Friday possible (~5 Go) |

**Orchestrator simplifié (moniteur RAM, pas gestionnaire d'exclusions) :**
```python
# config/profiles.py
SERVICE_RAM_PROFILES: dict[str, ServiceProfile] = {
    "faster-whisper": ServiceProfile(ram_gb=4),
    "kokoro-tts": ServiceProfile(ram_gb=2),
    "surya-ocr": ServiceProfile(ram_gb=2),
}
RAM_ALERT_THRESHOLD_PCT = 85  # Alerte si dépasse (40.8 Go sur 48 Go)
```

**Cohabitation Jarvis Friday** : Le VPS-4 48 Go permet d'héberger Friday 2.0 (~15 Go) + Jarvis Friday (~5 Go) avec large marge (~28 Go restants).

---

### 4. Sécurité RGPD - Pipeline Presidio OBLIGATOIRE

**RÈGLE CRITIQUE : Anonymisation AVANT tout appel LLM cloud.**

```python
# ❌ INTERDIT
response = await anthropic_client.messages.create(messages=[{"role": "user", "content": text_with_pii}])

# ✅ CORRECT
anonymized_text = await presidio_anonymize(text_with_pii)
response = await anthropic_client.messages.create(messages=[{"role": "user", "content": anonymized_text}])
result = await presidio_deanonymize(response)
```

**Autres règles sécurité :**
- Tailscale = RIEN exposé sur Internet public (SSH uniquement via Tailscale, 2FA obligatoire)
- age/SOPS pour secrets (JAMAIS de `.env` en clair dans git, JAMAIS de credentials en default dans le code)
- pgcrypto pour colonnes sensibles BDD (données médicales, financières)
- Redis ACL : moindre privilège par service (voir addendum section 9.2)
- Mapping Presidio : éphémère en mémoire uniquement, JAMAIS stocké en clair (voir addendum section 9.1)

---

### 5. Observability & Trust Layer - OBLIGATOIRE

**RÈGLE CRITIQUE : Chaque action de module DOIT passer par le décorateur `@friday_action`.**

#### Trust Levels (3 niveaux)

| Niveau | Comportement | Exemples |
|--------|-------------|----------|
| `auto` | Exécute + notifie après coup | Classification email, OCR, briefing |
| `propose` | Prépare + attend validation Telegram (inline buttons) | Brouillon réponse mail, classement financier |
| `blocked` | Analyse uniquement, jamais d'action | Données médicales, investissement, modification contrat |

**Initialisation par risque :** Low risk → `auto`, Medium → `propose`, High → `blocked`.

**Promotion/rétrogradation :**
- **Rétrogradation auto** : `auto` → `propose` si accuracy <90% sur 1 semaine (échantillon ≥10 actions)
- **Promotion manuelle** : `propose` → `auto` si accuracy ≥95% sur 3 semaines + validation Mainteneur
- **Anti-oscillation** : Après rétrogradation, minimum 2 semaines avant nouvelle promotion

Voir [addendum section 7](_docs/architecture-addendum-20260205.md) pour la définition formelle complète (formule, granularité par action, seuils minimaux).

#### Middleware `@friday_action`

```python
# agents/src/middleware/trust.py
@friday_action(module="email", action="classify", trust_default="propose")
async def classify_email(email: Email) -> ActionResult:
    # 1. Charge les correction_rules du module
    rules = await db.fetch(
        "SELECT conditions, output FROM core.correction_rules "
        "WHERE module='email' AND active=true"
    )
    # 2. Injecte les règles dans le prompt
    prompt = f"Classe cet email. Règles prioritaires: {format_rules(rules)}..."
    response = await llm_adapter.complete(prompt=prompt)
    # 3. Retourne ActionResult standardisé
    return ActionResult(
        input_summary=f"Email de {email.sender}: {email.subject}",
        output_summary=f"→ {response.category}",
        confidence=response.score,
        reasoning=f"Mots-clés: {response.keywords}..."
    )
```

#### ActionResult (modèle Pydantic obligatoire)

```python
# agents/src/middleware/models.py
class ActionResult(BaseModel):
    input_summary: str       # Ce qui est entré
    output_summary: str      # Ce qui a été fait
    confidence: float        # 0.0-1.0, confidence MIN de tous les steps
    reasoning: str           # Pourquoi cette décision
    payload: dict = {}       # Données techniques optionnelles
    steps: list[StepDetail] = []  # Sous-étapes détaillées
```

#### Feedback Loop (règles explicites, PAS de RAG)

```python
# ~50 règles max → un SELECT suffit, injectées dans le prompt
# Cycle : correction Mainteneur → détection pattern (2 occurrences) →
#   proposition de règle → validation Mainteneur → règle active
```

#### Tables SQL associées

- `core.action_receipts` — Reçus de chaque action (migration `011_trust_system.sql`)
- `core.correction_rules` — Règles de correction explicites
- `core.trust_metrics` — Accuracy hebdomadaire par module/action

#### Commandes Telegram Trust

| Commande | Usage |
|----------|-------|
| `/status` | Dashboard temps réel (services, dernières actions) |
| `/journal` | 20 dernières actions avec timestamps |
| `/receipt <id>` | Détail complet d'une action (-v pour steps) |
| `/confiance` | Tableau accuracy par module |
| `/stats` | Métriques globales agrégées |

#### Stratégie de Notification - Telegram Topics (Story 1.6)

**Architecture** : Supergroup Telegram avec **5 topics spécialisés** (décision 2026-02-05)

| Topic | Rôle | Contenu |
|-------|------|---------|
| 💬 **Chat & Proactive** (DEFAULT) | Conversation bidirectionnelle | Commandes, questions, heartbeat, reminders |
| 📬 **Email & Communications** | Notifications email | Classifications, PJ, emails urgents |
| 🤖 **Actions & Validations** | Validations trust=propose | Inline buttons Approve/Reject |
| 🚨 **System & Alerts** | Santé système | RAM >85%, services down, errors |
| 📊 **Metrics & Logs** | Métriques non-critiques | Actions auto, stats, logs |

**Rationale** : Éviter le chaos informationnel (tout mélangé dans un seul canal = illisible). Topics permettent filtrage granulaire via mute/unmute natif Telegram selon contexte utilisateur.

**Contrôle utilisateur** :
- Mode Normal : Tous topics actifs
- Mode Focus : Mute Email + Metrics, garde Actions + System
- Mode Deep Work : Mute tout sauf System
- Pas de quiet hours codées (utiliser fonctionnalités natives téléphone)

**Voir** : [Architecture addendum §11](_docs/architecture-addendum-20260205.md#11-stratégie-de-notification--telegram-topics-architecture) pour spécification complète (routing logic, configuration, impact stories).

---

## 🗂️ Standards techniques

### PostgreSQL - 3 schemas obligatoires

| Schema | Contenu | Usage |
|--------|---------|-------|
| `core` | Configuration, jobs, audit, utilisateurs | Socle système, jamais touché par pipelines |
| `ingestion` | Emails, documents, fichiers, métadonnées | Zone d'entrée données brutes |
| `knowledge` | Entités, relations, métadonnées embeddings | Zone de sortie post-traitement IA |

**JAMAIS** de table dans `public` schema.

---

### Migrations SQL - Numérotées, pas d'ORM

| Élément | Standard |
|---------|----------|
| Format | `001_init_schemas.sql`, `002_core_tables.sql`, etc. |
| Outil | Script Python custom `scripts/apply_migrations.py` |
| ORM | **AUCUN** (asyncpg brut) |
| Rollback | Via backup pré-migration automatique |

**Rationale :** Système pipeline/agent, pas CRUD classique. Requêtes optimisées à la main.

---

### Pydantic v2 - Validation partout

| Usage | Fichiers |
|-------|----------|
| Schemas API | `services/gateway/schemas/*.py` (FastAPI natif) |
| Schemas pipeline | `agents/src/models/*.py` |
| Config | `agents/src/config/settings.py` (BaseSettings) |

---

### Event-driven - Redis Streams + Pub/Sub

**Format événements :** Dot notation

**Transport : Redis Streams (événements critiques) vs Pub/Sub (informatifs)**

| Événement | Transport | Justification |
|-----------|-----------|---------------|
| `email.received` | **Redis Streams** | Critique - perte = email non traité |
| `document.processed` | **Redis Streams** | Critique - perte = document ignoré |
| `pipeline.error` | **Redis Streams** | Critique - perte = erreur silencieuse |
| `service.down` | **Redis Streams** | Critique - perte = panne non détectée |
| `trust.level.changed` | **Redis Streams** | Critique - perte = incohérence trust |
| `action.corrected` | **Redis Streams** | Critique - perte = feedback perdu |
| `action.validated` | **Redis Streams** | Critique - perte = validation perdue |
| `agent.completed` | Redis Pub/Sub | Non critique - retry possible |
| `file.uploaded` | Redis Pub/Sub | Non critique - détectable par scan |

**Règle** : Tout événement dont la perte entraîne une action manquée ou une incohérence d'état → Redis Streams. Événements informatifs/retry-safe → Redis Pub/Sub.

**Communication patterns :**
- **Sync** : REST (FastAPI) pour requêtes
- **Async critique** : Redis Streams pour événements métier (delivery garanti)
- **Async informatif** : Redis Pub/Sub pour logs/notifications (fire-and-forget)
- **HTTP interne** : Docker network pour services (n8n, emailengine, etc.)

---

### Error handling - Hiérarchie standardisée

```python
# config/exceptions/__init__.py
class FridayError(Exception):
    """Base exception Friday 2.0"""
    pass

class PipelineError(FridayError):
    """Erreurs pipeline ingestion/traitement"""
    pass

class AgentError(FridayError):
    """Erreurs agents IA"""
    pass

class InsufficientRAMError(FridayError):
    """RAM insuffisante pour service lourd"""
    pass

# Retry automatique
RETRYABLE_EXCEPTIONS = (ConnectionError, TimeoutError, RateLimitError)
```

---

### Logging - JSON structuré

```python
# config/logging.py (structlog)
{
    "timestamp": "2026-02-02T14:30:00Z",
    "service": "email-agent",
    "level": "INFO",
    "message": "Email classifié",
    "context": {
        "email_id": "abc123",
        "category": "medical",
        "confidence": 0.95
    }
}
```

---

### Naming conventions

| Élément | Convention | Exemple |
|---------|-----------|---------|
| Migrations SQL | Numérotées 3 chiffres | `001_init_schemas.sql` |
| Events Redis | Dot notation | `email.received` |
| Pydantic schemas | PascalCase | `EmailMessage`, `DocumentMetadata` |
| Fonctions Python | snake_case | `anonymize_text()`, `classify_email()` |
| Constantes | UPPER_SNAKE_CASE | `SERVICE_RAM_PROFILES` |

---

## 🧪 Tests - Standards obligatoires

### Tests critiques RGPD

**Presidio anonymization :**
```python
# tests/integration/test_anonymization_pipeline.py
# Dataset : tests/fixtures/pii_samples.json
@pytest.mark.integration
async def test_presidio_anonymizes_all_pii(pii_samples):
    for sample in pii_samples:
        anonymized = await anonymize_text(sample["input"])
        # Vérifier entités sensibles anonymisées
        for entity_type in sample["entities"]:
            assert f"[{entity_type}_" in anonymized
        # Vérifier pas de fuite PII
        for sensitive_value in sample["sensitive_values"]:
            assert sensitive_value not in anonymized
```

### Tests orchestrator RAM (VPS-4 48 Go)

```python
# tests/unit/supervisor/test_orchestrator.py
@pytest.mark.asyncio
async def test_ram_monitor_alerts_on_threshold():
    monitor = RAMMonitor(total_ram_gb=48, alert_threshold_pct=85)
    # Simuler charge élevée (>85% de 48 Go = 40.8 Go)
    monitor.simulate_usage(used_gb=42)
    alerts = await monitor.check()
    assert alerts[0].level == "warning"
    assert "85%" in alerts[0].message

@pytest.mark.asyncio
async def test_all_heavy_services_fit_in_ram():
    monitor = RAMMonitor(total_ram_gb=48, alert_threshold_pct=85)
    # Tous services lourds résidents simultanément (Ollama retiré D12)
    services = ["faster-whisper", "kokoro-tts", "surya-ocr"]
    for svc in services:
        await monitor.register_service(svc)
    assert monitor.total_allocated_gb <= 48 * 0.85  # Sous le seuil d'alerte (40.8 Go)
```

### Tests Trust Layer

```python
# tests/unit/middleware/test_trust.py
@pytest.mark.asyncio
async def test_friday_action_auto_executes_and_logs():
    """Trust=auto : exécute l'action + crée un receipt"""
    result = await classify_email(mock_email)
    receipt = await db.fetchrow("SELECT * FROM core.action_receipts ORDER BY created_at DESC LIMIT 1")
    assert receipt["status"] == "auto"
    assert receipt["confidence"] > 0

@pytest.mark.asyncio
async def test_friday_action_propose_waits_validation():
    """Trust=propose : crée receipt pending + envoie inline buttons Telegram"""
    result = await draft_email_reply(mock_email)
    receipt = await db.fetchrow("SELECT * FROM core.action_receipts ORDER BY created_at DESC LIMIT 1")
    assert receipt["status"] == "pending"
    assert receipt["trust_level"] == "propose"

@pytest.mark.asyncio
async def test_auto_retrogradation_below_90pct():
    """Si accuracy < 90% sur 1 semaine → rétrograde auto → propose"""
    # Simuler 10 actions dont 2 corrigées (80%)
    await simulate_corrections(module="email", action="classify", total=10, corrected=2)
    await run_nightly_metrics()
    new_level = await get_trust_level("email", "classify")
    assert new_level == "propose"
```

### Tests agents

**JAMAIS d'appels LLM réels en tests unitaires - Toujours mocker.**

```python
# ✅ CORRECT
@patch("agents.src.adapters.llm.AnthropicAdapter")
async def test_email_classifier(mock_llm):
    mock_llm.return_value.complete.return_value = "medical"
    # ...

# ❌ INCORRECT
async def test_email_classifier():
    # Appel réel à Claude API = coûteux + instable
```

---

## 🚫 Anti-patterns (INTERDITS)

| Anti-pattern | Raison | Alternative |
|--------------|--------|-------------|
| **ORM (SQLAlchemy/Tortoise)** | Système pipeline, pas CRUD | asyncpg brut + SQL optimisé |
| **Celery** | Redondant avec n8n + FastAPI | n8n (workflows longs) + BackgroundTasks (courts) |
| **Prometheus Day 1** | 400 Mo RAM, overkill pour Friday seul | `scripts/monitor-ram.sh` (cron + Telegram) |
| **GraphQL** | Over-engineering utilisateur unique | REST + Pydantic suffit |
| **Structure 3 niveaux Day 1** | Sur-organisation prématurée | Flat structure, refactor si douleur |
| **localStorage direct pour auth** | Token expiré, pas de refresh | `api()` helper ou `getAuthHeaders()` |
| **Big bang refactoring** | Risque régression massive | Refactoring incrémental si douleur réelle |

---

## 🤖 Bot Telegram

**Story 1.9** - Interface utilisateur Friday via Telegram avec 5 topics spécialisés.

### Structure
```
bot/
├── main.py              # Point d'entrée, heartbeat, graceful shutdown
├── config.py            # Configuration telegram.yaml + envvars
├── routing.py           # Routage événements → topics
├── models.py            # Pydantic models (TelegramEvent, BotConfig)
├── handlers/
│   ├── commands.py      # /help, /start, stubs Story 1.11
│   ├── messages.py      # Messages texte + onboarding
│   └── callbacks.py     # Inline buttons (Story 1.10)
└── requirements.txt
```

### 5 Topics spécialisés
1. **💬 Chat & Proactive** (DEFAULT) - Conversation bidirectionnelle
2. **📬 Email & Communications** - Notifications email
3. **🤖 Actions & Validations** - Actions nécessitant validation
4. **🚨 System & Alerts** - Santé système
5. **📊 Metrics & Logs** - Métriques non-critiques

### Commandes disponibles
- `/help` - Liste complète des commandes
- `/start` - Alias de /help
- Commandes Story 1.11 (stubs) : `/status`, `/journal`, `/receipt`, `/confiance`, `/stats`, `/budget`

### Variables d'environnement requises
```bash
# Token + Supergroup
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_SUPERGROUP_ID=<chat_id>

# Thread IDs des 5 topics (extraits via scripts/extract_telegram_thread_ids.py)
TOPIC_CHAT_PROACTIVE_ID=<thread_id>
TOPIC_EMAIL_ID=<thread_id>
TOPIC_ACTIONS_ID=<thread_id>
TOPIC_SYSTEM_ID=<thread_id>
TOPIC_METRICS_ID=<thread_id>

# User Mainteneur
ANTONIO_USER_ID=<user_id>

# Database & Redis
DATABASE_URL=postgresql://user:pass@host:5432/db
REDIS_URL=redis://user:pass@host:6379/0
```

### Déploiement
```bash
# Docker Compose (recommandé)
docker compose up -d friday-bot

# Standalone
docker build -f Dockerfile.bot -t friday-bot .
docker run -d --name friday-bot --env-file .env friday-bot
```

### Documentation complète
Voir [bot/README.md](bot/README.md) pour architecture détaillée, troubleshooting, tests.

---

## 🔧 Commandes utiles

### Development

```bash
# Setup automatique environnement dev
./scripts/dev-setup.sh

# Démarrer services core
docker compose up -d postgres redis

# Migrations
python scripts/apply_migrations.py

# Tests
pytest tests/unit -v                    # Tests unitaires
pytest tests/integration -v             # Tests intégration
pytest tests/e2e -v                     # Tests end-to-end
pytest --cov=agents --cov-report=html   # Coverage

# Linting
black agents/                           # Format code
isort agents/                           # Trier imports
mypy agents/ --strict                   # Type checking
flake8 agents/                          # Linting
```

### Production (VPS)

```bash
# Déploiement
./scripts/deploy.sh

# Monitoring RAM
./scripts/monitor-ram.sh                # Alerte si >85%

# Backup
./scripts/backup.sh                     # Backup BDD + volumes

# Logs
docker compose logs -f                  # Tous services
docker compose logs -f gateway          # Gateway uniquement
```

---

## 📋 Checklist avant commit

**Pré-commit hooks automatiques :**
- [x] `black` (format code)
- [x] `isort` (trier imports)
- [x] `flake8` (linting)
- [x] `mypy --strict` (type checking)
- [x] `sqlfluff` (migrations SQL)

**Checklist manuelle :**
- [ ] Tests ajoutés/mis à jour pour nouveaux features
- [ ] Presidio anonymization si données sensibles touchées
- [ ] Adaptateurs utilisés pour composants externes (jamais d'import direct LLM/vectorstore)
- [ ] Configuration externalisée (pas de valeurs hardcodées)
- [ ] Logs structurés JSON (pas de print())
- [ ] Documentation mise à jour si API publique modifiée
- [ ] `@friday_action` sur toute nouvelle action de module (trust level défini)
- [ ] `ActionResult` retourné avec confidence et reasoning
- [ ] Trust level approprié au risque (auto/propose/blocked)

---

## 🎯 Implémentation — Numérotation BMAD

> **Source de vérité** : [sprint-status.yaml](_bmad-output/implementation-artifacts/sprint-status.yaml) + [epics-mvp.md](_bmad-output/planning-artifacts/epics-mvp.md)
>
> Sprint 1 MVP = **7 Epics, 45 stories, 82 FRs**. Sprint 2 Growth = Epics 8-13. Sprint 3 Vision = Epics 14-20.

### Epic 1 : Socle Opérationnel & Contrôle (15 stories | 28 FRs)

Prérequis à tout. Infrastructure, Trust Layer, sécurité RGPD, Telegram, Self-Healing, opérations.

| Story | Titre | Status | Fichiers existants |
|-------|-------|--------|-------------------|
| **1.1** | Infrastructure Docker Compose | **review** | `docker-compose.yml`, `docker-compose.services.yml`, `tests/unit/infra/test_docker_compose.py`, `config/Caddyfile`, `config/redis.acl` |
| **1.2** | Schemas PostgreSQL & Migrations | ready-for-dev | `database/migrations/001-012_*.sql`, `scripts/apply_migrations.py` |
| **1.3** | FastAPI Gateway & Healthcheck | backlog | — |
| **1.4** | Tailscale VPN & Sécurité Réseau | backlog | `config/redis.acl` |
| **1.5** | Presidio Anonymisation & Fail-Explicit | ready-for-dev | `agents/src/tools/anonymize.py` |
| **1.6** | Trust Layer Middleware | ready-for-dev | `agents/src/middleware/trust.py`, `agents/src/middleware/models.py`, `config/trust_levels.yaml` |
| **1.7** | Feedback Loop & Correction Rules | backlog | — |
| **1.8** | Trust Metrics & Rétrogradation | ready-for-dev | `services/metrics/nightly.py` |
| **1.9** | Bot Telegram Core & Topics | backlog | — |
| **1.10** | Inline Buttons & Validation | backlog | — |
| **1.11** | Commandes Telegram Trust & Budget | backlog | — |
| **1.12** | Backup Chiffré & Sync PC | ready-for-dev | `tests/e2e/test_backup_restore.sh`, `scripts/monitor-ram.sh` |
| **1.13** | Self-Healing Tier 1-2 | ready-for-dev | `scripts/monitor-ram.sh` |
| **1.14** | Monitoring Docker Images | backlog | — |
| **1.15** | Cleanup & Purge RGPD | backlog | — |

### Epics 2-7 (Sprint 1 MVP — tous backlog, dépendent d'Epic 1)

| Epic | Stories | Titre | Dépendances |
|------|---------|-------|-------------|
| **2** | 2.1-2.7 | Pipeline Email Intelligent | Epic 1 complet |
| **3** | 3.1-3.7 | Archiviste & Recherche Documentaire | Epic 1 + Epic 2 |
| **4** | 4.1-4.5 | Intelligence Proactive & Briefings (incl. Heartbeat Engine) | Epic 1 + 2 + 3 |
| **5** | 5.1-5.4 | Interaction Vocale & Personnalité | Epic 1 |
| **6** | 6.1-6.4 | Mémoire Éternelle & Migration 110k emails | Epic 1 |
| **7** | 7.1-7.3 | Agenda & Calendrier Multi-casquettes | Epic 1 + 2 |

### Séquence d'implémentation suggérée

1. **Epic 1** (Socle) — prérequis à tout, stories 1.1→1.15 séquentielles
2. **Epic 6** (Mémoire) — PostgreSQL knowledge.* + pgvector nécessaires pour Epic 3
3. **Epic 2** (Email) — besoin #1 Mainteneur
4. **Epic 3** (Archiviste) — inséparable du pipeline email (PJ)
5. **Epic 5** (Vocal) — STT/TTS transversal
6. **Epic 7** (Agenda) — détecte événements dans emails
7. **Epic 4** (Proactivité) — briefing nécessite tous les modules précédents

### Dépendances critiques avant Epic 2

- PostgreSQL 16 + pgvector opérationnel avec 3 schemas + migrations 001-012 appliquées (Stories 1.1 + 1.2)
- Redis 7 opérationnel avec ACL par service (Story 1.1 + 1.4)
- FastAPI Gateway opérationnel avec `/api/v1/health` (Story 1.3)
- Tailscale mesh VPN configuré, 2FA obligatoire (Story 1.4)
- `@friday_action` middleware opérationnel (Story 1.6)
- Bot Telegram opérationnel avec 5 topics (Story 1.9)
- Presidio + spaCy-fr installés, fail-explicit (Story 1.5)

### Fichiers transversaux déjà créés

- ✅ `docker-compose.yml` + `docker-compose.services.yml` (Story 1.1)
- ✅ `database/migrations/001-012_*.sql` (Stories 1.1 + 1.2)
- ✅ `scripts/apply_migrations.py` (Story 1.2)
- ✅ `scripts/migrate_emails.py` (Story 6.4)
- ✅ `config/trust_levels.yaml` (Story 1.6)
- ✅ `config/redis.acl` + `config/Caddyfile` (Story 1.1 + 1.4)
- ✅ `agents/src/tools/anonymize.py` (Story 1.5)
- ✅ `agents/src/middleware/models.py` + `trust.py` (Story 1.6)
- ✅ `services/alerting/` (Story 1.9 dépendance)
- ✅ `services/metrics/nightly.py` (Story 1.8)
- ✅ `agents/docs/heartbeat-engine-spec.md` (Story 4.1 spec)
- ✅ `.sops.yaml`, `docs/DECISION_LOG.md`, `tests/fixtures/README.md`
- 📋 `services/gateway/` — À créer (Story 1.3)
- 📋 `bot/` — À créer (Story 1.9)
- 📋 `agents/src/core/heartbeat.py` + `context.py` — À créer (Story 4.1)

### Décisions architecturales clés

- **Memorystore (D19, 2026-02-09)** : PostgreSQL + pgvector Day 1. Qdrant retiré. Réévaluation si >300k vecteurs ou latence >100ms.
- **Heartbeat (2026-02-05)** : Natif Friday (pas OpenClaw). Réévaluation août 2026.
- **Graphiti (2026-02-05)** : Zep fermé 2024. Day 1 = PG + pgvector. Réévaluation Graphiti 6 mois (~août 2026).
- **LLM (D17, 2026-02-09)** : 100% Claude Sonnet 4.5. Zéro routing multi-provider.

---

## 🚀 Workflows BMAD recommandés

| Workflow | Usage |
|----------|-------|
| `bmad:bmm:workflows:create-epics-and-stories` | Transformer architecture en stories implémentables |
| `bmad:bmm:workflows:dev-story` | Implémenter une story (tasks/subtasks, tests, validation) |
| `bmad:bmm:workflows:code-review` | Review adversarial (trouver 3-10 problèmes minimum) |
| `bmad:bmm:workflows:quick-dev` | Dev flexible (tech-spec OU instructions directes) |
| `bmad:bmm:workflows:testarch-*` | Framework tests, ATDD, NFR assessment, CI/CD |

---

## 📞 Notifications Windows (BurntToast)

**RÈGLE : Notifier l'utilisateur dans les cas suivants.**

```powershell
# Tâche terminée
New-BurntToastNotification -Text "Claude", "Tâche terminée ✓"

# Question / Besoin d'attention
New-BurntToastNotification -Text "Claude", "J'ai besoin de ton attention"

# Erreur bloquante
New-BurntToastNotification -Text "Claude", "Erreur - Action requise"

# Longue tâche en cours (>2min)
New-BurntToastNotification -Text "Claude", "Toujours en cours..."
```

---

## 📚 Documentation de référence

### Documents principaux

- **Architecture complète** : [_docs/architecture-friday-2.0.md](_docs/architecture-friday-2.0.md) (~2500 lignes)
  *Source de vérité unique pour toutes décisions architecturales. Inclut : infrastructure, stack tech, sécurité RGPD, graphe de connaissances, Trust Layer, clarifications techniques complètes*

- **Analyse besoins** : [_docs/friday-2.0-analyse-besoins.md](_docs/friday-2.0-analyse-besoins.md)
  *Vision produit, 23 modules fonctionnels, sources de données, interconnexions, contraintes techniques (mise à jour 2026-02-05)*

- **Validation architecture** : [_docs/analyse-fonctionnelle-complete.md](_docs/analyse-fonctionnelle-complete.md)
  *Document de contrôle qualité (5 février 2026) - Vérifie cohérence architecture/besoins/implémentation. Inclut : diagrammes flux PC/VPS/BeeStation, répartition stockage, mesures sécurité transversales, 23 modules détaillés*

- **README** : [README.md](README.md)
  *Quick start, setup développement, commandes utiles*

### Documents techniques additionnels

- **Workflows n8n** : [docs/n8n-workflows-spec.md](docs/n8n-workflows-spec.md)
  *Spécifications complètes des 3 workflows critiques Day 1 (Email Ingestion, Briefing Daily, Backup Daily). Includes nodes, triggers, variables, tests*

- **Stratégie tests IA** : [docs/testing-strategy-ai.md](docs/testing-strategy-ai.md)
  *Pyramide de tests (80% unit mocks, 15% integ datasets, 5% E2E). Métriques qualité, datasets validation, tests critiques RGPD/RAM/Trust*

- **Roadmap implémentation** : [docs/implementation-roadmap.md](docs/implementation-roadmap.md)
  *Stories détaillées (1-9+), séquence implémentation, Acceptance Criteria, dépendances, durées estimées*

- **Addendum architecture (2026-02-05)** : [_docs/architecture-addendum-20260205.md](_docs/architecture-addendum-20260205.md)
  *Clarifications techniques : Presidio benchmark, pattern detection algo, profils RAM, critères OpenClaw, population graphe, trust retrogradation formelle (section 7), healthcheck complet (section 8), sécurité compléments (section 9), avertissement Zep (section 10), stratégie notification Telegram Topics (section 11)*

- **Politique modèles IA** : [docs/ai-models-policy.md](docs/ai-models-policy.md)
  *Versionnage modèle unique Claude Sonnet 4.5 (D17), procédure upgrade, veille mensuelle D18, surveillance accuracy/coûts, gestion budget mensuel*

- **Setup PC Backup** : [docs/pc-backup-setup.md](docs/pc-backup-setup.md)
  *Configuration complète PC Mainteneur pour recevoir backups quotidiens VPS via rsync/Tailscale. Guides par OS (Windows/WSL, Linux, macOS), SSH setup, tests validation*

### Configuration & Scripts implémentation

- **Trust levels config** : [config/trust_levels.yaml](config/trust_levels.yaml)
  *Configuration initiale trust levels pour les 23 modules (auto/propose/blocked par action)*

- **Script migration SQL** : [scripts/apply_migrations.py](scripts/apply_migrations.py)
  *Application migrations SQL avec tracking, backup automatique, rollback en cas d'erreur*

- **Script migration emails** : [scripts/migrate_emails.py](scripts/migrate_emails.py)
  *Migration 110k emails avec checkpointing, retry, resume, progress tracking*

- **Script monitoring RAM** : [scripts/monitor-ram.sh](scripts/monitor-ram.sh)
  *Vérification usage RAM + alertes Telegram si >85% (cron-able)*

- **Script vérification env** : [scripts/verify_env.sh](scripts/verify_env.sh)
  *Validation variables d'environnement requises avant démarrage*

- **Script Redis Streams setup** : [scripts/setup-redis-streams.sh](scripts/setup-redis-streams.sh)
  *Création consumer groups pour événements critiques*

- **Test backup/restore** : [tests/e2e/test_backup_restore.sh](tests/e2e/test_backup_restore.sh)
  *Test E2E complet : backup PostgreSQL → disaster simulation → restore → validation intégrité*

- **Plan création datasets** : [tests/fixtures/README.md](tests/fixtures/README.md)
  *Guide complet création datasets tests IA (PII, Email Classification, Archiviste, Finance, Thèse). Durées, responsable, formats*

### Guides techniques additionnels

- **Secrets Management** : [docs/secrets-management.md](docs/secrets-management.md)
  *Guide complet age/SOPS : installation, chiffrement/déchiffrement .env, partage clés, rotation*

- **Redis Streams Setup** : [docs/redis-streams-setup.md](docs/redis-streams-setup.md)
  *Configuration complète Redis Streams : consumer groups, retry, recovery, monitoring*

- **Playwright Automation** : [docs/playwright-automation-spec.md](docs/playwright-automation-spec.md)
  *Spécification automatisation web (Carrefour Drive, etc.) - Alternative fiable à Browser-Use*

- **Decision Log** : [docs/DECISION_LOG.md](docs/DECISION_LOG.md)
  *Historique chronologique des décisions architecturales majeures*

---

**Version** : 1.6.0 (2026-02-09)
**Status** : Architecture complète + D17 100% Claude Sonnet 4.5 (remplace Mistral/Gemini/Ollama) + Trust Layer + Code Review v2 — **Prêt pour implémentation Story 1**
