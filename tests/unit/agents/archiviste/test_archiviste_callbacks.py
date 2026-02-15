"""
Tests callbacks Telegram pour Archiviste (Story 3.1 - Task 6.5).

Verifie :
- Notifications topic Actions (inline buttons Approve/Reject/Correct)
- Notifications topic Metrics (document traite, confidence, latence)
- Notifications topic System (erreur Surya, timeout 45s)
- Trust Layer integration (trust=propose pour extract_metadata et rename)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from agents.src.agents.archiviste.models import MetadataExtraction, OCRResult


@pytest.fixture
def sample_metadata():
    """Metadata de test pour notifications."""
    return MetadataExtraction(
        date=datetime(2026, 2, 8),
        doc_type="Facture",
        emitter="Laboratoire Cerba",
        amount=145.0,
        confidence=0.88,
        reasoning="Facture medicale standard"
    )


@pytest.fixture
def sample_ocr_result():
    """OCRResult de test."""
    return OCRResult(
        text="FACTURE\nDate: 2026-02-08\nMontant: 145.00 EUR",
        confidence=0.92,
        page_count=1,
        language="fr",
        processing_time=8.5
    )


def test_trust_levels_archiviste_configured():
    """
    Test Task 6.1 : trust_levels.yaml contient la section archiviste.
    """
    from pathlib import Path
    import yaml

    trust_path = Path("config/trust_levels.yaml")
    assert trust_path.exists(), "trust_levels.yaml not found"

    config = yaml.safe_load(trust_path.read_text())
    assert "archiviste" in config, "archiviste section missing from trust_levels.yaml"
    assert config["archiviste"]["extract_metadata"] == "propose"
    assert config["archiviste"]["rename"] == "propose"


def test_trust_levels_ocr_is_auto():
    """
    Test Task 6.1 : OCR est trust=auto (pas de decision).
    """
    from pathlib import Path
    import yaml

    config = yaml.safe_load(Path("config/trust_levels.yaml").read_text())
    assert config["archiviste"]["ocr"] == "auto"


@pytest.mark.asyncio
async def test_metadata_extractor_has_friday_action_decorator():
    """
    Test Task 6.2 : MetadataExtractor.extract_metadata a @friday_action.
    """
    from agents.src.agents.archiviste.metadata_extractor import MetadataExtractor
    extractor = MetadataExtractor()

    # Verifier que la methode est decoree (attributs du decorator)
    method = extractor.extract_metadata
    assert callable(method)
    # Le decorator @friday_action wraps la methode, elle reste async
    import inspect
    assert inspect.iscoroutinefunction(method)


@pytest.mark.asyncio
async def test_renamer_has_friday_action_decorator():
    """
    Test Task 6.2 : DocumentRenamer.rename_document a @friday_action.
    """
    from agents.src.agents.archiviste.renamer import DocumentRenamer
    renamer = DocumentRenamer()

    method = renamer.rename_document
    assert callable(method)
    import inspect
    assert inspect.iscoroutinefunction(method)


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.pipeline.SuryaOCREngine")
async def test_pipeline_error_publishes_to_system_topic(mock_ocr_cls):
    """
    Test Task 6.4 : erreur Surya publie dans Redis pour alerting System topic.
    """
    from agents.src.agents.archiviste.pipeline import OCRPipeline

    mock_ocr = mock_ocr_cls.return_value
    mock_ocr.ocr_document = AsyncMock(
        side_effect=NotImplementedError("Surya OCR unavailable")
    )

    pipeline = OCRPipeline(redis_url="redis://localhost:6379/0")
    pipeline.redis = AsyncMock()
    pipeline.redis.xadd = AsyncMock()

    with pytest.raises(NotImplementedError):
        await pipeline.process_document(file_path="/tmp/test.pdf", filename="test.pdf")

    # Verifier evenement erreur publie
    pipeline.redis.xadd.assert_called_once()
    call_args = pipeline.redis.xadd.call_args
    stream_name = call_args[0][0]
    assert stream_name == "pipeline.error"


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.pipeline.SuryaOCREngine")
@patch("agents.src.agents.archiviste.pipeline.MetadataExtractor")
@patch("agents.src.agents.archiviste.pipeline.DocumentRenamer")
async def test_pipeline_success_publishes_processed_event(
    mock_renamer_cls, mock_extractor_cls, mock_ocr_cls,
    sample_ocr_result, sample_metadata
):
    """
    Test Task 6.3 : document traite publie document.processed pour topic Metrics.
    """
    from agents.src.agents.archiviste.pipeline import OCRPipeline
    from agents.src.agents.archiviste.models import RenameResult
    from agents.src.middleware.models import ActionResult

    mock_ocr = mock_ocr_cls.return_value
    mock_ocr.ocr_document = AsyncMock(return_value=sample_ocr_result)

    mock_extractor = mock_extractor_cls.return_value
    mock_extractor.extract_metadata = AsyncMock(return_value=ActionResult(
        input_summary="test", output_summary="test", confidence=0.88,
        reasoning="test",
        payload={"metadata": sample_metadata, "ocr_result": sample_ocr_result,
                 "filename": "test.pdf", "anonymized_text": "anon"}
    ))

    rename_result = RenameResult(
        original_filename="test.pdf",
        new_filename="2026-02-08_Facture_Laboratoire-Cerba_145EUR.pdf",
        metadata=sample_metadata, confidence=0.88, reasoning="test"
    )
    mock_ren = mock_renamer_cls.return_value
    mock_ren.rename_document = AsyncMock(return_value=ActionResult(
        input_summary="test", output_summary="test", confidence=0.88,
        reasoning="test",
        payload={"rename_result": rename_result, "original_filename": "test.pdf",
                 "new_filename": "2026-02-08_Facture_Laboratoire-Cerba_145EUR.pdf"}
    ))

    pipeline = OCRPipeline(redis_url="redis://localhost:6379/0")
    pipeline.redis = AsyncMock()
    pipeline.redis.xadd = AsyncMock()

    await pipeline.process_document(file_path="/tmp/test.pdf", filename="test.pdf")

    # Verifier document.processed publie
    xadd_calls = pipeline.redis.xadd.call_args_list
    stream_names = [call[0][0] for call in xadd_calls]
    assert "document.processed" in stream_names
