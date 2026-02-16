"""
Tests unitaires pour bot/handlers/formatters.py

Story 1.11 - Task 5.2 : Tests helpers formatage.
"""

from datetime import datetime, timedelta, timezone

import pytest
from bot.handlers.formatters import (
    format_confidence,
    format_eur,
    format_status_emoji,
    format_timestamp,
    parse_verbose_flag,
    truncate_text,
)


class TestFormatConfidence:
    """Tests pour format_confidence() — barre emoji + pourcentage."""

    def test_format_confidence_normal(self):
        """0.952 -> barre 9/10 remplie + '95.2%'"""
        result = format_confidence(0.952)
        assert "95.2%" in result
        assert "\u2588" in result  # filled block
        assert "\u2591" in result  # empty block

    def test_format_confidence_zero(self):
        """0.0 -> barre vide + '0.0%'"""
        result = format_confidence(0.0)
        assert "0.0%" in result
        assert result.count("\u2591") == 10  # all empty

    def test_format_confidence_one(self):
        """1.0 -> barre pleine + '100.0%'"""
        result = format_confidence(1.0)
        assert "100.0%" in result
        assert result.count("\u2588") == 10  # all filled

    def test_format_confidence_low(self):
        """0.123 -> barre 1/10 + '12.3%'"""
        result = format_confidence(0.123)
        assert "12.3%" in result
        assert result.count("\u2588") == 1


class TestFormatStatusEmoji:
    """Tests pour format_status_emoji()."""

    def test_all_known_statuses(self):
        """Verifie que tous les statuses connus ont un emoji."""
        known = [
            "auto",
            "pending",
            "approved",
            "rejected",
            "corrected",
            "expired",
            "error",
            "executed",
        ]
        for status in known:
            result = format_status_emoji(status)
            assert result != "?", f"Status '{status}' devrait avoir un emoji"

    def test_unknown_status(self):
        """Status inconnu retourne '?'."""
        assert format_status_emoji("unknown") == "?"

    def test_empty_status(self):
        """Status vide retourne '?'."""
        assert format_status_emoji("") == "?"


class TestFormatTimestamp:
    """Tests pour format_timestamp() — format relatif par defaut."""

    def test_none_returns_na(self):
        """None retourne 'N/A'."""
        assert format_timestamp(None) == "N/A"

    def test_verbose_format(self):
        """Format verbose: YYYY-MM-DD HH:MM."""
        dt = datetime(2026, 2, 10, 14, 30, 45, tzinfo=timezone.utc)
        result = format_timestamp(dt, verbose=True)
        assert result == "2026-02-10 14:30"

    def test_relative_seconds(self):
        """Timestamp recent -> 'il y a Xs'."""
        dt = datetime.now(tz=timezone.utc) - timedelta(seconds=30)
        result = format_timestamp(dt)
        assert result.startswith("il y a ")
        assert result.endswith("s")

    def test_relative_minutes(self):
        """Quelques minutes -> 'il y a Xmin'."""
        dt = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
        result = format_timestamp(dt)
        assert "5min" in result

    def test_relative_hours(self):
        """Quelques heures -> 'il y a Xh'."""
        dt = datetime.now(tz=timezone.utc) - timedelta(hours=3)
        result = format_timestamp(dt)
        assert "3h" in result

    def test_relative_days(self):
        """Quelques jours -> 'il y a Xj'."""
        dt = datetime.now(tz=timezone.utc) - timedelta(days=2)
        result = format_timestamp(dt)
        assert "2j" in result

    def test_future_datetime_fallback(self):
        """Datetime futur -> format HH:MM:SS fallback."""
        dt = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        result = format_timestamp(dt)
        assert ":" in result  # HH:MM:SS format

    def test_naive_datetime_assumed_utc(self):
        """Datetime naive traite comme UTC."""
        # Creer un naive datetime qui est 10min avant UTC now
        dt = datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
        result = format_timestamp(dt)
        assert "10min" in result


class TestFormatEur:
    """Tests pour format_eur()."""

    def test_format_eur_normal(self):
        """18.503 -> '18.50 EUR'"""
        assert format_eur(18.503) == "18.50 EUR"

    def test_format_eur_zero(self):
        """0 -> '0.00 EUR'"""
        assert format_eur(0) == "0.00 EUR"

    def test_format_eur_round_up(self):
        """45.999 -> '46.00 EUR'"""
        assert format_eur(45.999) == "46.00 EUR"


class TestTruncateText:
    """Tests pour truncate_text()."""

    def test_short_text_unchanged(self):
        """Texte court retourne tel quel."""
        assert truncate_text("hello", 100) == "hello"

    def test_long_text_truncated(self):
        """Texte long tronque avec '...'."""
        result = truncate_text("a" * 150, 100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_exact_length_unchanged(self):
        """Texte exactement a la limite retourne tel quel."""
        text = "a" * 100
        assert truncate_text(text, 100) == text


class TestParseVerboseFlag:
    """Tests pour parse_verbose_flag()."""

    def test_v_flag_detected(self):
        """-v dans args retourne True."""
        assert parse_verbose_flag(["-v"]) is True

    def test_verbose_flag_detected(self):
        """--verbose dans args retourne True."""
        assert parse_verbose_flag(["--verbose"]) is True

    def test_no_flag(self):
        """Sans flag retourne False."""
        assert parse_verbose_flag(["abc123"]) is False

    def test_empty_args(self):
        """Args vides retourne False."""
        assert parse_verbose_flag([]) is False

    def test_none_args(self):
        """Args None retourne False."""
        assert parse_verbose_flag(None) is False

    def test_mixed_args(self):
        """Flag mixte avec UUID."""
        assert parse_verbose_flag(["abc123", "-v"]) is True
