"""
Requêtes PostgreSQL pour CRUD warranties + alertes (Story 3.4 AC2).

asyncpg brut uniquement (PAS d'ORM).
Transactions explicites (BEGIN/COMMIT).
TIMESTAMPTZ pour dates.

Patterns réutilisés: Stories 3.1-3.3 (asyncpg, gen_random_uuid).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

import asyncpg
import structlog

from agents.src.agents.archiviste.warranty_models import WarrantyInfo

logger = structlog.get_logger(__name__)


async def insert_warranty(
    db_pool: asyncpg.Pool,
    warranty_info: WarrantyInfo,
    document_id: str,
    expiration_date: date,
) -> str:
    """
    Insert warranty + create reminder node + link edges (AC2).

    Args:
        db_pool: Pool asyncpg
        warranty_info: Infos garantie validées
        document_id: UUID document source
        expiration_date: Date expiration calculée

    Returns:
        UUID de la garantie créée

    Raises:
        asyncpg.PostgresError: En cas d'erreur DB
    """
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # 1. INSERT warranty
            warranty_id = await conn.fetchval(
                """
                INSERT INTO knowledge.warranties (
                    item_name, item_category, vendor, purchase_date,
                    warranty_duration_months, expiration_date,
                    purchase_amount, document_id, status, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active', $9)
                RETURNING id
                """,
                warranty_info.item_name,
                warranty_info.item_category.value,
                warranty_info.vendor,
                warranty_info.purchase_date,
                warranty_info.warranty_duration_months,
                expiration_date,
                warranty_info.purchase_amount if warranty_info.purchase_amount else None,
                document_id,
                {},
            )

            # 2. Create reminder node in knowledge graph
            node_id = await conn.fetchval(
                """
                SELECT knowledge.create_warranty_reminder_node($1, $2, $3)
                """,
                warranty_id,
                warranty_info.item_name,
                expiration_date,
            )

            # 3. Create edge: node -> document (created_from)
            if document_id:
                doc_node_id = await conn.fetchval(
                    """
                    SELECT id FROM knowledge.nodes
                    WHERE type = 'document' AND metadata->>'document_id' = $1
                    LIMIT 1
                    """,
                    document_id,
                )
                if doc_node_id:
                    await conn.execute(
                        """
                        INSERT INTO knowledge.edges (from_node_id, to_node_id, relation_type, metadata)
                        VALUES ($1, $2, 'created_from', '{}')
                        ON CONFLICT (from_node_id, to_node_id, relation_type) DO NOTHING
                        """,
                        node_id,
                        doc_node_id,
                    )

            # 4. Create belongs_to edge: reminder -> category entity
            category_value = warranty_info.item_category.value
            category_node_id = await conn.fetchval(
                """
                SELECT id FROM knowledge.nodes
                WHERE type = 'entity' AND metadata->>'domain' = 'warranty'
                  AND metadata->>'category' = $1
                LIMIT 1
                """,
                category_value,
            )
            if not category_node_id:
                category_node_id = await conn.fetchval(
                    """
                    INSERT INTO knowledge.nodes (type, name, metadata, source)
                    VALUES ('entity', $1, $2, 'archiviste')
                    RETURNING id
                    """,
                    f"Catégorie garantie: {category_value}",
                    {"domain": "warranty", "category": category_value},
                )
            if category_node_id:
                await conn.execute(
                    """
                    INSERT INTO knowledge.edges (from_node_id, to_node_id, relation_type, metadata)
                    VALUES ($1, $2, 'belongs_to', '{}')
                    ON CONFLICT (from_node_id, to_node_id, relation_type) DO NOTHING
                    """,
                    node_id,
                    category_node_id,
                )

            logger.info(
                "warranty_db.inserted",
                warranty_id=str(warranty_id),
                node_id=str(node_id),
                item_name=warranty_info.item_name,
            )

            return str(warranty_id)


async def get_active_warranties(
    db_pool: asyncpg.Pool,
) -> List[Dict[str, Any]]:
    """Query all active warranties."""
    rows = await db_pool.fetch("""
        SELECT
            id, item_name, item_category, vendor,
            purchase_date, warranty_duration_months,
            expiration_date, purchase_amount, document_id,
            status, metadata, created_at,
            (expiration_date - CURRENT_DATE) AS days_remaining
        FROM knowledge.warranties
        WHERE status = 'active'
        ORDER BY expiration_date ASC
        """)
    return [dict(r) for r in rows]


async def get_expiring_warranties(
    db_pool: asyncpg.Pool,
    days_threshold: int = 60,
) -> List[Dict[str, Any]]:
    """
    Query warranties expiring within threshold days (AC3).

    Args:
        db_pool: Pool asyncpg
        days_threshold: Nombre de jours avant expiration

    Returns:
        Liste de warranties avec days_remaining
    """
    rows = await db_pool.fetch(
        """
        SELECT
            id, item_name, item_category, vendor,
            purchase_date, warranty_duration_months,
            expiration_date, purchase_amount, document_id,
            status, metadata,
            (expiration_date - CURRENT_DATE) AS days_remaining
        FROM knowledge.warranties
        WHERE status = 'active'
          AND expiration_date BETWEEN CURRENT_DATE AND (CURRENT_DATE + $1 * INTERVAL '1 day')
        ORDER BY expiration_date ASC
        """,
        days_threshold,
    )
    return [dict(r) for r in rows]


async def get_warranty_stats(
    db_pool: asyncpg.Pool,
) -> Dict[str, Any]:
    """
    Statistiques agrégées pour /warranty_stats (AC6).

    Returns:
        Dict avec total_active, expired_12m, total_amount, next_expiry
    """
    stats = {}

    # Active count
    stats["total_active"] = (
        await db_pool.fetchval("SELECT COUNT(*) FROM knowledge.warranties WHERE status = 'active'")
        or 0
    )

    # Expired in last 12 months
    stats["expired_12m"] = await db_pool.fetchval("""
        SELECT COUNT(*) FROM knowledge.warranties
        WHERE status = 'expired'
          AND updated_at >= NOW() - INTERVAL '12 months'
        """) or 0

    # Total amount covered (active)
    stats["total_amount"] = await db_pool.fetchval("""
        SELECT COALESCE(SUM(purchase_amount), 0)
        FROM knowledge.warranties
        WHERE status = 'active' AND purchase_amount IS NOT NULL
        """) or Decimal("0")

    # Next expiring
    next_row = await db_pool.fetchrow("""
        SELECT item_name, expiration_date,
               (expiration_date - CURRENT_DATE) AS days_remaining
        FROM knowledge.warranties
        WHERE status = 'active'
        ORDER BY expiration_date ASC
        LIMIT 1
        """)
    if next_row:
        stats["next_expiry"] = dict(next_row)
    else:
        stats["next_expiry"] = None

    # By category
    category_rows = await db_pool.fetch("""
        SELECT item_category, COUNT(*) AS count,
               COALESCE(SUM(purchase_amount), 0) AS total_amount
        FROM knowledge.warranties
        WHERE status = 'active'
        GROUP BY item_category
        ORDER BY count DESC
        """)
    stats["by_category"] = [dict(r) for r in category_rows]

    return stats


async def mark_warranty_expired(
    db_pool: asyncpg.Pool,
    warranty_id: str,
) -> None:
    """Update warranty status to 'expired' (AC3)."""
    await db_pool.execute(
        """
        UPDATE knowledge.warranties
        SET status = 'expired', updated_at = NOW()
        WHERE id = $1 AND status = 'active'
        """,
        UUID(warranty_id),
    )
    logger.info("warranty_db.expired", warranty_id=warranty_id)


async def check_alert_sent(
    db_pool: asyncpg.Pool,
    warranty_id: str,
    alert_type: str,
) -> bool:
    """Check if alert already sent for warranty (anti-spam AC3)."""
    count = await db_pool.fetchval(
        """
        SELECT COUNT(*) FROM knowledge.warranty_alerts
        WHERE warranty_id = $1 AND alert_type = $2
        """,
        UUID(warranty_id),
        alert_type,
    )
    return count > 0


async def record_alert_sent(
    db_pool: asyncpg.Pool,
    warranty_id: str,
    alert_type: str,
) -> None:
    """Record alert in warranty_alerts table (AC3 anti-spam)."""
    await db_pool.execute(
        """
        INSERT INTO knowledge.warranty_alerts (warranty_id, alert_type)
        VALUES ($1, $2)
        ON CONFLICT (warranty_id, alert_type) DO NOTHING
        """,
        UUID(warranty_id),
        alert_type,
    )
    logger.info(
        "warranty_db.alert_recorded",
        warranty_id=warranty_id,
        alert_type=alert_type,
    )


async def delete_warranty(
    db_pool: asyncpg.Pool,
    warranty_id: str,
) -> bool:
    """
    Delete warranty + cleanup graph nodes/edges/alerts (AC5 Ignorer).

    Edges cascade-deleted via ON DELETE CASCADE on knowledge.edges FK.
    """
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # 1. Delete reminder node (edges cascade via ON DELETE CASCADE)
            await conn.execute(
                """
                DELETE FROM knowledge.nodes
                WHERE type = 'reminder' AND metadata->>'warranty_id' = $1
                """,
                str(warranty_id),
            )

            # 2. Delete warranty alerts (anti-spam records)
            await conn.execute(
                "DELETE FROM knowledge.warranty_alerts WHERE warranty_id = $1",
                UUID(warranty_id),
            )

            # 3. Delete warranty record
            result = await conn.execute(
                "DELETE FROM knowledge.warranties WHERE id = $1",
                UUID(warranty_id),
            )

    deleted = result == "DELETE 1"
    logger.info("warranty_db.deleted", warranty_id=warranty_id, deleted=deleted)
    return deleted
