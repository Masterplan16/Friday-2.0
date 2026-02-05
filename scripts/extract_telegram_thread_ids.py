#!/usr/bin/env python3
"""
Extract Telegram Thread IDs for Topics Setup

Ce script extrait automatiquement les thread IDs des topics d'un supergroup Telegram
et génère un fichier .env.telegram-topics prêt à copier dans .env

Usage:
    python scripts/extract_telegram_thread_ids.py

Prérequis:
    - TELEGRAM_BOT_TOKEN dans .env
    - Bot ajouté au supergroup Friday 2.0 Control
    - Bot a les droits admin (Manage Topics)

Story: 1.6.2 - Supergroup Setup
Date: 2026-02-05
"""

import asyncio
import os
import sys
from pathlib import Path

try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    print("❌ Erreur: python-telegram-bot non installé")
    print("   Installer avec: pip install python-telegram-bot")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("❌ Erreur: python-dotenv non installé")
    print("   Installer avec: pip install python-dotenv")
    sys.exit(1)


# Charger variables d'environnement
project_root = Path(__file__).parent.parent
env_file = project_root / ".env"
load_dotenv(env_file)


async def extract_thread_ids():
    """Extrait les thread IDs des topics du supergroup"""

    # 1. Vérifier token bot
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN manquant dans .env")
        print("   Obtenir via @BotFather : https://t.me/botfather")
        return False

    print(f"🔑 Token bot trouvé : {token[:10]}...")

    # 2. Initialiser bot
    try:
        bot = Bot(token=token)
        bot_info = await bot.get_me()
        print(f"✅ Bot connecté : @{bot_info.username}")
    except TelegramError as e:
        print(f"❌ Erreur connexion bot : {e}")
        return False

    # 3. Demander chat ID si pas dans .env
    supergroup_id = os.getenv("TELEGRAM_SUPERGROUP_ID")

    if not supergroup_id:
        print("\n📝 TELEGRAM_SUPERGROUP_ID non trouvé dans .env")
        print("   Obtenir via @userinfobot ajouté temporairement au supergroup")
        supergroup_id = input("   Entrer le Chat ID du supergroup (ex: -1001234567890): ").strip()

        if not supergroup_id:
            print("❌ Chat ID requis pour continuer")
            return False

    try:
        supergroup_id = int(supergroup_id)
    except ValueError:
        print(f"❌ Chat ID invalide : {supergroup_id}")
        return False

    print(f"\n✅ Supergroup ID : {supergroup_id}")

    # 4. Récupérer infos supergroup
    try:
        chat = await bot.get_chat(supergroup_id)
        print(f"✅ Supergroup trouvé : {chat.title}")

        if not chat.is_forum:
            print("❌ Ce groupe n'est pas un supergroup avec topics activés")
            print("   Activer topics : Paramètres groupe → Enable Topics")
            return False
    except TelegramError as e:
        print(f"❌ Erreur accès supergroup : {e}")
        print("   Vérifier que le bot est membre du groupe et a les droits admin")
        return False

    # 5. Lister les topics (forum topics)
    try:
        # Note: L'API Telegram ne fournit pas directement la liste des topics
        # On doit les déduire des messages ou utiliser getForumTopicIconStickers
        # Pour simplifier, on demande à l'utilisateur de poster un message dans chaque topic

        print("\n📂 Extraction des thread IDs...")
        print("   (Les topics General ont thread_id=null/0 par défaut)")

        # Topics attendus selon architecture
        expected_topics = [
            {"name": "💬 Chat & Proactive", "env_var": "TOPIC_CHAT_PROACTIVE_ID"},
            {"name": "📬 Email & Communications", "env_var": "TOPIC_EMAIL_ID"},
            {"name": "🤖 Actions & Validations", "env_var": "TOPIC_ACTIONS_ID"},
            {"name": "🚨 System & Alerts", "env_var": "TOPIC_SYSTEM_ID"},
            {"name": "📊 Metrics & Logs", "env_var": "TOPIC_METRICS_ID"},
        ]

        print("\n⚠️  MANUEL REQUIS :")
        print("   1. Poster un message dans CHAQUE topic (ex: 'test')")
        print("   2. Ce script va lire les derniers messages pour extraire les thread IDs")
        input("   Appuyer sur Entrée quand c'est fait...")

        # Récupérer updates récents
        updates = await bot.get_updates(limit=100, timeout=30)

        if not updates:
            print("❌ Aucun message récent trouvé")
            print("   Poster un message dans chaque topic et réessayer")
            return False

        # Extraire thread IDs des messages
        thread_ids = {}
        for update in updates:
            if update.message and update.message.chat.id == supergroup_id:
                thread_id = update.message.message_thread_id
                text = update.message.text or ""

                if thread_id and thread_id not in thread_ids.values():
                    # Essayer de deviner le topic par le texte
                    for topic in expected_topics:
                        if topic["name"] not in thread_ids:
                            thread_ids[topic["name"]] = thread_id
                            print(f"   ✅ {topic['name']} → thread_id: {thread_id}")
                            break

        if len(thread_ids) < 5:
            print(f"\n⚠️  Seulement {len(thread_ids)}/5 topics détectés")
            print("   Poster un message dans les topics manquants et réessayer")

        # 6. Générer fichier .env
        env_output = project_root / ".env.telegram-topics"

        with open(env_output, "w", encoding="utf-8") as f:
            f.write("# Telegram Topics Configuration\n")
            f.write("# Généré automatiquement par extract_telegram_thread_ids.py\n")
            f.write(f"# Date: {asyncio.get_event_loop().time()}\n\n")
            f.write(f"TELEGRAM_SUPERGROUP_ID={supergroup_id}\n")

            for topic in expected_topics:
                thread_id = thread_ids.get(topic["name"], "UNKNOWN")
                f.write(f"{topic['env_var']}={thread_id}\n")

        print(f"\n✅ Fichier généré : {env_output}")
        print(f"   Copier le contenu dans votre .env principal")

        if len(thread_ids) == 5:
            print("\n✅ Tous les topics détectés ! Setup terminé.")
            return True
        else:
            print(f"\n⚠️  Setup partiel : {len(thread_ids)}/5 topics")
            return False

    except TelegramError as e:
        print(f"❌ Erreur extraction topics : {e}")
        return False


def main():
    """Point d'entrée principal"""
    print("=" * 60)
    print("🔧 Extraction Telegram Thread IDs")
    print("   Friday 2.0 - Story 1.6.2")
    print("=" * 60)

    # Vérifier Python version
    if sys.version_info < (3, 11):
        print(f"⚠️  Python 3.11+ recommandé (vous avez {sys.version_info.major}.{sys.version_info.minor})")

    # Lancer extraction
    try:
        success = asyncio.run(extract_thread_ids())

        if success:
            print("\n🎉 Extraction terminée avec succès !")
            sys.exit(0)
        else:
            print("\n⚠️  Extraction incomplète ou échouée")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n❌ Interrompu par l'utilisateur")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Erreur inattendue : {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
