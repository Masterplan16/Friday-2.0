#!/bin/bash
# Script pour réinitialiser les 189 emails pending dans Redis Streams
# À utiliser APRÈS avoir configuré ANTHROPIC_API_KEY valide
#
# Usage:
#   ./scripts/reset_pending_emails.sh [--delete|--reclaim]
#
# Options:
#   --delete   : Supprimer définitivement les 189 pending (perte des emails)
#   --reclaim  : Réassigner les pending pour retraitement (option recommandée)
#
# Date: 2026-02-14

set -euo pipefail

REDIS_CONTAINER="friday-redis"
STREAM_NAME="emails:received"
GROUP_NAME="email-processor"
CONSUMER_NAME="consumer-1"

# Parse arguments
ACTION="${1:-reclaim}"

case "$ACTION" in
  --delete)
    echo "⚠️  MODE DESTRUCTIF : Suppression des emails pending"
    echo "⏳ Récupération des IDs pending..."

    # Get all pending message IDs
    PENDING_IDS=$(docker exec $REDIS_CONTAINER redis-cli XPENDING $STREAM_NAME $GROUP_NAME - + 200 $CONSUMER_NAME | grep -E '^[0-9]+-[0-9]+$' || true)

    if [ -z "$PENDING_IDS" ]; then
      echo "✅ Aucun message pending trouvé"
      exit 0
    fi

    COUNT=$(echo "$PENDING_IDS" | wc -l)
    echo "📊 $COUNT messages pending trouvés"
    echo ""
    read -p "⚠️  ATTENTION: Supprimer définitivement ces $COUNT emails ? (y/N): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "❌ Annulé"
      exit 1
    fi

    echo "🗑️  Suppression en cours..."
    for ID in $PENDING_IDS; do
      docker exec $REDIS_CONTAINER redis-cli XACK $STREAM_NAME $GROUP_NAME "$ID" > /dev/null
      echo "  ✓ ACK $ID"
    done

    echo "✅ $COUNT messages supprimés du pending (ACKed)"
    ;;

  --reclaim)
    echo "🔄 MODE RECLAIM : Réassignation des emails pending pour retraitement"
    echo "⏳ Récupération des IDs pending..."

    # Get all pending message IDs
    PENDING_IDS=$(docker exec $REDIS_CONTAINER redis-cli XPENDING $STREAM_NAME $GROUP_NAME - + 200 $CONSUMER_NAME | grep -E '^[0-9]+-[0-9]+$' || true)

    if [ -z "$PENDING_IDS" ]; then
      echo "✅ Aucun message pending trouvé"
      exit 0
    fi

    COUNT=$(echo "$PENDING_IDS" | wc -l)
    echo "📊 $COUNT messages pending trouvés"
    echo ""
    echo "ℹ️  Ces messages seront réassignés et retraités par le consumer"
    read -p "Continuer ? (Y/n): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Nn]$ ]]; then
      echo "❌ Annulé"
      exit 1
    fi

    echo "🔄 Réassignation en cours (XCLAIM avec min-idle-time=0)..."

    # XCLAIM tous les pending messages avec min-idle-time=0 (immédiat)
    # Note: XCLAIM les rend à nouveau pending pour ce consumer,
    # donc le consumer doit utiliser '0' pour les relire
    for ID in $PENDING_IDS; do
      docker exec $REDIS_CONTAINER redis-cli XCLAIM $STREAM_NAME $GROUP_NAME $CONSUMER_NAME 0 "$ID" > /dev/null
      echo "  ✓ XCLAIM $ID"
    done

    echo ""
    echo "✅ $COUNT messages réassignés"
    echo ""
    echo "⚠️  IMPORTANT: Pour retraiter ces messages, vous devez :"
    echo "   1. Configurer ANTHROPIC_API_KEY valide dans .env"
    echo "   2. Activer le pipeline: docker exec friday-redis redis-cli SET friday:pipeline_enabled true"
    echo "   3. Temporairement modifier consumer.py pour utiliser '0' au lieu de '>'"
    echo "   4. Redémarrer le consumer: docker compose restart email-processor"
    echo "   5. Une fois traités, remettre '>' et redémarrer"
    ;;

  *)
    echo "❌ Option invalide: $ACTION"
    echo "Usage: $0 [--delete|--reclaim]"
    exit 1
    ;;
esac

echo ""
echo "📊 État actuel du stream:"
docker exec $REDIS_CONTAINER redis-cli XINFO GROUPS $STREAM_NAME
