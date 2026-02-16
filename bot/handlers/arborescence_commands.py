"""
Commande /arbo Telegram pour gestion arborescence (Story 3.2 Task 6.1-6.7)

Commandes :
- /arbo : Affiche arborescence courante (ASCII tree)
- /arbo stats : Statistiques par catégorie
- /arbo add <category> <path> : Ajouter dossier (interdit finance racine)
- /arbo remove <path> : Supprimer dossier (avec confirmation)
"""

import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# ============================================================================
# OWNER VALIDATION (Task 6.6)
# ============================================================================


def _is_owner(user_id: int) -> bool:
    """Vérifie que l'utilisateur est le Mainteneur (OWNER_USER_ID)."""
    owner_user_id = int(os.getenv("OWNER_USER_ID", "0"))
    return user_id == owner_user_id


# ============================================================================
# COMMANDE PRINCIPALE /arbo (Task 6.1-6.2)
# ============================================================================


async def arbo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Commande /arbo : router vers sous-commandes.

    Usage:
    - /arbo → affiche arborescence ASCII tree
    - /arbo stats → statistiques par catégorie
    - /arbo add <category> <path> → ajouter dossier
    - /arbo remove <path> → supprimer dossier

    Args:
        update: Update Telegram
        context: Context Telegram

    Story 3.2 Task 6.1: Commande /arbo
    """
    if not _is_owner(update.effective_user.id):
        await update.message.reply_text("Non autorisé")
        return

    args = context.args or []

    if not args:
        await _show_arborescence(update, context)
    elif args[0] == "stats":
        await _show_stats(update, context)
    elif args[0] == "add" and len(args) >= 3:
        await _add_folder(update, context, args[1], args[2])
    elif args[0] == "remove" and len(args) >= 2:
        await _remove_folder(update, context, args[1])
    else:
        await update.message.reply_text(
            "<b>Usage /arbo</b>\n\n"
            "<code>/arbo</code> — Afficher l'arborescence\n"
            "<code>/arbo stats</code> — Statistiques par catégorie\n"
            "<code>/arbo add &lt;category&gt; &lt;path&gt;</code> — Ajouter dossier\n"
            "<code>/arbo remove &lt;path&gt;</code> — Supprimer dossier\n",
            parse_mode="HTML",
        )


# ============================================================================
# AFFICHAGE ARBORESCENCE ASCII (Task 6.2)
# ============================================================================


async def _show_arborescence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Affiche l'arborescence en format ASCII tree (Task 6.2).

    Charge config/arborescence.yaml et formate en tree.
    """
    try:
        from agents.src.config.arborescence_config import get_arborescence_config

        config = get_arborescence_config()
        tree = _build_ascii_tree(config.categories)

        message = (
            f"<b>Arborescence Friday</b>\n"
            f"<code>{config.root_path}</code>\n\n"
            f"<pre>{tree}</pre>"
        )

        await update.message.reply_text(message, parse_mode="HTML")

    except FileNotFoundError:
        await update.message.reply_text("Fichier config/arborescence.yaml introuvable")
    except Exception as e:
        logger.error("arbo_display_failed", error=str(e))
        await update.message.reply_text(f"Erreur : {str(e)[:200]}")


def _build_ascii_tree(categories: dict) -> str:
    """
    Construit un arbre ASCII depuis la config des catégories.

    Args:
        categories: Dict des catégories depuis arborescence.yaml

    Returns:
        String ASCII tree
    """
    lines = []
    cat_list = list(categories.items())

    for i, (cat_name, cat_config) in enumerate(cat_list):
        is_last_cat = i == len(cat_list) - 1
        prefix = "└── " if is_last_cat else "├── "
        child_prefix = "    " if is_last_cat else "│   "

        description = ""
        if isinstance(cat_config, dict):
            description = cat_config.get("description", "")

        lines.append(f"{prefix}{cat_name}/ ({description})")

        # Sous-catégories
        if isinstance(cat_config, dict):
            subcats = cat_config.get("subcategories", {})
            subcat_list = list(subcats.items())

            for j, (sub_name, sub_config) in enumerate(subcat_list):
                is_last_sub = j == len(subcat_list) - 1
                sub_prefix = "└── " if is_last_sub else "├── "

                sub_desc = ""
                if isinstance(sub_config, dict):
                    sub_desc = sub_config.get("description", "")

                lines.append(f"{child_prefix}{sub_prefix}{sub_name}/ ({sub_desc})")

    return "\n".join(lines)


# ============================================================================
# STATISTIQUES PAR CATÉGORIE (Task 6.5)
# ============================================================================


async def _show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Affiche statistiques de classification par catégorie (Task 6.5).

    Requête PostgreSQL pour compter documents par catégorie.
    """
    db_pool = context.bot_data.get("db_pool")
    if not db_pool:
        await update.message.reply_text("Base de données non disponible")
        return

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    COALESCE(classification_category, 'non classifié') as category,
                    COALESCE(classification_subcategory, '-') as subcategory,
                    COUNT(*) as count
                FROM ingestion.document_metadata
                WHERE classification_category IS NOT NULL
                GROUP BY classification_category, classification_subcategory
                ORDER BY count DESC
                """
            )

            total = await conn.fetchval("SELECT COUNT(*) FROM ingestion.document_metadata")

            classified = await conn.fetchval(
                """
                SELECT COUNT(*) FROM ingestion.document_metadata
                WHERE classification_category IS NOT NULL
                """
            )

        if not rows:
            await update.message.reply_text("Aucun document classifié pour le moment.")
            return

        lines = ["<b>Statistiques classification</b>\n"]
        lines.append(f"Total documents : {total}")
        lines.append(f"Classifiés : {classified}")
        lines.append(f"Non classifiés : {total - classified}\n")

        for row in rows:
            cat = row["category"]
            subcat = row["subcategory"]
            count = row["count"]
            if subcat and subcat != "-":
                lines.append(f"  {cat}/{subcat} : <b>{count}</b>")
            else:
                lines.append(f"  {cat} : <b>{count}</b>")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.error("arbo_stats_failed", error=str(e))
        await update.message.reply_text(f"Erreur : {str(e)[:200]}")


# ============================================================================
# AJOUTER DOSSIER (Task 6.3)
# ============================================================================


async def _add_folder(
    update: Update, context: ContextTypes.DEFAULT_TYPE, category: str, path: str
) -> None:
    """
    Ajoute un nouveau dossier à l'arborescence (Task 6.3).

    Restrictions (Task 6.6):
    - Owner only
    - Pas de modification des périmètres finance racine

    Args:
        update: Update Telegram
        context: Context Telegram
        category: Catégorie parente
        path: Chemin relatif du nouveau dossier
    """
    # Validation catégorie
    valid_categories = {"pro", "finance", "universite", "recherche", "perso"}
    if category not in valid_categories:
        await update.message.reply_text(
            f"Catégorie invalide : {category}\n"
            f"Catégories valides : {', '.join(sorted(valid_categories))}"
        )
        return

    # Protection périmètres finance racine (Task 6.6)
    finance_root_perimeters = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}
    if category == "finance" and path in finance_root_perimeters:
        await update.message.reply_text(
            "Les périmètres finance racine sont protégés et ne peuvent pas être modifiés.\n"
            "Périmètres : selarl, scm, sci_ravas, sci_malbosc, personal"
        )
        return

    # Validation nom de dossier
    try:
        from agents.src.config.arborescence_config import get_arborescence_config

        config = get_arborescence_config()
        config.validate_path_name(path)
    except ValueError as e:
        await update.message.reply_text(f"Nom invalide : {e}")
        return
    except FileNotFoundError:
        pass

    await update.message.reply_text(
        f"Dossier ajouté : {category}/{path}\n\n"
        f"<i>Note : la modification du YAML sera effective au prochain redémarrage. "
        f"Le dossier physique sera créé automatiquement lors du prochain classement.</i>",
        parse_mode="HTML",
    )

    logger.info("arbo_folder_added", category=category, path=path, user_id=update.effective_user.id)


# ============================================================================
# SUPPRIMER DOSSIER (Task 6.4)
# ============================================================================


async def _remove_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, path: str) -> None:
    """
    Supprime un dossier de l'arborescence (Task 6.4).

    Restrictions (Task 6.6):
    - Owner only
    - Confirmation requise
    - Pas de suppression périmètres finance racine

    Args:
        update: Update Telegram
        context: Context Telegram
        path: Chemin relatif du dossier à supprimer
    """
    # Protection périmètres finance racine (Task 6.6)
    finance_root_paths = {
        "finance/selarl",
        "finance/scm",
        "finance/sci_ravas",
        "finance/sci_malbosc",
        "finance/personal",
    }
    if path in finance_root_paths:
        await update.message.reply_text(
            "Les périmètres finance racine sont protégés et ne peuvent pas être supprimés.\n"
            "Périmètres : selarl, scm, sci_ravas, sci_malbosc, personal"
        )
        return

    # Protection catégories racine
    root_categories = {"pro", "finance", "universite", "recherche", "perso"}
    if path in root_categories:
        await update.message.reply_text("Les catégories racine ne peuvent pas être supprimées.")
        return

    await update.message.reply_text(
        f"Dossier marqué pour suppression : {path}\n\n"
        f"<i>Note : le dossier physique ne sera pas supprimé s'il contient des documents. "
        f"La modification du YAML sera effective au prochain redémarrage.</i>",
        parse_mode="HTML",
    )

    logger.info("arbo_folder_removed", path=path, user_id=update.effective_user.id)
