"""Tests unitaires pour la securite reseau et configuration (Story 1.4).

Valide les Acceptance Criteria:
- AC#1: SSH uniquement via Tailscale (verifie configuration UFW dans scripts)
- AC#6: Aucun port expose sur IP publique (verifie docker-compose ports)
- AC#7: Redis ACL operationnelles (6 users, moindre privilege)
- AC#8: Workflow secrets age/SOPS fonctionnel
- AC#9: Tests de validation securite couvrant tous les ACs
- AC#10: Script d'installation Tailscale automatise

NOTE: Les tests existants dans test_docker_compose.py (TestNetworkSecurity,
TestRedisACL, TestCaddyfile) ne sont PAS dupliques ici. Ce fichier couvre
des aspects complementaires: permissions ACL detaillees, absence +@all,
secrets workflow, scripts Tailscale, domaines Caddyfile.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ============================================
# 6.2: Ports docker-compose 127.0.0.1
# (complementaire a TestNetworkSecurity existant)
# ============================================
class TestDockerComposePortsSecurity:
    """Verifie la securite des ports dans les deux fichiers compose."""

    def test_main_compose_no_public_ports(self):
        """Tous les ports dans docker-compose.yml sont sur 127.0.0.1."""
        import yaml

        compose_file = PROJECT_ROOT / "docker-compose.yml"
        assert compose_file.exists(), "docker-compose.yml must exist"
        data = yaml.safe_load(compose_file.read_text())

        services = data.get("services", {})
        for svc_name, svc_config in services.items():
            ports = svc_config.get("ports", [])
            for port_entry in ports:
                port_str = str(port_entry).strip('"')
                if ":" in port_str:
                    assert port_str.startswith("127.0.0.1:"), (
                        f"Service {svc_name}: port {port_str} must be " f"bound to 127.0.0.1"
                    )


# ============================================
# 6.3 & 6.4: Redis ACL detailed permissions
# ============================================
class TestRedisACLPermissions:
    """Verifie les permissions detaillees de chaque user Redis ACL."""

    @pytest.fixture
    def acl_content(self):
        acl_file = PROJECT_ROOT / "config" / "redis.acl"
        assert acl_file.exists(), "config/redis.acl must exist"
        return acl_file.read_text()

    @pytest.fixture
    def acl_users(self, acl_content):
        """Parse ACL file into user definitions."""
        users = {}
        for line in acl_content.splitlines():
            line = line.strip()
            if line.startswith("user ") and not line.startswith("#"):
                parts = line.split()
                username = parts[1]
                users[username] = line
        return users

    def test_redis_acl_has_6_service_users(self, acl_users):
        """8 users de service + admin + default = 10 total (D25: EmailEngine → friday_email + friday_bot + document_processor)."""
        expected_users = {
            "default",
            "admin",
            "friday_gateway",
            "friday_agents",
            "friday_alerting",
            "friday_metrics",
            "friday_n8n",
            "friday_bot",
            "friday_email",
            "document_processor",
        }
        assert (
            set(acl_users.keys()) == expected_users
        ), f"Expected users {expected_users}, got {set(acl_users.keys())}"

    def test_default_user_is_off(self, acl_users):
        """user default doit etre OFF (aucune connexion anonyme)."""
        default_line = acl_users["default"]
        assert " off " in default_line or default_line.endswith(
            " off"
        ), "Default user must be disabled (off)"

    def test_no_service_user_has_all_commands(self, acl_users):
        """Aucun user de service ne doit avoir +@all (sauf admin)."""
        for username, line in acl_users.items():
            if username in ("admin", "default"):
                continue
            assert "+@all" not in line, (
                f"User {username} has +@all which violates least privilege. "
                f"Only admin should have +@all"
            )

    def test_admin_has_all_commands(self, acl_users):
        """Admin doit avoir +@all (dev/debug)."""
        admin_line = acl_users["admin"]
        assert "+@all" in admin_line, "Admin must have +@all"

    def test_gateway_has_cache_and_streams(self, acl_users):
        """Gateway: cache read/write + pub/sub + streams."""
        line = acl_users["friday_gateway"]
        for cmd in ["+get", "+set", "+publish", "+subscribe", "+xadd", "+xreadgroup"]:
            assert cmd in line, f"Gateway missing command: {cmd}"

    def test_agents_restricted_to_streams_and_presidio(self, acl_users):
        """Agents: streams + presidio mapping only, no unrestricted keys."""
        line = acl_users["friday_agents"]
        assert "~stream:*" in line, "Agents must have access to stream:* keys"
        assert "~presidio:mapping:*" in line, "Agents must have access to presidio:mapping:* keys"
        # Should NOT have bare ~* (all keys) - only prefixed key patterns allowed
        bare_wildcard = re.search(r"(?<!\S)~\*(?!\S)", line)
        assert bare_wildcard is None, "Agents should not have unrestricted key access (~*)"

    def test_alerting_restricted_to_streams(self, acl_users):
        """Alerting: streams only, pas de cache ni presidio."""
        line = acl_users["friday_alerting"]
        assert "~stream:*" in line, "Alerting must have access to stream:* keys"
        assert "~presidio:" not in line, "Alerting should not access presidio keys"

    def test_metrics_restricted_to_metrics_keys(self, acl_users):
        """Metrics: uniquement metrics:* keys."""
        line = acl_users["friday_metrics"]
        assert "~metrics:*" in line, "Metrics must have access to metrics:* keys"
        # No streams
        assert "+xadd" not in line, "Metrics should not have stream write access"
        assert "+xreadgroup" not in line, "Metrics should not have stream read access"

    def test_n8n_restricted_to_cache_bull_n8n(self, acl_users):
        """n8n: cache + bull + n8n keys, pas de streams."""
        line = acl_users["friday_n8n"]
        assert "~cache:*" in line, "n8n must have access to cache:* keys"
        assert "~bull:*" in line, "n8n must have access to bull:* keys"
        assert "~n8n:*" in line, "n8n must have access to n8n:* keys"
        assert "+xadd" not in line, "n8n should not have stream write access"

    def test_no_service_user_has_destructive_commands(self, acl_users):
        """Aucun service user ne doit avoir flushall/flushdb (sauf admin)."""
        destructive_cmds = ["+flushall", "+flushdb"]
        for username, line in acl_users.items():
            if username in ("admin", "default"):
                continue
            line_lower = line.lower()
            # Check for explicit destructive commands
            for cmd in destructive_cmds:
                assert cmd not in line_lower, (
                    f"User {username} has {cmd} which is destructive. "
                    f"Use -flushall -flushdb after +@write if needed"
                )
            # If +@write is used, ensure destructive cmds are negated
            if "+@write" in line_lower:
                assert (
                    "-flushall" in line_lower
                ), f"User {username} has +@write without -flushall negation"
                assert (
                    "-flushdb" in line_lower
                ), f"User {username} has +@write without -flushdb negation"

    def test_all_service_users_have_passwords(self, acl_users):
        """Tous les users de service doivent avoir un password (>)."""
        for username, line in acl_users.items():
            if username == "default":
                continue
            assert ">" in line, f"User {username} must have a password defined"


# ============================================
# 6.5: .env.example ne contient aucun secret reel
# ============================================
class TestEnvExampleSecurity:
    """Verifie que .env.example ne contient aucun secret reel."""

    @pytest.fixture
    def env_content(self):
        env_file = PROJECT_ROOT / ".env.example"
        assert env_file.exists(), ".env.example must exist"
        return env_file.read_text(encoding="utf-8")

    def test_no_real_api_keys(self, env_content):
        """Pas de vraies cles API (patterns connus)."""
        # Anthropic API key pattern: sk-ant-*
        assert "sk-ant-" not in env_content, ".env.example contains real Anthropic key"
        # Telegram bot token pattern: digits:alphanumeric
        telegram_token_pattern = re.compile(r"\d{10}:[A-Za-z0-9_-]{35}")
        assert not telegram_token_pattern.search(
            env_content
        ), ".env.example contains real Telegram token"

    def test_passwords_are_placeholders(self, env_content):
        """Les passwords doivent etre des placeholders (changeme/your_*_here)."""
        for line in env_content.splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if "PASSWORD" in key.upper() and key not in (
                "REDIS_ADMIN_PASSWORD",
                "REDIS_GATEWAY_PASSWORD",
                "REDIS_AGENTS_PASSWORD",
                "REDIS_ALERTING_PASSWORD",
                "REDIS_METRICS_PASSWORD",
                "REDIS_N8N_PASSWORD",
                "REDIS_EMAILENGINE_PASSWORD",
            ):
                assert (
                    "changeme" in value.lower() or "your_" in value.lower()
                ), f"{key} must be a placeholder (changeme/your_*_here), got: {value}"

    def test_no_real_tokens(self, env_content):
        """Pas de vrais tokens."""
        for line in env_content.splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if "TOKEN" in key.upper() and value:
                # Should be placeholder pattern
                assert (
                    "changeme" in value.lower()
                    or "your_" in value.lower()
                    or "tskey-auth-xxxxx" in value
                ), f"{key} must be a placeholder, got: {value}"


# ============================================
# 6.6: .sops.yaml existe et a creation_rules
# ============================================
class TestSopsConfig:
    """Verifie la configuration SOPS."""

    def test_sops_yaml_exists(self):
        sops_file = PROJECT_ROOT / ".sops.yaml"
        assert sops_file.exists(), ".sops.yaml must exist in project root"

    def test_sops_has_creation_rules(self):
        sops_file = PROJECT_ROOT / ".sops.yaml"
        content = sops_file.read_text()
        assert "creation_rules" in content, ".sops.yaml must have creation_rules"

    def test_sops_has_env_enc_rule(self):
        sops_file = PROJECT_ROOT / ".sops.yaml"
        content = sops_file.read_text()
        assert (
            ".env.enc" in content or r"\.env\.enc" in content
        ), ".sops.yaml must have a rule for .env.enc files"

    def test_sops_uses_age(self):
        sops_file = PROJECT_ROOT / ".sops.yaml"
        content = sops_file.read_text()
        assert "age:" in content, ".sops.yaml must use age encryption"


# ============================================
# 6.7: .gitignore exclut fichiers sensibles
# ============================================
class TestGitignoreSecurity:
    """Verifie que .gitignore exclut les fichiers sensibles."""

    @pytest.fixture
    def gitignore_content(self):
        gitignore = PROJECT_ROOT / ".gitignore"
        assert gitignore.exists(), ".gitignore must exist"
        return gitignore.read_text()

    def test_env_excluded(self, gitignore_content):
        """Les fichiers .env doivent etre exclus."""
        assert ".env" in gitignore_content, ".gitignore must exclude .env files"

    def test_key_files_excluded(self, gitignore_content):
        """Les fichiers *.key doivent etre exclus."""
        assert "*.key" in gitignore_content, ".gitignore must exclude *.key files"

    def test_credentials_excluded(self, gitignore_content):
        """credentials.json doit etre exclu."""
        assert "credentials.json" in gitignore_content, ".gitignore must exclude credentials.json"

    def test_service_account_excluded(self, gitignore_content):
        """service-account.json doit etre exclu."""
        assert (
            "service-account.json" in gitignore_content
        ), ".gitignore must exclude service-account.json"


# ============================================
# 6.8: Caddyfile domaines .friday.local
# ============================================
class TestCaddyfileSecurity:
    """Verifie que Caddyfile utilise des domaines internes."""

    @pytest.fixture
    def caddyfile_content(self):
        caddyfile = PROJECT_ROOT / "config" / "Caddyfile"
        assert caddyfile.exists(), "config/Caddyfile must exist"
        return caddyfile.read_text()

    def test_all_domains_are_local(self, caddyfile_content):
        """Tous les domaines doivent etre en .friday.local (pas de domaine public)."""
        # Match domain blocks (e.g., "example.com {") excluding .local/.internal
        domain_block = re.compile(r"^(\S+\.\S+)\s*\{", re.MULTILINE)
        for match in domain_block.finditer(caddyfile_content):
            domain = match.group(1)
            if domain.startswith(":"):
                continue  # Port-only block (e.g., ":80 {")
            assert domain.endswith(".local") or domain.endswith(".internal"), (
                f"Caddyfile domain {domain} must be .local or .internal, " f"not a public domain"
            )

    def test_has_friday_local_domains(self, caddyfile_content):
        """Au moins un domaine .friday.local doit etre configure."""
        assert ".friday.local" in caddyfile_content, "Caddyfile must contain .friday.local domains"

    def test_no_tls_auto(self, caddyfile_content):
        """Pas de TLS automatique (pas de certificats publics pour domaines locaux)."""
        assert (
            "tls {" not in caddyfile_content
        ), "Caddyfile should not have explicit TLS config for local domains"


# ============================================
# 6.9: Scripts Tailscale existent
# ============================================
class TestTailscaleScripts:
    """Verifie que les scripts Tailscale existent et ont le bon contenu."""

    def test_setup_tailscale_exists(self):
        script = PROJECT_ROOT / "scripts" / "setup-tailscale.sh"
        assert script.exists(), "scripts/setup-tailscale.sh must exist"

    def test_setup_tailscale_has_shebang(self):
        script = PROJECT_ROOT / "scripts" / "setup-tailscale.sh"
        content = script.read_text()
        assert content.startswith(
            "#!/usr/bin/env bash"
        ), "setup-tailscale.sh must have #!/usr/bin/env bash shebang"

    def test_setup_tailscale_has_hostname(self):
        """Script doit configurer hostname friday-vps."""
        script = PROJECT_ROOT / "scripts" / "setup-tailscale.sh"
        content = script.read_text()
        assert "friday-vps" in content, "setup-tailscale.sh must configure hostname friday-vps"

    def test_setup_tailscale_enables_service(self):
        """Script doit activer tailscaled au demarrage."""
        script = PROJECT_ROOT / "scripts" / "setup-tailscale.sh"
        content = script.read_text()
        assert (
            "systemctl enable tailscaled" in content
        ), "setup-tailscale.sh must enable tailscaled at boot"

    def test_setup_tailscale_verifies_status(self):
        """Script doit verifier tailscale status apres install."""
        script = PROJECT_ROOT / "scripts" / "setup-tailscale.sh"
        content = script.read_text()
        assert "tailscale status" in content, "setup-tailscale.sh must verify tailscale status"

    def test_harden_ssh_exists(self):
        script = PROJECT_ROOT / "scripts" / "harden-ssh.sh"
        assert script.exists(), "scripts/harden-ssh.sh must exist"

    def test_harden_ssh_has_shebang(self):
        script = PROJECT_ROOT / "scripts" / "harden-ssh.sh"
        content = script.read_text()
        assert content.startswith(
            "#!/usr/bin/env bash"
        ), "harden-ssh.sh must have #!/usr/bin/env bash shebang"

    def test_harden_ssh_configures_ufw(self):
        """Script doit configurer UFW pour bloquer SSH public."""
        script = PROJECT_ROOT / "scripts" / "harden-ssh.sh"
        content = script.read_text()
        assert "ufw deny 22/tcp" in content, "harden-ssh.sh must deny public SSH via UFW"

    def test_harden_ssh_configures_listenaddress(self):
        """Script doit configurer ListenAddress pour Tailscale."""
        script = PROJECT_ROOT / "scripts" / "harden-ssh.sh"
        content = script.read_text()
        assert "ListenAddress" in content, "harden-ssh.sh must configure SSH ListenAddress"

    def test_harden_ssh_allows_tailscale_interface(self):
        """Script doit autoriser interface tailscale0 dans UFW."""
        script = PROJECT_ROOT / "scripts" / "harden-ssh.sh"
        content = script.read_text()
        assert "tailscale0" in content, "harden-ssh.sh must allow tailscale0 interface in UFW"

    def test_sops_test_script_exists(self):
        script = PROJECT_ROOT / "scripts" / "test-sops-workflow.sh"
        assert script.exists(), "scripts/test-sops-workflow.sh must exist"

    def test_sops_test_script_has_shebang(self):
        script = PROJECT_ROOT / "scripts" / "test-sops-workflow.sh"
        content = script.read_text()
        assert content.startswith(
            "#!/usr/bin/env bash"
        ), "test-sops-workflow.sh must have #!/usr/bin/env bash shebang"
