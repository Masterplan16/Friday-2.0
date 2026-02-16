"""
Archiviste Agent (Epic 3).

Modules:
- ocr: Surya OCR Engine (Story 3.1)
- metadata_extractor: Extraction metadonnees via Claude (Story 3.1)
- renamer: Renommage intelligent documents (Story 3.1)
- pipeline: Orchestrateur OCR -> Extract -> Rename -> Store (Story 3.1)

Note (M3 fix): Les imports requierent redis, structlog, et les adapters
Friday (llm, anonymize). En cas de dependance manquante, le module
leve ImportError avec un message explicite.
"""

from agents.src.agents.archiviste.models import OCRResult, MetadataExtraction, RenameResult
from agents.src.agents.archiviste.ocr import SuryaOCREngine
from agents.src.agents.archiviste.metadata_extractor import MetadataExtractor
from agents.src.agents.archiviste.renamer import DocumentRenamer
from agents.src.agents.archiviste.pipeline import OCRPipeline

__all__ = [
    "OCRResult",
    "MetadataExtraction",
    "RenameResult",
    "SuryaOCREngine",
    "MetadataExtractor",
    "DocumentRenamer",
    "OCRPipeline",
]
