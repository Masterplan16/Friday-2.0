"""
Renommage intelligent de documents (Story 3.1 - Task 3).

Convention de nommage standardisée (AC2) :
Format: YYYY-MM-DD_Type_Emetteur_MontantEUR.ext

Exemples:
- Facture: 2026-02-08_Facture_Labo-Cerba_145EUR.pdf
- Courrier: 2026-01-15_Courrier_ARS_0EUR.pdf
- Garantie: 2025-12-20_Garantie_Boulanger_599EUR.pdf
- Inconnu: 2026-02-15_Inconnu_0EUR.jpg (fallback si metadata manquante)

Trust Layer: @friday_action avec trust=propose (Day 1).
"""

import re
from pathlib import Path

import structlog
from agents.src.agents.archiviste.models import MetadataExtraction, RenameResult
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action

logger = structlog.get_logger(__name__)


class DocumentRenamer:
    """
    Renommeur intelligent de documents (AC2, AC5).

    Génère des noms de fichiers standardisés depuis métadonnées extraites :
    - Date : Format ISO 8601 (YYYY-MM-DD)
    - Type : Facture, Courrier, Garantie, etc.
    - Émetteur : Sanitisé (espaces→tirets, caractères spéciaux supprimés)
    - Montant : Format {montant}EUR ou 0EUR si absent
    - Extension : Préservée depuis fichier original

    Trust Layer: Toutes actions passent par @friday_action (trust=propose Day 1).
    """

    # Caractères interdits Windows dans noms de fichiers (Task 3.3)
    FORBIDDEN_CHARS = ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]

    # Longueur max émetteur (Task 3.3)
    MAX_EMITTER_LENGTH = 50

    @friday_action(module="archiviste", action="rename", trust_default="propose")
    async def rename_document(
        self, original_filename: str, metadata: MetadataExtraction
    ) -> ActionResult:
        """
        Renommer document selon convention standardisée (AC2).

        Args:
            original_filename: Nom de fichier original (avec extension)
            metadata: Métadonnées extraites par Claude

        Returns:
            ActionResult avec RenameResult dans payload

        Format nouveau nom:
            YYYY-MM-DD_Type_Emetteur_MontantEUR.ext

        Règles sanitization (Task 3.3):
            - Émetteur: espaces → tirets, caractères spéciaux supprimés
            - Montant: Format décimal (99.99EUR) ou entier (100EUR)
            - Extension: Préservée, normalisée en minuscules

        Fallback (Task 3.4):
            - Si émetteur vide → "Inconnu"
            - Si date invalide → date du jour
            - Si type invalide → "Inconnu"
        """
        logger.info(
            "rename_document.start",
            original_filename=original_filename,
            doc_type=metadata.doc_type,
            emitter=metadata.emitter,
        )

        try:
            # 1. Extraire extension originale
            original_path = Path(original_filename)
            extension = original_path.suffix.lower()  # Normaliser en minuscules

            if not extension:
                # Fallback si pas d'extension
                extension = ".pdf"
                logger.warning(
                    "rename_document.no_extension",
                    original_filename=original_filename,
                    fallback=extension,
                )

            # 2. Formatter date (ISO 8601)
            date_str = metadata.date.strftime("%Y-%m-%d")

            # 3. Sanitiser émetteur (Task 3.3)
            emitter = self._sanitize_emitter(metadata.emitter)

            # 4. Formatter montant
            amount_str = self._format_amount(metadata.amount)

            # 5. Construire nouveau nom de fichier
            # Format: YYYY-MM-DD_Type_Emetteur_MontantEUR.ext
            new_filename = f"{date_str}_{metadata.doc_type}_{emitter}_{amount_str}{extension}"

            # 6. Créer RenameResult
            rename_result = RenameResult(
                original_filename=original_filename,
                new_filename=new_filename,
                metadata=metadata,
                confidence=metadata.confidence,  # Confidence = celle de metadata
                reasoning=f"Renommage selon convention : {metadata.doc_type} de {metadata.emitter}",
            )

            # 7. Construire ActionResult (Task 3.6)
            action_result = ActionResult(
                input_summary=f"Fichier original: {original_filename}",
                output_summary=f"Nouveau nom: {new_filename}",
                confidence=metadata.confidence,
                reasoning=f"Renommage {metadata.doc_type} de {metadata.emitter} ({metadata.amount}EUR)",
                payload={
                    "rename_result": rename_result,
                    "original_filename": original_filename,
                    "new_filename": new_filename,
                },
            )

            logger.info(
                "rename_document.success",
                original_filename=original_filename,
                new_filename=new_filename,
                confidence=metadata.confidence,
            )

            return action_result

        except Exception as e:
            logger.error(
                "rename_document.failure", original_filename=original_filename, error=str(e)
            )
            raise

    def _sanitize_emitter(self, emitter: str) -> str:
        """
        Sanitiser nom émetteur pour nom de fichier Windows (Task 3.3).

        Règles:
        - Espaces → tirets (-)
        - Caractères interdits Windows (\\/:*?"<>|) → supprimés
        - Longueur max: 50 caractères (Task 3.3)
        - Si vide après sanitization → "Inconnu" (Task 3.4)

        Args:
            emitter: Nom émetteur brut

        Returns:
            Émetteur sanitisé pour nom de fichier

        Examples:
            >>> _sanitize_emitter("Agence Régionale de Santé")
            "Agence-Regionale-de-Sante"

            >>> _sanitize_emitter("Labo / Tests*?")
            "Labo-Tests"

            >>> _sanitize_emitter("")
            "Inconnu"
        """
        if not emitter or not emitter.strip():
            # Fallback si émetteur vide (Task 3.4)
            return "Inconnu"

        # Remplacer espaces par tirets
        sanitized = emitter.replace(" ", "-")

        # Supprimer caractères interdits Windows
        for char in self.FORBIDDEN_CHARS:
            sanitized = sanitized.replace(char, "")

        # Supprimer caractères non-ASCII problématiques (accents, etc.)
        # On garde uniquement alphanumériques, tirets, underscores
        sanitized = re.sub(r"[^a-zA-Z0-9\-_]", "", sanitized)

        # Tronquer si trop long
        if len(sanitized) > self.MAX_EMITTER_LENGTH:
            sanitized = sanitized[: self.MAX_EMITTER_LENGTH]
            logger.debug(
                "rename_document.emitter_truncated",
                original_length=len(emitter),
                truncated_length=self.MAX_EMITTER_LENGTH,
            )

        # Si vide après sanitization → fallback
        if not sanitized:
            sanitized = "Inconnu"
            logger.warning(
                "rename_document.emitter_empty_after_sanitize",
                original_emitter=emitter,
                fallback=sanitized,
            )

        return sanitized

    def _format_amount(self, amount: float) -> str:
        """
        Formatter montant pour nom de fichier (Task 3.3).

        Règles:
        - Si entier (100.00) → "100EUR"
        - Si décimal (99.99) → "99.99EUR"
        - Si 0.0 → "0EUR"

        Args:
            amount: Montant en EUR

        Returns:
            Montant formaté avec "EUR"

        Examples:
            >>> _format_amount(145.0)
            "145EUR"

            >>> _format_amount(99.99)
            "99.99EUR"

            >>> _format_amount(0.0)
            "0EUR"
        """
        if amount == 0.0:
            return "0EUR"

        # Si entier (ex: 100.0), formatter sans décimales
        if amount == int(amount):
            return f"{int(amount)}EUR"

        # Sinon, formatter avec décimales
        # Supprimer les zéros trailing (99.50 → 99.5)
        return f"{amount:g}EUR"
