"""Pydantic models for Google Calendar sync."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GoogleCalendarEvent(BaseModel):
    """Google Calendar event model.

    Attributes:
        id: Google Calendar event ID
        summary: Event title/summary
        location: Event location (optional)
        description: Event description (optional)
        start: Start datetime (ISO 8601)
        end: End datetime (ISO 8601)
        attendees: List of attendee email addresses
        calendar_id: ID of the calendar this event belongs to
        updated: Last update timestamp from Google
        html_link: Direct link to event in Google Calendar web UI
    """

    id: str = Field(..., description="Google Calendar event ID")
    summary: str = Field(..., description="Event title/summary")
    location: Optional[str] = Field(default=None, description="Event location")
    description: Optional[str] = Field(default=None, description="Event description")
    start: str = Field(..., description="Start datetime (ISO 8601)")
    end: str = Field(..., description="End datetime (ISO 8601)")
    attendees: List[str] = Field(
        default_factory=list, description="List of attendee emails"
    )
    calendar_id: str = Field(..., description="Calendar ID")
    updated: Optional[str] = Field(default=None, description="Last update timestamp")
    html_link: Optional[str] = Field(
        default=None, description="Link to event in Google Calendar"
    )

    @classmethod
    def from_google_api(cls, event: dict, calendar_id: str) -> "GoogleCalendarEvent":
        """Create model from Google Calendar API response.

        Args:
            event: Event dict from Google Calendar API
            calendar_id: ID of the calendar

        Returns:
            GoogleCalendarEvent instance
        """
        # Extract attendees emails
        attendees = []
        if "attendees" in event:
            attendees = [a.get("email", "") for a in event["attendees"] if "email" in a]

        # Extract start/end datetime
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get(
            "date"
        )
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")

        return cls(
            id=event["id"],
            summary=event.get("summary", ""),
            location=event.get("location"),
            description=event.get("description"),
            start=start,
            end=end,
            attendees=attendees,
            calendar_id=calendar_id,
            updated=event.get("updated"),
            html_link=event.get("htmlLink"),
        )

    def to_google_api(self) -> dict:
        """Convert to Google Calendar API format.

        Returns:
            Dict suitable for Google Calendar API insert/update
        """
        body = {
            "summary": self.summary,
            "start": {"dateTime": self.start, "timeZone": "Europe/Paris"},
            "end": {"dateTime": self.end, "timeZone": "Europe/Paris"},
        }

        if self.location:
            body["location"] = self.location

        if self.description:
            body["description"] = self.description

        if self.attendees:
            body["attendees"] = [{"email": email} for email in self.attendees]

        # Default reminders
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 30}],
        }

        return body


class SyncResult(BaseModel):
    """Result of a synchronization operation.

    Attributes:
        events_created: Number of events created
        events_updated: Number of events updated
        events_deleted: Number of events deleted
        errors: List of error messages (if any)
        sync_timestamp: Timestamp when sync completed
    """

    events_created: int = Field(default=0, description="Events created count")
    events_updated: int = Field(default=0, description="Events updated count")
    events_deleted: int = Field(default=0, description="Events deleted count")
    errors: List[str] = Field(default_factory=list, description="Error messages")
    sync_timestamp: datetime = Field(
        default_factory=datetime.now, description="Sync completion timestamp"
    )

    @property
    def total_events(self) -> int:
        """Total number of events processed."""
        return self.events_created + self.events_updated + self.events_deleted

    @property
    def has_errors(self) -> bool:
        """Check if sync had any errors."""
        return len(self.errors) > 0

    @property
    def success(self) -> bool:
        """Check if sync was successful (no errors)."""
        return not self.has_errors
