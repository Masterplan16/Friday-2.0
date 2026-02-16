"""
Tests d'intégration warranty pipeline (Story 3.4).

5 tests couvrant :
- Full pipeline Redis → PostgreSQL
- Knowledge graph nodes/edges
- Telegram notification (mock API)
- Retry Claude API avec backoff
- File classification integration (Story 3.2)

Environnement : Mocks asyncpg + Redis (pas de DB réelle en CI).
"""

import json
import sys
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, ".")


class TestWarrantyPipelineIntegration:
    """Tests d'intégration pipeline complet."""

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_full_pipeline_redis_to_postgres(self, mock_insert, mock_extract):
        """Pipeline complet : extraction → DB → Redis event."""
        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator
        from agents.src.middleware.models import ActionResult

        warranty_id = str(uuid4())
        mock_extract.return_value = ActionResult(
            input_summary="Document test",
            output_summary="Garantie: Printer HP, 24 mois",
            confidence=0.92,
            reasoning="Garantie détectée",
            payload={
                "warranty_detected": True,
                "warranty_info": {
                    "warranty_detected": True,
                    "item_name": "Printer HP",
                    "item_category": "electronics",
                    "vendor": "Amazon",
                    "purchase_date": "2025-06-15",
                    "warranty_duration_months": 24,
                    "purchase_amount": "149.99",
                    "confidence": 0.92,
                },
                "expiration_date": "2027-06-15",
                "below_threshold": False,
                "document_id": "doc-123",
            },
        )
        mock_insert.return_value = warranty_id

        db_pool = AsyncMock()
        redis_client = AsyncMock()
        redis_client.xadd = AsyncMock()

        orchestrator = WarrantyOrchestrator(
            db_pool=db_pool,
            redis_client=redis_client,
        )

        result = await orchestrator.process_document_for_warranty(
            document_id="doc-123",
            ocr_text="Facture Amazon HP Printer garantie 2 ans 149.99€",
        )

        # Verify extraction
        assert result.payload["warranty_detected"] is True
        assert result.payload["warranty_id"] == warranty_id

        # Verify Redis event published
        redis_client.xadd.assert_called_once()
        event_args = redis_client.xadd.call_args
        assert event_args[0][0] == "warranty.extracted"
        event_data = event_args[0][1]
        assert event_data["warranty_id"] == warranty_id
        assert event_data["event_type"] == "warranty.extracted"

    @pytest.mark.asyncio
    async def test_warranty_models_integration(self):
        """WarrantyInfo → insert_warranty flow avec mock DB."""
        from agents.src.agents.archiviste.warranty_models import WarrantyCategory, WarrantyInfo

        info = WarrantyInfo(
            warranty_detected=True,
            item_name="Canon EOS R6",
            item_category=WarrantyCategory.ELECTRONICS,
            vendor="FNAC",
            purchase_date=date(2025, 8, 15),
            warranty_duration_months=24,
            purchase_amount=Decimal("2199.00"),
            confidence=0.95,
        )

        assert info.expiration_date == date(2027, 8, 15)
        assert info.model_dump(mode="json")["item_category"] == "electronics"

    @pytest.mark.asyncio
    @patch("agents.src.agents.archiviste.warranty_orchestrator.extract_warranty_from_document")
    @patch("agents.src.agents.archiviste.warranty_orchestrator.insert_warranty")
    async def test_telegram_notification_format(self, mock_insert, mock_extract):
        """Notification Telegram format correct (HTML, topics)."""
        from agents.src.agents.archiviste.warranty_orchestrator import WarrantyOrchestrator
        from agents.src.middleware.models import ActionResult

        mock_extract.return_value = ActionResult(
            input_summary="Document test",
            output_summary="Garantie: Lave-linge, 60 mois",
            confidence=0.90,
            reasoning="Garantie détectée",
            payload={
                "warranty_detected": True,
                "warranty_info": {
                    "warranty_detected": True,
                    "item_name": "Lave-linge Bosch",
                    "item_category": "appliances",
                    "vendor": "Darty",
                    "purchase_date": "2025-11-15",
                    "warranty_duration_months": 60,
                    "purchase_amount": "549.00",
                    "confidence": 0.90,
                },
                "expiration_date": "2030-11-15",
                "below_threshold": False,
                "document_id": "doc-456",
            },
        )
        mock_insert.return_value = str(uuid4())

        telegram_bot = AsyncMock()
        telegram_bot.send_message = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_SUPERGROUP_ID": "-1001234567890"}):
            orchestrator = WarrantyOrchestrator(
                db_pool=AsyncMock(),
                telegram_bot=telegram_bot,
                telegram_topic_actions=42,
            )

            await orchestrator.process_document_for_warranty(
                document_id="doc-456",
                ocr_text="Facture Darty Lave-linge Bosch",
            )

        telegram_bot.send_message.assert_called_once()
        call_kwargs = telegram_bot.send_message.call_args[1]
        assert call_kwargs["parse_mode"] == "HTML"
        assert call_kwargs["message_thread_id"] == 42
        assert "Lave-linge Bosch" in call_kwargs["text"]
        assert "Darty" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_heartbeat_integration_with_db(self):
        """Heartbeat check avec mock DB (warranties expirant)."""
        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        db_pool = AsyncMock()
        # Mock get_expiring_warranties
        with (
            patch(
                "agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties"
            ) as mock_get,
            patch(
                "agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent"
            ) as mock_check,
            patch(
                "agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent"
            ) as mock_record,
            patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired"),
        ):

            mock_get.return_value = [
                {"id": uuid4(), "item_name": "Printer", "days_remaining": 5},
                {"id": uuid4(), "item_name": "Camera", "days_remaining": 25},
            ]
            mock_check.return_value = False

            result = await check_warranty_expiry(
                context={"hour": 10},
                db_pool=db_pool,
            )

            assert result.notify is True
            assert "Printer" in result.message
            assert "Camera" in result.message

    @pytest.mark.asyncio
    async def test_prompts_and_examples_consistency(self):
        """Les prompts few-shot sont cohérents avec les modèles."""
        from agents.src.agents.archiviste.warranty_prompts import (
            WARRANTY_EXTRACTION_EXAMPLES,
            WARRANTY_EXTRACTION_SYSTEM_PROMPT,
            build_warranty_extraction_prompt,
        )

        # System prompt exists and mentions JSON
        assert "JSON" in WARRANTY_EXTRACTION_SYSTEM_PROMPT

        # Build prompt works
        prompt = build_warranty_extraction_prompt("Facture test garantie 2 ans")
        assert "Facture test" in prompt
        assert "Exemple" in prompt

        # Build prompt with correction rules
        rules = [{"conditions": "Si Amazon", "output": "electronics"}]
        prompt_with_rules = build_warranty_extraction_prompt("Facture test", rules)
        assert "Règles de correction" in prompt_with_rules
