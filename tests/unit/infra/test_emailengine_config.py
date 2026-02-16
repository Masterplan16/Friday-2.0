"""
Tests unitaires pour la configuration EmailEngine dans docker-compose.services.yml
Story 2.1 - Task 1 - EmailEngine setup
"""

import os
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def docker_compose_services():
    """Charge docker-compose.services.yml"""
    repo_root = Path(__file__).parent.parent.parent.parent
    compose_file = repo_root / "docker-compose.services.yml"

    assert compose_file.exists(), f"docker-compose.services.yml not found at {compose_file}"

    with open(compose_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestEmailEngineConfiguration:
    """Tests pour vérifier configuration EmailEngine"""

    def test_emailengine_service_exists(self, docker_compose_services):
        """AC1: EmailEngine service doit exister"""
        assert (
            "emailengine" in docker_compose_services["services"]
        ), "Service 'emailengine' not found in docker-compose.services.yml"

    def test_emailengine_has_correct_image(self, docker_compose_services):
        """AC1: Image EmailEngine doit être postalsys/emailengine:latest"""
        service = docker_compose_services["services"]["emailengine"]
        assert (
            "postalsys/emailengine" in service["image"]
        ), f"Expected postalsys/emailengine, got {service.get('image')}"

    def test_emailengine_has_volume_for_data_persistence(self, docker_compose_services):
        """AC1: Volume emailengine-data doit être monté sur /app/data pour persistance"""
        service = docker_compose_services["services"]["emailengine"]

        # Vérifier que volumes existe
        assert (
            "volumes" in service
        ), "EmailEngine service must have 'volumes' section for data persistence"

        # Chercher volume emailengine-data
        has_data_volume = any(
            "emailengine-data" in vol and "/app/data" in vol for vol in service["volumes"]
        )

        assert (
            has_data_volume
        ), "EmailEngine must have volume 'emailengine-data:/app/data' for persistence"

    def test_emailengine_has_database_url_env_var(self, docker_compose_services):
        """AC1: Variable DATABASE_URL doit être définie pour PostgreSQL"""
        service = docker_compose_services["services"]["emailengine"]

        assert "environment" in service, "EmailEngine service must have 'environment' section"

        # Chercher DATABASE_URL dans environment (format liste ou dict)
        env_vars = service["environment"]

        if isinstance(env_vars, list):
            has_database_url = any("DATABASE_URL" in var for var in env_vars)
        elif isinstance(env_vars, dict):
            has_database_url = "DATABASE_URL" in env_vars
        else:
            has_database_url = False

        assert (
            has_database_url
        ), "EmailEngine must have DATABASE_URL environment variable for PostgreSQL storage"

    def test_emailengine_has_redis_url_env_var(self, docker_compose_services):
        """AC1: Variable REDIS_URL ou EENGINE_REDIS doit être définie"""
        service = docker_compose_services["services"]["emailengine"]
        env_vars = service.get("environment", [])

        if isinstance(env_vars, list):
            has_redis = any("REDIS" in var for var in env_vars)
        elif isinstance(env_vars, dict):
            has_redis = any(k.upper().find("REDIS") != -1 for k in env_vars.keys())
        else:
            has_redis = False

        assert has_redis, "EmailEngine must have REDIS configuration (EENGINE_REDIS or REDIS_URL)"

    def test_emailengine_has_secret_env_var(self, docker_compose_services):
        """AC1: Variable EENGINE_SECRET doit être définie"""
        service = docker_compose_services["services"]["emailengine"]
        env_vars = service.get("environment", [])

        if isinstance(env_vars, list):
            has_secret = any("EENGINE_SECRET" in var for var in env_vars)
        elif isinstance(env_vars, dict):
            has_secret = "EENGINE_SECRET" in env_vars
        else:
            has_secret = False

        assert has_secret, "EmailEngine must have EENGINE_SECRET environment variable"

    def test_emailengine_has_healthcheck(self, docker_compose_services):
        """AC1: Healthcheck doit être configuré"""
        service = docker_compose_services["services"]["emailengine"]

        assert "healthcheck" in service, "EmailEngine must have healthcheck configured"

        healthcheck = service["healthcheck"]

        assert "test" in healthcheck, "Healthcheck must have 'test' command"

        # Vérifier que le test inclut /health endpoint
        test_cmd = (
            " ".join(healthcheck["test"])
            if isinstance(healthcheck["test"], list)
            else healthcheck["test"]
        )
        assert "/health" in test_cmd, "Healthcheck test must check /health endpoint"

    def test_emailengine_has_restart_policy(self, docker_compose_services):
        """AC1: Restart policy doit être unless-stopped"""
        service = docker_compose_services["services"]["emailengine"]

        assert "restart" in service, "EmailEngine must have restart policy"

        assert (
            service["restart"] == "unless-stopped"
        ), f"Expected restart='unless-stopped', got '{service['restart']}'"

    def test_emailengine_connected_to_friday_network(self, docker_compose_services):
        """AC1: EmailEngine doit être sur friday-network"""
        service = docker_compose_services["services"]["emailengine"]

        assert "networks" in service, "EmailEngine must be connected to a network"

        assert (
            "friday-network" in service["networks"]
        ), "EmailEngine must be connected to 'friday-network'"

    def test_emailengine_port_not_exposed_publicly(self, docker_compose_services):
        """AC1: Port 3000 doit être exposé uniquement sur localhost"""
        service = docker_compose_services["services"]["emailengine"]

        assert "ports" in service, "EmailEngine must have port mapping"

        # Vérifier que le port est lié à 127.0.0.1
        ports = service["ports"]
        has_localhost_binding = any(
            "127.0.0.1:3000" in str(port) or "localhost:3000" in str(port) for port in ports
        )

        assert (
            has_localhost_binding
        ), "EmailEngine port 3000 must be bound to localhost only (127.0.0.1:3000:3000)"
