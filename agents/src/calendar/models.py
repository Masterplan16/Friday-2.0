"""Calendar event models."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    """Event model returned by ContextProvider."""

    model_config = ConfigDict(from_attributes=True)  # Pydantic v2

    id: UUID
    name: str
    start_datetime: str  # ISO 8601 format
    end_datetime: str  # ISO 8601 format
    casquette: Literal["medecin", "enseignant", "chercheur"]
    status: Literal["proposed", "confirmed", "cancelled"] = "confirmed"
    location: str | None = None
    description: str | None = None
    participants: list[str] = Field(default_factory=list)
    html_link: str | None = None
