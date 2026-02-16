"""
Module Calendar - Detection evenements et gestion agenda multi-casquettes

Story 7.1: Detection evenements depuis emails via Claude Sonnet 4.5
"""

from agents.src.agents.calendar.event_detector import (
    detect_events_action,
    extract_events_from_email,
)
from agents.src.agents.calendar.models import Event, EventDetectionResult

__all__ = [
    "extract_events_from_email",
    "detect_events_action",
    "Event",
    "EventDetectionResult",
]
