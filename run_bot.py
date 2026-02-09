#!/usr/bin/env python3
"""
Script de lancement du bot Telegram avec chargement automatique du .env
"""

from dotenv import load_dotenv

# Charger .env AVANT tout autre import
load_dotenv()

# Maintenant importer et lancer le bot
from bot.main import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
