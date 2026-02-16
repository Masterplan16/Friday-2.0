"""Tests Unitaires - Event Detector (Story 7.1) - 15 tests"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from agents.src.agents.calendar.event_detector import extract_events_from_email
from agents.src.core.models import Casquette

@pytest.fixture
def mock_client():
    return AsyncMock()

@pytest.fixture
def mock_response(request):
    response = MagicMock()
    response.content = [MagicMock(text=request.param)]
    return response

@pytest.mark.asyncio
@pytest.mark.parametrize("mock_response", ['''{
"events_detected": [{
    "title": "Consultation cardiologie Dr Leblanc",
    "start_datetime": "2026-02-13T14:30:00",
    "end_datetime": "2026-02-13T15:00:00",
    "location": null,
    "participants": ["Dr Leblanc"],
    "event_type": "medical",
    "casquette": "medecin",
    "confidence": 0.95,
    "context": "RDV cardio"
}],
"confidence_overall": 0.95
}'''], indirect=True)
async def test_extract_event_medical(mock_client, mock_response):
    """Test AC1: Extraction événement medical."""
    mock_client.messages.create.return_value = mock_response
    with patch("agents.src.agents.calendar.event_detector.anonymize_text") as mock_anon:
        mock_anon.return_value = MagicMock(anonymized_text="RDV cardio Dr Leblanc jeudi 14h30", mapping={})
        result = await extract_events_from_email("RDV cardio Dr Leblanc jeudi 14h30", str(uuid4()), {}, "2026-02-10", mock_client)
    assert len(result.events_detected) == 1
    assert result.events_detected[0].event_type == "medical"
    assert result.events_detected[0].casquette == Casquette.MEDECIN
