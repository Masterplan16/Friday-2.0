# Story 3.2: Classement Arborescence

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **Mainteneur**,
I want **Friday to automatically classify and file documents into the correct folder hierarchy**,
so that **all processed documents are organized logically without manual sorting, and I can find any document instantly**.

## Acceptance Criteria

1. **AC1 - Arborescence initiale** : Friday classe les documents dans les 5 catégories principales : `pro/`, `finance/`, `universite/`, `recherche/`, `perso/` (D24)
2. **AC2 - Finance subdivisée** : Catégorie finance organisée en 5 périmètres : `finance/{selarl|scm|sci_ravas|sci_malbosc|personal}/YYYY/MM-Mois/` (FR10, D24)
3. **AC3 - Classification LLM** : Claude Sonnet 4.5 classifie catégorie + périmètre financier (si applicable) avec confidence ≥0.7 (FR10)
4. **AC4 - Trust Layer propose** : Classification trust=propose Day 1, inline buttons Telegram [Approuver] [Corriger] [Rejeter], puis auto après accuracy ≥95% sur 3 semaines
5. **AC5 - Déplacement fichier** : Document déplacé de zone transit vers arborescence finale sur PC via Syncthing (synchrone, <5s)
6. **AC6 - Pas de contamination** : Validation stricte : aucun document d'un périmètre financier ne peut être classé dans un autre périmètre (FR37)
7. **AC7 - Modification arborescence** : Commande Telegram `/arbo` permet de consulter et modifier l'arborescence (FR108)

## Tasks / Subtasks

### Task 1 : Module Classification Document (AC3, AC4)
- [x] 1.1 : Créer `agents/src/agents/archiviste/classifier.py` avec classe `DocumentClassifier`
- [x] 1.2 : Implémenter `@friday_action(module="archiviste", action="classify", trust_default="propose")`
- [x] 1.3 : Prompt Claude Sonnet 4.5 : extraire `{category, subcategory, confidence, reasoning}` depuis metadata OCR (Story 3.1)
- [x] 1.4 : Validation périmètres finance : si `category=finance` → forcer extraction `subcategory ∈ {selarl, scm, sci_ravas, sci_malbosc, personal}`
- [x] 1.5 : Modèle Pydantic `ClassificationResult(category, subcategory, path, confidence, reasoning)`
- [x] 1.6 : Retourner `ActionResult` avec confidence et reasoning explicite (seuil 0.7 appliqué par pipeline)
- [x] 1.7 : Tests unitaires `test_classifier.py` (mock Claude, 20 tests : 5 catégories + 5 périmètres finance + 7 edge cases + 3 JSON/rules) ✅ 20/20 PASS

### Task 2 : Arborescence Configuration (AC1, AC2, AC7)
- [x] 2.1 : Créer `config/arborescence.yaml` avec structure hiérarchique
- [x] 2.2 : Définir 5 catégories racines : `pro`, `finance`, `universite`, `recherche`, `perso`
- [x] 2.3 : Définir structure finance : `finance/{selarl|scm|sci_ravas|sci_malbosc|personal}/{YYYY}/{MM-Mois}/`
- [x] 2.4 : Définir autres structures : `universite/theses/{Prenom_Nom}/`, `recherche/publications/`, `pro/patients/`, `perso/`
- [x] 2.5 : Validation YAML schema : interdire noms réservés, caractères spéciaux, profondeur >6
- [x] 2.6 : Tests `test_arborescence_config.py` (validation YAML, edge cases) ✅ 19/19 PASS

### Task 3 : Gestionnaire Déplacement Fichiers (AC5)
- [x] 3.1 : Créer `agents/src/agents/archiviste/file_mover.py` avec classe `FileMover`
- [x] 3.2 : Implémenter `async def move_document(source_path: str, classification: ClassificationResult) -> MovedFile`
- [x] 3.3 : Résolution chemin destination depuis `arborescence.yaml` + `classification.category` + `classification.subcategory`
- [x] 3.4 : Création dossiers manquants (recursive `mkdir -p`)
- [x] 3.5 : Déplacement atomique (copy + verify + delete source)
- [x] 3.6 : Gestion conflits : si fichier existe → suffixe `_v2`, `_v3`, etc.
- [x] 3.7 : Update PostgreSQL `ingestion.document_metadata` : colonne `final_path`, `classification_category`, `classification_subcategory`
- [x] 3.8 : Tests unitaires `test_file_mover.py` (7 tests : 7/7 PASS, création dossiers, conflits, atomicité)

### Task 4 : Pipeline Orchestration Classement (AC3-6)
- [x] 4.1 : Créer `agents/src/agents/archiviste/classification_pipeline.py`
- [x] 4.2 : Consumer Redis Streams `document.processed` (depuis Story 3.1 pipeline OCR)
- [x] 4.3 : Séquence : 1) Classify → 2) Validate périmètre finance → 3) Move file → 4) Update PG → 5) Publish `document.classified`
- [x] 4.4 : Validation anti-contamination (AC6) : `if category=finance AND subcategory NOT IN {selarl, scm, sci_ravas, sci_malbosc, personal} → raise ValueError`
- [x] 4.5 : Retry automatique (backoff exponentiel 1s→2s→4s, 3 tentatives) si erreur retryable ✅ (review fix C1)
- [x] 4.6 : Timeout global 10s via asyncio.wait_for, alerte si dépassé ✅ (review fix C2)
- [x] 4.7 : Fail-explicit : si confidence <0.7 → status=pending, notification Redis `notification.system` ✅ (review fix M4)
- [x] 4.8 : Tests anti-contamination Pydantic `test_classification_anti_contamination.py` (8 tests modèle)

### Task 5 : Trust Layer & Notifications Telegram (AC4)
- [x] 5.1 : Config `config/trust_levels.yaml` section `archiviste.classify` : trust=propose (déjà présent)
- [x] 5.2 : Notification Telegram topic **Actions** : inline buttons [Approuver] [Corriger destination] [Rejeter] ✅ `bot/handlers/classification_notifications.py`
- [x] 5.3 : Callback "Corriger destination" : propose liste catégories + sous-menu périmètres finance ✅ `bot/handlers/classification_callbacks.py`
- [x] 5.4 : Notification topic **Metrics** : document classé avec succès (catégorie, confidence, latence) ✅ `send_classification_success()`
- [x] 5.5 : Notification topic **System** : erreur classification (confidence <0.7, périmètre invalide) ✅ `send_classification_error()`
- [x] 5.6 : Tests callbacks `test_classification_callbacks.py` ✅ 15 tests (approve, reject, correct, reclassify, finance perimeters, formatting)

### Task 6 : Commande Telegram Arborescence (AC7)
- [x] 6.1 : Créer `bot/handlers/arborescence_commands.py` ✅
- [x] 6.2 : Commande `/arbo` : affiche arborescence actuelle (format arbre ASCII) ✅
- [x] 6.3 : Commande `/arbo add <category> <path>` : ajoute nouveau dossier (protection finance) ✅
- [x] 6.4 : Commande `/arbo remove <path>` : supprime dossier (protection racine + finance) ✅
- [x] 6.5 : Commande `/arbo stats` : statistiques par catégorie (N documents) ✅
- [x] 6.6 : Validation : owner-only (OWNER_USER_ID), pas de modification périmètres finance racines ✅
- [x] 6.7 : Tests `test_arborescence_commands.py` ✅ 12 tests (owner-only, tree, stats, add, remove, protections)

### Task 7 : Migration SQL & Stockage (AC5)
- [x] 7.1 : Créer migration `database/migrations/037_classification_metadata.sql`
- [x] 7.2 : Ajouter colonnes à `ingestion.document_metadata` : `final_path TEXT`, `classification_category TEXT`, `classification_subcategory TEXT`, `classification_confidence FLOAT`
- [x] 7.3 : Index sur `classification_category`, `classification_subcategory` pour statistiques rapides
- [x] 7.4 : Tests migration (validation via CHECK constraints SQL)

### Task 8 : Tests End-to-End (AC1-7)
- [x] 8.1 : Dataset test : 20 documents variés (5 catégories × 4 documents) ✅ `TEST_DOCUMENTS` constante
- [x] 8.2 : Test E2E `test_classification_end_to_end.py` : pipeline complet ✅ 7 tests (20 docs, anti-contamination, latence, file mover, naming conflict, pipeline Redis)
- [x] 8.3 : Vérifier anti-contamination (AC6) : document finance SELARL ne peut pas aller dans SCM ✅
- [x] 8.4 : Vérifier conflit nommage : 2 fichiers identiques → suffixe _v2 ✅ (test_file_mover.py)
- [x] 8.5 : Vérifier latence < 10s (AC rapide) ✅ `test_classification_latency_under_10s`

### Task 9 : Documentation & Monitoring
- [x] 9.1 : Doc technique `docs/archiviste-classification-spec.md` ✅ (arborescence, pipeline, seuils, AC6, /arbo, monitoring)
- [x] 9.2 : Monitoring latence : log structuré JSON avec timings ✅ classify_duration_ms, move_duration_ms, total_duration_ms
- [x] 9.3 : Alerte si latence médiane >8s ✅ `_check_latency_alert()` fenêtre glissante 10 docs
- [x] 9.4 : Mise à jour `docs/telegram-user-guide.md` section Archiviste ✅ (commande /arbo, notifications, protections)

## Dev Notes

### Contraintes Architecture Friday 2.0

**Stack Technique** :
- **Python** : 3.12+ (asyncio obligatoire)
- **LLM** : Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) — 100% (Decision D17)
  - Temperature : 0.3 (classification = déterministe mais avec nuance)
  - Max tokens : 200 (réponse courte structurée)
- **Anonymisation** : Presidio + spaCy-fr OBLIGATOIRE avant appel Claude (NFR6, NFR7)
- **BDD** : PostgreSQL 16 avec asyncpg brut (PAS d'ORM)
- **Validation** : Pydantic v2 (`ClassificationResult`, `MovedFile`, `ActionResult`)
- **Events** : Redis Streams pour `document.processed` (input) et `document.classified` (output)
- **Trust Layer** : `@friday_action` decorator obligatoire, `ActionResult` avec confidence/reasoning
- **Filesystem** : Syncthing pour sync VPS → PC (zone transit → arborescence finale)

**Patterns Obligatoires** :
1. **Flat structure Day 1** : `agents/src/agents/archiviste/classifier.py`, `file_mover.py`, `classification_pipeline.py`
2. **Fail-explicit** : Si confidence <0.7 OU périmètre finance invalide → status=pending, notification, JAMAIS de classement silencieux erroné
3. **Atomic move** : Copy + verify + delete source (JAMAIS move direct qui peut corrompre)
4. **Tests pyramide** : 80% unit (mocks), 15% integration (Redis+PG+FS réels), 5% E2E (pipeline complet)
5. **Logs structurés JSON** : `structlog` avec context (document_id, category, subcategory, latence, confidence)

### Arborescence Finale PC (D24)

**Chemin racine** : `C:\Users\lopez\BeeStation\Friday\Archives\`

**Structure** :
```
C:\Users\lopez\BeeStation\Friday\Archives\
├── pro/                                  # Cabinet médical professionnel
│   ├── patients/                         # Dossiers patients (anonymisés)
│   └── administratif/                    # Documents administratifs cabinet
├── finance/                              # 5 périmètres financiers (D24)
│   ├── selarl/                           # Cabinet médical SELARL
│   │   ├── 2026/
│   │   │   ├── 01-Janvier/
│   │   │   ├── 02-Fevrier/
│   │   │   └── ...
│   │   └── ...
│   ├── scm/                              # SCM (Société Civile de Moyens)
│   │   └── YYYY/MM-Mois/
│   ├── sci_ravas/                        # SCI Ravas (anciennement sci_1)
│   │   └── YYYY/MM-Mois/
│   ├── sci_malbosc/                      # SCI Malbosc (anciennement sci_2)
│   │   └── YYYY/MM-Mois/
│   └── personal/                         # Finances personnelles
│       └── YYYY/MM-Mois/
├── universite/                           # Enseignement universitaire
│   ├── theses/                           # Encadrement thèses
│   │   ├── Prenom_Nom/                   # Un dossier par thésard
│   │   └── ...
│   └── cours/                            # Supports de cours
├── recherche/                            # Activité recherche
│   ├── publications/                     # Articles, communications
│   └── projets/                          # Dossiers projets recherche
└── perso/                                # Personnel (hors pro/finance/université)
    ├── famille/
    ├── voyages/
    └── divers/
```

**Règles de classement** :
- **Facture SELARL** → `finance/selarl/2026/02-Fevrier/2026-02-08_Facture_Labo-Cerba_145EUR.pdf`
- **Courrier ARS (pro)** → `pro/administratif/2026-01-15_Courrier_ARS_0EUR.pdf`
- **Thèse Julie v3** → `universite/theses/Julie_Dupont/2026-02-01_These_Julie-Dupont_v3.pdf`
- **Article recherche** → `recherche/publications/2025-12-20_Article_SGLT2-inhibitors_Nature.pdf`
- **Facture perso** → `perso/divers/2026-02-10_Facture_Plombier_350EUR.pdf`

**Zone de transit** (éphémère, <24h) :
- VPS : `/var/friday/transit/attachments/` (5-15 min après traitement OCR)
- PC : `C:\Users\lopez\BeeStation\Friday\Transit\` (cleanup cron 03:05 quotidien)

### Nomenclature Finance (D24) — RÈGLE ABSOLUE

**5 périmètres financiers** (migration 010 + 031) :
1. `selarl` : Cabinet médical SELARL
2. `scm` : SCM (Société Civile de Moyens)
3. `sci_ravas` : SCI Ravas (anciennement sci_1)
4. `sci_malbosc` : SCI Malbosc (anciennement sci_2)
5. `personal` : Personnel

**CRITIQUE** : Ces labels sont OFFICIELS donnés par Antonio. **JAMAIS inventer, renommer ou supposer** d'autres noms de périmètres financiers.

**Anti-contamination (AC6 / FR37)** :
- Document `selarl` JAMAIS classé dans `scm`, `sci_ravas`, `sci_malbosc`, `personal`
- Validation stricte : `if category=finance AND subcategory NOT IN {selarl, scm, sci_ravas, sci_malbosc, personal} → raise ValueError("Invalid financial perimeter")`
- Test E2E obligatoire : vérifier qu'un document SELARL ne peut PAS être approuvé pour SCM

### Dépendances Story

**Epic 1 (Socle)** :
- ✅ Story 1.1 : Docker Compose (PostgreSQL, Redis)
- ✅ Story 1.6 : Trust Layer `@friday_action`
- ✅ Story 1.9 : Bot Telegram 5 topics
- ✅ Story 1.10 : Inline buttons validation

**Epic 3 (Archiviste)** :
- ✅ Story 3.1 : OCR & Renommage → Event Redis `document.processed`

**Workflow complet Epic 3 (Stories 3.1 + 3.2)** :
1. **Story 3.1** : OCR → Extract metadata → Rename → Store PG → Event `document.processed`
2. **Story 3.2** : Event `document.processed` → Classify → Validate → Move → Update PG → Event `document.classified`
3. **Story 3.3** (future) : Event `document.classified` → Generate embeddings → Index pgvector

### Performance & Sécurité

**Latence cible < 10s** (AC rapide) :
- Classification Claude : ~2-3s (temperature 0.3, response court)
- Validation périmètre : ~0.1s
- Déplacement fichier : ~1-3s (copy atomique + sync Syncthing)
- Update PostgreSQL : ~0.5s
- **Total moyen** : ~5-8s (bien sous seuil 10s)

**RGPD strict (NFR6)** :
- ✅ Metadata OCR déjà anonymisée (Story 3.1)
- ✅ Presidio AVANT appel Claude pour classification
- ✅ Mapping éphémère Redis (TTL 15 min)
- ✅ PII jamais stockée en clair

**Fail-explicit (NFR7)** :
- Si confidence <0.7 → status=pending, notification Telegram, JAMAIS classement auto
- Si périmètre finance invalide → raise ValueError, alerte System
- Si déplacement échoue → retry 3x, puis notification System

### Learnings de Story 3.1 (OCR & Renommage)

**Patterns validés à réutiliser** :
- ✅ **Pipeline orchestration** : Consumer Redis Streams → Séquence étapes → Publish event final
- ✅ **@friday_action** : Decorator systématique avec `trust_default="propose"`
- ✅ **ActionResult** : Retour structuré avec `confidence`, `reasoning`, `payload`
- ✅ **Presidio anonymisation** : AVANT tout appel Claude
- ✅ **Retry automatique** : Backoff exponentiel (1s, 2s, 4s max 3 tentatives)
- ✅ **Fail-explicit** : NotImplementedError si crash critique
- ✅ **Logs structurés** : JSON avec timings par étape
- ✅ **Tests pyramide** : 55 tests (9+9+11+6+11+7+2) = 80% unit, 15% integration, 5% E2E
- ✅ **Migration SQL** : Numérotée séquentielle (030 → 032)
- ✅ **Flat structure** : agents/src/agents/archiviste/ sans sous-dossiers

**Bugs évités grâce à Story 3.1** :
- ❌ Double sanitization (modèle + renamer) → Sanitize uniquement dans renamer
- ❌ Redis colon notation → Utiliser dot notation (`document.classified`)
- ❌ `os.environ` set dans constructeur → Set dans lazy loading
- ❌ `json.dumps` crash sur datetime → `model_dump(mode="json")`
- ❌ Rename failure silencieux → Raise NotImplementedError explicite

**Tests obligatoires** :
- Unit : Mock Claude, vérifier validation périmètres finance
- Integration : Redis Streams réel, filesystem réel, PostgreSQL réel
- E2E : Pipeline complet document.processed → document.classified, vérifier anti-contamination

### Estimations Ressources

**RAM additionnelle Story 3.2** :
- Classification Claude : API cloud (0 Mo RAM local)
- Redis consumer : ~50 Mo
- Syncthing : ~100 Mo (déjà actif depuis Story 3.1)
- **Total Story 3.2** : ~150 Mo additionnels (négligeable)

**Coût API Claude Sonnet 4.5** :
- Classification : ~200 tokens input/output par document
- Estimation : ~20 documents/jour = ~4k tokens/jour = ~120k tokens/mois
- Coût : ~$0.36 input + ~$1.80 output = **~$2.16/mois** (dans budget total $73/mois)

**Espace disque PC** :
- Arborescence finale : croissance ~2-5 Go/an (documents scannés)
- BeeStation capacité : ~500 Go disponibles

### Tests Stratégie

**Unitaires (80%)** :
- `test_classifier.py` : Mock Claude, 15+ cas (5 catégories + 5 périmètres finance)
- `test_file_mover.py` : 12+ tests (création dossiers, conflits, atomicité)
- `test_arborescence_config.py` : Validation YAML schema

**Intégration (15%)** :
- `test_classification_pipeline_integration.py` : Claude mock + Redis Streams réel + filesystem réel
- `test_classification_callbacks.py` : Vérifier inline buttons Telegram

**E2E (5%)** :
- `test_classification_end_to_end.py` : Pipeline complet avec 20 documents variés
- Dataset : 5 catégories × 4 documents (factures, courriers, thèses, articles, perso)
- Vérifier : latence <10s, anti-contamination finance, conflicts nommage

### Anti-Patterns à Éviter

❌ **NE PAS** inventer de nouveaux périmètres financiers → Utiliser uniquement `{selarl, scm, sci_ravas, sci_malbosc, personal}`
❌ **NE PAS** classifier avec confidence <0.7 → Status pending, validation Mainteneur
❌ **NE PAS** move direct (risque corruption) → Copy + verify + delete source
❌ **NE PAS** appeler Claude AVANT anonymisation Presidio → RGPD violation critique
❌ **NE PAS** hardcoder chemins arborescence → Charger depuis `config/arborescence.yaml`
❌ **NE PAS** utiliser `print()` → `structlog` JSON obligatoire

### Références

**Sources Techniques** :
- [Anthropic Claude API](https://docs.anthropic.com) — Classification structured output
- [Syncthing Docs](https://docs.syncthing.net) — Sync VPS → PC

**Documents Projet** :
- [Source: _docs/architecture-friday-2.0.md#Decision-D24] — Nomenclature finance 5 périmètres
- [Source: _bmad-output/planning-artifacts/epics-mvp.md#Story-3.2] — Acceptance Criteria originaux
- [Source: _bmad-output/planning-artifacts/prd.md#FR10] — Classement arborescence configurable
- [Source: _bmad-output/planning-artifacts/prd.md#FR37] — Pas de contamination inter-périmètres finance
- [Source: _bmad-output/planning-artifacts/prd.md#FR108] — Modification arborescence via Telegram
- [Source: _docs/analyse-fonctionnelle-complete.md] — Workflows utilisateur complets
- [Source: MEMORY.md#Nomenclature-Finance-D24] — Labels officiels périmètres (JAMAIS inventer)
- [Source: _bmad-output/implementation-artifacts/3-1-ocr-renommage-intelligent.md] — Learnings Story 3.1

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)

### Debug Log References

N/A

### Completion Notes List

**Story 3.2 : Classement Arborescence - Implementation**

**Implémentation :** 2026-02-16

**Tasks Complétées :**
- ✅ Task 1 : Module Classification Document (20/20 tests PASS — JSON parsing, correction_rules ajoutés review)
- ✅ Task 2 : Arborescence Configuration (19/19 tests PASS + validation rules enforced review)
- ✅ Task 3 : Gestionnaire Déplacement Fichiers (7/7 tests PASS — atomic move via tmp + checksum SHA256 review)
- ✅ Task 4 : Pipeline Orchestration (retry exponentiel 3x + timeout 10s + notifications Redis review)
- ✅ Task 5.1 : Config trust_levels.yaml (archiviste.classify = propose — déjà présent avant story)
- ✅ Task 7 : Migration SQL 037 (colonnes classification + CHECK constraints)
- ✅ Task 8.3-8.4 : Tests anti-contamination Pydantic (8 tests) + conflit nommage

**Acceptance Criteria :**
- ✅ **AC1** : Arborescence 5 catégories (pro, finance, universite, recherche, perso)
- ✅ **AC2** : Finance subdivisée en 5 périmètres (selarl, scm, sci_ravas, sci_malbosc, personal)
- ✅ **AC3** : Classification Claude Sonnet 4.5 avec JSON parsing robuste + correction_rules feedback loop
- ⚠️ **AC4** : Trust Layer propose (@friday_action OK) — inline buttons Telegram NON implémentés (Tasks 5.2-5.6)
- ✅ **AC5** : Déplacement fichier atomique via tmp + SHA256 checksum
- ✅ **AC6** : Anti-contamination stricte (validation Pydantic + Python + SQL CHECK)
- ❌ **AC7** : Commande /arbo non implémentée (Tasks 6.1-6.7)

**Review Adversariale (2026-02-16) — 16 issues corrigées :**
- [C1] Retry exponentiel implémenté (3 tentatives, backoff 1s→2s→4s)
- [C2] Timeout 10s via asyncio.wait_for
- [C3] Docstring classifier corrigé (seuil vérifié dans pipeline, pas classifier)
- [C4] Commentaire Python retiré du f-string prompt LLM
- [H1] JSON parsing ajouté pour réponses LLM string/dict/markdown
- [H2] Validation max_depth, forbidden_names, forbidden_chars enforcée
- [H3] Tests intégration reclassés (étaient des tests Pydantic, pas d'intégration)
- [H4] Correction_rules injectées dans le prompt (feedback loop fonctionnel)
- [H5] _compute_relative_path utilise ArborescenceConfig au lieu de hardcoder
- [M1] File List corrigée (trust_levels.yaml non modifié)
- [M2] AC4 corrigé de ✅ à ⚠️ (inline buttons manquants)
- [M3] Atomic move via fichier .tmp + rename (atomique sur même FS)
- [M4] Notifications Redis pour low confidence et erreurs processing
- [L1] Commentaire backoff corrigé
- [L2] Checksum SHA256 ajouté pour vérification copie
- [L3] Default REDIS_URL supprimé, validation env vars obligatoire

### File List

**Fichiers Créés (11) :**
- agents/src/agents/archiviste/classifier.py
- agents/src/agents/archiviste/file_mover.py
- agents/src/agents/archiviste/classification_pipeline.py
- agents/src/config/arborescence_config.py
- config/arborescence.yaml
- database/migrations/037_classification_metadata.sql
- tests/unit/agents/archiviste/test_classifier.py
- tests/unit/agents/archiviste/test_file_mover.py
- tests/unit/agents/archiviste/conftest.py
- tests/unit/config/test_arborescence_config.py
- tests/integration/archiviste/test_classification_anti_contamination.py

**Fichiers Modifiés (1) :**
- agents/src/agents/archiviste/models.py (ajout ClassificationResult, MovedFile)
