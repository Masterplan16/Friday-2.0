#!/usr/bin/env python3
"""
Friday 2.0 - Anonymisation Presidio (RGPD obligatoire)
Pipeline anonymisation réversible AVANT tout appel LLM cloud

Usage:
    from agents.src.tools.anonymize import anonymize_text, deanonymize_text

RÈGLE CRITIQUE (CLAUDE.md):
    JAMAIS envoyer PII au LLM cloud sans anonymisation Presidio.

Architecture:
    - Presidio Analyzer (http://presidio-analyzer:5001) : détecte entités sensibles
    - Presidio Anonymizer (http://presidio-anonymizer:5002) : anonymise/deanonymise
    - Mapping éphémère en mémoire (JAMAIS stocké en clair, voir addendum section 9.1)

Benchmark (addendum section 1):
    - Latence: ~150-200ms (doc 1000 mots)
    - Précision: >95% pour entités FR (spaCy fr_core_news_lg)

Date: 2026-02-05
Version: 1.0.0 (Story 1.5.1)
"""

import os
import logging
from typing import Dict, List, Tuple, Optional
import httpx
from dataclasses import dataclass

# Configuration Presidio (via env vars)
PRESIDIO_ANALYZER_URL = os.getenv("PRESIDIO_ANALYZER_URL", "http://presidio-analyzer:5001")
PRESIDIO_ANONYMIZER_URL = os.getenv("PRESIDIO_ANONYMIZER_URL", "http://presidio-anonymizer:5002")
PRESIDIO_TIMEOUT = int(os.getenv("PRESIDIO_TIMEOUT", "30"))

# Entités sensibles à détecter (France)
FRENCH_ENTITIES = [
    "PERSON",           # Noms, prénoms
    "EMAIL_ADDRESS",    # Emails
    "PHONE_NUMBER",     # Téléphones
    "IBAN_CODE",        # IBAN bancaires
    "NRP",              # Numéro INSEE (Numéro de Sécurité Sociale)
    "LOCATION",         # Adresses, villes
    "DATE_TIME",        # Dates
    "MEDICAL_LICENSE",  # Numéros RPPS médecins
    "FR_NIR",           # NIR Sécurité Sociale
]

logger = logging.getLogger(__name__)


@dataclass
class AnonymizationResult:
    """Résultat anonymisation"""
    anonymized_text: str
    entities_found: List[Dict]
    mapping: Dict[str, str]  # Mapping temporaire pour deanonymization
    confidence_min: float


class AnonymizationError(Exception):
    """Erreur pipeline anonymisation"""
    pass


async def anonymize_text(
    text: str,
    language: str = "fr",
    entities: Optional[List[str]] = None,
    context: Optional[str] = None
) -> AnonymizationResult:
    """
    Anonymise un texte via Presidio AVANT envoi LLM cloud (RGPD obligatoire).

    Args:
        text: Texte à anonymiser (peut contenir PII)
        language: Langue (défaut: 'fr')
        entities: Liste entités à détecter (défaut: FRENCH_ENTITIES)
        context: Context ID optionnel (pour debug, PAS stocké)

    Returns:
        AnonymizationResult avec texte anonymisé + mapping éphémère

    Raises:
        AnonymizationError: Si Presidio unavailable ou timeout

    IMPORTANT:
        Le mapping retourné est éphémère (mémoire uniquement).
        JAMAIS stocker le mapping en clair en base (voir addendum section 9.1).

    Example:
        >>> result = await anonymize_text("Dr. Dupont prescrit Doliprane à Marie.")
        >>> result.anonymized_text
        "Dr. [PERSON_1] prescrit Doliprane à [PERSON_2]."
        >>> result.mapping
        {"[PERSON_1]": "Dupont", "[PERSON_2]": "Marie"}
    """
    if not text or not text.strip():
        return AnonymizationResult(
            anonymized_text=text,
            entities_found=[],
            mapping={},
            confidence_min=1.0
        )

    entities_to_detect = entities or FRENCH_ENTITIES

    try:
        async with httpx.AsyncClient(timeout=PRESIDIO_TIMEOUT) as client:
            # 1. Analyse: détection entités sensibles
            analyze_response = await client.post(
                f"{PRESIDIO_ANALYZER_URL}/analyze",
                json={
                    "text": text,
                    "language": language,
                    "entities": entities_to_detect,
                }
            )
            analyze_response.raise_for_status()
            entities_found = analyze_response.json()

            if not entities_found:
                # Aucune PII détectée
                logger.debug("Aucune PII detectee dans le texte (context: %s)", context)
                return AnonymizationResult(
                    anonymized_text=text,
                    entities_found=[],
                    mapping={},
                    confidence_min=1.0
                )

            # 2. Anonymisation: remplacer entités par placeholders
            anonymize_response = await client.post(
                f"{PRESIDIO_ANONYMIZER_URL}/anonymize",
                json={
                    "text": text,
                    "analyzer_results": entities_found,
                    "anonymizers": {
                        "DEFAULT": {"type": "replace"},
                        "PERSON": {"type": "replace", "new_value": "[PERSON_{{{{ID}}}}]"},
                        "EMAIL_ADDRESS": {"type": "replace", "new_value": "[EMAIL_{{{{ID}}}}]"},
                        "PHONE_NUMBER": {"type": "replace", "new_value": "[PHONE_{{{{ID}}}}]"},
                        "IBAN_CODE": {"type": "replace", "new_value": "[IBAN_{{{{ID}}}}]"},
                        "LOCATION": {"type": "replace", "new_value": "[LOCATION_{{{{ID}}}}]"},
                    }
                }
            )
            anonymize_response.raise_for_status()
            anonymization_result = anonymize_response.json()

            anonymized_text = anonymization_result["text"]

            # 3. Construire mapping pour deanonymization (éphémère, JAMAIS stocké)
            mapping = _build_mapping(text, entities_found, anonymized_text)

            # 4. Calculer confidence minimale
            confidence_min = min(
                (entity.get("score", 1.0) for entity in entities_found),
                default=1.0
            )

            logger.info(
                "Anonymisation reussie: %d entites detectees (confidence_min=%.2f, context=%s)",
                len(entities_found), confidence_min, context
            )

            return AnonymizationResult(
                anonymized_text=anonymized_text,
                entities_found=entities_found,
                mapping=mapping,
                confidence_min=confidence_min
            )

    except httpx.HTTPError as e:
        logger.error("Erreur HTTP Presidio: %s", e)
        raise AnonymizationError(f"Presidio unavailable: {e}") from e
    except Exception as e:
        logger.error("Erreur anonymisation: %s", e)
        raise AnonymizationError(f"Anonymization failed: {e}") from e


async def deanonymize_text(anonymized_text: str, mapping: Dict[str, str]) -> str:
    """
    Deanonymise un texte via mapping éphémère.

    Args:
        anonymized_text: Texte anonymisé (avec placeholders)
        mapping: Mapping éphémère (placeholder → valeur originale)

    Returns:
        Texte original avec PII restaurée

    IMPORTANT:
        Le mapping DOIT provenir de anonymize_text() dans la MÊME session.
        JAMAIS charger un mapping depuis BDD (violation RGPD).

    Example:
        >>> deanonymized = await deanonymize_text(
        ...     "Dr. [PERSON_1] prescrit Doliprane.",
        ...     {"[PERSON_1]": "Dupont"}
        ... )
        >>> deanonymized
        "Dr. Dupont prescrit Doliprane."
    """
    if not mapping:
        return anonymized_text

    deanonymized = anonymized_text
    for placeholder, original_value in mapping.items():
        deanonymized = deanonymized.replace(placeholder, original_value)

    logger.debug("Deanonymisation reussie: %d placeholders restaures", len(mapping))
    return deanonymized


def _build_mapping(original_text: str, entities: List[Dict], anonymized_text: str) -> Dict[str, str]:
    """
    Construit mapping placeholder → valeur originale (éphémère).

    IMPORTANT: Ce mapping est éphémère (mémoire uniquement).
    JAMAIS stocker en base (voir addendum section 9.1).
    """
    mapping = {}

    # Extraire valeurs originales depuis positions dans entities
    for idx, entity in enumerate(entities, start=1):
        entity_type = entity["entity_type"]
        start = entity["start"]
        end = entity["end"]
        original_value = original_text[start:end]

        # Construire placeholder (doit matcher format anonymization)
        placeholder = f"[{entity_type}_{idx}]"
        mapping[placeholder] = original_value

    return mapping


# TODO (Story 2+): Implémenter healthcheck Presidio
async def healthcheck_presidio() -> bool:
    """
    Vérifie que Presidio Analyzer + Anonymizer sont disponibles.

    Returns:
        True si Presidio OK, False sinon
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            analyzer_health = await client.get(f"{PRESIDIO_ANALYZER_URL}/health")
            anonymizer_health = await client.get(f"{PRESIDIO_ANONYMIZER_URL}/health")
            return analyzer_health.status_code == 200 and anonymizer_health.status_code == 200
    except Exception as e:
        logger.error("Healthcheck Presidio failed: %s", e)
        return False
