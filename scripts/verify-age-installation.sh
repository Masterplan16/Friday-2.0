#!/bin/bash
# Friday 2.0 - Script de vérification installation age CLI
# Story 1.12 - Task 1.1 Subtask 1.1.2
# Vérifie que age est correctement installé dans le container n8n

set -euo pipefail

echo "🔍 Vérification installation age CLI dans container n8n..."

# Couleurs pour output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Vérifier que container n8n existe et tourne
if ! docker ps | grep -q "friday-n8n"; then
    echo -e "${RED}❌ ERREUR: Container friday-n8n n'est pas en cours d'exécution${NC}"
    echo "   Lancez d'abord: docker compose up -d n8n"
    exit 1
fi

echo -e "${GREEN}✅ Container friday-n8n trouvé et actif${NC}"

# Test 1: Vérifier présence de age
echo ""
echo "Test 1: Vérification présence de age..."
if docker exec friday-n8n which age > /dev/null 2>&1; then
    AGE_PATH=$(docker exec friday-n8n which age)
    echo -e "${GREEN}✅ age trouvé: ${AGE_PATH}${NC}"
else
    echo -e "${RED}❌ ERREUR: age non trouvé dans le container${NC}"
    exit 1
fi

# Test 2: Vérifier version age
echo ""
echo "Test 2: Vérification version age..."
AGE_VERSION=$(docker exec friday-n8n age --version 2>&1 || true)

if echo "$AGE_VERSION" | grep -q "v1.3"; then
    echo -e "${GREEN}✅ Version age correcte: ${AGE_VERSION}${NC}"
else
    echo -e "${YELLOW}⚠️  Version age inattendue: ${AGE_VERSION}${NC}"
    echo "   Attendu: v1.3.0 ou supérieur"
fi

# Test 3: Vérifier présence de age-keygen
echo ""
echo "Test 3: Vérification présence de age-keygen..."
if docker exec friday-n8n which age-keygen > /dev/null 2>&1; then
    KEYGEN_PATH=$(docker exec friday-n8n which age-keygen)
    echo -e "${GREEN}✅ age-keygen trouvé: ${KEYGEN_PATH}${NC}"
else
    echo -e "${RED}❌ ERREUR: age-keygen non trouvé${NC}"
    exit 1
fi

# Test 4: Vérifier que age-keygen fonctionne
echo ""
echo "Test 4: Test fonctionnel age-keygen..."
if docker exec friday-n8n age-keygen --help > /dev/null 2>&1; then
    echo -e "${GREEN}✅ age-keygen fonctionnel${NC}"
else
    echo -e "${RED}❌ ERREUR: age-keygen ne répond pas${NC}"
    exit 1
fi

# Test 5: Vérifier permissions du dossier /backups
echo ""
echo "Test 5: Vérification dossier /backups..."
if docker exec friday-n8n test -d /backups; then
    BACKUPS_PERMS=$(docker exec friday-n8n stat -c "%a %U:%G" /backups)
    echo -e "${GREEN}✅ Dossier /backups existe: ${BACKUPS_PERMS}${NC}"

    # Vérifier que l'utilisateur node peut écrire
    if docker exec friday-n8n test -w /backups; then
        echo -e "${GREEN}✅ Permissions écriture OK pour user node${NC}"
    else
        echo -e "${YELLOW}⚠️  Permissions écriture manquantes pour /backups${NC}"
    fi
else
    echo -e "${RED}❌ ERREUR: Dossier /backups n'existe pas${NC}"
    exit 1
fi

# Test 6: Test chiffrement/déchiffrement simple
echo ""
echo "Test 6: Test fonctionnel chiffrement/déchiffrement..."

# Générer keypair temporaire
TEMP_KEY=$(docker exec friday-n8n mktemp)
docker exec friday-n8n age-keygen -o "$TEMP_KEY" > /dev/null 2>&1

# Extraire clé publique
PUBLIC_KEY=$(docker exec friday-n8n grep "# public key:" "$TEMP_KEY" | cut -d: -f2 | tr -d ' ')

# Test données
TEST_DATA="Friday 2.0 backup test"
ENCRYPTED_FILE=$(docker exec friday-n8n mktemp)
DECRYPTED_FILE=$(docker exec friday-n8n mktemp)

# Chiffrer
echo "$TEST_DATA" | docker exec -i friday-n8n age -r "$PUBLIC_KEY" -o "$ENCRYPTED_FILE"

# Déchiffrer
docker exec friday-n8n age -d -i "$TEMP_KEY" "$ENCRYPTED_FILE" > "$DECRYPTED_FILE" 2>&1

# Vérifier
DECRYPTED_DATA=$(docker exec friday-n8n cat "$DECRYPTED_FILE")
if [ "$DECRYPTED_DATA" = "$TEST_DATA" ]; then
    echo -e "${GREEN}✅ Test chiffrement/déchiffrement réussi${NC}"
else
    echo -e "${RED}❌ ERREUR: Échec test chiffrement/déchiffrement${NC}"
    exit 1
fi

# Cleanup
docker exec friday-n8n rm -f "$TEMP_KEY" "$ENCRYPTED_FILE" "$DECRYPTED_FILE"

# Résumé
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "${GREEN}✅ TOUS LES TESTS PASSÉS${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "age CLI est correctement installé et fonctionnel !"
echo "Version: $AGE_VERSION"
echo ""
echo "Prochaines étapes (Story 1.12):"
echo "  → Task 1.2: Générer keypair age pour production"
echo "  → Task 2.1: Créer scripts/backup.sh"
echo ""
