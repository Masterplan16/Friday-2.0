"""
Test Watchtower configuration in docker-compose.services.yml
Story 1.14 - AC1, AC3, AC4
"""

import pytest
import yaml
from pathlib import Path


@pytest.fixture
def docker_compose_services():
    """Load docker-compose.services.yml"""
    compose_path = Path(__file__).parent.parent.parent.parent / "docker-compose.services.yml"
    with open(compose_path) as f:
        return yaml.safe_load(f)


def test_watchtower_service_exists_in_docker_compose(docker_compose_services):
    """Test service watchtower défini dans docker-compose.services.yml (AC1)"""
    assert "watchtower" in docker_compose_services["services"], \
        "Service 'watchtower' not found in docker-compose.services.yml"

    watchtower = docker_compose_services["services"]["watchtower"]

    # Verify basic configuration
    assert watchtower["image"] == "containrrr/watchtower:latest", \
        "Watchtower image should be containrrr/watchtower:latest"
    assert watchtower["restart"] == "unless-stopped", \
        "Watchtower restart policy should be unless-stopped (Story 1.13 AC1)"
    assert watchtower["container_name"] == "friday-watchtower", \
        "Container name should be friday-watchtower"


def test_watchtower_monitor_only_enabled(docker_compose_services):
    """Test WATCHTOWER_MONITOR_ONLY=true configuré (AC4 CRITICAL)"""
    watchtower = docker_compose_services["services"]["watchtower"]
    env = watchtower.get("environment", [])

    # Environment can be list or dict
    if isinstance(env, list):
        env_vars = {e.split("=", 1)[0]: e.split("=", 1)[1] for e in env if "=" in e}
    else:
        env_vars = env

    assert "WATCHTOWER_MONITOR_ONLY" in env_vars, \
        "WATCHTOWER_MONITOR_ONLY must be set"
    assert env_vars["WATCHTOWER_MONITOR_ONLY"] == "true", \
        "WATCHTOWER_MONITOR_ONLY must be 'true' (AC4 CRITICAL - no auto-updates)"


def test_watchtower_docker_socket_readonly(docker_compose_services):
    """Test volume docker.sock monté en read-only (Security best practice)"""
    watchtower = docker_compose_services["services"]["watchtower"]
    volumes = watchtower.get("volumes", [])

    # Find docker.sock volume
    docker_sock_volume = [vol for vol in volumes if "docker.sock" in vol]
    assert len(docker_sock_volume) > 0, \
        "Docker socket volume /var/run/docker.sock must be mounted"

    # Verify read-only flag
    assert any(":ro" in vol for vol in docker_sock_volume), \
        "Docker socket must be mounted read-only (:ro) for security"


def test_watchtower_schedule_configured(docker_compose_services):
    """Test schedule cron 03h00 défini (AC3)"""
    watchtower = docker_compose_services["services"]["watchtower"]
    env = watchtower.get("environment", [])

    # Environment can be list or dict
    if isinstance(env, list):
        env_vars = {e.split("=", 1)[0]: e.split("=", 1)[1] for e in env if "=" in e}
    else:
        env_vars = env

    # Either SCHEDULE (cron) or POLL_INTERVAL (seconds) must be set
    has_schedule = "WATCHTOWER_SCHEDULE" in env_vars
    has_poll_interval = "WATCHTOWER_POLL_INTERVAL" in env_vars

    assert has_schedule or has_poll_interval, \
        "Either WATCHTOWER_SCHEDULE or WATCHTOWER_POLL_INTERVAL must be configured"

    # If schedule is set, verify it's 03:00 daily
    if has_schedule:
        schedule = env_vars["WATCHTOWER_SCHEDULE"]
        # Cron format: "0 0 3 * * *" = 03:00 daily
        assert "3" in schedule, \
            "Schedule should include 03:00 (hour 3)"

    # If poll interval is set, verify it's 24h (86400 seconds)
    if has_poll_interval:
        interval = env_vars["WATCHTOWER_POLL_INTERVAL"]
        assert interval == "86400", \
            "Poll interval should be 86400 seconds (24h) for daily check"


def test_watchtower_telegram_notification_url(docker_compose_services):
    """Test URL notification Telegram configurée (AC2)"""
    watchtower = docker_compose_services["services"]["watchtower"]
    env = watchtower.get("environment", [])

    # Environment can be list or dict
    if isinstance(env, list):
        # Use split("=", 1) to handle values containing "=" (e.g., base64 tokens)
        env_vars = {e.split("=", 1)[0]: e.split("=", 1)[1] if "=" in e else None for e in env}
    else:
        env_vars = env

    # Verify notification backend is configured
    assert "WATCHTOWER_NOTIFICATIONS" in env_vars, \
        "WATCHTOWER_NOTIFICATIONS must be set to enable notifications"
    assert env_vars["WATCHTOWER_NOTIFICATIONS"] == "shoutrrr", \
        "WATCHTOWER_NOTIFICATIONS should be 'shoutrrr' for Telegram support"

    # Verify notification URL is configured
    assert "WATCHTOWER_NOTIFICATION_URL" in env_vars, \
        "WATCHTOWER_NOTIFICATION_URL must be set for Telegram notifications"

    # Note: Full URL validation requires env vars expansion
    # Just verify the key exists for now


def test_watchtower_self_exclusion_label(docker_compose_services):
    """Test Watchtower has label to exclude itself from monitoring (AC1)"""
    watchtower = docker_compose_services["services"]["watchtower"]
    labels = watchtower.get("labels", [])

    # Labels can be list or dict
    if isinstance(labels, list):
        label_dict = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in labels if "=" in l}
    else:
        label_dict = labels

    assert "com.centurylinklabs.watchtower.enable" in label_dict, \
        "Watchtower should have com.centurylinklabs.watchtower.enable label"
    assert label_dict["com.centurylinklabs.watchtower.enable"] == "false", \
        "Watchtower should exclude itself from monitoring (enable=false)"
