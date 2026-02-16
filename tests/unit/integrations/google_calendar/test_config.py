"""Unit tests for Google Calendar configuration."""

import tempfile
from pathlib import Path

import pytest

from agents.src.integrations.google_calendar.config import (
    CalendarConfig,
    CalendarSettings,
    DefaultReminder,
    GoogleCalendarConfig,
    SyncRange,
)


@pytest.fixture
def valid_calendar_yaml():
    """Create valid calendar configuration YAML content."""
    return """
google_calendar:
  enabled: true
  sync_interval_minutes: 30
  calendars:
    - id: "primary"
      name: "Calendrier Médecin"
      casquette: "medecin"
      color: "#ff0000"
    - id: "calendar_enseignant_id"
      name: "Calendrier Enseignant"
      casquette: "enseignant"
      color: "#00ff00"
    - id: "calendar_chercheur_id"
      name: "Calendrier Chercheur"
      casquette: "chercheur"
      color: "#0000ff"
  sync_range:
    past_days: 7
    future_days: 90
  default_reminders:
    - method: "popup"
      minutes: 30
"""


@pytest.fixture
def unlimited_history_yaml():
    """Create YAML with unlimited history (sync_range: null)."""
    return """
google_calendar:
  enabled: true
  sync_interval_minutes: 30
  calendars:
    - id: "primary"
      name: "Calendrier Friday"
      casquette: "personnel"
      color: "#4285F4"
  sync_range: null
  default_reminders:
    - method: "popup"
      minutes: 30
"""


@pytest.fixture
def invalid_casquette_yaml():
    """Create YAML with invalid casquette."""
    return """
google_calendar:
  enabled: true
  sync_interval_minutes: 30
  calendars:
    - id: "primary"
      name: "Test Calendar"
      casquette: "invalid_casquette"
      color: "#ff0000"
  sync_range:
    past_days: 7
    future_days: 90
"""


@pytest.fixture
def no_calendars_yaml():
    """Create YAML with no calendars (should fail validation)."""
    return """
google_calendar:
  enabled: true
  sync_interval_minutes: 30
  calendars: []
  sync_range:
    past_days: 7
    future_days: 90
"""


class TestCalendarConfig:
    """Test suite for calendar configuration."""

    def test_load_valid_yaml(self, valid_calendar_yaml, tmp_path):
        """Test loading valid calendar configuration from YAML."""
        # Arrange
        config_file = tmp_path / "calendar_config.yaml"
        config_file.write_text(valid_calendar_yaml, encoding='utf-8')

        # Act
        config = CalendarConfig.from_yaml(str(config_file))

        # Assert
        assert config is not None
        assert config.google_calendar.enabled is True
        assert len(config.google_calendar.calendars) == 3
        assert config.google_calendar.calendars[0].casquette == "medecin"
        assert config.google_calendar.calendars[1].casquette == "enseignant"
        assert config.google_calendar.calendars[2].casquette == "chercheur"
        assert config.google_calendar.sync_interval_minutes == 30
        assert config.google_calendar.sync_range.past_days == 7
        assert config.google_calendar.sync_range.future_days == 90

    def test_validate_three_calendars(self, valid_calendar_yaml, tmp_path):
        """Test validation of 3 calendars configuration."""
        # Arrange
        config_file = tmp_path / "calendar_config.yaml"
        config_file.write_text(valid_calendar_yaml, encoding='utf-8')

        # Act
        config = CalendarConfig.from_yaml(str(config_file))

        # Assert
        assert len(config.google_calendar.calendars) == 3

        # Verify medecin calendar
        medecin = config.google_calendar.calendars[0]
        assert medecin.id == "primary"
        assert medecin.name == "Calendrier Médecin"
        assert medecin.casquette == "medecin"
        assert medecin.color == "#ff0000"

        # Verify enseignant calendar
        enseignant = config.google_calendar.calendars[1]
        assert enseignant.id == "calendar_enseignant_id"
        assert enseignant.name == "Calendrier Enseignant"
        assert enseignant.casquette == "enseignant"
        assert enseignant.color == "#00ff00"

        # Verify chercheur calendar
        chercheur = config.google_calendar.calendars[2]
        assert chercheur.id == "calendar_chercheur_id"
        assert chercheur.name == "Calendrier Chercheur"
        assert chercheur.casquette == "chercheur"
        assert chercheur.color == "#0000ff"

    def test_fail_fast_no_calendars(self, no_calendars_yaml, tmp_path):
        """Test fail-fast when no calendars configured."""
        # Arrange
        config_file = tmp_path / "calendar_config.yaml"
        config_file.write_text(no_calendars_yaml, encoding='utf-8')

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            CalendarConfig.from_yaml(str(config_file))

        # Pydantic v2 error message contains "at least 1 item"
        error_msg = str(exc_info.value).lower()
        assert "at least" in error_msg and ("calendar" in error_msg or "item" in error_msg)

    def test_invalid_casquette_rejected(self, invalid_casquette_yaml, tmp_path):
        """Test that invalid casquette is rejected."""
        # Arrange
        config_file = tmp_path / "calendar_config.yaml"
        config_file.write_text(invalid_casquette_yaml, encoding='utf-8')

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            CalendarConfig.from_yaml(str(config_file))

        assert "casquette" in str(exc_info.value).lower()

    def test_file_not_found_raises_error(self):
        """Test that missing config file raises FileNotFoundError."""
        # Act & Assert
        with pytest.raises(FileNotFoundError) as exc_info:
            CalendarConfig.from_yaml("nonexistent_config.yaml")

        assert "not found" in str(exc_info.value).lower()

    def test_invalid_color_format_rejected(self, tmp_path):
        """Test that invalid color format is rejected."""
        # Arrange
        invalid_color_yaml = """
google_calendar:
  enabled: true
  sync_interval_minutes: 30
  calendars:
    - id: "primary"
      name: "Test"
      casquette: "medecin"
      color: "red"  # Invalid - should be #RRGGBB
"""
        config_file = tmp_path / "calendar_config.yaml"
        config_file.write_text(invalid_color_yaml, encoding='utf-8')

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            CalendarConfig.from_yaml(str(config_file))

        assert "color" in str(exc_info.value).lower()
        assert "#RRGGBB" in str(exc_info.value)

    def test_negative_sync_days_rejected(self, tmp_path):
        """Test that negative sync days are rejected."""
        # Arrange
        invalid_sync_yaml = """
google_calendar:
  enabled: true
  sync_interval_minutes: 30
  calendars:
    - id: "primary"
      name: "Test"
      casquette: "medecin"
      color: "#ff0000"
  sync_range:
    past_days: -7  # Invalid - negative
    future_days: 90
"""
        config_file = tmp_path / "calendar_config.yaml"
        config_file.write_text(invalid_sync_yaml, encoding='utf-8')

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            CalendarConfig.from_yaml(str(config_file))

        assert "greater than or equal to 0" in str(exc_info.value).lower()

    def test_invalid_reminder_method_rejected(self, tmp_path):
        """Test that invalid reminder method is rejected."""
        # Arrange
        invalid_reminder_yaml = """
google_calendar:
  enabled: true
  sync_interval_minutes: 30
  calendars:
    - id: "primary"
      name: "Test"
      casquette: "medecin"
      color: "#ff0000"
  default_reminders:
    - method: "carrier_pigeon"  # Invalid method
      minutes: 30
"""
        config_file = tmp_path / "calendar_config.yaml"
        config_file.write_text(invalid_reminder_yaml, encoding='utf-8')

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            CalendarConfig.from_yaml(str(config_file))

        assert "reminder method" in str(exc_info.value).lower()

    def test_unlimited_history_sync_range_null(self, tmp_path, unlimited_history_yaml):
        """Test that sync_range: null (unlimited history) is accepted.

        Per Google Calendar API docs, timeMin/timeMax are optional.
        If not provided, API returns all events without time filtering.
        """
        # Arrange
        config_file = tmp_path / "calendar_config.yaml"
        config_file.write_text(unlimited_history_yaml, encoding='utf-8')

        # Act
        config = CalendarConfig.from_yaml(str(config_file))

        # Assert - sync_range is None (unlimited)
        assert config.google_calendar.sync_range is None
        assert config.google_calendar.enabled is True
        assert len(config.google_calendar.calendars) == 1
        assert config.google_calendar.calendars[0].id == "primary"
