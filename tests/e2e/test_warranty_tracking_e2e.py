"""
Tests E2E warranty tracking (Story 3.4).

7 tests couvrant le flux complet :
- Détection garantie depuis facture
- Alerte expiration 30 jours
- Alerte CRITICAL 7 jours (ignore quiet hours)
- False positive correction (Ignorer)
- Stats command
- Multiple warranties pipeline
- Latence <10s validation

Mock : Claude API, Presidio, PostgreSQL, Redis, Telegram.
JAMAIS d'appel LLM réel.
"""
import asyncio
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, ".")


class TestWarrantyTrackingE2E:
    """Tests E2E pipeline complet warranty."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_warranty_detection_from_receipt(
        self, mock_insert, mock_anonymize, mock_llm
    ):
        """E2E: PDF facture → extraction → PostgreSQL insert."""
        # Mock Presidio
        mock_anonymize.return_value = ("Facture Amazon HP Printer 149.99 EUR", {})

        # Mock Claude
        response = json.dumps({
            "warranty_detected": True,
            "item_name": "HP DeskJet 3720",
            "item_category": "electronics",
            "vendor": "Amazon",
            "purchase_date": "2025-06-15",
            "warranty_duration_months": 24,
            "purchase_amount": 149.99,
            "confidence": 0.92,
        })
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=response)
        mock_llm.return_value = mock_adapter

        # Mock DB
        warranty_id = str(uuid4())
        mock_insert.return_value = warranty_id

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(db_pool=AsyncMock())

        result = await orchestrator.process_document_for_warranty(
            document_id="pdf-001",
            ocr_text="Facture Amazon\nHP DeskJet 3720\nDate: 15/06/2025\nPrix: 149,99 EUR\nGarantie: 2 ans",
        )

        assert result.payload["warranty_detected"] is True
        assert result.payload["warranty_id"] == warranty_id
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_warranty_expiry_alert_30_days(self):
        """E2E: Warranty expiring 30j → Telegram notification."""
        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        with patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties") as mock_get, \
             patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent") as mock_check, \
             patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent") as mock_record, \
             patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired"):

            mock_get.return_value = [
                {"id": uuid4(), "item_name": "Camera Canon", "days_remaining": 25},
            ]
            mock_check.return_value = False

            result = await check_warranty_expiry(
                context={"hour": 10},
                db_pool=AsyncMock(),
            )

            assert result.notify is True
            assert "Camera Canon" in result.message
            assert "25 jours" in result.message
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_warranty_expiry_critical_7_days(self):
        """E2E: Warranty expiring 7j CRITICAL → ignore quiet hours."""
        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        with patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties") as mock_get, \
             patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent") as mock_check, \
             patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent") as mock_record, \
             patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired"):

            mock_get.return_value = [
                {"id": uuid4(), "item_name": "Expiring Printer", "days_remaining": 3},
            ]
            mock_check.return_value = False

            result = await check_warranty_expiry(
                context={"hour": 23},  # Quiet hours - but critical ignores
                db_pool=AsyncMock(),
            )

            assert result.notify is True
            assert "URGENT" in result.message
            assert "Expiring Printer" in result.message

    @pytest.mark.asyncio
    async def test_warranty_false_positive_correction(self):
        """E2E: User click Ignorer → delete warranty."""
        from agents.src.agents.archiviste.warranty_db import delete_warranty

        pool = AsyncMock()
        pool.execute = AsyncMock(return_value="DELETE 1")

        warranty_id = str(uuid4())
        result = await delete_warranty(pool, warranty_id)

        assert result is True
        pool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_warranty_stats_command_aggregation(self):
        """E2E: /warranty_stats → calculs agrégés corrects."""
        from agents.src.agents.archiviste.warranty_db import get_warranty_stats

        pool = AsyncMock()
        pool.fetchval = AsyncMock(side_effect=[
            8,                       # total_active
            3,                       # expired_12m
            Decimal("3245.50"),      # total_amount
        ])
        pool.fetchrow = AsyncMock(return_value={
            "item_name": "Printer HP",
            "expiration_date": date.today() + timedelta(days=15),
            "days_remaining": 15,
        })
        pool.fetch = AsyncMock(return_value=[
            {"item_category": "electronics", "count": 5, "total_amount": Decimal("2000")},
            {"item_category": "appliances", "count": 3, "total_amount": Decimal("1245.50")},
        ])

        stats = await get_warranty_stats(pool)

        assert stats["total_active"] == 8
        assert stats["expired_12m"] == 3
        assert stats["total_amount"] == Decimal("3245.50")
        assert stats["next_expiry"]["item_name"] == "Printer HP"
        assert stats["next_expiry"]["days_remaining"] == 15
        assert len(stats["by_category"]) == 2

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_pipeline_latency_under_10s(
        self, mock_insert, mock_anonymize, mock_llm
    ):
        """E2E: Pipeline complet <10s (timeout)."""
        import time

        mock_anonymize.return_value = ("Facture anonymisée", {})
        response = json.dumps({
            "warranty_detected": True,
            "item_name": "Test Product",
            "item_category": "electronics",
            "vendor": "TestVendor",
            "purchase_date": "2025-01-01",
            "warranty_duration_months": 12,
            "purchase_amount": 99.99,
            "confidence": 0.88,
        })
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=response)
        mock_llm.return_value = mock_adapter
        mock_insert.return_value = str(uuid4())

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(db_pool=AsyncMock())

        start = time.monotonic()
        result = await orchestrator.process_document_for_warranty(
            document_id="latency-test",
            ocr_text="Facture Test Product garantie 1 an",
        )
        elapsed = time.monotonic() - start

        assert result.payload["warranty_detected"] is True
        assert elapsed < 10.0  # Must complete under 10s
        assert result.payload.get("error") != "timeout"

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_extractor.get_llm_adapter")
    @patch("agents.src.agents.archiviste.warranty_extractor.anonymize_text")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_multiple_warranties_pipeline(
        self, mock_insert, mock_anonymize, mock_llm
    ):
        """E2E: Multiple documents → multiple warranties."""
        mock_anonymize.return_value = ("Facture anonymisée", {})
        mock_insert.return_value = str(uuid4())

        documents = [
            ("doc1", "Facture HP Printer 149€ garantie 2 ans", "HP Printer"),
            ("doc2", "Facture Bosch Lave-linge 549€ garantie 5 ans", "Bosch Lave-linge"),
            ("doc3", "Courrier simple sans garantie", None),
        ]

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        results = []
        for doc_id, ocr_text, expected_name in documents:
            if expected_name:
                response = json.dumps({
                    "warranty_detected": True,
                    "item_name": expected_name,
                    "item_category": "electronics",
                    "vendor": "Test",
                    "purchase_date": "2025-06-15",
                    "warranty_duration_months": 24,
                    "purchase_amount": 100.0,
                    "confidence": 0.90,
                })
            else:
                response = json.dumps({
                    "warranty_detected": False,
                    "item_name": "",
                    "item_category": "other",
                    "vendor": None,
                    "purchase_date": "",
                    "warranty_duration_months": 0,
                    "purchase_amount": None,
                    "confidence": 0.1,
                })

            mock_adapter = MagicMock()
            mock_adapter.complete = AsyncMock(return_value=response)
            mock_llm.return_value = mock_adapter

            orchestrator = WarrantyOrchestrator(db_pool=AsyncMock())
            result = await orchestrator.process_document_for_warranty(
                document_id=doc_id,
                ocr_text=ocr_text,
            )
            results.append(result)

        assert results[0].payload["warranty_detected"] is True
        assert results[1].payload["warranty_detected"] is True
        assert results[2].payload["warranty_detected"] is False
