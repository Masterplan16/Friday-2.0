#!/usr/bin/env bash
# Rotation des mots de passe Redis ACL
#
# Usage sur le VPS :
#   1. Créer /tmp/new-redis-passwords.env avec les nouveaux mots de passe
#   2. ./scripts/rotate-redis-passwords.sh
#   3. Vérifier que tous les services Friday redémarrent correctement
#
# Ce script :
#   - Charge les nouveaux mots de passe depuis /tmp/new-redis-passwords.env
#   - Applique les nouveaux ACL sur Redis avec ACL SETUSER
#   - Génère un nouveau config/redis.acl depuis le template
#   - NE redémarre PAS les services (à faire manuellement après)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "Rotation mots de passe Redis ACL"
echo "========================================"
echo ""

# Vérifier que le fichier de nouveaux passwords existe
NEW_PASSWORDS_FILE="/tmp/new-redis-passwords.env"
if [[ ! -f "$NEW_PASSWORDS_FILE" ]]; then
    echo "ERREUR : Fichier $NEW_PASSWORDS_FILE introuvable" >&2
    echo "" >&2
    echo "Créez ce fichier d'abord avec les nouveaux mots de passe :" >&2
    echo "  REDIS_ADMIN_PASSWORD=..." >&2
    echo "  REDIS_GATEWAY_PASSWORD=..." >&2
    echo "  etc." >&2
    exit 1
fi

# Charger les nouveaux mots de passe
echo "Chargement des nouveaux mots de passe..."
source "$NEW_PASSWORDS_FILE"

# Vérifier que toutes les variables sont définies
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

missing=()
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        missing+=("$var")
    fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERREUR : Variables manquantes dans $NEW_PASSWORDS_FILE :" >&2
    for var in "${missing[@]}"; do
        echo "  - $var" >&2
    done
    exit 1
fi

echo "  ✓ 10 nouveaux mots de passe chargés"
echo ""

# Connexion Redis (utilise le mot de passe admin ACTUEL depuis env var)
# source "$PROJECT_ROOT/.env"  # Commenté: peut avoir des erreurs de syntaxe
REDIS_CLI="docker exec -i friday-redis redis-cli --user admin --pass \"\$REDIS_ADMIN_PASSWORD\""

echo "Vérification connexion Redis..."
if ! $REDIS_CLI PING > /dev/null 2>&1; then
    echo "ERREUR : Connexion Redis échouée" >&2
    echo "Vérifiez que Redis est démarré et que REDIS_ADMIN_PASSWORD dans .env est correct" >&2
    exit 1
fi
echo "  ✓ Connexion Redis OK"
echo ""

# Appliquer les nouveaux mots de passe avec ACL SETUSER
echo "Application des nouveaux ACL sur Redis..."

# Admin (utilise le NOUVEAU mot de passe)
$REDIS_CLI ACL SETUSER admin on ">$REDIS_ADMIN_PASSWORD" ~* \&* +@all
echo "  ✓ admin"

# Gateway
$REDIS_CLI ACL SETUSER friday_gateway on ">$REDIS_GATEWAY_PASSWORD" ~* \&* +get +set +setex +del +expire +ttl +publish +subscribe +xadd +xreadgroup +xack +xlen +ping +info +client
echo "  ✓ friday_gateway"

# Agents
$REDIS_CLI ACL SETUSER friday_agents on ">$REDIS_AGENTS_PASSWORD" ~stream:* ~presidio:mapping:* \&* +xadd +xreadgroup +xack +xpending +xlen +get +setex +del +publish +subscribe +ping +info +client
echo "  ✓ friday_agents"

# Alerting
$REDIS_CLI ACL SETUSER friday_alerting on ">$REDIS_ALERTING_PASSWORD" ~stream:* \&* +xreadgroup +xack +xadd +xpending +xlen +subscribe +ping +info +client
echo "  ✓ friday_alerting"

# Metrics
$REDIS_CLI ACL SETUSER friday_metrics on ">$REDIS_METRICS_PASSWORD" ~metrics:* \&* +get +set +incrby +expire +ping +info +client
echo "  ✓ friday_metrics"

# n8n
$REDIS_CLI ACL SETUSER friday_n8n on ">$REDIS_N8N_PASSWORD" ~cache:* ~bull:* ~n8n:* \&* +get +set +setex +del +expire +lpush +rpush +lrange +llen +publish +subscribe +sadd +smembers +ping +info +client +select
echo "  ✓ friday_n8n"

# Bot
$REDIS_CLI ACL SETUSER friday_bot on ">$REDIS_BOT_PASSWORD" ~* \&* +get +set +setex +del +expire +publish +subscribe +xadd +xreadgroup +xack +xpending +xlen +ping +info +client +select
echo "  ✓ friday_bot"

# Email
$REDIS_CLI ACL SETUSER friday_email on ">$REDIS_EMAIL_PASSWORD" ~* \&* +get +set +setex +del +expire +exists +publish +subscribe +xadd +xreadgroup +xack +xpending +xlen +xgroup\|create +xgroup\|setid +xgroup\|delconsumer +xinfo\|groups +xinfo\|stream +ping +info +client +select
echo "  ✓ friday_email"

# Document Processor
$REDIS_CLI ACL SETUSER document_processor on ">$REDIS_DOCUMENT_PROCESSOR_PASSWORD" ~* \&* +get +set +setex +del +expire +exists +publish +subscribe +xadd +xreadgroup +xack +xpending +xlen +xgroup\|create +xgroup\|setid +xinfo\|groups +xinfo\|stream +ping +info +client +select
echo "  ✓ document_processor"

# EmailEngine
$REDIS_CLI ACL SETUSER friday_emailengine on ">$REDIS_EMAILENGINE_PASSWORD" ~* \&* +@read +@write -flushall -flushdb +@pubsub +@scripting +@connection +select +ping +info +client
echo "  ✓ friday_emailengine"

echo ""
echo "ACL sauvegardés sur Redis (en mémoire)"
echo ""

# Générer nouveau config/redis.acl depuis le template
echo "Génération nouveau config/redis.acl..."
export REDIS_ADMIN_PASSWORD
export REDIS_GATEWAY_PASSWORD
export REDIS_AGENTS_PASSWORD
export REDIS_ALERTING_PASSWORD
export REDIS_METRICS_PASSWORD
export REDIS_N8N_PASSWORD
export REDIS_BOT_PASSWORD
export REDIS_EMAIL_PASSWORD
export REDIS_DOCUMENT_PROCESSOR_PASSWORD
export REDIS_EMAILENGINE_PASSWORD

envsubst < "$PROJECT_ROOT/config/redis.acl.template" > "$PROJECT_ROOT/config/redis.acl"
chmod 600 "$PROJECT_ROOT/config/redis.acl"
echo "  ✓ config/redis.acl généré ($(wc -l < "$PROJECT_ROOT/config/redis.acl") lignes)"
echo ""

# Sauvegarder ACL sur disque (persistence Redis)
echo "Sauvegarde ACL sur disque..."
$REDIS_CLI ACL SAVE
echo "  ✓ ACL sauvegardés dans /data/users.acl"
echo ""

echo "========================================"
echo "Rotation terminée avec succès !"
echo "========================================"
echo ""
echo "ÉTAPES SUIVANTES :"
echo "1. Mettre à jour .env avec les nouveaux mots de passe"
echo "2. Chiffrer .env avec SOPS : sops -e .env > .env.enc"
echo "3. Redémarrer les services Friday :"
echo "     docker compose -p friday-20 -f docker-compose.yml -f docker-compose.services.yml restart"
echo "4. Vérifier que tous les services sont healthy :"
echo "     docker compose -p friday-20 ps"
echo "5. Supprimer /tmp/new-redis-passwords.env"
echo ""
echo "ATTENTION : Les services Friday ont encore les ANCIENS mots de passe."
echo "            Ils se reconnecteront automatiquement après le restart."
echo ""
