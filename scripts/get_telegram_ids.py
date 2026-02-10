#!/usr/bin/env python3
"""
Script pour extraire les IDs Telegram (supergroup + topics).

Usage:
    1. Installer: pip install python-telegram-bot
    2. Remplacer TOKEN par ton token @BotFather
    3. Lancer: python scripts/get_telegram_ids.py
    4. Forward un message de CHAQUE topic vers le bot en privé
"""

import asyncio
import os

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# ⚠️ REMPLACE PAR TON TOKEN @BotFather
TOKEN = "TON_TOKEN_ICI"

print("=" * 60)
print("Friday 2.0 - Extraction IDs Telegram")
print("=" * 60)
print()
print("Instructions:")
print("1. Lance ce script")
print("2. Va dans ton groupe Friday 2.0 Control")
print("3. Dans CHAQUE topic, envoie un message (ex: 'test')")
print("4. Forward ce message au bot EN PRIVÉ")
print("5. Répète pour les 5 topics")
print()
print("Attente des messages...")
print("-" * 60)
print()

received_topics = set()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler qui affiche les IDs des messages reçus."""

    if not update.message:
        return

    # Message normal (pas forwardé)
    if not update.message.forward_from_chat:
        chat_id = update.message.chat_id
        user_id = update.effective_user.id

        print(f"📱 Message direct reçu:")
        print(f"   User ID: {user_id}")
        print(f"   Chat ID: {chat_id}")
        print()
        return

    # Message forwardé depuis un topic
    forward_chat = update.message.forward_from_chat
    forward_thread_id = update.message.forward_from_message_id

    chat_id = forward_chat.id
    thread_id = forward_thread_id

    # Identifier le topic par le thread_id (approximatif)
    if thread_id not in received_topics:
        received_topics.add(thread_id)

        print(f"✅ Topic {len(received_topics)}/5 détecté:")
        print(f"   Supergroup ID: {chat_id}")
        print(f"   Thread ID: {thread_id}")
        print(f"   (Note le Thread ID pour ce topic)")
        print()

        if len(received_topics) == 5:
            print("=" * 60)
            print("🎉 LES 5 TOPICS ONT ÉTÉ DÉTECTÉS !")
            print("=" * 60)
            print()
            print("Copie ces valeurs dans ton .env :")
            print()
            print(f"TELEGRAM_SUPERGROUP_ID={chat_id}")
            print()
            print("# Thread IDs (dans l'ordre où tu les as envoyés):")
            for i, tid in enumerate(sorted(received_topics), 1):
                print(f"# Topic {i}: {tid}")
            print()
            print("⚠️  IMPORTANT: Note quel thread_id correspond à quel topic !")
            print("    (regarde l'ordre dans lequel tu as envoyé les messages)")
            print()


async def main():
    """Lance le bot."""
    if TOKEN == "TON_TOKEN_ICI":
        print("❌ ERREUR: Remplace TOKEN dans le script par ton vrai token !")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # Garder le bot en vie
    while len(received_topics) < 5:
        await asyncio.sleep(1)

    await asyncio.sleep(3)  # Laisser temps de lire
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
