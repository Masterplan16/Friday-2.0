#!/usr/bin/env bash
# Test E2E Pipeline Email - Story 2.9
#
# Prérequis :
#   - Webhooks EmailEngine configurés via interface web
#   - Email test envoyé à antonio.lopez@umontpellier.fr
#
# Usage :
#   ssh friday-vps 'bash -s' < scripts/test-email-pipeline-e2e.sh

set -euo pipefail

echo "=========================================="
echo "Test E2E Pipeline Email - Story 2.9"
echo "=========================================="
echo ""

cd /opt/friday
source .env
source .env.email

echo "=== 1. Vérification services ==="
docker ps --filter "name=friday-" --format "{{.Names}}\t{{.Status}}" | \
  grep -E "(gateway|email|redis)" | \
  awk '{printf "%-30s %s\n", $1, $2}'

echo ""
echo "=== 2. Configuration webhooks EmailEngine ==="
curl -s -H "Authorization: Bearer $EMAILENGINE_ACCESS_TOKEN" \
  http://localhost:3000/v1/settings | \
  python3 -c "import sys, json; d = json.load(sys.stdin) if sys.stdin.readable() else {}; print(f\"Enabled: {d.get('webhooksEnabled', False)}\"); print(f\"URL: {d.get('webhooks', 'NOT SET')}\")" \
  || echo "ERREUR: EmailEngine API inaccessible"

echo ""
echo "=== 3. Dernier email reçu (account_faculty) ==="
curl -s -H "Authorization: Bearer $EMAILENGINE_ACCESS_TOKEN" \
  "http://localhost:3000/v1/account/account_faculty/messages?limit=1" | \
  python3 -c "import sys, json; msgs = json.load(sys.stdin).get('messages', []); print(f\"Total: {len(msgs)}\"); [print(f\"  From: {m.get('from', {}).get('address')}\n  Subject: {m.get('subject')}\n  Date: {m.get('date')}\") for m in msgs[:1]] if msgs else print('  Aucun email')" \
  || echo "ERREUR: Impossible de récupérer emails"

echo ""
echo "=== 4. Events Redis Streams (emails:received) ==="
docker exec friday-redis redis-cli --user admin --pass "$REDIS_ADMIN_PASSWORD" \
  XLEN emails:received 2>/dev/null || echo "0"
echo "events dans le stream"

echo ""
echo "=== 5. Consumer group status ==="
docker exec friday-redis redis-cli --user admin --pass "$REDIS_ADMIN_PASSWORD" \
  XINFO GROUPS emails:received 2>/dev/null | head -10 || echo "Stream vide"

echo ""
echo "=== 6. Logs récents email-processor ==="
docker logs friday-email-processor --since 10m 2>&1 | \
  grep -E '(webhook|message|event|ERROR)' | tail -10 || echo "Aucun log récent"

echo ""
echo "=== 7. Logs récents gateway (webhooks) ==="
docker logs friday-gateway --since 10m 2>&1 | \
  grep -E '(webhook|emailengine)' | tail -10 || echo "Aucun webhook reçu"

echo ""
echo "=========================================="
echo "Test E2E terminé"
echo "=========================================="
