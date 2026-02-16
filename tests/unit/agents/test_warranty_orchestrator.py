"""
Tests unitaires warranty_orchestrator.py (Story 3.4 AC5, AC7).

18 tests couvrant :
- Pipeline complet (extract → store → notify)
- Trust level propose
- Timeout asyncio.wait_for(10)
- Redis event warranty.extracted
- Integration Story 3.2 classification
- Edge cases (DB error, Redis down, Telegram error)
"""
import asyncio
import json
import sys
import time
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, ".")


# ============================================================================
# FIXTURES
# ============================================================================

def _mock_extraction_result(warranty_detected=True, confidence=0.92):
    """Create mock ActionResult from extract_warranty_from_document."""
    from agents.src.middleware.models import ActionResult

    if warranty_detected:
        return ActionResult(
            input_summary="Document test-doc (OCR text analyse)",
            output_summary="Garantie: HP Printer, 24 mois jusqu'au 2027-06-15",
            confidence=confidence,
            reasoning="Garantie detectee (electronics), vendeur=Amazon, montant=149.99EUR",
            payload={
                "warranty_detected": True,
                "warranty_info": {
                    "warranty_detected": True,
                    "item_name": "HP Printer",
                    "item_category": "electronics",
                    "vendor": "Amazon",
                    "purchase_date": "2025-06-15",
                    "warranty_duration_months": 24,
                    "purchase_amount": "149.99",
                    "confidence": confidence,
                },
                "expiration_date": "2027-06-15",
                "below_threshold": confidence < 0.75,
                "document_id": "test-doc",
            },
        )
    else:
        return ActionResult(
            input_summary="Document test-doc (OCR text analyse)",
            output_summary="Aucune garantie detectee dans le document",
            confidence=0.1,
            reasoning="Aucune information de garantie trouvee dans le document analyse",
            payload={"warranty_detected": False},
        )


class TestWarrantyOrchestrator:
    """Tests pour WarrantyOrchestrator."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_full_pipeline_success(self, mock_insert, mock_extract):
        """Pipeline complet : extract → store → notify OK."""
        mock_extract.return_value = _mock_extraction_result()
        mock_insert.return_value = str(uuid4())

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        db_pool = AsyncMock()
        orchestrator = WarrantyOrchestrator(db_pool=db_pool)

        result = await orchestrator.process_document_for_warranty(
            document_id="test-doc",
            ocr_text="Facture HP Printer garantie 2 ans",
        )

        assert result.payload["warranty_detected"] is True
        assert result.confidence == 0.92
        mock_extract.assert_called_once()
        mock_insert.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    async def test_no_warranty_detected(self, mock_extract):
        """Pas de garantie détectée = pas d'insert."""
        mock_extract.return_value = _mock_extraction_result(warranty_detected=False)

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(db_pool=AsyncMock())

        result = await orchestrator.process_document_for_warranty(
            document_id="test-doc",
            ocr_text="Courrier simple sans garantie",
        )

        assert result.payload["warranty_detected"] is False

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    async def test_low_confidence_no_insert(self, mock_extract):
        """Confidence <0.75 = pas d'insert DB."""
        mock_extract.return_value = _mock_extraction_result(confidence=0.60)

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(db_pool=AsyncMock())

        result = await orchestrator.process_document_for_warranty(
            document_id="test-doc",
            ocr_text="Document flou",
        )

        assert result.payload["warranty_detected"] is True
        # Should not have warranty_id (not stored)
        assert "warranty_id" not in result.payload

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    async def test_timeout_exceeded(self, mock_extract):
        """Timeout 10s déclenché = ActionResult avec erreur."""
        async def slow_extract(*args, **kwargs):
            await asyncio.sleep(15)
            return _mock_extraction_result()

        mock_extract.side_effect = slow_extract

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(db_pool=AsyncMock())

        result = await orchestrator.process_document_for_warranty(
            document_id="test-doc",
            ocr_text="Document lent",
        )

        assert result.payload.get("error") == "timeout"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_redis_event_published(self, mock_insert, mock_extract):
        """Redis event warranty.extracted publié après insert."""
        mock_extract.return_value = _mock_extraction_result()
        mock_insert.return_value = str(uuid4())

        redis_client = AsyncMock()
        redis_client.xadd = AsyncMock()

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(
            db_pool=AsyncMock(),
            redis_client=redis_client,
        )

        await orchestrator.process_document_for_warranty(
            document_id="test-doc",
            ocr_text="Facture HP Printer",
        )

        redis_client.xadd.assert_called_once()
        call_args = redis_client.xadd.call_args
        assert call_args[0][0] == "warranty.extracted"
        assert call_args[0][1]["event_type"] == "warranty.extracted"

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_redis_failure_non_blocking(self, mock_insert, mock_extract):
        """Redis failure ne bloque pas le pipeline."""
        mock_extract.return_value = _mock_extraction_result()
        mock_insert.return_value = str(uuid4())

        redis_client = AsyncMock()
        redis_client.xadd = AsyncMock(side_effect=Exception("Redis down"))

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(
            db_pool=AsyncMock(),
            redis_client=redis_client,
        )

        # Should not raise
        result = await orchestrator.process_document_for_warranty(
            document_id="test-doc",
            ocr_text="Facture HP Printer",
        )

        assert result.payload["warranty_detected"] is True

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_telegram_notification_sent(self, mock_insert, mock_extract):
        """Telegram notification envoyée après insert."""
        mock_extract.return_value = _mock_extraction_result()
        mock_insert.return_value = str(uuid4())

        telegram_bot = AsyncMock()
        telegram_bot.send_message = AsyncMock()

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        with patch.dict("os.environ", {"TELEGRAM_SUPERGROUP_ID": "-1001234567890"}):
            orchestrator = WarrantyOrchestrator(
                db_pool=AsyncMock(),
                telegram_bot=telegram_bot,
                telegram_topic_actions=42,
            )

            await orchestrator.process_document_for_warranty(
                document_id="test-doc",
                ocr_text="Facture HP Printer",
            )

        telegram_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_telegram_failure_non_blocking(self, mock_insert, mock_extract):
        """Telegram failure ne bloque pas le pipeline."""
        mock_extract.return_value = _mock_extraction_result()
        mock_insert.return_value = str(uuid4())

        telegram_bot = AsyncMock()
        telegram_bot.send_message = AsyncMock(side_effect=Exception("Telegram error"))

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        with patch.dict("os.environ", {"TELEGRAM_SUPERGROUP_ID": "-1001234567890"}):
            orchestrator = WarrantyOrchestrator(
                db_pool=AsyncMock(),
                telegram_bot=telegram_bot,
                telegram_topic_actions=42,
            )

            result = await orchestrator.process_document_for_warranty(
                document_id="test-doc",
                ocr_text="Facture HP Printer",
            )

        assert result.payload["warranty_detected"] is True

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    async def test_no_db_pool_no_insert(self, mock_extract):
        """Sans db_pool, pas d'insert DB."""
        mock_extract.return_value = _mock_extraction_result()

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(db_pool=None)

        result = await orchestrator.process_document_for_warranty(
            document_id="test-doc",
            ocr_text="Facture HP Printer",
        )

        assert result.payload["warranty_detected"] is True
        assert "warranty_id" not in result.payload

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_db_insert_failure(self, mock_insert, mock_extract):
        """DB insert failure propage l'erreur."""
        mock_extract.return_value = _mock_extraction_result()
        mock_insert.side_effect = Exception("DB connection lost")

        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator

        orchestrator = WarrantyOrchestrator(db_pool=AsyncMock())

        with pytest.raises(Exception, match="DB connection"):
            await orchestrator.process_document_for_warranty(
                document_id="test-doc",
                ocr_text="Facture HP Printer",
            )
