"""
Middleware Trust Layer pour Friday 2.0.

Ce package fournit les outils d'observabilité et de contrôle pour toutes les actions
des modules Friday. Chaque action doit utiliser le décorateur @friday_action.
"""

from agents.src.middleware.models import ActionResult, CorrectionRule, StepDetail, TrustMetric
from agents.src.middleware.trust import (
    TrustManager,
    friday_action,
    get_trust_manager,
    init_trust_manager,
)

__all__ = [
    # Modèles
    "ActionResult",
    "CorrectionRule",
    "StepDetail",
    "TrustMetric",
    # Trust Manager
    "TrustManager",
    "friday_action",
    "get_trust_manager",
    "init_trust_manager",
]

__version__ = "1.0.0"
