"""
Context Manager - Gestion Contexte Multi-Casquettes

Story 7.3: Multi-casquettes & Conflits Calendrier (AC1)

Gère le contexte casquette actuel du Mainteneur avec détection automatique
selon 5 règles prioritaires:
1. Manuel (commande Telegram /casquette)
2. Événement en cours (NOW() entre start/end)
3. Heuristique heure (08:00-12:00 médecin, 14:00-16:00 enseignant, etc.)
4. Dernier événement passé
5. Défaut (NULL si aucune règle ne s'applique)

Le contexte influence:
- Classification email (bias @chu.fr → pro si médecin)
- Détection événements (réunion → casquette si contexte)
- Briefing matinal (filtrage par casquette)
"""

import asyncpg
import json
import redis.asyncio as redis
import structlog
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from agents.src.core.models import (
    UserContext,
    ContextSource,
    Casquette,
    OngoingEvent,
    TIME_BASED_CASQUETTE_MAPPING,
)

logger = structlog.get_logger(__name__)


# ============================================================================
# Context Manager
# ============================================================================


class ContextManager:
    """
    Gestionnaire contexte casquette multi-rôles (AC1).

    Détection automatique avec cache Redis (5 min TTL) pour optimiser
    les performances (éviter queries PostgreSQL répétées).
    """

    def __init__(
        self, db_pool: asyncpg.Pool, redis_client: redis.Redis, cache_ttl: int = 300  # 5 minutes
    ):
        """
        Initialize Context Manager.

        Args:
            db_pool: Pool de connexions PostgreSQL
            redis_client: Client Redis pour cache
            cache_ttl: TTL cache Redis en secondes (défaut 5 min)
        """
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.cache_ttl = cache_ttl
        self._cache_key = "user:context"

    # ========================================================================
    # Public API
    # ========================================================================

    async def get_current_context(self) -> UserContext:
        """
        Récupère le contexte casquette actuel (AC1).

        Essaie cache Redis d'abord, sinon query PostgreSQL + auto-detect.

        Returns:
            UserContext avec casquette active et source détermination
        """
        # Tentative lecture cache Redis
        cached_context = await self._get_cached_context()
        if cached_context:
            logger.debug("context_cache_hit")
            return cached_context

        # Cache miss → Query PostgreSQL (colonnes explicites, pas SELECT *)
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, current_casquette, updated_by, last_updated_at "
                "FROM core.user_context WHERE id = 1"
            )

        if not row:
            # Edge case: table user_context vide (ne devrait jamais arriver après migration 037)
            logger.warning("user_context_table_empty", action="creating_default")
            return await self._create_default_context()

        # Vérifier si contexte manuel (updated_by='manual')
        # H14 fix: Contexte manuel expire après 4h → retombe en auto-detect
        if row["updated_by"] == "manual" and row["current_casquette"]:
            manual_age = (
                datetime.now(timezone.utc) - row["last_updated_at"].replace(tzinfo=timezone.utc)
                if row["last_updated_at"].tzinfo is None
                else datetime.now(timezone.utc) - row["last_updated_at"]
            )
            if manual_age <= timedelta(hours=4):
                context = UserContext(
                    casquette=Casquette(row["current_casquette"]),
                    source=ContextSource.MANUAL,
                    updated_at=row["last_updated_at"],
                    updated_by="manual",
                )
            else:
                # Contexte manuel expiré → auto-detect
                logger.info("manual_context_expired", age_hours=manual_age.total_seconds() / 3600)
                context = await self.auto_detect_context()
        else:
            # Auto-detect contexte (updated_by='system' ou casquette=NULL)
            context = await self.auto_detect_context()

        # Mettre en cache
        await self._cache_context(context)

        return context

    async def set_context(
        self, casquette: Optional[Casquette], source: str = "manual"
    ) -> UserContext:
        """
        Force le contexte casquette manuellement (AC2).

        Utilisé par commande Telegram /casquette <casquette>.

        Args:
            casquette: Casquette à forcer (None = auto-detect)
            source: 'manual' (commande) ou 'system' (auto-detect)

        Returns:
            UserContext mis à jour
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE core.user_context
                SET current_casquette = $1, updated_by = $2
                WHERE id = 1
            """,
                casquette.value if casquette else None,
                source,
            )

        # Invalider cache Redis
        await self.redis_client.delete(self._cache_key)

        logger.info(
            "context_updated", casquette=casquette.value if casquette else None, source=source
        )

        # Retourner nouveau contexte
        return await self.get_current_context()

    async def auto_detect_context(self) -> UserContext:
        """
        Détection automatique contexte selon 5 règles (AC1).

        Priorité descendante:
        1. Manuel (déjà géré dans get_current_context)
        2. Événement en cours (NOW() entre start/end)
        3. Heuristique heure de la journée
        4. Dernier événement passé
        5. Défaut (NULL)

        Returns:
            UserContext avec source détection
        """
        # Règle 2: Événement en cours
        ongoing_event = await self._get_ongoing_event()
        if ongoing_event:
            logger.debug("context_detected_from_event", event_id=ongoing_event.id)
            return UserContext(
                casquette=ongoing_event.casquette, source=ContextSource.EVENT, updated_by="system"
            )

        # Règle 3: Heuristique heure de la journée
        time_based_casquette = self._get_context_from_time()
        if time_based_casquette:
            logger.debug("context_detected_from_time", casquette=time_based_casquette.value)
            return UserContext(
                casquette=time_based_casquette, source=ContextSource.TIME, updated_by="system"
            )

        # Règle 4: Dernier événement passé
        last_event_casquette = await self._get_last_event_casquette()
        if last_event_casquette:
            logger.debug("context_detected_from_last_event", casquette=last_event_casquette.value)
            return UserContext(
                casquette=last_event_casquette, source=ContextSource.LAST_EVENT, updated_by="system"
            )

        # Règle 5: Défaut (NULL)
        logger.debug("context_default_null")
        return UserContext(casquette=None, source=ContextSource.DEFAULT, updated_by="system")

    # ========================================================================
    # Detection Rules (Private)
    # ========================================================================

    async def _get_ongoing_event(self) -> Optional[OngoingEvent]:
        """
        Récupère événement en cours (NOW() entre start/end) (AC1 Règle 2).

        Returns:
            OngoingEvent si trouvé, sinon None
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    id,
                    properties->>'casquette' AS casquette,
                    properties->>'title' AS title,
                    (properties->>'start_datetime')::timestamptz AS start_datetime,
                    (properties->>'end_datetime')::timestamptz AS end_datetime
                FROM knowledge.entities
                WHERE entity_type = 'EVENT'
                  AND (properties->>'status') = 'confirmed'
                  AND NOW() >= (properties->>'start_datetime')::timestamptz
                  AND NOW() < (properties->>'end_datetime')::timestamptz
                  AND properties->>'casquette' IS NOT NULL
                ORDER BY (properties->>'start_datetime')::timestamptz ASC
                LIMIT 1
            """)

        if not row:
            return None

        return OngoingEvent(
            id=str(row["id"]),
            casquette=Casquette(row["casquette"]),
            title=row["title"],
            start_datetime=row["start_datetime"],
            end_datetime=row["end_datetime"],
        )

    def _get_context_from_time(self) -> Optional[Casquette]:
        """
        Détection contexte par heuristique heure (AC1 Règle 3).

        Mapping:
        - 08:00-12:00 → médecin (consultations matin)
        - 14:00-16:00 → enseignant (cours après-midi)
        - 16:00-18:00 → chercheur (recherche fin journée)
        - Autres → None

        Returns:
            Casquette si heure correspond, sinon None
        """
        # H2 fix: utiliser timezone locale pour heuristique heure
        now = datetime.now(timezone.utc)
        current_hour = now.hour

        for (start_hour, end_hour), casquette in TIME_BASED_CASQUETTE_MAPPING.items():
            if start_hour <= current_hour < end_hour:
                return casquette

        return None

    async def _get_last_event_casquette(self) -> Optional[Casquette]:
        """
        Récupère casquette du dernier événement passé (AC1 Règle 4).

        Returns:
            Casquette dernier événement, sinon None
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT properties->>'casquette' AS casquette
                FROM knowledge.entities
                WHERE entity_type = 'EVENT'
                  AND (properties->>'status') = 'confirmed'
                  AND (properties->>'end_datetime')::timestamptz < NOW()
                  AND properties->>'casquette' IS NOT NULL
                ORDER BY (properties->>'end_datetime')::timestamptz DESC
                LIMIT 1
            """)

        if not row or not row["casquette"]:
            return None

        return Casquette(row["casquette"])

    # ========================================================================
    # Cache Redis (Private)
    # ========================================================================

    async def _get_cached_context(self) -> Optional[UserContext]:
        """
        Récupère contexte depuis cache Redis.

        Returns:
            UserContext si cache hit, sinon None
        """
        try:
            cached_data = await self.redis_client.get(self._cache_key)
            if not cached_data:
                return None

            data = json.loads(cached_data)

            return UserContext(
                casquette=Casquette(data["casquette"]) if data.get("casquette") else None,
                source=ContextSource(data["source"]),
                updated_at=datetime.fromisoformat(data["updated_at"]),
                updated_by=data["updated_by"],
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("cache_read_deserialization_error", error=str(e))
            # Invalider cache corrompu
            await self.redis_client.delete(self._cache_key)
            return None
        except redis.RedisError as e:
            logger.warning("cache_read_redis_error", error=str(e))
            return None

    async def _cache_context(self, context: UserContext) -> None:
        """
        Met en cache le contexte dans Redis.

        Args:
            context: UserContext à cacher
        """
        try:
            data = {
                "casquette": context.casquette.value if context.casquette else None,
                "source": context.source.value,
                "updated_at": context.updated_at.isoformat(),
                "updated_by": context.updated_by,
            }

            await self.redis_client.setex(self._cache_key, self.cache_ttl, json.dumps(data))
        except Exception as e:
            logger.warning("cache_write_error", error=str(e))

    async def _create_default_context(self) -> UserContext:
        """
        Crée un contexte par défaut si table user_context vide.

        Edge case qui ne devrait jamais arriver après migration 037.
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO core.user_context (id, current_casquette, updated_by)
                VALUES (1, NULL, 'system')
                ON CONFLICT (id) DO NOTHING
            """)

        return UserContext(casquette=None, source=ContextSource.DEFAULT, updated_by="system")

    async def invalidate_cache(self) -> None:
        """
        Invalide le cache Redis contexte.

        Utilisé après changement manuel contexte via /casquette.
        """
        await self.redis_client.delete(self._cache_key)
        logger.debug("context_cache_invalidated")


# ============================================================================
# Factory Function
# ============================================================================


async def get_context_manager(db_pool: asyncpg.Pool, redis_client: redis.Redis) -> ContextManager:
    """
    Factory function pour créer ContextManager.

    Args:
        db_pool: Pool de connexions PostgreSQL
        redis_client: Client Redis

    Returns:
        Instance ContextManager configurée
    """
    return ContextManager(db_pool=db_pool, redis_client=redis_client, cache_ttl=300)  # 5 minutes
