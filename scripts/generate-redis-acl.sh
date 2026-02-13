#!/usr/bin/env bash
# Génère config/redis.acl à partir du template + variables d'environnement.
#
# Usage:
#   source .env && ./scripts/generate-redis-acl.sh
#   # ou
#   ./scripts/generate-redis-acl.sh  (si les vars sont déjà exportées)
#
# Requiert: toutes les variables REDIS_*_PASSWORD définies.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATE="$PROJECT_ROOT/config/redis.acl.template"
OUTPUT="$PROJECT_ROOT/config/redis.acl"

# Variables requises
REQUIRED_VARS=(
    REDIS_ADMIN_PASSWORD
    REDIS_GATEWAY_PASSWORD
    REDIS_AGENTS_PASSWORD
    REDIS_ALERTING_PASSWORD
    REDIS_METRICS_PASSWORD
    REDIS_N8N_PASSWORD
    REDIS_BOT_PASSWORD
    REDIS_EMAIL_PASSWORD
    REDIS_DOCUMENT_PROCESSOR_PASSWORD
    REDIS_EMAILENGINE_PASSWORD
)

# Vérification des variables
missing=()
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        missing+=("$var")
    fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERREUR: Variables manquantes:" >&2
    for var in "${missing[@]}"; do
        echo "  - $var" >&2
    done
    echo "" >&2
    echo "Chargez le .env d'abord: source .env && $0" >&2
    exit 1
fi

# Vérification template existe
if [[ ! -f "$TEMPLATE" ]]; then
    echo "ERREUR: Template non trouvé: $TEMPLATE" >&2
    exit 1
fi

# Génération via envsubst
envsubst < "$TEMPLATE" > "$OUTPUT"

# Permissions restrictives (lecture seule root/owner)
chmod 600 "$OUTPUT"

echo "redis.acl généré: $OUTPUT ($(wc -l < "$OUTPUT") lignes)"
