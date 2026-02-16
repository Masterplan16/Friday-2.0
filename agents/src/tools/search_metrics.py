#!/usr/bin/env python3
"""
Friday 2.0 - Search Performance Metrics (Story 3.3 - Task 8)

Monitoring latence recherche sémantique.

Métriques:
- query_duration_ms : Latence totale query
- embedding_duration_ms : Latence génération embedding query
- pgvector_query_ms : Latence query pgvector
- results_count : Nombre résultats retournés
- top_score : Score meilleur résultat

Date: 2026-02-16
Story: 3.3 - Task 8
"""

from collections import deque
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ============================================================
# Metrics Tracker
# ============================================================


class SearchMetrics:
    """
    Tracker métriques performance recherche (Task 8.1, 8.2).

    Fenêtre glissante 100 dernières queries pour calcul médiane.
    """

    def __init__(self, window_size: int = 100):
        """
        Initialise SearchMetrics.

        Args:
            window_size: Taille fenêtre glissante (default 100)
        """
        self.window_size = window_size
        self.latencies = deque(maxlen=window_size)  # Fenêtre glissante
        self.total_queries = 0
        logger.info("SearchMetrics initialized", window_size=window_size)

    def record_query(
        self,
        query_duration_ms: float,
        results_count: int,
        top_score: float,
    ) -> None:
        """
        Enregistre métriques d'une query (Task 8.1).

        Args:
            query_duration_ms: Latence totale
            results_count: Nombre résultats
            top_score: Score meilleur résultat
        """
        self.latencies.append(query_duration_ms)
        self.total_queries += 1

        logger.debug(
            "Search query metrics recorded",
            query_duration_ms=round(query_duration_ms, 2),
            results_count=results_count,
            top_score=round(top_score, 3),
        )

    def get_median_latency(self) -> Optional[float]:
        """
        Calcule latence médiane (Task 8.2).

        Returns:
            Latence médiane (ms) ou None si pas de données
        """
        if not self.latencies:
            return None

        sorted_latencies = sorted(self.latencies)
        mid = len(sorted_latencies) // 2

        if len(sorted_latencies) % 2 == 0:
            # Pair : moyenne des 2 valeurs centrales
            return (sorted_latencies[mid - 1] + sorted_latencies[mid]) / 2
        else:
            # Impair : valeur centrale
            return sorted_latencies[mid]

    def check_alert_threshold(self, threshold_ms: float = 2500.0) -> bool:
        """
        Vérifie si latence médiane dépasse seuil (Task 8.3).

        Args:
            threshold_ms: Seuil alerte (default 2.5s)

        Returns:
            True si alerte nécessaire
        """
        median = self.get_median_latency()
        if median is None:
            return False

        return median > threshold_ms

    def get_stats(self) -> dict:
        """
        Retourne statistiques complètes (Task 8.4).

        Returns:
            Dict métriques
        """
        if not self.latencies:
            return {
                "total_queries": self.total_queries,
                "window_size": len(self.latencies),
                "median_latency_ms": None,
                "min_latency_ms": None,
                "max_latency_ms": None,
            }

        sorted_latencies = sorted(self.latencies)
        p50_idx = len(sorted_latencies) // 2
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)

        return {
            "total_queries": self.total_queries,
            "window_size": len(self.latencies),
            "median_latency_ms": round(sorted_latencies[p50_idx], 2),
            "p95_latency_ms": round(sorted_latencies[p95_idx], 2),
            "p99_latency_ms": round(sorted_latencies[p99_idx], 2),
            "min_latency_ms": round(min(sorted_latencies), 2),
            "max_latency_ms": round(max(sorted_latencies), 2),
        }


# ============================================================
# Global Instance
# ============================================================

# Instance globale pour tracking
search_metrics = SearchMetrics(window_size=100)
