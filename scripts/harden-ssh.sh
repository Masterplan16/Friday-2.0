#!/usr/bin/env bash
# Friday 2.0 - SSH Hardening & Firewall Configuration
# Story 1.4 - AC#1 (SSH Tailscale only), AC#6 (no public ports)
#
# Usage: sudo bash scripts/harden-ssh.sh
# Target: Ubuntu 22.04 (VPS OVH)
#
# Prerequisites:
#   - Tailscale installed and connected (run setup-tailscale.sh first)
#   - SSH working via Tailscale IP BEFORE running this script
#
# WARNING: This script restricts SSH to Tailscale only.
#          Ensure Tailscale SSH connectivity works before running!

set -euo pipefail

SSHD_CONFIG="/etc/ssh/sshd_config"
SSHD_CONFIG_BACKUP="${SSHD_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"

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

# Step 0: Verify Tailscale is running
log "Checking Tailscale status..."
if ! command -v tailscale &>/dev/null; then
    error_exit "Tailscale not installed. Run setup-tailscale.sh first"
fi

TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
if [[ -z "${TAILSCALE_IP}" ]]; then
    error_exit "Cannot get Tailscale IP. Is Tailscale connected?"
fi

log "Tailscale IP detected: ${TAILSCALE_IP}"

# Step 1: Verify SSH works via Tailscale before hardening
log "IMPORTANT: Verify SSH works via Tailscale IP ${TAILSCALE_IP} before continuing"
log "From your PC, test: ssh root@${TAILSCALE_IP}"
read -r -p "Have you verified SSH via Tailscale works? (yes/no): " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
    error_exit "Aborted. Verify Tailscale SSH connectivity first"
fi

# Step 2: Backup sshd_config
log "Backing up ${SSHD_CONFIG} to ${SSHD_CONFIG_BACKUP}"
cp "${SSHD_CONFIG}" "${SSHD_CONFIG_BACKUP}"

# Step 3: Configure SSH to listen only on Tailscale IP
log "Configuring SSH to listen on Tailscale IP only..."

# Remove existing ListenAddress lines and add Tailscale-only
if grep -q "^ListenAddress" "${SSHD_CONFIG}"; then
    sed -i "s/^ListenAddress .*/ListenAddress ${TAILSCALE_IP}/" "${SSHD_CONFIG}"
elif grep -q "^#ListenAddress" "${SSHD_CONFIG}"; then
    sed -i "s/^#ListenAddress .*/ListenAddress ${TAILSCALE_IP}/" "${SSHD_CONFIG}"
else
    echo "ListenAddress ${TAILSCALE_IP}" >> "${SSHD_CONFIG}"
fi

# Disable password authentication (key-based only recommended)
log "Hardening SSH settings..."
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin prohibit-password/' "${SSHD_CONFIG}"
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' "${SSHD_CONFIG}"
sed -i 's/^#\?X11Forwarding .*/X11Forwarding no/' "${SSHD_CONFIG}"

# Validate sshd config before applying
log "Validating SSH config..."
if ! sshd -t; then
    log "SSH config validation failed! Restoring backup..."
    cp "${SSHD_CONFIG_BACKUP}" "${SSHD_CONFIG}"
    error_exit "Invalid sshd_config. Backup restored"
fi

# Step 4: Configure UFW firewall
log "Configuring UFW firewall..."

# Install UFW if not present
if ! command -v ufw &>/dev/null; then
    apt-get install -y ufw
fi

# Allow Tailscale interface (required for all VPN traffic including SSH)
ufw allow in on tailscale0

# Block SSH from public Internet (tailscale0 rule above covers SSH via VPN)
ufw deny 22/tcp

# Enable UFW (non-interactive)
echo "y" | ufw enable

# Step 5: Restart SSH service
log "Restarting SSH service..."
systemctl restart sshd

# Step 6: Post-hardening verification
log "Running post-hardening verification..."

# Verify SSH is listening on Tailscale IP only
LISTEN_ADDR=$(ss -tlnp | grep ":22 " | awk '{print $4}' || echo "unknown")
log "SSH listening on: ${LISTEN_ADDR}"

# Verify UFW rules
log "UFW status:"
ufw status numbered

log ""
log "SSH hardening complete!"
log "  SSH listens on: ${TAILSCALE_IP}:22 only"
log "  UFW: Tailscale SSH allowed, public SSH denied"
log ""
log "VERIFICATION STEPS:"
log "  1. From PC via Tailscale: ssh user@${TAILSCALE_IP} (should work)"
log "  2. From public IP: ssh user@<PUBLIC_IP> (should timeout/refuse)"
log ""
log "If locked out, use OVH console to restore: cp ${SSHD_CONFIG_BACKUP} ${SSHD_CONFIG}"
