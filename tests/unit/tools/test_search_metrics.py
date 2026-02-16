#!/usr/bin/env python3
"""
Tests unitaires SearchMetrics monitoring (Story 3.3 - Task 8.5).

Tests:
- record_query + total tracking
- get_median_latency (impair, pair, vide)
- check_alert_threshold (above, below, empty)
- get_stats (all fields, empty)
- sliding window overflow

Date: 2026-02-16
Story: 3.3 - Task 8.5
"""

import pytest
from agents.src.tools.search_metrics import SearchMetrics

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def metrics():
    """SearchMetrics instance with small window for testing."""
    return SearchMetrics(window_size=5)


# ============================================================
# Tests: record_query
# ============================================================


def test_record_query_increments_total(metrics):
    """record_query incremente total_queries."""
    metrics.record_query(query_duration_ms=100.0, results_count=3, top_score=0.95)
    metrics.record_query(query_duration_ms=200.0, results_count=5, top_score=0.88)
    assert metrics.total_queries == 2


def test_record_query_adds_to_latencies(metrics):
    """record_query ajoute la latence a la fenetre glissante."""
    metrics.record_query(query_duration_ms=150.0, results_count=1, top_score=0.9)
    assert len(metrics.latencies) == 1
    assert metrics.latencies[0] == 150.0


# ============================================================
# Tests: get_median_latency
# ============================================================


def test_median_latency_empty(metrics):
    """Median retourne None si pas de donnees."""
    assert metrics.get_median_latency() is None


def test_median_latency_odd_count(metrics):
    """Median pour nombre impair d'elements."""
    for latency in [100.0, 200.0, 300.0]:
        metrics.record_query(query_duration_ms=latency, results_count=1, top_score=0.5)
    assert metrics.get_median_latency() == 200.0


def test_median_latency_even_count(metrics):
    """Median pour nombre pair d'elements (moyenne des 2 centrales)."""
    for latency in [100.0, 200.0, 300.0, 400.0]:
        metrics.record_query(query_duration_ms=latency, results_count=1, top_score=0.5)
    assert metrics.get_median_latency() == 250.0


def test_median_latency_single_value(metrics):
    """Median pour un seul element."""
    metrics.record_query(query_duration_ms=42.0, results_count=1, top_score=0.9)
    assert metrics.get_median_latency() == 42.0


# ============================================================
# Tests: check_alert_threshold
# ============================================================


def test_alert_threshold_empty_no_alert(metrics):
    """Pas d'alerte si pas de donnees."""
    assert metrics.check_alert_threshold(threshold_ms=2500.0) is False


def test_alert_threshold_below(metrics):
    """Pas d'alerte si median sous le seuil."""
    for latency in [100.0, 200.0, 300.0]:
        metrics.record_query(query_duration_ms=latency, results_count=1, top_score=0.5)
    assert metrics.check_alert_threshold(threshold_ms=2500.0) is False


def test_alert_threshold_above(metrics):
    """Alerte si median depasse le seuil."""
    for latency in [3000.0, 3500.0, 4000.0]:
        metrics.record_query(query_duration_ms=latency, results_count=1, top_score=0.5)
    assert metrics.check_alert_threshold(threshold_ms=2500.0) is True


# ============================================================
# Tests: get_stats
# ============================================================


def test_stats_empty(metrics):
    """Stats vides si pas de donnees."""
    stats = metrics.get_stats()
    assert stats["total_queries"] == 0
    assert stats["median_latency_ms"] is None
    assert stats["min_latency_ms"] is None
    assert stats["max_latency_ms"] is None


def test_stats_with_data(metrics):
    """Stats avec donnees."""
    latencies = [50.0, 100.0, 150.0, 200.0, 250.0]
    for lat in latencies:
        metrics.record_query(query_duration_ms=lat, results_count=1, top_score=0.5)

    stats = metrics.get_stats()
    assert stats["total_queries"] == 5
    assert stats["window_size"] == 5
    assert stats["min_latency_ms"] == 50.0
    assert stats["max_latency_ms"] == 250.0
    assert "median_latency_ms" in stats
    assert "p95_latency_ms" in stats
    assert "p99_latency_ms" in stats


# ============================================================
# Tests: sliding window
# ============================================================


def test_sliding_window_overflow(metrics):
    """Fenetre glissante evicte les anciennes valeurs (window_size=5)."""
    # Ajouter 7 valeurs dans une fenetre de 5
    for i in range(7):
        metrics.record_query(
            query_duration_ms=float(i * 100),
            results_count=1,
            top_score=0.5,
        )

    assert len(metrics.latencies) == 5
    assert metrics.total_queries == 7
    # Les 2 premieres (0, 100) ont ete evictees
    assert list(metrics.latencies) == [200.0, 300.0, 400.0, 500.0, 600.0]
