"""
Bot Telegram Friday 2.0 - Pydantic Models

Modèles de données pour événements Telegram, configuration topics, etc.
"""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TelegramEvent(BaseModel):
    """
    Événement à router vers un topic Telegram.

    Utilisé pour déterminer dans quel topic envoyer une notification.
    """

    source: str | None = Field(None, description="Source de l'événement (heartbeat, proactive)")
    module: str | None = Field(None, description="Module Friday concerné (email, desktop_search)")
    type: str = Field(..., description="Type d'événement (action.pending, email.classified)")
    priority: str = Field("info", description="Priorité (critical, warning, info, debug)")
    message: str = Field(..., description="Contenu du message à envoyer")
    payload: dict[str, Any] = Field(default_factory=dict, description="Données additionnelles")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp événement")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """MED-4 fix: Valide format event.type (pattern: module.action)."""
        pattern = r"^[a-z_]+\.[a-z_]+$"
        if not re.match(pattern, v):
            raise ValueError(f"event.type doit matcher '{pattern}', reçu: {v}")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        """Valide que priority est dans les valeurs autorisées."""
        allowed = {"critical", "warning", "info", "debug"}
        if v not in allowed:
            raise ValueError(f"Priority doit être dans {allowed}, reçu: {v}")
        return v


class TopicConfig(BaseModel):
    """Configuration d'un topic Telegram."""

    name: str = Field(..., description="Nom du topic (ex: 'Chat & Proactive')")
    thread_id: int = Field(..., description="Thread ID du topic dans le supergroup")
    icon: str | None = Field(None, description="Emoji/icon du topic")
    description: str | None = Field(None, description="Description du topic")

    @field_validator("thread_id")
    @classmethod
    def validate_thread_id(cls, v: int) -> int:
        """Valide que thread_id est valide (>0)."""
        if v <= 0:
            raise ValueError(f"thread_id doit être >0, reçu: {v}")
        return v


class BotConfig(BaseModel):
    """Configuration complète du bot Telegram."""

    token: str = Field(..., description="Token du bot Telegram (@BotFather)")
    supergroup_id: int = Field(..., description="Chat ID du supergroup Friday 2.0 Control")
    topics: dict[str, TopicConfig] = Field(..., description="Mapping nom → config topic")
    heartbeat_interval_sec: int = Field(60, description="Intervalle heartbeat en secondes")
    rate_limit_msg_per_sec: int = Field(
        25, description="Rate limit messages/sec (marge sécurité vs 30)"
    )
    max_message_length: int = Field(4096, description="Longueur max message Telegram")

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        """Valide format du token Telegram (basic check)."""
        if not v or ":" not in v:
            raise ValueError("Token Telegram invalide (format attendu: <bot_id>:<token>)")
        return v

    @field_validator("supergroup_id")
    @classmethod
    def validate_supergroup_id(cls, v: int) -> int:
        """Valide que supergroup_id est négatif (format groupes Telegram)."""
        if v >= 0:
            raise ValueError(f"supergroup_id doit être négatif (groupe), reçu: {v}")
        return v


class MessageMetadata(BaseModel):
    """Métadonnées d'un message Telegram reçu."""

    user_id: int = Field(..., description="User ID Telegram de l'expéditeur")
    chat_id: int = Field(..., description="Chat ID (supergroup)")
    thread_id: int | None = Field(None, description="Thread ID du topic (None si General)")
    message_id: int = Field(..., description="Message ID unique Telegram")
    text: str | None = Field(None, description="Texte du message")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp réception")
