#!/usr/bin/env python3
"""
Script ultra-automatisé pour configurer Friday 2.0 avec Telegram.

owner n'a qu'à:
1. Lancer ce script
2. Envoyer 1 message dans chaque topic du groupe Friday
3. Le script génère le .env automatiquement

Token pré-rempli, zéro configuration.
"""

import asyncio
import os
from pathlib import Path

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# ✅ TOKEN et USER ID depuis variables d'environnement (sécurisé)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTONIO_USER_ID_STR = os.getenv("ANTONIO_USER_ID")

# Validation fail-explicit
if not TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN environment variable required.\n"
        "Déchiffrez les secrets avec: ./scripts/load-secrets.sh"
    )
if not ANTONIO_USER_ID_STR:
    raise ValueError(
        "ANTONIO_USER_ID environment variable required.\n"
        "Déchiffrez les secrets avec: ./scripts/load-secrets.sh"
    )

try:
    ANTONIO_USER_ID = int(ANTONIO_USER_ID_STR)
except ValueError:
    raise ValueError(f"ANTONIO_USER_ID must be a valid integer, got: {ANTONIO_USER_ID_STR}")

# Stockage des IDs détectés
detected_topics = {}
supergroup_id = None

print("=" * 70)
print("🤖 Friday 2.0 - Configuration Telegram AUTOMATIQUE")
print("=" * 70)
print()
print("✅ Token bot : OK")
print("✅ User ID owner : OK")
print()
print("📋 INSTRUCTIONS SIMPLES :")
print()
print("1. Va dans ton groupe Friday sur Telegram Desktop")
print("2. Dans CHAQUE topic (5 au total), envoie un message (ex: 'test')")
print("3. Ce script détecte automatiquement tous les IDs")
print("4. Le fichier .env est généré automatiquement")
print()
print("Topics attendus:")
print("  • 💬 Chat & Proactive")
print("  • 📬 Email & Communications")
print("  • 🤖 Actions & Validations")
print("  • 🚨 System & Alerts")
print("  • 📊 Metrics & Logs")
print()
print("-" * 70)
print()
input("Appuie sur ENTRÉE quand tu es prêt, puis envoie tes messages...")
print()
print("🎧 En écoute... Envoie tes 5 messages maintenant!")
print()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Détecte les messages dans les topics et extrait les IDs."""
    global supergroup_id

    if not update.message:
        return

    message = update.message
    chat = message.chat

    # On ne traite que les supergroupes (forums Telegram)
    if chat.type != "supergroup":
        return

    # Capturer le supergroup ID
    if supergroup_id is None:
        supergroup_id = chat.id
        print(f"✅ Supergroup détecté : {chat.title}")
        print(f"   ID : {supergroup_id}")
        print()

    # Capturer le thread ID
    thread_id = message.message_thread_id

    if thread_id and thread_id not in detected_topics:
        # Nouveau topic détecté
        detected_topics[thread_id] = {
            "text": message.text or "[media]",
            "from": message.from_user.first_name if message.from_user else "Unknown",
        }

        print(f"✅ Topic {len(detected_topics)}/5 détecté :")
        print(f"   Thread ID : {thread_id}")
        print(f"   Message : {message.text[:30] if message.text else '[media]'}...")
        print()

        if len(detected_topics) >= 5:
            print("=" * 70)
            print("🎉 LES 5 TOPICS DÉTECTÉS !")
            print("=" * 70)
            print()
            await generate_env_file()
            print()
            print("✅ Configuration terminée ! Tu peux fermer ce script.")
            print()

            # Arrêter le bot proprement
            await context.application.stop()


async def generate_env_file():
    """Génère le fichier .env avec tous les IDs détectés."""

    env_path = Path(__file__).parent.parent / ".env"

    # Lire le .env existant s'il existe
    existing_env = {}
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    existing_env[key] = value

    # Trier les thread IDs (ordre d'envoi = ordre des topics)
    sorted_threads = sorted(detected_topics.keys())

    # Mapping suggéré (owner devra vérifier l'ordre)
    topic_names = [
        ("TOPIC_CHAT_PROACTIVE_ID", "💬 Chat & Proactive"),
        ("TOPIC_EMAIL_ID", "📬 Email & Communications"),
        ("TOPIC_ACTIONS_ID", "🤖 Actions & Validations"),
        ("TOPIC_SYSTEM_ID", "🚨 System & Alerts"),
        ("TOPIC_METRICS_ID", "📊 Metrics & Logs"),
    ]

    # Préparer les nouvelles valeurs
    new_values = {
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TELEGRAM_SUPERGROUP_ID": str(supergroup_id),
        "ANTONIO_USER_ID": str(ANTONIO_USER_ID),
    }

    # Assigner les thread IDs
    for i, (env_key, topic_name) in enumerate(topic_names):
        if i < len(sorted_threads):
            new_values[env_key] = str(sorted_threads[i])

    # Fusionner avec l'existant
    existing_env.update(new_values)

    # Écrire le .env
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# Friday 2.0 - Configuration Environment\n")
        f.write("# Généré automatiquement par setup_telegram_auto.py\n")
        f.write("\n")
        f.write("# ========================================\n")
        f.write("# Telegram Bot Configuration\n")
        f.write("# ========================================\n")
        f.write(f"TELEGRAM_BOT_TOKEN={existing_env['TELEGRAM_BOT_TOKEN']}\n")
        f.write(f"TELEGRAM_SUPERGROUP_ID={existing_env['TELEGRAM_SUPERGROUP_ID']}\n")
        f.write(f"ANTONIO_USER_ID={existing_env['ANTONIO_USER_ID']}\n")
        f.write("\n")
        f.write("# Topics Thread IDs (vérifier l'ordre ci-dessous!)\n")

        for i, (env_key, topic_name) in enumerate(topic_names):
            if env_key in existing_env:
                f.write(f"{env_key}={existing_env[env_key]}  # {topic_name}\n")

        f.write("\n")
        f.write("# ========================================\n")
        f.write("# Database & Redis (à configurer)\n")
        f.write("# ========================================\n")

        # Préserver ou ajouter les autres variables
        other_vars = [
            ("DATABASE_URL", "postgresql://friday:password@localhost:5432/friday"),
            ("REDIS_URL", "redis://default:password@localhost:6379/0"),
            ("LOG_LEVEL", "INFO"),
        ]

        for key, default in other_vars:
            value = existing_env.get(key, default)
            f.write(f"{key}={value}\n")

    print("📝 Fichier .env généré/mis à jour :")
    print(f"   {env_path.absolute()}")
    print()
    print("⚠️  IMPORTANT : Vérifie que l'ordre des topics correspond !")
    print()

    # Afficher le mapping
    print("Mapping détecté (ordre d'envoi des messages) :")
    for i, (env_key, topic_name) in enumerate(topic_names):
        if i < len(sorted_threads):
            thread_id = sorted_threads[i]
            msg_preview = detected_topics[thread_id]["text"][:30]
            print(f"  {i+1}. {topic_name}")
            print(f"     Thread ID : {thread_id}")
            print(f"     Message : {msg_preview}...")
            print()


async def main():
    """Lance le bot et attend les messages."""

    # Créer l'application
    app = Application.builder().token(TOKEN).build()

    # Ajouter le handler pour TOUS les messages
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    # Démarrer le bot
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Attendre que les 5 topics soient détectés ou timeout de 5 minutes
    timeout = 300  # 5 minutes
    elapsed = 0

    while len(detected_topics) < 5 and elapsed < timeout:
        await asyncio.sleep(1)
        elapsed += 1

    if len(detected_topics) < 5:
        print()
        print("⏱️  Timeout - Seulement {} topics détectés sur 5".format(len(detected_topics)))
        print()
        print("Tu peux relancer le script ou vérifier que:")
        print("  • Le bot est bien ajouté au groupe")
        print("  • Le bot a les droits 'Read Messages'")
        print("  • Tu as envoyé des messages dans les 5 topics")
        print()

    # Arrêter le bot
    await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Script interrompu par l'utilisateur")
        print()
        if detected_topics:
            print(f"Topics détectés : {len(detected_topics)}/5")
            print("Relance le script pour continuer.")
