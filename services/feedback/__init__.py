"""
Services de feedback loop et pattern detection pour Friday 2.0.

Ce package contient les modules pour :
- Détection de patterns de correction (pattern_detector.py)
- Proposition de règles depuis clusters (rule_proposer.py - Story 1.9)
"""

from .pattern_detector import PatternCluster, PatternDetector

__all__ = ["PatternDetector", "PatternCluster"]
