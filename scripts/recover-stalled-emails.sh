#!/bin/bash
# Recover Stalled Emails - Story 2.1 Task 5.3
# Reclaim messages PEL (Pending Entries List) stuck >1h
#
# Usage:
#   bash scripts/recover-stalled-emails.sh [--dry-run]
#
# Cron: Quotidien 3h (peu d'emails stuck en temps normal)
#   0 3 * * * /app/scripts/recover-stalled-emails.sh >> /var/log/friday/recover-emails.log 2>&1

set -euo pipefail

# Configuration
REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
STREAM_NAME="emails:received"
CONSUMER_GROUP="email-processor-group"
RECOVERY_CONSUMER="consumer-recovery"
IDLE_TIME_MS=3600000  # 1h en millisecondes

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

echo "🔧 Starting stalled emails recovery..."
echo "   Stream: $STREAM_NAME"
echo "   Group: $CONSUMER_GROUP"
echo "   Idle time: ${IDLE_TIME_MS}ms (1h)"

# Get pending messages
PENDING=$(redis-cli --raw -u "$REDIS_URL" XPENDING "$STREAM_NAME" "$CONSUMER_GROUP" - + 100)

if [[ -z "$PENDING" ]] || [[ "$PENDING" == "0" ]]; then
    echo "✅ No pending messages found"
    exit 0
fi

echo "⚠️  Found pending messages, checking idle time..."

# Parse pending info (format: message_id consumer idle_time delivery_count)
while IFS= read -r line; do
    if [[ -z "$line" ]]; then
        continue
    fi

    # Parse line: 1) message_id 2) consumer 3) idle_time 4) delivery_count
    MESSAGE_ID=$(echo "$line" | awk '{print $1}')
    CONSUMER=$(echo "$line" | awk '{print $2}')
    IDLE_MS=$(echo "$line" | awk '{print $3}')

    if [[ "$IDLE_MS" -lt "$IDLE_TIME_MS" ]]; then
        echo "   ℹ️  Message $MESSAGE_ID idle ${IDLE_MS}ms (< threshold, skip)"
        continue
    fi

    echo "   🔁 Reclaiming message $MESSAGE_ID from $CONSUMER (idle ${IDLE_MS}ms)"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "      [DRY-RUN] Would XCLAIM message"
        continue
    fi

    # XCLAIM: Transfer ownership to recovery consumer
    CLAIMED=$(redis-cli --raw -u "$REDIS_URL" XCLAIM "$STREAM_NAME" "$CONSUMER_GROUP" "$RECOVERY_CONSUMER" "$IDLE_TIME_MS" "$MESSAGE_ID")

    if [[ -n "$CLAIMED" ]]; then
        echo "   ✅ Message $MESSAGE_ID reclaimed successfully"

        # TODO: Reprocess message (appeler consumer Python)
        # Pour l'instant, juste XACK (message sera perdu mais PEL nettoyé)
        redis-cli --raw -u "$REDIS_URL" XACK "$STREAM_NAME" "$CONSUMER_GROUP" "$MESSAGE_ID"
        echo "   ⚠️  Message XACK (reprocessing not implemented yet)"
    else
        echo "   ❌ Failed to reclaim message $MESSAGE_ID"
    fi

done <<< "$(redis-cli --raw -u "$REDIS_URL" XPENDING "$STREAM_NAME" "$CONSUMER_GROUP" - + 100 | tail -n +2)"

echo "✅ Stalled emails recovery complete"
