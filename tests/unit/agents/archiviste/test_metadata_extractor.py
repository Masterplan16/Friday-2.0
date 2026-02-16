"""
Tests unitaires pour MetadataExtractor (Story 3.1 - Task 2).

Tests avec mocks de Claude et Presidio pour vérifier :
- Anonymisation RGPD avant appel Claude (AC6)
- Extraction correcte des métadonnées
- Gestion des erreurs fail-explicit
- Trust Layer intégré (@friday_action)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.archiviste.metadata_extractor import MetadataExtractor
from agents.src.agents.archiviste.models import MetadataExtraction, OCRResult
from agents.src.middleware.models import ActionResult


@pytest.fixture
def metadata_extractor():
    """Fixture pour créer une instance de MetadataExtractor."""
    return MetadataExtractor()


@pytest.fixture
def sample_ocr_result():
    """Fixture OCR result avec PII pour tester anonymisation."""
    return OCRResult(
        text="""
        FACTURE
        Date: 08/02/2026
        Laboratoire Cerba
        Adresse: 123 rue des Tests, 75001 Paris
        Patient: Jean Dupont (né le 15/03/1985)
        Montant total: 145.00 EUR
        """,
        confidence=0.92,
        page_count=1,
        language="fr",
    )


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.deanonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.get_llm_adapter")
async def test_extract_metadata_with_presidio_anonymization(
    mock_get_llm, mock_deanonymize, mock_anonymize, metadata_extractor, sample_ocr_result
):
    """
    Test AC6 : Texte OCR anonymisé via Presidio AVANT appel Claude.

    Vérifie que :
    1. anonymize_text() est appelé AVANT get_llm_adapter()
    2. Claude reçoit texte anonymisé (sans PII)
    3. Métadonnées extraites correctement
    """
    # Arrange - Mock Presidio
    anonymized_text = """
    FACTURE
    Date: 08/02/2026
    Laboratoire Cerba
    Adresse: [ADDRESS_1], [LOCATION_1]
    Patient: [PERSON_1] (né le [DATE_1])
    Montant total: 145.00 EUR
    """
    mock_anonymize.return_value = (anonymized_text, {"PERSON_1": "Jean Dupont"})
    mock_deanonymize.return_value = "Laboratoire Cerba"  # Émetteur déanonymisé

    # Mock Claude response
    mock_llm = AsyncMock()
    mock_get_llm.return_value = mock_llm

    mock_llm.complete.return_value = MagicMock(
        content="""
        {
            "date": "2026-02-08",
            "doc_type": "Facture",
            "emitter": "[LOCATION_1]",
            "amount": 145.0,
            "confidence": 0.88,
            "reasoning": "Facture médicale du Laboratoire Cerba avec montant clair"
        }
        """,
        usage=MagicMock(input_tokens=150, output_tokens=50),
    )

    # Act
    result = await metadata_extractor.extract_metadata(sample_ocr_result, "test_doc.pdf")

    # Assert - Presidio appelé AVANT Claude
    mock_anonymize.assert_called_once()
    assert mock_anonymize.call_args[0][0] == sample_ocr_result.text

    # Claude reçoit texte anonymisé
    mock_llm.complete.assert_called_once()
    call_args = mock_llm.complete.call_args[1]
    assert anonymized_text in call_args["prompt"]
    assert "Jean Dupont" not in call_args["prompt"]  # PII absent du prompt

    # ActionResult retourné correctement
    assert isinstance(result, ActionResult)
    assert isinstance(result.payload["metadata"], dict)
    assert result.payload["metadata"]["doc_type"] == "Facture"
    assert result.payload["metadata"]["amount"] == 145.0


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.deanonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.get_llm_adapter")
async def test_extract_metadata_facture_success(
    mock_get_llm, mock_deanonymize, mock_anonymize, metadata_extractor
):
    """
    Test AC3 : Extraction métadonnées facture avec Claude Sonnet 4.5.
    """
    # Arrange
    ocr_result = OCRResult(
        text="FACTURE\nDate: 2026-02-08\nFournisseur: Boulanger\nMontant TTC: 599.00 EUR",
        confidence=0.95,
        page_count=1,
        language="fr",
    )

    mock_anonymize.return_value = (ocr_result.text, {})
    mock_deanonymize.return_value = "Boulanger"

    mock_llm = AsyncMock()
    mock_get_llm.return_value = mock_llm
    mock_llm.complete.return_value = MagicMock(
        content='{"date": "2026-02-08", "doc_type": "Facture", "emitter": "Boulanger", "amount": 599.0, "confidence": 0.92, "reasoning": "Facture Boulanger avec montant TTC clair"}',
        usage=MagicMock(input_tokens=100, output_tokens=40),
    )

    # Act
    result = await metadata_extractor.extract_metadata(ocr_result, "facture_boulanger.pdf")

    # Assert
    assert isinstance(result, ActionResult)
    metadata = result.payload["metadata"]
    assert metadata["doc_type"] == "Facture"
    assert metadata["emitter"] == "Boulanger"
    assert metadata["amount"] == 599.0
    assert datetime.fromisoformat(metadata["date"]) == datetime(2026, 2, 8)
    assert result.confidence >= 0.85  # Minimum de OCR + Claude


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.deanonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.get_llm_adapter")
async def test_extract_metadata_courrier_no_amount(
    mock_get_llm, mock_deanonymize, mock_anonymize, metadata_extractor
):
    """
    Test AC2 : Courrier sans montant → amount=0.0 EUR.
    """
    # Arrange
    ocr_result = OCRResult(
        text="Courrier\nDate: 15/01/2026\nAgence Régionale de Santé\nObjet: Demande de renseignements",
        confidence=0.88,
        page_count=1,
        language="fr",
    )

    mock_anonymize.return_value = (ocr_result.text, {})
    mock_deanonymize.return_value = "ARS"

    mock_llm = AsyncMock()
    mock_get_llm.return_value = mock_llm
    mock_llm.complete.return_value = MagicMock(
        content='{"date": "2026-01-15", "doc_type": "Courrier", "emitter": "ARS", "amount": 0.0, "confidence": 0.85, "reasoning": "Courrier administratif ARS sans montant"}',
        usage=MagicMock(input_tokens=80, output_tokens=35),
    )

    # Act
    result = await metadata_extractor.extract_metadata(ocr_result, "courrier_ars.pdf")

    # Assert
    metadata = result.payload["metadata"]
    assert metadata["doc_type"] == "Courrier"
    assert metadata["emitter"] == "ARS"
    assert metadata["amount"] == 0.0  # Pas de montant


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.deanonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.get_llm_adapter")
async def test_extract_metadata_fallback_date_today(
    mock_get_llm, mock_deanonymize, mock_anonymize, metadata_extractor
):
    """
    Test : Si date absente/invalide → fallback date du jour.
    """
    # Arrange
    ocr_result = OCRResult(
        text="Document sans date claire\nContenu illisible",
        confidence=0.65,
        page_count=1,
        language="fr",
    )

    mock_anonymize.return_value = (ocr_result.text, {})
    mock_deanonymize.return_value = "Inconnu"

    mock_llm = AsyncMock()
    mock_get_llm.return_value = mock_llm

    # Claude retourne date invalide
    today = datetime.now().strftime("%Y-%m-%d")
    mock_llm.complete.return_value = MagicMock(
        content=f'{{"date": "{today}", "doc_type": "Inconnu", "emitter": "Inconnu", "amount": 0.0, "confidence": 0.60, "reasoning": "Document illisible, métadonnées incertaines"}}',
        usage=MagicMock(input_tokens=50, output_tokens=30),
    )

    # Act
    result = await metadata_extractor.extract_metadata(ocr_result, "document_inconnu.jpg")

    # Assert
    metadata = result.payload["metadata"]
    assert (
        datetime.fromisoformat(metadata["date"]).date() == datetime.now().date()
    )  # Fallback aujourd'hui
    assert metadata["doc_type"] == "Inconnu"


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
async def test_extract_metadata_presidio_crash_fail_explicit(mock_anonymize, metadata_extractor):
    """
    Test AC7 : Si Presidio crash → NotImplementedError (fail-explicit).
    """
    # Arrange
    mock_anonymize.side_effect = RuntimeError("Presidio model unavailable")

    ocr_result = OCRResult(text="Test", confidence=0.9, page_count=1, language="fr")

    # Act & Assert
    with pytest.raises(NotImplementedError) as exc_info:
        await metadata_extractor.extract_metadata(ocr_result, "test.pdf")

    assert "Presidio anonymization unavailable" in str(exc_info.value)


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.get_llm_adapter")
async def test_extract_metadata_claude_crash_fail_explicit(
    mock_get_llm, mock_anonymize, metadata_extractor
):
    """
    Test AC7 : Si Claude API crash → NotImplementedError.
    """
    # Arrange
    mock_anonymize.return_value = ("anonymized text", {})

    mock_llm = AsyncMock()
    mock_get_llm.return_value = mock_llm
    mock_llm.complete.side_effect = Exception("Claude API timeout")

    ocr_result = OCRResult(text="Test", confidence=0.9, page_count=1, language="fr")

    # Act & Assert
    with pytest.raises(NotImplementedError) as exc_info:
        await metadata_extractor.extract_metadata(ocr_result, "test.pdf")

    assert "Claude API unavailable" in str(exc_info.value)


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.get_llm_adapter")
async def test_extract_metadata_confidence_calculation(
    mock_get_llm, mock_anonymize, metadata_extractor
):
    """
    Test AC5 : Confidence globale = min(confidence_ocr, confidence_claude).
    """
    # Arrange
    ocr_result = OCRResult(text="Facture test", confidence=0.85, page_count=1, language="fr")

    mock_anonymize.return_value = (ocr_result.text, {})

    mock_llm = AsyncMock()
    mock_get_llm.return_value = mock_llm
    mock_llm.complete.return_value = MagicMock(
        content='{"date": "2026-02-08", "doc_type": "Facture", "emitter": "Test", "amount": 100.0, "confidence": 0.92, "reasoning": "OK"}',
        usage=MagicMock(input_tokens=50, output_tokens=20),
    )

    # Act
    result = await metadata_extractor.extract_metadata(ocr_result, "test.pdf")

    # Assert - Confidence globale = min(0.85 OCR, 0.92 Claude) = 0.85
    assert result.confidence == 0.85


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.get_llm_adapter")
async def test_extract_metadata_low_confidence_warning(
    mock_get_llm, mock_anonymize, metadata_extractor
):
    """
    Test AC5 : Si confidence < 0.7 → warning dans reasoning.
    """
    # Arrange
    ocr_result = OCRResult(text="Texte peu lisible", confidence=0.55, page_count=1, language="fr")

    mock_anonymize.return_value = (ocr_result.text, {})

    mock_llm = AsyncMock()
    mock_get_llm.return_value = mock_llm
    mock_llm.complete.return_value = MagicMock(
        content='{"date": "2026-02-08", "doc_type": "Inconnu", "emitter": "Inconnu", "amount": 0.0, "confidence": 0.60, "reasoning": "OCR quality low, metadata uncertain"}',
        usage=MagicMock(input_tokens=40, output_tokens=25),
    )

    # Act
    result = await metadata_extractor.extract_metadata(ocr_result, "bad_quality.jpg")

    # Assert
    assert result.confidence < 0.7
    assert "uncertain" in result.reasoning.lower() or "low" in result.reasoning.lower()


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.metadata_extractor.anonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.deanonymize_text")
@patch("agents.src.agents.archiviste.metadata_extractor.get_llm_adapter")
async def test_extract_metadata_preserves_emitter_raw(
    mock_get_llm, mock_deanonymize, mock_anonymize, metadata_extractor
):
    """
    Test : MetadataExtraction preserves raw emitter value from Claude.

    Sanitization is DocumentRenamer's responsibility (H4 fix),
    NOT MetadataExtraction model's.
    """
    # Arrange
    ocr_result = OCRResult(
        text="FACTURE Labo / Tests*?", confidence=0.9, page_count=1, language="fr"
    )

    mock_anonymize.return_value = (ocr_result.text, {})
    mock_deanonymize.return_value = "Labo / Tests*?"  # Avec caractères interdits

    mock_llm = AsyncMock()
    mock_get_llm.return_value = mock_llm
    mock_llm.complete.return_value = MagicMock(
        content='{"date": "2026-02-08", "doc_type": "Facture", "emitter": "Labo / Tests*?", "amount": 50.0, "confidence": 0.88, "reasoning": "OK"}',
        usage=MagicMock(input_tokens=60, output_tokens=25),
    )

    # Act
    result = await metadata_extractor.extract_metadata(ocr_result, "test.pdf")

    # Assert - Emitter preserved as-is (sanitization in renamer, not model)
    metadata = result.payload["metadata"]
    assert metadata["emitter"] == "Labo / Tests*?"
