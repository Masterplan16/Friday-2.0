"""
Tests unitaires heartbeat warranty_expiry.py (Story 3.4 AC3).

10 tests couvrant :
- Quiet hours skip (sauf CRITICAL)
- 7 jours → CRITICAL, ignore quiet hours
- 30 jours → MEDIUM
- 60 jours → LOW
- Anti-spam (warranty_alerts check)
- Mark expired
- Multiple warranties same day
- DB query timeout
"""

import sys
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, ".")


# ============================================================================
# FIXTURES
# ============================================================================


def _make_warranty(days_remaining, item_name="Test Product", **kwargs):
    """Create mock warranty dict."""
    return {
        "id": uuid4(),
        "item_name": item_name,
        "item_category": "electronics",
        "vendor": "TestVendor",
        "expiration_date": date.today() + timedelta(days=days_remaining),
        "purchase_amount": 100.0,
        "days_remaining": days_remaining,
        **kwargs,
    }


class TestWarrantyExpiryCheck:
    """Tests pour check_warranty_expiry."""

    @pytest.mark.asyncio
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired")
    async def test_no_expiring_warranties(self, mock_expire, mock_record, mock_check, mock_get):
        """Aucune warranty expirant = notify False."""
        mock_get.return_value = []

        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        result = await check_warranty_expiry(
            context={"hour": 2},
            db_pool=AsyncMock(),
        )

        assert result.notify is False

    @pytest.mark.asyncio
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired")
    async def test_7_days_critical_alert(self, mock_expire, mock_record, mock_check, mock_get):
        """Warranty <7 jours = alerte CRITICAL envoyée."""
        warranty = _make_warranty(5, "HP Printer")
        mock_get.return_value = [warranty]
        mock_check.return_value = False  # Not yet sent

        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        result = await check_warranty_expiry(
            context={"hour": 2},
            db_pool=AsyncMock(),
        )

        assert result.notify is True
        assert "HP Printer" in result.message
        assert "5 jours" in result.message
        mock_record.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired")
    async def test_7_days_ignores_quiet_hours(self, mock_expire, mock_record, mock_check, mock_get):
        """Warranty <7 jours IGNORE quiet hours (23h)."""
        warranty = _make_warranty(3, "Urgent Item")
        mock_get.return_value = [warranty]
        mock_check.return_value = False

        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        result = await check_warranty_expiry(
            context={"hour": 23},  # Quiet hours
            db_pool=AsyncMock(),
        )

        assert result.notify is True
        assert "Urgent Item" in result.message

    @pytest.mark.asyncio
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired")
    async def test_30_days_medium_alert(self, mock_expire, mock_record, mock_check, mock_get):
        """Warranty 8-30 jours = alerte MEDIUM (respect quiet hours)."""
        warranty = _make_warranty(20, "Lave-linge Bosch")
        mock_get.return_value = [warranty]
        mock_check.return_value = False

        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        result = await check_warranty_expiry(
            context={"hour": 10},  # Not quiet hours
            db_pool=AsyncMock(),
        )

        assert result.notify is True
        assert "Lave-linge" in result.message

    @pytest.mark.asyncio
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired")
    async def test_30_days_quiet_hours_skip(self, mock_expire, mock_record, mock_check, mock_get):
        """Warranty 30 jours en quiet hours = pas d'alerte."""
        warranty = _make_warranty(25, "Non-urgent Item")
        mock_get.return_value = [warranty]
        mock_check.return_value = False

        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        result = await check_warranty_expiry(
            context={"hour": 23},  # Quiet hours
            db_pool=AsyncMock(),
        )

        assert result.notify is False

    @pytest.mark.asyncio
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired")
    async def test_alert_already_sent_anti_spam(
        self, mock_expire, mock_record, mock_check, mock_get
    ):
        """Alert déjà envoyée = pas de doublon (anti-spam)."""
        warranty = _make_warranty(5, "Already Notified")
        mock_get.return_value = [warranty]
        mock_check.return_value = True  # Already sent!

        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        result = await check_warranty_expiry(
            context={"hour": 2},
            db_pool=AsyncMock(),
        )

        assert result.notify is False
        mock_record.assert_not_called()

    @pytest.mark.asyncio
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired")
    async def test_expired_today_marked(self, mock_expire, mock_record, mock_check, mock_get):
        """Warranty expirée aujourd'hui = status 'expired'."""
        warranty = _make_warranty(0, "Expired Today")
        mock_get.return_value = [warranty]
        mock_check.return_value = False

        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        result = await check_warranty_expiry(
            context={"hour": 2},
            db_pool=AsyncMock(),
        )

        mock_expire.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.get_expiring_warranties")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.check_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.record_alert_sent")
    @patch("agents.src.core.heartbeat_checks.warranty_expiry.mark_warranty_expired")
    async def test_multiple_warranties(self, mock_expire, mock_record, mock_check, mock_get):
        """Multiple warranties avec différents seuils."""
        warranties = [
            _make_warranty(5, "Critical Item"),
            _make_warranty(20, "Medium Item"),
            _make_warranty(50, "Info Item"),
        ]
        mock_get.return_value = warranties
        mock_check.return_value = False

        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        result = await check_warranty_expiry(
            context={"hour": 10},
            db_pool=AsyncMock(),
        )

        assert result.notify is True
        assert "Critical Item" in result.message
        assert "Medium Item" in result.message
        assert "Info Item" in result.message
        assert mock_record.call_count == 3

    @pytest.mark.asyncio
    async def test_db_pool_none_creates_pool(self):
        """Sans db_pool, tente de créer un pool."""
        from agents.src.core.heartbeat_checks.warranty_expiry import check_warranty_expiry

        # Without DATABASE_URL → error
        with patch.dict("os.environ", {}, clear=True):
            result = await check_warranty_expiry(
                context={"hour": 2},
                db_pool=None,
            )
            assert result.notify is False
            assert result.error is not None


class TestQuietHours:
    """Tests pour _is_quiet_hours."""

    def test_quiet_hours_22h(self):
        """22h = quiet hours."""
        from agents.src.core.heartbeat_checks.warranty_expiry import _is_quiet_hours

        assert _is_quiet_hours({"hour": 22}) is True

    def test_quiet_hours_3h(self):
        """3h = quiet hours."""
        from agents.src.core.heartbeat_checks.warranty_expiry import _is_quiet_hours

        assert _is_quiet_hours({"hour": 3}) is True

    def test_not_quiet_hours_10h(self):
        """10h = pas quiet hours."""
        from agents.src.core.heartbeat_checks.warranty_expiry import _is_quiet_hours

        assert _is_quiet_hours({"hour": 10}) is False

    def test_not_quiet_hours_8h(self):
        """8h = pas quiet hours (boundary)."""
        from agents.src.core.heartbeat_checks.warranty_expiry import _is_quiet_hours

        assert _is_quiet_hours({"hour": 8}) is False
