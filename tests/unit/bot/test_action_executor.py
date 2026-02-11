"""
Tests unitaires pour bot/action_executor.py (Story 1.10, Task 3).

Teste l'execution securisee des actions approuvees.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.action_executor import ALLOWED_MODULES, ActionExecutor
from tests.conftest import create_mock_pool_with_conn


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg Pool."""
    conn = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    conn.fetchrow = AsyncMock(
        return_value={
            "id": "abc123",
            "status": "approved",
            "module": "email",
            "action_type": "classify",
            "payload": '{"action_func": "email.classify", "args": {}}',
        }
    )
    pool = create_mock_pool_with_conn(conn)
    return pool


@pytest.fixture
def executor(mock_db_pool):
    """Instance ActionExecutor pour tests."""
    return ActionExecutor(mock_db_pool)


@pytest.mark.asyncio
async def test_execute_action_success(executor, mock_db_pool):
    """
    Test Task 3.1: Action executee avec succes -> status='executed'.
    """
    # Enregistrer une action dans la whitelist
    mock_action = AsyncMock()
    executor.register_action("email.classify", mock_action)

    result = await executor.execute("abc123")
    assert result is True

    # H2 fix: Verifier status='executed' (pas 'auto')
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    calls = conn.execute.call_args_list
    success_call = [c for c in calls if "status = 'executed'" in str(c)]
    assert len(success_call) > 0


@pytest.mark.asyncio
async def test_execute_action_failure(executor, mock_db_pool):
    """
    Test Task 3.2: Erreur action -> status='error', alerte.
    """
    # Simuler une action qui echoue
    executor.register_action("email.classify", AsyncMock(side_effect=ValueError("test error")))

    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    result = await executor.execute("abc123")

    assert result is False

    # Verifier UPDATE status='error' avec COALESCE (H1 fix)
    calls = conn.execute.call_args_list
    error_call = [c for c in calls if "status = 'error'" in str(c)]
    assert len(error_call) > 0
    # H1 fix: Verifier COALESCE present
    error_sql = str(error_call[0])
    assert "COALESCE" in error_sql


@pytest.mark.asyncio
async def test_execute_prevents_double_execution(executor, mock_db_pool):
    """
    Test BUG-1.10.10: 2e appel execute() -> pas de double execution.
    """
    executor.register_action("email.classify", AsyncMock())

    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    # Premier appel: status='approved' -> execution OK
    conn.fetchrow.return_value = {
        "id": "abc123",
        "status": "approved",
        "module": "email",
        "action_type": "classify",
        "payload": '{"action_func": "email.classify", "args": {}}',
    }
    result1 = await executor.execute("abc123")
    assert result1 is True

    # Deuxieme appel: status='executed' (deja fait)
    conn.fetchrow.return_value = {
        "id": "abc123",
        "status": "executed",  # H2 fix: 'executed' pas 'auto'
        "module": "email",
        "action_type": "classify",
        "payload": "{}",
    }
    result2 = await executor.execute("abc123")
    assert result2 is False


@pytest.mark.asyncio
async def test_execute_unknown_module_not_in_whitelist(executor, mock_db_pool):
    """
    Test C3 fix: Module inconnu ET pas dans whitelist -> erreur.
    """
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "id": "abc123",
        "status": "approved",
        "module": "unknown_module",
        "action_type": "unknown_action",
        "payload": '{"action_func": "unknown_module.unknown_action", "args": {}}',
    }

    result = await executor.execute("abc123")
    assert result is False


@pytest.mark.asyncio
async def test_execute_whitelist_not_bypassed_by_registry(executor, mock_db_pool):
    """
    Test C3 fix: Meme si action enregistree, elle doit etre dans la whitelist.
    """
    # Enregistrer une action qui n'est PAS dans ALLOWED_MODULES
    executor.register_action("malicious.inject", AsyncMock())

    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = {
        "id": "abc123",
        "status": "approved",
        "module": "malicious",
        "action_type": "inject",
        "payload": '{}',
    }

    result = await executor.execute("abc123")
    assert result is False  # C3: Whitelist bloque meme si dans registry


@pytest.mark.asyncio
async def test_execute_receipt_not_found(executor, mock_db_pool):
    """
    Test: Receipt introuvable -> False.
    """
    conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow.return_value = None

    result = await executor.execute("nonexistent")
    assert result is False
