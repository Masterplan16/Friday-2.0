#!/usr/bin/env python3
"""
Tests unitaires desktop_search_wrapper + desktop_search_consumer (Story 3.3 - Task 6.7).

Tests:
- Wrapper: invoke CLI success, parse results, fallback, timeout, CLI unavailable
- Consumer: process search request, publish completed, ACK, empty query, failures

Date: 2026-02-16
Story: 3.3 - Task 6.7
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.src.tools.desktop_search_consumer import DesktopSearchConsumer
from agents.src.tools.desktop_search_wrapper import (
    _is_claude_cli_available,
    _parse_cli_output,
    search_desktop,
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_redis():
    """Redis client mock."""
    redis = AsyncMock()
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xadd = AsyncMock(return_value=b"1234567890-0")
    redis.xack = AsyncMock()
    redis.xgroup_create = AsyncMock()
    return redis


@pytest.fixture
def consumer(mock_redis):
    """DesktopSearchConsumer instance with mock Redis."""
    return DesktopSearchConsumer(redis_client=mock_redis)


@pytest.fixture
def sample_cli_results():
    """Sample Claude CLI search results."""
    return [
        {
            "path": r"C:\Users\lopez\BeeStation\Friday\Archives\finance\facture.pdf",
            "title": "facture.pdf",
            "excerpt": "Facture plombier intervention fevrier 2026",
            "score": 0.92,
        },
        {
            "path": r"C:\Users\lopez\BeeStation\Friday\Archives\pro\devis.pdf",
            "title": "devis.pdf",
            "excerpt": "Devis travaux bureau",
            "score": 0.78,
        },
    ]


# ============================================================
# Tests: _parse_cli_output
# ============================================================


def test_parse_cli_output_valid_json_array(sample_cli_results):
    """Parse une sortie CLI JSON array valide."""
    raw = json.dumps(sample_cli_results)
    results = _parse_cli_output(raw, max_results=5)
    assert len(results) == 2
    assert results[0]["title"] == "facture.pdf"


def test_parse_cli_output_wrapped_in_result_key(sample_cli_results):
    """Parse une sortie CLI wrappee dans {"result": "..."}."""
    inner = json.dumps(sample_cli_results)
    raw = json.dumps({"result": inner})
    results = _parse_cli_output(raw, max_results=5)
    assert len(results) == 2


def test_parse_cli_output_embedded_json(sample_cli_results):
    """Parse JSON embede dans du texte."""
    raw = "Here are the results:\n" + json.dumps(sample_cli_results) + "\nDone."
    results = _parse_cli_output(raw, max_results=5)
    assert len(results) == 2


def test_parse_cli_output_invalid():
    """Retourne liste vide pour sortie non-parsable."""
    results = _parse_cli_output("Not JSON at all", max_results=5)
    assert results == []


def test_parse_cli_output_respects_max_results(sample_cli_results):
    """Limite le nombre de resultats."""
    raw = json.dumps(sample_cli_results)
    results = _parse_cli_output(raw, max_results=1)
    assert len(results) == 1


# ============================================================
# Tests: search_desktop
# ============================================================


@pytest.mark.asyncio
async def test_search_desktop_success(sample_cli_results):
    """Recherche desktop reussie via Claude CLI."""
    stdout = json.dumps(sample_cli_results).encode()

    with patch(
        "agents.src.tools.desktop_search_wrapper._is_claude_cli_available",
        return_value=True,
    ):
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(stdout, b""))
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            results = await search_desktop(query="facture plombier")
            assert len(results) == 2
            assert results[0]["title"] == "facture.pdf"


@pytest.mark.asyncio
async def test_search_desktop_cli_unavailable():
    """FileNotFoundError si Claude CLI indisponible."""
    with patch(
        "agents.src.tools.desktop_search_wrapper._is_claude_cli_available",
        return_value=False,
    ):
        with pytest.raises(FileNotFoundError, match="Claude Code CLI not found"):
            await search_desktop(query="test")


@pytest.mark.asyncio
async def test_search_desktop_timeout():
    """TimeoutError si Claude CLI depasse timeout."""
    import asyncio

    with patch(
        "agents.src.tools.desktop_search_wrapper._is_claude_cli_available",
        return_value=True,
    ):
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_process.kill = MagicMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(TimeoutError, match="timeout"):
                await search_desktop(query="test")


@pytest.mark.asyncio
async def test_search_desktop_cli_error():
    """RuntimeError si Claude CLI retourne un code erreur."""
    with patch(
        "agents.src.tools.desktop_search_wrapper._is_claude_cli_available",
        return_value=True,
    ):
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"", b"Error: auth failed"))
        mock_process.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(RuntimeError, match="Claude CLI failed"):
                await search_desktop(query="test")


@pytest.mark.asyncio
async def test_is_claude_cli_available_true():
    """Claude CLI disponible."""
    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"1.0.0", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        assert await _is_claude_cli_available() is True


@pytest.mark.asyncio
async def test_is_claude_cli_available_false():
    """Claude CLI indisponible."""
    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError,
    ):
        assert await _is_claude_cli_available() is False


# ============================================================
# Tests: DesktopSearchConsumer
# ============================================================


@pytest.mark.asyncio
async def test_consumer_process_search_request(consumer, mock_redis, sample_cli_results):
    """Consumer traite un search.requested et publie search.completed."""
    data = {
        b"query": b"facture plombier",
        b"request_id": b"req-123",
        b"max_results": b"5",
    }

    with patch(
        "agents.src.tools.desktop_search_consumer.search_desktop",
        return_value=sample_cli_results,
    ):
        await consumer._process_search_request(
            message_id="msg-001",
            data=data,
        )

    # Verifie publish search.completed
    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    assert call_args.kwargs["name"] == "search.completed"
    fields = call_args.kwargs["fields"]
    assert fields["request_id"] == "req-123"
    assert fields["results_count"] == "2"

    # Verifie ACK
    mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
async def test_consumer_empty_query(consumer, mock_redis):
    """Consumer ignore les requetes sans query."""
    data = {b"request_id": b"req-456"}

    await consumer._process_search_request(
        message_id="msg-002",
        data=data,
    )

    # ACK mais pas de publish
    mock_redis.xack.assert_called_once()
    mock_redis.xadd.assert_not_called()


@pytest.mark.asyncio
async def test_consumer_cli_unavailable_publishes_empty(consumer, mock_redis):
    """Consumer publie resultats vides si Claude CLI indisponible."""
    data = {b"query": b"test query", b"request_id": b"req-789"}

    with patch(
        "agents.src.tools.desktop_search_consumer.search_desktop",
        side_effect=FileNotFoundError("CLI not found"),
    ):
        await consumer._process_search_request(
            message_id="msg-003",
            data=data,
        )

    # Publie quand meme avec results vides
    mock_redis.xadd.assert_called_once()
    fields = mock_redis.xadd.call_args.kwargs["fields"]
    assert fields["results_count"] == "0"
    assert json.loads(fields["results"]) == []


@pytest.mark.asyncio
async def test_consumer_consecutive_failures(consumer, mock_redis):
    """Consumer incremente failures sur exception non-geree."""
    data = {b"query": b"test", b"request_id": b"req-999"}

    with patch(
        "agents.src.tools.desktop_search_consumer.search_desktop",
        side_effect=RuntimeError("unexpected error"),
    ):
        await consumer._process_search_request(
            message_id="msg-004",
            data=data,
        )

    assert consumer.consecutive_failures == 1
