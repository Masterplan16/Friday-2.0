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
from typing import Dict, List, Optional

import httpx
import structlog
from pydantic import BaseModel, Field

from config.exceptions import PipelineError

# Configuration Presidio (via env vars)
# Note: Port 3000 = port interne container (5001/5002 = ports HOST)
PRESIDIO_ANALYZER_URL = os.getenv("PRESIDIO_ANALYZER_URL", "http://presidio-analyzer:3000")
PRESIDIO_ANONYMIZER_URL = os.getenv("PRESIDIO_ANONYMIZER_URL", "http://presidio-anonymizer:3000")
PRESIDIO_TIMEOUT = int(os.getenv("PRESIDIO_TIMEOUT", "30"))

# Entités sensibles à détecter (France)
# Note: Utilise seulement les recognizers supportés par Presidio + spaCy FR
# Les entités custom (IBAN_CODE, FR_NIR, etc.) nécessiteraient des recognizers custom
FRENCH_ENTITIES = [
    "PERSON",  # Noms, prénoms (spaCy FR)
    "EMAIL_ADDRESS",  # Emails (built-in Presidio)
    "PHONE_NUMBER",  # Téléphones (built-in Presidio)
    # Entités FR custom désactivées temporairement (nécessitent recognizers custom):
    # "IBAN_CODE", "NRP", "LOCATION", "DATE_TIME", "MEDICAL_LICENSE", "FR_NIR", "CREDIT_CARD"
]

logger = structlog.get_logger(__name__)

# Module-level HTTP client (réutilisable, fix Bug B6)
# Créé au premier appel, réutilisé ensuite (performance optimisation)
_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    """
    Retourne un httpx.AsyncClient.

    TEMPORARY FIX: Create new client each time to avoid connection pool issues.
    Performance impact minimal (~5ms overhead vs connection errors).
    """
    # Always create new client to avoid connection pool state issues
    return httpx.AsyncClient(timeout=PRESIDIO_TIMEOUT)


async def close_http_client():
    """
    Ferme le client HTTP module-level (à appeler au shutdown).

    Usage:
        await close_http_client()
    """
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


class AnonymizationResult(BaseModel):
    """
    Résultat anonymisation (Pydantic v2 BaseModel pour alignement pattern projet).

    Migration dataclass → Pydantic (Subtask 1.7, Bug B7).
    """

    anonymized_text: str = Field(..., description="Texte anonymisé avec placeholders")
    entities_found: List[Dict] = Field(default_factory=list, description="Entités PII détectées")
    mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping éphémère placeholder → valeur originale (JAMAIS persisté)",
    )
    confidence_min: float = Field(..., ge=0.0, le=1.0, description="Confidence minimale (0.0-1.0)")


class AnonymizationError(PipelineError):
    """Erreur pipeline anonymisation (hérite de PipelineError selon hiérarchie Story 1.2)"""


async def anonymize_text(
    text: str,
    language: str = "fr",
    entities: Optional[List[str]] = None,
    context: Optional[str] = None,
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
        NotImplementedError: Si anonymisation pas configurée/disponible (AC2)

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
    # AC2 — Fail-explicit: Vérifier que Presidio est configuré
    if not PRESIDIO_ANALYZER_URL or not PRESIDIO_ANONYMIZER_URL:
        raise NotImplementedError(
            "Presidio anonymization not configured. "
            "PRESIDIO_ANALYZER_URL and PRESIDIO_ANONYMIZER_URL must be set. "
            "Cannot proceed with LLM call without anonymization (RGPD compliance)."
        )

    if not text or not text.strip():
        return AnonymizationResult(
            anonymized_text=text, entities_found=[], mapping={}, confidence_min=1.0
        )

    entities_to_detect = entities or FRENCH_ENTITIES

    print(f"[DEBUG] anonymize_text called, text_length={len(text)}", flush=True)

    client = None
    try:
        print("[DEBUG] Creating HTTP client...", flush=True)
        # Create new client for this request
        client = _get_http_client()
        print(f"[DEBUG] HTTP client created: {client}", flush=True)

        # DEBUG: Test connection first
        print("[DEBUG] Testing Presidio connection...", flush=True)
        try:
            import socket

            # Parse URL to get host and port
            host = PRESIDIO_ANALYZER_URL.split("://")[1].split(":")[0]
            port = 3000

            print(f"[DEBUG] Resolving DNS for {host}...", flush=True)
            # Resolve DNS
            ip = socket.gethostbyname(host)
            print(f"[DEBUG] DNS resolved: {host} -> {ip}", flush=True)

            # Test TCP connection
            print(f"[DEBUG] Testing TCP connection to {ip}:{port}...", flush=True)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((ip, port))
            sock.close()
            print(f"[DEBUG] TCP test result: {result} (0=success)", flush=True)
        except Exception as conn_test_error:
            print(f"[DEBUG] Connection test failed: {conn_test_error}", flush=True)

        # DEBUG: Log connection attempt details
        analyzer_url = f"{PRESIDIO_ANALYZER_URL}/analyze"
        print(f"[DEBUG] About to POST to {analyzer_url}...", flush=True)

        # 1. Analyse: détection entités sensibles
        try:
            print("[DEBUG] Calling client.post()...", flush=True)
            analyze_response = await client.post(
                analyzer_url,
                json={
                    "text": text,
                    "language": language,
                    "entities": entities_to_detect,
                },
            )
            print(f"[DEBUG] POST response: {analyze_response.status_code}", flush=True)
            analyze_response.raise_for_status()
            entities_found = analyze_response.json()
        except Exception as analyze_error:
            print(
                f"[DEBUG] POST failed: {type(analyze_error).__name__}: {analyze_error}", flush=True
            )
            raise

        if not entities_found:
            # Aucune PII détectée
            logger.debug("no_pii_detected", context=context)
            return AnonymizationResult(
                anonymized_text=text, entities_found=[], mapping={}, confidence_min=1.0
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
                },
            },
        )
        anonymize_response.raise_for_status()
        anonymization_result = anonymize_response.json()

        # Validation JSON : vérifier que la clé "text" est présente (Bug B2)
        if "text" not in anonymization_result:
            raise AnonymizationError(
                f"Invalid Presidio anonymizer response: missing 'text' key. "
                f"Response: {anonymization_result}"
            )

        anonymized_text = anonymization_result["text"]

        # 3. Construire mapping pour deanonymization (éphémère, JAMAIS stocké)
        mapping = _build_mapping(text, entities_found, anonymized_text)

        # 4. Calculer confidence minimale (M2 fix: validation robuste)
        try:
            confidence_min = min(
                (entity.get("score", 1.0) for entity in entities_found), default=1.0
            )
        except (TypeError, ValueError) as e:
            # Fallback si entities_found malformé
            logger.warning(
                "confidence_calculation_failed",
                error=str(e),
                message="Using default confidence 1.0",
            )
            confidence_min = 1.0

        logger.info(
            "anonymization_success",
            entities_count=len(entities_found),
            confidence_min=confidence_min,
            context=context,
        )

        return AnonymizationResult(
            anonymized_text=anonymized_text,
            entities_found=entities_found,
            mapping=mapping,
            confidence_min=confidence_min,
        )

    except httpx.HTTPError as e:
        logger.error("presidio_http_error", error=str(e), error_type=type(e).__name__)
        raise AnonymizationError(f"Presidio unavailable: {e}") from e
    except Exception as e:
        logger.error("anonymization_failed", error=str(e), error_type=type(e).__name__)
        raise AnonymizationError(f"Anonymization failed: {e}") from e
    finally:
        # Close client to avoid resource leaks (new client per request)
        if client is not None:
            await client.aclose()


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

    logger.debug("deanonymization_success", placeholders_count=len(mapping))
    return deanonymized


def _build_mapping(
    original_text: str, entities: List[Dict], anonymized_text: str
) -> Dict[str, str]:
    """
    Construit mapping placeholder → valeur originale (éphémère).

    IMPORTANT: Ce mapping est éphémère (mémoire uniquement).
    JAMAIS stocker en base (voir addendum section 9.1).

    Note (Bug B3): Parse le texte anonymisé pour extraire les placeholders réels
    générés par Presidio au lieu de deviner leur format.
    """
    import re

    mapping = {}

    # Extraire valeurs originales depuis positions dans entities
    entity_values = []
    for entity in entities:
        start = entity["start"]
        end = entity["end"]
        original_value = original_text[start:end]
        entity_type = entity["entity_type"]
        entity_values.append((entity_type, original_value))

    # Extraire les placeholders réels du texte anonymisé (format: [TYPE_ID])
    # Regex pour capturer les placeholders générés par Presidio
    placeholder_pattern = r"\[([A-Z_]+)_(\d+)\]"
    placeholders_found = re.findall(placeholder_pattern, anonymized_text)

    # Construire le mapping en associant les placeholders trouvés aux valeurs originales
    # On assume que l'ordre des placeholders correspond à l'ordre des entités
    for idx, (entity_type, original_value) in enumerate(entity_values):
        # Trouver le placeholder correspondant dans le texte anonymisé
        # Format attendu: [ENTITY_TYPE_ID]
        if idx < len(placeholders_found):
            placeholder_type, placeholder_id = placeholders_found[idx]
            placeholder = f"[{placeholder_type}_{placeholder_id}]"
            mapping[placeholder] = original_value
        else:
            # Fallback: utiliser format générique si parsing échoue
            # ⚠️ WARNING: Ce fallback peut causer deanonymization incorrecte
            # si le format réel de Presidio diffère
            placeholder = f"[{entity_type}_{idx + 1}]"
            mapping[placeholder] = original_value

            logger.warning(
                "mapping_fallback_used",
                entity_type=entity_type,
                entity_index=idx,
                placeholder=placeholder,
                message=(
                    "⚠️ Fallback mapping format - "
                    "deanonymization peut échouer si format Presidio diffère"
                ),
            )

    return mapping


async def healthcheck_presidio() -> bool:
    """
    Vérifie que Presidio Analyzer + Anonymizer sont disponibles.

    Returns:
        True si Presidio OK, False sinon

    Note:
        Utilisé par services/gateway/healthcheck.py pour monitoring système.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            analyzer_health = await client.get(f"{PRESIDIO_ANALYZER_URL}/health")
            anonymizer_health = await client.get(f"{PRESIDIO_ANONYMIZER_URL}/health")
            return analyzer_health.status_code == 200 and anonymizer_health.status_code == 200
    except Exception as e:
        logger.error("presidio_healthcheck_failed", error=str(e))
        return False
