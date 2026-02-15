"""
Tests unitaires pour SuryaOCREngine (Story 3.1 - Task 1)

Tests avec mocks de Surya pour vérifier les appels API et la gestion d'erreurs.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from pathlib import Path

from agents.src.agents.archiviste.ocr import SuryaOCREngine
from agents.src.agents.archiviste.models import OCRResult


@pytest.fixture
def ocr_engine():
    """Fixture pour créer une instance de SuryaOCREngine."""
    return SuryaOCREngine(device="cpu")


@pytest.fixture
def mock_surya_result():
    """Fixture pour simuler un résultat Surya OCR."""
    mock_result = MagicMock()
    mock_line1 = MagicMock()
    mock_line1.text = "FACTURE"
    mock_line1.confidence = 0.95

    mock_line2 = MagicMock()
    mock_line2.text = "Date: 2026-02-08"
    mock_line2.confidence = 0.92

    mock_line3 = MagicMock()
    mock_line3.text = "Laboratoire Cerba"
    mock_line3.confidence = 0.88

    mock_line4 = MagicMock()
    mock_line4.text = "Montant: 145.00 EUR"
    mock_line4.confidence = 0.90

    mock_result.text_lines = [mock_line1, mock_line2, mock_line3, mock_line4]
    return mock_result


@pytest.mark.asyncio
async def test_ocr_engine_initialization_cpu_mode(ocr_engine):
    """
    Test AC1 : Vérifier que le moteur OCR s'initialise correctement en mode CPU.
    """
    assert ocr_engine.device == "cpu"
    assert ocr_engine.model is None  # Modèle chargé à la demande


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.ocr.Image")
@patch("agents.src.agents.archiviste.ocr.asyncio.to_thread")
@patch("agents.src.agents.archiviste.ocr.Path")
async def test_ocr_document_image_success(mock_path_class, mock_to_thread, mock_image, ocr_engine, mock_surya_result):
    """
    Test AC1 : OCR sur image JPG réussit et retourne OCRResult avec texte extrait.

    GREEN phase : Ce test devrait passer maintenant avec l'implémentation.
    """
    # Arrange - Mock du fichier image
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.suffix = ".jpg"
    mock_path_class.return_value = mock_path

    # Mock Image.open
    mock_img = MagicMock()
    mock_image.open.return_value = mock_img

    # Mock asyncio.to_thread pour les appels de load_model et run_ocr
    async def mock_thread_exec(func, *args, **kwargs):
        if func.__name__ == "run_ocr":
            return [mock_surya_result]
        # Pour load_model/load_processor
        return MagicMock()

    mock_to_thread.side_effect = mock_thread_exec

    file_path = "test_facture.jpg"

    # Act
    result = await ocr_engine.ocr_document(file_path)

    # Assert
    assert isinstance(result, OCRResult)
    assert "FACTURE" in result.text
    assert "2026-02-08" in result.text
    assert "Laboratoire Cerba" in result.text
    assert "145.00 EUR" in result.text
    assert result.confidence > 0.0
    assert result.page_count == 1
    assert result.language == "fr"


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.ocr.fitz")
@patch("agents.src.agents.archiviste.ocr.Image")
@patch("agents.src.agents.archiviste.ocr.asyncio.to_thread")
@patch("agents.src.agents.archiviste.ocr.Path")
async def test_ocr_document_pdf_multipage(mock_path_class, mock_to_thread, mock_image, mock_fitz, ocr_engine):
    """
    Test AC1 : OCR sur PDF multi-pages extrait tout le texte.
    """
    # Arrange - Mock du fichier PDF
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.suffix = ".pdf"
    mock_path_class.return_value = mock_path

    # Mock PyMuPDF (fitz) pour 3 pages
    mock_pdf = MagicMock()
    mock_pdf.__len__.return_value = 3

    mock_pages = []
    for i in range(3):
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.width = 800
        mock_pix.height = 1000
        mock_pix.samples = b"fake_image_data"
        mock_page.get_pixmap.return_value = mock_pix
        mock_pages.append(mock_page)

    mock_pdf.__getitem__.side_effect = lambda i: mock_pages[i]
    mock_fitz.open.return_value = mock_pdf

    # Mock Image.frombytes
    mock_img = MagicMock()
    mock_image.frombytes.return_value = mock_img

    # Mock résultats OCR pour 3 pages
    page1_result = MagicMock()
    page1_line = MagicMock()
    page1_line.text = "Page 1 content"
    page1_line.confidence = 0.9
    page1_result.text_lines = [page1_line]

    page2_result = MagicMock()
    page2_line = MagicMock()
    page2_line.text = "Page 2 content"
    page2_line.confidence = 0.85
    page2_result.text_lines = [page2_line]

    page3_result = MagicMock()
    page3_line = MagicMock()
    page3_line.text = "Page 3 content"
    page3_line.confidence = 0.88
    page3_result.text_lines = [page3_line]

    async def mock_thread_exec(func, *args, **kwargs):
        if func.__name__ == "run_ocr":
            return [page1_result, page2_result, page3_result]
        return MagicMock()

    mock_to_thread.side_effect = mock_thread_exec

    file_path = "test_multipage.pdf"

    # Act
    result = await ocr_engine.ocr_document(file_path)

    # Assert
    assert isinstance(result, OCRResult)
    assert "Page 1 content" in result.text
    assert "Page 2 content" in result.text
    assert "Page 3 content" in result.text
    assert result.page_count == 3


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.ocr.Image")
@patch("agents.src.agents.archiviste.ocr.asyncio.to_thread")
@patch("agents.src.agents.archiviste.ocr.Path")
async def test_ocr_document_empty_result(mock_path_class, mock_to_thread, mock_image, ocr_engine):
    """
    Test AC7 : OCR sur document vide ou illisible retourne texte vide mais pas d'erreur.
    """
    # Arrange
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.suffix = ".jpg"
    mock_path_class.return_value = mock_path

    mock_img = MagicMock()
    mock_image.open.return_value = mock_img

    # Résultat OCR vide
    empty_result = MagicMock()
    empty_result.text_lines = []

    async def mock_thread_exec(func, *args, **kwargs):
        if func.__name__ == "run_ocr":
            return [empty_result]
        return MagicMock()

    mock_to_thread.side_effect = mock_thread_exec

    file_path = "empty_document.jpg"

    # Act
    result = await ocr_engine.ocr_document(file_path)

    # Assert
    assert isinstance(result, OCRResult)
    assert result.text == ""
    assert result.confidence == 0.0
    assert result.page_count == 1


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.ocr.Path")
async def test_ocr_document_file_not_found(mock_path_class, ocr_engine):
    """
    Test AC7 : Fichier inexistant lève FileNotFoundError.
    """
    # Arrange
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_path_class.return_value = mock_path

    file_path = "fichier_inexistant.jpg"

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        await ocr_engine.ocr_document(file_path)


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.ocr.asyncio.to_thread")
@patch("agents.src.agents.archiviste.ocr.Path")
async def test_ocr_document_surya_crash(mock_path_class, mock_to_thread, ocr_engine):
    """
    Test AC7 : Si Surya crash, lève NotImplementedError (fail-explicit).
    """
    # Arrange
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.suffix = ".jpg"
    mock_path_class.return_value = mock_path

    # Simuler crash lors du chargement du modèle
    async def mock_thread_crash(func, *args, **kwargs):
        raise RuntimeError("Surya model loading failed")

    mock_to_thread.side_effect = mock_thread_crash

    file_path = "test_document.jpg"

    # Act & Assert
    with pytest.raises(NotImplementedError) as exc_info:
        await ocr_engine.ocr_document(file_path)

    assert "Surya OCR unavailable" in str(exc_info.value)


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.ocr.Path")
async def test_ocr_document_unsupported_format(mock_path_class, ocr_engine):
    """
    Test : Format de fichier non supporté lève ValueError.
    """
    # Arrange
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.suffix = ".docx"
    mock_path_class.return_value = mock_path

    file_path = "document.docx"

    # Act & Assert
    with pytest.raises(ValueError) as exc_info:
        await ocr_engine.ocr_document(file_path)

    assert "Unsupported file format" in str(exc_info.value)


@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.ocr.Image")
@patch("agents.src.agents.archiviste.ocr.asyncio.to_thread")
@patch("agents.src.agents.archiviste.ocr.Path")
async def test_ocr_model_lazy_loading(mock_path_class, mock_to_thread, mock_image, ocr_engine):
    """
    Test AC1, Task 1.5 : Le modèle Surya est chargé à la demande (lazy loading).
    """
    # Arrange
    assert ocr_engine.model is None  # Pas chargé à l'initialisation

    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.suffix = ".jpg"
    mock_path_class.return_value = mock_path

    mock_img = MagicMock()
    mock_image.open.return_value = mock_img

    mock_result = MagicMock()
    mock_line = MagicMock()
    mock_line.text = "Test"
    mock_line.confidence = 0.9
    mock_result.text_lines = [mock_line]

    call_count = 0
    async def mock_thread_exec(func, *args, **kwargs):
        nonlocal call_count
        if "load_model" in func.__name__ or "load_processor" in func.__name__:
            call_count += 1
            return MagicMock()
        if func.__name__ == "run_ocr":
            return [mock_result]
        return MagicMock()

    mock_to_thread.side_effect = mock_thread_exec

    # Act - Premier appel
    await ocr_engine.ocr_document("test.jpg")

    # Assert - Modèle chargé
    assert ocr_engine.model is not None
    first_call_count = call_count

    # Act - Deuxième appel
    await ocr_engine.ocr_document("test2.jpg")

    # Assert - Modèle PAS rechargé (lazy loading)
    assert call_count == first_call_count  # Pas d'appels supplémentaires aux load_model


@pytest.mark.asyncio
async def test_torch_device_configuration(ocr_engine):
    """
    Test Task 1.3 : Configuration TORCH_DEVICE=cpu est respectée.

    Note (M2 fix): os.environ["TORCH_DEVICE"] is set in _load_model_if_needed(),
    NOT in __init__(), to avoid side effects at import time.
    """
    import os
    assert ocr_engine.device == "cpu"
    # TORCH_DEVICE not set at init time (M2 fix: moved to _load_model_if_needed)
    # It will be set when model is loaded for the first time
