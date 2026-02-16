"""
Tests anti-contamination périmètres finance - Validation Pydantic.

Story 3.2 - Task 8.3 - AC6 CRITIQUE
Vérifie qu'un document SELARL ne peut PAS être classé dans SCM/SCI/etc.

NOTE: Ces tests valident la couche modèle Pydantic (ClassificationResult).
Les tests d'intégration pipeline complets (Redis → Classify → Move → PG)
seront dans test_classification_pipeline_integration.py avec mocks/fixtures
appropriés.
"""
import pytest
from pydantic import ValidationError
from agents.src.agents.archiviste.models import ClassificationResult


# ==================== Anti-contamination Pydantic (AC6) ====================

class TestFinanceAntiContamination:
    """Tests AC6 : Validation stricte périmètres finance."""

    def test_finance_invalid_perimeter_raises_error(self):
        """Test AC6 : Périmètre finance invalide lève ValueError."""
        with pytest.raises(ValidationError, match="Invalid financial perimeter"):
            ClassificationResult(
                category="finance",
                subcategory="invalid_perimeter",
                path="finance/invalid_perimeter",
                confidence=0.90,
                reasoning="Test anti-contamination"
            )

    def test_finance_must_have_subcategory(self):
        """Test AC6 : Finance DOIT avoir un subcategory."""
        with pytest.raises(ValidationError, match="Finance category requires subcategory"):
            ClassificationResult(
                category="finance",
                subcategory=None,
                path="finance",
                confidence=0.90,
                reasoning="Test validation finance"
            )

    def test_finance_valid_perimeters_accepted(self):
        """Test AC6 : Les 5 périmètres valides sont acceptés."""
        valid_perimeters = ["selarl", "scm", "sci_ravas", "sci_malbosc", "personal"]

        for perimeter in valid_perimeters:
            result = ClassificationResult(
                category="finance",
                subcategory=perimeter,
                path=f"finance/{perimeter}",
                confidence=0.92,
                reasoning=f"Test {perimeter} valide"
            )
            assert result.subcategory == perimeter

    def test_non_finance_categories_do_not_require_subcategory(self):
        """Test catégories non-finance n'exigent pas subcategory."""
        categories = ["pro", "universite", "recherche", "perso"]

        for category in categories:
            result = ClassificationResult(
                category=category,
                subcategory=None,
                path=category,
                confidence=0.88,
                reasoning=f"Test {category}"
            )
            assert result.category == category

    def test_finance_cross_contamination_selarl_to_scm(self):
        """Test AC6 : Document marqué SELARL ne peut pas accepter SCM comme périmètre."""
        # Vérifier que le modèle interdit les périmètres non-standard
        with pytest.raises(ValidationError):
            ClassificationResult(
                category="finance",
                subcategory="selarl_scm_mixed",
                path="finance/selarl_scm_mixed",
                confidence=0.90,
                reasoning="Tentative contamination"
            )

    def test_invalid_category_rejected(self):
        """Test : Catégorie invalide rejetée."""
        with pytest.raises(ValidationError, match="Invalid category"):
            ClassificationResult(
                category="medical",
                subcategory=None,
                path="medical",
                confidence=0.90,
                reasoning="Catégorie inexistante"
            )

    def test_confidence_bounds(self):
        """Test : Confidence doit être entre 0.0 et 1.0."""
        with pytest.raises(ValidationError):
            ClassificationResult(
                category="pro",
                subcategory=None,
                path="pro",
                confidence=1.5,
                reasoning="Confidence hors limites"
            )

        with pytest.raises(ValidationError):
            ClassificationResult(
                category="pro",
                subcategory=None,
                path="pro",
                confidence=-0.1,
                reasoning="Confidence négative"
            )
