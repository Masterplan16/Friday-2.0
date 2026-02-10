"""
Tests unitaires pour le Trust Layer middleware.

Tests couverts :
- TrustManager : init, load_trust_levels, get_trust_level, load_correction_rules
- Décorateur @friday_action : auto, propose, blocked, error handling
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from agents.src.middleware.models import ActionResult, CorrectionRule
from agents.src.middleware.trust import (
    TrustManager,
    friday_action,
    get_trust_manager,
    init_trust_manager,
)


# ==========================================
# Fixtures
# ==========================================


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg.Pool pour tests unitaires."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = AsyncMock(return_value=None)
    return pool


@pytest.fixture
def trust_manager(mock_db_pool):
    """Fixture TrustManager avec mock DB."""
    return TrustManager(db_pool=mock_db_pool)


@pytest.fixture
def temp_trust_levels_yaml(tmp_path: Path):
    """Créer un fichier trust_levels.yaml temporaire pour tests."""
    yaml_content = """
modules:
  email:
    classify: auto
    draft: propose
    send: blocked
  archiviste:
    ocr: auto
    classify: propose
"""
    yaml_file = tmp_path / "trust_levels.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")
    return str(yaml_file)


@pytest.fixture
def sample_correction_rules():
    """Fixture avec des correction_rules d'exemple."""
    return [
        CorrectionRule(
            id=uuid4(),
            module="email",
            action_type="classify",
            scope="classification",
            priority=1,
            conditions={"sender_contains": "@urgent.com"},
            output={"category": "urgent"},
            source_receipts=[],
            hit_count=5,
            active=True,
            created_at=datetime.now(UTC),
            created_by="owner",
        ),
        CorrectionRule(
            id=uuid4(),
            module="email",
            action_type="classify",
            scope="classification",
            priority=2,
            conditions={"subject_contains": "facture"},
            output={"category": "finance"},
            source_receipts=[],
            hit_count=10,
            active=True,
            created_at=datetime.now(UTC),
            created_by="owner",
        ),
    ]


# ==========================================
# Tests TrustManager
# ==========================================


def test_trust_manager_init(mock_db_pool):
    """Test : TrustManager s'initialise correctement avec db_pool."""
    manager = TrustManager(db_pool=mock_db_pool)

    assert manager.db_pool == mock_db_pool
    assert manager.trust_levels == {}
    assert manager._loaded is False


@pytest.mark.asyncio
async def test_load_trust_levels(trust_manager, temp_trust_levels_yaml):
    """Test : Chargement trust_levels.yaml réussi."""
    await trust_manager.load_trust_levels(temp_trust_levels_yaml)

    assert trust_manager._loaded is True
    assert "email" in trust_manager.trust_levels
    assert "archiviste" in trust_manager.trust_levels
    assert trust_manager.trust_levels["email"]["classify"] == "auto"
    assert trust_manager.trust_levels["email"]["draft"] == "propose"
    assert trust_manager.trust_levels["email"]["send"] == "blocked"


@pytest.mark.asyncio
async def test_get_trust_level(trust_manager, temp_trust_levels_yaml):
    """Test : Récupération trust level correct."""
    await trust_manager.load_trust_levels(temp_trust_levels_yaml)

    # Trust levels valides
    assert trust_manager.get_trust_level("email", "classify") == "auto"
    assert trust_manager.get_trust_level("email", "draft") == "propose"
    assert trust_manager.get_trust_level("email", "send") == "blocked"

    # Module inconnu
    with pytest.raises(ValueError, match="Unknown module"):
        trust_manager.get_trust_level("unknown_module", "action")

    # Action inconnue
    with pytest.raises(ValueError, match="Unknown action"):
        trust_manager.get_trust_level("email", "unknown_action")


@pytest.mark.asyncio
async def test_load_correction_rules(trust_manager, mock_db_pool):
    """Test : Chargement correction_rules depuis PostgreSQL (mock)."""
    # Mock fetchval retournant des rows SQL
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "module": "email",
                "action_type": "classify",
                "scope": "classification",
                "priority": 1,
                "conditions": {"test": "value"},
                "output": {"category": "urgent"},
                "source_receipts": [],
                "hit_count": 5,
                "active": True,
                "created_at": datetime.now(UTC),
                "created_by": "owner",
            }
        ]
    )

    rules = await trust_manager.load_correction_rules("email", "classify")

    assert len(rules) == 1
    assert rules[0].module == "email"
    assert rules[0].action_type == "classify"
    assert rules[0].priority == 1
    mock_conn.fetch.assert_called_once()


def test_format_rules_for_prompt(trust_manager, sample_correction_rules):
    """Test : Formatage rules pour LLM."""
    formatted = trust_manager.format_rules_for_prompt(sample_correction_rules)

    assert "RÈGLES DE CORRECTION PRIORITAIRES" in formatted
    assert "[Règle priorité 1]" in formatted
    assert "[Règle priorité 2]" in formatted
    assert "classification" in formatted

    # Vide si pas de règles
    assert trust_manager.format_rules_for_prompt([]) == ""


@pytest.mark.asyncio
async def test_create_receipt(trust_manager, mock_db_pool):
    """Test : Création receipt dans PostgreSQL (mock)."""
    # Mock fetchval retournant un UUID
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    receipt_id = uuid4()
    mock_conn.fetchval = AsyncMock(return_value=receipt_id)

    # ActionResult d'exemple
    result = ActionResult(
        module="email",
        action_type="classify",
        input_summary="Email de test@example.com: Test subject",
        output_summary="→ Category: urgent",
        confidence=0.95,
        reasoning="Mots-clés détectés: urgent, important",
        payload={"category": "urgent"},
        steps=[],
        duration_ms=150,
        trust_level="auto",
        status="auto",
    )

    created_id = await trust_manager.create_receipt(result)

    assert created_id == str(receipt_id)
    mock_conn.fetchval.assert_called_once()


# ==========================================
# Tests décorateur @friday_action
# ==========================================


@pytest.mark.asyncio
async def test_friday_action_auto(trust_manager, temp_trust_levels_yaml, mock_db_pool):
    """Test : Décorateur avec trust=auto exécute l'action."""
    # Setup trust manager
    await trust_manager.load_trust_levels(temp_trust_levels_yaml)

    # Mock create_receipt
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchval = AsyncMock(return_value=uuid4())
    mock_conn.fetch = AsyncMock(return_value=[])  # Pas de correction_rules

    # Mock get_trust_manager() pour retourner notre trust_manager mocké
    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager):
        # Fonction décorée
        @friday_action(module="email", action="classify", trust_default="auto")
        async def classify_email_auto(**kwargs: Any) -> ActionResult:
            return ActionResult(
                input_summary="Email de test@example.com",
                output_summary="→ Category: urgent",
                confidence=0.95,
                reasoning="Test reasoning for auto action",
            )

        result = await classify_email_auto()

    assert result.status == "auto"
    assert result.module == "email"
    assert result.action_type == "classify"
    assert result.trust_level == "auto"
    assert result.duration_ms is not None


@pytest.mark.asyncio
async def test_friday_action_propose(trust_manager, temp_trust_levels_yaml, mock_db_pool):
    """Test : Décorateur avec trust=propose attend validation."""
    # Setup trust manager
    await trust_manager.load_trust_levels(temp_trust_levels_yaml)

    # Mock
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchval = AsyncMock(return_value=uuid4())
    mock_conn.fetch = AsyncMock(return_value=[])

    # Mock get_trust_manager()
    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager):
        # Fonction décorée (draft = propose selon yaml)
        @friday_action(module="email", action="draft", trust_default="propose")
        async def draft_email(**kwargs: Any) -> ActionResult:
            return ActionResult(
                input_summary="Email de test@example.com",
                output_summary="→ brouillon créé",
                confidence=0.85,
                reasoning="Test reasoning for propose action",
            )

        result = await draft_email()

    assert result.status == "pending"
    assert result.trust_level == "propose"


@pytest.mark.asyncio
async def test_friday_action_blocked(trust_manager, temp_trust_levels_yaml, mock_db_pool):
    """Test : Décorateur avec trust=blocked analyse seule."""
    # Setup trust manager
    await trust_manager.load_trust_levels(temp_trust_levels_yaml)

    # Mock
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchval = AsyncMock(return_value=uuid4())
    mock_conn.fetch = AsyncMock(return_value=[])

    # Mock get_trust_manager()
    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager):
        # Fonction décorée (send = blocked selon yaml)
        @friday_action(module="email", action="send", trust_default="blocked")
        async def send_email(**kwargs: Any) -> ActionResult:
            return ActionResult(
                input_summary="Email à envoyer pour test",
                output_summary="→ analyse seule pour validation",
                confidence=0.90,
                reasoning="Test reasoning for blocked action security",
            )

        result = await send_email()

    assert result.status == "blocked"
    assert result.trust_level == "blocked"


@pytest.mark.asyncio
async def test_friday_action_error(trust_manager, temp_trust_levels_yaml, mock_db_pool):
    """Test : Décorateur gère les exceptions correctement."""
    # Setup trust manager
    await trust_manager.load_trust_levels(temp_trust_levels_yaml)

    # Mock
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchval = AsyncMock(return_value=uuid4())
    mock_conn.fetch = AsyncMock(return_value=[])

    # Mock get_trust_manager()
    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager):
        # Fonction décorée qui raise une exception
        @friday_action(module="email", action="classify", trust_default="auto")
        async def failing_action(**kwargs: Any) -> ActionResult:
            raise ValueError("Test error")

        # L'exception doit être propagée après création du receipt d'erreur
        with pytest.raises(ValueError, match="Test error"):
            await failing_action()

    # Un receipt d'erreur doit avoir été créé
    mock_conn.fetchval.assert_called_once()


# ==========================================
# Tests edge cases et améliorations (code review fixes)
# ==========================================


@pytest.mark.asyncio
async def test_load_trust_levels_file_not_found(trust_manager):
    """Test : FileNotFoundError si fichier trust_levels.yaml absent."""
    with pytest.raises(FileNotFoundError):
        await trust_manager.load_trust_levels("nonexistent_file.yaml")


def test_get_trust_level_not_loaded(trust_manager):
    """Test : RuntimeError si trust_levels pas encore chargés."""
    # trust_manager pas encore chargé (_loaded = False)
    with pytest.raises(RuntimeError, match="not loaded"):
        trust_manager.get_trust_level("email", "classify")


@pytest.mark.asyncio
async def test_friday_action_injects_rules_prompt(
    trust_manager, temp_trust_levels_yaml, mock_db_pool
):
    """
    Test : Le décorateur injecte bien _rules_prompt et _correction_rules dans kwargs.

    Vérifie que les règles chargées sont accessibles à la fonction décorée.
    """
    # Setup trust manager
    await trust_manager.load_trust_levels(temp_trust_levels_yaml)

    # Mock correction_rules (2 règles)
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "module": "email",
                "action_type": "classify",
                "scope": "test-scope",
                "priority": 1,
                "conditions": {"test": "value1"},
                "output": {"category": "test1"},
                "source_receipts": [],
                "hit_count": 5,
                "active": True,
                "created_at": datetime.now(UTC),
                "created_by": "owner",
            },
            {
                "id": uuid4(),
                "module": "email",
                "action_type": "classify",
                "scope": "test-scope-2",
                "priority": 2,
                "conditions": {"test": "value2"},
                "output": {"category": "test2"},
                "source_receipts": [],
                "hit_count": 3,
                "active": True,
                "created_at": datetime.now(UTC),
                "created_by": "owner",
            },
        ]
    )
    mock_conn.fetchval = AsyncMock(return_value=uuid4())

    # Capturer les kwargs injectés
    captured_kwargs = {}

    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager):

        @friday_action(module="email", action="classify", trust_default="auto")
        async def test_func(**kwargs: Any) -> ActionResult:
            # Capturer kwargs pour vérification
            captured_kwargs.update(kwargs)
            return ActionResult(
                input_summary="Email test injection rules",
                output_summary="→ Test injection successful",
                confidence=0.95,
                reasoning="Test reasoning for kwargs injection verification",
            )

        result = await test_func()

    # Vérifier que _rules_prompt et _correction_rules sont injectés
    assert "_rules_prompt" in captured_kwargs
    assert "_correction_rules" in captured_kwargs

    # Vérifier le contenu
    assert len(captured_kwargs["_correction_rules"]) == 2
    assert "RÈGLES DE CORRECTION PRIORITAIRES" in captured_kwargs["_rules_prompt"]
    assert "[Règle priorité 1]" in captured_kwargs["_rules_prompt"]
    assert "[Règle priorité 2]" in captured_kwargs["_rules_prompt"]


@pytest.mark.asyncio
async def test_friday_action_propose_calls_telegram_validation(
    trust_manager, temp_trust_levels_yaml, mock_db_pool
):
    """
    Test : Le décorateur appelle send_telegram_validation() pour trust=propose.

    Vérifie que la méthode Telegram est bien appelée avec le bon ActionResult.
    """
    # Setup trust manager
    await trust_manager.load_trust_levels(temp_trust_levels_yaml)

    # Mock
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchval = AsyncMock(return_value=uuid4())
    mock_conn.fetch = AsyncMock(return_value=[])

    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager):
        # Mock send_telegram_validation pour vérifier l'appel
        with patch.object(
            trust_manager, "send_telegram_validation", new=AsyncMock()
        ) as mock_telegram:

            @friday_action(module="email", action="draft", trust_default="propose")
            async def propose_action(**kwargs: Any) -> ActionResult:
                return ActionResult(
                    input_summary="Email test propose with Telegram",
                    output_summary="→ Brouillon créé, attend validation",
                    confidence=0.85,
                    reasoning="Test reasoning for Telegram validation call",
                )

            result = await propose_action()

            # Vérifier que send_telegram_validation() a été appelé UNE fois
            mock_telegram.assert_called_once()

            # Vérifier le status
            assert result.status == "pending"
            assert result.trust_level == "propose"
