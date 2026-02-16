"""
Tests unitaires pour les rétrogradations automatiques trust levels.

Story 1.8 - AC2, AC3 : Rétrogradation automatique auto→propose et propose→blocked
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
import yaml
from services.metrics.nightly import MetricsAggregator


@pytest.fixture
def mock_trust_config():
    """Fixture : configuration trust levels initiale."""
    return {
        "modules": {
            "email": {
                "classify": "auto",
                "draft_reply": "propose",
            },
            "finance": {
                "classify_transaction": "propose",
            },
        }
    }


@pytest.fixture
def metrics_aggregator():
    """Fixture : MetricsAggregator avec mocks."""
    aggregator = MetricsAggregator()

    # Mock db_pool avec support async context manager pour acquire()
    # Créer un mock connection
    mock_conn = AsyncMock()

    # Créer un context manager mock pour acquire()
    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    # Mock pool où acquire() retourne le context manager
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockAcquireContext()

    aggregator.db_pool = mock_pool
    aggregator.redis_client = AsyncMock()
    return aggregator


class TestApplyRetrogradations:
    """Tests pour la méthode apply_retrogradations() (Bug #1 fix)."""

    @pytest.mark.asyncio
    async def test_apply_retrogradations_modifies_yaml(
        self, metrics_aggregator, mock_trust_config, tmp_path
    ):
        """
        Test AC2: apply_retrogradations() modifie config/trust_levels.yaml.

        Scénario : email.classify rétrogradé auto → propose
        Vérifie que le fichier YAML est modifié correctement.
        """
        # Setup : Créer fichier trust_levels.yaml temporaire
        config_file = tmp_path / "trust_levels.yaml"
        config_file.write_text(yaml.dump(mock_trust_config, allow_unicode=True))

        retrogradations = [
            {
                "module": "email",
                "action": "classify",
                "accuracy": 0.867,
                "total_actions": 15,
                "old_level": "auto",
                "new_level": "propose",
            }
        ]

        # Patch le chemin du fichier config
        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_trust_config))):
            with patch("yaml.safe_load", return_value=mock_trust_config):
                with patch("yaml.dump") as mock_yaml_dump:
                    with patch.object(
                        metrics_aggregator,
                        "load_current_trust_levels",
                        return_value=mock_trust_config,
                    ):
                        # Action : Appliquer rétrogradations
                        await metrics_aggregator.apply_retrogradations(retrogradations)

        # Vérification : yaml.dump appelé avec config modifiée
        mock_yaml_dump.assert_called_once()
        updated_config = mock_yaml_dump.call_args[0][0]
        assert updated_config["modules"]["email"]["classify"] == "propose"

    @pytest.mark.asyncio
    async def test_apply_retrogradations_completes_successfully(
        self, metrics_aggregator, mock_trust_config, capsys
    ):
        """
        Test AC2: apply_retrogradations() s'exécute sans erreur et log correctement.

        Note: structlog n'utilise pas le système logging standard, donc on vérifie
        simplement que la méthode s'exécute sans lever d'exception.
        """
        retrogradations = [
            {
                "module": "email",
                "action": "classify",
                "accuracy": 0.85,
                "total_actions": 12,
                "old_level": "auto",
                "new_level": "propose",
            }
        ]

        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_trust_config))):
            with patch("yaml.safe_load", return_value=mock_trust_config):
                with patch("yaml.dump"):
                    # Action : doit s'exécuter sans erreur
                    await metrics_aggregator.apply_retrogradations(retrogradations)

                    # Vérification : capture stdout pour voir les logs structlog
                    captured = capsys.readouterr()
                    assert (
                        "Trust level retrogradé" in captured.out
                        or "Trust level retrograd" in captured.out
                    )

    @pytest.mark.asyncio
    async def test_apply_retrogradations_multiple(self, metrics_aggregator, mock_trust_config):
        """
        Test AC2: Appliquer plusieurs rétrogradations simultanément.
        """
        retrogradations = [
            {
                "module": "email",
                "action": "classify",
                "accuracy": 0.85,
                "total_actions": 12,
                "old_level": "auto",
                "new_level": "propose",
            },
            {
                "module": "finance",
                "action": "classify_transaction",
                "accuracy": 0.65,
                "total_actions": 8,
                "old_level": "propose",
                "new_level": "blocked",
            },
        ]

        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_trust_config))):
            with patch("yaml.safe_load", return_value=mock_trust_config):
                with patch("yaml.dump") as mock_yaml_dump:
                    # Action
                    await metrics_aggregator.apply_retrogradations(retrogradations)

                    # Vérification : yaml.dump appelé
                    mock_yaml_dump.assert_called_once()
                    updated_config = mock_yaml_dump.call_args[0][0]
                    assert updated_config["modules"]["email"]["classify"] == "propose"
                    assert updated_config["modules"]["finance"]["classify_transaction"] == "blocked"

    @pytest.mark.asyncio
    async def test_apply_retrogradations_creates_missing_module(
        self, metrics_aggregator, mock_trust_config
    ):
        """
        Test AC2: Si module n'existe pas dans config, le créer.
        """
        retrogradations = [
            {
                "module": "tuteur_these",  # Module non existant
                "action": "review",
                "accuracy": 0.82,
                "total_actions": 11,
                "old_level": "auto",
                "new_level": "propose",
            }
        ]

        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_trust_config))):
            with patch("yaml.safe_load", return_value=mock_trust_config):
                with patch("yaml.dump") as mock_yaml_dump:
                    # Action
                    await metrics_aggregator.apply_retrogradations(retrogradations)

                    # Vérification : module créé
                    updated_config = mock_yaml_dump.call_args[0][0]
                    assert "tuteur_these" in updated_config["modules"]
                    assert updated_config["modules"]["tuteur_these"]["review"] == "propose"


class TestDetectRetrogradationsAutoToPropose:
    """Tests pour règle auto → propose (AC2)."""

    @pytest.mark.asyncio
    async def test_detect_retrogradation_auto_to_propose_success(self, metrics_aggregator):
        """
        Test AC2: Règle auto→propose appliquée si accuracy <90% et sample >=10.
        """
        metrics = [
            {
                "module": "email",
                "action_type": "classify",
                "accuracy": 0.85,
                "total_actions": 12,
            }
        ]

        trust_levels = {"email": {"classify": "auto"}}

        with patch.object(
            metrics_aggregator, "load_current_trust_levels", return_value=trust_levels
        ):
            with patch.object(
                metrics_aggregator, "send_retrogradation_alerts", new_callable=AsyncMock
            ):
                # Action
                retrogradations = await metrics_aggregator.detect_retrogradations(metrics)

        # Vérification : Rétrogradation détectée
        assert len(retrogradations) == 1
        assert retrogradations[0]["old_level"] == "auto"
        assert retrogradations[0]["new_level"] == "propose"
        assert retrogradations[0]["accuracy"] == 0.85

    @pytest.mark.asyncio
    async def test_detect_retrogradation_below_sample_threshold(self, metrics_aggregator):
        """
        Test AC2: Pas de rétrogradation si sample <10 (seuil échantillon).
        """
        metrics = [
            {
                "module": "email",
                "action_type": "classify",
                "accuracy": 0.85,  # <90% mais sample trop petit
                "total_actions": 9,  # <10
            }
        ]

        trust_levels = {"email": {"classify": "auto"}}

        with patch.object(
            metrics_aggregator, "load_current_trust_levels", return_value=trust_levels
        ):
            # Action
            retrogradations = await metrics_aggregator.detect_retrogradations(metrics)

        # Vérification : Aucune rétrogradation (sample insuffisant)
        assert len(retrogradations) == 0

    @pytest.mark.asyncio
    async def test_detect_retrogradation_above_accuracy_threshold(self, metrics_aggregator):
        """
        Test AC2: Pas de rétrogradation si accuracy >=90%.
        """
        metrics = [
            {
                "module": "email",
                "action_type": "classify",
                "accuracy": 0.92,  # >=90%
                "total_actions": 15,
            }
        ]

        trust_levels = {"email": {"classify": "auto"}}

        with patch.object(
            metrics_aggregator, "load_current_trust_levels", return_value=trust_levels
        ):
            # Action
            retrogradations = await metrics_aggregator.detect_retrogradations(metrics)

        # Vérification : Aucune rétrogradation (accuracy OK)
        assert len(retrogradations) == 0


class TestDetectRetrogradationsProposeToBlocked:
    """Tests pour règle propose → blocked (AC3 - Bug #2 fix)."""

    @pytest.mark.asyncio
    async def test_detect_retrogradation_propose_to_blocked_success(self, metrics_aggregator):
        """
        Test AC3: Règle propose→blocked appliquée si accuracy <70% et sample >=5.
        """
        metrics = [
            {
                "module": "finance",
                "action_type": "classify_transaction",
                "accuracy": 0.65,
                "total_actions": 8,
            }
        ]

        trust_levels = {"finance": {"classify_transaction": "propose"}}

        with patch.object(
            metrics_aggregator, "load_current_trust_levels", return_value=trust_levels
        ):
            with patch.object(
                metrics_aggregator, "send_retrogradation_alerts", new_callable=AsyncMock
            ):
                # Action
                retrogradations = await metrics_aggregator.detect_retrogradations(metrics)

        # Vérification : Rétrogradation vers blocked détectée
        assert len(retrogradations) == 1
        assert retrogradations[0]["old_level"] == "propose"
        assert retrogradations[0]["new_level"] == "blocked"
        assert retrogradations[0]["accuracy"] == 0.65

    @pytest.mark.asyncio
    async def test_detect_retrogradation_propose_below_sample_threshold(self, metrics_aggregator):
        """
        Test AC3: Pas de rétrogradation propose→blocked si sample <5.
        """
        metrics = [
            {
                "module": "finance",
                "action_type": "classify_transaction",
                "accuracy": 0.60,  # <70% mais sample trop petit
                "total_actions": 4,  # <5
            }
        ]

        trust_levels = {"finance": {"classify_transaction": "propose"}}

        with patch.object(
            metrics_aggregator, "load_current_trust_levels", return_value=trust_levels
        ):
            # Action
            retrogradations = await metrics_aggregator.detect_retrogradations(metrics)

        # Vérification : Aucune rétrogradation (sample insuffisant)
        assert len(retrogradations) == 0

    @pytest.mark.asyncio
    async def test_detect_retrogradation_propose_above_accuracy_threshold(self, metrics_aggregator):
        """
        Test AC3: Pas de rétrogradation propose→blocked si accuracy >=70%.
        """
        metrics = [
            {
                "module": "finance",
                "action_type": "classify_transaction",
                "accuracy": 0.75,  # >=70%
                "total_actions": 8,
            }
        ]

        trust_levels = {"finance": {"classify_transaction": "propose"}}

        with patch.object(
            metrics_aggregator, "load_current_trust_levels", return_value=trust_levels
        ):
            # Action
            retrogradations = await metrics_aggregator.detect_retrogradations(metrics)

        # Vérification : Aucune rétrogradation (accuracy OK pour propose)
        assert len(retrogradations) == 0


class TestIntegrationRetrogradationFlow:
    """Tests d'intégration : flux complet détection → application."""

    @pytest.mark.asyncio
    async def test_detect_and_apply_retrogradations_flow(
        self, metrics_aggregator, mock_trust_config
    ):
        """
        Test intégration AC2: detect_retrogradations appelle apply_retrogradations automatiquement.

        Note: detect_retrogradations() appelle maintenant apply_retrogradations() en interne,
        donc on vérifie juste que le YAML est modifié après detect_retrogradations().
        """
        metrics = [
            {
                "module": "email",
                "action_type": "classify",
                "accuracy": 0.85,
                "total_actions": 12,
            }
        ]

        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_trust_config))):
            with patch("yaml.safe_load", return_value=mock_trust_config):
                with patch("yaml.dump") as mock_yaml_dump:
                    with patch.object(
                        metrics_aggregator,
                        "send_retrogradation_alerts",
                        new_callable=AsyncMock,
                    ):
                        # Action : Détection (qui applique automatiquement)
                        retrogradations = await metrics_aggregator.detect_retrogradations(metrics)

                        # Vérification : YAML modifié une fois par detect_retrogradations
                        mock_yaml_dump.assert_called_once()
                        updated_config = mock_yaml_dump.call_args[0][0]
                        assert updated_config["modules"]["email"]["classify"] == "propose"
