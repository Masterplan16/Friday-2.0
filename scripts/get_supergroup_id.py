#!/usr/bin/env python3
"""
Script ultra simple pour récupérer le Supergroup ID.

Usage:
    1. Crée ton bot via @BotFather
    2. Ajoute le bot au groupe Friday
    3. Remplace TOKEN ci-dessous
    4. Lance: python scripts/get_supergroup_id.py
    5. Envoie UN message dans le groupe
"""

import requests
import sys

# ⚠️ REMPLACE PAR TON TOKEN @BotFather
TOKEN = "TON_TOKEN_ICI"

if TOKEN == "TON_TOKEN_ICI":
    print("❌ ERREUR: Remplace TOKEN dans le script par ton vrai token !")
    sys.exit(1)

print("=" * 60)
print("Friday 2.0 - Récupération Supergroup ID")
print("=" * 60)
print()
print("Étapes:")
print("1. Lance ce script")
print("2. Envoie UN message dans ton groupe Friday")
print("3. Attends 2 secondes")
print()
input("Appuie sur ENTRÉE quand tu es prêt...")
print()
print("Récupération des updates...")

url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
response = requests.get(url)

if response.status_code != 200:
    print(f"❌ Erreur API: {response.status_code}")
    print(response.text)
    sys.exit(1)

data = response.json()

if not data.get("ok"):
    print("❌ Erreur:", data)
    sys.exit(1)

updates = data.get("result", [])

if not updates:
    print("⚠️  Aucun message détecté.")
    print("   Envoie un message dans le groupe et relance le script.")
    sys.exit(0)

print(f"✅ {len(updates)} message(s) détecté(s)")
print()

# Chercher les supergroupes
supergroups = {}

for update in updates:
    message = update.get("message", {})
    chat = message.get("chat", {})

    if chat.get("type") == "supergroup":
        chat_id = chat.get("id")
        title = chat.get("title", "Sans titre")
        thread_id = message.get("message_thread_id")

        if chat_id not in supergroups:
            supergroups[chat_id] = {
                "title": title,
                "threads": set()
            }

        if thread_id:
            supergroups[chat_id]["threads"].add(thread_id)

if not supergroups:
    print("⚠️  Aucun supergroup détecté.")
    print("   Vérifie que le bot est bien dans le groupe.")
    sys.exit(0)

# Afficher les résultats
print("=" * 60)
print("🎉 SUPERGROUPE(S) DÉTECTÉ(S)")
print("=" * 60)
print()

for chat_id, info in supergroups.items():
    print(f"📱 Groupe: {info['title']}")
    print(f"   Supergroup ID: {chat_id}")

    if info['threads']:
        print(f"   Thread IDs détectés: {sorted(info['threads'])}")

    print()
    print("Copie dans ton .env:")
    print(f"TELEGRAM_SUPERGROUP_ID={chat_id}")
    print()

    if info['threads']:
        print("Thread IDs (note bien quel topic correspond à quel ID!):")
        for tid in sorted(info['threads']):
            print(f"# Topic ?: {tid}")
        print()

print("✅ Terminé!")
