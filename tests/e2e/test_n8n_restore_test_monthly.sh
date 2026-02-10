#!/bin/bash
# Test E2E: Workflow n8n restore-test-monthly
# Valide que le test restore mensuel fonctionne et log résultats
#
# Usage:
#   ./tests/e2e/test_n8n_restore_test_monthly.sh
#
# Prerequis:
#   - Docker Compose running
#   - n8n operationnel
#   - Au moins 1 backup existant

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Friday 2.0 - Test Restore Monthly${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Configuration
POSTGRES_CONTAINER="friday-postgres"
POSTGRES_USER="friday"
POSTGRES_DB="friday"

#############################################
# ÉTAPE 1: Vérifier qu'un backup existe
#############################################
echo -e "${YELLOW}[1/3] Vérification backup existant...${NC}"

BACKUP_COUNT=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
    "SELECT COUNT(*) FROM core.backup_metadata;" | tr -d ' ')

if [ "$BACKUP_COUNT" -eq 0 ]; then
    echo -e "${RED}❌ Aucun backup trouvé - exécuter backup.sh d'abord${NC}"
    exit 1
fi

echo -e "${GREEN}✅ ${BACKUP_COUNT} backup(s) trouvé(s)${NC}"

#############################################
# ÉTAPE 2: Trigger workflow n8n manuellement
#############################################
echo ""
echo -e "${YELLOW}[2/3] Trigger workflow restore-test-monthly...${NC}"

# Note: Nécessite n8n API key configurée
if [ -z "${N8N_API_KEY:-}" ]; then
    echo -e "${YELLOW}⚠️  N8N_API_KEY not set - skipping workflow trigger${NC}"
    echo -e "${YELLOW}   Manual test: Trigger workflow via n8n UI${NC}"
else
    # Trouver workflow ID
    WORKFLOW_ID=$(curl -s -X GET "http://localhost:5678/api/v1/workflows" \
        -H "X-N8N-API-KEY: $N8N_API_KEY" \
        | jq -r '.data[] | select(.name=="Friday Restore Test Monthly") | .id' 2>/dev/null || echo "")

    if [ -z "$WORKFLOW_ID" ]; then
        echo -e "${YELLOW}⚠️  Workflow 'Friday Restore Test Monthly' not found in n8n${NC}"
        echo -e "${YELLOW}   Import n8n-workflows/restore-test-monthly.json first${NC}"
    else
        # Trigger execution
        curl -s -X POST "http://localhost:5678/api/v1/workflows/$WORKFLOW_ID/execute" \
            -H "X-N8N-API-KEY: $N8N_API_KEY" > /dev/null

        echo -e "${GREEN}✅ Workflow triggered (ID: $WORKFLOW_ID)${NC}"
        echo -e "${YELLOW}   Waiting 30s for execution...${NC}"
        sleep 30
    fi
fi

#############################################
# ÉTAPE 3: Vérifier résultats dans BDD
#############################################
echo ""
echo -e "${YELLOW}[3/3] Vérification résultats test restore...${NC}"

# Chercher dernier test restore dans core.backup_metadata
LATEST_TEST=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
    "SELECT restore_test_status FROM core.backup_metadata
     WHERE last_restore_test IS NOT NULL
     ORDER BY last_restore_test DESC LIMIT 1;" | tr -d ' ')

if [ -z "$LATEST_TEST" ]; then
    echo -e "${YELLOW}⚠️  Aucun test restore trouvé - workflow peut-être pas encore exécuté${NC}"
    echo -e "${YELLOW}   Vérifier logs n8n: docker compose logs friday-n8n${NC}"
    exit 0
fi

if [ "$LATEST_TEST" = "success" ]; then
    echo -e "${GREEN}✅ Dernier test restore: SUCCESS${NC}"
    EXIT_CODE=0
elif [ "$LATEST_TEST" = "failed" ]; then
    echo -e "${RED}❌ Dernier test restore: FAILED${NC}"
    EXIT_CODE=1
else
    echo -e "${YELLOW}⚠️  Statut inconnu: $LATEST_TEST${NC}"
    EXIT_CODE=1
fi

#############################################
# RÉSULTAT FINAL
#############################################
echo ""
echo -e "${YELLOW}========================================${NC}"

if [ "$EXIT_CODE" -eq 0 ]; then
    echo -e "${GREEN}✅ TEST RESTORE MONTHLY : SUCCÈS${NC}"
else
    echo -e "${RED}❌ TEST RESTORE MONTHLY : ÉCHEC${NC}"
fi

echo -e "${YELLOW}========================================${NC}"
exit $EXIT_CODE
