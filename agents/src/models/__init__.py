"""
Modèles Pydantic pour agents Friday 2.0.

Schémas de validation et structures de données.
"""

from agents.src.models.email_classification import EmailClassification
from agents.src.models.vip_detection import UrgencyResult, VIPSender

__all__ = ["EmailClassification", "VIPSender", "UrgencyResult"]
