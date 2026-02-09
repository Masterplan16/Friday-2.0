#!/usr/bin/env bash
# Friday 2.0 - Tailscale VPN Installation Script
# Story 1.4 - AC#5 (hostname friday-vps), AC#10 (automated install)
#
# Usage: sudo bash scripts/setup-tailscale.sh
# Target: Ubuntu 22.04 (VPS OVH)
#
# Prerequisites:
#   - Root or sudo access
#   - Internet connectivity (for package download)
#
# Post-install manual steps (Tailscale dashboard):
#   - Approve device in https://login.tailscale.com/admin/machines
#   - Enable 2FA (Settings > Auth > Two-factor authentication)
#   - Enable Device Authorization (Settings > Keys)
#   - Set Key Expiry to 90 days (Settings > Keys)

set -euo pipefail

TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-friday-vps}"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $1"
}

error_exit() {
    log "ERROR: $1"
    exit 1
}

# Check root privileges
if [[ $EUID -ne 0 ]]; then
    error_exit "This script must be run as root (use sudo)"
fi

# Check OS compatibility
if [[ ! -f /etc/os-release ]]; then
    error_exit "Cannot detect OS version"
fi

source /etc/os-release
if [[ "${ID}" != "ubuntu" ]]; then
    error_exit "This script is designed for Ubuntu. Detected: ${ID}"
fi

# Auto-detect Ubuntu codename (jammy=22.04, noble=24.04, etc.)
UBUNTU_CODENAME="${VERSION_CODENAME:-}"
if [[ -z "${UBUNTU_CODENAME}" ]]; then
    error_exit "Cannot detect Ubuntu codename from /etc/os-release"
fi

log "Starting Tailscale installation on ${PRETTY_NAME} (${UBUNTU_CODENAME})"

# Step 1: Add Tailscale repository
log "Adding Tailscale repository..."
curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${UBUNTU_CODENAME}.noarmor.gpg" \
    | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null

curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${UBUNTU_CODENAME}.tailscale-list" \
    | tee /etc/apt/sources.list.d/tailscale.list >/dev/null

# Step 2: Install Tailscale
log "Installing Tailscale..."
apt-get update -qq
apt-get install -y tailscale

# Step 3: Enable tailscaled at boot
log "Enabling tailscaled service at boot..."
systemctl enable tailscaled
systemctl start tailscaled

# Step 4: Connect with hostname
# Note: tailscale up is interactive (opens browser URL for auth).
# For fully non-interactive install (CI/CD), use: --auth-key=tskey-auth-xxxxx
log "Connecting to Tailscale with hostname: ${TAILSCALE_HOSTNAME}"
tailscale up --hostname "${TAILSCALE_HOSTNAME}"

# Step 5: Post-install verification
log "Verifying Tailscale installation..."

if ! tailscale status >/dev/null 2>&1; then
    error_exit "Tailscale status check failed"
fi

TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
TAILSCALE_STATUS=$(tailscale status --json 2>/dev/null | grep -o '"BackendState":"[^"]*"' | cut -d'"' -f4 || echo "unknown")

log "Tailscale installation complete!"
log "  Hostname: ${TAILSCALE_HOSTNAME}"
log "  Tailscale IP: ${TAILSCALE_IP}"
log "  Backend State: ${TAILSCALE_STATUS}"
log ""
log "MANUAL STEPS REQUIRED (Tailscale Dashboard):"
log "  1. Approve device: https://login.tailscale.com/admin/machines"
log "  2. Enable 2FA: Settings > Auth > Two-factor authentication"
log "  3. Enable Device Authorization: Settings > Keys"
log "  4. Set Key Expiry to 90 days: Machines > ${TAILSCALE_HOSTNAME} > Key expiry"
log "  5. Save 2FA recovery codes in password manager"
