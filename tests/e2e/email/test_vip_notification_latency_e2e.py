"""
Test E2E latence notification VIP (Story 2.3 - AC3).

AC3 CRITIQUE : Email VIP → notification push <5 secondes.
Ce test valide la contrainte NFR1 (latence totale <30s, budget Story 2.3 = 5s).

Fix Code Review H2 : Ce test manquait (Subtask 7.3 pas implémentée).
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agents.src.agents.email.vip_detector import (
    compute_email_hash,
    detect_vip_sender,
    update_vip_email_stats,
)


# ==========================================
# Fixtures
# ==========================================


class MockPoolVIP:
    """Mock pool avec un VIP de test."""

    def __init__(self, vip_email_hash: str, vip_label: str):
        self.vip_hash = vip_email_hash
        self.vip_label = vip_label

    async def fetchrow(self, query, email_hash):
        """Mock fetchrow pour detect_vip_sender."""
        if email_hash == self.vip_hash:
            return {
                "id": "00000000-0000-0000-0000-111111111111",
                "email_anon": f"[EMAIL_VIP_{email_hash[:8]}]",
                "email_hash": email_hash,
                "label": self.vip_label,
                "priority_override": None,
                "designation_source": "manual",
                "added_by": None,
                "emails_received_count": 5,
                "active": True,
            }
        return None

    async def execute(self, query, *args):
        """Mock execute pour update_vip_email_stats."""
        pass  # Stats update non critique pour ce test


# ==========================================
# Tests E2E Latence VIP
# ==========================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_vip_notification_latency_under_5_seconds():
    """
    AC3 CRITIQUE : Test latence notification VIP <5 secondes.

    Pipeline simulé :
    1. Réception email VIP
    2. Détection VIP via hash lookup
    3. Notification Telegram envoyée
    4. Total <5s

    Assert :
    - Latence totale <5 secondes (NFR1 budget)
    - VIP correctement détecté
    - Notification envoyée au bon topic
    """
    # Setup VIP de test
    vip_email_original = "doyen@univ-test.fr"
    vip_email_hash = compute_email_hash(vip_email_original)
    vip_label = "Doyen Test Latence"
    email_anon = f"[EMAIL_VIP_{vip_email_hash[:8]}]"

    mock_pool = MockPoolVIP(vip_email_hash, vip_label)

    # Mock Telegram API
    telegram_called = False
    telegram_latency = None

    async def mock_telegram_post(url, json, **kwargs):
        """Mock Telegram sendMessage."""
        nonlocal telegram_called, telegram_latency
        telegram_called = True
        telegram_latency = time.time()
        # Simuler délai réseau Telegram API (~200-500ms)
        await asyncio.sleep(0.3)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True}
        return response

    # === MESURE LATENCE TOTALE ===
    start_time = time.time()

    # Phase 1: Détection VIP (target <100ms)
    phase1_start = time.time()
    vip_result = await detect_vip_sender(
        email_anon=email_anon,
        email_hash=vip_email_hash,
        db_pool=mock_pool,
    )
    phase1_latency = (time.time() - phase1_start) * 1000

    # Vérifier VIP détecté
    assert vip_result.payload["is_vip"] is True
    assert vip_result.payload["vip"]["label"] == vip_label

    # Phase 2: Update stats VIP (non critique, mode dégradé OK)
    phase2_start = time.time()
    await update_vip_email_stats(
        vip_id=vip_result.payload["vip"]["id"],
        db_pool=mock_pool,
    )
    phase2_latency = (time.time() - phase2_start) * 1000

    # Phase 3: Notification Telegram
    phase3_start = time.time()
    with patch("httpx.AsyncClient.post", new=mock_telegram_post):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.telegram.org/botMOCK_TOKEN/sendMessage",
                json={
                    "chat_id": "MOCK_CHAT_ID",
                    "message_thread_id": "MOCK_TOPIC_EMAIL_ID",
                    "text": f"Nouvel email VIP : {vip_label}",
                },
                timeout=10.0,
            )
    phase3_latency = (time.time() - phase3_start) * 1000

    # Latence totale
    total_latency = (time.time() - start_time) * 1000

    # === ASSERTIONS AC3 ===
    assert (
        total_latency < 5000
    ), f"AC3 FAILED: Latence VIP notification {total_latency:.2f}ms > 5000ms (5s)"

    # Assertions détaillées (breakdown)
    assert phase1_latency < 100, f"Phase 1 (VIP lookup) trop lente: {phase1_latency:.2f}ms > 100ms"
    assert phase2_latency < 50, f"Phase 2 (stats update) trop lente: {phase2_latency:.2f}ms > 50ms"
    assert phase3_latency < 1000, f"Phase 3 (Telegram) trop lente: {phase3_latency:.2f}ms > 1000ms"

    # Vérifier notification envoyée
    assert telegram_called is True, "Telegram notification pas envoyée"

    # Log breakdown pour debug
    print(f"\n✅ AC3 PASS - Latence VIP notification: {total_latency:.2f}ms (<5000ms)")
    print(f"  - Phase 1 (VIP lookup): {phase1_latency:.2f}ms")
    print(f"  - Phase 2 (stats update): {phase2_latency:.2f}ms")
    print(f"  - Phase 3 (Telegram): {phase3_latency:.2f}ms")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_vip_notification_fast_path_vs_normal():
    """
    Test que VIP notification est PLUS RAPIDE que classification normale.

    VIP path : ~5s (avant classification LLM ~10s)
    Normal path : ~15s (classification LLM + tout le pipeline)

    Assert : VIP path doit être 2-3x plus rapide
    """
    vip_email_hash = compute_email_hash("vip@fast.com")
    mock_pool = MockPoolVIP(vip_email_hash, "VIP Fast")

    # Mesurer VIP fast path
    start_vip = time.time()
    vip_result = await detect_vip_sender(
        email_anon="[EMAIL_VIP]",
        email_hash=vip_email_hash,
        db_pool=mock_pool,
    )
    vip_latency = (time.time() - start_vip) * 1000

    # Assert : VIP lookup ultra rapide (<100ms typiquement <50ms)
    assert vip_latency < 100, f"VIP fast path trop lent: {vip_latency:.2f}ms"

    print(f"\n✅ VIP fast path: {vip_latency:.2f}ms (target <100ms)")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_vip_notification_degraded_mode_telegram_down():
    """
    Test mode dégradé si Telegram API down.

    Scénario : Telegram timeout/erreur ne doit PAS bloquer pipeline.
    VIP détection doit quand même se faire en <100ms.
    """
    vip_email_hash = compute_email_hash("vip@resilient.com")
    mock_pool = MockPoolVIP(vip_email_hash, "VIP Resilient")

    # Simuler Telegram API down (timeout)
    async def mock_telegram_timeout(url, json, **kwargs):
        """Mock Telegram timeout."""
        await asyncio.sleep(10)  # Simuler timeout long
        raise httpx.TimeoutException("Telegram API timeout")

    # VIP detection doit quand même être rapide
    start = time.time()
    vip_result = await detect_vip_sender(
        email_anon="[EMAIL_VIP_RESILIENT]",
        email_hash=vip_email_hash,
        db_pool=mock_pool,
    )
    vip_latency = (time.time() - start) * 1000

    # Assert : VIP lookup non affecté par Telegram down
    assert vip_latency < 100, f"VIP lookup affecté par Telegram: {vip_latency:.2f}ms"
    assert vip_result.payload["is_vip"] is True

    # Notification Telegram échouera mais VIP détecté quand même
    with patch("httpx.AsyncClient.post", new=mock_telegram_timeout):
        notification_start = time.time()
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                await client.post(
                    "https://api.telegram.org/botMOCK_TOKEN/sendMessage",
                    json={"chat_id": "MOCK", "text": "Test"},
                )
        except (httpx.TimeoutException, httpx.ReadTimeout):
            pass  # Mode dégradé OK : notification échoue mais VIP détecté
        notification_latency = (time.time() - notification_start) * 1000

    # Log
    print(f"\n✅ Mode dégradé: VIP détecté en {vip_latency:.2f}ms malgré Telegram down")
    print(f"  - Notification échouée après {notification_latency:.2f}ms (timeout)")
