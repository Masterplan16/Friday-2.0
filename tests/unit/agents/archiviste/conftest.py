"""
Configuration pytest pour tests agents/archiviste.

Initialise TrustManager pour tests unitaires nécessitant @friday_action.
Story 3.2 - Tests unitaires classifier.
"""

import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.middleware.trust import init_trust_manager


class MockAsyncPool:
    """Mock d'un pool asyncpg pour tests unitaires."""

    def __init__(self):
        self.mock_conn = AsyncMock()
        self.mock_conn.fetch.return_value = []  # Empty correction rules
        self.mock_conn.fetchval.return_value = None
        self.mock_conn.execute.return_value = None

    @asynccontextmanager
    async def acquire(self):
        """Context manager async pour acquire()."""
        yield self.mock_conn

    async def fetchval(self, query, *args):
        """Mock fetchval direct sur pool."""
        return "auto"


@pytest.fixture(scope="session", autouse=True)
def initialize_trust_manager():
    """
    Initialise TrustManager en mode mock pour tests unitaires.

    Nécessaire pour les fonctions utilisant @friday_action decorator.
    """
    # Créer mock pool avec vrai async context manager
    mock_pool = MockAsyncPool()

    # Initialiser TrustManager avec mock pool (synchrone)
    init_trust_manager(db_pool=mock_pool)

    yield

    # Cleanup si nécessaire
    # (TrustManager n'a pas de méthode close pour l'instant)


@pytest.fixture(scope="session", autouse=True)
def mock_surya_modules():
    """
    Mock les modules Surya dans sys.modules pour tests unitaires.

    Surya n'est pas installé dans l'environnement de test (dépendance lourde ~4Go).
    Ce mock permet aux tests d'importer ocr.py sans ModuleNotFoundError.

    Les fonctions clés reçoivent un __name__ explicite pour que les mock_thread_exec
    des tests puissent les identifier par nom.
    """
    # run_ocr avec __name__ explicite pour que les tests puissent le détecter
    mock_run_ocr = MagicMock()
    mock_run_ocr.__name__ = "run_ocr"
    mock_surya_ocr = MagicMock()
    mock_surya_ocr.run_ocr = mock_run_ocr

    # load_model/load_processor avec __name__ pour lazy loading test
    def _make_named_mock(name: str) -> MagicMock:
        m = MagicMock()
        m.__name__ = name
        return m

    mock_det_model_module = MagicMock()
    mock_det_model_module.load_model = _make_named_mock("load_model")
    mock_det_proc_module = MagicMock()
    mock_det_proc_module.load_processor = _make_named_mock("load_processor")
    mock_rec_model_module = MagicMock()
    mock_rec_model_module.load_model = _make_named_mock("load_model")
    mock_rec_proc_module = MagicMock()
    mock_rec_proc_module.load_processor = _make_named_mock("load_processor")

    surya_mocks = {
        "surya": MagicMock(),
        "surya.model": MagicMock(),
        "surya.model.detection": MagicMock(),
        "surya.model.detection.model": mock_det_model_module,
        "surya.model.detection.processor": mock_det_proc_module,
        "surya.model.recognition": MagicMock(),
        "surya.model.recognition.model": mock_rec_model_module,
        "surya.model.recognition.processor": mock_rec_proc_module,
        "surya.ocr": mock_surya_ocr,
    }
    with patch.dict(sys.modules, surya_mocks):
        yield
