#!/usr/bin/env python3
"""
Friday 2.0 - Telegram /search Handler (Story 6.2 Task 5 - Stub minimal)

IMPORTANT: Implémentation minimale pour Story 6.2.
          Implémentation complète sera faite quand bot est opérationnel (Story 1.9+).

Date: 2026-02-11
Story: 6.2 - Task 5 (stub)
"""

import logging

logger = logging.getLogger(__name__)


async def handle_search_command(update, context):
    """
    Handler /search <query>

    Example:
        /search facture plombier
        /search SGLT2 diabète

    TODO (Story 6.2 complet):
        - Appeler endpoint Gateway /api/v1/search/semantic
        - Formater résultats avec inline buttons [Ouvrir] [Détails]
        - Progressive disclosure (top 3 résultats, puis "Voir plus")
    """
    query = " ".join(context.args) if context.args else ""

    if not query:
        await update.message.reply_text("Usage: /search <requête>\n\nExemple: /search facture plombier")
        return

    # Stub minimal (retourne message TODO)
    logger.info("Search command received: %s", query)
    await update.message.reply_text(
        f"🔍 Recherche pour '{query}'...\n\n"
        f"⚠️ Recherche sémantique pas encore implémentée (Story 6.2 en cours).\n\n"
        f"Prochaines étapes:\n"
        f"- Appel API Gateway /api/v1/search/semantic\n"
        f"- Formatage résultats\n"
        f"- Inline buttons [Ouvrir] [Détails]"
    )
