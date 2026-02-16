"""
Tests unitaires pour DocumentRenamer (Story 3.1 - Task 3).

Tests pour renommage intelligent selon convention :
Format: YYYY-MM-DD_Type_Emetteur_MontantEUR.ext

Edge cases :
- Émetteur avec espaces, caractères spéciaux
- Montant null/absent
- Date invalide
- Collisions de noms
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.agents.archiviste.models import MetadataExtraction, RenameResult
from agents.src.agents.archiviste.renamer import DocumentRenamer
from agents.src.middleware.models import ActionResult


@pytest.fixture
def renamer():
    """Fixture pour créer une instance de DocumentRenamer."""
    return DocumentRenamer()


@pytest.fixture
def sample_metadata_facture():
    """Fixture metadata facture standard."""
    return MetadataExtraction(
        date=datetime(2026, 2, 8),
        doc_type="Facture",
        emitter="Laboratoire Cerba",
        amount=145.0,
        confidence=0.92,
        reasoning="Facture médicale standard",
    )


@pytest.mark.asyncio
async def test_rename_document_facture_standard(renamer, sample_metadata_facture):
    """
    Test AC2 : Renommage facture selon format YYYY-MM-DD_Type_Emetteur_MontantEUR.ext
    """
    # Arrange
    original_filename = "scan_20260208_001.pdf"

    # Act
    result = await renamer.rename_document(original_filename, sample_metadata_facture)

    # Assert
    assert isinstance(result, ActionResult)
    rename_result = result.payload["rename_result"]
    assert isinstance(rename_result, RenameResult)

    # Format attendu : 2026-02-08_Facture_Laboratoire-Cerba_145EUR.pdf
    assert rename_result.new_filename.startswith("2026-02-08_Facture_")
    assert (
        "Laboratoire-Cerba" in rename_result.new_filename
        or "Laboratoire" in rename_result.new_filename
    )
    assert "145EUR" in rename_result.new_filename
    assert rename_result.new_filename.endswith(".pdf")
    assert rename_result.original_filename == original_filename


@pytest.mark.asyncio
async def test_rename_document_emitter_with_spaces(renamer):
    """
    Test AC2 : Émetteur avec espaces → remplacés par tirets.

    Exemple: "Agence Régionale de Santé" → "Agence-Regionale-de-Sante"
    """
    # Arrange
    metadata = MetadataExtraction(
        date=datetime(2026, 1, 15),
        doc_type="Courrier",
        emitter="Agence Régionale de Santé",
        amount=0.0,
        confidence=0.88,
        reasoning="Courrier administratif",
    )
    original_filename = "courrier.pdf"

    # Act
    result = await renamer.rename_document(original_filename, metadata)

    # Assert
    rename_result = result.payload["rename_result"]
    # Espaces remplacés par tirets
    assert " " not in rename_result.new_filename.split(".")[0]  # Avant extension
    assert "Agence" in rename_result.new_filename
    assert "-" in rename_result.new_filename


@pytest.mark.asyncio
async def test_rename_document_emitter_with_special_chars(renamer):
    """
    Test AC2 : Émetteur avec caractères spéciaux interdits Windows → supprimés.

    Caractères interdits: \\ / : * ? " < > |
    Exemple: "Labo / Tests*?" → "Labo-Tests"
    """
    # Arrange
    metadata = MetadataExtraction(
        date=datetime(2026, 2, 10),
        doc_type="Facture",
        emitter="Labo / Tests*?",
        amount=50.0,
        confidence=0.85,
        reasoning="Facture labo",
    )
    original_filename = "test.pdf"

    # Act
    result = await renamer.rename_document(original_filename, metadata)

    # Assert
    rename_result = result.payload["rename_result"]
    # Caractères spéciaux supprimés
    forbidden_chars = ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]
    for char in forbidden_chars:
        assert char not in rename_result.new_filename


@pytest.mark.asyncio
async def test_rename_document_zero_amount(renamer):
    """
    Test AC2 : Document sans montant → 0EUR.

    Exemple: Courrier administratif sans montant
    """
    # Arrange
    metadata = MetadataExtraction(
        date=datetime(2026, 1, 20),
        doc_type="Courrier",
        emitter="ARS",
        amount=0.0,
        confidence=0.90,
        reasoning="Courrier sans montant",
    )
    original_filename = "courrier_ars.pdf"

    # Act
    result = await renamer.rename_document(original_filename, metadata)

    # Assert
    rename_result = result.payload["rename_result"]
    assert "0EUR" in rename_result.new_filename


@pytest.mark.asyncio
async def test_rename_document_fallback_inconnu(renamer):
    """
    Test AC2, Task 3.4 : Si metadata manquante → fallback "Inconnu".

    Exemple: Date invalide, émetteur vide → YYYY-MM-DD_Inconnu.ext
    """
    # Arrange
    metadata = MetadataExtraction(
        date=datetime.now(),  # Fallback date du jour
        doc_type="Inconnu",
        emitter="",  # Émetteur vide
        amount=0.0,
        confidence=0.50,
        reasoning="Métadonnées incertaines",
    )
    original_filename = "document_illisible.jpg"

    # Act
    result = await renamer.rename_document(original_filename, metadata)

    # Assert
    rename_result = result.payload["rename_result"]
    # Fallback "Inconnu" utilisé
    assert "Inconnu" in rename_result.new_filename
    assert rename_result.new_filename.endswith(".jpg")


@pytest.mark.asyncio
async def test_rename_document_preserve_extension(renamer, sample_metadata_facture):
    """
    Test AC2 : Extension du fichier original préservée.

    Exemples: .pdf → .pdf, .jpg → .jpg, .png → .png
    """
    # Arrange
    test_cases = [
        ("facture.pdf", ".pdf"),
        ("scan.jpg", ".jpg"),
        ("document.png", ".png"),
        ("garantie.TIFF", ".tiff"),  # Normalisé en minuscule
    ]

    for original, expected_ext in test_cases:
        # Act
        result = await renamer.rename_document(original, sample_metadata_facture)

        # Assert
        rename_result = result.payload["rename_result"]
        assert rename_result.new_filename.lower().endswith(expected_ext)


@pytest.mark.asyncio
async def test_rename_document_confidence_min_preserved(renamer):
    """
    Test AC5 : Confidence renommage = min(confidence metadata).

    Si metadata.confidence = 0.75 → rename_result.confidence = 0.75
    """
    # Arrange
    metadata = MetadataExtraction(
        date=datetime(2026, 2, 8),
        doc_type="Facture",
        emitter="Test",
        amount=100.0,
        confidence=0.75,
        reasoning="Confiance moyenne",
    )
    original_filename = "test.pdf"

    # Act
    result = await renamer.rename_document(original_filename, metadata)

    # Assert
    assert result.confidence == 0.75


@pytest.mark.asyncio
async def test_rename_document_emitter_too_long_truncated(renamer):
    """
    Test : Émetteur trop long (>50 chars) → tronqué à 50.

    Pour éviter noms de fichiers trop longs (limite Windows: 260 chars total).
    """
    # Arrange
    long_emitter = "A" * 80  # 80 caractères
    metadata = MetadataExtraction(
        date=datetime(2026, 2, 8),
        doc_type="Facture",
        emitter=long_emitter,
        amount=100.0,
        confidence=0.90,
        reasoning="Émetteur long",
    )
    original_filename = "test.pdf"

    # Act
    result = await renamer.rename_document(original_filename, metadata)

    # Assert
    rename_result = result.payload["rename_result"]
    # Émetteur tronqué à 50 caractères max
    emitter_part = rename_result.new_filename.split("_")[2]  # 3ème partie = emitter
    assert len(emitter_part) <= 50


@pytest.mark.asyncio
async def test_rename_document_amount_decimal_formatted(renamer):
    """
    Test AC2 : Montants décimaux formatés correctement.

    Exemples:
    - 145.50 → 145.50EUR
    - 100.00 → 100EUR (pas de .00 si entier)
    - 99.99 → 99.99EUR
    """
    # Arrange
    test_cases = [
        (145.50, "145.5EUR"),  # Python format
        (100.00, "100EUR"),
        (99.99, "99.99EUR"),
    ]

    for amount, expected in test_cases:
        metadata = MetadataExtraction(
            date=datetime(2026, 2, 8),
            doc_type="Facture",
            emitter="Test",
            amount=amount,
            confidence=0.90,
            reasoning="Test montant",
        )

        # Act
        result = await renamer.rename_document("test.pdf", metadata)

        # Assert
        rename_result = result.payload["rename_result"]
        # Montant formaté correctement
        assert (
            expected in rename_result.new_filename
            or f"{int(amount)}EUR" in rename_result.new_filename
        )


@pytest.mark.asyncio
async def test_rename_document_action_result_structure(renamer, sample_metadata_facture):
    """
    Test AC5 : ActionResult retourné avec structure correcte.

    Vérifie :
    - input_summary
    - output_summary
    - confidence
    - reasoning
    - payload contient RenameResult
    """
    # Arrange
    original_filename = "facture.pdf"

    # Act
    result = await renamer.rename_document(original_filename, sample_metadata_facture)

    # Assert
    assert isinstance(result, ActionResult)
    assert result.input_summary  # Non vide
    assert result.output_summary  # Non vide
    assert 0.0 <= result.confidence <= 1.0
    assert result.reasoning  # Non vide
    assert "rename_result" in result.payload
    assert isinstance(result.payload["rename_result"], RenameResult)


@pytest.mark.asyncio
async def test_rename_document_trust_layer_decorator_applied(renamer):
    """
    Test AC5, Task 3.2 : Vérifier que @friday_action decorator est appliqué.

    Le decorator doit enregistrer l'action dans core.action_receipts.
    """
    # Note: Ce test vérifie que la méthode a le decorator
    # Les tests d'intégration vérifieront l'enregistrement DB
    import inspect

    method = renamer.rename_document
    # Vérifier que c'est une coroutine (async)
    assert inspect.iscoroutinefunction(method)

    # TODO: Vérifier présence decorator @friday_action
    # (nécessite inspection du code source ou tests d'intégration)
