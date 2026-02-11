"""
Tests unitaires pour models/vip_detection.py

Vérifie la validation Pydantic des schemas VIPSender et UrgencyResult.
Story 2.3 - Detection VIP & Urgence
"""

import pytest
from pydantic import ValidationError
from uuid import UUID

from agents.src.models.vip_detection import VIPSender, UrgencyResult


# ==========================================
# Tests VIPSender - Valid Inputs
# ==========================================


def test_vip_sender_valid_minimal():
    """Test création VIPSender avec champs minimaux requis."""
    data = {
        "email_anon": "[EMAIL_VIP_123]",
        "email_hash": "a" * 64,
    }

    vip = VIPSender(**data)

    assert vip.email_anon == "[EMAIL_VIP_123]"
    assert vip.email_hash == "a" * 64
    assert vip.id is None
    assert vip.label is None
    assert vip.priority_override is None
    assert vip.designation_source == "manual"
    assert vip.added_by is None
    assert vip.emails_received_count == 0
    assert vip.active is True


def test_vip_sender_valid_complete():
    """Test création VIPSender avec tous les champs."""
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    vip_id = "987e6543-e21b-98d7-b654-321098765432"

    data = {
        "id": vip_id,
        "email_anon": "[EMAIL_DOYEN_456]",
        "email_hash": "b" * 64,
        "label": "Doyen Faculté Médecine",
        "priority_override": "urgent",
        "designation_source": "manual",
        "added_by": user_id,
        "emails_received_count": 42,
        "active": True,
    }

    vip = VIPSender(**data)

    assert vip.id == UUID(vip_id)
    assert vip.email_anon == "[EMAIL_DOYEN_456]"
    assert vip.label == "Doyen Faculté Médecine"
    assert vip.priority_override == "urgent"
    assert vip.emails_received_count == 42


def test_vip_sender_valid_priority_override_values():
    """Test que toutes les valeurs priority_override valides sont acceptées."""
    valid_priorities = ["high", "urgent"]

    for priority in valid_priorities:
        vip = VIPSender(
            email_anon="[EMAIL_TEST]",
            email_hash="c" * 64,
            priority_override=priority,
        )
        assert vip.priority_override == priority


def test_vip_sender_valid_designation_source_values():
    """Test que toutes les valeurs designation_source valides sont acceptées."""
    valid_sources = ["manual", "learned"]

    for source in valid_sources:
        vip = VIPSender(
            email_anon="[EMAIL_TEST]",
            email_hash="d" * 64,
            designation_source=source,
        )
        assert vip.designation_source == source


# ==========================================
# Tests VIPSender - Invalid Inputs
# ==========================================


def test_vip_sender_invalid_email_hash_format():
    """Test que hash invalide (pas 64 caractères hex) est rejeté."""
    with pytest.raises(ValidationError) as exc_info:
        VIPSender(
            email_anon="[EMAIL_TEST]",
            email_hash="invalid_hash",  # Pas 64 hex
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("email_hash",)
    assert "string_pattern_mismatch" in errors[0]["type"]


def test_vip_sender_invalid_priority_override():
    """Test que priority_override invalide est rejetée."""
    with pytest.raises(ValidationError) as exc_info:
        VIPSender(
            email_anon="[EMAIL_TEST]",
            email_hash="e" * 64,
            priority_override="invalid_priority",
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("priority_override",)
    assert "string_pattern_mismatch" in errors[0]["type"]


def test_vip_sender_invalid_designation_source():
    """Test que designation_source invalide est rejetée."""
    with pytest.raises(ValidationError) as exc_info:
        VIPSender(
            email_anon="[EMAIL_TEST]",
            email_hash="f" * 64,
            designation_source="invalid_source",
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("designation_source",)
    assert "string_pattern_mismatch" in errors[0]["type"]


def test_vip_sender_invalid_emails_received_count_negative():
    """Test que emails_received_count négatif est rejeté."""
    with pytest.raises(ValidationError) as exc_info:
        VIPSender(
            email_anon="[EMAIL_TEST]",
            email_hash="1" * 64,
            emails_received_count=-5,
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("emails_received_count",)
    assert "greater_than_equal" in errors[0]["type"]


# ==========================================
# Tests UrgencyResult - Valid Inputs
# ==========================================


def test_urgency_result_valid_urgent():
    """Test création UrgencyResult pour email urgent."""
    data = {
        "is_urgent": True,
        "confidence": 0.85,
        "reasoning": "VIP + keyword 'deadline' détecté",
        "factors": {
            "vip": True,
            "keywords": ["deadline", "urgent"],
            "deadline": {"pattern": "avant demain", "context": "Réponse avant demain 17h"},
        },
    }

    result = UrgencyResult(**data)

    assert result.is_urgent is True
    assert result.confidence == 0.85
    assert result.reasoning == "VIP + keyword 'deadline' détecté"
    assert result.factors["vip"] is True
    assert "deadline" in result.factors["keywords"]


def test_urgency_result_valid_not_urgent():
    """Test création UrgencyResult pour email non urgent."""
    data = {
        "is_urgent": False,
        "confidence": 0.3,
        "reasoning": "Aucun facteur urgence détecté",
        "factors": {
            "vip": False,
            "keywords": [],
            "deadline": None,
        },
    }

    result = UrgencyResult(**data)

    assert result.is_urgent is False
    assert result.confidence == 0.3
    assert result.factors["keywords"] == []


def test_urgency_result_valid_confidence_boundaries():
    """Test valeurs limites confidence (0.0 et 1.0)."""
    # Confidence 0.0
    low = UrgencyResult(
        is_urgent=False,
        confidence=0.0,
        reasoning="No urgency detected",
    )
    assert low.confidence == 0.0

    # Confidence 1.0
    high = UrgencyResult(
        is_urgent=True,
        confidence=1.0,
        reasoning="Maximum urgency",
    )
    assert high.confidence == 1.0


def test_urgency_result_default_factors():
    """Test valeur par défaut de factors (dict vide)."""
    result = UrgencyResult(
        is_urgent=False,
        confidence=0.2,
        reasoning="Default factors test",
    )

    assert result.factors == {}


# ==========================================
# Tests UrgencyResult - Invalid Inputs
# ==========================================


def test_urgency_result_invalid_confidence_out_of_range_low():
    """Test que confidence < 0.0 est rejetée."""
    with pytest.raises(ValidationError) as exc_info:
        UrgencyResult(
            is_urgent=False,
            confidence=-0.1,
            reasoning="Valid reasoning",
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("confidence",)
    assert "greater_than_equal" in errors[0]["type"]


def test_urgency_result_invalid_confidence_out_of_range_high():
    """Test que confidence > 1.0 est rejetée."""
    with pytest.raises(ValidationError) as exc_info:
        UrgencyResult(
            is_urgent=True,
            confidence=1.5,
            reasoning="Valid reasoning",
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("confidence",)
    assert "less_than_equal" in errors[0]["type"]


def test_urgency_result_invalid_reasoning_too_short():
    """Test que reasoning < 10 caractères est rejeté."""
    with pytest.raises(ValidationError) as exc_info:
        UrgencyResult(
            is_urgent=True,
            confidence=0.8,
            reasoning="Short",  # Seulement 5 caractères
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("reasoning",)
    assert "string_too_short" in errors[0]["type"]


# ==========================================
# Tests JSON Serialization
# ==========================================


def test_vip_sender_to_dict():
    """Test sérialisation VIPSender en dict."""
    vip = VIPSender(
        email_anon="[EMAIL_TEST]",
        email_hash="2" * 64,
        label="Test Label",
    )

    data = vip.model_dump()

    assert data["email_anon"] == "[EMAIL_TEST]"
    assert data["email_hash"] == "2" * 64
    assert data["label"] == "Test Label"


def test_urgency_result_to_json():
    """Test sérialisation UrgencyResult en JSON."""
    result = UrgencyResult(
        is_urgent=True,
        confidence=0.75,
        reasoning="Test urgency reasoning",
        factors={"vip": True, "keywords": ["test"]},
    )

    json_str = result.model_dump_json()

    assert "true" in json_str.lower()  # is_urgent=True
    assert "0.75" in json_str
    assert "Test urgency reasoning" in json_str


def test_urgency_result_from_json():
    """Test désérialisation UrgencyResult depuis JSON."""
    json_data = """
    {
        "is_urgent": true,
        "confidence": 0.9,
        "reasoning": "Email VIP urgent",
        "factors": {
            "vip": true,
            "keywords": ["URGENT", "deadline"]
        }
    }
    """

    result = UrgencyResult.model_validate_json(json_data)

    assert result.is_urgent is True
    assert result.confidence == 0.9
    assert "URGENT" in result.factors["keywords"]
