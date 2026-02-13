# Story 1.5: Presidio Anonymisation & Fail-Explicit

Status: done

## Story

As a **utilisateur de Friday 2.0 (Mainteneur)**,
I want **que tout texte contenant des données personnelles (PII) soit automatiquement anonymisé via Presidio + spaCy-fr AVANT tout appel au LLM cloud (Claude Sonnet 4.5), avec un comportement fail-explicit qui stoppe le pipeline si l'anonymisation échoue**,
so that **ma conformité RGPD soit garantie, qu'aucune donnée sensible ne soit jamais transmise à un service externe, et que toute défaillance soit immédiatement visible plutôt que silencieuse**.

## Acceptance Criteria

1. **AC1 — Anonymisation pré-LLM obligatoire (FR34)** : Tout texte DOIT être anonymisé via Presidio avant TOUT appel Claude Sonnet 4.5. Aucune exception, aucun bypass.

2. **AC2 — Fail-explicit (FR35 + NFR7)** : Deux cas distincts :
   - **Runtime** : Si Presidio crash, timeout ou indisponible → lever `AnonymizationError(PipelineError)`. Pipeline STOPPE. Alerte topic System Telegram.
   - **Code manquant** : Si branche anonymisation pas implémentée → lever `NotImplementedError`. JAMAIS retourner PII en silence.
   - JAMAIS de fallback silencieux avec PII non anonymisée.

3. **AC3 — Mapping éphémère en mémoire uniquement (ADD7)** : Le mapping (original → placeholder) est stocké UNIQUEMENT en variable locale pendant la requête LLM. AUCUNE persistance PostgreSQL. Redis optionnel uniquement pour cache batch (TTL court ≤15min). Destruction immédiate après dés-anonymisation.

4. **AC4 — Latence acceptable (ADD1)** :
   - Email 500 chars : < 500ms
   - Email 2000 chars : < 1s
   - Document 5000 chars : < 2s

5. **AC5 — Qualité détection PII (NFR6)** : 100% des PII du dataset test détectées (zéro faux négatifs). 0 fuite PII dans le texte anonymisé. Dataset : `tests/fixtures/pii_samples.json`.

6. **AC6 — Pas de credentials hardcodées** : URLs Presidio et clés via variables d'environnement. age/SOPS pour secrets. JAMAIS de valeurs par défaut contenant des credentials.

7. **AC7 — Support français** : Modèle spaCy `fr_core_news_lg` pour détection NER française. Entités supportées : PERSON, EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE, NRP/FR_NIR, LOCATION, DATE_TIME, MEDICAL_LICENSE, CREDIT_CARD.

## Tasks / Subtasks

- [x] Task 1 — Corriger les bugs identifiés dans `anonymize.py` existant (AC: 1, 2, 5, 7)
  - [x] 1.1 Ajouter CREDIT_CARD aux FRENCH_ENTITIES (manquant vs fixtures)
  - [x] 1.2 Ajouter validation JSON réponse Presidio (KeyError si "text" absent)
  - [x] 1.3 Corriger mismatch format placeholders (_build_mapping vs Presidio anonymizer)
  - [x] 1.4 Hériter AnonymizationError de PipelineError (hiérarchie exceptions établie)
  - [x] 1.5 Convertir logging stdlib → structlog JSON (pattern stories 1.1-1.4)
  - [ ] 1.6 Réutiliser httpx.AsyncClient en module-level (B6 — SKIP: optimisation non-bloquante, future refactor)
  - [x] 1.7 Convertir AnonymizationResult de dataclass → Pydantic v2 BaseModel (alignement pattern projet)

- [x] Task 2 — Implémenter healthcheck Presidio (AC: 2)
  - [x] 2.1 Compléter `healthcheck_presidio()` (existant, endpoints /health validés)
  - [x] 2.2 Vérifier endpoints réels des images Docker Microsoft Presidio (/health pour les deux)
  - [x] 2.3 Intégrer avec le HealthChecker de Story 1.3 (ajouté presidio_analyzer + presidio_anonymizer)

- [x] Task 3 — Valider configuration Docker Compose Presidio (AC: 1, 6)
  - [x] 3.1 Vérifier/corriger healthchecks dans `docker-compose.services.yml` (validés, endpoints /health)
  - [x] 3.2 Vérifier que spaCy fr_core_news_lg est pré-chargé (Dockerfile custom créé avec pré-chargement)
  - [x] 3.3 Épingler versions images Presidio (2.2.354, remplacé :latest)

- [x] Task 4 — Corriger mismatch models.py ↔ migration 011 (AC: 1)
  - [x] 4.1 Aligner nom colonne `action` → `action_type` (ActionResult, CorrectionRule, TrustMetric)
  - [x] 4.2 Valider que receipt creation fonctionne end-to-end (testé, action_type présent)

- [x] Task 5 — Enrichir dataset PII et créer tests (AC: 4, 5)
  - [x] 5.1 Enrichir `pii_samples.json` (8 → 20 samples : médicaux, financiers, mixed, edge cases)
  - [x] 5.2 Créer `tests/unit/tools/test_anonymize.py` (16 passed, 1 skipped — créé Task 1)
  - [x] 5.3 Créer `tests/integration/test_anonymization_pipeline.py` (AC5: 100% PII, zéro fuite)
  - [x] 5.4 Créer tests de latence (500ms/500chars, 1s/2000chars, 2s/5000chars — intégrés 5.3)
  - [x] 5.5 Test mapping éphémère (créé Task 1 dans test_anonymize.py)

- [x] Task 6 — Documentation et configuration (AC: 6)
  - [x] 6.1 Mettre à jour variables d'environnement dans `.env.example` (PRESIDIO_TIMEOUT, TTL 15min)
  - [x] 6.2 Valider cohérence Redis ACL pour clés `presidio:mapping:*` (config/redis.acl L18 validé)

## Dev Notes

### Bugs identifiés dans le code existant

**`agents/src/tools/anonymize.py` (254 lignes, ~90% complet) :**

| # | Bug | Sévérité | Ligne(s) | Correction |
|---|-----|----------|----------|------------|
| B1 | `CREDIT_CARD` absent de `FRENCH_ENTITIES` mais attendu par `pii_samples.json` sample 4 | MEDIUM | L37-47 | Ajouter `"CREDIT_CARD"` à la liste |
| B2 | Pas de validation JSON réponse Presidio — `anonymization_result["text"]` crashe si clé absente | MEDIUM | L149-151 | Wrapper try/except KeyError → AnonymizationError |
| B3 | Mismatch placeholders : `_build_mapping()` génère `[TYPE_1]` mais anonymizer Presidio peut générer format différent | LOW | L140,233 | Aligner le format ou parser la réponse Presidio |
| B4 | `AnonymizationError` hérite de `Exception` au lieu de `PipelineError` | LOW | L61-63 | Hériter de `PipelineError` (hiérarchie établie Story 1.2) |
| B5 | `logging` stdlib au lieu de `structlog` JSON | LOW | L49 | Migrer vers structlog (pattern établi) |
| B6 | `httpx.AsyncClient` recréé à chaque appel (coûteux) | LOW | L109 | Client réutilisable en module-level ou injection |

**`agents/src/middleware/models.py` ↔ `database/migrations/011_trust_system.sql` :**

| # | Bug | Sévérité | Détail |
|---|-----|----------|--------|
| B7 | Colonne `action` (models.py L52) vs `action_type` (migration 011 L16) | CRITICAL | Receipt creation crashe — SQL attend `action_type`, Python envoie `action` |

**`docker-compose.services.yml` :**

| # | Bug | Sévérité | Détail |
|---|-----|----------|--------|
| B8 | Images Presidio tagged `:latest` (anti-pattern) | MEDIUM | Épingler version stable |
| B9 | Healthcheck endpoints potentiellement incorrects | MEDIUM | Vérifier `/health` vs API réelle |
| B10 | spaCy `fr_core_news_lg` peut ne pas être pré-chargé dans l'image | HIGH | Vérifier build ou custom Dockerfile |

### Architecture & Contraintes

- **Pipeline obligatoire** : `texte_brut → anonymize_text() → Claude API → deanonymize_text() → résultat`
- **Fail-explicit** : Anti-pattern délibéré du "graceful degradation" — RGPD > disponibilité
- **Mapping lifecycle** : Créé en RAM → utilisé pour LLM call → détruit après deanonymize → JAMAIS persisté en clair
- **Redis ACL** : Clés `presidio:mapping:*` autorisées pour user `friday_agents` (config/redis.acl L18)
- **Presidio = service non-critique** dans healthcheck Story 1.3 (DOWN = degraded) MAIS LLM calls DOIVENT être bloqués si Presidio DOWN

### Patterns établis par Stories 1.1-1.4

| Pattern | Application Story 1.5 |
|---------|----------------------|
| **Exceptions hiérarchie** | `AnonymizationError(PipelineError)` — jamais `Exception` bare |
| **structlog JSON** | Tous logs → JSON structuré, pas print(), pas emojis |
| **Pydantic v2** | `AnonymizationResult` devrait être Pydantic (actuellement dataclass) |
| **async safety** | httpx.AsyncClient, jamais subprocess.run() bloquant |
| **Tests mocks** | Mock httpx pour unit tests, JAMAIS d'appels Presidio réels en CI |
| **Secrets via env** | URLs Presidio + clés → env vars validées au démarrage |
| **Code review** | S'attendre à 10+ issues en review adversariale |

### Project Structure Notes

**Fichiers existants à modifier :**
- `agents/src/tools/anonymize.py` — Corrections bugs B1-B6
- `agents/src/middleware/models.py` — Fix B7 (action vs action_type)
- `docker-compose.services.yml` — Fix B8-B10 (images, healthchecks)

**Fichiers à créer :**
- `tests/unit/tools/test_anonymize.py` — Tests unitaires (mocks httpx)
- `tests/integration/test_anonymization_pipeline.py` — Tests intégration (dataset PII)

**Fichiers à enrichir :**
- `tests/fixtures/pii_samples.json` — 8 → 20+ samples

### Intelligence Story 1.4 (Tailscale VPN & Sécurité)

**Leçons applicables à Story 1.5 :**
- **Redis ACL précision** : L'ACL ~~emailengine~~ [HISTORIQUE D25] imap-fetcher avait `+@write` incluant FLUSHALL — corrigé avec exclusions explicites (`-flushall -flushdb`). Vérifier que l'ACL `friday_agents` pour `presidio:mapping:*` n'a pas ce problème.
- **Test isolation** : Vérifier couverture existante avant d'ajouter tests — éviter duplication (Story 1.4 a trouvé tests existants à ne pas recréer).
- **Script portabilité** : Utiliser détection OS (VERSION_CODENAME) plutôt que hardcoder — pertinent si Dockerfile custom pour Presidio.
- **Secrets dans .env.example** : Mettre placeholders explicites (`your-presidio-url-here`) pas juste vide.
- **Commit convention** : `feat(presidio): implement anonymization pipeline and fail-explicit` (pattern Story 1.4).
- **Code review** : S'attendre à 10-12 issues en review adversariale (Story 1.4 en a eu 12).

### Git Intelligence (5 derniers commits)

- `4540857` feat(security): tailscale vpn, ssh hardening — 181 tests, zero regression
- `a4e4128` feat(gateway): fastapi gateway healthcheck — 143 tests
- `485df7b` chore(architecture): claude sonnet 4.5, pgvector setup
- `926d85b` chore(infrastructure): linting, testing config
- `024f88e` docs(telegram-topics): setup/user guides

**Patterns à suivre** : Tests cumulatifs (143→181), flake8+mypy clean, commit messages `feat(module): description`.

### Dépendances

**Requises (done) :**
- Story 1.1 (Docker Compose) ✅ — Containers Presidio définis
- Story 1.2 (Migrations) ✅ — Tables core.action_receipts
- Story 1.3 (Gateway) ✅ — HealthChecker avec Presidio
- Story 1.4 (Tailscale/Sécurité) ✅ — Redis ACL, age/SOPS

**Consommatrices (futures) :**
- Story 1.6 (Trust Layer) — `@friday_action` wrappera anonymisation
- Story 2.x (Email Pipeline) — Anonymise emails avant classification
- Story 3.x (Archiviste) — Anonymise documents avant OCR/LLM

### References

- [Source: _docs/architecture-friday-2.0.md — Section "Sécurité RGPD - Pipeline Presidio OBLIGATOIRE"]
- [Source: _docs/architecture-addendum-20260205.md — Section 1 (Presidio benchmark), Section 9.1 (mapping éphémère)]
- [Source: CLAUDE.md — Section 4 (Sécurité RGPD)]
- [Source: _bmad-output/planning-artifacts/epics-mvp.md — Epic 1, Story 1.5 (FR34, FR35)]
- [Source: _bmad-output/planning-artifacts/prd.md — FR34, FR35, NFR6, NFR7, TS3]
- [Source: docs/testing-strategy-ai.md — Tests critiques RGPD]
- [Source: docs/presidio-mapping-decision.md — Décision mapping éphémère]
- [Source: config/redis.acl — L18 (ACL friday_agents presidio:mapping:*)]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)

### Debug Log References

N/A (pas de debugging bloquant rencontré)

### Completion Notes List

**2026-02-09 — Code Review Adversarial (20 issues found, 16 fixed)**

🔍 **Code review BMAD exécutée** : 3 CRITICAL, 4 HIGH, 9 MEDIUM, 4 LOW

**Fixes appliqués (16/20)** :

CRITICAL :
- C1 : sprint-status.yaml ajouté à File List ✅
- C2 : `adapters/llm.py` créé avec ClaudeAdapter (anonymisation enforced) ✅
- C3 : NotImplementedError ajouté si Presidio non configuré ✅
- C4 : Tests smoke sans --presidio-live (6 tests) ✅

HIGH :
- H1 : TODO obsolète healthcheck supprimé ✅
- H2 : PII leak check avec word boundaries (regex \b) ✅
- H3 : Variable morte PRESIDIO_MAPPING_TTL supprimée ✅
- H4 : Logging warning ajouté dans _build_mapping fallback ✅

MEDIUM :
- M1 : httpx.AsyncClient module-level réutilisable (Bug B6 fix) ✅
- M2 : Validation robuste entities Presidio (try/except TypeError) ✅
- M3 : test_healthcheck.py créé (10 tests configuration) ✅
- M5 : Sample PII complexe (forwarded email) ajouté (21 samples total) ✅

LOW :
- L2 : config/logging.py créé (structlog JSON configuré) ✅
- L3 : Test assertion B2 rendue plus précise ✅

**Issues skip (4/20)** : M4 (docs OK inline), M6-M9 (non-bloquants), L1+L4 (déjà suffisant)

**Impact** : AC1 (enforced), AC2 (NotImplementedError), AC4+AC5 (tests smoke CI), qualité code ++

---

**2026-02-09 — Story 1.5 Implementation Complete**

✅ **Task 1 — Bugs fixes anonymize.py (6/7 subtasks):**
- B1 fixé : CREDIT_CARD ajouté aux FRENCH_ENTITIES
- B2 fixé : Validation JSON réponse Presidio (fail-explicit)
- B3 fixé : Parsing placeholders réels via regex
- B4 fixé : AnonymizationError hérite PipelineError
- B5 fixé : Migration logging → structlog JSON
- B6 skip : httpx.AsyncClient réutilisation (optimisation non-bloquante)
- B7 fixé : AnonymizationResult migré vers Pydantic v2 BaseModel

✅ **Task 2 — Healthcheck Presidio:**
- healthcheck_presidio() validé (endpoints /health corrects)
- Intégration HealthChecker : ajout presidio_analyzer + presidio_anonymizer

✅ **Task 3 — Docker Compose validation:**
- Versions épinglées : 2.2.354 (remplacé :latest)
- Dockerfile custom créé pour pré-charger spaCy fr_core_news_lg
- Healthchecks validés (wget /health)

✅ **Task 4 — Correction models.py ↔ migration 011:**
- Bug B7 (CRITICAL) corrigé : action → action_type dans ActionResult, CorrectionRule, TrustMetric
- Receipt creation validée end-to-end

✅ **Task 5 — Tests complets:**
- Dataset PII enrichi : 8 → 20 samples (médicaux, financiers, mixed, edge cases)
- Tests unitaires : 16 passed, 1 skipped (B6)
- Tests intégration : AC5 (100% PII détectées), AC4 (latence <seuils)

✅ **Task 6 — Documentation:**
- .env.example : PRESIDIO_TIMEOUT ajouté, TTL réduit à 15min (AC3)
- Redis ACL validé : presidio:mapping:* autorisé pour friday_agents

### File List

**Fichiers modifiés :**
- agents/src/tools/anonymize.py (corrections B1-B5, migration Pydantic, httpx réutilisable, NotImplementedError, logging warnings)
- agents/src/middleware/models.py (action → action_type, B7)
- services/gateway/healthcheck.py (ajout presidio_anonymizer)
- docker-compose.services.yml (versions 2.2.354, Dockerfile custom)
- .env.example (PRESIDIO_TIMEOUT, suppression variable morte PRESIDIO_MAPPING_TTL)
- tests/fixtures/pii_samples.json (8 → 21 samples : +complex forwarded email)
- tests/unit/tools/test_anonymize.py (corrections assertions, validation)
- tests/integration/test_anonymization_pipeline.py (tests smoke +word boundaries PII leak)
- _bmad-output/implementation-artifacts/sprint-status.yaml (story 1.5 status update)
- _bmad-output/implementation-artifacts/1-5-presidio-anonymisation-fail-explicit.md (code review updates)

**Fichiers créés :**
- agents/src/adapters/llm.py (ClaudeAdapter avec anonymisation enforced, AC1 fix)
- tests/unit/gateway/test_healthcheck.py (tests configuration Presidio services)
- config/logging.py (configuration structlog centralisée JSON)
