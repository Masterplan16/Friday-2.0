"""
Modèles Pydantic pour l'agent Archiviste (Story 3.1).

Définit les structures de données pour :
- OCRResult : Résultat d'OCR Surya
- MetadataExtraction : Métadonnées extraites par Claude
- RenameResult : Résultat du renommage intelligent
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class OCRResult(BaseModel):
    """
    Résultat de l'OCR Surya (AC1).

    Attributes:
        text: Texte extrait du document (toutes pages concaténées)
        confidence: Score de confiance moyen (0.0-1.0)
        page_count: Nombre de pages traitées
        language: Langue détectée (ex: 'fr', 'en')
        processing_time: Durée du traitement OCR en secondes
    """
    text: str = Field(..., description="Texte OCR extrait")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score de confiance moyen de l'OCR"
    )
    page_count: int = Field(..., ge=1, description="Nombre de pages OCR")
    language: str = Field(default="fr", description="Langue détectée")
    processing_time: float = Field(
        default=0.0,
        ge=0.0,
        description="Durée traitement OCR (secondes)"
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_none(cls, v):
        """Valider que le texte n'est pas None (peut être vide)."""
        if v is None:
            raise ValueError("OCR text cannot be None")
        return v


class MetadataExtraction(BaseModel):
    """
    Métadonnées extraites par Claude depuis texte OCR (AC3, Task 2).

    Format pour renommage intelligent : YYYY-MM-DD_Type_Emetteur_MontantEUR.ext

    Attributes:
        date: Date du document (extraction Claude ou fallback date du jour)
        doc_type: Type de document (Facture, Courrier, Garantie, etc.)
        emitter: Émetteur/Expéditeur du document
        amount: Montant en EUR (0.0 si absent)
        confidence: Score de confiance de l'extraction (0.0-1.0)
        reasoning: Explication de la décision d'extraction
    """
    date: datetime = Field(..., description="Date du document")
    doc_type: str = Field(
        ...,
        description="Type: Facture, Courrier, Garantie, Contrat, Releve, Attestation, Inconnu"
    )
    emitter: str = Field(..., description="Émetteur du document")
    amount: float = Field(default=0.0, ge=0.0, description="Montant en EUR")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiance extraction")
    reasoning: str = Field(..., description="Explication de l'extraction")

    @field_validator("doc_type")
    @classmethod
    def validate_doc_type(cls, v):
        """Valider que le type de document est dans la liste autorisée."""
        allowed_types = {
            "Facture", "Courrier", "Garantie", "Contrat",
            "Releve", "Attestation", "Inconnu"
        }
        if v not in allowed_types:
            # Fallback vers "Inconnu" si type non reconnu
            return "Inconnu"
        return v

    @field_validator("emitter")
    @classmethod
    def validate_emitter_not_empty(cls, v):
        """Valider que l'émetteur n'est pas vide. Sanitization dans DocumentRenamer."""
        if not v or not v.strip():
            return "Inconnu"
        return v


class RenameResult(BaseModel):
    """
    Résultat du renommage intelligent (AC2, Task 3).

    Attributes:
        original_filename: Nom de fichier original
        new_filename: Nouveau nom de fichier standardisé
        metadata: Métadonnées extraites utilisées pour renommage
        confidence: Confiance globale du renommage (min des confidences OCR + extraction)
        reasoning: Explication de la décision de renommage
    """
    original_filename: str = Field(..., description="Nom fichier original")
    new_filename: str = Field(..., description="Nouveau nom standardisé")
    metadata: MetadataExtraction = Field(..., description="Métadonnées utilisées")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiance globale")
    reasoning: str = Field(..., description="Explication du renommage")

    @field_validator("new_filename")
    @classmethod
    def validate_filename_format(cls, v):
        """
        Valider que le nouveau nom de fichier suit le format standardisé.

        Format attendu : YYYY-MM-DD_Type_Emetteur_MontantEUR.ext
        """
        if not v:
            raise ValueError("New filename cannot be empty")

        # Vérifier présence d'une extension
        if '.' not in v:
            raise ValueError("New filename must have an extension")

        return v
