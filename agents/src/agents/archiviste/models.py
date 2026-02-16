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
    confidence: float = Field(..., ge=0.0, le=1.0, description="Score de confiance moyen de l'OCR")
    page_count: int = Field(..., ge=1, description="Nombre de pages OCR")
    language: str = Field(default="fr", description="Langue détectée")
    processing_time: float = Field(
        default=0.0, ge=0.0, description="Durée traitement OCR (secondes)"
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
        ..., description="Type: Facture, Courrier, Garantie, Contrat, Releve, Attestation, Inconnu"
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
            "Facture",
            "Courrier",
            "Garantie",
            "Contrat",
            "Releve",
            "Attestation",
            "Inconnu",
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
        if "." not in v:
            raise ValueError("New filename must have an extension")

        return v


class ClassificationResult(BaseModel):
    """
    Résultat de classification d'un document (Story 3.2 - Task 1.5).

    Attributes:
        category: Catégorie principale (pro, finance, universite, recherche, perso)
        subcategory: Sous-catégorie (obligatoire pour finance)
        path: Chemin relatif calculé dans l'arborescence
        confidence: Score de confiance [0.0-1.0]
        reasoning: Explication de la classification
    """

    category: str = Field(..., description="Catégorie principale du document")
    subcategory: Optional[str] = Field(
        None, description="Sous-catégorie (obligatoire si category=finance)"
    )
    path: str = Field(..., description="Chemin relatif dans l'arborescence finale")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Score de confiance de la classification"
    )
    reasoning: str = Field(..., description="Explication textuelle de la décision")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Valide que la catégorie est dans la liste autorisée."""
        valid_categories = {"pro", "finance", "universite", "recherche", "perso"}
        if v not in valid_categories:
            raise ValueError(f"Invalid category '{v}'. Must be one of: {valid_categories}")
        return v

    @field_validator("subcategory")
    @classmethod
    def validate_finance_subcategory(cls, v: Optional[str], info) -> Optional[str]:
        """Valide le périmètre financier si category=finance."""
        # Accéder à category depuis les données du modèle
        if "category" in info.data and info.data["category"] == "finance":
            if v is None:
                raise ValueError("Finance category requires subcategory")

            valid_finance_perimeters = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}

            if v not in valid_finance_perimeters:
                raise ValueError(
                    f"Invalid financial perimeter '{v}'. "
                    f"Must be one of: {valid_finance_perimeters}"
                )

        return v


class MovedFile(BaseModel):
    """
    Résultat du déplacement d'un fichier (Story 3.2 - Task 3).

    Attributes:
        source_path: Chemin source original
        destination_path: Chemin destination final
        success: Succès du déplacement
        error: Message d'erreur si échec
    """

    source_path: str = Field(..., description="Chemin source du fichier")
    destination_path: str = Field(..., description="Chemin destination final")
    success: bool = Field(..., description="Succès de l'opération")
    error: Optional[str] = Field(None, description="Message d'erreur si échec")


class EmbeddingResult(BaseModel):
    """
    Résultat de génération d'embedding pour un document (Story 3.3 - Task 1.5).

    Attributes:
        document_id: UUID du document dans ingestion.document_metadata
        embedding_vector: Vecteur embedding (1024 dimensions pour voyage-4-large)
        model_name: Nom du modèle utilisé (voyage-4-large)
        confidence: Score de confiance [0.0-1.0]
        metadata: Métadonnées optionnelles (filename, category, etc.)
    """

    document_id: str = Field(..., description="UUID du document")
    embedding_vector: list[float] = Field(..., description="Vecteur embedding 1024 dims")
    model_name: str = Field(default="voyage-4-large", description="Modèle embeddings")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Score de confiance")
    metadata: dict = Field(default_factory=dict, description="Métadonnées optionnelles")

    @field_validator("embedding_vector")
    @classmethod
    def validate_dimensions(cls, v: list[float]) -> list[float]:
        """Valide que l'embedding a exactement 1024 dimensions."""
        if len(v) != 1024:
            raise ValueError(f"Expected 1024 dimensions, got {len(v)}")
        return v


class SearchResult(BaseModel):
    """
    Résultat de recherche sémantique (Story 3.3 - Task 4.9).

    Attributes:
        document_id: UUID du document trouvé
        title: Titre du document (filename ou metadata.title)
        path: Chemin absolu vers le fichier
        score: Score de similarité cosinus [0.0-1.0]
        excerpt: Extrait pertinent du document (200 chars)
        metadata: Métadonnées complètes du document
    """

    document_id: str = Field(..., description="UUID du document")
    title: str = Field(..., description="Titre du document")
    path: str = Field(..., description="Chemin absolu fichier")
    score: float = Field(..., ge=0.0, le=1.0, description="Score similarité cosinus")
    excerpt: str = Field(..., max_length=250, description="Extrait pertinent ~200 chars")
    metadata: dict = Field(default_factory=dict, description="Métadonnées document")
