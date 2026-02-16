"""
Tests E2E pipeline Watchdog (Story 3.5 - Task 8.1).

2 tests pipeline complet :
- Watchdog → Redis → Consumer (OCR pipeline simulation)
- CSV detection → Watchdog → Redis event avec workflow_target
"""
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from agents.src.agents.archiviste.watchdog_observer import FridayWatchdogObserver


@pytest.fixture
def e2e_config(tmp_path):
    """Config E2E avec dossiers scans et finance."""
    scans_dir = tmp_path / "scans"
    scans_dir.mkdir()
    finance_dir = tmp_path / "finance"
    finance_dir.mkdir()

    config_file = tmp_path / "watchdog.yaml"
    config_data = {
        "watchdog": {
            "enabled": True,
            "polling_interval_seconds": 1,
            "stabilization_delay_seconds": 0,
            "paths": [
                {
                    "path": str(scans_dir),
                    "recursive": False,
                    "extensions": [".pdf", ".png", ".jpg", ".jpeg"],
                    "source_label": "scanner_physique",
                    "workflow_target": "ocr_pipeline",
                },
                {
                    "path": str(finance_dir),
                    "recursive": False,
                    "extensions": [".csv", ".xlsx"],
                    "source_label": "csv_bancaire",
                    "workflow_target": "csv_processing",
                },
            ],
        }
    }
    config_file.write_text(yaml.dump(config_data), encoding="utf-8")

    return {
        "config_file": config_file,
        "scans_dir": scans_dir,
        "finance_dir": finance_dir,
    }


@pytest.mark.asyncio
async def test_watchdog_to_ocr_pipeline(e2e_config):
    """
    E2E: Fichier PDF detecte → Watchdog → Redis Streams document.received.

    Simule le pipeline complet :
    1. Scanner physique depose un PDF
    2. Watchdog detecte dans <2s
    3. Event publie dans Redis Streams document.received
    4. Event contient metadata correcte (source, workflow_target)

    Verifie AC1 + AC2 + AC6 (latence).
    """
    captured_events = []
    mock_redis = AsyncMock()

    async def capture_xadd(stream, data, **kwargs):
        captured_events.append({"stream": stream, "data": data})
        return f"{int(time.time())}-0"

    mock_redis.xadd = AsyncMock(side_effect=capture_xadd)
    mock_redis.close = AsyncMock()

    with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
        mock_aioredis.from_url = AsyncMock(return_value=mock_redis)

        observer = FridayWatchdogObserver(
            config_path=str(e2e_config["config_file"]),
            use_polling=True,
        )

        await observer.start()
        assert observer.is_running

        # Simuler depot scanner physique
        start_time = time.time()
        scan_file = e2e_config["scans_dir"] / "2026-02-16_Facture_EDF_150EUR.pdf"
        scan_file.write_bytes(b"%PDF-1.4 " + b"x" * 1024)

        # Attendre detection avec timeout
        timeout = 5.0
        while time.time() - start_time < timeout:
            if captured_events:
                break
            await asyncio.sleep(0.3)

        detection_time = time.time() - start_time

        await observer.stop()

    # Verifier event publie
    assert len(captured_events) >= 1, (
        "Watchdog should detect PDF and publish to Redis within 5s"
    )

    event = captured_events[0]
    assert event["stream"] == "document.received"

    data = event["data"]
    assert data["filename"] == "2026-02-16_Facture_EDF_150EUR.pdf"
    assert data["source"] == "scanner_physique"
    assert data["workflow_target"] == "ocr_pipeline"
    assert data["extension"] == ".pdf"
    assert int(data["size_bytes"]) > 0
    assert "detected_at" in data

    # AC6: Latence detection → Redis <5s
    assert detection_time < 5.0, (
        f"Detection latency {detection_time:.1f}s exceeds 5s limit"
    )


@pytest.mark.asyncio
async def test_watchdog_csv_import_workflow(e2e_config):
    """
    E2E: CSV bancaire detecte → event avec workflow_target=csv_processing.

    Simule le pipeline :
    1. CSV bancaire copie dans dossier finance
    2. Watchdog detecte
    3. Event publie avec source=csv_bancaire, workflow_target=csv_processing
    4. Consumer (n8n) recevrait cet event pour routing

    Verifie AC3.
    """
    captured_events = []
    mock_redis = AsyncMock()

    async def capture_xadd(stream, data, **kwargs):
        captured_events.append({"stream": stream, "data": data})
        return f"{int(time.time())}-0"

    mock_redis.xadd = AsyncMock(side_effect=capture_xadd)
    mock_redis.close = AsyncMock()

    with patch("agents.src.agents.archiviste.watchdog_observer.aioredis") as mock_aioredis:
        mock_aioredis.from_url = AsyncMock(return_value=mock_redis)

        observer = FridayWatchdogObserver(
            config_path=str(e2e_config["config_file"]),
            use_polling=True,
        )

        await observer.start()

        # Simuler import CSV bancaire
        start_time = time.time()
        csv_file = e2e_config["finance_dir"] / "releve_ca_2026-02.csv"
        csv_content = (
            "date;libelle;montant\n"
            "2026-02-01;Virement salaire;+3500.00\n"
            "2026-02-02;Loyer;-1200.00\n"
        )
        csv_file.write_text(csv_content, encoding="utf-8")

        # Attendre detection avec timeout
        timeout = 5.0
        while time.time() - start_time < timeout:
            csv_found = [
                e for e in captured_events
                if e["data"].get("source") == "csv_bancaire"
            ]
            if csv_found:
                break
            await asyncio.sleep(0.3)

        await observer.stop()

    # Verifier event CSV
    csv_events = [
        e for e in captured_events
        if e["data"].get("source") == "csv_bancaire"
    ]
    assert len(csv_events) >= 1, (
        "Watchdog should detect CSV and publish to Redis within 5s"
    )

    event = csv_events[0]
    data = event["data"]
    assert data["filename"] == "releve_ca_2026-02.csv"
    assert data["source"] == "csv_bancaire"
    assert data["workflow_target"] == "csv_processing"
    assert data["extension"] == ".csv"
