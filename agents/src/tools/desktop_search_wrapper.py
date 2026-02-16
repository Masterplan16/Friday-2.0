#!/usr/bin/env python3
"""
Friday 2.0 - Desktop Search Wrapper via Claude Code CLI (Story 3.3 - Task 6)

Wrapper leger pour invoquer Claude Code CLI sur PC Mainteneur.

Architecture (D23):
    Telegram /search -> VPS -> Redis Streams search.requested ->
    PC Mainteneur -> Claude Code CLI (prompt mode) ->
    Redis Streams search.completed -> Telegram response

Phase 1 (MVP): Claude CLI sur PC Mainteneur (disponibilite 8h-22h)
Phase 2 (Future): Migration vers NAS Synology DS725+ (24/7)

Date: 2026-02-16
Story: 3.3 - Task 6
"""

import asyncio
import json
import os
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ============================================================
# Constants
# ============================================================

CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")
SEARCH_BASE_PATH = os.getenv(
    "SEARCH_BASE_PATH",
    r"C:\Users\lopez\BeeStation\Friday\Archives",
)
TIMEOUT_SECONDS = int(os.getenv("DESKTOP_SEARCH_TIMEOUT", "30"))


# ============================================================
# Desktop Search Wrapper
# ============================================================


async def search_desktop(
    query: str,
    base_path: str = SEARCH_BASE_PATH,
    max_results: int = 5,
) -> list[dict]:
    """
    Recherche documents via Claude Code CLI en mode prompt (Task 6.3).

    Claude Code CLI est invoque avec --print (non-interactif)
    et un prompt qui demande de chercher dans le dossier cible.

    Args:
        query: Query anonymisee (Presidio deja applique)
        base_path: Chemin base recherche (default Archives)
        max_results: Nombre max resultats

    Returns:
        Liste resultats [{path, title, excerpt, score}]

    Raises:
        FileNotFoundError: Si Claude CLI indisponible
        TimeoutError: Si timeout
    """
    logger.info(
        "Invoking Claude Code CLI for desktop search",
        query=query,
        base_path=base_path,
    )

    # Verifier Claude CLI disponible (async)
    if not await _is_claude_cli_available():
        raise FileNotFoundError(
            "Claude Code CLI not found. Install: npm install -g @anthropic-ai/claude-code"
        )

    # Construire prompt pour Claude CLI (mode --print, non-interactif)
    search_prompt = (
        f"Search for files matching this query in {base_path}: '{query}'. "
        f"Return top {max_results} results as a JSON array with fields: "
        f"path, title (filename), excerpt (first 200 chars of content), "
        f"score (relevance 0-1). Output ONLY the JSON array, no explanation."
    )

    cmd = [
        CLAUDE_CLI_PATH,
        "--print",  # Non-interactif, stdout seulement
        "--output-format", "json",
        search_prompt,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=base_path,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            process.kill()
            raise TimeoutError(
                f"Claude CLI search timeout after {TIMEOUT_SECONDS}s"
            )

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Claude CLI failed (rc={process.returncode}): {error_msg}")

        # Parse resultats JSON (Task 6.4)
        raw_output = stdout.decode().strip()
        results = _parse_cli_output(raw_output, max_results)

        logger.info(
            "Claude CLI search completed",
            results_count=len(results),
        )

        return results

    except FileNotFoundError:
        logger.warning("Claude CLI unavailable, falling back to pgvector only")
        raise

    except TimeoutError:
        logger.warning(
            "Claude CLI timeout",
            timeout_seconds=TIMEOUT_SECONDS,
        )
        raise

    except Exception as e:
        logger.error("Desktop search failed", query=query, error=str(e))
        raise


def _parse_cli_output(raw_output: str, max_results: int) -> list[dict]:
    """
    Parse la sortie Claude CLI en liste de resultats.

    Tente JSON direct, sinon extrait le bloc JSON du texte.
    """
    try:
        data = json.loads(raw_output)
        if isinstance(data, list):
            return data[:max_results]
        # Si output est un objet avec une cle "result"
        if isinstance(data, dict) and "result" in data:
            result_text = data["result"]
            # Tenter de parser le texte du result comme JSON
            return json.loads(result_text)[:max_results]
        return []
    except (json.JSONDecodeError, TypeError):
        # Tenter d'extraire un bloc JSON du texte
        start = raw_output.find("[")
        end = raw_output.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw_output[start : end + 1])[:max_results]
            except json.JSONDecodeError:
                pass
        logger.warning(
            "Failed to parse CLI output as JSON",
            output_length=len(raw_output),
        )
        return []


async def _is_claude_cli_available() -> bool:
    """Verifie si Claude Code CLI est disponible (async, non-bloquant)."""
    try:
        process = await asyncio.create_subprocess_exec(
            CLAUDE_CLI_PATH, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=5)
        return process.returncode == 0
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return False
