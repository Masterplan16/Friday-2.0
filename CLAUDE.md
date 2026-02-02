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
| LLM | `adapters/llm.py` | Mistral → Gemini/Claude (1 fichier) |
| Vectorstore | `adapters/vectorstore.py` | Qdrant → Milvus/pgvector |
| Memorystore | `adapters/memorystore.py` | Zep+Graphiti → Neo4j/MemGPT |
| Filesync | `adapters/filesync.py` | Syncthing → rsync/rclone |
| Email | `adapters/email.py` | EmailEngine → IMAP direct |

**Factory pattern obligatoire :**
```python
def get_llm_adapter() -> LLMAdapter:
    provider = os.getenv("LLM_PROVIDER", "mistral")
    if provider == "mistral":
        return MistralAdapter(api_key=os.getenv("MISTRAL_API_KEY"))
    # Extensible : ajouter Gemini, Claude, etc.
    raise ValueError(f"Unknown LLM provider: {provider}")
```

---

### 3. Contraintes matérielles - VPS 16 Go RAM

**Services lourds mutuellement exclusifs - Gestion obligatoire.**

| Service lourd | RAM | Compatible avec | Incompatible avec |
|---------------|-----|-----------------|-------------------|
| Ollama Nemo 12B | ~8 Go | Surya, Playwright | Faster-Whisper |
| Ollama Ministral 3B | ~3 Go | Whisper, Kokoro, Surya | - |
| Faster-Whisper | ~4 Go | Ministral 3B, Kokoro | Ollama Nemo 12B |
| Kokoro TTS | ~2 Go | Tout sauf Nemo+Whisper | - |
| Surya OCR | ~2 Go | Tout sauf Nemo+Whisper | - |

**Configuration externe obligatoire :**
```python
# config/profiles.py
SERVICE_RAM_PROFILES: dict[str, ServiceProfile] = {
    "ollama-nemo": ServiceProfile(ram_gb=8, incompatible_with=["faster-whisper"]),
    "ollama-ministral": ServiceProfile(ram_gb=3, incompatible_with=[]),
    "faster-whisper": ServiceProfile(ram_gb=4, incompatible_with=["ollama-nemo"]),
    # ...
}
```

**Orchestrator LangGraph gère l'ordonnancement :**
```python
# agents/src/supervisor/orchestrator.py charge config/profiles.py
```

---

### 4. Sécurité RGPD - Pipeline Presidio OBLIGATOIRE

**RÈGLE CRITIQUE : Anonymisation AVANT tout appel LLM cloud.**

```python
# ❌ INTERDIT
response = await mistral_client.chat(messages=[{"role": "user", "content": text_with_pii}])

# ✅ CORRECT
anonymized_text = await presidio_anonymize(text_with_pii)
response = await mistral_client.chat(messages=[{"role": "user", "content": anonymized_text}])
result = await presidio_deanonymize(response)
```

**Autres règles sécurité :**
- Tailscale = RIEN exposé sur Internet public (SSH uniquement via Tailscale)
- age/SOPS pour secrets (JAMAIS de `.env` en clair dans git)
- pgcrypto pour colonnes sensibles BDD (données médicales, financières)
- Ollama local VPS pour données ultra-sensibles (pas de sortie cloud)

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

### Event-driven - Redis Pub/Sub

**Format événements :** Dot notation

```python
# Exemples
"email.received"           # Nouvel email ingéré
"document.processed"       # Document OCR terminé
"agent.completed"          # Agent a fini sa tâche
"file.uploaded"            # Fichier uploadé via Telegram
```

**Communication patterns :**
- **Sync** : REST (FastAPI) pour requêtes
- **Async** : Redis Pub/Sub pour événements
- **HTTP interne** : Docker network pour services (qdrant, n8n, etc.)

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

### Tests orchestrator RAM

```python
# tests/unit/supervisor/test_orchestrator.py
@pytest.mark.asyncio
async def test_ram_profiles_prevent_conflicts():
    orchestrator = RAMOrchestrator(total_ram_gb=16, reserved_gb=4)
    await orchestrator.start_service("ollama-nemo")  # 8 GB

    # Whisper 4GB devrait échouer (besoin buffer)
    with pytest.raises(InsufficientRAMError):
        await orchestrator.start_service("faster-whisper")
```

### Tests agents

**JAMAIS d'appels LLM réels en tests unitaires - Toujours mocker.**

```python
# ✅ CORRECT
@patch("agents.tools.apis.mistral.MistralClient")
async def test_email_classifier(mock_mistral):
    mock_mistral.return_value.chat.return_value = "medical"
    # ...

# ❌ INCORRECT
async def test_email_classifier():
    # Appel réel à Mistral API = coûteux + instable
```

---

## 🚫 Anti-patterns (INTERDITS)

| Anti-pattern | Raison | Alternative |
|--------------|--------|-------------|
| **ORM (SQLAlchemy/Tortoise)** | Système pipeline, pas CRUD | asyncpg brut + SQL optimisé |
| **Celery** | Redondant avec n8n + FastAPI | n8n (workflows longs) + BackgroundTasks (courts) |
| **Prometheus Day 1** | 400 Mo RAM, overkill VPS 16 Go | `scripts/monitor-ram.sh` (cron + Telegram) |
| **GraphQL** | Over-engineering utilisateur unique | REST + Pydantic suffit |
| **Structure 3 niveaux Day 1** | Sur-organisation prématurée | Flat structure, refactor si douleur |
| **localStorage direct pour auth** | Token expiré, pas de refresh | `api()` helper ou `getAuthHeaders()` |
| **Big bang refactoring** | Risque régression massive | Refactoring incrémental si douleur réelle |

---

## 🔧 Commandes utiles

### Development

```bash
# Setup automatique environnement dev
./scripts/dev-setup.sh

# Démarrer services core
docker compose up -d postgres redis qdrant

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
./scripts/monitor-ram.sh                # Alerte si >90%

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

---

## 🎯 First Implementation Priority

**Story 1 : Infrastructure de base**

1. ✅ Docker Compose (PostgreSQL 16, Redis 7, Qdrant, n8n 2.4.8, Caddy)
2. ✅ Migrations SQL 001-009 (schemas core/ingestion/knowledge + tables)
3. ✅ FastAPI Gateway + auth simple + OpenAPI
4. ✅ Healthcheck endpoint (`GET /api/v1/health`)
5. ✅ Tailscale configuré (VPS hostname `friday-vps`)
6. ✅ Tests end-to-end (sanity check tous services)

**Dépendances critiques avant Story 2 :**
- PostgreSQL 16 opérationnel avec 3 schemas
- Redis 7 opérationnel (cache + pub/sub)
- FastAPI Gateway opérationnel avec `/api/v1/health`
- Tailscale mesh VPN configuré

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

- **Architecture complète** : [_docs/architecture-friday-2.0.md](_docs/architecture-friday-2.0.md) (1700+ lignes)
- **Analyse besoins** : [_docs/friday-2.0-analyse-besoins.md](_docs/friday-2.0-analyse-besoins.md)
- **README** : [README.md](README.md)

---

**Version** : 1.0.0 (2026-02-02)
**Status** : Architecture complétée ✅ - Prêt pour implémentation
