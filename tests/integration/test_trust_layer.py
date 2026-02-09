"""
Tests d'intégration End-to-End pour le Trust Layer.

IMPORTANT : Ces tests nécessitent PostgreSQL réel avec migrations appliquées.

Tests couverts :
- E2E : Décorateur → INSERT receipt → SELECT vérification
- Correction rules : Antonio corrige → règle créée → règle appliquée
- Trust levels : auto exécute, propose attend, blocked bloque
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import asyncpg
import pytest

from agents.src.middleware.models import ActionResult, CorrectionRule
from agents.src.middleware.trust import TrustManager, friday_action


# Skip tous les tests si pas de variable d'env INTEGRATION_TESTS
pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Integration tests disabled. Set INTEGRATION_TESTS=1 to run.",
)


# ==========================================
# Fixtures locales
# ==========================================


@pytest.fixture
async def trust_manager_real(db_pool: asyncpg.Pool) -> TrustManager:
    """TrustManager avec vraie DB PostgreSQL."""
    manager = TrustManager(db_pool=db_pool)
    # Charger trust_levels.yaml
    config_path = Path(__file__).parent.parent.parent / "config" / "trust_levels.yaml"
    await manager.load_trust_levels(str(config_path))
    return manager


@pytest.fixture
async def load_fixtures(db_pool: asyncpg.Pool):
    """Charge les fixtures SQL avant le test."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "trust_layer_fixtures.sql"

    if fixtures_path.exists():
        with open(fixtures_path, "r", encoding="utf-8") as f:
            fixtures_sql = f.read()

        async with db_pool.acquire() as conn:
            await conn.execute(fixtures_sql)

    yield

    # Cleanup après test
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE core.correction_rules CASCADE")


# ==========================================
# Tests E2E
# ==========================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_e2e_friday_action_to_receipt(
    db_pool: asyncpg.Pool, trust_manager_real: TrustManager, clean_tables
):
    """
    Test E2E complet : Décorateur @friday_action → INSERT → SELECT receipt.

    Vérifie que :
    1. Le décorateur exécute la fonction
    2. Un receipt est créé dans core.action_receipts
    3. Le receipt peut être récupéré et contient toutes les données
    """
    # Mock get_trust_manager() pour utiliser notre manager réel
    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager_real):
        # Fonction décorée
        @friday_action(module="email", action="classify", trust_default="auto")
        async def classify_email_e2e(**kwargs: Any) -> ActionResult:
            return ActionResult(
                input_summary="Email de test@example.com: Test subject E2E",
                output_summary="→ Category: urgent (E2E test)",
                confidence=0.95,
                reasoning="Test E2E complet décorateur → receipt → SELECT",
                payload={"category": "urgent", "test": "e2e"},
            )

        # Exécuter l'action décorée
        result = await classify_email_e2e()

        # Vérifier que result est OK
        assert result.module == "email"
        assert result.action_type == "classify"
        assert result.trust_level == "auto"
        assert result.status == "auto"
        assert result.confidence == 0.95

        # Récupérer le receipt depuis la DB
        async with db_pool.acquire() as conn:
            receipt = await conn.fetchrow(
                "SELECT * FROM core.action_receipts ORDER BY created_at DESC LIMIT 1"
            )

        # Vérifier le receipt
        assert receipt is not None
        assert receipt["module"] == "email"
        assert receipt["action_type"] == "classify"
        assert receipt["input_summary"] == "Email de test@example.com: Test subject E2E"
        assert receipt["confidence"] == 0.95
        assert receipt["trust_level"] == "auto"
        assert receipt["status"] == "auto"
        assert receipt["payload"]["category"] == "urgent"
        assert receipt["payload"]["test"] == "e2e"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_correction_rules_applied(
    db_pool: asyncpg.Pool, trust_manager_real: TrustManager, load_fixtures, clean_tables
):
    """
    Test : Correction rules chargées et appliquées correctement.

    Vérifie que :
    1. Les fixtures SQL sont chargées
    2. load_correction_rules() retourne les règles actives
    3. Les règles sont triées par priorité
    4. format_rules_for_prompt() génère du texte injecté
    """
    # Charger les correction_rules du module email
    rules = await trust_manager_real.load_correction_rules("email", "classify")

    # Vérifier que les règles sont chargées (3 rules email.classify dans fixtures)
    assert len(rules) >= 2
    assert all(rule.module == "email" for rule in rules)
    assert all(rule.action_type == "classify" for rule in rules)

    # Vérifier tri par priorité (1=max priorité en premier)
    assert rules[0].priority == 1
    assert rules[1].priority == 2

    # Vérifier format pour prompt
    prompt = trust_manager_real.format_rules_for_prompt(rules)
    assert "RÈGLES DE CORRECTION PRIORITAIRES" in prompt
    assert "[Règle priorité 1]" in prompt
    assert "classification" in prompt


@pytest.mark.asyncio
@pytest.mark.integration
async def test_trust_level_auto_executes(
    db_pool: asyncpg.Pool, trust_manager_real: TrustManager, clean_tables
):
    """
    Test : Trust level 'auto' exécute l'action + crée receipt status='auto'.

    Vérifie que :
    1. L'action est exécutée automatiquement
    2. Le receipt a status='auto'
    3. Aucune attente de validation
    """
    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager_real):
        @friday_action(module="email", action="classify", trust_default="auto")
        async def auto_action(**kwargs: Any) -> ActionResult:
            return ActionResult(
                input_summary="Email test auto execution",
                output_summary="→ Action auto exécutée immédiatement",
                confidence=0.92,
                reasoning="Test trust level auto execution automatique",
            )

        result = await auto_action()

        # Vérifier l'exécution
        assert result.status == "auto"
        assert result.trust_level == "auto"

        # Vérifier receipt dans DB
        async with db_pool.acquire() as conn:
            receipt = await conn.fetchrow(
                "SELECT * FROM core.action_receipts WHERE id = $1",
                result.action_id,
            )

        assert receipt["status"] == "auto"
        assert receipt["trust_level"] == "auto"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_trust_level_propose_waits(
    db_pool: asyncpg.Pool, trust_manager_real: TrustManager, clean_tables
):
    """
    Test : Trust level 'propose' crée receipt status='pending'.

    Vérifie que :
    1. L'action est préparée mais pas exécutée
    2. Le receipt a status='pending'
    3. Attend validation Telegram (inline buttons)
    """
    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager_real):
        @friday_action(module="email", action="draft", trust_default="propose")
        async def propose_action(**kwargs: Any) -> ActionResult:
            return ActionResult(
                input_summary="Email test propose validation",
                output_summary="→ Brouillon email créé, attend validation",
                confidence=0.85,
                reasoning="Test trust level propose nécessite validation Telegram",
            )

        result = await propose_action()

        # Vérifier l'exécution
        assert result.status == "pending"
        assert result.trust_level == "propose"

        # Vérifier receipt dans DB
        async with db_pool.acquire() as conn:
            receipt = await conn.fetchrow(
                "SELECT * FROM core.action_receipts WHERE id = $1",
                result.action_id,
            )

        assert receipt["status"] == "pending"
        assert receipt["trust_level"] == "propose"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_trust_level_blocked_no_action(
    db_pool: asyncpg.Pool, trust_manager_real: TrustManager, clean_tables
):
    """
    Test : Trust level 'blocked' crée receipt status='blocked' (analyse seule).

    Vérifie que :
    1. L'action est analysée uniquement
    2. Le receipt a status='blocked'
    3. Aucune action exécutée (analyse seule pour données sensibles)
    """
    with patch("agents.src.middleware.trust.get_trust_manager", return_value=trust_manager_real):
        @friday_action(module="email", action="send", trust_default="blocked")
        async def blocked_action(**kwargs: Any) -> ActionResult:
            return ActionResult(
                input_summary="Email médical sensible test blocked",
                output_summary="→ Analyse seule, aucune action effectuée",
                confidence=0.90,
                reasoning="Test trust level blocked pour données médicales sensibles",
            )

        result = await blocked_action()

        # Vérifier l'exécution
        assert result.status == "blocked"
        assert result.trust_level == "blocked"

        # Vérifier receipt dans DB
        async with db_pool.acquire() as conn:
            receipt = await conn.fetchrow(
                "SELECT * FROM core.action_receipts WHERE id = $1",
                result.action_id,
            )

        assert receipt["status"] == "blocked"
        assert receipt["trust_level"] == "blocked"


# ==========================================
# Tests feedback loop (bonus)
# ==========================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_feedback_loop_correction_to_rule(
    db_pool: asyncpg.Pool, trust_manager_real: TrustManager, clean_tables
):
    """
    Test : Feedback loop complet correction → règle créée → règle appliquée.

    Vérifie que :
    1. Antonio peut créer une correction_rule manuellement
    2. La règle est chargée au prochain appel
    3. La règle est injectée dans le prompt (_rules_prompt)
    """
    # 1. Créer une nouvelle correction_rule
    new_rule_id = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.correction_rules (
                id, module, action_type, scope, priority, conditions, output,
                source_receipts, hit_count, active, created_at, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            new_rule_id,
            "email",
            "classify",
            "test-feedback",
            10,  # Basse priorité
            {"test": "feedback_loop"},
            {"category": "test_rule"},
            [],
            0,
            True,
            datetime.now(UTC),
            "Antonio",
        )

    # 2. Charger les règles
    rules = await trust_manager_real.load_correction_rules("email", "classify")

    # Vérifier que la nouvelle règle est présente
    assert any(rule.id == new_rule_id for rule in rules)

    # 3. Vérifier que format_rules_for_prompt() inclut la règle
    prompt = trust_manager_real.format_rules_for_prompt(rules)
    assert "test-feedback" in prompt
    assert "[Règle priorité 10]" in prompt
