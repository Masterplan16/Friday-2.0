#!/usr/bin/env python3
"""
Tests d'intégration pour le pipeline d'anonymisation Presidio (Story 1.5)

Tests avec Presidio RÉEL (pas de mocks). Requis services Docker up :
- presidio-analyzer:5001
- presidio-anonymizer:5002

AC5 : 100% des PII du dataset détectées, zéro fuite PII.
AC4 : Latence < seuils (500ms/500chars, 1s/2000chars, 2s/5000chars).

Usage:
    pytest tests/integration/test_anonymization_pipeline.py -v
    pytest tests/integration/test_anonymization_pipeline.py -v --presidio-live
"""

import asyncio
import json
from pathlib import Path

import pytest

# Skip tous les tests si Presidio pas disponible (sauf si --presidio-live)
pytest_plugins = []


def pytest_addoption(parser):
    parser.addoption(
        "--presidio-live",
        action="store_true",
        default=False,
        help="Run tests against live Presidio services (requires Docker up)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "presidio_live: mark test as requiring live Presidio services"
    )


@pytest.fixture(scope="module")
def pii_dataset():
    """Charge le dataset PII depuis fixtures"""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "pii_samples.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
async def presidio_available(request):
    """Vérifie que Presidio est disponible (skip tests si non)"""
    if not request.config.getoption("--presidio-live"):
        pytest.skip("Presidio tests disabled. Use --presidio-live to enable.")

    from agents.src.tools.anonymize import healthcheck_presidio

    is_available = await healthcheck_presidio()
    if not is_available:
        pytest.skip("Presidio services not available (Docker containers down?)")

    return True


@pytest.mark.asyncio
class TestAnonymizationPipelineSmoke:
    """
    Tests smoke sans Presidio (toujours exécutés en CI).

    Ces tests vérifient que le code est importable et structurellement correct
    SANS nécessiter les services Docker. Permet de détecter les erreurs de syntaxe
    ou d'import en CI/CD sans --presidio-live.
    """

    def test_anonymize_module_imports(self):
        """Vérifier que le module anonymize.py est importable"""
        from agents.src.tools.anonymize import (
            FRENCH_ENTITIES,
            AnonymizationError,
            anonymize_text,
            deanonymize_text,
        )

        # Si on arrive ici, les imports sont OK
        assert callable(anonymize_text)
        assert callable(deanonymize_text)
        assert len(FRENCH_ENTITIES) >= 10  # Au moins 10 entités françaises

    def test_french_entities_complete(self):
        """Vérifier que toutes les entités critiques sont présentes"""
        from agents.src.tools.anonymize import FRENCH_ENTITIES

        critical_entities = [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "IBAN_CODE",
            "FR_NIR",
            "CREDIT_CARD",
        ]

        for entity in critical_entities:
            assert entity in FRENCH_ENTITIES, f"{entity} manquante dans FRENCH_ENTITIES"

    def test_anonymization_result_model_structure(self):
        """Vérifier que AnonymizationResult est un Pydantic model valide"""
        from agents.src.tools.anonymize import AnonymizationResult
        from pydantic import BaseModel

        assert issubclass(AnonymizationResult, BaseModel)

        # Créer une instance test
        result = AnonymizationResult(
            anonymized_text="Test [PERSON_1]",
            entities_found=[],
            mapping={"[PERSON_1]": "Jean"},
            confidence_min=0.95,
        )

        assert result.anonymized_text == "Test [PERSON_1]"
        assert result.confidence_min == 0.95

    async def test_deanonymize_without_presidio(self):
        """Test deanonymize_text() qui ne nécessite pas Presidio"""
        from agents.src.tools.anonymize import deanonymize_text

        anonymized = "Dr. [PERSON_1] prescrit [MEDICATION] à [PERSON_2]."
        mapping = {
            "[PERSON_1]": "Dupont",
            "[PERSON_2]": "Marie",
            "[MEDICATION]": "Doliprane",
        }

        result = await deanonymize_text(anonymized, mapping)

        assert result == "Dr. Dupont prescrit Doliprane à Marie."

    def test_pii_dataset_is_valid_json(self):
        """Vérifier que le dataset PII est un JSON valide"""
        import json
        from pathlib import Path

        fixture_path = Path(__file__).parent.parent / "fixtures" / "pii_samples.json"

        with open(fixture_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)

        assert "samples" in dataset
        assert len(dataset["samples"]) >= 20  # Au moins 20 samples (8→20 enrichissement)

        # Vérifier structure de chaque sample
        for sample in dataset["samples"]:
            assert "id" in sample
            assert "input" in sample
            assert "entities" in sample
            assert "sensitive_values" in sample


@pytest.mark.asyncio
@pytest.mark.presidio_live
class TestAnonymizationPipelineIntegration:
    """Tests d'intégration avec Presidio réel (nécessite --presidio-live)"""

    async def test_presidio_services_are_up(self, presidio_available):
        """Vérifier que les services Presidio sont disponibles"""
        assert presidio_available is True

    async def test_all_pii_samples_are_anonymized(self, pii_dataset, presidio_available):
        """
        AC5 : 100% des PII du dataset doivent être détectées et anonymisées.
        CRITIQUE : Zéro faux négatif toléré.
        """
        from agents.src.tools.anonymize import anonymize_text

        failures = []

        for sample in pii_dataset["samples"]:
            sample_id = sample["id"]
            input_text = sample["input"]
            expected_entities = sample["entities"]
            sensitive_values = sample["sensitive_values"]

            # Anonymiser
            result = await anonymize_text(input_text)

            # Vérifier que TOUTES les entités attendues sont détectées
            detected_entity_types = {e["entity_type"] for e in result.entities_found}
            missing_entities = set(expected_entities) - detected_entity_types

            if missing_entities:
                failures.append(
                    {
                        "sample_id": sample_id,
                        "issue": "missing_entities",
                        "missing": list(missing_entities),
                        "detected": list(detected_entity_types),
                    }
                )

            # CRITIQUE : Vérifier ZÉRO fuite PII dans le texte anonymisé
            # Utiliser word boundaries pour éviter faux positifs (ex: "Jean" vs "je")
            import re

            for sensitive_value in sensitive_values:
                # Échapper les caractères spéciaux regex et utiliser word boundaries
                escaped_value = re.escape(sensitive_value)
                # Pattern avec word boundaries (\b) pour match exact
                pattern = r"\b" + escaped_value + r"\b"

                if re.search(pattern, result.anonymized_text, re.IGNORECASE):
                    failures.append(
                        {
                            "sample_id": sample_id,
                            "issue": "pii_leak",
                            "leaked_value": sensitive_value,
                            "anonymized_text": result.anonymized_text,
                        }
                    )

        # Échec si une seule PII a fuité ou n'a pas été détectée
        if failures:
            failure_msg = f"\n\n{'=' * 80}\n"
            failure_msg += "❌ ANONYMIZATION FAILURES (AC5 violated)\n"
            failure_msg += f"{'=' * 80}\n\n"
            for idx, failure in enumerate(failures, 1):
                failure_msg += f"[{idx}] Sample: {failure['sample_id']}\n"
                failure_msg += f"    Issue: {failure['issue']}\n"
                if failure["issue"] == "missing_entities":
                    failure_msg += f"    Missing: {failure['missing']}\n"
                    failure_msg += f"    Detected: {failure['detected']}\n"
                elif failure["issue"] == "pii_leak":
                    failure_msg += f"    LEAKED VALUE: {failure['leaked_value']}\n"
                    failure_msg += f"    Anonymized text: {failure['anonymized_text'][:100]}...\n"
                failure_msg += "\n"

            pytest.fail(failure_msg)

    async def test_anonymization_preserves_context(self, presidio_available):
        """Vérifier que l'anonymisation préserve le contexte (sens du texte)"""
        from agents.src.tools.anonymize import anonymize_text, deanonymize_text

        original = "Dr. Martin prescrit Doliprane à Jean Dupont pour douleurs cervicales."

        result = await anonymize_text(original)

        # Le texte anonymisé doit contenir la structure
        assert "prescrit" in result.anonymized_text
        assert "Doliprane" in result.anonymized_text  # Médicament pas PII
        assert "douleurs cervicales" in result.anonymized_text

        # Deanonymisation doit restaurer l'original
        deanonymized = await deanonymize_text(result.anonymized_text, result.mapping)

        assert deanonymized == original


@pytest.mark.asyncio
@pytest.mark.presidio_live
class TestAnonymizationLatency:
    """Tests de latence (AC4)"""

    async def test_latency_500_chars(self, presidio_available):
        """AC4 : Email 500 chars < 500ms"""
        import time

        from agents.src.tools.anonymize import anonymize_text

        text = (
            "Jean Dupont (jean.dupont@email.fr, 06 12 34 56 78) habite au 123 rue de la Paix 75001 Paris. "
            * 5
        )
        assert len(text) <= 500

        start = time.monotonic()
        await anonymize_text(text)
        latency_ms = (time.monotonic() - start) * 1000

        assert latency_ms < 500, f"Latency {latency_ms:.0f}ms exceeds 500ms threshold for 500 chars"

    async def test_latency_2000_chars(self, presidio_available):
        """AC4 : Email 2000 chars < 1s"""
        import time

        from agents.src.tools.anonymize import anonymize_text

        text = (
            "Jean Dupont (jean.dupont@email.fr, 06 12 34 56 78) habite au 123 rue de la Paix 75001 Paris. "
            * 20
        )
        assert len(text) <= 2000

        start = time.monotonic()
        await anonymize_text(text)
        latency_ms = (time.monotonic() - start) * 1000

        assert (
            latency_ms < 1000
        ), f"Latency {latency_ms:.0f}ms exceeds 1000ms threshold for 2000 chars"

    async def test_latency_5000_chars(self, presidio_available):
        """AC4 : Document 5000 chars < 2s"""
        import time

        from agents.src.tools.anonymize import anonymize_text

        text = (
            "Jean Dupont (jean.dupont@email.fr, 06 12 34 56 78) habite au 123 rue de la Paix 75001 Paris. "
            * 50
        )
        assert len(text) <= 5000

        start = time.monotonic()
        await anonymize_text(text)
        latency_ms = (time.monotonic() - start) * 1000

        assert (
            latency_ms < 2000
        ), f"Latency {latency_ms:.0f}ms exceeds 2000ms threshold for 5000 chars"
