"""
Heartbeat Checks Package

Story 7.3 Task 7: Calendar conflicts check
Story 4.1 (future): Additional heartbeat checks
"""

from agents.src.core.heartbeat_checks.calendar_conflicts import (
    check_calendar_conflicts,
    CHECK_METADATA as CALENDAR_CONFLICTS_METADATA,
)

__all__ = ["check_calendar_conflicts", "CALENDAR_CONFLICTS_METADATA"]
