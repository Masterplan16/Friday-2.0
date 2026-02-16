#!/usr/bin/env python3
"""
Tests unitaires pour services/gateway/healthcheck.py (Story 1.5 review fix M3)

Tests couvrant :
- Presidio services présents dans SERVICE_CHECKS
- Configuration complète services critiques
- CRITICAL_SERVICES contient les bons services
"""

import pytest
from services.gateway.healthcheck import CRITICAL_SERVICES, SERVICE_CHECKS, HealthChecker


class TestServiceConfiguration:
    """Tests configuration healthcheck services"""

    def test_presidio_analyzer_in_service_checks(self):
        """Presidio Analyzer doit être dans SERVICE_CHECKS (Story 1.5)"""
        assert (
            "presidio_analyzer" in SERVICE_CHECKS
        ), "presidio_analyzer manquant dans SERVICE_CHECKS (requis Story 1.5)"

    def test_presidio_anonymizer_in_service_checks(self):
        """Presidio Anonymizer doit être dans SERVICE_CHECKS (Story 1.5)"""
        assert (
            "presidio_anonymizer" in SERVICE_CHECKS
        ), "presidio_anonymizer manquant dans SERVICE_CHECKS (requis Story 1.5)"

    def test_presidio_services_have_correct_config(self):
        """Vérifier que les services Presidio ont les bonnes URLs"""
        analyzer = SERVICE_CHECKS.get("presidio_analyzer")
        anonymizer = SERVICE_CHECKS.get("presidio_anonymizer")

        assert analyzer is not None
        assert anonymizer is not None

        # Vérifier type HTTP
        assert analyzer["type"] == "http"
        assert anonymizer["type"] == "http"

        # Vérifier URLs (format attendu)
        assert "presidio-analyzer" in analyzer["url"]
        assert "5001" in analyzer["url"]
        assert "/health" in analyzer["url"]

        assert "presidio-anonymizer" in anonymizer["url"]
        assert "5002" in anonymizer["url"]
        assert "/health" in anonymizer["url"]

    def test_critical_services_configuration(self):
        """Vérifier que les services critiques sont correctement configurés"""
        # Services critiques attendus
        expected_critical = {"postgresql", "redis", "emailengine"}

        assert CRITICAL_SERVICES == expected_critical, (
            f"CRITICAL_SERVICES mismatch. "
            f"Attendu: {expected_critical}, "
            f"Réel: {CRITICAL_SERVICES}"
        )

    def test_presidio_services_are_not_critical(self):
        """
        Presidio est NON-CRITIQUE (Story 1.5 architecture).

        Si Presidio DOWN → système degraded (pas unhealthy).
        LLM calls doivent être bloqués côté applicatif, mais le système reste up.
        """
        assert "presidio_analyzer" not in CRITICAL_SERVICES
        assert "presidio_anonymizer" not in CRITICAL_SERVICES

    def test_all_service_checks_have_required_fields(self):
        """Tous les services doivent avoir les champs requis"""
        for service_name, config in SERVICE_CHECKS.items():
            assert "type" in config, f"{service_name} manque 'type'"
            assert "url" in config, f"{service_name} manque 'url'"

            # Type doit être 'http' pour tous les services actuels
            assert (
                config["type"] == "http"
            ), f"{service_name} a type '{config['type']}' au lieu de 'http'"

    def test_service_urls_are_docker_internal(self):
        """
        Vérifier que les URLs sont internes Docker (pas localhost).

        Les services communiquent via docker network, pas via host.
        """
        for service_name, config in SERVICE_CHECKS.items():
            url = config["url"]

            # Ne devrait PAS utiliser localhost ou 127.0.0.1
            assert (
                "localhost" not in url
            ), f"{service_name} utilise localhost (devrait être nom service Docker)"
            assert (
                "127.0.0.1" not in url
            ), f"{service_name} utilise 127.0.0.1 (devrait être nom service Docker)"

            # Doit utiliser http:// (pas https pour réseau interne)
            assert url.startswith("http://"), f"{service_name} URL doit commencer par http://"


@pytest.mark.asyncio
class TestHealthCheckerInitialization:
    """Tests initialization HealthChecker"""

    async def test_healthchecker_can_be_initialized_without_dependencies(self):
        """HealthChecker peut être créé sans dépendances (test mode)"""
        checker = HealthChecker()

        assert checker.pg_pool is None
        assert checker.redis is None
        assert checker.cache_ttl == 5  # Default TTL

    async def test_healthchecker_custom_cache_ttl(self):
        """HealthChecker respecte le cache_ttl custom"""
        checker = HealthChecker(cache_ttl=10)

        assert checker.cache_ttl == 10


# Note: Tests d'intégration avec Presidio réel dans tests/integration/
# Ces tests unitaires vérifient uniquement la configuration statique
