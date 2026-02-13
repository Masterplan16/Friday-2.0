# Extraction Pièces Jointes - Story 2.4

**Version** : 1.0.0
**Date** : 2026-02-11
**Auteur** : Claude Sonnet 4.5
**Status** : ✅ Implémenté (MVP)

---

## Vue d'ensemble

L'extraction automatique de pièces jointes permet à Friday de :
- **Extraire** automatiquement les fichiers joints aux emails reçus
- **Valider** MIME types et tailles (sécurité)
- **Sanitizer** noms de fichiers (protection path traversal)
- **Stocker** en zone transit temporaire (24h rétention)
- **Publier** événements pour traitement ultérieur (Epic 3 - Archiviste)
- **Notifier** via Telegram (topic Email)

---

## Architecture

### Pipeline complet

```
┌──────────────────────┐
│ imap-fetcher (IDLE)  │──▶ Redis Streams email.received [D25]
└──────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────┐
│ Consumer Email (services/email_processor/consumer.py)      │
│                                                              │
│ Phase 1: Fetch email complet                                │
│ Phase 2: Anonymisation Presidio                             │
│ Phase 3: Détection VIP + Urgence                            │
│ Phase 4: Classification LLM                                 │
│ Phase 5: Stockage DB ingestion.emails                       │
│ Phase 6: EXTRACTION PIECES JOINTES (Story 2.4)              │
│   ├─ IMAP FETCH BODYSTRUCTURE (liste attachments) [D25]    │
│   ├─ Pour chaque attachment :                               │
│   │   ├─ Validation MIME type (whitelist/blacklist)        │
│   │   ├─ Validation taille (<= 25 Mo)                       │
│   │   ├─ Download via IMAP FETCH BODY[part] [D25]          │
│   │   ├─ Sanitization nom fichier (sécurité)               │
│   │   ├─ Stockage zone transit VPS                          │
│   │   ├─ INSERT métadonnées DB                              │
│   │   └─ Publish Redis Streams documents:received          │
│   └─ UPDATE ingestion.emails SET has_attachments=TRUE       │
│ Phase 7: Stats VIP                                          │
│ Phase 8: Notifications Telegram                             │
│          ├─ Email reçu (topic Email/Actions)                │
│          └─ 🆕 PJ extraites (topic Email)                    │
└────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────┐
│ Redis Streams: documents:received                          │
│ Maxlen: 10000 events (rétention ~7 jours)                  │
└────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────┐
│ Consumer Archiviste (services/document_processor/consumer_stub.py) │
│                                                              │
│ Phase 1: Consume event documents:received                  │
│ Phase 2: UPDATE status='processed' (MVP stub)              │
│ Phase 3: XACK event                                         │
│                                                              │
│ 📝 NOTE : Pipeline complet (OCR, renommage, classement,     │
│           copie vers localisation finale) dans Epic 3       │
└────────────────────────────────────────────────────────────┘
        │
        ▼ (après traitement Epic 3)
┌────────────────────────────────────────────────────────────┐
│ Localisation finale (BeeStation/NAS)                        │
│ Status: 'archived'                                          │
└────────────────────────────────────────────────────────────┘
        │
        ▼ (après 24h)
┌────────────────────────────────────────────────────────────┐
│ Cleanup zone transit (scripts/cleanup-attachments-transit.sh) │
│ Cron: 03:05 quotidien                                       │
│ Supprime fichiers status='archived' AND processed_at > 24h │
└────────────────────────────────────────────────────────────┘
```

---

## Composants

### 1. Extraction Module (`agents/src/agents/email/attachment_extractor.py`)

**Fonction principale** : `extract_attachments()`

```python
@friday_action(module="email", action="extract_attachments", trust_default="auto")
async def extract_attachments(
    email_id: str,  # UUID email (depuis ingestion.emails)
    db_pool: asyncpg.Pool,
    emailengine_client: EmailEngineClient,
    redis_client: Any,
    **kwargs
) -> AttachmentExtractResult
```

**Workflow** [D25 : IMAP FETCH remplace EmailEngine API] :
1. IMAP FETCH BODYSTRUCTURE pour liste attachments
2. Pour chaque attachment :
   - Validation MIME type (cf. section Securite)
   - Validation taille <= 25 Mo (`MAX_ATTACHMENT_SIZE_BYTES`)
   - Download via IMAP FETCH BODY[part_number]
   - Sanitization nom fichier (cf. `sanitize_filename()`)
   - Stockage zone transit `/var/friday/transit/attachments/YYYY-MM-DD/`
   - INSERT métadonnées `ingestion.attachments`
   - Publish Redis Streams `documents:received`
3. UPDATE `ingestion.emails` SET `has_attachments=TRUE`
4. Retourne `AttachmentExtractResult` (ActionResult-compatible)

**Helper** : `sanitize_filename(filename: str) -> str`

Sécurisation nom fichier en 8 étapes :
1. Normalisation Unicode NFD (supprime accents : é → e)
2. Suppression caractères dangereux (garde alphanum + _ - . espaces)
3. Normalisation espaces multiples → underscore unique
4. Suppression underscores multiples consécutifs
5. Extensions lowercase (`.PDF` → `.pdf`)
6. Limite longueur max 200 chars (conserve extension)
7. Suppression . _ - en début/fin
8. Fallback `unnamed_file` si vide après sanitization

**Exemples** :
- `../../etc/passwd` → `etc_passwd`
- `Mon Document   Final.PDF` → `Mon_Document_Final.pdf`
- `Résumé été 2025.pdf` → `Resume_ete_2025.pdf`
- `file; rm -rf /` → `file_rm_-rf`

### 2. Validation MIME Types (`agents/src/config/mime_types.py`)

**Whitelist** (18 types autorisés) :
- Documents : `application/pdf`, `application/vnd.openxmlformats-officedocument.*` (Office 2007+)
- Images : `image/jpeg`, `image/png`, `image/gif`, `image/webp`
- Texte : `text/plain`, `text/csv`
- OpenDocument : `application/vnd.oasis.opendocument.*`

**Blacklist** (25+ types bloqués) :
- Exécutables : `application/x-msdownload` (.exe), `application/x-sh` (.sh)
- Archives : `application/zip`, `application/x-7z-compressed`, `application/x-rar-compressed`
- Scripts : `application/javascript`, `text/x-python`
- Vidéos : `video/*` (taille excessive)

**Fonction** : `validate_mime_type(mime_type: str) -> tuple[bool, str]`

```python
is_valid, reason = validate_mime_type("application/pdf")
# (True, "Allowed")

is_valid, reason = validate_mime_type("application/x-msdownload")
# (False, "Blocked (executable)")
```

### 3. Pydantic Models (`agents/src/models/attachment.py`)

**`Attachment`** : Métadonnées PJ en DB

```python
class Attachment(BaseModel):
    id: UUID
    email_id: UUID
    filename: str  # Nom original (traçabilité)
    filepath: str  # Chemin Unix zone transit
    size_bytes: int  # <= 26214400 (25 Mo)
    mime_type: str
    status: Literal['pending', 'processed', 'archived', 'error']
    extracted_at: datetime
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

**`AttachmentExtractResult`** : Résultat extraction (ActionResult-compatible)

```python
class AttachmentExtractResult(BaseModel):
    extracted_count: int
    failed_count: int
    total_size_mb: float
    filepaths: list[str]

    # Trust Layer fields
    input_summary: str
    output_summary: str
    confidence: float  # 1.0 (extraction = déterministe)
    reasoning: str
    payload: dict
```

### 4. Consumer Stub Archiviste (`services/document_processor/consumer_stub.py`)

**Workflow MVP** :
1. XREADGROUP sur stream `documents:received` (group `document-processor-group`)
2. Pour chaque event :
   - Log événement reçu
   - UPDATE `ingestion.attachments` SET `status='processed'`, `processed_at=NOW()`
   - Log `document_processed_stub`
   - XACK event
3. Error handling : log + continue (pas de crash)
4. Graceful shutdown : SIGINT/SIGTERM

**Docker Compose** :
```yaml
document-processor-stub:
  build: ./services/document_processor
  depends_on:
    - postgres
    - redis
  restart: unless-stopped
  environment:
    - DATABASE_URL=postgresql://...
    - REDIS_URL=redis://...
```

### 5. Cleanup Zone Transit (`scripts/cleanup-attachments-transit.sh`)

**Workflow** :
1. Query PostgreSQL :
   ```sql
   SELECT filepath FROM ingestion.attachments
   WHERE status='archived'
     AND processed_at < NOW() - INTERVAL '24 hours';
   ```
2. Pour chaque filepath : `rm -f $filepath`
3. Calcul espace libéré (du -sb avant/après)
4. Notification Telegram System si freed >= 100 Mo
5. Cleanup répertoires vides

**Cron** : 03:05 quotidien (via `scripts/cleanup-disk.sh`)

---

## Sécurité

### 1. Validation MIME Types

❌ **Bloqués** (sécurité) :
- Exécutables (`.exe`, `.sh`, `.bat`, `.com`)
- Archives (`.zip`, `.rar`, `.7z`, `.tar.gz`) - peuvent contenir malware
- Scripts (`.js`, `.py`, `.rb`, `.pl`)
- Vidéos (taille excessive, pas d'utilité métier)

✅ **Autorisés** (whitelist uniquement) :
- Documents bureautique (PDF, Office, OpenDocument)
- Images (JPEG, PNG, GIF, WebP)
- Texte (TXT, CSV)

### 2. Sanitization Nom Fichier

**Protections** :
- ✅ Path traversal : `../../etc/passwd` → `etc_passwd`
- ✅ Command injection : `file; rm -rf /` → `file_rm_-rf`
- ✅ Unicode attacks : Normalisation NFD + ASCII only
- ✅ Overflow : Limite 200 chars
- ✅ Extensions malveillantes : lowercase forcé

**Tests** :
- 10 tests unitaires sanitization (`test_attachment_extractor.py`)
- Dataset 15 emails avec cas malveillants

### 3. Validation Taille

**Limite** : 25 Mo (`MAX_ATTACHMENT_SIZE_BYTES = 26214400`)

**Rationale** :
- Limite configurable : 25 Mo par attachment (defaut)
- RAM VPS-4 : 48 Go (limite buffer memory)
- Performance : download + sanitization < 5s par fichier

### 4. Zone Transit Temporaire

**Localisation** : `/var/friday/transit/attachments/YYYY-MM-DD/`

**Rétention** : 24h après `processed_at` (status='archived')

**Permissions** : `chown -R friday:friday /var/friday/transit/` (user non-root)

**Isolation** : Séparé de la localisation finale (BeeStation/NAS)

---

## Base de Données

### Table `ingestion.attachments`

```sql
CREATE TABLE ingestion.attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_id UUID NOT NULL REFERENCES ingestion.emails(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,  -- Nom original (traçabilité)
    filepath TEXT NOT NULL,  -- Chemin Unix zone transit
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 26214400),
    mime_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processed', 'archived', 'error')),
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_attachments_status ON ingestion.attachments(status);
CREATE INDEX idx_attachments_email_id ON ingestion.attachments(email_id);
CREATE INDEX idx_attachments_processed_at ON ingestion.attachments(processed_at) WHERE status='archived';
```

### Colonne `ingestion.emails.has_attachments`

```sql
ALTER TABLE ingestion.emails ADD COLUMN has_attachments BOOLEAN DEFAULT FALSE;
CREATE INDEX idx_emails_has_attachments ON ingestion.emails(has_attachments) WHERE has_attachments=TRUE;
```

---

## Redis Streams

### Event `documents:received`

**Stream** : `documents:received`
**Consumer Group** : `document-processor-group`
**Maxlen** : 10000 (rétention ~7 jours)

**Payload** :
```python
{
    'attachment_id': '123e4567-e89b-12d3-a456-426614174000',  # UUID
    'email_id': '123e4567-e89b-12d3-a456-426614174001',
    'filename': 'facture_2026.pdf',  # Nom sanitisé
    'filepath': '/var/friday/transit/attachments/2026-02-11/123_0_facture_2026.pdf',
    'mime_type': 'application/pdf',
    'size_bytes': '150000',  # String (Redis Streams)
    'source': 'email'
}
```

**Retry Policy** (tenacity) :
- 3 tentatives max (1 original + 2 retries)
- Backoff exponentiel : 1s, 2s
- Reraise après 3 échecs

---

## Notifications Telegram

### Topic : Email & Communications (`TOPIC_EMAIL_ID`)

**Format** :
```
Pieces jointes extraites : 3

Email : Facture Orange janvier 2026
De : comptabilite@orange.fr
Taille totale : 1.42 Mo

Fichiers :
- Facture.pdf
- Justificatif.jpg
- Releve.xlsx

[View Email] (inline button)
```

**Inline Button** : `[View Email]` → URL Gmail email original

**Conditions envoi** :
- ✅ Si `extracted_count > 0`
- ❌ Si `extracted_count = 0` (skip)

**Limite fichiers listés** : Max 5 fichiers + `"... et X autre(s)"`

---

## Monitoring & Trust Layer

### ActionResult

Chaque extraction crée un `ActionResult` avec :
- `input_summary` : "Email abc123 avec 3 pièce(s) jointe(s)"
- `output_summary` : "→ 2 extraite(s), 1 ignorée(s)"
- `confidence` : 1.0 (extraction = déterministe)
- `reasoning` : "Extraction PJ : 2 PJ extraites (0.38 Mo), 1 PJ ignorées (MIME bloqué ou taille)"

### Trust Level

**Default** : `auto` (exécution automatique + notification après coup)

**Rationale** : Extraction = opération déterministe, pas d'ambiguïté

### Métriques

Logs structlog :
- `attachment_extraction_started`
- `attachments_found` (count)
- `attachment_mime_rejected` (reason)
- `attachment_too_large` (size_mb)
- `attachment_saved_transit` (filepath, size_bytes)
- `attachment_metadata_inserted` (attachment_uuid)
- `document_received_event_published`
- `attachment_extraction_complete` (extracted, failed, total_size_mb)

---

## Tests

### Pyramide de tests (105 tests total)

```
E2E (18 tests, 17%)
├─ 10 tests pipeline complet (test_attachment_extraction_pipeline_e2e.py)
└─ 8 tests acceptance AC1-AC6 (test_acceptance_criteria_validation.py)

Integration (6 tests, 6%)
└─ 6 tests consumer stub (test_document_processor_stub.py)

Unit (81 tests, 77%)
├─ 17 tests migration SQL (test_migration_030.py)
├─ 54 tests Pydantic models (test_attachment.py + test_mime_types.py)
├─ 20 tests extraction module (test_attachment_extractor.py)
├─ 8 tests publication Redis (test_publish_document_received.py)
├─ 10 tests consumer email (test_consumer_attachments.py)
└─ 5 tests cleanup script (test_cleanup_attachments_transit.sh)
```

### Dataset

**`tests/fixtures/email_attachments_dataset.json`** : 15 emails réalistes

Catégories :
- Nominal (5) : PDF simple, multi-PJ, Word, Excel, image
- Sécurité (3) : path traversal, Unicode, nom long
- Validation (4) : .exe bloqué, >25Mo, .zip bloqué, limite 25Mo
- Edge cases (3) : sans PJ, mix valide/bloqué, nom tronqué

---

## Troubleshooting

### Erreur : "MIME type blocked"

**Cause** : Type MIME dans blacklist (ex: `.exe`, `.zip`)

**Solution** : Valider que le fichier est légitime. Si oui, ajouter exception whitelist dans `mime_types.py`

### Erreur : "Size exceeds 25 Mo limit"

**Cause** : Fichier > 25 Mo (limite EmailEngine API)

**Solution** : Demander à l'expéditeur de compresser ou utiliser cloud storage (Google Drive, Dropbox)

### Fichier non extrait (pas d'erreur visible)

**Cause** : Validation silencieuse (MIME type ou taille)

**Debug** :
1. Vérifier logs structlog : `grep attachment_mime_rejected`
2. Vérifier `failed_count` dans `AttachmentExtractResult`
3. Vérifier notification Telegram (liste failed)

### Zone transit pleine

**Cause** : Cleanup pas exécuté ou fichiers status != 'archived'

**Debug** :
1. Vérifier cron cleanup : `systemctl status cron`
2. Vérifier logs cleanup : `/var/log/friday/cleanup-disk.log`
3. Vérifier status fichiers : `SELECT status, COUNT(*) FROM ingestion.attachments GROUP BY status`

**Solution** :
- Forcer cleanup manuel : `./scripts/cleanup-attachments-transit.sh`
- Vérifier consumer Archiviste fonctionne (UPDATE status='archived')

---

## Limitations Connues (MVP)

1. **Localisation finale** : Epic 3 (Archiviste)
   - Zone transit = temporaire uniquement
   - Pas de copie automatique vers BeeStation/NAS
   - Cleanup après 24h si status='archived'

2. **OCR & Renommage intelligent** : Epic 3
   - Pas d'extraction texte PDF/images
   - Pas de renommage sémantique
   - Nom original conservé

3. **Classement automatique** : Epic 3
   - Pas d'arborescence intelligente
   - Stockage flat en zone transit

4. **Recherche documentaire** : Epic 3
   - Pas d'indexation fulltext
   - Pas de recherche sémantique
   - Métadonnées DB uniquement

---

## Roadmap

### Epic 3 : Archiviste & Recherche Documentaire

**Story 3.1** : OCR + Renommage intelligent
- Surya OCR pour extraction texte PDF/images
- Renommage sémantique basé contenu
- Détection type document (facture, contrat, etc.)

**Story 3.2** : Classement arborescence
- Arborescence intelligente (date/catégorie/entité)
- Copie vers localisation finale (BeeStation/NAS)
- Gestion versions + déduplication

**Story 3.3** : Recherche sémantique
- Embeddings pgvector
- Recherche fulltext + sémantique
- Interface Telegram `/search` + `/doc`

**Story 3.4** : Suivi garanties
- Détection dates garanties
- Alertes expiration
- Classement garanties actives

---

## Références

- **Story File** : `_bmad-output/implementation-artifacts/2-4-extraction-pieces-jointes.md`
- **Architecture** : `_docs/architecture-friday-2.0.md`
- **MIME Types** : https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types
- **aioimaplib** : https://github.com/bamthomas/aioimaplib [D25 : remplace EmailEngine API]
- **Redis Streams** : https://redis.io/docs/manual/data-types/streams/
- **Tenacity** : https://tenacity.readthedocs.io/

---

**Dernière mise à jour** : 2026-02-11
**Version** : 1.0.0
**Auteur** : Claude Sonnet 4.5
