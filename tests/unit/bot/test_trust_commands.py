"""
Tests unitaires pour les commandes /trust (promote, set).

Story 1.8 - AC4, AC5, AC6 : Tests handlers Telegram trust management.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import yaml

from telegram import Update, Message, User, Chat
from telegram.ext import ContextTypes

from bot.handlers.trust_commands import (
    trust_command_router,
    trust_promote_command,
    trust_set_command,
)


@pytest.fixture
def mock_update():
    """Fixture : Mock Telegram Update."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345
    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Fixture : Mock Telegram Context."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    return context


@pytest.fixture
def mock_trust_config():
    """Fixture : Configuration trust levels."""
    return {
        "modules": {
            "email": {
                "classify": "propose",
                "draft_reply": "propose",
            },
            "finance": {
                "classify_transaction": "blocked",
            },
        }
    }


class TestTrustCommandRouter:
    """Tests pour le router /trust (dispatching sous-commandes)."""

    @pytest.mark.asyncio
    async def test_router_without_args_shows_help(self, mock_update, mock_context):
        """
        Test : /trust sans arguments affiche l'aide.
        """
        mock_context.args = []

        await trust_command_router(mock_update, mock_context)

        # Vérifier que reply_text a été appelé avec l'aide
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Usage commande /trust" in call_args[0][0]
        assert "/trust promote" in call_args[0][0]
        assert "/trust set" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_router_promote_dispatches_correctly(self, mock_update, mock_context):
        """
        Test : /trust promote dispatche vers trust_promote_command.
        """
        mock_context.args = ["promote", "email", "classify"]

        with patch("bot.handlers.trust_commands.trust_promote_command", new_callable=AsyncMock) as mock_promote:
            await trust_command_router(mock_update, mock_context)

            # Vérifier que promote a été appelé avec args modifiés
            mock_promote.assert_called_once()
            assert mock_context.args == ["email", "classify"]

    @pytest.mark.asyncio
    async def test_router_set_dispatches_correctly(self, mock_update, mock_context):
        """
        Test : /trust set dispatche vers trust_set_command.
        """
        mock_context.args = ["set", "email", "classify", "auto"]

        with patch("bot.handlers.trust_commands.trust_set_command", new_callable=AsyncMock) as mock_set:
            await trust_command_router(mock_update, mock_context)

            # Vérifier que set a été appelé avec args modifiés
            mock_set.assert_called_once()
            assert mock_context.args == ["email", "classify", "auto"]

    @pytest.mark.asyncio
    async def test_router_unknown_subcommand_shows_error(self, mock_update, mock_context):
        """
        Test : /trust avec sous-commande invalide affiche erreur.
        """
        mock_context.args = ["invalid", "email", "classify"]

        await trust_command_router(mock_update, mock_context)

        # Vérifier message d'erreur
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Sous-commande inconnue" in call_args[0][0]
        assert "invalid" in call_args[0][0]


class TestTrustPromoteCommand:
    """Tests pour /trust promote (AC4, AC5)."""

    @pytest.mark.asyncio
    async def test_promote_without_args_shows_usage(self, mock_update, mock_context):
        """
        Test : /trust promote sans arguments affiche usage.
        """
        mock_context.args = []

        await trust_promote_command(mock_update, mock_context)

        # Vérifier message d'usage
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Usage" in call_args[0][0]
        assert "/trust promote <module> <action>" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_promote_propose_to_auto_success(self, mock_update, mock_context, mock_trust_config):
        """
        Test AC4 : Promotion propose→auto réussie (accuracy 97%, 24 actions, pas d'anti-oscillation).
        """
        mock_context.args = ["email", "classify"]

        # Mock helpers
        with patch("bot.handlers.trust_commands._get_current_trust_level", return_value="propose"):
            with patch("bot.handlers.trust_commands._get_last_trust_change", return_value=None):
                with patch("bot.handlers.trust_commands._get_metrics") as mock_metrics:
                    mock_metrics.return_value = [
                        {"accuracy": 0.97, "total_actions": 12},
                        {"accuracy": 0.96, "total_actions": 12},
                    ]  # Total 24 actions, avg 96.5%

                    with patch("bot.handlers.trust_commands._apply_trust_level_change", new_callable=AsyncMock):
                        await trust_promote_command(mock_update, mock_context)

                        # Vérifier succès
                        mock_update.message.reply_text.assert_called_once()
                        call_args = mock_update.message.reply_text.call_args
                        assert "Promotion réussie" in call_args[0][0]
                        assert "propose" in call_args[0][0]
                        assert "auto" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_promote_blocked_to_propose_success(self, mock_update, mock_context):
        """
        Test AC5 : Promotion blocked→propose réussie (accuracy 93%, 12 actions sur 4 semaines).
        """
        mock_context.args = ["finance", "classify_transaction"]

        with patch("bot.handlers.trust_commands._get_current_trust_level", return_value="blocked"):
            with patch("bot.handlers.trust_commands._get_last_trust_change", return_value=None):
                with patch("bot.handlers.trust_commands._get_metrics") as mock_metrics:
                    mock_metrics.return_value = [
                        {"accuracy": 0.93, "total_actions": 3},
                        {"accuracy": 0.92, "total_actions": 3},
                        {"accuracy": 0.94, "total_actions": 3},
                        {"accuracy": 0.91, "total_actions": 3},
                    ]  # Total 12 actions, avg 92.5%

                    with patch("bot.handlers.trust_commands._apply_trust_level_change", new_callable=AsyncMock):
                        await trust_promote_command(mock_update, mock_context)

                        # Vérifier succès
                        call_args = mock_update.message.reply_text.call_args
                        assert "Promotion réussie" in call_args[0][0]
                        assert "blocked" in call_args[0][0]
                        assert "propose" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_promote_refused_low_accuracy(self, mock_update, mock_context):
        """
        Test AC4 : Promotion propose→auto refusée (accuracy 92% < 95%).
        """
        mock_context.args = ["email", "classify"]

        with patch("bot.handlers.trust_commands._get_current_trust_level", return_value="propose"):
            with patch("bot.handlers.trust_commands._get_last_trust_change", return_value=None):
                with patch("bot.handlers.trust_commands._get_metrics") as mock_metrics:
                    mock_metrics.return_value = [
                        {"accuracy": 0.92, "total_actions": 12},
                        {"accuracy": 0.91, "total_actions": 12},
                    ]  # Total 24 actions, avg 91.5% < 95%

                    await trust_promote_command(mock_update, mock_context)

                    # Vérifier refus
                    call_args = mock_update.message.reply_text.call_args
                    assert "Promotion refusée" in call_args[0][0]
                    assert "Accuracy insuffisante" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_promote_refused_insufficient_sample(self, mock_update, mock_context):
        """
        Test AC4 : Promotion propose→auto refusée (échantillon 18 < 20).
        """
        mock_context.args = ["email", "classify"]

        with patch("bot.handlers.trust_commands._get_current_trust_level", return_value="propose"):
            with patch("bot.handlers.trust_commands._get_last_trust_change", return_value=None):
                with patch("bot.handlers.trust_commands._get_metrics") as mock_metrics:
                    mock_metrics.return_value = [
                        {"accuracy": 0.97, "total_actions": 9},
                        {"accuracy": 0.96, "total_actions": 9},
                    ]  # Total 18 actions < 20

                    await trust_promote_command(mock_update, mock_context)

                    # Vérifier refus
                    call_args = mock_update.message.reply_text.call_args
                    assert "Promotion refusée" in call_args[0][0]
                    assert "Échantillon insuffisant" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_promote_refused_anti_oscillation(self, mock_update, mock_context):
        """
        Test AC7 : Promotion refusée (anti-oscillation 5 jours < 14).
        """
        mock_context.args = ["email", "classify"]

        # Dernière transition il y a 5 jours
        last_change = datetime.utcnow() - timedelta(days=5)

        with patch("bot.handlers.trust_commands._get_current_trust_level", return_value="propose"):
            with patch("bot.handlers.trust_commands._get_last_trust_change", return_value=last_change):
                await trust_promote_command(mock_update, mock_context)

                # Vérifier refus anti-oscillation
                call_args = mock_update.message.reply_text.call_args
                assert "Promotion refusée" in call_args[0][0]
                assert "Anti-oscillation" in call_args[0][0]
                assert "5" in call_args[0][0]
                assert "14" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_promote_already_at_auto(self, mock_update, mock_context):
        """
        Test : Promotion impossible si déjà au niveau auto.
        """
        mock_context.args = ["email", "classify"]

        with patch("bot.handlers.trust_commands._get_current_trust_level", return_value="auto"):
            await trust_promote_command(mock_update, mock_context)

            # Vérifier message info
            call_args = mock_update.message.reply_text.call_args
            assert "déjà au niveau" in call_args[0][0]
            assert "auto" in call_args[0][0]


class TestTrustSetCommand:
    """Tests pour /trust set (AC6)."""

    @pytest.mark.asyncio
    async def test_set_without_args_shows_usage(self, mock_update, mock_context):
        """
        Test : /trust set sans arguments affiche usage.
        """
        mock_context.args = []

        await trust_set_command(mock_update, mock_context)

        # Vérifier message d'usage
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Usage" in call_args[0][0]
        assert "/trust set <module> <action> <level>" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_set_override_bypass_all_conditions(self, mock_update, mock_context):
        """
        Test AC6 : Override manuel bypass toutes conditions (anti-oscillation, accuracy).
        """
        mock_context.args = ["email", "classify", "blocked"]

        with patch("bot.handlers.trust_commands._get_current_trust_level", return_value="auto"):
            with patch("bot.handlers.trust_commands._apply_trust_level_change", new_callable=AsyncMock):
                await trust_set_command(mock_update, mock_context)

                # Vérifier succès override
                call_args = mock_update.message.reply_text.call_args
                assert "Override manuel appliqué" in call_args[0][0]
                assert "auto" in call_args[0][0]
                assert "blocked" in call_args[0][0]
                assert "Bypass" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_set_invalid_level_shows_error(self, mock_update, mock_context):
        """
        Test : /trust set avec niveau invalide affiche erreur.
        """
        mock_context.args = ["email", "classify", "invalid"]

        await trust_set_command(mock_update, mock_context)

        # Vérifier message d'erreur
        call_args = mock_update.message.reply_text.call_args
        assert "Niveau invalide" in call_args[0][0]
        assert "invalid" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_set_already_at_level(self, mock_update, mock_context):
        """
        Test : /trust set avec niveau identique affiche info.
        """
        mock_context.args = ["email", "classify", "propose"]

        with patch("bot.handlers.trust_commands._get_current_trust_level", return_value="propose"):
            await trust_set_command(mock_update, mock_context)

            # Vérifier message info
            call_args = mock_update.message.reply_text.call_args
            assert "déjà au niveau" in call_args[0][0]
            assert "propose" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_set_handles_errors_gracefully(self, mock_update, mock_context):
        """
        Test : /trust set gère les erreurs (module inexistant, etc.).
        """
        mock_context.args = ["nonexistent", "action", "auto"]

        with patch("bot.handlers.trust_commands._get_current_trust_level", side_effect=ValueError("Module not found")):
            await trust_set_command(mock_update, mock_context)

            # Vérifier message d'erreur
            call_args = mock_update.message.reply_text.call_args
            assert "Erreur" in call_args[0][0]


class TestTrustCommandHelpers:
    """Tests pour les helpers internes."""

    @pytest.mark.asyncio
    async def test_get_current_trust_level_success(self, mock_trust_config):
        """
        Test : _get_current_trust_level charge depuis YAML.
        """
        from bot.handlers.trust_commands import _get_current_trust_level

        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_trust_config))):
            with patch("yaml.safe_load", return_value=mock_trust_config):
                level = await _get_current_trust_level("email", "classify")
                assert level == "propose"

    @pytest.mark.asyncio
    async def test_get_current_trust_level_not_found(self, mock_trust_config):
        """
        Test : _get_current_trust_level raise ValueError si module inexistant.
        """
        from bot.handlers.trust_commands import _get_current_trust_level

        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_trust_config))):
            with patch("yaml.safe_load", return_value=mock_trust_config):
                with pytest.raises(ValueError, match="Module/action introuvable"):
                    await _get_current_trust_level("nonexistent", "action")

    @pytest.mark.asyncio
    async def test_apply_trust_level_change_updates_yaml_and_db(self, mock_trust_config):
        """
        Test : _apply_trust_level_change modifie YAML + BDD + Redis.
        """
        from bot.handlers.trust_commands import _apply_trust_level_change

        # Patcher _DB_URL pour éviter ValueError si DATABASE_URL non défini
        with patch("bot.handlers.trust_commands._DB_URL", "postgresql://test"):
            with patch("builtins.open", mock_open(read_data=yaml.dump(mock_trust_config))):
                with patch("yaml.safe_load", return_value=mock_trust_config):
                    with patch("yaml.dump") as mock_yaml_dump:
                        with patch("asyncpg.connect", new_callable=AsyncMock) as mock_conn:
                            mock_conn.return_value.__aenter__.return_value.execute = AsyncMock()
                            mock_conn.return_value.__aexit__ = AsyncMock()

                            # Mock Redis async context manager
                            mock_redis_client = AsyncMock()
                            mock_redis_client.xadd = AsyncMock()

                            class MockRedisContext:
                                async def __aenter__(self):
                                    return mock_redis_client

                                async def __aexit__(self, exc_type, exc_val, exc_tb):
                                    return None

                            with patch("redis.asyncio.from_url") as mock_redis_from_url:
                                mock_redis_from_url.return_value = MockRedisContext()

                                await _apply_trust_level_change("email", "classify", "auto", "promotion")

                                # Vérifier YAML modifié
                                mock_yaml_dump.assert_called_once()

                                # Vérifier Redis event envoyé
                                mock_redis_client.xadd.assert_called_once()
