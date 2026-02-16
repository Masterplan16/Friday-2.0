# Telegram File Handling - Spécification Technique

**Story 3.6** : Fichiers via Telegram (envoi/réception)
**Date** : 2026-02-16
**Version** : 1.0.0
**Status** : ✅ Implémenté

---

## Vue d'ensemble

Friday 2.0 permet l'envoi et la réception de fichiers directement via Telegram, avec traitement automatique par le pipeline Archiviste et recherche sémantique pour récupération ultérieure.

### Fonctionnalités

1. **Upload automatique** : Document/Photo → Zone transit → Pipeline OCR → PostgreSQL
2. **Recherche sémantique** : Requête texte → Embeddings pgvector → Fichier trouvé
3. **Envoi intelligent** : Fichier <20 Mo → Telegram avec metadata caption

---

## Architecture

### Workflow Upload

```
Telegram Bot
    ↓ (MessageHandler filters.Document.ALL / filters.PHOTO)
bot/handlers/file_handlers.py
    ↓ handle_document() / handle_photo()
    1. Validation MIME type + extension
    2. Rate limiting (20 fichiers/minute)
    3. Download → /var/friday/transit/telegram_uploads/
    4. Publish Redis Streams `document.received`
    ↓
services/archiviste_consumer/consumer.py
    ↓ XREADGROUP (Consumer Group: archiviste-processor)
    1. Read event `document.received`
    2. Call OCRPipeline.process_document()
        - OCR via Surya (Story 3.1)
        - Extract metadata Claude (anonymisé Presidio)
        - Rename intelligent
        - Store PostgreSQL ingestion.document_metadata
        - Classification arborescence (Story 3.2)
        - Embeddings pgvector (Story 6.2)
    3. Cleanup zone transit (15 min)
    4. XACK message
```

### Workflow Recherche & Envoi

```
Telegram Bot
    ↓ MessageHandler filters.TEXT (block=False)
bot/handlers/file_send_commands.py
    ↓ handle_file_send_request()
    1. Intent detection via Claude Sonnet 4.5
        - Few-shot examples
        - Confidence >80%
    2. Semantic search pgvector
        - Query embedding (Voyage AI)
        - Search knowledge.embeddings
        - JOIN ingestion.document_metadata
    3. File retrieval
        - resolve_file_path_vps() : PC path → VPS mirror
        - Check file exists
        - Verify size <20 Mo
    4. Send via Telegram
        - reply_document() avec caption metadata
        - Notification confirmation
```

---

## Composants

### 1. File Handlers (`bot/handlers/file_handlers.py`)

**Responsabilités** :
- Recevoir fichiers Telegram (Document/Photo)
- Valider type et taille
- Télécharger dans zone transit
- Publier event Redis Streams

**Endpoints** :
- `handle_document(update, context)` : Documents (.pdf, .docx, .xlsx, .csv)
- `handle_photo(update, context)` : Photos (.png, .jpg, .jpeg)

**Validation** :
```python
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".csv", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB (limite Telegram Bot API)

# Whitelist MIME types
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "image/png",
    "image/jpeg",
}
```

**Rate Limiting** :
- Limite : 20 fichiers/minute par utilisateur
- Pattern : `SimpleRateLimiter` (reuse Story 2.3)
- Comportement : Si dépassé, message "Limite atteinte, retry dans X secondes"

**Retry Pattern** :
```python
MAX_RETRIES = 3
BACKOFF_BASE = 1  # secondes

# Tentatives : 0s → échec → wait 1s → retry
#              1s → échec → wait 2s → retry
#              2s → échec → wait 4s → retry
#              4s → échec → alerte System + stop
```

**Event Redis Streams** :
```python
stream_name = "document.received"
event_data = {
    "filename": str,              # "facture.pdf"
    "file_path": str,             # "/var/friday/transit/telegram_uploads/facture.pdf"
    "source": "telegram",         # Constant
    "telegram_user_id": str,      # "123456"
    "telegram_message_id": str,   # "789"
    "mime_type": str,             # "application/pdf"
    "file_size_bytes": str,       # "524288" (512 KB)
    "detected_at": str,           # ISO 8601 UTC
}
```

---

### 2. Archiviste Consumer (`services/archiviste_consumer/consumer.py`)

**Responsabilités** :
- Consommer events `document.received` (Redis Streams)
- Appeler pipeline OCR complet
- Cleanup zone transit après traitement

**Consumer Group** :
```python
STREAM_NAME = "document.received"
CONSUMER_GROUP = "archiviste-processor"
CONSUMER_NAME = "archiviste-processor-1"
BLOCK_MS = 5000  # Block 5s en attente nouveaux messages
BATCH_SIZE = 10  # Max messages lus par batch
```

**Workflow** :
1. `XREADGROUP` pour lire messages non-ack
2. Pour chaque message : `process_document_event()`
3. Appeler `OCRPipeline.process_document()`
4. `XACK` message après succès
5. Schedule `cleanup_transit_file()` (15 min delay)

**Fail-Explicit Pattern** :
```python
try:
    result = await pipeline.process_document(filename, file_path)
except NotImplementedError as e:
    # Composant indisponible (Presidio, Surya, Claude)
    # NE PAS ACK → permet retry manuel après restauration service
    logger.error("event_processing_failed_explicit", error=str(e))
    continue  # Pas de crash, message reste en pending
except Exception as e:
    # Erreur autre → log + ACK pour éviter boucle infinie
    logger.error("event_processing_failed", error=str(e))
    await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, event_id)
```

**Cleanup Zone Transit** :
```python
TRANSIT_CLEANUP_DELAY_SECONDS = 900  # 15 minutes

async def cleanup_transit_file(file_path: str, delay_seconds: int = 900):
    await asyncio.sleep(delay_seconds)
    if Path(file_path).exists():
        Path(file_path).unlink()
        logger.info("transit_file_cleaned", file_path=file_path)
```

---

### 3. File Send Commands (`bot/handlers/file_send_commands.py`)

**Responsabilités** :
- Détecter intention "envoyer fichier"
- Recherche sémantique pgvector
- Récupérer fichier depuis PC/VPS
- Envoyer via Telegram

**Intent Detection** :
```python
async def detect_file_request_intent(text: str) -> Optional[FileRequest]:
    """
    Claude Sonnet 4.5 avec few-shot examples.

    Exemples positifs :
    - "Envoie-moi la facture du plombier" → FileRequest(query="facture plombier")
    - "Je veux le contrat SELARL" → FileRequest(query="contrat SELARL")
    - "Donne-moi le dernier relevé bancaire" → FileRequest(query="relevé bancaire")

    Exemples négatifs :
    - "Bonjour" → None
    - "Comment vas-tu ?" → None
    - "Combien j'ai payé le plombier ?" → None (question info, pas demande fichier)

    Returns:
        FileRequest si confidence >80%, None sinon
    """
```

**Semantic Search** :
```python
async def search_documents_semantic(
    query: str,
    top_k: int = 3,
    doc_type: Optional[str] = None,
) -> list[DocumentSearchResult]:
    """
    Workflow :
    1. Generate query embedding (Voyage AI)
    2. Search knowledge.embeddings (pgvector HNSW)
    3. JOIN ingestion.document_metadata
    4. Filter by similarity threshold (>70%)
    5. Return top-k results sorted by similarity DESC
    """
```

**File Retrieval** :
```python
def resolve_file_path_vps(pc_path: str) -> Optional[Path]:
    """
    Convertit chemin PC → chemin VPS via miroir Syncthing.

    Exemple :
    C:\\Users\\lopez\\BeeStation\\Friday\\Archives\\finance\\facture.pdf
    → /var/friday/archives/finance/facture.pdf

    Returns:
        Path VPS si fichier existe, None sinon

    Note Day 1 :
        Si fichier pas sur VPS (pas synchronisé), retourne None.
        Handler notifie utilisateur : "Fichier trouvé sur PC : {path}"
    """
```

**Envoi Telegram** :
```python
# Fichier <20 Mo
with open(vps_file_path, "rb") as f:
    caption = f"📄 {filename}\n"
    if doc_type:
        caption += f"Type : {doc_type}\n"
    if emitter:
        caption += f"Émetteur : {emitter}\n"
    if amount > 0:
        caption += f"Montant : {amount:.2f} EUR\n"

    await update.message.reply_document(
        document=f,
        filename=filename,
        caption=caption,
        message_thread_id=TOPIC_EMAIL_ID,
    )

# Fichier >20 Mo
await update.message.reply_text(
    f"✅ Fichier trouvé : {filename}\n"
    f"❌ Fichier trop volumineux : {size_mb:.1f} Mo\n"
    f"Limite Telegram : 20 Mo\n"
    f"Accédez-y sur votre PC : {pc_path}"
)
```

---

## Configuration

### Variables d'environnement

```bash
# Telegram
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_SUPERGROUP_ID=<chat_id>
TOPIC_EMAIL_ID=<thread_id>  # Email & Communications topic
TOPIC_SYSTEM_ID=<thread_id>  # System & Alerts topic

# Redis
REDIS_URL=redis://USER:PASSWORD@HOST:6379/0

# PostgreSQL
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DB

# LLM (Intent Detection)
ANTHROPIC_API_KEY=YOUR_KEY_HERE  # Claude Sonnet 4.5

# Embeddings (Semantic Search)
VOYAGE_API_KEY=YOUR_KEY_HERE  # Voyage AI voyage-4-large (1024 dims)
```

### Paths

```python
# Zone transit VPS (éphémère 15 min max)
TRANSIT_DIR = Path("/var/friday/transit/telegram_uploads")

# Stockage final PC (permanent)
PC_ARCHIVES_ROOT = r"C:\Users\lopez\BeeStation\Friday\Archives"

# Mirror Syncthing VPS (Day 1 simplifié)
VPS_ARCHIVES_MIRROR = "/var/friday/archives"
```

---

## Sécurité

### Validation Fichiers

**Whitelist extensions** :
- Documents : `.pdf`, `.docx`, `.xlsx`, `.csv`
- Images : `.png`, `.jpg`, `.jpeg`

**Blacklist extensions** (explicitement rejetés) :
- Exécutables : `.exe`, `.bat`, `.sh`, `.py`, `.js`, `.vbs`
- Archives : `.zip`, `.rar`, `.7z` (potentiel malware)
- Scripts : `.ps1`, `.cmd`, `.com`

**Validation MIME type** :
- Extension ET MIME type doivent être cohérents
- Exemple : `document.pdf` avec `text/plain` → REJETÉ (suspicious)

**Magic number validation** (optionnel Phase 2) :
- Vérifier les premiers bytes du fichier correspondent au type déclaré
- Exemple : PDF doit commencer par `%PDF-`

### Rate Limiting

- **Upload** : 20 fichiers/minute par utilisateur
- **Recherche** : Pas de limite (requêtes texte légères)

### RGPD

- **Anonymisation Presidio** : Obligatoire avant appel LLM cloud
- **Stockage temporaire** : Zone transit nettoyée après 15 min
- **Logs** : Structlog JSON, PAS de print() avec PII

---

## Performance

### Latences cibles (AC#7)

| Opération | Cible | Mesure |
|-----------|-------|--------|
| Upload → Zone transit | <5s | Fichier 5 Mo |
| Recherche + Envoi | <10s | Fichier trouvé sur PC |
| OCR Pipeline complet | <30s | PDF 10 pages |

### Optimisations

**Upload** :
- Download asynchrone (AsyncIO)
- Batch processing (10 messages/batch)
- Rate limiting pour éviter saturation

**Recherche** :
- Index HNSW pgvector (m=16, ef_construction=64)
- Query optimization (LIMIT 3 top results)
- Cache embeddings (éviter régénération)

**Stockage** :
- Cleanup automatique zone transit (15 min)
- Compression images avant sync (Phase 2)

---

## Monitoring

### Métriques

```python
# Logs structlog (JSON)
logger.info("file_uploaded", filename=str, size_bytes=int, mime_type=str)
logger.info("file_processed", document_id=str, duration_sec=float)
logger.info("file_sent", filename=str, similarity=float, user_id=int)

# Erreurs
logger.error("file_download_failed", error=str, retry_attempt=int)
logger.error("pipeline_failed", document_id=str, error=str)
```

### Alertes Telegram

**Topic "System & Alerts"** :
- Upload échec après 3 retry
- Redis Streams down
- PostgreSQL connection failed
- Rate limit dépassé (abus potentiel)

---

## Tests

### Pyramide Tests (80/15/5)

**Unit Tests (80%)** : 18 tests
- `tests/unit/bot/test_file_handlers.py` : 10 tests
- `tests/unit/bot/test_file_send_commands.py` : 8 tests

**Integration Tests (15%)** : 8 tests
- `tests/integration/test_telegram_file_upload.py` : 5 tests
- `tests/integration/test_telegram_file_send.py` : 3 tests

**E2E Tests (5%)** : 3 tests
- `tests/e2e/test_telegram_file_pipeline_e2e.py` : 3 tests

### Coverage Critique

✅ Validation MIME type + extension
✅ Rate limiting 20 fichiers/minute
✅ Retry 3× backoff exponentiel
✅ Redis Streams publish/consume
✅ Intent detection (positifs + négatifs)
✅ Semantic search (trouvé/non trouvé)
✅ File size >20 Mo rejection
✅ Fail-explicit pattern (NotImplementedError)

---

## Limitations Day 1

### File Retrieval

❌ **Pas de récupération directe depuis PC**
- Day 1 : Vérifier miroir Syncthing VPS uniquement
- Si fichier pas sur VPS : notifier utilisateur avec chemin PC
- Phase 2 : Implémenter retrieve via Tailscale/rsync

### Types Fichiers

❌ **Pas de support archives** (`.zip`, `.rar`)
❌ **Pas de support vidéos** (`.mp4`, `.avi`)
❌ **Pas de support audio** (`.mp3`, `.wav`)

### Recherche

❌ **Pas de filtres avancés** (date range, montant, émetteur)
❌ **Pas de recherche multi-documents** (trouve 1 seul fichier)

---

## Roadmap Phase 2

### Q2 2026

🔄 **File retrieval direct depuis PC** via Tailscale/rsync
🔄 **Support archives** : décompression automatique `.zip`
🔄 **Filtres recherche avancés** : date, montant, catégorie
🔄 **Multi-file download** : envoyer plusieurs fichiers d'un coup
🔄 **Preview images** : thumbnails dans Telegram
🔄 **OCR preview** : extrait texte avant classement complet

---

## Références

### Stories Liées

- [Story 1.9: Bot Telegram Core](_bmad-output/implementation-artifacts/1-9-bot-telegram-core-topics.md)
- [Story 3.1: OCR Pipeline](_bmad-output/implementation-artifacts/3-1-ocr-renommage-intelligent.md)
- [Story 3.2: Classification](_bmad-output/implementation-artifacts/3-2-classement-arborescence.md)
- [Story 6.2: Embeddings pgvector](_bmad-output/implementation-artifacts/6-2-embeddings-pgvector.md)

### Documentation Projet

- [Architecture Friday 2.0](_docs/architecture-friday-2.0.md)
- [CLAUDE.md](CLAUDE.md)
- [Telegram User Guide](telegram-user-guide.md)

---

**Auteur** : Claude Sonnet 4.5
**Dernière mise à jour** : 2026-02-16
