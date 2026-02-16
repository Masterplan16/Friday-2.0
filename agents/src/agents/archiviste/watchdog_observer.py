"""
Watchdog Observer pour detection nouveaux fichiers (Story 3.5 - Task 3).

Surveille N dossiers configures dans watchdog.yaml.
Publie evenements document.received dans Redis Streams.

Features:
- Multi-path watching
- Extension filtering
- Hot-reload config (<10s)
- Error handling + retry
- Graceful shutdown
- Performance: <500ms latency, <100Mo RAM
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import structlog
from redis import asyncio as aioredis
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from agents.src.agents.archiviste.watchdog_config import (
    WatchdogConfigManager,
    WatchdogConfigSchema,
)
from agents.src.agents.archiviste.watchdog_handler import FridayWatchdogHandler

logger = structlog.get_logger(__name__)

# Intervalle check hot-reload config (secondes)
CONFIG_RELOAD_CHECK_INTERVAL = 5


class FridayWatchdogObserver:
    """
    Observateur principal Watchdog Friday 2.0.

    Orchestre les observers watchdog pour chaque dossier configure.
    Gere la connexion Redis, le hot-reload config, et le graceful shutdown.
    """

    def __init__(
        self,
        config_path: str = "config/watchdog.yaml",
        redis_url: str = "redis://localhost:6379/0",
        use_polling: bool = False,
    ):
        """
        Initialiser observateur.

        Args:
            config_path: Chemin vers watchdog.yaml
            redis_url: URL Redis pour Streams
            use_polling: Utiliser PollingObserver au lieu de natif
                         (utile pour NFS/Docker volumes)
        """
        self.config_manager = WatchdogConfigManager(config_path)
        self.redis_url = redis_url
        self.use_polling = use_polling

        self._observers: List[Observer] = []
        self._handlers: List[FridayWatchdogHandler] = []
        self.redis: Optional[aioredis.Redis] = None
        self._running = False
        self._reload_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """
        Demarrer les observers pour tous les dossiers configures.

        Connecte Redis, cree un observer par dossier, lance le hot-reload.
        """
        config = self.config_manager.config

        if not config.enabled:
            logger.info("watchdog.disabled_by_config")
            return

        # Connexion Redis
        await self._connect_redis()

        # Stocker le loop pour usage dans callbacks sync (M3 fix)
        self._loop = asyncio.get_running_loop()

        # Demarrer observers
        await self._start_observers(config, self._loop)

        # Lancer le check hot-reload periodique
        self._running = True
        self._reload_task = asyncio.create_task(self._config_reload_loop())

        logger.info(
            "watchdog.started",
            paths_count=len(config.paths),
            polling=self.use_polling
        )

    async def stop(self) -> None:
        """
        Arreter tous les observers gracefully.

        Stop le hot-reload, arrete les threads watchdog, ferme Redis.
        """
        self._running = False

        # Annuler la tache de hot-reload
        if self._reload_task and not self._reload_task.done():
            self._reload_task.cancel()
            try:
                await self._reload_task
            except asyncio.CancelledError:
                pass

        # Arreter les observers watchdog
        self._stop_observers()

        # Fermer Redis
        await self._disconnect_redis()

        logger.info("watchdog.stopped")

    async def _connect_redis(self) -> None:
        """Connecter a Redis."""
        if self.redis is None:
            self.redis = await aioredis.from_url(self.redis_url)
            logger.info(
                "watchdog.redis_connected",
                redis_url=self.redis_url
            )

    async def _disconnect_redis(self) -> None:
        """Deconnecter Redis."""
        if self.redis:
            await self.redis.close()
            self.redis = None
            logger.info("watchdog.redis_disconnected")

    async def _start_observers(
        self,
        config: WatchdogConfigSchema,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """
        Creer et demarrer un observer par dossier configure.

        Verifie que chaque dossier existe avant de le surveiller.
        """
        for path_config in config.paths:
            watch_path = Path(path_config.path)

            # Verifier que le dossier existe
            if not watch_path.exists():
                logger.warning(
                    "watchdog.path_not_found",
                    path=str(watch_path),
                    source_label=path_config.source_label
                )
                continue

            if not watch_path.is_dir():
                logger.warning(
                    "watchdog.path_not_directory",
                    path=str(watch_path),
                    source_label=path_config.source_label
                )
                continue

            # Creer handler
            handler = FridayWatchdogHandler(
                redis=self.redis,
                loop=loop,
                extensions=path_config.extensions,
                source_label=path_config.source_label,
                watched_root=path_config.path,
                workflow_target=path_config.workflow_target,
                stabilization_delay=config.stabilization_delay_seconds,
                error_directory=config.error_directory,
            )
            self._handlers.append(handler)

            # Creer observer (polling ou natif)
            if self.use_polling:
                observer = PollingObserver(
                    timeout=config.polling_interval_seconds
                )
            else:
                observer = Observer()

            observer.schedule(
                handler,
                path=str(watch_path),
                recursive=path_config.recursive
            )
            observer.daemon = True
            observer.start()
            self._observers.append(observer)

            logger.info(
                "watchdog.path_watching",
                path=str(watch_path),
                source_label=path_config.source_label,
                recursive=path_config.recursive,
                extensions=path_config.extensions
            )

    def _stop_observers(self) -> None:
        """Arreter tous les observers gracefully (join threads)."""
        for observer in self._observers:
            try:
                observer.stop()
            except Exception as e:
                logger.warning(
                    "watchdog.observer_stop_error",
                    error=str(e)
                )

        for observer in self._observers:
            try:
                observer.join(timeout=5)
            except Exception as e:
                logger.warning(
                    "watchdog.observer_join_error",
                    error=str(e)
                )

        self._observers.clear()
        self._handlers.clear()

    async def _config_reload_loop(self) -> None:
        """
        Boucle periodique pour verifier modification config (hot-reload AC7).

        Verifie toutes les CONFIG_RELOAD_CHECK_INTERVAL secondes.
        Gere le restart des observers directement (pas de callback sync-to-async).
        Publie notification Redis sur reload (AC7 Telegram via bot).
        """
        while self._running:
            try:
                await asyncio.sleep(CONFIG_RELOAD_CHECK_INTERVAL)
                if not self.config_manager.check_reload():
                    continue

                new_config = self.config_manager.config

                logger.info(
                    "watchdog.config_reload_triggered",
                    new_paths_count=len(new_config.paths),
                    enabled=new_config.enabled
                )

                # Arreter les observers actuels
                self._stop_observers()

                if new_config.enabled and self._loop:
                    await self._start_observers(new_config, self._loop)

                # AC7: Publier notification reload (bot -> Telegram topic System)
                await self._publish_config_reload_event(new_config)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "watchdog.config_reload_loop_error",
                    error=str(e)
                )

    async def _publish_config_reload_event(
        self,
        config: WatchdogConfigSchema,
    ) -> None:
        """
        Publier notification de reload config via Redis Pub/Sub (AC7).

        Non-critique (informatif) → Redis Pub/Sub (pas Streams).
        Le bot Telegram consomme et route vers topic System.
        """
        if not self.redis:
            return

        try:
            payload = json.dumps({
                "type": "config_reloaded",
                "service": "watchdog",
                "paths_count": len(config.paths),
                "enabled": config.enabled,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await self.redis.publish("system.notification", payload)

            logger.info(
                "watchdog.config_reload_notified",
                paths_count=len(config.paths)
            )
        except Exception as e:
            logger.warning(
                "watchdog.config_reload_notify_failed",
                error=str(e)
            )

    @property
    def is_running(self) -> bool:
        """Retourne True si au moins un observer est actif."""
        return self._running and len(self._observers) > 0

    @property
    def watched_paths_count(self) -> int:
        """Nombre de dossiers actuellement surveilles."""
        return len(self._observers)
