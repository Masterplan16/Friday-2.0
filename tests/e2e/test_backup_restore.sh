#!/bin/bash
# Test End-to-End: Backup & Restore complet
# Verifie que les backups Friday 2.0 sont restaurables et complets
#
# Usage:
#   ./tests/e2e/test_backup_restore.sh
#
# Prerequis:
#   - Docker Compose running
#   - Tailscale connecte
#   - Services PostgreSQL (+ pgvector D19) operationnels
#
# Portabilite:
#   - Linux/macOS : Natif
#   - Windows : Requiert WSL 2 UNIQUEMENT (Git Bash incompatible avec heredoc psql)
#   - Installer jq dans WSL: sudo apt-get install jq

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
POSTGRES_CONTAINER="friday-postgres"
BACKUP_DIR="/backups"
TEST_BACKUP_DIR="/tmp/friday_backup_test_$(date +%Y%m%d_%H%M%S)"
POSTGRES_USER="friday"
POSTGRES_DB="friday"

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Friday 2.0 - Test Backup & Restore${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Fonction d'erreur
error_exit() {
    echo -e "${RED}❌ ERREUR: $1${NC}" >&2
    cleanup
    exit 1
}

# Fonction de nettoyage
cleanup() {
    echo -e "${YELLOW}🧹 Nettoyage...${NC}"
    rm -rf "$TEST_BACKUP_DIR" 2>/dev/null || true
}

# Trap pour cleanup en cas d'erreur
trap cleanup EXIT

# Créer dossier de test
mkdir -p "$TEST_BACKUP_DIR"
echo -e "${GREEN}✅ Dossier test créé: $TEST_BACKUP_DIR${NC}"

#############################################
# ÉTAPE 1: Créer données de test
#############################################
echo ""
echo -e "${YELLOW}[1/6] Création données de test PostgreSQL...${NC}"

docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<EOF || error_exit "Échec création données test"
-- Insérer emails de test
INSERT INTO ingestion.emails (message_id, sender, subject, body_text, category, priority, received_at)
VALUES
    ('test_001', 'test@example.com', 'Test Email 1', 'Body test 1', 'test', 'low', NOW()),
    ('test_002', 'test@example.com', 'Test Email 2', 'Body test 2', 'test', 'medium', NOW()),
    ('test_003', 'test@example.com', 'Test Email 3', 'Body test 3', 'test', 'high', NOW());

-- Insérer documents de test
INSERT INTO ingestion.documents (filename, path, doc_type, category, created_at)
VALUES
    ('test_doc_001.pdf', '/test/doc1.pdf', 'facture', 'finance', NOW()),
    ('test_doc_002.pdf', '/test/doc2.pdf', 'contrat', 'legal', NOW());

-- Insérer receipts de test (Trust Layer)
INSERT INTO core.action_receipts (module, action_type, trust_level, input_summary, output_summary, confidence, status)
VALUES
    ('email', 'classify', 'auto', 'Test email 1', 'Category: test', 0.95, 'auto'),
    ('archiviste', 'rename', 'propose', 'Test doc 1', 'Renamed to: test_doc_001.pdf', 0.88, 'pending');
EOF

echo -e "${GREEN}✅ 3 emails + 2 documents + 2 receipts créés${NC}"

# Compter données insérées
EMAIL_COUNT=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM ingestion.emails WHERE message_id LIKE 'test_%';" | tr -d ' ')
DOC_COUNT=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM ingestion.documents WHERE filename LIKE 'test_%';" | tr -d ' ')
RECEIPT_COUNT=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM core.action_receipts WHERE input_summary LIKE 'Test%';" | tr -d ' ')

echo "   Emails de test: $EMAIL_COUNT"
echo "   Documents de test: $DOC_COUNT"
echo "   Receipts de test: $RECEIPT_COUNT"

#############################################
# ÉTAPE 2: Backup PostgreSQL
#############################################
echo ""
echo -e "${YELLOW}[2/6] Backup PostgreSQL...${NC}"

BACKUP_FILE="$TEST_BACKUP_DIR/postgres_test_$(date +%Y%m%d_%H%M%S).dump"

docker exec "$POSTGRES_CONTAINER" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c -f "/tmp/test_backup.dump" \
    || error_exit "Échec pg_dump"

docker cp "$POSTGRES_CONTAINER:/tmp/test_backup.dump" "$BACKUP_FILE" \
    || error_exit "Échec copie backup"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo -e "${GREEN}✅ Backup créé: $BACKUP_FILE ($BACKUP_SIZE)${NC}"

# Vérifier taille backup (doit être >10 KB)
BACKUP_SIZE_KB=$(du -k "$BACKUP_FILE" | cut -f1)
if [ "$BACKUP_SIZE_KB" -lt 10 ]; then
    error_exit "Backup trop petit ($BACKUP_SIZE_KB KB < 10 KB) - potentiellement incomplet"
fi

#############################################
# ÉTAPE 3: [D19] pgvector sauvegardé avec PostgreSQL
# Qdrant retiré (D19) - embeddings dans knowledge.embeddings via pgvector
# Sauvegardé automatiquement par pg_dump à l'étape 2
#############################################
echo ""
echo -e "${GREEN}[3/6] pgvector (D19) - inclus dans backup PostgreSQL${NC}"

#############################################
# ÉTAPE 4: Wipe données (simulation disaster)
#############################################
echo ""
echo -e "${YELLOW}[4/6] Suppression données (simulation disaster)...${NC}"

docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<EOF || error_exit "Échec suppression données"
DELETE FROM ingestion.emails WHERE message_id LIKE 'test_%';
DELETE FROM ingestion.documents WHERE filename LIKE 'test_%';
DELETE FROM core.action_receipts WHERE input_summary LIKE 'Test%';
EOF

# Vérifier suppression
EMAIL_COUNT_AFTER=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM ingestion.emails WHERE message_id LIKE 'test_%';" | tr -d ' ')
DOC_COUNT_AFTER=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM ingestion.documents WHERE filename LIKE 'test_%';" | tr -d ' ')

if [ "$EMAIL_COUNT_AFTER" -ne 0 ] || [ "$DOC_COUNT_AFTER" -ne 0 ]; then
    error_exit "Suppression données incomplète (emails: $EMAIL_COUNT_AFTER, docs: $DOC_COUNT_AFTER)"
fi

echo -e "${GREEN}✅ Données supprimées (simulation disaster recovery)${NC}"

#############################################
# ÉTAPE 5: Restaurer backup
#############################################
echo ""
echo -e "${YELLOW}[5/6] Restauration backup PostgreSQL...${NC}"

# Copier backup dans container
docker cp "$BACKUP_FILE" "$POSTGRES_CONTAINER:/tmp/test_restore.dump" \
    || error_exit "Échec copie backup vers container"

# Restaurer (avec --clean pour éviter conflits)
docker exec "$POSTGRES_CONTAINER" pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/test_restore.dump \
    || echo "⚠️ pg_restore warnings (peut être normal pour certaines tables système)"

echo -e "${GREEN}✅ Backup restauré${NC}"

#############################################
# ÉTAPE 6: Vérifier intégrité données
#############################################
echo ""
echo -e "${YELLOW}[6/6] Vérification intégrité données restaurées...${NC}"

# Compter données restaurées
EMAIL_COUNT_RESTORED=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM ingestion.emails WHERE message_id LIKE 'test_%';" | tr -d ' ')
DOC_COUNT_RESTORED=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM ingestion.documents WHERE filename LIKE 'test_%';" | tr -d ' ')
RECEIPT_COUNT_RESTORED=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM core.action_receipts WHERE input_summary LIKE 'Test%';" | tr -d ' ')

echo "   Emails restaurés: $EMAIL_COUNT_RESTORED / $EMAIL_COUNT"
echo "   Documents restaurés: $DOC_COUNT_RESTORED / $DOC_COUNT"
echo "   Receipts restaurés: $RECEIPT_COUNT_RESTORED / $RECEIPT_COUNT"

# Vérifier intégrité
ERRORS=0

if [ "$EMAIL_COUNT_RESTORED" -ne "$EMAIL_COUNT" ]; then
    echo -e "${RED}❌ Emails manquants après restauration ($EMAIL_COUNT_RESTORED != $EMAIL_COUNT)${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [ "$DOC_COUNT_RESTORED" -ne "$DOC_COUNT" ]; then
    echo -e "${RED}❌ Documents manquants après restauration ($DOC_COUNT_RESTORED != $DOC_COUNT)${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [ "$RECEIPT_COUNT_RESTORED" -ne "$RECEIPT_COUNT" ]; then
    echo -e "${RED}❌ Receipts manquants après restauration ($RECEIPT_COUNT_RESTORED != $RECEIPT_COUNT)${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Vérifier contenu spécifique (exemple: un email)
# Note: on utilise trim() SQL au lieu de tr -d pour préserver le contenu original
TEST_EMAIL=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT trim(subject) FROM ingestion.emails WHERE message_id='test_001';" | xargs)
if [ "$TEST_EMAIL" != "Test Email 1" ]; then
    echo -e "${RED}❌ Contenu email incorrect après restauration (got: '$TEST_EMAIL', expected: 'Test Email 1')${NC}"
    ERRORS=$((ERRORS + 1))
fi

# FIX M3: Vérifier healthcheck services avec HTTP 200 validation
echo -e "${YELLOW}Testing services healthcheck...${NC}"
if command -v curl &> /dev/null; then
    HEALTHCHECK_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health || echo "000")
    if [ "$HEALTHCHECK_STATUS" = "200" ]; then
        echo -e "${GREEN}✅ Gateway healthcheck: HTTP 200${NC}"
    else
        echo -e "${RED}❌ Gateway healthcheck failed: HTTP $HEALTHCHECK_STATUS${NC}"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${YELLOW}⚠️  curl not found - skipping healthcheck test${NC}"
fi

#############################################
# RÉSULTAT FINAL
#############################################
echo ""
echo -e "${YELLOW}========================================${NC}"

if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}✅ TEST BACKUP & RESTORE : SUCCÈS${NC}"
    echo -e "${GREEN}   Toutes les données restaurées avec succès${NC}"
    EXIT_CODE=0
else
    echo -e "${RED}❌ TEST BACKUP & RESTORE : ÉCHEC${NC}"
    echo -e "${RED}   $ERRORS erreur(s) détectée(s)${NC}"
    EXIT_CODE=1
fi

echo -e "${YELLOW}========================================${NC}"

#############################################
# NETTOYAGE FINAL
#############################################
echo ""
echo -e "${YELLOW}Nettoyage données de test...${NC}"

docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<EOF
DELETE FROM ingestion.emails WHERE message_id LIKE 'test_%';
DELETE FROM ingestion.documents WHERE filename LIKE 'test_%';
DELETE FROM core.action_receipts WHERE input_summary LIKE 'Test%';
EOF

echo -e "${GREEN}✅ Données de test supprimées${NC}"

exit $EXIT_CODE
