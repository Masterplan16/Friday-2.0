"""
Tests integration pipeline OCR (Story 3.1 - Task 4.7).

Tests avec mocks Surya + Claude mais Redis Streams reel.
Verifie l'orchestration complete OCR -> Extract -> Rename -> Store -> Events.
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.archiviste.models import MetadataExtraction, OCRResult
from agents.src.agents.archiviste.pipeline import OCRPipeline
from agents.src.middleware.models import ActionResult


@pytest.fixture
def mock_ocr_result():
    """OCRResult simule pour tests integration."""
    return OCRResult(
        text="FACTURE\nDate: 2026-02-08\nLaboratoire Cerba\nMontant: 145.00 EUR",
        confidence=0.92,
        page_count=1,
        language="fr",
        processing_time=8.5,
    )


@pytest.fixture
def mock_metadata():
    """MetadataExtraction simulee pour tests integration."""
    return MetadataExtraction(
        date=datetime(2026, 2, 8),
        doc_type="Facture",
        emitter="Laboratoire Cerba",
        amount=145.0,
        confidence=0.88,
        reasoning="Facture medicale standard",
    )


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.pipeline.SuryaOCREngine")
@patch("agents.src.agents.archiviste.pipeline.MetadataExtractor")
@patch("agents.src.agents.archiviste.pipeline.DocumentRenamer")
async def test_pipeline_full_sequence(
    mock_renamer_cls, mock_extractor_cls, mock_ocr_cls, mock_ocr_result, mock_metadata
):
    """
    Test integration : pipeline execute OCR -> Extract -> Rename dans l'ordre.
    """
    # Arrange
    mock_ocr = mock_ocr_cls.return_value
    mock_ocr.ocr_document = AsyncMock(return_value=mock_ocr_result)

    mock_extractor = mock_extractor_cls.return_value
    mock_extractor.extract_metadata = AsyncMock(
        return_value=ActionResult(
            input_summary="OCR de test.pdf",
            output_summary="Facture Laboratoire Cerba",
            confidence=0.88,
            reasoning="Facture medicale standard document",
            payload={
                "metadata": mock_metadata,
                "ocr_result": mock_ocr_result,
                "filename": "test.pdf",
                "anonymized_text": "FACTURE anonymise",
            },
        )
    )

    from agents.src.agents.archiviste.models import RenameResult

    mock_rename_result = RenameResult(
        original_filename="test.pdf",
        new_filename="2026-02-08_Facture_Laboratoire-Cerba_145EUR.pdf",
        metadata=mock_metadata,
        confidence=0.88,
        reasoning="Renommage Facture effectue avec succes",
    )
    mock_ren = mock_renamer_cls.return_value
    mock_ren.rename_document = AsyncMock(
        return_value=ActionResult(
            input_summary="Fichier original: test.pdf",
            output_summary="Nouveau nom: 2026-02-08_Facture_Laboratoire-Cerba_145EUR.pdf",
            confidence=0.88,
            reasoning="Renommage Facture effectue avec succes",
            payload={
                "rename_result": mock_rename_result,
                "original_filename": "test.pdf",
                "new_filename": "2026-02-08_Facture_Laboratoire-Cerba_145EUR.pdf",
            },
        )
    )

    pipeline = OCRPipeline(redis_url="redis://localhost:6379/0", timeout_seconds=45)
    pipeline.redis = AsyncMock()
    pipeline.redis.xadd = AsyncMock()

    # Act
    result = await pipeline.process_document(file_path="/tmp/test.pdf", filename="test.pdf")

    # Assert - Sequence complete
    mock_ocr.ocr_document.assert_called_once_with("/tmp/test.pdf")
    mock_extractor.extract_metadata.assert_called_once()
    mock_ren.rename_document.assert_called_once()

    assert result["success"] is True
    assert result["metadata"]["doc_type"] == "Facture"
    assert "timings" in result


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.pipeline.SuryaOCREngine")
async def test_pipeline_surya_crash_publishes_error_event(mock_ocr_cls):
    """
    Test integration : Surya crash -> erreur publiee dans Redis + raise.
    """
    mock_ocr = mock_ocr_cls.return_value
    mock_ocr.ocr_document = AsyncMock(side_effect=NotImplementedError("Surya OCR unavailable"))

    pipeline = OCRPipeline(redis_url="redis://localhost:6379/0")
    pipeline.redis = AsyncMock()
    pipeline.redis.xadd = AsyncMock()

    with pytest.raises(NotImplementedError):
        await pipeline.process_document(file_path="/tmp/test.pdf", filename="test.pdf")

    # Verifier erreur publiee dans Redis
    pipeline.redis.xadd.assert_called_once()
    call_args = pipeline.redis.xadd.call_args
    assert call_args[0][0] == "pipeline.error"


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.pipeline.SuryaOCREngine")
@patch("agents.src.agents.archiviste.pipeline.MetadataExtractor")
@patch("agents.src.agents.archiviste.pipeline.DocumentRenamer")
async def test_pipeline_rename_crash_fail_explicit(
    mock_renamer_cls, mock_extractor_cls, mock_ocr_cls, mock_ocr_result, mock_metadata
):
    """
    Test H1 fix : Rename crash -> NotImplementedError (fail-explicit AC7).
    """
    mock_ocr = mock_ocr_cls.return_value
    mock_ocr.ocr_document = AsyncMock(return_value=mock_ocr_result)

    mock_extractor = mock_extractor_cls.return_value
    mock_extractor.extract_metadata = AsyncMock(
        return_value=ActionResult(
            input_summary="Test document for validation",
            output_summary="Test processing completed",
            confidence=0.88,
            reasoning="Test reasoning with sufficient length for validation",
            payload={
                "metadata": mock_metadata,
                "ocr_result": mock_ocr_result,
                "filename": "test.pdf",
                "anonymized_text": "anon",
            },
        )
    )

    mock_ren = mock_renamer_cls.return_value
    mock_ren.rename_document = AsyncMock(side_effect=RuntimeError("Rename crashed"))

    pipeline = OCRPipeline(redis_url="redis://localhost:6379/0")
    pipeline.redis = AsyncMock()
    pipeline.redis.xadd = AsyncMock()

    with pytest.raises(NotImplementedError, match="Document rename failed"):
        await pipeline.process_document(file_path="/tmp/test.pdf", filename="test.pdf")


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.pipeline.SuryaOCREngine")
@patch("agents.src.agents.archiviste.pipeline.MetadataExtractor")
@patch("agents.src.agents.archiviste.pipeline.DocumentRenamer")
async def test_pipeline_timeout_raises_timeout_error(
    mock_renamer_cls, mock_extractor_cls, mock_ocr_cls
):
    """
    Test AC4 : Timeout global declenche asyncio.TimeoutError.
    """

    async def slow_ocr(*args, **kwargs):
        await asyncio.sleep(5)  # Plus long que le timeout
        return MagicMock()

    mock_ocr = mock_ocr_cls.return_value
    mock_ocr.ocr_document = slow_ocr

    pipeline = OCRPipeline(redis_url="redis://localhost:6379/0", timeout_seconds=1)
    pipeline.redis = AsyncMock()
    pipeline.redis.xadd = AsyncMock()

    with pytest.raises(asyncio.TimeoutError):
        await pipeline.process_document(file_path="/tmp/test.pdf", filename="test.pdf")


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.pipeline.SuryaOCREngine")
@patch("agents.src.agents.archiviste.pipeline.MetadataExtractor")
@patch("agents.src.agents.archiviste.pipeline.DocumentRenamer")
async def test_pipeline_result_json_serializable(
    mock_renamer_cls, mock_extractor_cls, mock_ocr_cls, mock_ocr_result, mock_metadata
):
    """
    Test C4 fix : le resultat pipeline est JSON-serializable (pas de crash datetime).
    """
    mock_ocr = mock_ocr_cls.return_value
    mock_ocr.ocr_document = AsyncMock(return_value=mock_ocr_result)

    mock_extractor = mock_extractor_cls.return_value
    mock_extractor.extract_metadata = AsyncMock(
        return_value=ActionResult(
            input_summary="Test document for validation",
            output_summary="Test processing completed",
            confidence=0.88,
            reasoning="Test reasoning with sufficient length for validation",
            payload={
                "metadata": mock_metadata,
                "ocr_result": mock_ocr_result,
                "filename": "test.pdf",
                "anonymized_text": "anon",
            },
        )
    )

    from agents.src.agents.archiviste.models import RenameResult

    mock_ren = mock_renamer_cls.return_value
    mock_ren.rename_document = AsyncMock(
        return_value=ActionResult(
            input_summary="Test document for validation",
            output_summary="Test processing completed",
            confidence=0.88,
            reasoning="Test reasoning with sufficient length for validation",
            payload={
                "rename_result": RenameResult(
                    original_filename="test.pdf",
                    new_filename="2026-02-08_Facture_Test_145EUR.pdf",
                    metadata=mock_metadata,
                    confidence=0.88,
                    reasoning="Document renamed according to standard format with extracted metadata",
                ),
                "original_filename": "test.pdf",
                "new_filename": "2026-02-08_Facture_Test_145EUR.pdf",
            },
        )
    )

    pipeline = OCRPipeline(redis_url="redis://localhost:6379/0")
    pipeline.redis = AsyncMock()
    pipeline.redis.xadd = AsyncMock()

    result = await pipeline.process_document(file_path="/tmp/test.pdf", filename="test.pdf")

    # Fix C4 : json.dumps ne doit PAS crash
    serialized = json.dumps(result)
    assert "2026-02-08" in serialized
    assert "Facture" in serialized


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.pipeline.SuryaOCREngine")
@patch("agents.src.agents.archiviste.pipeline.MetadataExtractor")
@patch("agents.src.agents.archiviste.pipeline.DocumentRenamer")
async def test_pipeline_publishes_dot_notation_events(
    mock_renamer_cls, mock_extractor_cls, mock_ocr_cls, mock_ocr_result, mock_metadata
):
    """
    Test M1 fix : Redis Streams utilise dot notation (document.processed, pas document:processed).
    """
    mock_ocr = mock_ocr_cls.return_value
    mock_ocr.ocr_document = AsyncMock(return_value=mock_ocr_result)

    mock_extractor = mock_extractor_cls.return_value
    mock_extractor.extract_metadata = AsyncMock(
        return_value=ActionResult(
            input_summary="Test document for validation",
            output_summary="Test processing completed",
            confidence=0.88,
            reasoning="Test reasoning with sufficient length for validation",
            payload={
                "metadata": mock_metadata,
                "ocr_result": mock_ocr_result,
                "filename": "test.pdf",
                "anonymized_text": "anon",
            },
        )
    )

    from agents.src.agents.archiviste.models import RenameResult

    mock_ren = mock_renamer_cls.return_value
    mock_ren.rename_document = AsyncMock(
        return_value=ActionResult(
            input_summary="Test document for validation",
            output_summary="Test processing completed",
            confidence=0.88,
            reasoning="Test reasoning with sufficient length for validation",
            payload={
                "rename_result": RenameResult(
                    original_filename="test.pdf",
                    new_filename="2026-02-08_Facture_Test_145EUR.pdf",
                    metadata=mock_metadata,
                    confidence=0.88,
                    reasoning="Document renamed according to standard format with extracted metadata",
                ),
                "original_filename": "test.pdf",
                "new_filename": "2026-02-08_Facture_Test_145EUR.pdf",
            },
        )
    )

    pipeline = OCRPipeline(redis_url="redis://localhost:6379/0")
    pipeline.redis = AsyncMock()
    pipeline.redis.xadd = AsyncMock()

    await pipeline.process_document(file_path="/tmp/test.pdf", filename="test.pdf")

    # Verifier dot notation (pas colon)
    xadd_calls = pipeline.redis.xadd.call_args_list
    stream_names = [call[0][0] for call in xadd_calls]
    assert "document.processed" in stream_names
    assert "document:processed" not in stream_names
