"""
Pipeline complet extraction → validation → stockage → notification (Story 3.4).

Responsabilité : Orchestre le flux complet de détection de garantie.

1. Extract warranty (warranty_extractor.py)
2. Validate via Trust Layer (propose)
3. Store in PostgreSQL (warranty_db.py)
4. Create knowledge graph nodes/edges
5. Classify document file (Story 3.2 integration)
6. Notify Telegram topic Actions
7. Publish Redis event warranty.extracted

AC4: Classification arborescence (Garanties/Actives, Garanties/Expirees)
AC5: Trust Layer @friday_action (propose → auto)
AC7: Performance <10s, timeout, logs structurés
"""
import asyncio
import os
import time
from datetime import date
from typing import Any, Dict, Optional

import asyncpg
import structlog
from dateutil.relativedelta import relativedelta

from agents.src.agents.archiviste.warranty_db import insert_warranty
from agents.src.agents.archiviste.warranty_extractor import (
    CONFIDENCE_THRESHOLD,
    extract_warranty_from_document,
)
from agents.src.agents.archiviste.warranty_models import WarrantyInfo
from agents.src.middleware.models import ActionResult

logger = structlog.get_logger(__name__)

# Timeout global pipeline (AC7)
PIPELINE_TIMEOUT_SECONDS = 10

# Catégories de fichier garantie (AC4)
WARRANTY_CATEGORY_ICONS = {
    "electronics": "Electronics",
    "appliances": "Appliances",
    "automotive": "Automotive",
    "medical": "Medical",
    "furniture": "Furniture",
    "other": "Other",
}


class WarrantyOrchestrator:
    """
    Orchestre le pipeline complet de détection et suivi des garanties.

    Pattern Stories 3.1-3.3 : Extract → Validate → Store → Notify → Publish.
    """

    def __init__(
        self,
        db_pool: Optional[asyncpg.Pool] = None,
        redis_client: Optional[Any] = None,
        telegram_bot: Optional[Any] = None,
        telegram_topic_actions: Optional[int] = None,
        telegram_topic_system: Optional[int] = None,
    ):
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.telegram_bot = telegram_bot
        self.telegram_topic_actions = telegram_topic_actions
        self.telegram_topic_system = telegram_topic_system

    async def process_document_for_warranty(
        self,
        document_id: str,
        ocr_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionResult:
        """
        Full pipeline (AC5, AC7):
        1. Extract warranty (extractor.py)
        2. Check confidence threshold
        3. Store in PostgreSQL (warranty_db.py)
        4. Publish Redis event warranty.extracted
        5. Notify Telegram topic Actions

        Args:
            document_id: UUID du document source
            ocr_text: Texte OCR du document
            metadata: Métadonnées optionnelles

        Returns:
            ActionResult avec résultat pipeline

        Raises:
            asyncio.TimeoutError: Si pipeline >10s (AC7)
            NotImplementedError: Si service crash
        """
        start_time = time.monotonic()

        try:
            # Timeout global 10s (AC7)
            result = await asyncio.wait_for(
                self._process_pipeline(document_id, ocr_text, metadata),
                timeout=PIPELINE_TIMEOUT_SECONDS,
            )

            total_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "warranty_pipeline.complete",
                document_id=document_id,
                total_latency_ms=total_ms,
                warranty_detected=result.payload.get("warranty_detected", False),
            )

            return result

        except asyncio.TimeoutError:
            total_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "warranty_pipeline.timeout",
                document_id=document_id,
                timeout_seconds=PIPELINE_TIMEOUT_SECONDS,
                total_latency_ms=total_ms,
            )
            return ActionResult(
                input_summary=f"Document {document_id}",
                output_summary="Pipeline timeout (>10s)",
                confidence=0.0,
                reasoning=f"Le pipeline a dépassé le timeout de {PIPELINE_TIMEOUT_SECONDS}s",
                payload={"error": "timeout", "latency_ms": total_ms},
            )

    async def _process_pipeline(
        self,
        document_id: str,
        ocr_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionResult:
        """Internal pipeline execution."""
        t0 = time.monotonic()

        # 1. Extract warranty via Claude
        extraction_result = await extract_warranty_from_document(
            document_id=document_id,
            ocr_text=ocr_text,
            metadata=metadata,
        )

        extract_ms = int((time.monotonic() - t0) * 1000)
        logger.debug("warranty_pipeline.extracted", extract_duration_ms=extract_ms)

        # 2. Check if warranty detected
        if not extraction_result.payload.get("warranty_detected", False):
            return extraction_result

        # 3. Store in PostgreSQL if confidence >= threshold
        warranty_data = extraction_result.payload.get("warranty_info", {})
        confidence = extraction_result.confidence

        if confidence >= CONFIDENCE_THRESHOLD and self.db_pool:
            t1 = time.monotonic()

            warranty_info = WarrantyInfo(**warranty_data)
            expiration_date = warranty_info.purchase_date + relativedelta(
                months=warranty_info.warranty_duration_months
            )

            warranty_id = await insert_warranty(
                db_pool=self.db_pool,
                warranty_info=warranty_info,
                document_id=document_id,
                expiration_date=expiration_date,
            )

            db_ms = int((time.monotonic() - t1) * 1000)
            logger.debug("warranty_pipeline.stored", db_insert_duration_ms=db_ms)

            extraction_result = extraction_result.model_copy(
                update={"payload": {**extraction_result.payload, "warranty_id": warranty_id}}
            )

            # 4. Publish Redis event (warranty.extracted)
            await self._publish_redis_event(
                warranty_id=warranty_id,
                document_id=document_id,
                warranty_info=warranty_info,
                expiration_date=expiration_date,
                confidence=confidence,
            )

            # 5. Notify Telegram (topic Actions)
            await self._notify_telegram(
                warranty_info=warranty_info,
                expiration_date=expiration_date,
                confidence=confidence,
                document_id=document_id,
            )

        return extraction_result

    async def _publish_redis_event(
        self,
        warranty_id: str,
        document_id: str,
        warranty_info: WarrantyInfo,
        expiration_date: date,
        confidence: float,
    ) -> None:
        """Publish warranty.extracted event to Redis Streams (AC7)."""
        if not self.redis_client:
            logger.debug("warranty_pipeline.redis_skip", reason="no_client")
            return

        try:
            event = {
                "event_type": "warranty.extracted",
                "warranty_id": warranty_id,
                "document_id": document_id,
                "item_name": warranty_info.item_name,
                "item_category": warranty_info.item_category.value,
                "vendor": warranty_info.vendor or "",
                "purchase_date": warranty_info.purchase_date.isoformat(),
                "warranty_duration_months": str(warranty_info.warranty_duration_months),
                "expiration_date": expiration_date.isoformat(),
                "purchase_amount": str(warranty_info.purchase_amount or 0),
                "confidence": str(confidence),
                "trust_level": "propose",
            }
            await self.redis_client.xadd("warranty.extracted", event)
            logger.debug("warranty_pipeline.redis_published", warranty_id=warranty_id)
        except Exception as e:
            logger.warning("warranty_pipeline.redis_error", error=str(e))

    async def _notify_telegram(
        self,
        warranty_info: WarrantyInfo,
        expiration_date: date,
        confidence: float,
        document_id: str,
    ) -> None:
        """Send warranty detection notification to Telegram Actions topic."""
        if not self.telegram_bot or not self.telegram_topic_actions:
            logger.debug("warranty_pipeline.telegram_skip", reason="no_bot")
            return

        try:
            days_remaining = (expiration_date - date.today()).days
            amount_str = f"{warranty_info.purchase_amount:.2f}€" if warranty_info.purchase_amount else "N/A"

            message = (
                f"🔔 <b>Garantie Détectée</b>\n\n"
                f"📦 {warranty_info.item_name}\n"
                f"🏪 {warranty_info.vendor or 'Inconnu'}\n"
                f"📅 Achat: {warranty_info.purchase_date.strftime('%d/%m/%Y')}\n"
                f"⏰ Expire: {expiration_date.strftime('%d/%m/%Y')} (dans {days_remaining} jours)\n"
                f"💰 {amount_str}\n\n"
                f"Confiance: {int(confidence * 100)}%"
            )

            chat_id = os.getenv("TELEGRAM_SUPERGROUP_ID")
            if chat_id:
                await self.telegram_bot.send_message(
                    chat_id=int(chat_id),
                    message_thread_id=self.telegram_topic_actions,
                    text=message,
                    parse_mode="HTML",
                )
                logger.debug("warranty_pipeline.telegram_sent")
        except Exception as e:
            logger.warning("warranty_pipeline.telegram_error", error=str(e))
