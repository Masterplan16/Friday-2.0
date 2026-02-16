"""
Extraction de garanties depuis texte OCR via Claude Sonnet 4.5 (Story 3.4 AC1).

Pipeline RGPD strict :
1. Anonymiser texte OCR via Presidio
2. Extraire garantie via Claude (texte anonymisé, few-shot 5 exemples)
3. Parser JSON + validation Pydantic
4. Déanonymiser résultats (vendor, item_name)
5. Retourner ActionResult avec confidence

Trust Layer: @friday_action avec trust=propose (Day 1).
"""
import json
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog
from dateutil.relativedelta import relativedelta

from agents.src.agents.archiviste.warranty_models import (
    WarrantyCategory,
    WarrantyExtractionResult,
    WarrantyInfo,
)
from agents.src.agents.archiviste.warranty_prompts import (
    WARRANTY_EXTRACTION_SYSTEM_PROMPT,
    build_warranty_extraction_prompt,
)
from agents.src.adapters.llm import get_llm_adapter
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action
from agents.src.tools.anonymize import anonymize_text, deanonymize_text

logger = structlog.get_logger(__name__)

# Seuil de confiance minimum pour validation automatique (AC1)
CONFIDENCE_THRESHOLD = 0.75


@friday_action(
    module="archiviste",
    action="extract_warranty",
    trust_default="propose"
)
async def extract_warranty_from_document(
    document_id: str,
    ocr_text: str,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> ActionResult:
    """
    Extract warranty information from OCR text (AC1, AC5).

    Pipeline:
    1. Anonymize PII (Presidio) - RGPD obligatoire
    2. Call Claude with few-shot prompt
    3. Parse JSON response + Pydantic validation
    4. Deanonymize vendor/item_name
    5. Check confidence threshold (>=0.75)
    6. Return ActionResult

    Args:
        document_id: UUID du document source
        ocr_text: Texte OCR du document
        metadata: Métadonnées optionnelles du document
        **kwargs: Decorator-injected arguments (_correction_rules, etc.)

    Returns:
        ActionResult avec warranty info dans payload

    Raises:
        NotImplementedError: Si Presidio ou Claude crash (fail-explicit)
    """
    logger.info(
        "warranty_extraction.start",
        document_id=document_id,
        text_length=len(ocr_text),
    )

    try:
        # 1. Anonymiser texte OCR via Presidio (RGPD obligatoire)
        try:
            anonymized_result = await anonymize_text(ocr_text)
            if isinstance(anonymized_result, tuple):
                anonymized_text, mapping = anonymized_result
            else:
                anonymized_text = anonymized_result.anonymized_text
                mapping = anonymized_result.mapping
            logger.debug(
                "warranty_extraction.anonymized",
                entities_count=len(mapping),
            )
        except Exception as e:
            logger.error("warranty_extraction.presidio_failure", error=str(e))
            raise NotImplementedError(
                f"Presidio anonymization unavailable: {e}"
            ) from e

        # 2. Construire prompt few-shot avec correction_rules
        correction_rules = kwargs.get("_correction_rules", [])
        prompt = build_warranty_extraction_prompt(anonymized_text, correction_rules)

        # 3. Appeler Claude Sonnet 4.5
        try:
            llm = get_llm_adapter()
            response = await llm.complete(
                prompt=prompt,
                system=WARRANTY_EXTRACTION_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=400,
            )
            content = response if isinstance(response, str) else response.content
            logger.debug(
                "warranty_extraction.claude_response",
                response_length=len(content) if content else 0,
            )
        except Exception as e:
            logger.error("warranty_extraction.claude_failure", error=str(e))
            raise NotImplementedError(
                f"Claude API unavailable: {e}"
            ) from e

        # 4. Parser réponse JSON
        warranty_data = _parse_claude_response(content)

        # 5. Vérifier si garantie détectée
        if not warranty_data.get("warranty_detected", False):
            logger.info(
                "warranty_extraction.no_warranty_detected",
                document_id=document_id,
            )
            return ActionResult(
                input_summary=f"Document {document_id} ({len(ocr_text)} chars OCR)",
                output_summary="Aucune garantie détectée",
                confidence=warranty_data.get("confidence", 0.0),
                reasoning="Aucune information de garantie trouvée dans le document",
                payload={"warranty_detected": False},
            )

        # 6. Déanonymiser vendor et item_name
        item_name = warranty_data.get("item_name", "")
        vendor = warranty_data.get("vendor")
        if mapping:
            if item_name and any(k in item_name for k in mapping):
                item_name = await deanonymize_text(item_name, mapping)
            if vendor and any(k in vendor for k in mapping):
                vendor = await deanonymize_text(vendor, mapping)

        # 7. Valider avec Pydantic
        purchase_date = _parse_date(warranty_data.get("purchase_date", ""))
        duration_months = int(warranty_data.get("warranty_duration_months", 0))
        expiration_date = purchase_date + relativedelta(months=duration_months)

        warranty_info = WarrantyInfo(
            warranty_detected=True,
            item_name=item_name,
            item_category=_parse_category(warranty_data.get("item_category", "other")),
            vendor=vendor,
            purchase_date=purchase_date,
            warranty_duration_months=duration_months,
            purchase_amount=_parse_amount(warranty_data.get("purchase_amount")),
            confidence=float(warranty_data.get("confidence", 0.0)),
        )

        # 8. Check confidence threshold
        confidence = warranty_info.confidence
        below_threshold = confidence < CONFIDENCE_THRESHOLD

        logger.info(
            "warranty_extraction.success",
            document_id=document_id,
            item_name=warranty_info.item_name,
            category=warranty_info.item_category.value,
            confidence=confidence,
            below_threshold=below_threshold,
        )

        return ActionResult(
            input_summary=f"Document: {document_id}",
            output_summary=(
                f"Garantie: {warranty_info.item_name}, "
                f"{warranty_info.warranty_duration_months} mois "
                f"jusqu'au {expiration_date.isoformat()}"
            ),
            confidence=confidence,
            reasoning=(
                f"Garantie détectée ({warranty_info.item_category.value}), "
                f"vendeur={warranty_info.vendor or 'inconnu'}, "
                f"montant={warranty_info.purchase_amount or 'N/A'}EUR"
            ),
            payload={
                "warranty_detected": True,
                "warranty_info": warranty_info.model_dump(mode="json"),
                "expiration_date": expiration_date.isoformat(),
                "below_threshold": below_threshold,
                "document_id": document_id,
            },
        )

    except NotImplementedError:
        raise
    except Exception as e:
        logger.error(
            "warranty_extraction.unexpected_error",
            document_id=document_id,
            error=str(e),
        )
        raise RuntimeError(
            f"Warranty extraction failed: {e}"
        ) from e


def _parse_claude_response(content: str) -> Dict[str, Any]:
    """Parse Claude JSON response, handling markdown code blocks."""
    if not content:
        return {"warranty_detected": False, "confidence": 0.0}

    text = content.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(
            "warranty_extraction.json_parse_error",
            response_preview=text[:200],
            error=str(e),
        )
        raise ValueError(f"Failed to parse Claude response: {e}") from e


def _parse_date(date_str: str) -> date:
    """Parse date string to date object."""
    if not date_str:
        raise ValueError("Date string is empty")
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        # Try DD/MM/YYYY format
        parts = date_str.split("/")
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
        raise ValueError(f"Cannot parse date: {date_str}")


def _parse_category(category_str: str) -> WarrantyCategory:
    """Parse category string to enum, defaulting to OTHER."""
    try:
        return WarrantyCategory(category_str.lower())
    except ValueError:
        return WarrantyCategory.OTHER


def _parse_amount(amount) -> Optional[Decimal]:
    """Parse amount to Decimal, returning None if invalid."""
    if amount is None:
        return None
    try:
        val = Decimal(str(amount))
        return val if val >= 0 else None
    except (ValueError, TypeError):
        return None
