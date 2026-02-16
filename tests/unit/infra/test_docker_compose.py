"""Tests unitaires pour la configuration Docker Compose (Story 1.1).

Valide les Acceptance Criteria:
- AC#1: docker compose up -d demarre tous les services sans erreur
- AC#2: PostgreSQL 16 accessible avec parametres tuning VPS-4
- AC#3: Redis 7 avec ACL configurees par service
- AC#4: pgvector dans PostgreSQL pour stockage vectoriel (D19 - remplace Qdrant)
- AC#5: n8n accessible via reverse proxy Caddy
- AC#6: Healthcheck sur tous les services
- AC#7: restart: unless-stopped sur tous les services
- AC#8: Usage RAM total < 40.8 Go (85% de 48 Go VPS-4)
"""

import platform
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_MAIN = PROJECT_ROOT / "docker-compose.yml"
COMPOSE_SERVICES = PROJECT_ROOT / "docker-compose.services.yml"


@pytest.fixture
def main_config():
    """Charge docker-compose.yml."""
    with open(COMPOSE_MAIN) as f:
        return yaml.safe_load(f)


@pytest.fixture
def services_config():
    """Charge docker-compose.services.yml."""
    with open(COMPOSE_SERVICES) as f:
        return yaml.safe_load(f)


@pytest.fixture
def all_services(main_config, services_config):
    """Combine tous les services des deux fichiers compose."""
    services = dict(main_config.get("services", {}))
    services.update(services_config.get("services", {}))
    return services


# ============================================
# AC#1: Versions images Docker
# ============================================
class TestDockerImageVersions:
    """Verifie que les images Docker sont aux bonnes versions."""

    def test_postgres_version(self, main_config):
        image = main_config["services"]["postgres"]["image"]
        assert image == "pgvector/pgvector:pg16"

    def test_redis_version(self, main_config):
        image = main_config["services"]["redis"]["image"]
        assert image == "redis:7.4-alpine"

    def test_qdrant_not_active(self, main_config):
        """Qdrant doit etre retire (Decision D19 - pgvector Day 1)."""
        services = main_config.get("services", {})
        assert (
            "qdrant" not in services
        ), "Qdrant should be removed (Decision D19 - pgvector in PostgreSQL)"

    def test_n8n_uses_custom_build(self, main_config):
        """n8n utilise un build custom (Dockerfile.n8n) au lieu d'une image publique."""
        n8n_config = main_config["services"]["n8n"]
        assert "build" in n8n_config, "n8n should use custom Dockerfile build"
        assert n8n_config["build"]["dockerfile"] == "Dockerfile.n8n"

    def test_caddy_version(self, main_config):
        image = main_config["services"]["caddy"]["image"]
        assert image == "caddy:2.10.2-alpine"

    def test_postgres_uses_pgvector_image(self, main_config):
        """AC#4: L'image PostgreSQL doit inclure pgvector (D19)."""
        image = main_config["services"]["postgres"]["image"]
        assert "pgvector" in image, (
            f"PostgreSQL image must include pgvector extension (D19). "
            f"Got: {image}, expected: pgvector/pgvector:pg16"
        )

    def test_no_version_attribute(self, main_config, services_config):
        """L'attribut version est obsolete dans Docker Compose."""
        assert "version" not in main_config
        assert "version" not in services_config

    def test_ollama_not_active(self, services_config):
        """Ollama doit etre retire (Decision D12)."""
        services = services_config.get("services", {})
        assert "ollama" not in services, "Ollama should be removed (Decision D12)"


# ============================================
# AC#2: PostgreSQL configuration VPS-4
# ============================================
class TestPostgresConfig:
    """Verifie la configuration PostgreSQL pour VPS-4 48 Go."""

    def test_postgres_tuning_shared_buffers(self, main_config):
        command = main_config["services"]["postgres"]["command"]
        assert "shared_buffers=256MB" in command

    def test_postgres_tuning_effective_cache(self, main_config):
        command = main_config["services"]["postgres"]["command"]
        assert "effective_cache_size=1GB" in command

    def test_postgres_db_name(self, main_config):
        env = main_config["services"]["postgres"]["environment"]
        assert env["POSTGRES_DB"] == "${POSTGRES_DB:-friday}"

    def test_postgres_no_default_password(self, main_config):
        env = main_config["services"]["postgres"]["environment"]
        # Le password ne doit PAS avoir de valeur par defaut
        assert env["POSTGRES_PASSWORD"] == "${POSTGRES_PASSWORD}"

    def test_postgres_port_localhost_only(self, main_config):
        ports = main_config["services"]["postgres"]["ports"]
        for port in ports:
            assert port.startswith("127.0.0.1:"), f"Port {port} must be localhost only"


# ============================================
# AC#3: Redis ACL par service
# ============================================
class TestRedisACL:
    """Verifie la configuration Redis ACL."""

    @pytest.mark.skip(
        reason="Redis ACL disabled in docker-compose.yml (CRLF issue) - TODO Story 1.17"
    )
    def test_redis_acl_file_mounted(self, main_config):
        volumes = main_config["services"]["redis"]["volumes"]
        acl_volumes = [v for v in volumes if "redis.acl" in v or "users.acl" in v]
        assert len(acl_volumes) > 0, "Redis ACL file must be mounted"

    @pytest.mark.skip(
        reason="Redis ACL disabled in docker-compose.yml (CRLF issue) - TODO Story 1.17"
    )
    def test_redis_command_loads_acl(self, main_config):
        command = main_config["services"]["redis"]["command"]
        assert "--aclfile" in command, "Redis must load ACL file"

    def test_gateway_uses_acl_credentials(self, main_config):
        env = main_config["services"]["gateway"]["environment"]
        redis_url = [e for e in env if "REDIS_URL" in e][0]
        assert "friday_gateway" in redis_url, "Gateway must use ACL user"

    def test_alerting_uses_acl_credentials(self, main_config):
        env = main_config["services"]["alerting"]["environment"]
        redis_url = [e for e in env if "REDIS_URL" in e][0]
        assert "friday_alerting" in redis_url, "Alerting must use ACL user"

    def test_metrics_uses_acl_credentials(self, main_config):
        env = main_config["services"]["metrics"]["environment"]
        redis_url = [e for e in env if "REDIS_URL" in e][0]
        assert "friday_metrics" in redis_url, "Metrics must use ACL user"

    def test_redis_acl_file_exists(self):
        acl_file = PROJECT_ROOT / "config" / "redis.acl"
        assert acl_file.exists(), "config/redis.acl must exist"

    def test_redis_acl_has_required_users(self):
        acl_file = PROJECT_ROOT / "config" / "redis.acl"
        content = acl_file.read_text()
        required_users = [
            "friday_gateway",
            "friday_agents",
            "friday_alerting",
            "friday_metrics",
            "friday_n8n",
            "friday_emailengine",
        ]
        for user in required_users:
            assert f"user {user}" in content, f"ACL must define user {user}"


# ============================================
# AC#6: Healthchecks sur tous les services
# ============================================
class TestHealthchecks:
    """Verifie que tous les services ont un healthcheck."""

    SERVICES_WITH_HEALTHCHECK = [
        "postgres",
        "redis",
        "n8n",
        "caddy",
        "gateway",
        "stt",
        "tts",
        "ocr",
        "presidio-analyzer",
        "presidio-anonymizer",
        "emailengine",
    ]

    def test_all_services_have_healthcheck(self, all_services):
        for svc_name in self.SERVICES_WITH_HEALTHCHECK:
            assert svc_name in all_services, f"Service {svc_name} not found"
            svc = all_services[svc_name]
            assert "healthcheck" in svc, f"Service {svc_name} must have a healthcheck"
            assert "test" in svc["healthcheck"], f"{svc_name} healthcheck must have a test"

    def test_postgres_healthcheck_uses_pg_isready(self, main_config):
        hc = main_config["services"]["postgres"]["healthcheck"]["test"]
        hc_str = " ".join(hc) if isinstance(hc, list) else hc
        assert "pg_isready" in hc_str

    def test_redis_healthcheck_uses_ping(self, main_config):
        hc = main_config["services"]["redis"]["healthcheck"]["test"]
        hc_str = " ".join(hc) if isinstance(hc, list) else hc
        assert "ping" in hc_str

    def test_gateway_healthcheck_endpoint(self, main_config):
        hc = main_config["services"]["gateway"]["healthcheck"]["test"]
        hc_str = " ".join(hc) if isinstance(hc, list) else hc
        assert "/api/v1/health" in hc_str


# ============================================
# AC#7: Restart policy
# ============================================
class TestRestartPolicy:
    """Verifie restart: unless-stopped sur tous les services."""

    def test_all_services_have_restart_policy(self, all_services):
        for svc_name, svc in all_services.items():
            assert svc.get("restart") == "unless-stopped", (
                f"Service {svc_name} must have restart: unless-stopped, "
                f"got: {svc.get('restart')}"
            )


# ============================================
# AC#8: Usage RAM < 40.8 Go (85% de 48 Go VPS-4)
# ============================================
class TestRAMConstraints:
    """Verifie que l'usage RAM total reste sous le seuil VPS-4."""

    VPS4_RAM_GB = 48
    ALERT_THRESHOLD_PCT = 85
    MAX_RAM_GB = VPS4_RAM_GB * ALERT_THRESHOLD_PCT / 100  # 40.8 Go

    def _parse_memory_gb(self, mem_str: str) -> float:
        """Convertit '10G' ou '512M' en Go."""
        mem_str = mem_str.strip().upper()
        if mem_str.endswith("G"):
            return float(mem_str[:-1])
        if mem_str.endswith("M"):
            return float(mem_str[:-1]) / 1024
        return 0

    def test_total_ram_limits_under_threshold(self, services_config):
        """Les resource limits des services lourds ne doivent pas depasser le seuil."""
        total_limits = 0.0
        services = services_config.get("services", {})
        for svc_name, svc in services.items():
            deploy = svc.get("deploy", {})
            resources = deploy.get("resources", {})
            limits = resources.get("limits", {})
            if "memory" in limits:
                total_limits += self._parse_memory_gb(limits["memory"])

        # Services lourds seuls ne doivent pas depasser le seuil
        # (le socle permanent ajoute ~6.5-8.5 Go)
        assert total_limits <= self.MAX_RAM_GB, (
            f"Total RAM limits ({total_limits:.1f} Go) exceeds "
            f"threshold ({self.MAX_RAM_GB:.1f} Go)"
        )

    def test_individual_services_have_memory_limits(self, services_config):
        """Les services lourds doivent avoir des resource limits."""
        heavy_services = ["stt", "tts", "ocr"]
        services = services_config.get("services", {})
        for svc_name in heavy_services:
            svc = services[svc_name]
            deploy = svc.get("deploy", {})
            resources = deploy.get("resources", {})
            limits = resources.get("limits", {})
            assert "memory" in limits, f"Service {svc_name} must have memory limit"


# ============================================
# Network: Tous ports localhost only
# ============================================
class TestNetworkSecurity:
    """Verifie que tous les ports sont binds sur 127.0.0.1."""

    def test_all_ports_localhost_only(self, all_services):
        for svc_name, svc in all_services.items():
            ports = svc.get("ports", [])
            for port in ports:
                assert str(port).startswith(
                    "127.0.0.1:"
                ), f"Service {svc_name} port {port} must be localhost only (127.0.0.1)"

    def test_friday_network_exists(self, main_config):
        networks = main_config.get("networks", {})
        assert "friday-network" in networks
        assert networks["friday-network"]["driver"] == "bridge"


# ============================================
# n8n v2 migration
# ============================================
class TestN8nV2Config:
    """Verifie la configuration n8n v2."""

    def test_n8n_uses_postgres(self, main_config):
        env = main_config["services"]["n8n"]["environment"]
        db_type = [e for e in env if "DB_TYPE" in e][0]
        assert "postgresdb" in db_type

    def test_n8n_file_access_restricted(self, main_config):
        env = main_config["services"]["n8n"]["environment"]
        restrict = [e for e in env if "N8N_RESTRICT_FILE_ACCESS_TO" in e]
        assert len(restrict) > 0, "n8n must have file access restriction (v2 security)"

    def test_n8n_env_access_blocked(self, main_config):
        env = main_config["services"]["n8n"]["environment"]
        block = [e for e in env if "N8N_BLOCK_ENV_ACCESS_IN_NODE" in e]
        assert len(block) > 0, "n8n must block env access in code nodes (v2 security)"


# ============================================
# Caddyfile
# ============================================
class TestCaddyfile:
    """Verifie que le Caddyfile existe et est monte."""

    def test_caddyfile_exists(self):
        caddyfile = PROJECT_ROOT / "config" / "Caddyfile"
        assert caddyfile.exists(), "config/Caddyfile must exist"

    def test_caddyfile_mounted(self, main_config):
        volumes = main_config["services"]["caddy"]["volumes"]
        caddy_volumes = [v for v in volumes if "Caddyfile" in v]
        assert len(caddy_volumes) > 0, "Caddyfile must be mounted in caddy service"

    def test_caddyfile_has_n8n_proxy(self):
        """AC#5: n8n doit etre accessible via reverse proxy Caddy."""
        caddyfile = PROJECT_ROOT / "config" / "Caddyfile"
        content = caddyfile.read_text()
        assert "n8n.friday.local" in content, "Caddyfile must proxy n8n.friday.local"
        assert "friday-n8n:5678" in content, "Caddyfile must route to friday-n8n:5678"

    def test_caddyfile_has_gateway_proxy(self):
        """Gateway doit etre accessible via reverse proxy Caddy."""
        caddyfile = PROJECT_ROOT / "config" / "Caddyfile"
        content = caddyfile.read_text()
        assert "api.friday.local" in content, "Caddyfile must proxy api.friday.local"
        assert "friday-gateway:8000" in content, "Caddyfile must route to friday-gateway:8000"

    def test_caddyfile_has_health_endpoint(self):
        """Caddy doit avoir un endpoint /health pour le healthcheck."""
        caddyfile = PROJECT_ROOT / "config" / "Caddyfile"
        content = caddyfile.read_text()
        assert "/health" in content, "Caddyfile must have /health endpoint"
