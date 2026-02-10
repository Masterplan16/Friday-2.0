#!/bin/bash
# Friday 2.0 - Script de build image n8n custom avec age CLI
# Story 1.12 - Task 1.1
# Construit l'image n8n custom et vérifie l'installation

set -euo pipefail

echo "🔨 Construction de l'image n8n custom avec age CLI..."

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Vérifier que Dockerfile.n8n existe
if [ ! -f "Dockerfile.n8n" ]; then
    echo "❌ ERREUR: Dockerfile.n8n non trouvé"
    echo "   Assurez-vous d'être à la racine du projet Friday 2.0"
    exit 1
fi

# Build l'image
echo ""
echo "Construction de l'image (cela peut prendre quelques minutes)..."
docker build -f Dockerfile.n8n -t friday-n8n:custom .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Image construite avec succès: friday-n8n:custom${NC}"
else
    echo "❌ Échec de la construction"
    exit 1
fi

# Vérifier l'image
echo ""
echo "Vérification de l'image construite..."
docker run --rm friday-n8n:custom age --version

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ age CLI fonctionnel dans l'image${NC}"
else
    echo "❌ age CLI non fonctionnel"
    exit 1
fi

# Afficher les labels
echo ""
echo "Labels de l'image:"
docker inspect friday-n8n:custom | grep -A 5 "Labels"

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "${GREEN}✅ BUILD RÉUSSI${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Image prête: friday-n8n:custom"
echo ""
echo -e "${YELLOW}Note:${NC} docker-compose utilisera cette image automatiquement"
echo "       lors du prochain: docker compose up --build n8n"
echo ""
