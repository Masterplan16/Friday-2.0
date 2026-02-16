"""
Tests unitaires commande /arbo (Story 3.2 Task 6.7).

Tests : affichage tree, stats, add, remove, protection finance, owner-only
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_update():
    """Mock Telegram Update."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram context."""
    context = MagicMock()
    context.args = []
    context.bot_data = {}
    return context


# ==================== Tests Owner Only (Task 6.6) ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "99999"})
async def test_arbo_unauthorized_user(mock_update, mock_context):
    """Test /arbo par utilisateur non autorisé."""
    from bot.handlers.arborescence_commands import arbo_command

    await arbo_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_with("Non autorisé")


# ==================== Tests Affichage (Task 6.2) ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
@patch("bot.handlers.arborescence_commands.get_arborescence_config")
async def test_arbo_display_tree(mock_config, mock_update, mock_context):
    """Test /arbo affiche l'arborescence ASCII."""
    from bot.handlers.arborescence_commands import arbo_command

    # Mock config
    config = MagicMock()
    config.root_path = "C:/test/Archives"
    config.categories = {
        "pro": {
            "description": "Cabinet",
            "subcategories": {
                "patients": {"description": "Patients", "path": "pro/patients"},
            },
        },
        "finance": {
            "description": "Finance",
            "subcategories": {
                "selarl": {"description": "SELARL", "path": "finance/selarl"},
            },
        },
        "universite": {"description": "Université", "subcategories": {}},
        "recherche": {"description": "Recherche", "subcategories": {}},
        "perso": {"description": "Personnel", "subcategories": {}},
    }
    mock_config.return_value = config

    mock_context.args = []

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "Arborescence" in call_text
    assert "pro/" in call_text
    assert "finance/" in call_text


# ==================== Tests Stats (Task 6.5) ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_arbo_stats_no_db(mock_update, mock_context):
    """Test /arbo stats sans base de données."""
    from bot.handlers.arborescence_commands import arbo_command

    mock_context.args = ["stats"]
    mock_context.bot_data = {}

    await arbo_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_with("Base de données non disponible")


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_arbo_stats_with_data(mock_update, mock_context):
    """Test /arbo stats avec données."""
    from bot.handlers.arborescence_commands import arbo_command

    # Mock DB pool
    db_pool = AsyncMock()
    conn = AsyncMock()
    db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.fetch.return_value = [
        {"category": "pro", "subcategory": "-", "count": 10},
        {"category": "finance", "subcategory": "selarl", "count": 5},
    ]
    conn.fetchval.side_effect = [20, 15]  # total, classified

    mock_context.args = ["stats"]
    mock_context.bot_data = {"db_pool": db_pool}

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "Statistiques" in call_text
    assert "20" in call_text  # Total
    assert "15" in call_text  # Classified


# ==================== Tests Add (Task 6.3) ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
@patch("bot.handlers.arborescence_commands.get_arborescence_config")
async def test_arbo_add_valid_folder(mock_config, mock_update, mock_context):
    """Test /arbo add avec dossier valide."""
    from bot.handlers.arborescence_commands import arbo_command

    config = MagicMock()
    config.validate_path_name.return_value = True
    mock_config.return_value = config

    mock_context.args = ["add", "pro", "formations"]

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "ajouté" in call_text.lower()
    assert "pro/formations" in call_text


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_arbo_add_invalid_category(mock_update, mock_context):
    """Test /arbo add avec catégorie invalide."""
    from bot.handlers.arborescence_commands import arbo_command

    mock_context.args = ["add", "medical", "dossiers"]

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "invalide" in call_text.lower()


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_arbo_add_protected_finance_root(mock_update, mock_context):
    """Test AC6 : impossible d'ajouter un périmètre finance racine."""
    from bot.handlers.arborescence_commands import arbo_command

    mock_context.args = ["add", "finance", "selarl"]

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "protégés" in call_text.lower()


# ==================== Tests Remove (Task 6.4) ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_arbo_remove_protected_finance(mock_update, mock_context):
    """Test AC6 : impossible de supprimer un périmètre finance."""
    from bot.handlers.arborescence_commands import arbo_command

    mock_context.args = ["remove", "finance/selarl"]

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "protégés" in call_text.lower()


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_arbo_remove_root_category_blocked(mock_update, mock_context):
    """Test impossible de supprimer une catégorie racine."""
    from bot.handlers.arborescence_commands import arbo_command

    mock_context.args = ["remove", "pro"]

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "racine" in call_text.lower()


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_arbo_remove_allowed_subfolder(mock_update, mock_context):
    """Test suppression sous-dossier autorisée."""
    from bot.handlers.arborescence_commands import arbo_command

    mock_context.args = ["remove", "pro/formations"]

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "suppression" in call_text.lower()


# ==================== Tests ASCII Tree ====================


def test_build_ascii_tree():
    """Test construction arbre ASCII."""
    from bot.handlers.arborescence_commands import _build_ascii_tree

    categories = {
        "pro": {
            "description": "Cabinet",
            "subcategories": {
                "patients": {"description": "Patients"},
            },
        },
        "perso": {"description": "Personnel", "subcategories": {}},
    }

    tree = _build_ascii_tree(categories)

    assert "pro/" in tree
    assert "patients/" in tree
    assert "perso/" in tree
    assert "├──" in tree or "└──" in tree


# ==================== Tests Usage ====================


@pytest.mark.asyncio
@patch.dict("os.environ", {"OWNER_USER_ID": "12345"})
async def test_arbo_invalid_subcommand_shows_usage(mock_update, mock_context):
    """Test sous-commande invalide affiche l'usage."""
    from bot.handlers.arborescence_commands import arbo_command

    mock_context.args = ["invalid"]

    await arbo_command(mock_update, mock_context)

    call_text = mock_update.message.reply_text.call_args[0][0]
    assert "Usage" in call_text
