# Story 1.3: FastAPI Gateway & Healthcheck

Status: done

## Story

En tant que **développeur Friday 2.0**,
Je veux **déployer le FastAPI Gateway avec auth bearer token, OpenAPI/Swagger UI, et un healthcheck étendu surveillant 10 services critiques**,
Afin que **tous les services soient accessibles via une API REST sécurisée avec documentation interactive, et que l'état de santé du système soit facilement consultable (3 états : healthy, degraded, unhealthy)**.

## Acceptance Criteria

1. `GET /api/v1/health` retourne l'état de 10 services critiques avec 3 états possibles
2. État `healthy` : tous les services critiques (PostgreSQL, Redis) sont UP
3. État `degraded` : au moins un service non-critique est DOWN (ex: n8n)
4. État `unhealthy` : au moins un service critique est DOWN
5. Cache healthcheck avec TTL de 5 secondes pour éviter surcharge
6. OpenAPI documentation accessible sur `/docs` (Swagger UI)
7. Auth bearer token simple pour single-user (header `Authorization: Bearer <token>`)
8. Logs structurés JSON (structlog) sans emojis
9. Gateway démarre sans erreur et répond sur le port 8000
10. Tests unitaires et d'intégration couvrant les 3 états healthcheck

## Tasks / Subtasks

- [x] Task 1 : Implémenter la structure FastAPI Gateway de base (AC: #7, #9)
  - [x] 1.1 Créer `services/gateway/main.py` avec app FastAPI
  - [x] 1.2 Configurer structlog pour logging JSON (pas de print(), pas d'emojis)
  - [x] 1.3 Ajouter middleware CORS pour développement
  - [x] 1.4 Configurer uvicorn avec workers et reload (dev)
  - [x] 1.5 Créer Dockerfile multi-stage (dev + production)

- [x] Task 2 : Implémenter l'authentification bearer token simple (AC: #7)
  - [x] 2.1 Créer `services/gateway/auth.py` avec fonction `verify_token()`
  - [x] 2.2 Dependency `get_current_user` utilisant `HTTPBearer`
  - [x] 2.3 Token stocké dans variable env `API_TOKEN` (age/SOPS chiffré)
  - [x] 2.4 Retourner 401 si token invalide ou manquant
  - [x] 2.5 Tester auth avec pytest (6 tests)

- [x] Task 3 : Implémenter le healthcheck étendu multi-services (AC: #1-#5)
  - [x] 3.1 Créer `services/gateway/healthcheck.py` avec classe `HealthChecker`
  - [x] 3.2 Définir liste des 10 services critiques et non-critiques (voir Dev Notes)
  - [x] 3.3 Implémenter checks async parallèles via `asyncio.create_task()`
  - [x] 3.4 Logique 3 états : healthy (tous critical OK), degraded (non-critical down), unhealthy (critical down)
  - [x] 3.5 Cache Redis avec TTL 5s (clé `healthcheck:cache`)
  - [x] 3.6 Endpoint `GET /api/v1/health` retournant JSON structuré

- [x] Task 4 : Configurer OpenAPI/Swagger UI (AC: #6)
  - [x] 4.1 Configurer `title`, `description`, `version` dans FastAPI app
  - [x] 4.2 Activer Swagger UI sur `/docs`
  - [x] 4.3 Activer ReDoc sur `/redoc` (documentation alternative)
  - [x] 4.4 Ajouter exemples de requêtes dans les docstrings
  - [x] 4.5 Tester docs accessibles et fonctionnelles (3 tests OpenAPI)

- [x] Task 5 : Écrire les tests unitaires et d'intégration (AC: #10)
  - [x] 5.1 Test : healthcheck retourne `healthy` si tous services UP
  - [x] 5.2 Test : healthcheck retourne `degraded` si n8n DOWN
  - [x] 5.3 Test : healthcheck retourne `unhealthy` si PostgreSQL DOWN
  - [x] 5.4 Test : cache healthcheck fonctionne (cache miss + cache hit + TTL)
  - [x] 5.5 Test : auth bearer token valide → 200, invalide → 401
  - [x] 5.6 Test : OpenAPI schema généré correctement
  - [x] 5.7 Test : logs structurés JSON (pas d'emojis, format valide)

- [x] Task 6 : Validation finale et déploiement Docker (AC: #9)
  - [x] 6.1 Dockerfile multi-stage créé (dev + production)
  - [x] 6.2 Vérifier reverse proxy Caddy route bien vers gateway (config existante OK)
  - [x] 6.3 Healthcheck Docker dans docker-compose.yml (déjà configuré Story 1.1)
  - [x] 6.4 API_TOKEN ajouté dans docker-compose.yml et .env.example
  - [x] 6.5 143/143 tests passent, zero régression

## Dev Notes

### 10 Services surveillés par le healthcheck

**Services critiques** (DOWN = unhealthy) :
1. **PostgreSQL** : Base de données principale (3 schemas)
2. **Redis** : Cache et pub/sub
3. **EmailEngine** : Réception emails (4 comptes IMAP)

**Services non-critiques** (DOWN = degraded) :
4. **n8n** : Orchestration workflows (peut redémarrer sans impact immédiat)
5. **Caddy** : Reverse proxy (si down, le healthcheck ne sera pas accessible, mais service gateway fonctionne)
6. **Presidio** : Anonymisation RGPD (peut être temporairement indisponible, mode dégradé sans anonymisation bloquera les appels LLM)
7. **Faster-Whisper** : STT vocal (Epic 5, peut être absent Day 1)
8. **Kokoro TTS** : Synthèse vocale (Epic 5, peut être absent Day 1)
9. **Surya OCR** : OCR documents (Epic 3, peut être absent Day 1)
10. **Telegram Bot** : Interface utilisateur (Epic 1.9, peut être absent Day 1)

**Note** : Les services 7-10 peuvent ne pas être déployés lors de Story 1.3. Le healthcheck doit gérer leur absence gracieusement (état "not_deployed" distinct de "down").

### Format de réponse healthcheck

```json
{
  "status": "healthy",  // ou "degraded" ou "unhealthy"
  "timestamp": "2026-02-09T14:30:00Z",
  "services": {
    "postgresql": {"status": "up", "latency_ms": 12},
    "redis": {"status": "up", "latency_ms": 3},
    "emailengine": {"status": "up", "latency_ms": 45},
    "n8n": {"status": "up", "latency_ms": 120},
    "caddy": {"status": "up", "latency_ms": 5},
    "presidio": {"status": "up", "latency_ms": 80},
    "faster_whisper": {"status": "not_deployed"},
    "kokoro_tts": {"status": "not_deployed"},
    "surya_ocr": {"status": "not_deployed"},
    "telegram_bot": {"status": "not_deployed"}
  },
  "cache_hit": false
}
```

**Statuts possibles par service** :
- `"up"` : Service répond correctement (+ latency_ms)
- `"down"` : Service ne répond pas ou erreur
- `"not_deployed"` : Service pas encore déployé (normal pour Epic 3, 5, etc.)

### Architecture Guardrails - RÈGLES ABSOLUES

**Source** : [CLAUDE.md](../../CLAUDE.md) + [architecture-friday-2.0.md](../../_docs/architecture-friday-2.0.md)

| Contrainte | Valeur | Justification |
|------------|--------|---------------|
| **Langage** | Python 3.12+ | LangGraph requirement |
| **Framework** | FastAPI | Performance async, OpenAPI natif |
| **Auth** | Bearer token simple (single-user) | Antonio seul utilisateur, pas besoin OAuth2 complet |
| **Logging** | structlog (JSON) | JAMAIS print(), JAMAIS emojis dans les logs |
| **Validation** | Pydantic v2 | Schemas API + config |
| **ORM** | **AUCUN** | asyncpg brut uniquement |
| **Error handling** | FridayError > PipelineError > GatewayError | Hiérarchie standardisée |
| **Cache** | Redis (TTL 5s) | Éviter surcharge PostgreSQL |
| **CORS** | Activé en dev, restrictif en production | Sécurité |
| **HTTPS** | Caddy reverse proxy | Certificats auto via Let's Encrypt |

### Latest Tech Stack (recherche web 2026-02-09)

**FastAPI** :
- Dernière version stable : 0.115+ (vérifier `pip list`)
- Auth bearer token : `OAuth2PasswordBearer` (FastAPI natif)
- Healthcheck : Pattern async `asyncio.gather()` pour checks parallèles
- Password hashing : **Argon2id** (recommendation 2026, remplace bcrypt)
- Swagger UI : Configurable via `swagger_ui_parameters`

**Sources** :
- [FastAPI Security First Steps](https://fastapi.tiangolo.com/tutorial/security/first-steps/)
- [FastAPI Best Practices 2026](https://fastlaunchapi.dev/blog/fastapi-best-practices-production-2026)
- [FastAPI Health Check Pattern](https://python.plainenglish.io/fastapi-microservice-patterns-health-check-api-bb839c2df18a)
- [Configure Swagger UI - FastAPI](https://fastapi.tiangolo.com/how-to/configure-swagger-ui/)

### Healthcheck Implementation Pattern (2026)

```python
# services/gateway/healthcheck.py
import asyncio
import time
from typing import Literal

import structlog
from redis.asyncio import Redis
import asyncpg

logger = structlog.get_logger()

ServiceStatus = Literal["up", "down", "not_deployed"]
SystemStatus = Literal["healthy", "degraded", "unhealthy"]

CRITICAL_SERVICES = {"postgresql", "redis", "emailengine"}

class HealthChecker:
    def __init__(self, cache_ttl: int = 5):
        self.cache_ttl = cache_ttl
        self.redis = None  # Initialisé dans lifespan FastAPI
        self.pg_pool = None  # Initialisé dans lifespan FastAPI

    async def check_postgresql(self) -> tuple[ServiceStatus, float]:
        """Check PostgreSQL avec latence"""
        start = time.time()
        try:
            async with self.pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            latency_ms = (time.time() - start) * 1000
            return ("up", latency_ms)
        except Exception as e:
            logger.error("postgresql_check_failed", error=str(e))
            return ("down", 0)

    async def check_redis(self) -> tuple[ServiceStatus, float]:
        """Check Redis avec latence"""
        start = time.time()
        try:
            await self.redis.ping()
            latency_ms = (time.time() - start) * 1000
            return ("up", latency_ms)
        except Exception as e:
            logger.error("redis_check_failed", error=str(e))
            return ("down", 0)

    async def check_service_http(self, name: str, url: str) -> tuple[ServiceStatus, float]:
        """Check service HTTP générique"""
        import httpx
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url)
                response.raise_for_status()
            latency_ms = (time.time() - start) * 1000
            return ("up", latency_ms)
        except httpx.HTTPStatusError:
            return ("down", 0)
        except httpx.RequestError:
            # Service pas déployé vs service down
            # Pour Story 1.3, services Epic 3/5 ne sont pas déployés
            return ("not_deployed", 0)

    async def check_all_services(self) -> dict:
        """Check tous les services en parallèle"""
        # Vérifier cache Redis
        cache_key = "healthcheck:cache"
        cached = await self.redis.get(cache_key)
        if cached:
            import json
            result = json.loads(cached)
            result["cache_hit"] = True
            return result

        # Exécuter tous les checks en parallèle
        checks = {
            "postgresql": self.check_postgresql(),
            "redis": self.check_redis(),
            "emailengine": self.check_service_http("emailengine", "http://emailengine:3000/health"),
            "n8n": self.check_service_http("n8n", "http://n8n:5678/healthz"),
            "caddy": self.check_service_http("caddy", "http://caddy:80/"),
            "presidio": self.check_service_http("presidio", "http://presidio-analyzer:3000/health"),
            "faster_whisper": self.check_service_http("faster_whisper", "http://faster-whisper:8001/health"),
            "kokoro_tts": self.check_service_http("kokoro_tts", "http://kokoro-tts:8002/health"),
            "surya_ocr": self.check_service_http("surya_ocr", "http://surya-ocr:8003/health"),
            "telegram_bot": self.check_service_http("telegram_bot", "http://telegram-bot:8080/health"),
        }

        results = await asyncio.gather(*checks.values(), return_exceptions=True)

        # Construire résultat
        services = {}
        for (name, _), result in zip(checks.items(), results):
            if isinstance(result, Exception):
                services[name] = {"status": "down"}
            else:
                status, latency = result
                services[name] = {"status": status}
                if latency > 0:
                    services[name]["latency_ms"] = int(latency)

        # Déterminer état système global
        system_status = self._determine_system_status(services)

        response = {
            "status": system_status,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "services": services,
            "cache_hit": False
        }

        # Mettre en cache
        import json
        await self.redis.setex(cache_key, self.cache_ttl, json.dumps(response))

        return response

    def _determine_system_status(self, services: dict) -> SystemStatus:
        """Détermine l'état global du système"""
        # Au moins un service critique DOWN → unhealthy
        for service_name in CRITICAL_SERVICES:
            if services.get(service_name, {}).get("status") == "down":
                return "unhealthy"

        # Au moins un service non-critique DOWN → degraded
        for service_name, service_data in services.items():
            if service_name not in CRITICAL_SERVICES:
                if service_data.get("status") == "down":
                    return "degraded"

        # Tous services OK (ou not_deployed) → healthy
        return "healthy"
```

### Authentication Implementation Pattern

```python
# services/gateway/auth.py
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import structlog

logger = structlog.get_logger()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Token stocké dans env var chiffrée (age/SOPS)
API_TOKEN = os.getenv("API_TOKEN")  # JAMAIS de default en clair

async def verify_token(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Vérifie le bearer token.
    Single-user, simple comparison.
    """
    if not API_TOKEN:
        logger.error("api_token_not_configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API token not configured"
        )

    if token != API_TOKEN:
        logger.warning("invalid_token_attempt", token_prefix=token[:8] if token else "")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"username": "antonio"}  # Single user

# Dependency pour protéger les routes
async def get_current_user(user: dict = Depends(verify_token)) -> dict:
    return user
```

### FastAPI Main Application

```python
# services/gateway/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import structlog
import asyncpg
from redis.asyncio import Redis

from .healthcheck import HealthChecker
from .auth import get_current_user

logger = structlog.get_logger()

# Lifespan context manager pour initialiser/fermer les connexions
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("gateway_starting")

    # Initialiser pool PostgreSQL
    app.state.pg_pool = await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL"),
        min_size=2,
        max_size=10
    )

    # Initialiser Redis
    app.state.redis = Redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379"),
        decode_responses=True
    )

    # Initialiser HealthChecker
    app.state.health_checker = HealthChecker(cache_ttl=5)
    app.state.health_checker.pg_pool = app.state.pg_pool
    app.state.health_checker.redis = app.state.redis

    logger.info("gateway_started")

    yield  # Application runs

    # Shutdown
    logger.info("gateway_stopping")
    await app.state.pg_pool.close()
    await app.state.redis.close()
    logger.info("gateway_stopped")

app = FastAPI(
    title="Friday 2.0 Gateway",
    description="API Gateway pour Friday 2.0 - Second Cerveau Personnel",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS (dev uniquement, restrictif en production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # n8n
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/health")
async def health_check(request: Request):
    """
    Healthcheck étendu surveillant 10 services.

    États possibles :
    - healthy : tous services critiques UP
    - degraded : au moins un service non-critique DOWN
    - unhealthy : au moins un service critique DOWN

    Cache : 5 secondes TTL
    """
    health_checker: HealthChecker = request.app.state.health_checker
    result = await health_checker.check_all_services()

    # Retourner 503 si unhealthy (standard HTTP)
    status_code = 200
    if result["status"] == "unhealthy":
        status_code = 503
    elif result["status"] == "degraded":
        status_code = 200  # Dégradé mais opérationnel

    return JSONResponse(content=result, status_code=status_code)

@app.get("/api/v1/protected")
async def protected_route(current_user: dict = Depends(get_current_user)):
    """
    Route protégée exemple (nécessite auth bearer token).
    """
    return {"message": f"Hello {current_user['username']}!"}
```

### Previous Story Intelligence (Story 1.2)

**Learnings de Story 1.2** :
- **111 tests passent** : Framework de test robuste en place (pytest + structlog)
- **asyncpg fonctionne** : Pool connections PostgreSQL opérationnel
- **Migrations idempotentes** : Script `apply_migrations.py` fiable avec backup/rollback
- **structlog configuré** : Logs JSON sans emojis, format standardisé
- **Docker Compose stable** : PostgreSQL + Redis + n8n + Caddy fonctionnent ensemble
- **Code review Opus 4.6** : Détection de 11 issues (4H, 4M, 3L) — être très vigilant sur la cohérence
- **Linting actif** : black, isort, flake8, mypy --strict activés

**Pièges à éviter** :
- ❌ Ne PAS utiliser `subprocess.run()` sans `asyncio.create_subprocess_exec` (bloque event loop)
- ❌ Ne PAS oublier les timeouts sur les requêtes HTTP (httpx.AsyncClient)
- ❌ Ne PAS mettre de credentials en default dans le code (API_TOKEN DOIT être env var)
- ❌ Ne PAS utiliser print() — uniquement structlog
- ❌ Ne PAS oublier BEGIN/COMMIT dans les migrations SQL futures

**Patterns à réutiliser** :
- ✅ Tests avec mocks (unittest.mock.patch)
- ✅ Tests async (pytest-asyncio)
- ✅ Hiérarchie exceptions (FridayError > PipelineError > GatewayError)
- ✅ Logging structlog avec context (`logger.bind(service="gateway")`)
- ✅ Validation Pydantic v2 pour les schemas

### Git Intelligence (5 derniers commits)

```
485df7b chore(architecture): claude sonnet 4.5 and pgvector setup, fix story 1.2
926d85b chore(infrastructure): add linting, testing config, and development tooling
024f88e docs(telegram-topics): add setup/user guides and extraction script
024d819 docs(telegram-topics): add notification strategy with 5 topics architecture
981cc7a feat(story1.5): implement trust layer middleware and observability services
```

**Patterns observés** :
- Convention commit : `type(scope): message` (conventional commits)
- `chore` pour infrastructure/config, `feat` pour features, `docs` pour documentation
- Tests dans `tests/unit/` et `tests/integration/`
- Pas d'emojis dans les commits ni les logs
- Linting obligatoire avant commit (pre-commit hooks)

### Project Structure Notes

**Fichiers à créer** :
```
services/gateway/
├── __init__.py
├── main.py              # FastAPI app principale
├── auth.py              # Authentication bearer token
├── healthcheck.py       # HealthChecker class
├── config.py            # Configuration (Pydantic Settings)
├── schemas.py           # Pydantic models
└── exceptions.py        # GatewayError hierarchy

tests/unit/gateway/
├── __init__.py
├── test_healthcheck.py  # Tests healthcheck 3 états
├── test_auth.py         # Tests bearer token
└── conftest.py          # Fixtures pytest

docker/gateway/
├── Dockerfile           # Multi-stage (dev + production)
└── requirements.txt     # Dépendances Python
```

**Fichiers à modifier** :
```
docker-compose.yml       # Ajouter service gateway
config/Caddyfile         # Ajouter reverse proxy vers gateway
.env.example             # Ajouter API_TOKEN exemple
```

**Pas de conflit détecté** : Structure cohérente avec Stories 1.1 et 1.2.

### Dépendances techniques

**Python packages** (à ajouter dans `services/gateway/requirements.txt`) :
```txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
asyncpg==0.29.0
redis==5.0.8
httpx==0.27.0
structlog==24.4.0
pydantic==2.9.0
pydantic-settings==2.5.2
python-dotenv==1.0.1
argon2-cffi==23.1.0  # Password hashing (2026 recommendation)
```

**Dev dependencies** :
```txt
pytest==8.3.0
pytest-asyncio==0.24.0
pytest-cov==5.0.0
httpx==0.27.0  # Pour tester les endpoints
```

**Versions minimum** :
- Python : 3.12+
- FastAPI : 0.115+
- PostgreSQL : 16+
- Redis : 7+

### Testing Strategy

**Pyramide de tests** (source : [testing-strategy-ai.md](../../docs/testing-strategy-ai.md)) :
- 80% unitaires (mocks)
- 15% intégration (Docker Compose)
- 5% E2E (via Caddy reverse proxy)

**Tests unitaires** (mocks, rapides) :
- `test_healthcheck_all_services_up` : Mock tous services UP → status "healthy"
- `test_healthcheck_n8n_down` : Mock n8n DOWN → status "degraded"
- `test_healthcheck_postgresql_down` : Mock PostgreSQL DOWN → status "unhealthy"
- `test_healthcheck_cache_hit` : 1er appel cache miss, 2e appel cache hit
- `test_auth_valid_token` : Token correct → 200
- `test_auth_invalid_token` : Token incorrect → 401
- `test_auth_missing_token` : Pas de header → 401

**Tests intégration** (Docker Compose, plus lents) :
- `test_health_endpoint_real_services` : Healthcheck avec vrais services Docker
- `test_protected_route_with_real_auth` : Route protégée avec vrai token

**Coverage minimum** : 85% (pytest-cov)

### Références

- **Architecture** : [_docs/architecture-friday-2.0.md](../../_docs/architecture-friday-2.0.md) — Section "FastAPI Gateway"
- **Addendum** : [_docs/architecture-addendum-20260205.md](../../_docs/architecture-addendum-20260205.md) — Section 8 (healthcheck étendu)
- **Epics MVP** : [_bmad-output/planning-artifacts/epics-mvp.md](../../_bmad-output/planning-artifacts/epics-mvp.md) — Story 1.3 lignes 61-76
- **Story 1.1** : [1-1-infrastructure-docker-compose.md](1-1-infrastructure-docker-compose.md) — Docker Compose, Caddy, healthchecks
- **Story 1.2** : [1-2-schemas-postgresql-migrations.md](1-2-schemas-postgresql-migrations.md) — asyncpg, structlog, testing patterns
- **CLAUDE.md** : [CLAUDE.md](../../CLAUDE.md) — Sections "FastAPI", "Auth", "Logging", "Testing"
- **Testing Strategy** : [docs/testing-strategy-ai.md](../../docs/testing-strategy-ai.md) — Pyramide tests, conventions
- **Secrets Management** : [docs/secrets-management.md](../../docs/secrets-management.md) — age/SOPS pour API_TOKEN

**Sources externes (recherche web 2026-02-09)** :
- [FastAPI Security First Steps](https://fastapi.tiangolo.com/tutorial/security/first-steps/)
- [FastAPI Best Practices 2026](https://fastlaunchapi.dev/blog/fastapi-best-practices-production-2026)
- [FastAPI Health Check Pattern](https://python.plainenglish.io/fastapi-microservice-patterns-health-check-api-bb839c2df18a)
- [Configure Swagger UI - FastAPI](https://fastapi.tiangolo.com/how-to/configure-swagger-ui/)
- [Argon2id Password Hashing 2026](https://betterstack.com/community/guides/scaling-python/authentication-fastapi/)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 via BMAD create-story workflow

### Debug Log References

- Initial test run: 28/32 passed, 4 failed (mock_pg_pool async context manager, raise_server_errors API change, auth dependency injection)
- Fix 1: MockAsyncContextManager + FailingAsyncContextManager for proper asyncpg pool mocking
- Fix 2: raise_server_errors -> raise_server_exceptions (Starlette API change)
- Fix 3: FastAPI dependency_overrides[get_settings] for auth test isolation
- Final: 32/32 gateway tests pass, 143/143 total tests pass

### Completion Notes List

- Story créée par BMAD create-story workflow (2026-02-09)
- Analyse exhaustive : Architecture + Epics + Story 1.2 + Git + Web research
- 10 services healthcheck définis (3 critical, 7 non-critical)
- Guardrails complets : FastAPI patterns 2026, asyncpg, structlog, auth bearer
- Learnings Story 1.2 intégrés (111 tests, asyncpg, structlog, code review Opus)
- Implementation complete (2026-02-09): 32 new tests, 143/143 total, zero regression
- Auth: HTTPBearer (pas OAuth2PasswordBearer) — plus adapte au bearer token simple
- Healthcheck: asyncio.create_task() pour parallelisme (pas gather direct sur dict)
- Config: Pydantic Settings avec factory get_settings() pour injection de dependances
- Schemas: Pydantic v2 models (HealthResponse, ServiceHealth, AuthUser)
- Cache: Redis setex avec TTL configurable (default 5s)
- Dockerfile: Multi-stage (base → dev avec hot-reload → production avec non-root user)
- Sprint-status.yaml mis a jour : ready-for-dev → in-progress → review
- argon2-cffi mentionne dans Dev Notes mais non utilise (bearer token = comparaison simple, pas de hashing necessaire)

### File List

**Fichiers crees** :
- services/gateway/__init__.py
- services/gateway/main.py
- services/gateway/auth.py
- services/gateway/healthcheck.py
- services/gateway/config.py
- services/gateway/schemas.py
- services/gateway/exceptions.py
- services/gateway/logging_config.py
- services/gateway/requirements.txt
- services/gateway/Dockerfile
- tests/unit/gateway/__init__.py
- tests/unit/gateway/test_healthcheck.py (26 tests)
- tests/unit/gateway/test_auth.py (6 tests)
- tests/unit/gateway/conftest.py
- config/__init__.py (canonical exceptions package)
- config/exceptions/__init__.py (canonical FridayError hierarchy)

**Fichiers modifies** :
- docker-compose.yml (ajout API_TOKEN dans env gateway)
- .env.example (API_PASSWORD -> API_TOKEN)

**Fichiers supprimes** :
- services/gateway/api/v1/.gitkeep (obsolete)
- nul (artefact Windows)

## Senior Developer Review (AI)

**Reviewer:** Claude Opus 4.6 via BMAD code-review workflow
**Date:** 2026-02-09

### Issues Found: 3 High, 4 Medium, 2 Low — ALL FIXED

| # | Severite | Issue | Fichier | Fix |
|---|----------|-------|---------|-----|
| H1 | HIGH | `import os` inutilise (violation flake8) | main.py:10 | Import retire |
| H2 | HIGH | `get_settings()` pas cachee (`@lru_cache` manquant) | config.py:37 | `@lru_cache` ajoute |
| H3 | HIGH | `FridayError` dupliquee (pas de source canonique) | exceptions.py | `config/exceptions/__init__.py` cree |
| M1 | MEDIUM | `httpx.AsyncClient` cree/detruit par check HTTP | healthcheck.py:87 | Client reutilisable via `_get_http_client()` |
| M2 | MEDIUM | `open()` sans `with` (resource leak) | test_healthcheck.py:510 | `Path.read_text()` + assertion `__file__` |
| M3 | MEDIUM | Pas de validation `API_TOKEN` au demarrage | main.py lifespan | Warning log si token vide |
| M4 | MEDIUM | `argon2-cffi` dans Dev Notes mais pas utilise | Story Dev Notes | Note ajoutee (pas necessaire pour bearer token) |
| L1 | LOW | CORS `allow_methods/headers=["*"]` en production | main.py:108 | Restrictif en prod, permissif en dev |
| L2 | LOW | Fichier `nul` artefact Windows | racine | Supprime |

### Verification Post-Fix

- 143/143 tests passent (zero regression)
- flake8 clean (zero violation)
- mypy clean (zero erreur)
- Tous les 10 ACs implementes et verifies
- Toutes les tasks [x] reellement implementees

## Change Log

- 2026-02-09: Création Story 1.3 — FastAPI Gateway avec healthcheck étendu (10 services, 3 états), auth bearer token simple, OpenAPI/Swagger UI. Analyse exhaustive architecture + learnings Story 1.2 + web research 2026. Status: ready-for-dev.
- 2026-02-09: Implementation complete — 14 fichiers crees, 2 fichiers modifies, 32 nouveaux tests (143 total, zero regression). Auth HTTPBearer + HealthChecker async parallele + Cache Redis TTL 5s + OpenAPI/Swagger/ReDoc + Dockerfile multi-stage. Status: review.
- 2026-02-09: Code review adversarial — 9 issues (3H, 4M, 2L) identifiees et corrigees. get_settings() cache, httpx client reutilisable, FridayError canonique, CORS restrictif prod, resource leak fix, API_TOKEN validation. 143/143 tests, flake8+mypy clean. Status: done.
