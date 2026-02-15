# Archiviste OCR & Renommage Intelligent - Spécification Technique

**Story 3.1** | **Date**: 2026-02-15 | **Status**: Implémenté

## Vue d'ensemble

Pipeline OCR automatique pour documents (images JPG/PNG/TIFF, PDF) avec renommage intelligent standardisé.

**Flux** : Document → OCR Surya → Extract metadata Claude → Rename → PostgreSQL → Redis Streams

## Architecture

### Composants

| Composant | Fichier | Responsabilité |
|-----------|---------|----------------|
| **SuryaOCREngine** | `agents/src/agents/archiviste/ocr.py` | OCR CPU-only, lazy loading modèle |
| **MetadataExtractor** | `agents/src/agents/archiviste/metadata_extractor.py` | Extraction via Claude + Presidio |
| **DocumentRenamer** | `agents/src/agents/archiviste/renamer.py` | Renommage convention standardisée |
| **OCRPipeline** | `agents/src/agents/archiviste/pipeline.py` | Orchestrateur complet |

### Dépendances

```
surya-ocr>=0.17.0       # OCR multilingue CPU
PyMuPDF>=1.23.0         # PDF→Image
Pillow>=10.0.0          # Traitement images
```

## Convention Nommage (AC2)

**Format** : `YYYY-MM-DD_Type_Emetteur_MontantEUR.ext`

**Exemples** :
- `2026-02-08_Facture_Laboratoire-Cerba_145EUR.pdf`
- `2026-01-15_Courrier_ARS_0EUR.pdf`
- `2025-12-20_Garantie_Boulanger_599EUR.pdf`
- `2026-02-15_Inconnu_0EUR.jpg` (fallback si metadata manquante)

**Règles sanitization** :
- Émetteur : espaces → tirets, caractères spéciaux supprimés
- Longueur max émetteur : 50 caractères
- Extension : préservée, normalisée minuscules

## Performance (AC4)

| Metric | Target | Moyen observé |
|--------|--------|---------------|
| **Latence totale** | <45s | ~15-25s (1-3 pages) |
| OCR Surya (1 page) | - | ~5-15s CPU |
| OCR Surya (3-5 pages) | - | ~20-30s CPU |
| Presidio anonymisation | - | ~0.5-1s |
| Claude extraction | - | ~2-5s |
| Renommage | - | ~0.5s |

**Alerte** : Si latence médiane >35s (seuil 45s avec marge)

## RGPD Strict (AC6)

**Pipeline Presidio obligatoire** :

```python
# ❌ INTERDIT
response = await claude_api(text_with_pii)

# ✅ CORRECT
anonymized_text = await anonymize_text(text_with_pii)
response = await claude_api(anonymized_text)
result = await deanonymize_text(response, mapping)
```

**Mapping éphémère** : Redis TTL 15 min, JAMAIS PostgreSQL

**PII stockée** : `ocr_text` = version anonymisée uniquement

## Fail-Explicit (AC7)

**Toutes erreurs lèvent NotImplementedError** :

| Composant crash | Comportement |
|-----------------|--------------|
| **Surya OCR** | `NotImplementedError("Surya OCR unavailable")` + alerte System topic |
| **Presidio** | `NotImplementedError("Presidio anonymization unavailable")` + alerte |
| **Claude API** | `NotImplementedError("Claude API unavailable")` + alerte |
| **Timeout 45s** | `asyncio.TimeoutError` + alerte System topic |

**JAMAIS de fallback silencieux**

## Trust Layer (AC5)

**Actions decorées @friday_action** :
- `extract_metadata` : trust=**propose** (Day 1, validation Telegram requise)
- `rename` : trust=**propose** (Day 1, validation Telegram requise)
- `ocr` : trust=**auto** (pas de décision, juste extraction)

**Confidence globale** : `min(confidence_ocr, confidence_claude)`

**ActionResult obligatoire** : input_summary, output_summary, confidence, reasoning

## Stockage PostgreSQL (AC3)

**Table** : `ingestion.document_metadata`

```sql
CREATE TABLE ingestion.document_metadata (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    ocr_text TEXT,  -- Anonymisé Presidio
    extracted_date TIMESTAMPTZ,
    doc_type TEXT,
    emitter TEXT,
    amount NUMERIC(10, 2),
    confidence FLOAT,
    page_count INTEGER,
    processing_duration FLOAT,
    created_at TIMESTAMPTZ
);
```

## Formats Supportés

| Format | Support | Notes |
|--------|---------|-------|
| **JPG, JPEG** | ✅ | Natif Surya |
| **PNG** | ✅ | Natif Surya |
| **TIFF** | ✅ | Natif Surya |
| **PDF** | ✅ | Via PyMuPDF conversion |
| **DOCX, XLSX** | ❌ | Hors scope Story 3.1 |

## Redis Streams Events

**Input** : `document:received` (depuis Epic 2 Story 2.4)
**Output** : `document:processed` (payload complet OCR+metadata+rename)
**Errors** : `pipeline:error` (Surya crash, timeout, etc.)

## Monitoring

**Logs structurés JSON** (structlog) :

```json
{
    "timestamp": "2026-02-15T14:30:00Z",
    "service": "ocr-pipeline",
    "level": "INFO",
    "event": "pipeline.process_complete",
    "filename": "facture.pdf",
    "total_duration": 18.5,
    "doc_type": "Facture",
    "confidence": 0.92
}
```

**Métriques clés** :
- `ocr_duration` (secondes)
- `extract_duration` (secondes)
- `rename_duration` (secondes)
- `total_duration` (secondes)
- `confidence` (0.0-1.0)
- `page_count`

## Tests

**Pyramide tests** :
- **80% unitaires** (mocks Surya + Claude + Presidio)
- **15% intégration** (Redis + PostgreSQL réels, mocks LLM)
- **5% E2E** (pipeline complet avec fichiers réels)

**Tests critiques** :
- Anonymisation Presidio AVANT Claude (AC6)
- Convention nommage respectée (AC2)
- Fail-explicit si Surya crash (AC7)
- Timeout 45s déclenché (AC4)
- Trust Layer appliqué (AC5)

## Coûts API Claude Sonnet 4.5

**Estimation** :
- ~500-1000 tokens input/output par document
- ~20 documents/jour = ~30k tokens/jour = ~900k tokens/mois
- **Coût** : ~$2.70 input + ~$13.50 output = **~$16.20/mois**

## Limites Connues

1. **CPU-only** : Surya ~3-5x plus lent que GPU (acceptable VPS)
2. **Manuscrits** : Surya meilleur que Tesseract mais pas parfait
3. **Multi-colonnes** : Layout complexe peut poser problème
4. **Formules mathématiques** : OCR standard, pas LaTeX

## Prochaines évolutions (Epic 3.2+)

- Classement arborescence automatique (Story 3.2)
- Recherche sémantique documents (Story 3.3)
- Suivi garanties (Story 3.4)
- Détection nouveaux fichiers (Story 3.5)
