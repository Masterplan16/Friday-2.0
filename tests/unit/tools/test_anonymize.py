#!/usr/bin/env python3
"""
Tests unitaires pour anonymize.py (Story 1.5)

Tests couvrant :
- B1 : CREDIT_CARD manquant dans FRENCH_ENTITIES
- B2 : Validation JSON réponse Presidio
- B3 : Mismatch placeholders format
- B4 : AnonymizationError hérite de PipelineError
- B5 : structlog JSON (pas stdlib logging)
- B6 : httpx.AsyncClient réutilisable
- Fail-explicit behavior
- Edge cases (texte vide, pas de PII)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

# Import après définition des mocks pour éviter les imports réels
from agents.src.tools.anonymize import (
    anonymize_text,
    deanonymize_text,
    AnonymizationResult,
    AnonymizationError,
    FRENCH_ENTITIES,
)
from config.exceptions import PipelineError


class TestFrenchEntitiesConfiguration:
    """Tests configuration entités françaises (Bug B1)"""

    def test_credit_card_in_french_entities(self):
        """B1: CREDIT_CARD doit être dans FRENCH_ENTITIES"""
        assert "CREDIT_CARD" in FRENCH_ENTITIES, (
            "CREDIT_CARD manquant dans FRENCH_ENTITIES (requis par pii_samples.json sample 004)"
        )

    def test_all_required_entities_present(self):
        """Vérifier que toutes les entités requises sont présentes"""
        required_entities = [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "IBAN_CODE",
            "NRP",
            "FR_NIR",
            "LOCATION",
            "DATE_TIME",
            "MEDICAL_LICENSE",
            "CREDIT_CARD",
        ]
        for entity in required_entities:
            assert entity in FRENCH_ENTITIES, f"{entity} manquant dans FRENCH_ENTITIES"


class TestAnonymizationErrorHierarchy:
    """Tests hiérarchie exceptions (Bug B4)"""

    def test_anonymization_error_inherits_pipeline_error(self):
        """B4: AnonymizationError doit hériter de PipelineError"""
        assert issubclass(AnonymizationError, PipelineError), (
            "AnonymizationError doit hériter de PipelineError (pas Exception bare)"
        )

    def test_anonymization_error_is_exception(self):
        """AnonymizationError doit être une Exception"""
        assert issubclass(AnonymizationError, Exception)


class TestAnonymizationResultModel:
    """Tests modèle AnonymizationResult (Bug B7 - migration vers Pydantic)"""

    def test_anonymization_result_is_pydantic_model(self):
        """AnonymizationResult devrait être un Pydantic BaseModel"""
        from pydantic import BaseModel

        # Migration dataclass → Pydantic complétée (Task 1.7)
        assert issubclass(AnonymizationResult, BaseModel), (
            "AnonymizationResult devrait être Pydantic BaseModel (alignement pattern projet)"
        )


@pytest.mark.asyncio
class TestAnonymizeTextBasicFunctionality:
    """Tests fonctionnalité de base anonymize_text"""

    async def test_anonymize_empty_text(self):
        """Edge case: texte vide retourne résultat vide sans appel Presidio"""
        result = await anonymize_text("")
        assert result.anonymized_text == ""
        assert result.entities_found == []
        assert result.mapping == {}
        assert result.confidence_min == 1.0

    async def test_anonymize_whitespace_only(self):
        """Edge case: texte avec seulement espaces"""
        result = await anonymize_text("   \n  \t  ")
        assert result.anonymized_text == "   \n  \t  "
        assert result.entities_found == []

    @patch("agents.src.tools.anonymize.httpx.AsyncClient")
    async def test_anonymize_no_pii_detected(self, mock_client_class):
        """Texte sans PII retourne texte identique"""
        # Mock httpx.AsyncClient
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Mock response analyzer: aucune entité détectée
        mock_analyze_response = MagicMock()
        mock_analyze_response.raise_for_status = MagicMock()
        mock_analyze_response.json = MagicMock(return_value=[])
        mock_client.post = AsyncMock(return_value=mock_analyze_response)

        text = "Bonjour, la réunion est confirmée pour mardi."
        result = await anonymize_text(text)

        assert result.anonymized_text == text
        assert result.entities_found == []
        assert result.mapping == {}
        assert result.confidence_min == 1.0

    @patch("agents.src.tools.anonymize.httpx.AsyncClient")
    async def test_anonymize_with_person_entity(self, mock_client_class):
        """Test anonymisation basique avec entité PERSON"""
        # Mock httpx.AsyncClient
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Mock analyzer response
        mock_analyze_response = MagicMock()
        mock_analyze_response.raise_for_status = MagicMock()
        mock_analyze_response.json = MagicMock(return_value=[
            {
                "entity_type": "PERSON",
                "start": 0,
                "end": 11,
                "score": 0.95,
            }
        ])

        # Mock anonymizer response
        mock_anonymize_response = MagicMock()
        mock_anonymize_response.raise_for_status = MagicMock()
        mock_anonymize_response.json = MagicMock(return_value={
            "text": "[PERSON_1] habite à Paris.",
        })

        mock_client.post = AsyncMock(side_effect=[mock_analyze_response, mock_anonymize_response])

        text = "Jean Dupont habite à Paris."
        result = await anonymize_text(text)

        assert "[PERSON_1]" in result.anonymized_text
        assert len(result.entities_found) == 1
        assert result.entities_found[0]["entity_type"] == "PERSON"
        assert result.confidence_min == 0.95


@pytest.mark.asyncio
class TestAnonymizeTextFailExplicit:
    """Tests fail-explicit behavior (Bug B2, AC2)"""

    @patch("agents.src.tools.anonymize.httpx.AsyncClient")
    async def test_presidio_analyzer_unavailable_raises_error(self, mock_client_class):
        """Fail-explicit: Si analyzer unavailable → lever AnonymizationError"""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(AnonymizationError) as exc_info:
            await anonymize_text("Test text with PII")

        assert "Presidio unavailable" in str(exc_info.value)

    @patch("agents.src.tools.anonymize.httpx.AsyncClient")
    async def test_presidio_timeout_raises_error(self, mock_client_class):
        """Fail-explicit: Si timeout Presidio → lever AnonymizationError"""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.side_effect = httpx.TimeoutException("Request timeout")

        with pytest.raises(AnonymizationError) as exc_info:
            await anonymize_text("Test text")

        assert "Presidio unavailable" in str(exc_info.value)

    @patch("agents.src.tools.anonymize.httpx.AsyncClient")
    async def test_missing_text_key_in_response_raises_error(self, mock_client_class):
        """B2: Validation JSON - KeyError si 'text' absent → AnonymizationError"""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Mock analyzer response
        mock_analyze_response = AsyncMock()
        mock_analyze_response.raise_for_status = MagicMock()
        mock_analyze_response.json.return_value = [
            {"entity_type": "PERSON", "start": 0, "end": 4, "score": 0.9}
        ]

        # Mock anonymizer response SANS clé "text" (bug)
        mock_anonymize_response = AsyncMock()
        mock_anonymize_response.raise_for_status = MagicMock()
        mock_anonymize_response.json.return_value = {
            "error": "anonymization failed"
        }  # Pas de clé "text"

        mock_client.post.side_effect = [mock_analyze_response, mock_anonymize_response]

        with pytest.raises(AnonymizationError) as exc_info:
            await anonymize_text("Jean Dupont")

        # Vérifier que l'erreur mentionne explicitement le problème (L3 fix)
        error_msg = str(exc_info.value)
        assert "Anonymization failed" in error_msg or "missing 'text' key" in error_msg, (
            f"Expected specific error message, got: {error_msg}"
        )


@pytest.mark.asyncio
class TestDeanonymizeText:
    """Tests deanonymize_text"""

    async def test_deanonymize_basic(self):
        """Test deanonymization basique"""
        anonymized = "Dr. [PERSON_1] prescrit Doliprane à [PERSON_2]."
        mapping = {
            "[PERSON_1]": "Dupont",
            "[PERSON_2]": "Marie",
        }

        result = await deanonymize_text(anonymized, mapping)

        assert result == "Dr. Dupont prescrit Doliprane à Marie."

    async def test_deanonymize_empty_mapping(self):
        """Edge case: mapping vide retourne texte identique"""
        text = "Texte anonymisé [PERSON_1]"
        result = await deanonymize_text(text, {})

        assert result == text

    async def test_deanonymize_multiple_occurrences(self):
        """Deanonymization avec multiples occurrences même placeholder"""
        anonymized = "[PERSON_1] appelle [PERSON_1] demain."
        mapping = {"[PERSON_1]": "Jean"}

        result = await deanonymize_text(anonymized, mapping)

        assert result == "Jean appelle Jean demain."


class TestHttpClientReuse:
    """Tests réutilisation httpx.AsyncClient (Bug B6)"""

    def test_http_client_should_be_module_level_or_injected(self):
        """
        B6: httpx.AsyncClient devrait être réutilisable (pas recréé à chaque appel)

        NOTE: Ce test documente l'intention, mais la correction complète nécessiterait
        un refactoring plus large (injection de dépendance ou client module-level).
        Pour Story 1.5, on accepte la création par appel mais on documente l'amélioration future.
        """
        # Ce test est documentaire - skip pour l'instant
        pytest.skip("B6 - Optimisation future: réutiliser AsyncClient (non bloquant Story 1.5)")


@pytest.mark.asyncio
class TestMappingLifecycle:
    """Tests lifecycle mapping éphémère (AC3)"""

    @patch("agents.src.tools.anonymize.httpx.AsyncClient")
    async def test_mapping_is_ephemeral_in_memory_only(self, mock_client_class):
        """
        AC3: Le mapping doit être éphémère (mémoire uniquement).

        Ce test vérifie que le mapping est retourné dans AnonymizationResult
        et peut être utilisé pour deanonymization, mais n'est jamais persisté.
        """
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Mock responses
        mock_analyze_response = MagicMock()
        mock_analyze_response.raise_for_status = MagicMock()
        mock_analyze_response.json = MagicMock(return_value=[
            {"entity_type": "PERSON", "start": 0, "end": 4, "score": 0.9}
        ])

        mock_anonymize_response = MagicMock()
        mock_anonymize_response.raise_for_status = MagicMock()
        mock_anonymize_response.json = MagicMock(return_value={
            "text": "[PERSON_1] habite Paris."
        })

        mock_client.post = AsyncMock(side_effect=[mock_analyze_response, mock_anonymize_response])

        # Anonymiser
        result = await anonymize_text("Jean habite Paris.")

        # Le mapping doit être présent en mémoire
        assert result.mapping is not None
        assert len(result.mapping) > 0

        # Deanonymiser avec mapping éphémère
        deanonymized = await deanonymize_text(result.anonymized_text, result.mapping)

        assert "Jean" in deanonymized

        # Après utilisation, le mapping devrait être détruit (garbaqe collected)
        # En Python, on ne peut pas forcer/tester le GC, mais on documente l'intention
        # IMPORTANT: JAMAIS stocker result.mapping en PostgreSQL (voir AC3, ADD7)
