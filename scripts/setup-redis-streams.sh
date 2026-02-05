#!/bin/bash
# setup-redis-streams.sh - Setup Redis Streams consumer groups pour Friday 2.0
#
# Usage: ./scripts/setup-redis-streams.sh

set -euo pipefail

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Fonction : Créer un consumer group
create_stream_group() {
    local stream=$1
    local group=$2

    echo -n "📝 Creating consumer group: $stream → $group ... "

    local cmd="XGROUP CREATE $stream $group $ MKSTREAM"

    if [[ -n "$REDIS_PASSWORD" ]]; then
        output=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning $cmd 2>&1 || true)
    else
        output=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" $cmd 2>&1 || true)
    fi

    if [[ "$output" == "OK" ]]; then
        echo -e "${GREEN}✓${NC}"
    elif [[ "$output" == *"BUSYGROUP"* ]]; then
        echo -e "${YELLOW}⚠ Already exists${NC}"
    else
        echo -e "❌ Error: $output"
        return 1
    fi
}

# Main
main() {
    echo "🚀 Setup Redis Streams for Friday 2.0"
    echo "======================================"
    echo ""
    echo "Redis: $REDIS_HOST:$REDIS_PORT"
    echo ""

    # Test connexion Redis
    echo -n "🔌 Testing Redis connection ... "
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ${REDIS_PASSWORD:+-a "$REDIS_PASSWORD" --no-auth-warning} PING > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Connected${NC}"
    else
        echo "❌ Failed"
        echo ""
        echo "💡 Vérifier que Redis est démarré :"
        echo "   docker compose up -d redis"
        exit 1
    fi

    echo ""
    echo "📋 Creating consumer groups..."
    echo "-------------------------------"

    # Créer consumer groups pour chaque stream critique
    create_stream_group "email.received" "email-processor"
    create_stream_group "document.processed" "document-indexer"
    create_stream_group "pipeline.error" "error-handler"
    create_stream_group "service.down" "monitoring"
    create_stream_group "trust.level.changed" "trust-manager"
    create_stream_group "action.corrected" "feedback-loop"
    create_stream_group "action.validated" "trust-manager"

    echo ""
    echo "======================================"
    echo -e "${GREEN}✅ Redis Streams setup complete!${NC}"
    echo ""
    echo "📊 Verify with:"
    echo "   redis-cli XINFO GROUPS email.received"
    echo "   redis-cli XINFO STREAMS email.received"
}

main "$@"
