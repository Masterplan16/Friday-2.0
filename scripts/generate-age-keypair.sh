#!/bin/bash
# Friday 2.0 - Génération keypair age pour backups chiffrés
# Story 1.12 - Task 1.2
# ATTENTION: Ce script génère une clé privée SENSIBLE - à exécuter UNE SEULE FOIS

set -euo pipefail

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "═══════════════════════════════════════════════════"
echo "   Friday 2.0 - Génération Keypair age"
echo "   Story 1.12 - Backup Chiffré"
echo "═══════════════════════════════════════════════════"
echo ""

# Vérifier que age-keygen est installé
if ! command -v age-keygen &> /dev/null; then
    echo -e "${RED}❌ ERREUR: age-keygen non trouvé${NC}"
    echo ""
    echo "Installation requise:"
    echo "  - macOS: brew install age"
    echo "  - Ubuntu: apt install age"
    echo "  - Windows: choco install age ou télécharger depuis GitHub"
    echo ""
    echo "Source: https://github.com/FiloSottile/age/releases"
    exit 1
fi

echo -e "${GREEN}✅ age-keygen trouvé${NC}"
AGE_VERSION=$(age --version 2>&1 || echo "unknown")
echo "   Version: $AGE_VERSION"
echo ""

# Avertissement sécurité
echo -e "${YELLOW}⚠️  AVERTISSEMENT SÉCURITÉ${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Ce script va générer:"
echo "  1. Une clé PUBLIQUE (à stocker sur VPS dans .env.enc)"
echo "  2. Une clé PRIVÉE (à stocker SUR PC UNIQUEMENT)"
echo ""
echo -e "${RED}CRITIQUE:${NC} La clé privée NE DOIT JAMAIS être:"
echo "  ❌ Commitée dans git"
echo "  ❌ Stockée sur le VPS"
echo "  ❌ Partagée par email/Slack"
echo "  ❌ Stockée en clair sur disque non chiffré"
echo ""
echo -e "${GREEN}La clé privée DOIT être:${NC}"
echo "  ✅ Stockée sur PC dans ~/.age/key.txt"
echo "  ✅ Permissions 600 (chmod 600)"
echo "  ✅ Sur partition chiffrée (BitLocker/LUKS/FileVault)"
echo "  ✅ Backupée dans password manager (optionnel mais recommandé)"
echo ""

read -p "Continuer? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Opération annulée."
    exit 0
fi

# Dossier de destination
KEY_DIR="$HOME/.age"
KEY_FILE="$KEY_DIR/friday-backup-key.txt"

# Créer dossier si inexistant
if [ ! -d "$KEY_DIR" ]; then
    echo ""
    echo "Création du dossier $KEY_DIR..."
    mkdir -p "$KEY_DIR"
    chmod 700 "$KEY_DIR"
fi

# Vérifier si une clé existe déjà
if [ -f "$KEY_FILE" ]; then
    echo ""
    echo -e "${YELLOW}⚠️  Une clé existe déjà: $KEY_FILE${NC}"
    echo ""
    read -p "Écraser la clé existante? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Opération annulée. Clé existante conservée."
        exit 0
    fi
fi

# Générer keypair
echo ""
echo "Génération du keypair age..."
age-keygen -o "$KEY_FILE"

# Sécuriser permissions
chmod 600 "$KEY_FILE"

echo ""
echo -e "${GREEN}✅ Keypair généré avec succès!${NC}"
echo "═══════════════════════════════════════════════════"
echo ""

# Extraire clé publique
PUBLIC_KEY=$(grep "# public key:" "$KEY_FILE" | cut -d: -f2 | tr -d ' ')

echo -e "${BLUE}📋 CLÉ PUBLIQUE (à copier dans .env.enc sur VPS):${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "AGE_PUBLIC_KEY=\"$PUBLIC_KEY\""
echo ""
echo "═══════════════════════════════════════════════════"
echo ""

echo -e "${YELLOW}🔒 CLÉ PRIVÉE (stockée localement):${NC}"
echo "═══════════════════════════════════════════════════"
echo "Fichier: $KEY_FILE"
echo "Permissions: $(stat -c "%a" "$KEY_FILE" 2>/dev/null || stat -f "%A" "$KEY_FILE" 2>/dev/null || echo "600")"
echo ""
echo -e "${RED}⚠️  NE JAMAIS partager ou commiter cette clé privée!${NC}"
echo ""

# Instructions suivantes
echo "═══════════════════════════════════════════════════"
echo -e "${GREEN}PROCHAINES ÉTAPES:${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "1. Copier la clé publique ci-dessus"
echo ""
echo "2. Sur le VPS, éditer .env.enc avec SOPS:"
echo "   $ sops .env.enc"
echo ""
echo "3. Ajouter la ligne:"
echo "   AGE_PUBLIC_KEY=\"$PUBLIC_KEY\""
echo ""
echo "4. Vérifier que la clé privée n'est PAS sur VPS:"
echo "   $ git grep -i \"AGE-SECRET-KEY\"  # Doit retourner 0 résultats"
echo ""
echo "5. Tester le chiffrement:"
echo "   $ echo \"test\" | age -r \"$PUBLIC_KEY\" > test.age"
echo "   $ age -d -i $KEY_FILE test.age  # Doit afficher: test"
echo ""
echo "═══════════════════════════════════════════════════"
echo ""
echo -e "${GREEN}✅ Setup keypair age terminé!${NC}"
echo ""
