"""
Surya OCR Engine pour Friday 2.0 (Story 3.1 - AC1).

Implémente l'OCR de documents (images JPG/PNG/TIFF, PDF) via Surya OCR
en mode CPU uniquement (VPS sans GPU).

Usage:
    engine = SuryaOCREngine(device="cpu")
    result = await engine.ocr_document("facture.pdf")
    print(result.text, result.confidence)
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

from agents.src.agents.archiviste.models import OCRResult


class SuryaOCREngine:
    """
    Moteur OCR basé sur Surya (AC1).

    Surya est un modèle OCR multilingue (90+ langues dont français)
    optimisé pour CPU, utilisable sans GPU.

    Attributes:
        device: Device Torch ('cpu' ou 'cuda')
        model: Modèle Surya chargé (lazy loading)
        processor: Processeur Surya pour pre/post-processing
    """

    # Formats de fichiers supportés (AC1, Dev Notes)
    SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".pdf"}

    def __init__(self, device: str = "cpu"):
        """
        Initialiser le moteur OCR Surya.

        Args:
            device: Device Torch ('cpu' ou 'cuda'). Default 'cpu' pour VPS.

        Note:
            Le modèle Surya est chargé à la demande (lazy loading)
            au premier appel ocr_document() pour économiser RAM.
        """
        self.device = device
        self.model: Optional[object] = None
        self.processor: Optional[object] = None

    async def _load_model_if_needed(self):
        """
        Charger le modèle Surya à la demande (lazy loading, Task 1.5).

        Le modèle est téléchargé automatiquement au premier lancement
        (~400 Mo, stocké dans cache Hugging Face ~/.cache/huggingface/).

        Raises:
            NotImplementedError: Si le chargement du modèle échoue (AC7).
        """
        if self.model is not None and self.processor is not None:
            # Modèle déjà chargé
            return

        try:
            # Configurer TORCH_DEVICE avant import Surya (Task 1.3, M2 fix)
            os.environ["TORCH_DEVICE"] = self.device

            # Import dynamique pour éviter le chargement au démarrage
            from surya.model.detection.model import load_model as load_det_model
            from surya.model.detection.processor import load_processor as load_det_processor
            from surya.model.recognition.model import load_model as load_rec_model
            from surya.model.recognition.processor import load_processor as load_rec_processor

            # Charger modèles de détection et reconnaissance
            # Note: Surya 0.17.0+ utilise des modèles séparés pour détection + OCR
            self.det_model = await asyncio.to_thread(load_det_model)
            self.det_processor = await asyncio.to_thread(load_det_processor)
            self.rec_model = await asyncio.to_thread(load_rec_model)
            self.rec_processor = await asyncio.to_thread(load_rec_processor)

            # Marquer comme chargé
            self.model = self.rec_model
            self.processor = self.rec_processor

        except Exception as e:
            # Fail-explicit (AC7, NFR7) : Si Surya crash, on lève NotImplementedError
            raise NotImplementedError(
                f"Surya OCR unavailable: Failed to load model - {str(e)}"
            ) from e

    def _validate_file_format(self, file_path: str) -> None:
        """
        Valider que le format de fichier est supporté.

        Args:
            file_path: Chemin vers le fichier à OCR

        Raises:
            ValueError: Si le format n'est pas supporté
            FileNotFoundError: Si le fichier n'existe pas
        """
        path = Path(file_path)

        # Vérifier existence fichier
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Vérifier extension supportée
        if path.suffix.lower() not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported file format: {path.suffix}. "
                f"Supported: {', '.join(self.SUPPORTED_FORMATS)}"
            )

    async def ocr_document(self, file_path: str, language: str = "fr") -> OCRResult:
        """
        Effectuer l'OCR sur un document (image ou PDF).

        Args:
            file_path: Chemin vers le fichier à traiter
            language: Code langue pour OCR (default 'fr'). Surya supporte 90+ langues.

        Returns:
            OCRResult avec texte extrait, confidence, nombre de pages

        Raises:
            FileNotFoundError: Si le fichier n'existe pas
            ValueError: Si le format de fichier n'est pas supporté
            NotImplementedError: Si Surya crash (fail-explicit AC7)

        Performance:
            - Image 1 page : ~5-15s (CPU mode)
            - PDF 3-5 pages : ~20-30s (CPU mode)
        """
        start_time = time.time()

        # Valider fichier et format
        self._validate_file_format(file_path)

        # Charger modèle si nécessaire (lazy loading)
        await self._load_model_if_needed()

        try:
            # Import dynamique
            import fitz  # PyMuPDF pour PDF
            from PIL import Image
            from surya.ocr import run_ocr

            # Charger document
            path = Path(file_path)
            images = []

            if path.suffix.lower() == ".pdf":
                # Convertir PDF en images
                pdf_doc = fitz.open(file_path)
                for page_num in range(len(pdf_doc)):
                    page = pdf_doc[page_num]
                    pix = page.get_pixmap()
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    images.append(img)
                pdf_doc.close()
            else:
                # Charger image directement
                images = [Image.open(file_path)]

            # Exécuter OCR avec Surya
            # Note: run_ocr() est synchrone, on l'exécute dans un thread
            predictions = await asyncio.to_thread(
                run_ocr,
                images,
                [[language]],  # Langue configurable (default 'fr')
                self.det_model,
                self.det_processor,
                self.rec_model,
                self.rec_processor,
            )

            # Extraire texte et confidence
            all_text = []
            all_confidences = []

            for page_pred in predictions:
                for line in page_pred.text_lines:
                    all_text.append(line.text)
                    # Calculer confidence moyenne (Surya retourne confidence par caractère)
                    if hasattr(line, "confidence"):
                        all_confidences.append(line.confidence)

            # Concaténer tout le texte avec saut de ligne
            full_text = "\n".join(all_text)

            # Calculer confidence moyenne
            if all_confidences:
                avg_confidence = sum(all_confidences) / len(all_confidences)
            else:
                # Si pas de texte détecté, confidence = 0
                avg_confidence = 0.0

            processing_time = time.time() - start_time

            return OCRResult(
                text=full_text,
                confidence=round(avg_confidence, 2),
                page_count=len(images),
                language=language,
                processing_time=round(processing_time, 2),
            )

        except Exception as e:
            # Fail-explicit (AC7) : Si Surya crash pendant l'OCR
            if isinstance(e, (FileNotFoundError, ValueError, NotImplementedError)):
                # Re-raise les erreurs déjà typées
                raise

            # Autres erreurs Surya → NotImplementedError
            raise NotImplementedError(
                f"Surya OCR unavailable: OCR processing failed - {str(e)}"
            ) from e
