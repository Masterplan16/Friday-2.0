# Archiviste - Classification automatique de documents

**Story 3.2** — Classement arborescence archiviste

## Architecture

### Pipeline

```
document.processed (Redis Streams)
    → ClassificationPipeline._process_document()
        → Phase 1 : Presidio anonymisation
        → Phase 2 : Claude Sonnet 4.5 classification (temperature=0.3)
        → Phase 3 : Validation anti-contamination (AC6)
        → Phase 4 : FileMover (atomic copy → verify SHA256 → rename → delete source)
        → Phase 5 : Update PostgreSQL (ingestion.document_metadata)
        → Phase 6 : Publish document.classified (Redis Streams)
        → Phase 7 : Notification Telegram (trust=propose)
```

### Catégories (5 racines)

| Catégorie | Description | Subcategory obligatoire |
|-----------|-------------|------------------------|
| `pro` | Cabinet médical | Non |
| `finance` | Documents financiers | **Oui** (5 périmètres) |
| `universite` | Enseignement | Non |
| `recherche` | Recherche scientifique | Non |
| `perso` | Personnel | Non |

### Périmètres finance (5 — OFFICIELS, IMMUABLES)

| Périmètre | Description |
|-----------|-------------|
| `selarl` | Cabinet médical SELARL |
| `scm` | SCM (Société Civile de Moyens) |
| `sci_ravas` | SCI Ravas |
| `sci_malbosc` | SCI Malbosc |
| `personal` | Finances personnelles |

## Fichiers

| Fichier | Rôle |
|---------|------|
| `agents/src/agents/archiviste/classifier.py` | Classification LLM (Claude Sonnet 4.5) |
| `agents/src/agents/archiviste/file_mover.py` | Déplacement atomique fichiers |
| `agents/src/agents/archiviste/classification_pipeline.py` | Consumer Redis Streams |
| `agents/src/agents/archiviste/models.py` | Modèles Pydantic (ClassificationResult, MovedFile) |
| `agents/src/config/arborescence_config.py` | Config YAML loader + validation |
| `config/arborescence.yaml` | Configuration arborescence (catégories, paths, validation) |
| `database/migrations/037_classification_metadata.sql` | Migration PostgreSQL |
| `bot/handlers/classification_notifications.py` | Notifications Telegram |
| `bot/handlers/classification_callbacks.py` | Callbacks inline buttons |
| `bot/handlers/arborescence_commands.py` | Commande /arbo |

## Seuils et limites

| Paramètre | Valeur | Description |
|-----------|--------|-------------|
| Confidence threshold | 0.7 | En dessous → status pending, pas de déplacement |
| Max retries | 3 | Avec backoff exponentiel (1s → 2s → 4s) |
| Process timeout | 10s | `asyncio.wait_for` par document |
| OCR text limit | 1000 chars | Tronqué dans le prompt LLM |
| LLM temperature | 0.3 | Classification déterministe |
| LLM max_tokens | 200 | Réponse JSON courte |
| Latence alerte | 8s médiane | Alerte si médiane > 8s |

## Anti-contamination AC6

- Finance **DOIT** avoir un subcategory (ValueError sinon)
- Subcategory **DOIT** être dans les 5 périmètres valides (ValueError sinon)
- Validation à 3 niveaux :
  1. Modèle Pydantic `ClassificationResult` (field_validator)
  2. Classifier `classify()` (vérification explicite)
  3. Pipeline `_process_document()` (double vérification)

## Commande Telegram /arbo

| Commande | Usage |
|----------|-------|
| `/arbo` | Affiche arborescence ASCII tree |
| `/arbo stats` | Statistiques documents par catégorie |
| `/arbo add <cat> <path>` | Ajouter dossier (protections finance) |
| `/arbo remove <path>` | Supprimer dossier (protections racine + finance) |

Restrictions :
- Owner-only (OWNER_USER_ID)
- Impossible de modifier/supprimer les périmètres finance racine
- Impossible de supprimer les catégories racine

## Inline buttons classification

Quand trust=propose (Day 1), notification dans Topic Actions :

```
📁 Document classifié (validation requise)

📄 Document : doc-123
🏷️ Catégorie : Finance > SELARL
📂 Destination : finance/selarl
📊 Confiance : 94%

[✅ Approuver] [📂 Corriger] [❌ Rejeter]
```

- **Approuver** : status → approved
- **Corriger** : affiche liste catégories → si finance, sous-menu périmètres
- **Rejeter** : status → rejected

## Monitoring latence

Logs structurés JSON avec timings :

```json
{
    "event": "document_processing_completed",
    "document_id": "doc-123",
    "category": "finance",
    "classify_duration_ms": 1200,
    "move_duration_ms": 45,
    "total_duration_ms": 1250,
    "status": "classified"
}
```

Alerte Telegram topic System si médiane latence > 8s sur les 10 derniers documents.
