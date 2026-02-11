"""
Models Pydantic pour pièces jointes emails.

Story 2.4 - Extraction Pièces Jointes
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


MAX_ATTACHMENT_SIZE_BYTES = 26214400  # 25 Mo (EmailEngine limite)
MAX_FILENAME_LENGTH = 200


class Attachment(BaseModel):
    """Métadonnées pièce jointe email extraite."""

    id: UUID
    email_id: UUID
    filename: str = Field(..., max_length=MAX_FILENAME_LENGTH)
    filepath: str
    size_bytes: int = Field(..., gt=0, le=MAX_ATTACHMENT_SIZE_BYTES)
    mime_type: str
    status: Literal['pending', 'processed', 'archived', 'error'] = 'pending'
    extracted_at: datetime
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator('filename')
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Valide nom fichier (max 200 chars, pas vide)."""
        if not v or not v.strip():
            raise ValueError("Filename cannot be empty")

        if len(v) > MAX_FILENAME_LENGTH:
            raise ValueError(f"Filename too long (max {MAX_FILENAME_LENGTH} chars)")

        return v.strip()

    @field_validator('mime_type')
    @classmethod
    def validate_mime_type(cls, v: str) -> str:
        """Valide format MIME type (type/subtype)."""
        if not v or '/' not in v:
            raise ValueError("Invalid MIME type format (expected: type/subtype)")

        parts = v.split('/')
        if len(parts) != 2 or not all(parts):
            raise ValueError("Invalid MIME type format")

        return v.lower()  # Normalisation lowercase

    @field_validator('filepath')
    @classmethod
    def validate_filepath(cls, v: str) -> str:
        """Valide filepath (pas vide, format Unix)."""
        if not v or not v.strip():
            raise ValueError("Filepath cannot be empty")

        # Format Unix paths (zone transit VPS)
        if not v.startswith('/'):
            raise ValueError("Filepath must be absolute Unix path")

        return v.strip()

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "email_id": "123e4567-e89b-12d3-a456-426614174001",
                "filename": "facture_2026.pdf",
                "filepath": "/var/friday/transit/attachments/2026-02-11/123_0_facture_2026.pdf",
                "size_bytes": 150000,
                "mime_type": "application/pdf",
                "status": "pending",
                "extracted_at": "2026-02-11T10:30:00Z",
                "processed_at": None,
                "created_at": "2026-02-11T10:30:00Z",
                "updated_at": "2026-02-11T10:30:00Z"
            }
        }
    }


class AttachmentExtractResult(BaseModel):
    """
    Résultat extraction pièces jointes (compatible ActionResult).

    Utilisé par @friday_action pour logging et métriques Trust Layer.
    """

    extracted_count: int = Field(..., ge=0)
    failed_count: int = Field(..., ge=0)
    total_size_mb: float = Field(..., ge=0.0)
    filepaths: list[str] = Field(default_factory=list)

    # Fields ActionResult (Trust Layer)
    input_summary: str = ""
    output_summary: str = ""
    confidence: float = Field(1.0, ge=0.0, le=1.0)  # Extraction = déterministe
    reasoning: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)  # Middleware trust compatibility

    @field_validator('filepaths')
    @classmethod
    def validate_filepaths(cls, v: list[str]) -> list[str]:
        """Valide liste filepaths (Unix paths absolus)."""
        for filepath in v:
            if not filepath.startswith('/'):
                raise ValueError(f"Filepath must be absolute Unix path: {filepath}")

        return v

    def generate_summaries(self, email_id: str, attachments_total: int) -> None:
        """
        Génère input_summary et output_summary pour ActionResult.

        Args:
            email_id: ID email source
            attachments_total: Nombre total attachments dans email
        """
        self.input_summary = f"Email {email_id} avec {attachments_total} pièce(s) jointe(s)"
        self.output_summary = f"→ {self.extracted_count} extraite(s), {self.failed_count} ignorée(s)"

        # Reasoning détaillé
        reasons = []
        if self.extracted_count > 0:
            reasons.append(f"{self.extracted_count} PJ extraites ({self.total_size_mb:.2f} Mo)")
        if self.failed_count > 0:
            reasons.append(f"{self.failed_count} PJ ignorées (MIME bloqué ou taille)")

        self.reasoning = "Extraction PJ : " + ", ".join(reasons) if reasons else "Aucune PJ à extraire"

    def model_dump_receipt(self) -> dict[str, Any]:
        """
        Export formaté pour stockage dans core.action_receipts.

        Méthode requise par middleware trust (@friday_action).
        Les champs module, action_type, action_id sont ajoutés dynamiquement
        par le décorateur @friday_action.

        Returns:
            Dict compatible avec structure table core.action_receipts
        """
        # Champs ajoutés dynamiquement par @friday_action
        module = getattr(self, 'module', None)
        action_type = getattr(self, 'action_type', None)
        action_id = getattr(self, 'action_id', None)

        if module is None or action_type is None:
            raise ValueError(
                "module and action_type must be set by @friday_action before creating receipt"
            )

        # Payload avec stats extraction (merge avec payload existant)
        payload_merged = {
            **self.payload,  # Existing payload
            'extracted_count': self.extracted_count,
            'failed_count': self.failed_count,
            'total_size_mb': self.total_size_mb,
            'filepaths': self.filepaths
        }

        return {
            "id": str(action_id) if action_id else None,
            "module": module,
            "action_type": action_type,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "payload": payload_merged,
            "status": "auto",  # Trust level default
            "trust_level": "auto",
            "duration_ms": getattr(self, 'duration_ms', None)  # Calculé par middleware
        }

    model_config = {
        "extra": "allow",  # Permet champs additionnels du middleware trust (@friday_action)
        "json_schema_extra": {
            "example": {
                "extracted_count": 2,
                "failed_count": 1,
                "total_size_mb": 0.38,
                "filepaths": [
                    "/var/friday/transit/attachments/2026-02-11/123_0_facture.pdf",
                    "/var/friday/transit/attachments/2026-02-11/123_1_photo.jpg"
                ],
                "input_summary": "Email abc123 avec 3 pièce(s) jointe(s)",
                "output_summary": "→ 2 extraite(s), 1 ignorée(s)",
                "confidence": 1.0,
                "reasoning": "Extraction PJ : 2 PJ extraites (0.38 Mo), 1 PJ ignorées (MIME bloqué ou taille)"
            }
        }
    }
