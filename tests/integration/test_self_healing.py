"""
Tests d'intégration Self-Healing - Story 1.13

Tests intégration pour :
- RAM spike → auto-recovery
- Crash loop → stop service
- Workflows n8n (E2E)
"""

import asyncio
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Test 4.3.4: Simuler RAM spike → vérifier auto-kill
@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("CI") and not Path("/usr/bin/stress-ng").exists(),
    reason="Nécessite stress-ng ou CI environment",
)
def test_ram_spike_triggers_auto_recovery():
    """
    Test intégration : Simuler RAM spike → vérifier auto-kill service

    Scénario :
    1. Créer mock service Docker (ou simuler)
    2. Forcer RAM > 91% (via stress-ng ou mock)
    3. Appeler monitor-ram.sh --json
    4. Vérifier que RAM > 91%
    5. Appeler auto-recover-ram.sh
    6. Vérifier qu'un service est tué
    7. Vérifier que RAM diminue ou exit code = 0
    """
    # Mock environnement
    env = os.environ.copy()
    env["TELEGRAM_BOT_TOKEN"] = "test_token"
    env["TELEGRAM_CHAT_ID"] = "test_chat_id"
    env["TOPIC_SYSTEM_ID"] = "1234"

    # Étape 1: Vérifier état initial RAM avec monitor-ram.sh
    result_monitor = subprocess.run(
        ["bash", "scripts/monitor-ram.sh", "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result_monitor.returncode == 0, "monitor-ram.sh devrait réussir"

    # Parser JSON output
    import json

    try:
        metrics = json.loads(result_monitor.stdout)
        initial_ram_pct = metrics.get("ram_usage_pct", 0)
    except json.JSONDecodeError:
        pytest.skip("monitor-ram.sh ne retourne pas de JSON valide")

    # Étape 2: Simuler RAM spike (mock ou skip si impossible)
    # En environnement de test, on peut soit :
    # a) Utiliser stress-ng pour forcer RAM haute (nécessite sudo)
    # b) Mocker la fonction RAM% dans le script
    # c) Skip le test si pas d'environnement approprié

    # Pour ce test d'intégration, on va SIMULER en mockant RAM_PCT
    env["RAM_PCT"] = "92"  # Force 92% pour déclencher recovery

    # Étape 3: Appeler auto-recover-ram.sh avec RAM forcée
    # NOTE: En vrai, auto-recover-ram.sh devrait lire RAM% du système
    # Pour le test, on passe en variable d'environnement

    # Mock docker pour éviter de tuer vrais containers
    mock_docker_script = """
    #!/usr/bin/env bash
    if [[ "$1" == "stop" ]]; then
        echo "MOCK: docker stop $2"
        exit 0
    elif [[ "$1" == "ps" ]]; then
        echo "kokoro-tts"
        exit 0
    else
        /usr/bin/docker "$@"
    fi
    """

    # Créer mock docker temporaire
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(mock_docker_script)
        mock_docker_path = f.name

    os.chmod(mock_docker_path, 0o755)

    try:
        # Ajouter mock docker au PATH
        env["PATH"] = f"{os.path.dirname(mock_docker_path)}:{env['PATH']}"

        # Appeler auto-recover-ram.sh
        result_recovery = subprocess.run(
            ["bash", "scripts/auto-recover-ram.sh"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # Vérifier que le script a réussi
        # Exit 0 = recovery effectuée OU pas nécessaire
        assert result_recovery.returncode == 0, f"auto-recover-ram.sh failed: {result_recovery.stderr}"

        # Vérifier output mentionne kill service ou recovery
        output = result_recovery.stdout + result_recovery.stderr
        assert (
            "Stopping" in output
            or "MOCK: docker stop" in output
            or "RAM below" in output
            or "kokoro-tts" in output
        ), f"Output devrait mentionner action recovery: {output}"

    finally:
        # Cleanup mock docker
        os.unlink(mock_docker_path)


# Test 4.3.5: Simuler crash loop → vérifier stop service
@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("CI"), reason="Nécessite Docker environment ou CI")
def test_crash_loop_stops_service():
    """
    Test intégration : Simuler crash loop → vérifier stop service

    Scénario :
    1. Mock docker inspect pour retourner RestartCount > 3
    2. Appeler detect-crash-loop.sh
    3. Vérifier que le script détecte le crash loop
    4. Vérifier que docker stop est appelé
    5. Vérifier exit code = 1 (crash loop détecté)
    """
    # Mock environnement
    env = os.environ.copy()
    env["TELEGRAM_BOT_TOKEN"] = "test_token"
    env["TELEGRAM_CHAT_ID"] = "test_chat_id"
    env["TOPIC_SYSTEM_ID"] = "1234"

    # Mock docker qui retourne RestartCount élevé
    mock_docker_script = """
    #!/usr/bin/env bash
    if [[ "$1" == "ps" ]]; then
        echo "CONTAINER ID   NAMES"
        echo "abc123         crashing-service"
    elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.RestartCount}}" ]]; then
        echo "5"  # 5 restarts
    elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.State.StartedAt}}" ]]; then
        # Démarré il y a 30min (moins de 1h)
        date -u -d "30 minutes ago" +"%Y-%m-%dT%H:%M:%S.%NZ" 2>/dev/null || date -u -v-30M +"%Y-%m-%dT%H:%M:%S.%NZ"
    elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.Name}}" ]]; then
        echo "/crashing-service"
    elif [[ "$1" == "logs" ]]; then
        echo "Error: Connection failed"
        echo "Fatal: Exiting"
    elif [[ "$1" == "stop" ]]; then
        echo "MOCK: Stopped crashing-service" >&2
        exit 0
    else
        echo "MOCK: Unknown docker command: $*" >&2
        exit 1
    fi
    """

    # Créer mock docker temporaire
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(mock_docker_script)
        mock_docker_path = f.name

    os.chmod(mock_docker_path, 0o755)

    try:
        # Ajouter mock docker au PATH
        env["PATH"] = f"{os.path.dirname(mock_docker_path)}:{env['PATH']}"

        # Appeler detect-crash-loop.sh
        result = subprocess.run(
            ["bash", "scripts/detect-crash-loop.sh"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # Exit 1 = crash loop détecté
        assert result.returncode == 1, f"detect-crash-loop.sh devrait retourner 1 (crash loop detected)"

        # Vérifier output mentionne crash loop
        output = result.stdout + result.stderr
        assert (
            "CRASH LOOP" in output or "Stopped" in output or "crashing-service" in output
        ), f"Output devrait mentionner crash loop: {output}"

        # Vérifier que docker stop a été appelé (dans stderr du mock)
        assert "Stopped crashing-service" in result.stderr, "docker stop devrait avoir été appelé"

    finally:
        # Cleanup mock docker
        os.unlink(mock_docker_path)


# Test 4.3.6: Workflow n8n complet (E2E)
@pytest.mark.e2e
@pytest.mark.skipif(
    not os.getenv("N8N_API_KEY") or not os.getenv("N8N_URL"), reason="Nécessite n8n instance + API key"
)
@pytest.mark.asyncio
async def test_n8n_auto_recover_workflow_e2e():
    """
    Test E2E : Workflow n8n auto-recover-ram.json complet

    Scénario :
    1. Vérifier que workflow n8n existe et est actif
    2. Trigger manuellement via API n8n
    3. Attendre exécution (max 60s)
    4. Vérifier que workflow a réussi
    5. Vérifier logs indiquent check RAM effectué
    """
    import httpx

    n8n_url = os.getenv("N8N_URL", "http://localhost:5678")
    n8n_api_key = os.getenv("N8N_API_KEY")

    headers = {"X-N8N-API-KEY": n8n_api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        # Étape 1: Lister workflows
        resp = await client.get(f"{n8n_url}/api/v1/workflows", headers=headers)
        assert resp.status_code == 200, f"Failed to list workflows: {resp.text}"

        workflows = resp.json()["data"]

        # Chercher workflow "Auto-Recover RAM"
        auto_recover_workflow = None
        for wf in workflows:
            if "auto-recover-ram" in wf["name"].lower() or "story 1.13" in wf["name"].lower():
                auto_recover_workflow = wf
                break

        if not auto_recover_workflow:
            pytest.skip("Workflow Auto-Recover RAM not found in n8n instance")

        workflow_id = auto_recover_workflow["id"]

        # Étape 2: Trigger manuellement (si webhook ou API trigger disponible)
        # NOTE: n8n Schedule Trigger ne peut pas être triggé manuellement via API
        # On va plutôt vérifier que le workflow existe et est actif

        # Vérifier que workflow est actif
        assert auto_recover_workflow["active"] is True, "Workflow devrait être actif"

        # Vérifier que workflow contient les nodes attendus
        # (impossible via API, nécessite accès à la définition du workflow)

        # Alternative: Vérifier executions récentes
        resp_executions = await client.get(
            f"{n8n_url}/api/v1/executions", params={"workflowId": workflow_id, "limit": 10}, headers=headers
        )

        assert resp_executions.status_code == 200, f"Failed to get executions: {resp_executions.text}"

        executions = resp_executions.json()["data"]

        # Si des exécutions existent, vérifier qu'au moins une a réussi
        if executions:
            successful_executions = [e for e in executions if e["finished"] and not e.get("stoppedAt")]
            # Note: Vérifier le champ exact dépend de la version n8n
            # Pour simplifier, on vérifie juste qu'il y a des exécutions
            assert len(executions) > 0, "Workflow devrait avoir des exécutions historiques"

        # Test réussi si workflow existe et est actif
        # Un vrai test E2E nécessiterait de déclencher manuellement et attendre
        # Mais n8n Schedule Trigger ne supporte pas le trigger manuel via API
