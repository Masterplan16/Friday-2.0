#!/bin/bash
# generate-secrets.sh - Génération automatique des secrets manquants pour Friday 2.0
#
# Usage:
#   ./scripts/generate-secrets.sh [--env-file .env]
#
# Ce script:
#   1. Lit le .env existant (ou crée depuis .env.example)
#   2. Génère les clés/passwords manquants
#   3. Préserve les valeurs existantes (ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, etc.)
#   4. Crée .env.new avec toutes les valeurs complètes
#
# SÉCURITÉ: Le fichier .env généré contient des secrets sensibles.
# Chiffrer avec SOPS avant commit: ./scripts/encrypt-env.sh

set -euo pipefail

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
ENV_NEW="${PROJECT_ROOT}/.env.new"
ENV_EXAMPLE="${PROJECT_ROOT}/.env.example"

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Friday 2.0 - Générateur automatique de secrets${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Fonction: Générer un password aléatoire (base64, 32 bytes)
generate_password() {
    openssl rand -base64 32 | tr -d '\n'
}

# Fonction: Générer une clé hex (64 caractères)
generate_hex_key() {
    openssl rand -hex 32 | tr -d '\n'
}

# Fonction: Lire une valeur du .env existant
get_env_value() {
    local key="$1"
    local file="${2:-$ENV_FILE}"

    if [[ -f "$file" ]]; then
        grep "^${key}=" "$file" 2>/dev/null | cut -d= -f2- || echo ""
    else
        echo ""
    fi
}

# Vérifier si .env existe
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
        echo -e "${YELLOW}⚠️  Aucun .env trouvé. Copie depuis .env.example...${NC}"
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        echo -e "${GREEN}✓ .env créé depuis .env.example${NC}"
    else
        echo -e "${RED}❌ Erreur: .env.example introuvable!${NC}"
        exit 1
    fi
fi

echo -e "${BLUE}📋 Analyse du fichier .env existant...${NC}"
echo ""

# Compter secrets manquants
missing_count=0
generated_count=0

# Créer le nouveau .env
cat > "$ENV_NEW" << 'EOF'
# Friday 2.0 - Environment Variables
# Généré automatiquement par scripts/generate-secrets.sh
# Date: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
#
# ⚠️  IMPORTANT: Ce fichier contient des secrets sensibles
# Chiffrer avant commit: ./scripts/encrypt-env.sh

# ============================================
# PostgreSQL Database
# ============================================
EOF

# PostgreSQL
echo "" >> "$ENV_NEW"
POSTGRES_DB=$(get_env_value "POSTGRES_DB")
POSTGRES_DB=${POSTGRES_DB:-friday}
echo "POSTGRES_DB=$POSTGRES_DB" >> "$ENV_NEW"

POSTGRES_USER=$(get_env_value "POSTGRES_USER")
POSTGRES_USER=${POSTGRES_USER:-friday}
echo "POSTGRES_USER=$POSTGRES_USER" >> "$ENV_NEW"

POSTGRES_PASSWORD=$(get_env_value "POSTGRES_PASSWORD")
if [[ -z "$POSTGRES_PASSWORD" || "$POSTGRES_PASSWORD" == "changeme"* ]]; then
    POSTGRES_PASSWORD=$(generate_password)
    echo -e "${GREEN}✓ Généré: POSTGRES_PASSWORD${NC}"
    ((generated_count++))
else
    echo -e "${BLUE}→ Préservé: POSTGRES_PASSWORD (existant)${NC}"
fi
echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" >> "$ENV_NEW"

# Redis passwords
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# Redis - Passwords par service (ACL)
# ============================================
EOF

echo "" >> "$ENV_NEW"

REDIS_PASSWORD=$(get_env_value "REDIS_PASSWORD")
if [[ -z "$REDIS_PASSWORD" || "$REDIS_PASSWORD" == "changeme"* ]]; then
    REDIS_PASSWORD=$(generate_password)
    echo -e "${GREEN}✓ Généré: REDIS_PASSWORD${NC}"
    ((generated_count++))
else
    echo -e "${BLUE}→ Préservé: REDIS_PASSWORD (existant)${NC}"
fi
echo "REDIS_PASSWORD=$REDIS_PASSWORD" >> "$ENV_NEW"

# Générer passwords Redis par service
for service in GATEWAY BOT EMAIL ALERTING METRICS DOCUMENT_PROCESSOR; do
    var_name="REDIS_${service}_PASSWORD"
    current_value=$(get_env_value "$var_name")

    if [[ -z "$current_value" || "$current_value" == "changeme"* ]]; then
        new_value=$(generate_password)
        echo -e "${GREEN}✓ Généré: $var_name${NC}"
        ((generated_count++))
    else
        new_value="$current_value"
        echo -e "${BLUE}→ Préservé: $var_name (existant)${NC}"
    fi

    echo "${var_name}=$new_value" >> "$ENV_NEW"
done

# n8n
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# n8n Workflow Automation
# ============================================
EOF

echo "" >> "$ENV_NEW"

N8N_HOST=$(get_env_value "N8N_HOST")
N8N_HOST=${N8N_HOST:-n8n.friday.local}
echo "N8N_HOST=$N8N_HOST" >> "$ENV_NEW"

N8N_ENCRYPTION_KEY=$(get_env_value "N8N_ENCRYPTION_KEY")
if [[ -z "$N8N_ENCRYPTION_KEY" || "$N8N_ENCRYPTION_KEY" == "changeme"* ]]; then
    N8N_ENCRYPTION_KEY=$(generate_hex_key)
    echo -e "${GREEN}✓ Généré: N8N_ENCRYPTION_KEY${NC}"
    ((generated_count++))
else
    echo -e "${BLUE}→ Préservé: N8N_ENCRYPTION_KEY (existant)${NC}"
fi
echo "N8N_ENCRYPTION_KEY=$N8N_ENCRYPTION_KEY" >> "$ENV_NEW"

# API Security
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# API Security
# ============================================
EOF

echo "" >> "$ENV_NEW"

API_TOKEN=$(get_env_value "API_TOKEN")
if [[ -z "$API_TOKEN" || "$API_TOKEN" == "changeme"* ]]; then
    API_TOKEN=$(generate_hex_key)
    echo -e "${GREEN}✓ Généré: API_TOKEN${NC}"
    ((generated_count++))
else
    echo -e "${BLUE}→ Préservé: API_TOKEN (existant)${NC}"
fi
echo "API_TOKEN=$API_TOKEN" >> "$ENV_NEW"

# LLM Provider
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# LLM Provider - Claude Sonnet 4.5 (D17)
# ============================================
EOF

echo "" >> "$ENV_NEW"

ANTHROPIC_API_KEY=$(get_env_value "ANTHROPIC_API_KEY")
if [[ -z "$ANTHROPIC_API_KEY" || "$ANTHROPIC_API_KEY" == "your_"* ]]; then
    echo -e "${YELLOW}⚠️  ANTHROPIC_API_KEY manquante - À configurer manuellement${NC}"
    echo "ANTHROPIC_API_KEY=your_anthropic_api_key_here" >> "$ENV_NEW"
    ((missing_count++))
else
    echo -e "${BLUE}→ Préservé: ANTHROPIC_API_KEY (existant)${NC}"
    echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" >> "$ENV_NEW"
fi

# Embeddings Provider
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# Embeddings Provider - Voyage AI (Story 6.2)
# ============================================
EOF

echo "" >> "$ENV_NEW"

VOYAGE_API_KEY=$(get_env_value "VOYAGE_API_KEY")
if [[ -z "$VOYAGE_API_KEY" || "$VOYAGE_API_KEY" == "your_"* ]]; then
    echo -e "${YELLOW}⚠️  VOYAGE_API_KEY manquante (optionnel Day 1)${NC}"
    echo "# VOYAGE_API_KEY=your_voyage_api_key_here" >> "$ENV_NEW"
else
    echo -e "${BLUE}→ Préservé: VOYAGE_API_KEY (existant)${NC}"
    echo "VOYAGE_API_KEY=$VOYAGE_API_KEY" >> "$ENV_NEW"
fi

echo "EMBEDDING_PROVIDER=voyage" >> "$ENV_NEW"
echo "EMBEDDING_DIMENSIONS=1024" >> "$ENV_NEW"

# Memorystore
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# Memorystore Provider (Story 6.3)
# ============================================
EOF

echo "" >> "$ENV_NEW"
echo "MEMORYSTORE_PROVIDER=postgresql" >> "$ENV_NEW"

# Telegram
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# Telegram Bot (Story 1.9)
# ============================================
EOF

echo "" >> "$ENV_NEW"

TELEGRAM_BOT_TOKEN=$(get_env_value "TELEGRAM_BOT_TOKEN")
if [[ -z "$TELEGRAM_BOT_TOKEN" || "$TELEGRAM_BOT_TOKEN" == "your_"* ]]; then
    echo -e "${YELLOW}⚠️  TELEGRAM_BOT_TOKEN manquante - À configurer manuellement${NC}"
    echo "TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here" >> "$ENV_NEW"
    ((missing_count++))
else
    echo -e "${BLUE}→ Préservé: TELEGRAM_BOT_TOKEN (existant)${NC}"
    echo "TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN" >> "$ENV_NEW"
fi

TELEGRAM_SUPERGROUP_ID=$(get_env_value "TELEGRAM_SUPERGROUP_ID")
if [[ -z "$TELEGRAM_SUPERGROUP_ID" || "$TELEGRAM_SUPERGROUP_ID" == "-1001234567890" ]]; then
    echo -e "${YELLOW}⚠️  TELEGRAM_SUPERGROUP_ID manquante - À configurer manuellement${NC}"
    echo "TELEGRAM_SUPERGROUP_ID=-1001234567890" >> "$ENV_NEW"
    ((missing_count++))
else
    echo -e "${BLUE}→ Préservé: TELEGRAM_SUPERGROUP_ID (existant)${NC}"
    echo "TELEGRAM_SUPERGROUP_ID=$TELEGRAM_SUPERGROUP_ID" >> "$ENV_NEW"
fi

OWNER_USER_ID=$(get_env_value "OWNER_USER_ID")
if [[ -z "$OWNER_USER_ID" || "$OWNER_USER_ID" == "123456789" ]]; then
    echo -e "${YELLOW}⚠️  OWNER_USER_ID manquante - À configurer manuellement${NC}"
    echo "OWNER_USER_ID=123456789" >> "$ENV_NEW"
    ((missing_count++))
else
    echo -e "${BLUE}→ Préservé: OWNER_USER_ID (existant)${NC}"
    echo "OWNER_USER_ID=$OWNER_USER_ID" >> "$ENV_NEW"
fi

# Topics Telegram
echo "" >> "$ENV_NEW"
echo "# Thread IDs des 5 topics Telegram" >> "$ENV_NEW"
for i in 2 3 4 5 6; do
    case $i in
        2) topic="TOPIC_CHAT_PROACTIVE_ID" ;;
        3) topic="TOPIC_EMAIL_ID" ;;
        4) topic="TOPIC_ACTIONS_ID" ;;
        5) topic="TOPIC_SYSTEM_ID" ;;
        6) topic="TOPIC_METRICS_ID" ;;
    esac

    value=$(get_env_value "$topic")
    if [[ -z "$value" ]]; then
        value="$i"
        echo -e "${YELLOW}⚠️  $topic défaut: $i (à vérifier)${NC}"
    else
        echo -e "${BLUE}→ Préservé: $topic (existant)${NC}"
    fi
    echo "${topic}=$value" >> "$ENV_NEW"
done

# Backup & Encryption
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# Backup & Encryption (Story 1.12)
# ============================================
EOF

echo "" >> "$ENV_NEW"

AGE_PUBLIC_KEY=$(get_env_value "AGE_PUBLIC_KEY")
if [[ -z "$AGE_PUBLIC_KEY" || "$AGE_PUBLIC_KEY" == "age1x"* ]]; then
    echo -e "${YELLOW}⚠️  AGE_PUBLIC_KEY manquante - Générer avec: bash scripts/generate-age-keypair.sh${NC}"
    echo "AGE_PUBLIC_KEY=age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" >> "$ENV_NEW"
    ((missing_count++))
else
    echo -e "${BLUE}→ Préservé: AGE_PUBLIC_KEY (existant)${NC}"
    echo "AGE_PUBLIC_KEY=$AGE_PUBLIC_KEY" >> "$ENV_NEW"
fi

TAILSCALE_PC_HOSTNAME=$(get_env_value "TAILSCALE_PC_HOSTNAME")
TAILSCALE_PC_HOSTNAME=${TAILSCALE_PC_HOSTNAME:-mainteneur-pc}
echo "TAILSCALE_PC_HOSTNAME=$TAILSCALE_PC_HOSTNAME" >> "$ENV_NEW"

# PGP Encryption (D25: renomme depuis EMAILENGINE_ENCRYPTION_KEY)
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# PGP Encryption - pgcrypto pour emails raw (D25)
# ============================================
EOF

echo "" >> "$ENV_NEW"

PGP_ENCRYPTION_KEY=$(get_env_value "PGP_ENCRYPTION_KEY")
# Fallback: essayer ancien nom si nouveau absent
if [[ -z "$PGP_ENCRYPTION_KEY" ]]; then
    PGP_ENCRYPTION_KEY=$(get_env_value "EMAILENGINE_ENCRYPTION_KEY")
fi
if [[ -z "$PGP_ENCRYPTION_KEY" || "$PGP_ENCRYPTION_KEY" == "changeme"* ]]; then
    PGP_ENCRYPTION_KEY=$(generate_hex_key)
    echo -e "${GREEN}✓ Généré: PGP_ENCRYPTION_KEY${NC}"
    ((generated_count++))
else
    echo -e "${BLUE}→ Préservé: PGP_ENCRYPTION_KEY (existant)${NC}"
fi
echo "PGP_ENCRYPTION_KEY=$PGP_ENCRYPTION_KEY" >> "$ENV_NEW"

# [RETIRÉ D25] WEBHOOK_SECRET n'est plus nécessaire (IMAP direct, pas de webhook)

# Attachments Storage
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# Attachments Storage (Story 2.4)
# ============================================
EOF

echo "" >> "$ENV_NEW"

ATTACHMENTS_STORAGE_PATH=$(get_env_value "ATTACHMENTS_STORAGE_PATH")
ATTACHMENTS_STORAGE_PATH=${ATTACHMENTS_STORAGE_PATH:-C:\Friday\attachments}
echo "ATTACHMENTS_STORAGE_PATH=$ATTACHMENTS_STORAGE_PATH" >> "$ENV_NEW"

# Monitoring
cat >> "$ENV_NEW" << 'EOF'

# ============================================
# Monitoring & Logging
# ============================================
EOF

echo "" >> "$ENV_NEW"
echo "LOG_LEVEL=INFO" >> "$ENV_NEW"
echo "ENVIRONMENT=production" >> "$ENV_NEW"

# Résumé final
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Génération terminée !${NC}"
echo ""
echo -e "${GREEN}📊 Secrets générés automatiquement : $generated_count${NC}"
echo -e "${YELLOW}⚠️  Variables à configurer manuellement : $missing_count${NC}"
echo ""

if [[ $missing_count -gt 0 ]]; then
    echo -e "${YELLOW}Variables manquantes :${NC}"
    echo -e "${YELLOW}  - ANTHROPIC_API_KEY (requis)${NC}"
    echo -e "${YELLOW}  - TELEGRAM_BOT_TOKEN (requis)${NC}"
    echo -e "${YELLOW}  - TELEGRAM_SUPERGROUP_ID (requis)${NC}"
    echo -e "${YELLOW}  - OWNER_USER_ID (requis)${NC}"
    echo -e "${YELLOW}  - AGE_PUBLIC_KEY (backup)${NC}"
    echo ""
fi

echo -e "${BLUE}📁 Fichier généré : .env.new${NC}"
echo ""
echo -e "${BLUE}Prochaines étapes :${NC}"
echo -e "  1. Vérifier .env.new : ${BLUE}cat .env.new${NC}"
echo -e "  2. Ajouter les clés manquantes manuellement"
echo -e "  3. Remplacer .env : ${BLUE}mv .env.new .env${NC}"
echo -e "  4. Vérifier : ${BLUE}bash scripts/verify_env.sh --env-file .env${NC}"
echo -e "  5. Chiffrer : ${BLUE}./scripts/encrypt-env.sh${NC}"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
