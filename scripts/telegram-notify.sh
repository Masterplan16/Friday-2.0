#!/usr/bin/env bash
# telegram-notify.sh - Helper pour notifications Telegram Friday 2.0
#
# Envoie une notification Telegram au topic System
# Usage: ./telegram-notify.sh "Message text"
#
# Story 1.13 - AC5: Helper notifications Telegram

set -euo pipefail

# Configuration
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
TOPIC_SYSTEM_ID="${TOPIC_SYSTEM_ID:-}"  # Topic System (Story 1.9)
TIMEOUT_SECONDS=30  # AC5

# Vérifier arguments
if [ $# -eq 0 ]; then
    echo "Usage: $(basename "$0") \"Message text\""
    exit 1
fi

MESSAGE="$1"

# Vérifier variables d'environnement
if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ -z "$TELEGRAM_CHAT_ID" ]]; then
    echo "⚠️  TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Notification skipped."
    exit 0  # Exit 0 car c'est optionnel
fi

# Construire requête
API_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
POST_DATA="chat_id=${TELEGRAM_CHAT_ID}&text=${MESSAGE}&parse_mode=Markdown"

# Ajouter topic System si configuré
if [[ -n "$TOPIC_SYSTEM_ID" ]]; then
    POST_DATA="${POST_DATA}&message_thread_id=${TOPIC_SYSTEM_ID}"
fi

# Envoyer notification (AC5: timeout 30s)
if curl -s --max-time "$TIMEOUT_SECONDS" -X POST "$API_URL" -d "$POST_DATA" > /dev/null 2>&1; then
    echo "✅ Telegram notification sent"
    exit 0
else
    echo "❌ Telegram notification failed (timeout or error)"
    exit 1
fi
