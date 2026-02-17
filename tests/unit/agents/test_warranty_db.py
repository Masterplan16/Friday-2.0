"""
Tests unitaires warranty_db.py (Story 3.4 AC2).

12 tests couvrant :
- Insert warranty + nodes + edges
- Get expiring warranties
- Mark warranty expired
- Check alert sent
- Record alert sent
- Delete warranty
- Statistics
"""

import sys
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, ".")

from agents.src.agents.archiviste.warranty_models import WarrantyCategory, WarrantyInfo


def _make_warranty_info(**kwargs) -> WarrantyInfo:
    """Helper pour créer un WarrantyInfo de test."""
    defaults = {
        "warranty_detected": True,
        "item_name": "HP Printer",
        "item_category": WarrantyCategory.ELECTRONICS,
        "vendor": "Amazon",
        "purchase_date": date(2025, 6, 15),
        "warranty_duration_months": 24,
        "purchase_amount": Decimal("149.99"),
        "confidence": 0.92,
    }
    defaults.update(kwargs)
    return WarrantyInfo(**defaults)


def _make_mock_pool():
    """Create mock asyncpg pool with proper async context managers."""
    from contextlib import asynccontextmanager

    conn = AsyncMock()
    transaction = AsyncMock()

    @asynccontextmanager
    async def mock_transaction():
        yield transaction

    conn.transaction = mock_transaction

    pool = AsyncMock()

    @asynccontextmanager
    async def mock_acquire():
        yield conn

    pool.acquire = mock_acquire
    return pool, conn


class TestInsertWarranty:
    """Tests pour insert_warranty."""

    @pytest.mark.asyncio
    async def test_insert_warranty_success(self):
        """INSERT warranty + node + edge OK."""
        pool, conn = _make_mock_pool()
        warranty_id = uuid4()
        node_id = uuid4()
        doc_node_id = uuid4()

        cat_node_id = uuid4()
        conn.fetchval = AsyncMock(side_effect=[warranty_id, node_id, doc_node_id, cat_node_id])
        conn.execute = AsyncMock()

        from agents.src.agents.archiviste.warranty_db import insert_warranty

        info = _make_warranty_info()
        result = await insert_warranty(
            db_pool=pool,
            warranty_info=info,
            document_id="test-doc-id",
            expiration_date=date(2027, 6, 15),
        )

        assert result == str(warranty_id)
        assert conn.fetchval.call_count == 4  # warranty + node + doc_node + category_node

    @pytest.mark.asyncio
    async def test_insert_warranty_no_document_node(self):
        """INSERT warranty sans document node existant."""
        pool, conn = _make_mock_pool()
        warranty_id = uuid4()
        node_id = uuid4()

        cat_node_id = uuid4()
        conn.fetchval = AsyncMock(side_effect=[warranty_id, node_id, None, cat_node_id])
        conn.execute = AsyncMock()

        from agents.src.agents.archiviste.warranty_db import insert_warranty

        info = _make_warranty_info()
        result = await insert_warranty(
            db_pool=pool,
            warranty_info=info,
            document_id="test-doc-id",
            expiration_date=date(2027, 6, 15),
        )

        assert result == str(warranty_id)
        # Doc edge NOT created (doc_node_id=None), but category belongs_to edge IS created
        conn.execute.assert_called_once()


class TestGetExpiringWarranties:
    """Tests pour get_expiring_warranties."""

    @pytest.mark.asyncio
    async def test_get_expiring_60d(self):
        """Query warranties expirant dans 60 jours."""
        pool = AsyncMock()
        mock_rows = [
            {"id": uuid4(), "item_name": "Printer", "days_remaining": 30},
            {"id": uuid4(), "item_name": "Laptop", "days_remaining": 55},
        ]
        pool.fetch = AsyncMock(return_value=mock_rows)

        from agents.src.agents.archiviste.warranty_db import get_expiring_warranties

        result = await get_expiring_warranties(pool, days_threshold=60)

        assert len(result) == 2
        assert result[0]["item_name"] == "Printer"
        pool.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_expiring_empty(self):
        """Aucune warranty expirant."""
        pool = AsyncMock()
        pool.fetch = AsyncMock(return_value=[])

        from agents.src.agents.archiviste.warranty_db import get_expiring_warranties

        result = await get_expiring_warranties(pool, days_threshold=60)

        assert result == []


class TestMarkWarrantyExpired:
    """Tests pour mark_warranty_expired."""

    @pytest.mark.asyncio
    async def test_mark_expired(self):
        """Status update active → expired."""
        pool = AsyncMock()
        pool.execute = AsyncMock()

        from agents.src.agents.archiviste.warranty_db import mark_warranty_expired

        await mark_warranty_expired(pool, str(uuid4()))

        pool.execute.assert_called_once()
        sql = pool.execute.call_args[0][0]
        assert "expired" in sql


class TestAlertTracking:
    """Tests pour check_alert_sent et record_alert_sent."""

    @pytest.mark.asyncio
    async def test_check_alert_not_sent(self):
        """Alert pas encore envoyée."""
        pool = AsyncMock()
        pool.fetchval = AsyncMock(return_value=0)

        from agents.src.agents.archiviste.warranty_db import check_alert_sent

        result = await check_alert_sent(pool, str(uuid4()), "7_days")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_alert_already_sent(self):
        """Alert déjà envoyée (anti-spam)."""
        pool = AsyncMock()
        pool.fetchval = AsyncMock(return_value=1)

        from agents.src.agents.archiviste.warranty_db import check_alert_sent

        result = await check_alert_sent(pool, str(uuid4()), "30_days")

        assert result is True

    @pytest.mark.asyncio
    async def test_record_alert_sent(self):
        """Record alert dans warranty_alerts."""
        pool = AsyncMock()
        pool.execute = AsyncMock()

        from agents.src.agents.archiviste.warranty_db import record_alert_sent

        await record_alert_sent(pool, str(uuid4()), "60_days")

        pool.execute.assert_called_once()
        sql = pool.execute.call_args[0][0]
        assert "warranty_alerts" in sql
        assert "ON CONFLICT" in sql


class TestDeleteWarranty:
    """Tests pour delete_warranty."""

    @pytest.mark.asyncio
    async def test_delete_warranty_success(self):
        """Suppression warranty OK."""
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        from agents.src.agents.archiviste.warranty_db import delete_warranty

        result = await delete_warranty(pool, str(uuid4()))

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_warranty_not_found(self):
        """Warranty non trouvée."""
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        from agents.src.agents.archiviste.warranty_db import delete_warranty

        result = await delete_warranty(pool, str(uuid4()))

        assert result is False


class TestWarrantyStats:
    """Tests pour get_warranty_stats."""

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Statistiques agrégées."""
        pool = AsyncMock()
        pool.fetchval = AsyncMock(side_effect=[5, 2, Decimal("1500.00")])
        pool.fetchrow = AsyncMock(
            return_value={
                "item_name": "Printer",
                "expiration_date": date(2026, 3, 15),
                "days_remaining": 27,
            }
        )
        pool.fetch = AsyncMock(
            return_value=[
                {"item_category": "electronics", "count": 3, "total_amount": Decimal("900")},
                {"item_category": "appliances", "count": 2, "total_amount": Decimal("600")},
            ]
        )

        from agents.src.agents.archiviste.warranty_db import get_warranty_stats

        stats = await get_warranty_stats(pool)

        assert stats["total_active"] == 5
        assert stats["expired_12m"] == 2
        assert stats["total_amount"] == Decimal("1500.00")
        assert stats["next_expiry"]["item_name"] == "Printer"
        assert len(stats["by_category"]) == 2
