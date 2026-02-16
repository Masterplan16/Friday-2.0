"""
Handler evenements filesystem Watchdog (Story 3.5 - Task 4).

Filtre les extensions autorisees.
Publie dans Redis Streams document.received.
Retry automatique avec backoff exponentiel.
Validation path traversal.
Deplacement vers error_directory si echec persistant (AC5).
"""

import asyncio
import shutil
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

import structlog
from redis import asyncio as aioredis
from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler

logger = structlog.get_logger(__name__)

# Stream Redis pour documents recus (dot notation CLAUDE.md)
DOCUMENT_RECEIVED_STREAM = "document.received"

# Retry config
MAX_RETRIES = 3
BACKOFF_BASE = 1  # 1s, 2s, 4s


class FridayWatchdogHandler(FileSystemEventHandler):
    """
    Handler pour evenements filesystem.

    Filtre les extensions autorisees.
    Publie dans Redis Streams document.received.
    Retry automatique avec backoff exponentiel (1s, 2s, 4s).
    Validation path traversal (securite).
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        loop: asyncio.AbstractEventLoop,
        extensions: List[str],
        source_label: str,
        watched_root: str,
        workflow_target: Optional[str] = None,
        stabilization_delay: float = 1.0,
        error_directory: Optional[str] = None,
    ):
        """
        Initialiser handler.

        Args:
            redis: Client Redis async pour Streams
            loop: Event loop asyncio (pour bridge sync->async)
            extensions: Extensions autorisees (ex: [".pdf", ".csv"])
            source_label: Label source (ex: "scanner_physique")
            watched_root: Racine du dossier surveille (pour path traversal check)
            workflow_target: n8n workflow ID cible
            stabilization_delay: Delai attente ecriture complete (secondes)
            error_directory: Dossier pour fichiers en erreur (AC5)
        """
        super().__init__()
        self.redis = redis
        self._loop = loop
        self.extensions = [ext.lower() for ext in extensions]
        self.source_label = source_label
        self.watched_root = Path(watched_root).resolve()
        self.workflow_target = workflow_target or "default"
        self.stabilization_delay = stabilization_delay
        self.error_directory = Path(error_directory) if error_directory else None

    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle file creation event (sync callback from watchdog thread)."""
        if event.is_directory:
            return
        self._process_event(event.src_path)

    def on_moved(self, event: FileMovedEvent) -> None:
        """Handle file moved/renamed event (supports file copy into folder)."""
        if event.is_directory:
            return
        self._process_event(event.dest_path)

    def _process_event(self, src_path: str) -> None:
        """
        Traiter un evenement fichier.

        Valide extension, path traversal, puis dispatch vers async.
        """
        file_path = Path(src_path)

        # Filtrer extensions
        if file_path.suffix.lower() not in self.extensions:
            logger.debug(
                "watchdog.ignored_extension", path=str(file_path), extension=file_path.suffix
            )
            return

        # Validation path traversal (securite) — is_relative_to (Python 3.9+)
        try:
            resolved = file_path.resolve()
            if not resolved.is_relative_to(self.watched_root):
                logger.warning(
                    "watchdog.path_traversal_blocked",
                    path=str(file_path),
                    watched_root=str(self.watched_root),
                )
                return
        except (OSError, ValueError) as e:
            logger.error("watchdog.path_resolve_failed", path=str(file_path), error=str(e))
            return

        # Bridge sync watchdog thread -> async event loop
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._handle_file_detected(resolved), self._loop)
        else:
            logger.warning("watchdog.event_loop_not_running", path=str(file_path))

    async def _handle_file_detected(self, file_path: Path) -> None:
        """
        Attendre stabilisation fichier puis publier event Redis.

        Stabilisation = attendre que la taille ne change plus pendant
        stabilization_delay secondes (evite traiter fichier en cours d'ecriture).

        Si echec persistant (AC5) : deplace vers error_directory, publie
        pipeline.error (best effort), log error.
        """
        try:
            # Attendre stabilisation (fichier pas encore fini d'etre copie)
            if self.stabilization_delay > 0:
                stable = await self._wait_for_stabilization(file_path)
                if not stable:
                    logger.warning("watchdog.file_not_stable", filename=file_path.name)
                    return

            await self._publish_with_retry(file_path)

        except Exception as e:
            logger.error("watchdog.handle_failed", filename=file_path.name, error=str(e))
            # AC5: Deplacer vers error_directory + publier pipeline.error
            self._move_to_error_dir(file_path)
            await self._publish_pipeline_error(file_path, e)

    async def _wait_for_stabilization(self, file_path: Path, max_wait: float = 10.0) -> bool:
        """
        Attendre que le fichier soit stable (ecriture complete).

        Verifie toutes les 0.5s que la taille ne change plus.

        Returns:
            True si fichier stable, False si timeout ou disparu.
        """
        start = time.monotonic()
        prev_size = -1

        while time.monotonic() - start < max_wait:
            try:
                current_size = file_path.stat().st_size
            except OSError:
                # Fichier supprime pendant attente
                return False

            if current_size == prev_size and current_size > 0:
                return True

            prev_size = current_size
            await asyncio.sleep(self.stabilization_delay)

        # Timeout - on traite quand meme si le fichier existe
        return file_path.exists()

    async def _publish_with_retry(self, file_path: Path) -> None:
        """
        Publier document.received dans Redis Streams avec retry.

        Retry : 3x backoff exponentiel (1s, 2s, 4s).
        """
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Recuperer taille fichier
                try:
                    file_size = file_path.stat().st_size
                except OSError:
                    logger.warning("watchdog.file_disappeared", filename=file_path.name)
                    return

                # Format plat Redis Streams (coherent avec attachment_extractor.py)
                event_data = {
                    "filename": file_path.name,
                    "filepath": str(file_path),
                    "extension": file_path.suffix.lower(),
                    "source": self.source_label,
                    "workflow_target": self.workflow_target,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "size_bytes": str(file_size),
                }

                await self.redis.xadd(
                    DOCUMENT_RECEIVED_STREAM,
                    event_data,
                    maxlen=10000,
                )

                logger.info(
                    "watchdog.document_detected",
                    filename=file_path.name,
                    source=self.source_label,
                    size_bytes=file_size,
                    extension=file_path.suffix.lower(),
                )
                return  # Success

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    backoff = BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        "watchdog.publish_retry",
                        filename=file_path.name,
                        attempt=attempt,
                        max_retries=MAX_RETRIES,
                        backoff=backoff,
                        error=str(e),
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "watchdog.publish_failed",
                        filename=file_path.name,
                        attempts=MAX_RETRIES,
                        error=str(e),
                    )

        # Toutes tentatives echouees
        raise last_error

    def _move_to_error_dir(self, file_path: Path) -> None:
        """
        Deplacer fichier problematique vers error_directory/{date}/ (AC5).

        Cree le sous-dossier date si necessaire.
        Si error_directory non configure, log seulement.
        """
        if not self.error_directory:
            return

        try:
            today = date.today().isoformat()
            error_subdir = self.error_directory / today
            error_subdir.mkdir(parents=True, exist_ok=True)

            dest = error_subdir / file_path.name
            # Eviter ecrasement si fichier existe deja
            if dest.exists():
                stem = file_path.stem
                suffix = file_path.suffix
                dest = error_subdir / f"{stem}_{int(time.time())}{suffix}"

            shutil.move(str(file_path), str(dest))

            logger.info(
                "watchdog.file_moved_to_errors", filename=file_path.name, destination=str(dest)
            )

        except Exception as e:
            logger.error("watchdog.error_dir_move_failed", filename=file_path.name, error=str(e))

    async def _publish_pipeline_error(
        self,
        file_path: Path,
        error: Exception,
    ) -> None:
        """
        Publier pipeline.error dans Redis Streams (best effort, AC5).

        Si Redis est down (cause probable de l'erreur), ce publish echouera
        aussi — dans ce cas on log seulement. Le bot Telegram consommera
        pipeline.error pour envoyer l'alerte topic System.
        """
        try:
            event_data = {
                "event_type": "pipeline.error",
                "source": "watchdog",
                "source_label": self.source_label,
                "filename": file_path.name,
                "filepath": str(file_path),
                "error": str(error),
                "retry_count": str(MAX_RETRIES),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await self.redis.xadd(
                "pipeline.error",
                event_data,
                maxlen=5000,
            )

            logger.info("watchdog.pipeline_error_published", filename=file_path.name)

        except Exception as publish_err:
            # Best effort — Redis peut etre la cause de l'erreur initiale
            logger.error(
                "watchdog.pipeline_error_publish_failed",
                filename=file_path.name,
                error=str(publish_err),
            )
