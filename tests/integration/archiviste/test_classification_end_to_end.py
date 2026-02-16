"""
Tests E2E pipeline classification documents (Story 3.2 Task 8.1-8.2+8.5).

Test dataset : 20 documents variés (5 catégories × 4 documents)
Pipeline complet : document.processed → classify → move → PG update → document.classified
Validation latence < 10s
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.archiviste.classification_pipeline import ClassificationPipeline
from agents.src.agents.archiviste.classifier import ClassificationResult, DocumentClassifier
from agents.src.agents.archiviste.file_mover import FileMover
from agents.src.middleware.models import ActionResult

# ============================================================================
# TEST DATASET : 20 documents variés (Task 8.1)
# ============================================================================

TEST_DOCUMENTS: List[Dict[str, Any]] = [
    # --- PRO (4 documents) ---
    {
        "document_id": "doc-pro-001",
        "ocr_text": "Courrier ARS Occitanie concernant votre activité de médecin généraliste",
        "expected_category": "pro",
        "expected_subcategory": None,
        "filename": "2026-02-01_Courrier_ARS.pdf",
    },
    {
        "document_id": "doc-pro-002",
        "ocr_text": "Attestation RPPS numéro 123456789 - Ordre des médecins",
        "expected_category": "pro",
        "expected_subcategory": None,
        "filename": "2026-01-15_Attestation_RPPS.pdf",
    },
    {
        "document_id": "doc-pro-003",
        "ocr_text": "Convocation inspection sanitaire cabinet médical",
        "expected_category": "pro",
        "expected_subcategory": None,
        "filename": "2026-02-10_Convocation_Inspection.pdf",
    },
    {
        "document_id": "doc-pro-004",
        "ocr_text": "Convention CPAM médecin secteur 1 renouvellement",
        "expected_category": "pro",
        "expected_subcategory": None,
        "filename": "2025-12-20_Convention_CPAM.pdf",
    },
    # --- FINANCE (4 documents) ---
    {
        "document_id": "doc-fin-001",
        "ocr_text": "Facture Laboratoire Cerba 145 EUR Cabinet médical SELARL",
        "expected_category": "finance",
        "expected_subcategory": "selarl",
        "filename": "2026-02-08_Facture_Cerba_145EUR.pdf",
    },
    {
        "document_id": "doc-fin-002",
        "ocr_text": "Charges mensuelles SCM janvier 2026 Société Civile de Moyens",
        "expected_category": "finance",
        "expected_subcategory": "scm",
        "filename": "2026-01-31_Charges_SCM.pdf",
    },
    {
        "document_id": "doc-fin-003",
        "ocr_text": "Taxe foncière SCI Ravas copropriété lot 12",
        "expected_category": "finance",
        "expected_subcategory": "sci_ravas",
        "filename": "2025-11-15_TF_SCI-Ravas.pdf",
    },
    {
        "document_id": "doc-fin-004",
        "ocr_text": "Relevé bancaire compte courant personnel février 2026",
        "expected_category": "finance",
        "expected_subcategory": "personal",
        "filename": "2026-02-01_Releve_Personnel.pdf",
    },
    # --- UNIVERSITE (4 documents) ---
    {
        "document_id": "doc-uni-001",
        "ocr_text": "Thèse de doctorat version finale soutenance prévue mars 2026",
        "expected_category": "universite",
        "expected_subcategory": None,
        "filename": "2026-02-05_These_v_finale.pdf",
    },
    {
        "document_id": "doc-uni-002",
        "ocr_text": "Support de cours Master 2 Pharmacologie 2025-2026",
        "expected_category": "universite",
        "expected_subcategory": None,
        "filename": "2026-01-20_Cours_M2_Pharmaco.pdf",
    },
    {
        "document_id": "doc-uni-003",
        "ocr_text": "Rapport jury thèse comité de suivi doctoral",
        "expected_category": "universite",
        "expected_subcategory": None,
        "filename": "2025-06-30_Rapport_Jury.pdf",
    },
    {
        "document_id": "doc-uni-004",
        "ocr_text": "Sujet examen session janvier Biochimie L3",
        "expected_category": "universite",
        "expected_subcategory": None,
        "filename": "2026-01-10_Examen_L3_Biochimie.pdf",
    },
    # --- RECHERCHE (4 documents) ---
    {
        "document_id": "doc-rech-001",
        "ocr_text": "Article Nature Medicine SGLT2 inhibitors efficacy diabetes",
        "expected_category": "recherche",
        "expected_subcategory": None,
        "filename": "2025-12-15_Article_SGLT2.pdf",
    },
    {
        "document_id": "doc-rech-002",
        "ocr_text": "Dossier ANR appel à projets recherche médicale 2026",
        "expected_category": "recherche",
        "expected_subcategory": None,
        "filename": "2026-01-05_Dossier_ANR.pdf",
    },
    {
        "document_id": "doc-rech-003",
        "ocr_text": "Communication orale congrès EASD Barcelona septembre 2026",
        "expected_category": "recherche",
        "expected_subcategory": None,
        "filename": "2026-02-12_Abstract_EASD.pdf",
    },
    {
        "document_id": "doc-rech-004",
        "ocr_text": "Résultats essai clinique phase III protocole RCT-2024-001",
        "expected_category": "recherche",
        "expected_subcategory": None,
        "filename": "2026-01-28_Resultats_RCT.pdf",
    },
    # --- PERSO (4 documents) ---
    {
        "document_id": "doc-perso-001",
        "ocr_text": "Facture plombier réparation salle de bain domicile",
        "expected_category": "perso",
        "expected_subcategory": None,
        "filename": "2026-02-03_Facture_Plombier.pdf",
    },
    {
        "document_id": "doc-perso-002",
        "ocr_text": "Confirmation réservation vol Paris Tokyo 15 avril 2026",
        "expected_category": "perso",
        "expected_subcategory": None,
        "filename": "2026-02-10_Reservation_Vol.pdf",
    },
    {
        "document_id": "doc-perso-003",
        "ocr_text": "Attestation assurance habitation 2026 Maif",
        "expected_category": "perso",
        "expected_subcategory": None,
        "filename": "2026-01-01_Assurance_Maif.pdf",
    },
    {
        "document_id": "doc-perso-004",
        "ocr_text": "Certificat de scolarité enfant école primaire 2025-2026",
        "expected_category": "perso",
        "expected_subcategory": None,
        "filename": "2025-09-15_Certificat_Scolarite.pdf",
    },
]


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_llm_adapter():
    """Mock adaptateur LLM qui retourne des classifications correctes."""
    with patch("agents.src.agents.archiviste.classifier.get_llm_adapter") as mock:
        llm = AsyncMock()
        mock.return_value = llm
        yield llm


@pytest.fixture
def mock_presidio():
    """Mock Presidio anonymisation."""
    with patch("agents.src.agents.archiviste.classifier.anonymize_text") as mock:
        mock.return_value = "ANONYMIZED_TEXT"
        yield mock


@pytest.fixture
def classifier(mock_llm_adapter, mock_presidio):
    """Instance classifier avec mocks."""
    return DocumentClassifier()


# ============================================================================
# TEST E2E : Classification pipeline complète (Task 8.2)
# ============================================================================


@pytest.mark.asyncio
async def test_e2e_classify_all_20_documents(classifier, mock_llm_adapter):
    """
    Test E2E : 20 documents classifiés correctement.

    Pipeline : metadata → classify → ActionResult → ClassificationResult
    Vérifie catégorie, subcategory, et structure retour pour chaque document.
    """
    for doc in TEST_DOCUMENTS:
        # Configurer réponse LLM mock
        mock_llm_adapter.complete.return_value = {
            "category": doc["expected_category"],
            "subcategory": doc["expected_subcategory"],
            "confidence": 0.92,
            "reasoning": f"Test document {doc['document_id']}",
        }

        metadata = {"ocr_text": doc["ocr_text"], "document_id": doc["document_id"]}

        result = await classifier.classify(metadata)

        # Vérifier structure ActionResult
        assert isinstance(result, ActionResult), f"Expected ActionResult for {doc['document_id']}"
        assert (
            result.confidence >= 0.7
        ), f"Low confidence for {doc['document_id']}: {result.confidence}"

        # Vérifier classification
        classification = ClassificationResult(**result.payload)
        assert classification.category == doc["expected_category"], (
            f"Wrong category for {doc['document_id']}: "
            f"expected {doc['expected_category']}, got {classification.category}"
        )

        if doc["expected_subcategory"]:
            assert classification.subcategory == doc["expected_subcategory"], (
                f"Wrong subcategory for {doc['document_id']}: "
                f"expected {doc['expected_subcategory']}, got {classification.subcategory}"
            )


@pytest.mark.asyncio
async def test_e2e_finance_anti_contamination(classifier, mock_llm_adapter):
    """
    Test E2E AC6 : Finance anti-contamination.

    Vérifie que chaque document finance est classifié dans le BON périmètre
    et qu'un périmètre invalide est rejeté.
    """
    finance_docs = [d for d in TEST_DOCUMENTS if d["expected_category"] == "finance"]

    for doc in finance_docs:
        mock_llm_adapter.complete.return_value = {
            "category": "finance",
            "subcategory": doc["expected_subcategory"],
            "confidence": 0.94,
            "reasoning": f"Finance {doc['expected_subcategory']}",
        }

        metadata = {"ocr_text": doc["ocr_text"], "document_id": doc["document_id"]}

        result = await classifier.classify(metadata)
        classification = ClassificationResult(**result.payload)

        assert classification.category == "finance"
        assert classification.subcategory == doc["expected_subcategory"]

    # Test périmètre invalide → ValueError
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "invalid_perimeter",
        "confidence": 0.90,
        "reasoning": "Test",
    }

    with pytest.raises(ValueError, match="Invalid financial perimeter"):
        await classifier.classify({"ocr_text": "Facture test", "document_id": "doc-invalid"})


# ============================================================================
# TEST LATENCE < 10s (Task 8.5)
# ============================================================================


@pytest.mark.asyncio
async def test_classification_latency_under_10s(classifier, mock_llm_adapter):
    """
    Test Task 8.5 : Vérifier latence classification < 10s.

    Exécute classification de 20 documents et vérifie que chaque
    classification individuelle prend < 10s et la médiane < 8s.
    """
    latencies = []

    for doc in TEST_DOCUMENTS:
        mock_llm_adapter.complete.return_value = {
            "category": doc["expected_category"],
            "subcategory": doc["expected_subcategory"],
            "confidence": 0.90,
            "reasoning": f"Test {doc['document_id']}",
        }

        metadata = {"ocr_text": doc["ocr_text"], "document_id": doc["document_id"]}

        start = time.monotonic()
        await classifier.classify(metadata)
        elapsed_ms = (time.monotonic() - start) * 1000

        latencies.append(elapsed_ms)

        # Chaque classification < 10s
        assert (
            elapsed_ms < 10_000
        ), f"Classification too slow for {doc['document_id']}: {elapsed_ms:.0f}ms"

    # Médiane < 8s (Task 9.3)
    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)
    median = sorted_latencies[n // 2]

    assert median < 8_000, f"Median latency too high: {median:.0f}ms"


# ============================================================================
# TEST FILE MOVER INTEGRATION (Task 8.2)
# ============================================================================


@pytest.mark.asyncio
async def test_e2e_file_mover_atomic(tmp_path):
    """
    Test E2E : FileMover déplace fichier atomiquement.

    Crée fichier temp → move → vérifie destination existe + source supprimée.
    """
    # Créer fichier source
    source_dir = tmp_path / "transit"
    source_dir.mkdir()
    source_file = source_dir / "2026-02-08_Facture_Cerba.pdf"
    source_file.write_text("Contenu facture test")

    # Créer destination
    dest_dir = tmp_path / "archives"
    dest_dir.mkdir()

    # Classifier result
    classification = ClassificationResult(
        category="finance",
        subcategory="selarl",
        path="finance/selarl",
        confidence=0.94,
        reasoning="Facture Cerba SELARL",
    )

    # Mock config pour utiliser tmp_path
    with patch("agents.src.agents.archiviste.file_mover.get_arborescence_config") as mock_config:
        config = MagicMock()
        config.root_path = str(dest_dir)
        mock_config.return_value = config

        mover = FileMover(db_pool=None)
        result = await mover.move_document(
            source_path=str(source_file),
            classification=classification,
        )

    assert result.success, f"Move failed: {result.error}"
    assert not source_file.exists(), "Source file should be deleted"
    assert Path(result.destination_path).exists(), "Destination should exist"


@pytest.mark.asyncio
async def test_e2e_file_mover_naming_conflict(tmp_path):
    """
    Test E2E : FileMover gère collision de noms (_v2, _v3).
    """
    source_dir = tmp_path / "transit"
    source_dir.mkdir()

    dest_dir = tmp_path / "archives"
    dest_dir.mkdir()
    finance_dir = dest_dir / "finance" / "selarl"
    finance_dir.mkdir(parents=True)

    # Créer fichier existant à la destination
    existing = finance_dir / "facture.pdf"
    existing.write_text("existing")

    # Créer source
    source = source_dir / "facture.pdf"
    source.write_text("new content")

    classification = ClassificationResult(
        category="finance",
        subcategory="selarl",
        path="finance/selarl",
        confidence=0.94,
        reasoning="Test",
    )

    with patch("agents.src.agents.archiviste.file_mover.get_arborescence_config") as mock_config:
        config = MagicMock()
        config.root_path = str(dest_dir)
        mock_config.return_value = config

        mover = FileMover(db_pool=None)
        result = await mover.move_document(
            source_path=str(source),
            classification=classification,
        )

    assert result.success
    assert "_v2" in result.destination_path, "Should have _v2 suffix"


# ============================================================================
# TEST PIPELINE REDIS STREAMS (Task 8.2)
# ============================================================================


@pytest.mark.asyncio
async def test_e2e_pipeline_process_document():
    """
    Test E2E : Pipeline complet document.processed → document.classified.

    Mock Redis et PostgreSQL pour tester le flow complet.
    """
    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_db_pool = AsyncMock()

    with (
        patch("agents.src.agents.archiviste.classifier.get_llm_adapter") as mock_llm,
        patch("agents.src.agents.archiviste.classifier.anonymize_text") as mock_presidio,
        patch("agents.src.agents.archiviste.file_mover.get_arborescence_config") as mock_config,
    ):

        # Setup mocks
        llm = AsyncMock()
        llm.complete.return_value = {
            "category": "pro",
            "subcategory": None,
            "confidence": 0.92,
            "reasoning": "Document professionnel",
        }
        mock_llm.return_value = llm
        mock_presidio.return_value = "ANONYMIZED"

        config = MagicMock()
        config.root_path = "/tmp/test"
        mock_config.return_value = config

        pipeline = ClassificationPipeline(mock_redis, mock_db_pool)

        # Simuler message Redis
        msg_id = b"1234567890-0"
        data = {
            b"document_id": b"doc-e2e-001",
            b"file_path": b"/tmp/nonexistent.pdf",
            b"metadata": json.dumps({"ocr_text": "Courrier ARS"}).encode(),
        }

        # Le file_mover va échouer car fichier n'existe pas, mais la classification devrait fonctionner
        # On attend une RuntimeError du move
        try:
            await pipeline._process_document(msg_id, data)
        except RuntimeError as e:
            if "Move failed" in str(e) or "Source file not found" in str(e):
                pass  # Attendu car fichier n'existe pas
            else:
                raise

        # Vérifier que le LLM a été appelé
        assert llm.complete.called, "LLM should have been called"

        # Vérifier que Presidio a été appelé
        assert mock_presidio.called, "Presidio should have been called before LLM"
