"""
Tests unitaires warranty_extractor.py (Story 3.4 AC1).

18 tests couvrant :
- Extraction valide/invalide
- Confidence threshold
- Presidio anonymisation failure
- Few-shot examples validation
- Edge cases (date future, montant négatif, vendor manquant)

JAMAIS d'appel Claude réel - Toujours mocker.
"""

import json
import sys
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, ".")

from agents.src.agents.archiviste.warranty_models import WarrantyCategory, WarrantyInfo

# ============================================================================
# FIXTURES
# ============================================================================

VALID_CLAUDE_RESPONSE = json.dumps(
    {
        "warranty_detected": True,
        "item_name": "Imprimante HP DeskJet 3720",
        "item_category": "electronics",
        "vendor": "Amazon",
        "purchase_date": "2025-06-15",
        "warranty_duration_months": 24,
        "purchase_amount": 149.99,
        "confidence": 0.92,
    }
)

NO_WARRANTY_RESPONSE = json.dumps(
    {
        "warranty_detected": False,
        "item_name": "",
        "item_category": "other",
        "vendor": None,
        "purchase_date": "",
        "warranty_duration_months": 0,
        "purchase_amount": None,
        "confidence": 0.1,
    }
)

LOW_CONFIDENCE_RESPONSE = json.dumps(
    {
        "warranty_detected": True,
        "item_name": "Produit inconnu",
        "item_category": "other",
        "vendor": None,
        "purchase_date": "2025-01-01",
        "warranty_duration_months": 12,
        "purchase_amount": None,
        "confidence": 0.60,
    }
)


# ============================================================================
# WARRANTY INFO MODEL TESTS
# ============================================================================


class TestWarrantyInfo:
    """Tests pour WarrantyInfo Pydantic model."""

    def test_valid_warranty_info(self):
        """Test création WarrantyInfo valide."""
        info = WarrantyInfo(
            warranty_detected=True,
            item_name="HP Printer",
            item_category=WarrantyCategory.ELECTRONICS,
            vendor="Amazon",
            purchase_date=date(2025, 6, 15),
            warranty_duration_months=24,
            purchase_amount=Decimal("149.99"),
            confidence=0.92,
        )
        assert info.item_name == "HP Printer"
        assert info.item_category == WarrantyCategory.ELECTRONICS
        assert info.warranty_duration_months == 24
        assert info.confidence == 0.92

    def test_future_date_rejected(self):
        """Date d'achat dans le futur = ValueError."""
        from datetime import timedelta

        with pytest.raises(ValueError, match="future"):
            WarrantyInfo(
                warranty_detected=True,
                item_name="Test",
                item_category=WarrantyCategory.OTHER,
                purchase_date=date.today() + timedelta(days=30),
                warranty_duration_months=12,
                confidence=0.9,
            )

    def test_invalid_duration_too_high(self):
        """Durée >120 mois = ValueError."""
        with pytest.raises(ValueError):
            WarrantyInfo(
                warranty_detected=True,
                item_name="Test",
                item_category=WarrantyCategory.OTHER,
                purchase_date=date(2025, 1, 1),
                warranty_duration_months=121,
                confidence=0.9,
            )

    def test_invalid_duration_zero(self):
        """Durée 0 mois = ValueError."""
        with pytest.raises(ValueError):
            WarrantyInfo(
                warranty_detected=True,
                item_name="Test",
                item_category=WarrantyCategory.OTHER,
                purchase_date=date(2025, 1, 1),
                warranty_duration_months=0,
                confidence=0.9,
            )

    def test_expiration_date_property(self):
        """Test calcul date expiration."""
        info = WarrantyInfo(
            warranty_detected=True,
            item_name="Test",
            item_category=WarrantyCategory.OTHER,
            purchase_date=date(2025, 6, 15),
            warranty_duration_months=24,
            confidence=0.9,
        )
        assert info.expiration_date == date(2027, 6, 15)

    def test_all_categories_valid(self):
        """Test toutes les catégories."""
        for cat in WarrantyCategory:
            info = WarrantyInfo(
                warranty_detected=True,
                item_name="Test",
                item_category=cat,
                purchase_date=date(2025, 1, 1),
                warranty_duration_months=12,
                confidence=0.9,
            )
            assert info.item_category == cat

    def test_optional_fields(self):
        """Vendor et purchase_amount sont optionnels."""
        info = WarrantyInfo(
            warranty_detected=True,
            item_name="Test",
            item_category=WarrantyCategory.OTHER,
            purchase_date=date(2025, 1, 1),
            warranty_duration_months=12,
            confidence=0.9,
        )
        assert info.vendor is None
        assert info.purchase_amount is None

    def test_negative_amount_rejected(self):
        """Montant négatif = ValueError."""
        with pytest.raises(ValueError):
            WarrantyInfo(
                warranty_detected=True,
                item_name="Test",
                item_category=WarrantyCategory.OTHER,
                purchase_date=date(2025, 1, 1),
                warranty_duration_months=12,
                purchase_amount=Decimal("-10"),
                confidence=0.9,
            )


# ============================================================================
# EXTRACTOR FUNCTION TESTS
# ============================================================================


class TestExtractWarranty:
    """Tests pour extract_warranty_from_document."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    async def test_extract_valid_warranty(self, mock_anonymize, mock_llm):
        """Extraction garantie valide depuis facture complète."""
        mock_anonymize.return_value = ("Texte anonymisé facture HP", {})
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=VALID_CLAUDE_RESPONSE)
        mock_llm.return_value = mock_adapter

        from agents.src.agents.archiviste.warranty_extractor import extract_warranty_from_document

        result = await extract_warranty_from_document(
            document_id="test-doc-123",
            ocr_text="Facture Amazon\nHP DeskJet\nGarantie 2 ans",
        )

        assert result.payload["warranty_detected"] is True
        assert "HP" in result.output_summary or "DeskJet" in result.output_summary
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    async def test_extract_no_warranty(self, mock_anonymize, mock_llm):
        """Document sans garantie = warranty_detected False."""
        mock_anonymize.return_value = ("Texte anonymisé courrier", {})
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=NO_WARRANTY_RESPONSE)
        mock_llm.return_value = mock_adapter

        from agents.src.agents.archiviste.warranty_extractor import extract_warranty_from_document

        result = await extract_warranty_from_document(
            document_id="test-doc-456",
            ocr_text="Courrier informatif sans garantie",
        )

        assert result.payload["warranty_detected"] is False
        assert "Aucune" in result.output_summary

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    async def test_extract_low_confidence(self, mock_anonymize, mock_llm):
        """Confidence <0.75 = below_threshold True."""
        mock_anonymize.return_value = ("Texte anonymisé", {})
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=LOW_CONFIDENCE_RESPONSE)
        mock_llm.return_value = mock_adapter

        from agents.src.agents.archiviste.warranty_extractor import extract_warranty_from_document

        result = await extract_warranty_from_document(
            document_id="test-doc-789",
            ocr_text="Document flou",
        )

        assert result.payload["warranty_detected"] is True
        assert result.payload["below_threshold"] is True
        assert result.confidence == 0.60

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    async def test_extract_presidio_failure(self, mock_anonymize):
        """Presidio crash = NotImplementedError (fail-explicit)."""
        mock_anonymize.side_effect = Exception("Presidio service unavailable")

        from agents.src.agents.archiviste.warranty_extractor import extract_warranty_from_document

        with pytest.raises(NotImplementedError, match="Presidio"):
            await extract_warranty_from_document(
                document_id="test-doc",
                ocr_text="Texte quelconque",
            )

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    async def test_extract_claude_failure(self, mock_anonymize, mock_llm):
        """Claude API crash = NotImplementedError."""
        mock_anonymize.return_value = ("Texte anonymisé", {})
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(side_effect=Exception("API error"))
        mock_llm.return_value = mock_adapter

        from agents.src.agents.archiviste.warranty_extractor import extract_warranty_from_document

        with pytest.raises(NotImplementedError, match="Claude"):
            await extract_warranty_from_document(
                document_id="test-doc",
                ocr_text="Facture avec garantie",
            )

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    async def test_extract_invalid_json(self, mock_anonymize, mock_llm):
        """Réponse Claude non-JSON = NotImplementedError."""
        mock_anonymize.return_value = ("Texte anonymisé", {})
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value="ceci n'est pas du JSON")
        mock_llm.return_value = mock_adapter

        from agents.src.agents.archiviste.warranty_extractor import extract_warranty_from_document

        with pytest.raises(NotImplementedError, match="parse"):
            await extract_warranty_from_document(
                document_id="test-doc",
                ocr_text="Facture",
            )

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    async def test_extract_with_deanonymize(self, mock_anonymize, mock_llm):
        """Déanonymisation vendor si mapping présent."""
        mock_anonymize.return_value = (
            "Facture [PERSON_1] HP Printer",
            {"[PERSON_1]": "Jean Dupont"},
        )
        response = json.dumps(
            {
                "warranty_detected": True,
                "item_name": "HP Printer",
                "item_category": "electronics",
                "vendor": "[PERSON_1]",
                "purchase_date": "2025-06-15",
                "warranty_duration_months": 24,
                "purchase_amount": 149.99,
                "confidence": 0.90,
            }
        )
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=response)
        mock_llm.return_value = mock_adapter

        with patch(
            "agents.src.agents.archiviste.warranty_extractor.deanonymize_text"
        ) as mock_deanon:
            mock_deanon.return_value = "Jean Dupont"

            from agents.src.agents.archiviste.warranty_extractor import (
                extract_warranty_from_document,
            )

            result = await extract_warranty_from_document(
                document_id="test-doc",
                ocr_text="Facture Jean Dupont HP Printer",
            )

            assert result.payload["warranty_detected"] is True
            mock_deanon.assert_called()


# ============================================================================
# HELPER FUNCTION TESTS
# ============================================================================


class TestHelperFunctions:
    """Tests pour fonctions utilitaires."""

    def test_parse_date_iso(self):
        """Parse date ISO 8601."""
        from agents.src.agents.archiviste.warranty_extractor import _parse_date

        assert _parse_date("2025-06-15") == date(2025, 6, 15)

    def test_parse_date_fr_format(self):
        """Parse date format DD/MM/YYYY."""
        from agents.src.agents.archiviste.warranty_extractor import _parse_date

        assert _parse_date("15/06/2025") == date(2025, 6, 15)

    def test_parse_date_empty_raises(self):
        """Date vide = ValueError."""
        from agents.src.agents.archiviste.warranty_extractor import _parse_date

        with pytest.raises(ValueError):
            _parse_date("")

    def test_parse_category_valid(self):
        """Parse catégorie valide."""
        from agents.src.agents.archiviste.warranty_extractor import _parse_category

        assert _parse_category("electronics") == WarrantyCategory.ELECTRONICS
        assert _parse_category("APPLIANCES") == WarrantyCategory.APPLIANCES

    def test_parse_category_unknown(self):
        """Catégorie inconnue = OTHER."""
        from agents.src.agents.archiviste.warranty_extractor import _parse_category

        assert _parse_category("xyz") == WarrantyCategory.OTHER

    def test_parse_amount_valid(self):
        """Parse montant valide."""
        from agents.src.agents.archiviste.warranty_extractor import _parse_amount

        assert _parse_amount(149.99) == Decimal("149.99")
        assert _parse_amount("89.90") == Decimal("89.90")

    def test_parse_amount_none(self):
        """Montant None = None."""
        from agents.src.agents.archiviste.warranty_extractor import _parse_amount

        assert _parse_amount(None) is None

    def test_parse_amount_negative(self):
        """Montant négatif = None."""
        from agents.src.agents.archiviste.warranty_extractor import _parse_amount

        assert _parse_amount(-10) is None


# ============================================================================
# FEW-SHOT EXAMPLES VALIDATION
# ============================================================================


class TestFewShotExamples:
    """Test que les 5 exemples few-shot sont valides."""

    def test_all_examples_parse_to_warranty_info(self):
        """Tous les 5 exemples few-shot doivent produire un WarrantyInfo valide."""
        from agents.src.agents.archiviste.warranty_prompts import WARRANTY_EXTRACTION_EXAMPLES

        assert len(WARRANTY_EXTRACTION_EXAMPLES) == 5

        for i, example in enumerate(WARRANTY_EXTRACTION_EXAMPLES):
            output = example["output"]
            info = WarrantyInfo(
                warranty_detected=output["warranty_detected"],
                item_name=output["item_name"],
                item_category=WarrantyCategory(output["item_category"]),
                vendor=output.get("vendor"),
                purchase_date=date.fromisoformat(output["purchase_date"]),
                warranty_duration_months=output["warranty_duration_months"],
                purchase_amount=(
                    Decimal(str(output["purchase_amount"]))
                    if output.get("purchase_amount")
                    else None
                ),
                confidence=output["confidence"],
            )
            assert info.warranty_detected is True, f"Example {i+1} should detect warranty"
            assert info.confidence >= 0.75, f"Example {i+1} confidence should be >= 0.75"

    def test_examples_cover_all_categories(self):
        """Les exemples couvrent les 5 catégories principales."""
        from agents.src.agents.archiviste.warranty_prompts import WARRANTY_EXTRACTION_EXAMPLES

        categories_covered = set()
        for example in WARRANTY_EXTRACTION_EXAMPLES:
            categories_covered.add(example["output"]["item_category"])

        expected = {"electronics", "appliances", "automotive", "medical", "furniture"}
        assert categories_covered == expected
