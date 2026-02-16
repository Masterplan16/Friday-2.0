"""
Tests unitaires pour CheckRegistry (Story 4.1 Task 2)

RED PHASE : Tests écrits AVANT l'implémentation (TDD)
"""

import pytest
from unittest.mock import AsyncMock

from agents.src.core.check_registry import CheckRegistry
from agents.src.core.heartbeat_models import Check, CheckResult, CheckPriority


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def check_registry():
    """Fixture CheckRegistry singleton."""
    # Reset singleton entre tests
    CheckRegistry._instance = None
    return CheckRegistry()


@pytest.fixture
async def mock_check_fn():
    """Mock check function."""
    async def _mock_check(*args, **kwargs) -> CheckResult:
        return CheckResult(notify=False, message="Mock check executed")
    return _mock_check


# ============================================================================
# Tests Task 2.1-2.2: Register Checks
# ============================================================================

def test_check_registry_singleton(check_registry):
    """Test 1: CheckRegistry est singleton."""
    registry1 = CheckRegistry()
    registry2 = CheckRegistry()

    assert registry1 is registry2


@pytest.mark.asyncio
async def test_register_check(check_registry, mock_check_fn):
    """Test 2: register_check() enregistre un check."""
    check_registry.register_check(
        check_id="check_urgent_emails",
        priority=CheckPriority.HIGH,
        description="Emails urgents non lus",
        execute_fn=mock_check_fn
    )

    # Vérifier check enregistré
    check = check_registry.get_check("check_urgent_emails")
    assert check is not None
    assert check.check_id == "check_urgent_emails"
    assert check.priority == CheckPriority.HIGH
    assert check.description == "Emails urgents non lus"


def test_register_duplicate_check_id_raises_error(check_registry, mock_check_fn):
    """Test 3: Enregistrer check_id existant → ValueError."""
    check_registry.register_check(
        check_id="check_duplicate",
        priority=CheckPriority.HIGH,
        description="Check 1",
        execute_fn=mock_check_fn
    )

    with pytest.raises(ValueError, match="already registered"):
        check_registry.register_check(
            check_id="check_duplicate",
            priority=CheckPriority.MEDIUM,
            description="Check 2",
            execute_fn=mock_check_fn
        )


# ============================================================================
# Tests Task 2.3: Get Checks by Priority
# ============================================================================

@pytest.mark.asyncio
async def test_get_checks_by_priority(check_registry, mock_check_fn):
    """Test 4: get_checks_by_priority() filtre par priorité."""
    # Enregistrer checks avec priorités différentes
    check_registry.register_check(
        check_id="check_critical",
        priority=CheckPriority.CRITICAL,
        description="Check critique",
        execute_fn=mock_check_fn
    )

    check_registry.register_check(
        check_id="check_high",
        priority=CheckPriority.HIGH,
        description="Check high",
        execute_fn=mock_check_fn
    )

    check_registry.register_check(
        check_id="check_medium",
        priority=CheckPriority.MEDIUM,
        description="Check medium",
        execute_fn=mock_check_fn
    )

    # Récupérer checks CRITICAL
    critical_checks = check_registry.get_checks_by_priority(CheckPriority.CRITICAL)
    assert len(critical_checks) == 1
    assert critical_checks[0].check_id == "check_critical"

    # Récupérer checks HIGH
    high_checks = check_registry.get_checks_by_priority(CheckPriority.HIGH)
    assert len(high_checks) == 1
    assert high_checks[0].check_id == "check_high"


# ============================================================================
# Tests Task 2.4: Get All Checks
# ============================================================================

@pytest.mark.asyncio
async def test_get_all_checks(check_registry, mock_check_fn):
    """Test 5: get_all_checks() retourne tous les checks."""
    check_registry.register_check(
        check_id="check_1",
        priority=CheckPriority.HIGH,
        description="Check 1",
        execute_fn=mock_check_fn
    )

    check_registry.register_check(
        check_id="check_2",
        priority=CheckPriority.MEDIUM,
        description="Check 2",
        execute_fn=mock_check_fn
    )

    all_checks = check_registry.get_all_checks()
    assert len(all_checks) == 2

    check_ids = [c.check_id for c in all_checks]
    assert "check_1" in check_ids
    assert "check_2" in check_ids


def test_get_check_by_id_exists(check_registry, mock_check_fn):
    """Test 6: get_check() retourne check si existe."""
    check_registry.register_check(
        check_id="check_exists",
        priority=CheckPriority.MEDIUM,
        description="Check exists",
        execute_fn=mock_check_fn
    )

    check = check_registry.get_check("check_exists")
    assert check is not None
    assert check.check_id == "check_exists"


def test_get_check_by_id_not_exists(check_registry):
    """Test 7: get_check() retourne None si check inexistant."""
    check = check_registry.get_check("check_nonexistent")
    assert check is None


# ============================================================================
# Tests Task 2.5: Singleton Pattern Validation
# ============================================================================

def test_check_registry_persists_across_instances(mock_check_fn):
    """Test 8: Checks persistent entre instances singleton."""
    registry1 = CheckRegistry()
    registry1.register_check(
        check_id="check_persistent",
        priority=CheckPriority.HIGH,
        description="Check persistent",
        execute_fn=mock_check_fn
    )

    # Nouvelle instance (même singleton)
    registry2 = CheckRegistry()
    check = registry2.get_check("check_persistent")

    assert check is not None
    assert check.check_id == "check_persistent"
