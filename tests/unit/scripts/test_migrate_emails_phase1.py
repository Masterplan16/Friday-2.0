"""
Tests unitaires pour migrate_emails.py Phase 1 (Classification Claude + Presidio)

Tests:
- classify_email() avec mock Claude
- _parse_classification() avec différents formats JSON
- _track_api_usage() pour vérification calculs coûts
- anonymize_for_classification() avec mock Presidio

Story 6.4 Subtask 2.5
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock environment variables AVANT import de migrate_emails
# (car le module valide POSTGRES_DSN et ANTHROPIC_API_KEY à l'import)
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-12345")


@pytest.fixture
def mock_migration_state():
    """Mock MigrationState pour tests"""
    from datetime import datetime
    from scripts.migrate_emails import MigrationState

    return MigrationState(
        total_emails=1000,
        processed=0,
        failed=0,
        last_email_id=None,
        started_at=datetime.now(),
        last_checkpoint_at=datetime.now(),
        estimated_cost=0.0,
        estimated_time_remaining=None,
    )


@pytest.fixture
def mock_migrator(mock_migration_state):
    """Mock EmailMigrator pour tests"""
    from scripts.migrate_emails import EmailMigrator

    migrator = EmailMigrator(dry_run=False)
    migrator.state = mock_migration_state
    migrator.logger = MagicMock()
    migrator.llm_client = AsyncMock()
    migrator.db = AsyncMock()
    return migrator


class TestParseClassification:
    """Tests pour _parse_classification()"""

    def test_parse_valid_json(self, mock_migrator):
        """JSON valide standard"""
        response = json.dumps(
            {
                "category": "pro",
                "priority": "high",
                "confidence": 0.95,
                "keywords": ["rdv", "docteur"],
            }
        )

        result = mock_migrator._parse_classification(response)

        assert result["category"] == "pro"
        assert result["priority"] == "high"
        assert result["confidence"] == 0.95
        assert result["keywords"] == ["rdv", "docteur"]

    def test_parse_json_with_markdown(self, mock_migrator):
        """JSON wrapped dans ```json ... ```"""
        response = """```json
{
  "category": "financial",
  "priority": "medium",
  "confidence": 0.88,
  "keywords": ["facture", "paiement"]
}
```"""

        result = mock_migrator._parse_classification(response)

        assert result["category"] == "financial"
        assert result["confidence"] == 0.88

    def test_parse_json_confidence_normalization(self, mock_migrator):
        """Confidence hors limites [0, 1] → normalisée"""
        response = json.dumps(
            {"category": "test", "priority": "low", "confidence": 1.5, "keywords": []}
        )

        result = mock_migrator._parse_classification(response)

        # Confidence 1.5 → clampé à 1.0
        assert result["confidence"] == 1.0

    def test_parse_invalid_json_raises(self, mock_migrator):
        """JSON invalide → ValueError"""
        response = "Ceci n'est pas du JSON"

        with pytest.raises(ValueError, match="pas JSON"):
            mock_migrator._parse_classification(response)

    def test_parse_missing_fields_raises(self, mock_migrator):
        """Champs manquants → ValueError"""
        response = json.dumps({"category": "test"})  # Manque priority, confidence, keywords

        with pytest.raises(ValueError, match="Champs manquants"):
            mock_migrator._parse_classification(response)

    def test_parse_invalid_types_raises(self, mock_migrator):
        """Types invalides → ValueError"""
        response = json.dumps(
            {
                "category": "test",
                "priority": "low",
                "confidence": "pas un nombre",  # Type invalide
                "keywords": [],
            }
        )

        with pytest.raises(ValueError, match="confidence doit être numérique"):
            mock_migrator._parse_classification(response)


class TestTrackApiUsage:
    """Tests pour _track_api_usage()"""

    def test_track_basic_usage(self, mock_migrator):
        """Track usage basique"""
        usage = {"input_tokens": 500, "output_tokens": 100}

        mock_migrator._track_api_usage(usage)

        # 500 tokens input × $3/1M = $0.0015
        # 100 tokens output × $15/1M = $0.0015
        # Total = $0.003
        assert pytest.approx(mock_migrator.state.estimated_cost, abs=0.0001) == 0.003

    def test_track_multiple_calls(self, mock_migrator):
        """Plusieurs appels → coûts cumulatifs"""
        usage1 = {"input_tokens": 500, "output_tokens": 100}
        usage2 = {"input_tokens": 600, "output_tokens": 150}

        mock_migrator._track_api_usage(usage1)
        mock_migrator._track_api_usage(usage2)

        # Call 1: 500×3/1M + 100×15/1M = 0.003
        # Call 2: 600×3/1M + 150×15/1M = 0.0018 + 0.00225 = 0.00405
        # Total = 0.00705
        assert pytest.approx(mock_migrator.state.estimated_cost, abs=0.0001) == 0.00705

    def test_track_missing_tokens(self, mock_migrator):
        """Usage sans tokens → 0 coût"""
        usage = {}

        mock_migrator._track_api_usage(usage)

        assert mock_migrator.state.estimated_cost == 0.0


class TestAnonymizeForClassification:
    """Tests pour anonymize_for_classification()"""

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_anonymize_success(self, mock_anonymize, mock_migrator):
        """Anonymisation réussie"""
        from tools.anonymize import AnonymizationResult

        # Mock anonymize_text
        # entities_found doit être List[Dict] (format API Presidio)
        mock_result = AnonymizationResult(
            anonymized_text="Sujet: RDV [PERSON_1]\nDe: [EMAIL_1]",
            entities_found=[
                {"entity_type": "PERSON", "start": 10, "end": 20, "score": 0.95},
                {"entity_type": "EMAIL_ADDRESS", "start": 30, "end": 45, "score": 0.98},
            ],
            confidence_min=0.95,
            mapping={"[PERSON_1]": "Dr. Martin", "[EMAIL_1]": "test@example.com"},
        )
        mock_anonymize.return_value = mock_result

        email = {
            "message_id": "<test@example.com>",
            "subject": "RDV Dr. Martin",
            "sender": "test@example.com",
            "body_text": "Bonjour...",
        }

        result = await mock_migrator.anonymize_for_classification(email)

        # Vérifier appel anonymize_text
        mock_anonymize.assert_called_once()
        assert "[PERSON_1]" in result
        assert "[EMAIL_1]" in result

    @pytest.mark.asyncio
    async def test_anonymize_dry_run(self, mock_migrator):
        """Dry run → pas d'anonymisation"""
        mock_migrator.dry_run = True

        email = {
            "message_id": "<test@example.com>",
            "subject": "Test",
            "sender": "test@example.com",
            "body_text": "Content",
        }

        result = await mock_migrator.anonymize_for_classification(email)

        # Dry run → texte brut (pas d'anonymisation)
        assert "Test" in result
        assert "test@example.com" in result


class TestClassifyEmail:
    """Tests pour classify_email()"""

    @pytest.mark.asyncio
    async def test_classify_dry_run(self, mock_migrator):
        """Dry run → classification simulée"""
        mock_migrator.dry_run = True

        email = {
            "message_id": "<test@example.com>",
            "subject": "Test",
            "sender": "test@example.com",
            "body_text": "Content",
        }

        result = await mock_migrator.classify_email(email)

        assert result["category"] == "test"
        assert result["priority"] == "low"
        assert result["confidence"] == 0.95

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_classify_real_call(self, mock_anonymize, mock_migrator):
        """Vrai appel Claude (mocké)"""
        from adapters.llm import LLMResponse
        from tools.anonymize import AnonymizationResult

        # Mock anonymize_text
        mock_anonymize.return_value = AnonymizationResult(
            anonymized_text="Anonymized content",
            entities_found=[],
            confidence_min=1.0,
            mapping={},
        )

        # Mock Claude response
        mock_migrator.llm_client.complete_raw.return_value = LLMResponse(
            content=json.dumps(
                {
                    "category": "pro",
                    "priority": "urgent",
                    "confidence": 0.92,
                    "keywords": ["rdv", "urgence"],
                }
            ),
            model="claude-sonnet-4-5-20250929",
            usage={"input_tokens": 450, "output_tokens": 80},
            anonymization_applied=False,
        )

        email = {
            "message_id": "<test@example.com>",
            "subject": "RDV urgent",
            "sender": "test@example.com",
            "body_text": "J'ai besoin d'un RDV urgent...",
        }

        result = await mock_migrator.classify_email(email)

        # Vérifier classification
        assert result["category"] == "pro"
        assert result["priority"] == "urgent"
        assert result["confidence"] == 0.92
        assert "rdv" in result["keywords"]

        # Vérifier appel complete_raw
        mock_migrator.llm_client.complete_raw.assert_called_once()

        # Vérifier tracking coût
        # 450 input × 3/1M + 80 output × 15/1M = 0.00135 + 0.0012 = 0.00255
        assert pytest.approx(mock_migrator.state.estimated_cost, abs=0.0001) == 0.00255

    @pytest.mark.asyncio
    @patch("scripts.migrate_emails.anonymize_text")
    async def test_classify_retry_on_error(self, mock_anonymize, mock_migrator):
        """Retry exponentiel en cas d'erreur"""
        from tools.anonymize import AnonymizationResult

        mock_anonymize.return_value = AnonymizationResult(
            anonymized_text="Content", entities_found=[], confidence_min=1.0, mapping={}
        )

        # Premier appel échoue, deuxième réussit
        mock_migrator.llm_client.complete_raw.side_effect = [
            Exception("API error"),
            MagicMock(
                content=json.dumps(
                    {"category": "test", "priority": "low", "confidence": 0.5, "keywords": []}
                ),
                usage={"input_tokens": 100, "output_tokens": 50},
            ),
        ]

        email = {"message_id": "<test@example.com>", "subject": "Test", "sender": "t@t.com", "body_text": "C"}

        # Doit retry 1 fois et réussir
        with patch("asyncio.sleep", new_callable=AsyncMock):  # Skip sleep delays
            result = await mock_migrator.classify_email(email)

        assert result["category"] == "test"
        assert mock_migrator.llm_client.complete_raw.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
