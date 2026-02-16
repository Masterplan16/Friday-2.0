"""
Module de detection urgence multi-facteurs (Story 2.3).

Algorithme urgence = 3 facteurs :
- VIP status (0.5 si VIP)
- Keywords urgence (0.3 max)
- Deadline patterns (0.2 max)
Seuil urgence : score >= 0.6
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional

import asyncpg
import structlog
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action
from agents.src.models.vip_detection import UrgencyResult

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class UrgencyDetectorError(Exception):
    """Erreur dans le processus de detection urgence."""


@friday_action(module="email", action="detect_urgency", trust_default="auto")
async def detect_urgency(
    email_text: str,
    vip_status: bool,
    db_pool: asyncpg.Pool,
    **kwargs: Any,  # Absorbe _correction_rules et _rules_prompt injectes par decorateur
) -> ActionResult:
    """
    Detecte si un email est urgent via analyse multi-facteurs.

    Algorithme :
    - Facteur VIP : 0.5 si vip_status=True
    - Facteur keywords : 0.3 * (keywords_matched / keywords_total)
    - Facteur deadline : 0.2 si deadline detecte dans subject/body

    Seuil urgence : score >= 0.6

    Args:
        email_text: Texte email anonymise (subject + body)
        vip_status: True si expediteur VIP detecte
        db_pool: Pool de connexions PostgreSQL
        **kwargs: Parametres injectes par decorateur

    Returns:
        ActionResult avec:
            - confidence = urgency_score (0.0-1.0)
            - payload contient UrgencyResult si urgent

    Raises:
        UrgencyDetectorError: Si detection echoue

    Notes:
        - Trust level: auto (algorithme deterministe)
        - Latence cible: <100ms
        - Keywords via table core.urgency_keywords
    """
    try:
        # === PHASE 1: Calculer facteur VIP ===
        vip_factor = 0.5 if vip_status else 0.0

        # === PHASE 2: Calculer facteur keywords ===
        keywords_matched = await check_urgency_keywords(
            text=email_text,
            db_pool=db_pool,
        )
        keywords_factor = 0.3 if keywords_matched else 0.0

        # === PHASE 3: Calculer facteur deadline ===
        deadline_detected = extract_deadline_patterns(email_text)
        deadline_factor = 0.2 if deadline_detected else 0.0

        # === PHASE 4: Score total urgence ===
        urgency_score = vip_factor + keywords_factor + deadline_factor
        is_urgent = urgency_score >= 0.6

        # === PHASE 5: Build reasoning ===
        factors_details = []
        if vip_factor > 0:
            factors_details.append(f"VIP={vip_factor:.1f}")
        if keywords_factor > 0:
            factors_details.append(
                f"keywords={keywords_factor:.1f} ({len(keywords_matched)} matches)"
            )
        if deadline_factor > 0:
            factors_details.append(f"deadline={deadline_factor:.1f}")

        reasoning = (
            f"Score urgence: {urgency_score:.2f} (seuil=0.6). "
            f"Facteurs: {', '.join(factors_details) if factors_details else 'aucun'}"
        )

        # === PHASE 6: Build UrgencyResult ===
        urgency_result = UrgencyResult(
            is_urgent=is_urgent,
            confidence=urgency_score,
            reasoning=reasoning,
            factors={
                "vip": vip_factor,
                "keywords": keywords_factor,
                "deadline": deadline_factor,
                "keywords_matched": keywords_matched,
                "deadline_text": deadline_detected,
            },
        )

        logger.info(
            "urgency_detected" if is_urgent else "urgency_not_detected",
            is_urgent=is_urgent,
            score=urgency_score,
            vip_factor=vip_factor,
            keywords_factor=keywords_factor,
            deadline_factor=deadline_factor,
        )

        return ActionResult(
            input_summary=f"Email text ({len(email_text)} chars, VIP={vip_status})",
            output_summary=(
                f"Urgent (score={urgency_score:.2f})"
                if is_urgent
                else f"Normal (score={urgency_score:.2f})"
            ),
            confidence=urgency_score,
            reasoning=reasoning,
            payload={"urgency": urgency_result.model_dump(), "is_urgent": is_urgent},
        )

    except Exception as e:
        logger.error(
            "urgency_detection_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise UrgencyDetectorError(f"Urgency detection failed: {e}") from e


async def check_urgency_keywords(
    text: str,
    db_pool: asyncpg.Pool,
) -> list[str]:
    """
    Verifie presence keywords urgence dans texte.

    Args:
        text: Texte email (subject + body anonymise)
        db_pool: Pool de connexions PostgreSQL

    Returns:
        Liste keywords matches (ex: ["URGENT", "deadline"])

    Notes:
        - Recherche case-insensitive
        - Keywords depuis core.urgency_keywords WHERE active=TRUE
        - Si erreur DB -> log warning + retourne [] (mode degrade)
    """
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT keyword, weight
                FROM core.urgency_keywords
                WHERE active = TRUE
                ORDER BY weight DESC
                """)

            if not rows:
                logger.warning(
                    "urgency_keywords_empty", message="No active urgency keywords in database"
                )
                return []

            # Recherche case-insensitive
            text_lower = text.lower()
            matched = []

            for row in rows:
                keyword = row["keyword"]
                if keyword.lower() in text_lower:
                    matched.append(keyword)
                    logger.debug(
                        "urgency_keyword_matched",
                        keyword=keyword,
                        weight=row["weight"],
                    )

            return matched

    except Exception as e:
        logger.warning(
            "urgency_keywords_check_failed",
            error=str(e),
            error_type=type(e).__name__,
            fallback="degraded_mode",
        )
        # Mode degrade : continuer sans keywords
        return []


def extract_deadline_patterns(text: str) -> Optional[str]:
    """
    Detecte patterns deadline dans texte email.

    Patterns detectes :
    - "avant [date]" (ex: "avant demain", "avant le 15")
    - "deadline [date]"
    - "pour [date]" (ex: "pour demain")
    - "d'ici [date]"
    - "urgent" + date proche

    Args:
        text: Texte email anonymise

    Returns:
        Pattern deadline matche (ex: "avant demain") ou None

    Notes:
        - Recherche case-insensitive
        - Regex patterns francais
        - Retourne premier match trouve
    """
    deadline_patterns = [
        r"avant\s+(demain|le\s+\d{1,2}|la\s+fin|ce\s+soir)",
        r"deadline\s+\d{1,2}",
        r"pour\s+(demain|ce\s+soir|la\s+fin)",
        r"d'ici\s+(demain|ce\s+soir|\d+\s+(jours?|heures?))",
        r"urgent.*\b(demain|aujourd'hui|ce\s+soir)\b",
    ]

    text_lower = text.lower()

    for pattern in deadline_patterns:
        match = re.search(pattern, text_lower)
        if match:
            deadline_text = match.group(0)
            logger.debug(
                "deadline_pattern_matched",
                pattern=pattern,
                match=deadline_text,
            )
            return deadline_text

    return None
