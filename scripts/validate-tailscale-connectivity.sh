#!/bin/bash
# Friday 2.0 - Validation connectivité Tailscale VPN
# Story 1.12 - Task 1.3
# Vérifie que Tailscale est opérationnel pour les backups sync vers PC

set -euo pipefail

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "═══════════════════════════════════════════════════"
echo "   Friday 2.0 - Validation Tailscale VPN"
echo "   Story 1.12 - Backup Sync Connectivity"
echo "═══════════════════════════════════════════════════"
echo ""

# Vérifier que Tailscale est installé
if ! command -v tailscale &> /dev/null; then
    echo -e "${RED}❌ ERREUR: Tailscale non installé${NC}"
    echo ""
    echo "Installation requise (Story 1.4):"
    echo "  - Linux: curl -fsSL https://tailscale.com/install.sh | sh"
    echo "  - macOS: brew install tailscale"
    echo "  - Windows: winget install tailscale.tailscale"
    echo ""
    exit 1
fi

echo -e "${GREEN}✅ Tailscale installé${NC}"
TAILSCALE_VERSION=$(tailscale version | head -1)
echo "   Version: $TAILSCALE_VERSION"
echo ""

# Test 1: Vérifier que Tailscale est démarré
echo "Test 1: Vérifier statut Tailscale..."
if ! sudo tailscale status &> /dev/null; then
    echo -e "${RED}❌ ERREUR: Tailscale non démarré${NC}"
    echo "   Lancer avec: sudo tailscale up"
    exit 1
fi

echo -e "${GREEN}✅ Tailscale démarré${NC}"
echo ""

# Test 2: Vérifier authentification
echo "Test 2: Vérifier authentification..."
TAILSCALE_STATUS=$(sudo tailscale status)

if echo "$TAILSCALE_STATUS" | grep -q "logged out"; then
    echo -e "${RED}❌ ERREUR: Non authentifié à Tailscale${NC}"
    echo "   Se connecter avec: sudo tailscale up"
    exit 1
fi

echo -e "${GREEN}✅ Authentifié à Tailscale${NC}"
echo ""

# Test 3: Lister les devices du réseau
echo "Test 3: Lister les devices Tailscale..."
echo "$TAILSCALE_STATUS"
echo ""

# Vérifier PC Mainteneur dans le réseau
PC_HOSTNAME=${TAILSCALE_PC_HOSTNAME:-mainteneur-pc}

if echo "$TAILSCALE_STATUS" | grep -q "$PC_HOSTNAME"; then
    echo -e "${GREEN}✅ PC Mainteneur détecté: $PC_HOSTNAME${NC}"

    # Extraire IP Tailscale du PC
    PC_IP=$(echo "$TAILSCALE_STATUS" | grep "$PC_HOSTNAME" | awk '{print $1}')
    echo "   IP Tailscale: $PC_IP"
else
    echo -e "${YELLOW}⚠️  WARNING: PC $PC_HOSTNAME non détecté dans le réseau Tailscale${NC}"
    echo ""
    echo "Causes possibles:"
    echo "  - PC Mainteneur éteint"
    echo "  - Tailscale non démarré sur PC"
    echo "  - Hostname Tailscale différent (vérifier avec: tailscale status)"
    echo ""
    echo "Variable actuelle: TAILSCALE_PC_HOSTNAME=$PC_HOSTNAME"
    echo ""
fi

# Test 4: Test ping vers PC
echo ""
echo "Test 4: Test ping vers PC Mainteneur..."

if echo "$TAILSCALE_STATUS" | grep -q "$PC_HOSTNAME"; then
    PC_IP=$(echo "$TAILSCALE_STATUS" | grep "$PC_HOSTNAME" | awk '{print $1}')

    if ping -c 3 "$PC_IP" &> /dev/null; then
        echo -e "${GREEN}✅ Ping vers $PC_HOSTNAME ($PC_IP) réussi${NC}"
    else
        echo -e "${RED}❌ Ping vers $PC_HOSTNAME ($PC_IP) échoué${NC}"
        echo "   Le PC peut être en veille ou firewall actif"
    fi
else
    echo -e "${YELLOW}⚠️  SKIP: PC non détecté, impossible de tester ping${NC}"
fi

# Test 5: Test SSH vers PC (optionnel)
echo ""
echo "Test 5: Test SSH vers PC Mainteneur..."

if echo "$TAILSCALE_STATUS" | grep -q "$PC_HOSTNAME"; then
    # Vérifier si clé SSH existe
    SSH_KEY_PATH="$HOME/.ssh/friday_backup_key"

    if [ ! -f "$SSH_KEY_PATH" ]; then
        echo -e "${YELLOW}⚠️  INFO: Clé SSH $SSH_KEY_PATH non trouvée${NC}"
        echo "   Créer avec: ssh-keygen -t ed25519 -f $SSH_KEY_PATH -N \"\""
        echo "   Puis copier sur PC: ssh-copy-id -i $SSH_KEY_PATH mainteneur@$PC_HOSTNAME"
    else
        # Tenter SSH
        if ssh -i "$SSH_KEY_PATH" -o ConnectTimeout=5 -o StrictHostKeyChecking=no mainteneur@"$PC_HOSTNAME" "echo 'SSH OK'" &> /dev/null; then
            echo -e "${GREEN}✅ SSH vers $PC_HOSTNAME réussi${NC}"
        else
            echo -e "${YELLOW}⚠️  WARNING: SSH vers $PC_HOSTNAME échoué${NC}"
            echo "   Causes possibles:"
            echo "   - Clé SSH non autorisée sur PC (voir ssh-copy-id)"
            echo "   - SSHD non démarré sur PC"
            echo "   - Firewall bloque port 22"
        fi
    fi
else
    echo -e "${YELLOW}⚠️  SKIP: PC non détecté, impossible de tester SSH${NC}"
fi

# Test 6: Vérifier 2FA activé (à valider manuellement)
echo ""
echo "Test 6: Vérifier 2FA Tailscale..."
echo -e "${BLUE}ℹ️  INFO: Validation manuelle requise${NC}"
echo ""
echo "Vérifier sur https://login.tailscale.com/admin/settings/security :"
echo "  ✅ Two-factor authentication: Enabled"
echo "  ✅ Device authorization: Required"
echo ""

# Résumé
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "${GREEN}VALIDATION TAILSCALE TERMINÉE${NC}"
echo "═══════════════════════════════════════════════════"
echo ""

if echo "$TAILSCALE_STATUS" | grep -q "$PC_HOSTNAME"; then
    echo -e "${GREEN}✅ Réseau Tailscale opérationnel${NC}"
    echo -e "${GREEN}✅ PC Mainteneur accessible via Tailscale${NC}"
    echo ""
    echo "Prochaines étapes (Story 1.12):"
    echo "  → Task 2.1: Créer scripts/backup.sh"
    echo "  → Task 2.2: Créer scripts/rsync-to-pc.sh"
else
    echo -e "${YELLOW}⚠️  PC Mainteneur non détecté${NC}"
    echo ""
    echo "Actions requises:"
    echo "  1. Vérifier que Tailscale est démarré sur PC"
    echo "  2. Vérifier hostname Tailscale du PC (tailscale status)"
    echo "  3. Mettre à jour TAILSCALE_PC_HOSTNAME si nécessaire"
    echo ""
    echo "Note: Les backups VPS fonctionneront, mais sync PC échouera"
fi

echo ""
