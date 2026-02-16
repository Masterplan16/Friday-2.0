"""
Gestionnaire de déplacement de fichiers pour l'agent Archiviste.

Story 3.2 - Task 3
Déplacement atomique documents de zone transit vers arborescence finale.
"""

import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Optional

import asyncpg
import structlog
from agents.src.agents.archiviste.models import ClassificationResult, MovedFile
from agents.src.config.arborescence_config import get_arborescence_config

logger = structlog.get_logger(__name__)


class FileMover:
    """
    Gestionnaire de déplacement de fichiers dans l'arborescence Friday.

    Déplace les documents de la zone de transit vers l'arborescence finale
    en utilisant une approche atomique (copy + verify + delete).

    Attributes:
        config: Configuration arborescence chargée
        db_pool: Pool de connexions PostgreSQL
    """

    def __init__(self, db_pool: Optional[asyncpg.Pool] = None):
        """
        Initialise le FileMover.

        Args:
            db_pool: Pool de connexions PostgreSQL (optionnel pour tests)
        """
        self._config = None
        self.db_pool = db_pool

    @property
    def config(self):
        """Lazy loading de la configuration arborescence."""
        if self._config is None:
            self._config = get_arborescence_config()
        return self._config

    async def move_document(
        self,
        source_path: str,
        classification: ClassificationResult,
        document_id: Optional[str] = None,
    ) -> MovedFile:
        """
        Déplace un document vers l'arborescence finale.

        Args:
            source_path: Chemin source du fichier
            classification: Résultat de classification (category, subcategory, path)
            document_id: ID du document dans BDD (optionnel)

        Returns:
            MovedFile avec succès/échec + chemins

        Raises:
            FileNotFoundError: Si fichier source introuvable
            PermissionError: Si permissions insuffisantes
        """
        source = Path(source_path)

        if not source.exists():
            logger.error("source_file_not_found", source=str(source))
            return MovedFile(
                source_path=str(source),
                destination_path="",
                success=False,
                error=f"Source file not found: {source}",
            )

        try:
            # Résolution chemin destination
            dest_path = self._resolve_destination_path(source, classification)
            dest = Path(dest_path)

            logger.info(
                "move_started",
                source=str(source),
                destination=str(dest),
                category=classification.category,
                subcategory=classification.subcategory,
            )

            # Créer dossiers parents si manquants
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Gérer conflits de nommage
            final_dest = self._handle_naming_conflict(dest)

            # Déplacement atomique : copy + verify + delete
            await self._atomic_move(source, final_dest)

            # Mettre à jour BDD si document_id fourni
            if document_id and self.db_pool:
                await self._update_database(
                    document_id=document_id,
                    final_path=str(final_dest),
                    classification=classification,
                )

            logger.info(
                "move_completed",
                source=str(source),
                destination=str(final_dest),
                category=classification.category,
            )

            return MovedFile(
                source_path=str(source), destination_path=str(final_dest), success=True, error=None
            )

        except Exception as e:
            logger.error(
                "move_failed", source=str(source), error=str(e), category=classification.category
            )
            return MovedFile(
                source_path=str(source), destination_path="", success=False, error=str(e)
            )

    def _resolve_destination_path(self, source: Path, classification: ClassificationResult) -> str:
        """
        Résout le chemin destination complet.

        Args:
            source: Chemin source du fichier
            classification: Résultat de classification

        Returns:
            Chemin destination complet
        """
        # Chemin racine depuis config
        root = Path(self.config.root_path)

        # Chemin relatif depuis classification
        relative_path = classification.path

        # Nom de fichier : garder le nom renommé de Story 3.1
        filename = source.name

        # Construire chemin complet
        full_path = root / relative_path / filename

        return str(full_path)

    def _handle_naming_conflict(self, dest: Path) -> Path:
        """
        Gère les conflits de nommage si fichier existe déjà.

        Ajoute suffixe _v2, _v3, etc. si collision.

        Args:
            dest: Chemin destination souhaité

        Returns:
            Chemin destination unique (éventuellement avec suffixe)
        """
        if not dest.exists():
            return dest

        # Extraire nom et extension
        stem = dest.stem
        suffix = dest.suffix

        # Chercher version disponible
        version = 2
        while True:
            new_dest = dest.parent / f"{stem}_v{version}{suffix}"
            if not new_dest.exists():
                logger.info(
                    "naming_conflict_resolved",
                    original=str(dest),
                    renamed=str(new_dest),
                    version=version,
                )
                return new_dest
            version += 1

            # Limite de sécurité (éviter boucle infinie)
            if version > 100:
                raise RuntimeError(f"Too many file versions: {dest}")

    async def _atomic_move(self, source: Path, dest: Path) -> None:
        """
        Déplacement atomique via fichier temporaire : copy→temp, verify, rename, delete source.

        Utilise un fichier .tmp dans le dossier destination. Si le process crash
        entre copy et rename, seul le .tmp reste (nettoyable). Le rename est
        atomique sur le même filesystem.

        Args:
            source: Fichier source
            dest: Fichier destination

        Raises:
            IOError: Si copy/verify échoue
        """
        # Fichier temporaire dans le même dossier (même filesystem = rename atomique)
        tmp_dest = dest.parent / f".{dest.name}.{uuid.uuid4().hex[:8]}.tmp"

        try:
            # Phase 1 : Copy vers fichier temporaire
            await asyncio.to_thread(shutil.copy2, source, tmp_dest)

            # Phase 2 : Verify (taille + checksum)
            source_size = source.stat().st_size
            tmp_size = tmp_dest.stat().st_size

            if source_size != tmp_size:
                raise IOError(
                    f"File size mismatch after copy: "
                    f"source={source_size} tmp={tmp_size} ({source} -> {tmp_dest})"
                )

            source_hash = await self._file_hash(source)
            tmp_hash = await self._file_hash(tmp_dest)

            if source_hash != tmp_hash:
                raise IOError(f"File checksum mismatch after copy: {source} -> {tmp_dest}")

            # Phase 3 : Rename temp → destination (atomique sur même FS)
            await asyncio.to_thread(tmp_dest.rename, dest)

            # Phase 4 : Delete source
            await asyncio.to_thread(source.unlink)

        except Exception:
            # Cleanup : supprimer fichier temporaire si rename n'a pas eu lieu
            if tmp_dest.exists():
                tmp_dest.unlink()
            raise

    @staticmethod
    async def _file_hash(path: Path, algorithm: str = "sha256") -> str:
        """
        Calcule le hash d'un fichier.

        Args:
            path: Chemin du fichier
            algorithm: Algorithme de hash (défaut: sha256)

        Returns:
            Hash hexadécimal du fichier
        """

        def _compute():
            h = hashlib.new(algorithm)
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()

        return await asyncio.to_thread(_compute)

    async def _update_database(
        self, document_id: str, final_path: str, classification: ClassificationResult
    ) -> None:
        """
        Met à jour PostgreSQL avec chemin final et classification.

        Args:
            document_id: ID du document
            final_path: Chemin final du fichier
            classification: Résultat de classification
        """
        if not self.db_pool:
            return

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ingestion.document_metadata
                SET final_path = $1,
                    classification_category = $2,
                    classification_subcategory = $3,
                    classification_confidence = $4
                WHERE document_id = $5
                """,
                final_path,
                classification.category,
                classification.subcategory,
                classification.confidence,
                document_id,
            )
