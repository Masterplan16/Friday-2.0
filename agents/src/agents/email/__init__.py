"""
Module email pour Friday 2.0 - Classification intelligente d'emails.

Agents et outils pour traiter et classifier les emails entrants.
"""

from agents.src.agents.email.urgency_detector import (
    check_urgency_keywords,
    detect_urgency,
    extract_deadline_patterns,
)
from agents.src.agents.email.vip_detector import (
    compute_email_hash,
    detect_vip_sender,
    update_vip_email_stats,
)

__all__ = [
    "compute_email_hash",
    "detect_vip_sender",
    "update_vip_email_stats",
    "detect_urgency",
    "check_urgency_keywords",
    "extract_deadline_patterns",
]
