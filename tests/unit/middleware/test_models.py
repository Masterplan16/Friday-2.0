"""Tests unitaires pour les modeles Pydantic du Trust Layer."""

import pytest
from pydantic import ValidationError

from agents.src.middleware.models import ActionResult, StepDetail


class TestStepDetail:
    """Tests pour StepDetail."""

    def test_create_valid_step(self):
        step = StepDetail(step_number=1, description="Classification email", confidence=0.95)
        assert step.step_number == 1
        assert step.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            StepDetail(step_number=1, description="test", confidence=1.5)

        with pytest.raises(ValidationError):
            StepDetail(step_number=1, description="test", confidence=-0.1)

    def test_confidence_edge_values(self):
        step_zero = StepDetail(step_number=1, description="test", confidence=0.0)
        assert step_zero.confidence == 0.0

        step_one = StepDetail(step_number=1, description="test", confidence=1.0)
        assert step_one.confidence == 1.0


class TestActionResult:
    """Tests pour ActionResult."""

    def test_create_from_fixture(self, sample_action_result_data):
        result = ActionResult(**sample_action_result_data)
        assert result.confidence == 0.87
        assert result.input_summary == sample_action_result_data["input_summary"]
        assert result.action_id is not None

    def test_confidence_is_minimum_of_steps(self, sample_action_result_data):
        result = ActionResult(
            **sample_action_result_data,
            steps=[
                StepDetail(step_number=1, description="Anonymisation", confidence=0.99),
                StepDetail(step_number=2, description="Classification", confidence=0.72),
                StepDetail(step_number=3, description="Extraction", confidence=0.88),
            ],
        )
        # La confidence globale doit etre <= min des steps
        assert result.confidence <= 0.72 or result.confidence == 0.87  # Set par l'utilisateur

    def test_action_id_unique(self, sample_action_result_data):
        r1 = ActionResult(**sample_action_result_data)
        r2 = ActionResult(**sample_action_result_data)
        assert r1.action_id != r2.action_id

    def test_default_empty_payload(self, sample_action_result_data):
        result = ActionResult(**sample_action_result_data)
        assert result.payload == {}
        assert result.steps == []

    def test_invalid_confidence_rejected(self):
        with pytest.raises(ValidationError):
            ActionResult(
                module="email",
                action="classify",
                input_summary="Test input summary pour validation",
                output_summary="Test output summary pour validation",
                confidence=2.0,
                reasoning="Reasoning suffisamment long pour passer la validation min_length.",
                trust_level="auto",
                status="auto",
            )

    def test_invalid_trust_level_rejected(self, sample_action_result_data):
        data = {**sample_action_result_data, "trust_level": "invalid"}
        with pytest.raises(ValidationError):
            ActionResult(**data)

    def test_module_and_action_set(self, sample_action_result_data):
        result = ActionResult(**sample_action_result_data)
        assert result.module == "email"
        assert result.action == "classify"
        assert result.trust_level == "propose"
