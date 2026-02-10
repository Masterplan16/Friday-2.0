#!/usr/bin/env bash
# healthcheck-all.sh - Healthcheck complet Friday 2.0
#
# Vérifie que tous les services critiques sont opérationnels
# Usage: ./healthcheck-all.sh
#
# Story 1.13 - AC4: Post-reboot validation

set -euo pipefail

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
TIMEOUT_SECONDS=60  # Timeout total pour healthcheck
CRITICAL_SERVICES=(
    "postgres"
    "redis"
    "friday-gateway"
    "friday-bot"
    "n8n"
)

echo "🔍 Friday 2.0 - Healthcheck All Services"
echo "==========================================="
echo ""

# Fonction : Vérifier service Docker
check_docker_service() {
    local service=$1
    local max_retries=3
    local retry=0

    while [ $retry -lt $max_retries ]; do
        if docker ps --format "{{.Names}}" | grep -q "^${service}$"; then
            # Service en cours d'exécution, vérifier state
            local state=$(docker inspect --format='{{.State.Status}}' "$service" 2>/dev/null || echo "unknown")

            if [ "$state" = "running" ]; then
                echo -e "  ${GREEN}✓${NC} $service (running)"
                return 0
            else
                echo -e "  ${YELLOW}⚠${NC} $service (state: $state, retry $((retry+1))/$max_retries)"
                sleep 5
                ((retry++))
            fi
        else
            echo -e "  ${YELLOW}⚠${NC} $service (not found, retry $((retry+1))/$max_retries)"
            sleep 5
            ((retry++))
        fi
    done

    echo -e "  ${RED}✗${NC} $service (DOWN after $max_retries retries)"
    return 1
}

# Vérifier Docker daemon
echo "📦 Checking Docker daemon..."
if ! systemctl is-active --quiet docker; then
    echo -e "${RED}❌ Docker daemon is not running${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Docker daemon is running${NC}"
echo ""

# Vérifier services critiques
echo "🔧 Checking critical services..."
failed_services=()

for service in "${CRITICAL_SERVICES[@]}"; do
    if ! check_docker_service "$service"; then
        failed_services+=("$service")
    fi
done

echo ""

# Vérifier RAM
echo "📊 Checking system resources..."
if command -v free &> /dev/null; then
    total_gb=$(free -g | awk '/^Mem:/ {print $2}')
    used_gb=$(free -g | awk '/^Mem:/ {print $3}')
    ram_pct=$((used_gb * 100 / total_gb))
    echo "  RAM: ${used_gb}/${total_gb} GB (${ram_pct}%)"

    if [ "$ram_pct" -ge 85 ]; then
        echo -e "  ${YELLOW}⚠  RAM usage high: ${ram_pct}%${NC}"
    else
        echo -e "  ${GREEN}✓${NC} RAM OK"
    fi
fi

# Vérifier disk
if command -v df &> /dev/null; then
    disk_pct=$(df -h / | tail -1 | awk '{print $5}' | tr -d '%')
    echo "  Disk: ${disk_pct}%"

    if [ "$disk_pct" -ge 80 ]; then
        echo -e "  ${YELLOW}⚠  Disk usage high: ${disk_pct}%${NC}"
    else
        echo -e "  ${GREEN}✓${NC} Disk OK"
    fi
fi

echo ""

# Résultat final
if [ ${#failed_services[@]} -eq 0 ]; then
    echo -e "${GREEN}✅ All critical services are healthy${NC}"

    # Envoyer notification Telegram succès
    if command -v /opt/friday/scripts/telegram-notify.sh &> /dev/null; then
        /opt/friday/scripts/telegram-notify.sh "✅ *Friday Healthcheck PASSED*

All critical services are running:
$(printf '• %s\n' "${CRITICAL_SERVICES[@]}")

RAM: ${ram_pct}%
Disk: ${disk_pct}%

System ready."
    fi

    exit 0
else
    echo -e "${RED}❌ Healthcheck FAILED${NC}"
    echo "Failed services: ${failed_services[*]}"

    # Envoyer notification Telegram échec
    if command -v /opt/friday/scripts/telegram-notify.sh &> /dev/null; then
        /opt/friday/scripts/telegram-notify.sh "🚨 *Friday Healthcheck FAILED*

Failed services:
$(printf '• %s\n' "${failed_services[@]}")

Manual intervention required!"
    fi

    exit 1
fi
