"""Google Calendar configuration models."""

from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field, field_validator


class CalendarSettings(BaseModel):
    """Individual calendar configuration.

    Attributes:
        id: Google Calendar ID (e.g., 'primary' or long ID from calendar settings)
        name: Human-readable calendar name
        casquette: One of medecin, enseignant, chercheur
        color: Hex color code for calendar display
    """

    id: str = Field(..., description="Google Calendar ID")
    name: str = Field(..., description="Calendar display name")
    casquette: str = Field(..., description="Casquette (medecin, enseignant, chercheur)")
    color: str = Field(default="#000000", description="Calendar color (hex)")

    @field_validator("casquette")
    @classmethod
    def validate_casquette(cls, v: str) -> str:
        """Validate casquette is one of the allowed values."""
        allowed = {"medecin", "enseignant", "chercheur", "personnel"}
        if v not in allowed:
            raise ValueError(f"casquette must be one of {allowed}, got '{v}'")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        """Validate color is a valid hex code."""
        if not v.startswith("#") or len(v) != 7:
            raise ValueError(f"color must be hex format #RRGGBB, got '{v}'")
        return v


class SyncRange(BaseModel):
    """Sync time range configuration.

    Attributes:
        past_days: Number of days in the past to sync (None = no limit, retrieves all history)
        future_days: Number of days in the future to sync (None = no limit)
    """

    past_days: int | None = Field(
        default=None, ge=0, description="Days in the past to sync (None = unlimited)"
    )
    future_days: int | None = Field(
        default=None, ge=1, description="Days in the future to sync (None = unlimited)"
    )


class DefaultReminder(BaseModel):
    """Default reminder configuration.

    Attributes:
        method: Reminder method (popup, email, sms)
        minutes: Minutes before event to trigger reminder
    """

    method: str = Field(default="popup", description="Reminder method")
    minutes: int = Field(default=30, ge=0, description="Minutes before event")

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        """Validate reminder method is supported."""
        allowed = {"popup", "email", "sms"}
        if v not in allowed:
            raise ValueError(f"reminder method must be one of {allowed}, got '{v}'")
        return v


class GoogleCalendarConfig(BaseModel):
    """Google Calendar API configuration.

    Attributes:
        enabled: Whether Google Calendar sync is enabled
        sync_interval_minutes: Sync frequency in minutes
        calendars: List of calendars to synchronize
        sync_range: Time range for synchronization
        default_reminders: Default reminders for new events
    """

    enabled: bool = Field(default=True, description="Enable Google Calendar sync")
    sync_interval_minutes: int = Field(default=30, ge=1, description="Sync interval in minutes")
    calendars: List[CalendarSettings] = Field(
        ..., min_length=1, description="List of calendars to sync"
    )
    sync_range: SyncRange = Field(default_factory=SyncRange, description="Sync time range")
    default_reminders: List[DefaultReminder] = Field(
        default_factory=lambda: [DefaultReminder()], description="Default reminders"
    )

    @field_validator("calendars")
    @classmethod
    def validate_at_least_one_calendar(cls, v: List[CalendarSettings]) -> List[CalendarSettings]:
        """Validate at least one calendar is configured."""
        if not v:
            raise ValueError("At least one calendar must be configured")
        return v


class CalendarConfig(BaseModel):
    """Root calendar configuration.

    Attributes:
        google_calendar: Google Calendar settings
    """

    google_calendar: GoogleCalendarConfig = Field(..., description="Google Calendar settings")

    @classmethod
    def from_yaml(cls, path: str) -> "CalendarConfig":
        """Load configuration from YAML file.

        Args:
            path: Path to calendar_config.yaml file

        Returns:
            CalendarConfig instance with validated settings

        Raises:
            FileNotFoundError: If YAML file doesn't exist
            ValueError: If YAML is invalid or validation fails
        """
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Calendar config file not found: {path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty or invalid YAML file: {path}")

        return cls(**data)
