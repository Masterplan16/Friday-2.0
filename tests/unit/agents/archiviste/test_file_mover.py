"""
Tests unitaires pour FileMover.

Story 3.2 - Task 3.8
Tests : création dossiers, conflits, atomicité
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from agents.src.agents.archiviste.file_mover import FileMover
from agents.src.agents.archiviste.models import ClassificationResult, MovedFile


@pytest.fixture
def file_mover():
    """Instance FileMover sans DB pool."""
    return FileMover(db_pool=None)


@pytest.fixture
def sample_classification():
    """Classification exemple pour tests."""
    return ClassificationResult(
        category="finance",
        subcategory="selarl",
        path="finance/selarl",
        confidence=0.92,
        reasoning="Facture SELARL cabinet medical",
    )


@pytest.fixture
def temp_source_file(tmp_path):
    """Crée un fichier source temporaire."""
    source = tmp_path / "transit" / "2026-02-15_Facture_Test_100EUR.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("test content")
    return source


@pytest.mark.asyncio
async def test_move_document_success(file_mover, temp_source_file, sample_classification, tmp_path):
    """Test déplacement réussi."""
    mock_config = MagicMock()
    mock_config.root_path = str(tmp_path / "archives")
    file_mover._config = mock_config

    result = await file_mover.move_document(
        source_path=str(temp_source_file), classification=sample_classification
    )

    assert isinstance(result, MovedFile)
    assert result.success is True
    assert result.error is None
    assert not temp_source_file.exists()  # Source supprimé


@pytest.mark.asyncio
async def test_move_document_source_not_found(file_mover, sample_classification):
    """Test fichier source introuvable."""
    result = await file_mover.move_document(
        source_path="/nonexistent/file.pdf", classification=sample_classification
    )

    assert result.success is False
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_handle_naming_conflict(
    file_mover, temp_source_file, sample_classification, tmp_path
):
    """Test gestion conflit nommage."""
    mock_config = MagicMock()
    mock_config.root_path = str(tmp_path / "archives")
    file_mover._config = mock_config

    # Premier déplacement
    result1 = await file_mover.move_document(str(temp_source_file), sample_classification)

    # Créer nouveau fichier source identique
    source2 = tmp_path / "transit" / "2026-02-15_Facture_Test_100EUR.pdf"
    source2.parent.mkdir(parents=True, exist_ok=True)
    source2.write_text("test content 2")

    # Deuxième déplacement (devrait ajouter _v2)
    result2 = await file_mover.move_document(str(source2), sample_classification)

    assert result1.success is True
    assert result2.success is True
    assert "_v2" in result2.destination_path


@pytest.mark.asyncio
async def test_resolve_destination_path(
    file_mover, temp_source_file, sample_classification, tmp_path
):
    """Test résolution chemin destination."""
    mock_config = MagicMock()
    mock_config.root_path = str(tmp_path / "archives")
    file_mover._config = mock_config

    dest = file_mover._resolve_destination_path(temp_source_file, sample_classification)

    assert "archives" in dest
    assert "finance" in dest.replace("\\", "/")  # Windows path fix
    assert temp_source_file.name in dest


@pytest.mark.asyncio
async def test_atomic_move_creates_parent_dirs(
    file_mover, temp_source_file, sample_classification, tmp_path
):
    """Test création dossiers parents."""
    mock_config = MagicMock()
    mock_config.root_path = str(tmp_path / "archives")
    file_mover._config = mock_config

    result = await file_mover.move_document(str(temp_source_file), sample_classification)

    dest = Path(result.destination_path)
    assert dest.parent.exists()  # Dossiers parents créés


@pytest.mark.asyncio
async def test_update_database_called_with_document_id(
    temp_source_file, sample_classification, tmp_path
):
    """Test update BDD appelé si document_id fourni."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    file_mover = FileMover(db_pool=mock_pool)
    mock_config = MagicMock()
    mock_config.root_path = str(tmp_path / "archives")
    file_mover._config = mock_config

    await file_mover.move_document(
        str(temp_source_file), sample_classification, document_id="doc-123"
    )

    # Vérifier que execute() a été appelé
    assert mock_conn.execute.called


@pytest.mark.asyncio
async def test_move_preserves_filename(
    file_mover, temp_source_file, sample_classification, tmp_path
):
    """Test que le nom de fichier est préservé."""
    mock_config = MagicMock()
    mock_config.root_path = str(tmp_path / "archives")
    file_mover._config = mock_config

    result = await file_mover.move_document(str(temp_source_file), sample_classification)

    dest = Path(result.destination_path)
    assert dest.name == temp_source_file.name
