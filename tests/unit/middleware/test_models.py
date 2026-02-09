"""
Tests unitaires pour les modèles Pydantic du Trust Layer.

Tests couverts :
- ActionResult : validation champs obligatoires, confidence, trust_level, status
- model_dump_receipt() : mapping correct vers dict SQL
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.src.middleware.models import ActionResult, StepDetail


# ==========================================
# Tests ActionResult validation
# ==========================================


def test_action_result_validation():
    """Test : Validation Pydantic des champs obligatoires."""
    # ActionResult valide (module et action_type Optional, remplis par décorateur)
    result = ActionResult(
        input_summary="Email de test@example.com: Subject",
        output_summary="→ Category: urgent",
        confidence=0.95,
        reasoning="Détection mots-clés: urgent, important",
    )

    assert result.action_id is not None
    assert result.input_summary == "Email de test@example.com: Subject"
    assert result.output_summary == "→ Category: urgent"
    assert result.confidence == 0.95
    assert result.reasoning == "Détection mots-clés: urgent, important"
    assert result.payload == {}
    assert result.steps == []
    assert result.timestamp is not None

    # Champs manquants
    with pytest.raises(ValidationError):
        ActionResult(
            input_summary="Too short",  # Min 10 chars
            output_summary="→ Category: urgent",
            confidence=0.95,
            reasoning="Test",  # Min 20 chars
        )


def test_action_result_confidence():
    """Test : Validator confidence entre 0.0 et 1.0."""
    # Confidence valide
    result = ActionResult(
        input_summary="Email de test@example.com: Subject",
        output_summary="→ Category: urgent",
        confidence=0.0,
        reasoning="Confidence minimale valide",
    )
    assert result.confidence == 0.0

    result = ActionResult(
        input_summary="Email de test@example.com: Subject",
        output_summary="→ Category: urgent",
        confidence=1.0,
        reasoning="Confidence maximale valide",
    )
    assert result.confidence == 1.0

    # Confidence invalide
    with pytest.raises(ValidationError):
        ActionResult(
            input_summary="Email de test@example.com: Subject",
            output_summary="→ Category: urgent",
            confidence=-0.1,
            reasoning="Confidence négative invalide",
        )

    with pytest.raises(ValidationError):
        ActionResult(
            input_summary="Email de test@example.com: Subject",
            output_summary="→ Category: urgent",
            confidence=1.5,
            reasoning="Confidence supérieure à 1.0 invalide",
        )


def test_action_result_trust_level():
    """Test : Validator trust_level valide (auto/propose/blocked)."""
    # Trust levels valides (Optional, rempli par décorateur)
    result = ActionResult(
        input_summary="Email de test@example.com: Subject",
        output_summary="→ Category: urgent",
        confidence=0.95,
        reasoning="Test trust level auto",
        trust_level="auto",
    )
    assert result.trust_level == "auto"

    result.trust_level = "propose"
    assert result.trust_level == "propose"

    result.trust_level = "blocked"
    assert result.trust_level == "blocked"

    # Trust level invalide
    with pytest.raises(ValidationError):
        ActionResult(
            input_summary="Email de test@example.com: Subject",
            output_summary="→ Category: urgent",
            confidence=0.95,
            reasoning="Trust level invalide",
            trust_level="invalid_level",
        )


def test_action_result_status():
    """Test : Validator status valide (5 statuts SQL)."""
    # Statuts valides : auto, pending, approved, rejected, corrected
    valid_statuses = ["auto", "pending", "approved", "rejected", "corrected"]

    for status in valid_statuses:
        result = ActionResult(
            input_summary="Email de test@example.com: Subject",
            output_summary="→ Category: urgent",
            confidence=0.95,
            reasoning=f"Test status validation for {status} status",
            status=status,
        )
        assert result.status == status

    # Statut invalide
    with pytest.raises(ValidationError):
        ActionResult(
            input_summary="Email de test@example.com: Subject",
            output_summary="→ Category: urgent",
            confidence=0.95,
            reasoning="Statut invalide",
            status="invalid_status",
        )


def test_model_dump_receipt():
    """Test : Mapping correct vers dict SQL avec steps dans payload."""
    # ActionResult avec steps
    step1 = StepDetail(
        step_number=1,
        description="Analyse de l'email",
        confidence=0.95,
        duration_ms=50,
        metadata={"tokens": 150},
    )
    step2 = StepDetail(
        step_number=2,
        description="Classification finale",
        confidence=0.90,
        duration_ms=30,
    )

    result = ActionResult(
        module="email",
        action_type="classify",
        input_summary="Email de test@example.com: Subject",
        output_summary="→ Category: urgent",
        confidence=0.90,
        reasoning="Classification en 2 étapes",
        payload={"category": "urgent", "priority": "high"},
        steps=[step1, step2],
        duration_ms=150,
        trust_level="auto",
        status="auto",
    )

    receipt_dict = result.model_dump_receipt()

    # Vérifier champs SQL obligatoires
    assert "id" in receipt_dict
    assert receipt_dict["module"] == "email"
    assert receipt_dict["action_type"] == "classify"
    assert receipt_dict["input_summary"] == "Email de test@example.com: Subject"
    assert receipt_dict["output_summary"] == "→ Category: urgent"
    assert receipt_dict["confidence"] == 0.90
    assert receipt_dict["reasoning"] == "Classification en 2 étapes"
    assert receipt_dict["duration_ms"] == 150
    assert receipt_dict["trust_level"] == "auto"
    assert receipt_dict["status"] == "auto"

    # Vérifier payload JSONB inclut steps + données originales
    assert "payload" in receipt_dict
    assert receipt_dict["payload"]["category"] == "urgent"
    assert receipt_dict["payload"]["priority"] == "high"
    assert "steps" in receipt_dict["payload"]
    assert len(receipt_dict["payload"]["steps"]) == 2
    assert receipt_dict["payload"]["steps"][0]["step_number"] == 1
    assert receipt_dict["payload"]["steps"][1]["step_number"] == 2


def test_step_detail_validation():
    """Test : Validation StepDetail."""
    # StepDetail valide
    step = StepDetail(
        step_number=1,
        description="Test step",
        confidence=0.95,
        duration_ms=100,
        metadata={"key": "value"},
    )

    assert step.step_number == 1
    assert step.description == "Test step"
    assert step.confidence == 0.95
    assert step.duration_ms == 100
    assert step.metadata == {"key": "value"}

    # Confidence invalide
    with pytest.raises(ValidationError):
        StepDetail(
            step_number=1,
            description="Test step",
            confidence=1.5,  # > 1.0 invalide
        )
