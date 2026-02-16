"""
Test E2E detection VIP & Urgence (Story 2.3 - AC5 CRITIQUE).

Valide le pipeline complet avec dataset 31 emails.

Acceptance Criteria AC5 :
- 100% recall urgence (5/5 emails urgents detectes)
- Faux positifs <10% (max 3/26 normaux classes urgents)
- Latence detection <1s par email
"""

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agents.src.agents.email.urgency_detector import detect_urgency
from agents.src.agents.email.vip_detector import compute_email_hash, detect_vip_sender

# ==========================================
# Fixtures
# ==========================================


@pytest.fixture(scope="module")
def dataset():
    """Charge le dataset 30 emails de test."""
    dataset_path = Path(__file__).parent.parent.parent / "fixtures" / "vip_urgency_dataset.json"
    with open(dataset_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def vip_hashes(dataset):
    """Cree un dictionnaire email -> hash pour les VIP du dataset."""
    vip_emails = {}
    for email in dataset["emails"]:
        if email["expected_vip"]:
            email_hash = compute_email_hash(email["from"])
            vip_emails[email["from"]] = {
                "hash": email_hash,
                "label": email.get("vip_label"),
            }
    return vip_emails


class MockPoolVIPDataset:
    """Mock pool qui simule la DB avec les VIP du dataset."""

    def __init__(self, vip_hashes):
        self.vip_hashes = vip_hashes
        # Map hash -> VIP data
        self.hash_to_vip = {v["hash"]: k for k, v in vip_hashes.items()}

    async def fetchrow(self, query, email_hash):
        """Mock fetchrow pour detect_vip_sender."""
        # Chercher si ce hash correspond a un VIP
        if email_hash in self.hash_to_vip:
            email_from = self.hash_to_vip[email_hash]
            vip_data = self.vip_hashes[email_from]
            return {
                "id": "00000000-0000-0000-0000-000000000000",
                "email_anon": f"[EMAIL_VIP_{email_hash[:8]}]",
                "email_hash": email_hash,
                "label": vip_data["label"],
                "priority_override": None,
                "designation_source": "manual",
                "added_by": None,
                "emails_received_count": 0,
                "active": True,
            }
        return None


class MockPoolKeywordsDataset:
    """Mock pool avec keywords urgence du dataset."""

    def __init__(self):
        self.keywords = [
            {"keyword": "URGENT", "weight": 0.5},
            {"keyword": "urgent", "weight": 0.5},
            {"keyword": "deadline", "weight": 0.3},
            {"keyword": "délai", "weight": 0.3},
            {"keyword": "échéance", "weight": 0.3},
        ]
        self.mock_conn = AsyncMock()
        self.mock_conn.fetch.return_value = self.keywords

    @asynccontextmanager
    async def acquire(self):
        """Mock acquire pour context manager."""
        yield self.mock_conn


# ==========================================
# Tests E2E
# ==========================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_vip_detection_e2e_recall(dataset, vip_hashes):
    """
    AC5.1: Test recall VIP - tous les VIP du dataset doivent etre detectes.

    Expected: 11 VIP dans dataset -> 11 detectes (100% recall)
    """
    mock_pool = MockPoolVIPDataset(vip_hashes)

    vip_detected_count = 0
    vip_missed = []

    for email in dataset["emails"]:
        email_hash = compute_email_hash(email["from"])
        result = await detect_vip_sender(
            email_anon=f"[EMAIL_{email['id']}]",
            email_hash=email_hash,
            db_pool=mock_pool,
        )

        is_vip = result.payload["is_vip"]

        if email["expected_vip"]:
            if is_vip:
                vip_detected_count += 1
            else:
                vip_missed.append(email["id"])

    # Assertions
    expected_vip_count = dataset["metadata"]["expected_vip_count"]
    assert (
        vip_detected_count == expected_vip_count
    ), f"VIP recall failed: {vip_detected_count}/{expected_vip_count} detected. Missed: {vip_missed}"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_urgency_detection_e2e_recall(dataset, vip_hashes):
    """
    AC5.2: Test recall urgence - 100% des emails urgents doivent etre detectes.

    Expected: 5 emails urgents -> 5 detectes (100% recall)
    """
    mock_pool_vip = MockPoolVIPDataset(vip_hashes)
    mock_pool_keywords = MockPoolKeywordsDataset()

    urgent_detected_count = 0
    urgent_missed = []
    latencies = []

    for email in dataset["emails"]:
        start_time = time.time()

        # Phase 1: Detection VIP
        email_hash = compute_email_hash(email["from"])
        vip_result = await detect_vip_sender(
            email_anon=f"[EMAIL_{email['id']}]",
            email_hash=email_hash,
            db_pool=mock_pool_vip,
        )
        is_vip = vip_result.payload["is_vip"]

        # Phase 2: Detection urgence
        email_text = f"{email['subject']} {email['body']}"
        urgency_result = await detect_urgency(
            email_text=email_text,
            vip_status=is_vip,
            db_pool=mock_pool_keywords,
        )
        is_urgent = urgency_result.payload["is_urgent"]

        latency_ms = (time.time() - start_time) * 1000
        latencies.append(latency_ms)

        if email["expected_urgent"]:
            if is_urgent:
                urgent_detected_count += 1
            else:
                urgent_missed.append(
                    {
                        "id": email["id"],
                        "score": urgency_result.confidence,
                        "factors": email.get("urgency_factors", []),
                    }
                )

    # Assertions AC5.2
    expected_urgent_count = dataset["metadata"]["expected_urgent_count"]
    assert (
        urgent_detected_count == expected_urgent_count
    ), f"Urgency recall FAILED (AC5.2): {urgent_detected_count}/{expected_urgent_count} detected. Missed: {urgent_missed}"

    # Assertion latence <1s par email
    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)
    assert max_latency < 1000, f"Latency FAILED: max={max_latency:.2f}ms (seuil=1000ms)"
    assert avg_latency < 500, f"Avg latency high: {avg_latency:.2f}ms (target <500ms)"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_urgency_detection_e2e_precision(dataset, vip_hashes):
    """
    AC5.3: Test precision urgence - faux positifs <10%.

    Expected: Max 2/20 emails normaux classes urgents (90% precision)
    """
    mock_pool_vip = MockPoolVIPDataset(vip_hashes)
    mock_pool_keywords = MockPoolKeywordsDataset()

    false_positives = []

    for email in dataset["emails"]:
        # Phase 1: Detection VIP
        email_hash = compute_email_hash(email["from"])
        vip_result = await detect_vip_sender(
            email_anon=f"[EMAIL_{email['id']}]",
            email_hash=email_hash,
            db_pool=mock_pool_vip,
        )
        is_vip = vip_result.payload["is_vip"]

        # Phase 2: Detection urgence
        email_text = f"{email['subject']} {email['body']}"
        urgency_result = await detect_urgency(
            email_text=email_text,
            vip_status=is_vip,
            db_pool=mock_pool_keywords,
        )
        is_urgent = urgency_result.payload["is_urgent"]

        # Detecter faux positifs (detecte urgent mais pas vraiment urgent)
        if not email["expected_urgent"] and is_urgent:
            false_positives.append(
                {
                    "id": email["id"],
                    "score": urgency_result.confidence,
                    "reasoning": urgency_result.reasoning,
                }
            )

    # Assertions AC5.3
    # Total emails non-urgents = 30 - 5 urgents = 25
    non_urgent_count = len(dataset["emails"]) - dataset["metadata"]["expected_urgent_count"]
    false_positive_rate = len(false_positives) / non_urgent_count

    assert (
        false_positive_rate < 0.10
    ), f"Precision FAILED (AC5.3): {len(false_positives)}/{non_urgent_count} faux positifs ({false_positive_rate:.1%}). Details: {false_positives}"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_edge_cases_handling(dataset, vip_hashes):
    """
    AC5.4: Test gestion edge cases.

    Verifie comportement sur cas limites :
    - VIP avec contenu spam
    - Urgence ambigue
    - Faux VIP (phishing)
    - Multi keywords spam
    """
    mock_pool_vip = MockPoolVIPDataset(vip_hashes)
    mock_pool_keywords = MockPoolKeywordsDataset()

    edge_cases = [e for e in dataset["emails"] if e["id"].startswith("edge_")]

    results = []
    for email in edge_cases:
        # Phase 1: Detection VIP
        email_hash = compute_email_hash(email["from"])
        vip_result = await detect_vip_sender(
            email_anon=f"[EMAIL_{email['id']}]",
            email_hash=email_hash,
            db_pool=mock_pool_vip,
        )
        is_vip = vip_result.payload["is_vip"]

        # Phase 2: Detection urgence
        email_text = f"{email['subject']} {email['body']}"
        urgency_result = await detect_urgency(
            email_text=email_text,
            vip_status=is_vip,
            db_pool=mock_pool_keywords,
        )
        is_urgent = urgency_result.payload["is_urgent"]

        results.append(
            {
                "id": email["id"],
                "expected_vip": email["expected_vip"],
                "detected_vip": is_vip,
                "expected_urgent": email["expected_urgent"],
                "detected_urgent": is_urgent,
                "urgency_score": urgency_result.confidence,
                "note": email.get("note", ""),
            }
        )

    # Assertions edge cases
    assert len(results) == 6, f"Expected 6 edge cases, got {len(results)}"

    # edge_vip_spam: VIP mais pas urgent malgre keywords spam
    edge_vip_spam = next(r for r in results if r["id"] == "edge_vip_spam")
    assert edge_vip_spam["detected_vip"] is True, "edge_vip_spam: VIP non detecte"
    assert edge_vip_spam["detected_urgent"] is False, "edge_vip_spam: detecte urgent a tort"

    # edge_faux_vip: Pas VIP (email different)
    edge_faux_vip = next(r for r in results if r["id"] == "edge_faux_vip")
    assert edge_faux_vip["detected_vip"] is False, "edge_faux_vip: VIP detecte a tort"

    # edge_multi_keywords: Multi keywords mais score <0.6
    edge_multi = next(r for r in results if r["id"] == "edge_multi_keywords")
    assert (
        edge_multi["urgency_score"] < 0.6
    ), f"edge_multi_keywords: score trop eleve {edge_multi['urgency_score']}"


@pytest.mark.e2e
def test_dataset_integrity(dataset):
    """
    AC5.5: Valide l'integrite du dataset.

    Verifie que le dataset contient bien 30 emails avec la bonne repartition.
    """
    emails = dataset["emails"]
    metadata = dataset["metadata"]

    # Verifier total count
    assert len(emails) == 31, f"Expected 31 emails, got {len(emails)}"
    assert metadata["total_count"] == 31

    # Verifier repartition (excluding edges pour eviter double comptage)
    vip_non_urgent = sum(
        1
        for e in emails
        if e["expected_vip"] and not e["expected_urgent"] and not e["id"].startswith("edge_")
    )
    vip_urgent = sum(
        1
        for e in emails
        if e["expected_vip"] and e["expected_urgent"] and not e["id"].startswith("edge_")
    )
    non_vip_urgent = sum(
        1
        for e in emails
        if not e["expected_vip"] and e.get("urgency_factors") and not e["id"].startswith("edge_")
    )
    normal = sum(
        1
        for e in emails
        if not e["expected_vip"]
        and not e["expected_urgent"]
        and not e.get("urgency_factors")
        and not e["id"].startswith("edge_")
    )
    edge = sum(1 for e in emails if e["id"].startswith("edge_"))

    assert vip_non_urgent == 5, f"Expected 5 vip_non_urgent, got {vip_non_urgent}"
    assert vip_urgent == 5, f"Expected 5 vip_urgent, got {vip_urgent}"
    assert non_vip_urgent == 5, f"Expected 5 non_vip_urgent, got {non_vip_urgent}"
    assert normal == 10, f"Expected 10 normal, got {normal}"
    assert edge == 6, f"Expected 6 edge cases, got {edge}"

    # Verifier champs obligatoires
    for email in emails:
        assert "id" in email
        assert "from" in email
        assert "subject" in email
        assert "body" in email
        assert "expected_vip" in email
        assert "expected_urgent" in email
