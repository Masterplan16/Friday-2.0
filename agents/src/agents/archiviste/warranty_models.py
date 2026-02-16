"""
Modèles Pydantic pour le suivi des garanties (Story 3.4).

Définit les structures de données pour :
- WarrantyCategory : Enum catégories de garantie
- WarrantyInfo : Informations garantie extraites par Claude
- WarrantyExtractionResult : Résultat complet extraction
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class WarrantyCategory(str, Enum):
    """Catégories de garantie supportées (AC4)."""

    ELECTRONICS = "electronics"
    APPLIANCES = "appliances"
    AUTOMOTIVE = "automotive"
    MEDICAL = "medical"
    FURNITURE = "furniture"
    OTHER = "other"


class WarrantyInfo(BaseModel):
    """
    Informations garantie extraites par Claude (AC1).

    Attributes:
        warranty_detected: Si une garantie a été détectée
        item_name: Nom du produit
        item_category: Catégorie du produit
        vendor: Fournisseur/vendeur
        purchase_date: Date d'achat
        warranty_duration_months: Durée garantie en mois (1-120)
        purchase_amount: Montant achat en EUR
        confidence: Score de confiance [0.0-1.0]
    """

    warranty_detected: bool = Field(..., description="Si une garantie a été détectée")
    item_name: str = Field(..., min_length=1, max_length=500, description="Nom du produit")
    item_category: WarrantyCategory = Field(..., description="Catégorie du produit")
    vendor: Optional[str] = Field(None, max_length=255, description="Fournisseur/vendeur")
    purchase_date: date = Field(..., description="Date d'achat")
    warranty_duration_months: int = Field(
        ..., ge=1, le=120, description="Durée garantie en mois (1-120)"
    )
    purchase_amount: Optional[Decimal] = Field(None, ge=0, description="Montant achat en EUR")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Score de confiance extraction")

    @field_validator("purchase_date")
    @classmethod
    def validate_date_not_future(cls, v: date) -> date:
        """Date d'achat ne peut pas être dans le futur."""
        if v > date.today():
            raise ValueError("Purchase date cannot be in the future")
        return v

    @property
    def expiration_date(self) -> date:
        """Calcule la date d'expiration."""
        from dateutil.relativedelta import relativedelta

        return self.purchase_date + relativedelta(months=self.warranty_duration_months)


class WarrantyExtractionResult(BaseModel):
    """
    Résultat complet d'extraction de garantie (AC1).

    Attributes:
        warranty_info: Informations garantie (None si pas détectée)
        error: Message d'erreur si extraction échouée
    """

    warranty_info: Optional[WarrantyInfo] = None
    error: Optional[str] = None
