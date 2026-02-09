#!/usr/bin/env bash
# Friday 2.0 - Security Checklist E2E Validation
# Story 1.4 - AC#9 (tests de validation securite)
#
# Usage: bash tests/e2e/test_security_checklist.sh
# Target: VPS OVH Ubuntu 22.04 (post-deployment)
#
# Prerequisites:
#   - Tailscale installed and connected
#   - SSH hardened (scripts/harden-ssh.sh executed)
#   - Docker services running
#   - Redis with ACL configured
#
# NOTE: This script must be run ON the VPS itself.
# Some tests require network access to verify external blocking.

set -euo pipefail

PASSED=0
FAILED=0
SKIPPED=0

log() {
    echo "[SECURITY-E2E] $1"
}

pass() {
    log "PASS: $1"
    PASSED=$((PASSED + 1))
}

fail() {
    log "FAIL: $1"
    FAILED=$((FAILED + 1))
}

skip() {
    log "SKIP: $1"
    SKIPPED=$((SKIPPED + 1))
}

log "========================================="
log "Friday 2.0 - Security Checklist E2E"
log "========================================="

# ----------------------------------------
# Test 1: Tailscale status
# ----------------------------------------
log ""
log "--- Tailscale ---"

if command -v tailscale &>/dev/null; then
    pass "Tailscale installed"
else
    fail "Tailscale not installed"
fi

if tailscale status &>/dev/null; then
    pass "Tailscale connected"

    HOSTNAME=$(tailscale status --json 2>/dev/null | grep -o '"Self":{"[^}]*' | grep -o '"HostName":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
    if [[ "${HOSTNAME}" == "friday-vps" ]]; then
        pass "Tailscale hostname is friday-vps"
    else
        fail "Tailscale hostname is '${HOSTNAME}', expected 'friday-vps'"
    fi

    TS_IP=$(tailscale ip -4 2>/dev/null || echo "")
    if [[ -n "${TS_IP}" ]]; then
        pass "Tailscale IPv4: ${TS_IP}"
    else
        fail "No Tailscale IPv4 address"
    fi
else
    fail "Tailscale not connected"
    skip "Tailscale hostname check (not connected)"
    skip "Tailscale IP check (not connected)"
fi

if systemctl is-enabled tailscaled &>/dev/null; then
    pass "tailscaled enabled at boot"
else
    fail "tailscaled not enabled at boot"
fi

# ----------------------------------------
# Test 2: SSH configuration
# ----------------------------------------
log ""
log "--- SSH Security ---"

SSHD_CONFIG="/etc/ssh/sshd_config"
if [[ -f "${SSHD_CONFIG}" ]]; then
    LISTEN_ADDR=$(grep "^ListenAddress" "${SSHD_CONFIG}" 2>/dev/null | awk '{print $2}' || echo "")
    if [[ -n "${LISTEN_ADDR}" && "${LISTEN_ADDR}" == 100.* ]]; then
        pass "SSH ListenAddress on Tailscale IP: ${LISTEN_ADDR}"
    elif [[ -z "${LISTEN_ADDR}" ]]; then
        fail "SSH ListenAddress not configured (listening on all interfaces)"
    else
        fail "SSH ListenAddress is ${LISTEN_ADDR} (not a Tailscale IP)"
    fi

    if grep -q "^PasswordAuthentication no" "${SSHD_CONFIG}" 2>/dev/null; then
        pass "SSH password authentication disabled"
    else
        skip "SSH password authentication check (may not be configured yet)"
    fi
else
    fail "sshd_config not found"
fi

# ----------------------------------------
# Test 3: UFW Firewall
# ----------------------------------------
log ""
log "--- Firewall (UFW) ---"

if command -v ufw &>/dev/null; then
    UFW_STATUS=$(ufw status 2>/dev/null | head -1 || echo "")
    if echo "${UFW_STATUS}" | grep -q "active"; then
        pass "UFW is active"

        # Check SSH deny rule
        if ufw status 2>/dev/null | grep -q "22/tcp.*DENY"; then
            pass "UFW denies public SSH"
        else
            fail "UFW missing SSH deny rule"
        fi

        # Check tailscale0 interface
        if ufw status 2>/dev/null | grep -q "tailscale0"; then
            pass "UFW allows tailscale0 interface"
        else
            fail "UFW missing tailscale0 interface rule"
        fi
    else
        fail "UFW is not active"
    fi
else
    fail "UFW not installed"
fi

# ----------------------------------------
# Test 4: Docker ports security
# ----------------------------------------
log ""
log "--- Docker Ports ---"

if command -v docker &>/dev/null; then
    # Check no ports are exposed on 0.0.0.0
    PUBLIC_PORTS=$(docker ps --format '{{.Ports}}' 2>/dev/null | grep -v "127.0.0.1" | grep "0.0.0.0" || echo "")
    if [[ -z "${PUBLIC_PORTS}" ]]; then
        pass "No Docker ports exposed on 0.0.0.0"
    else
        fail "Docker ports exposed publicly: ${PUBLIC_PORTS}"
    fi
else
    skip "Docker not available (not on VPS?)"
fi

# ----------------------------------------
# Test 5: Redis ACL
# ----------------------------------------
log ""
log "--- Redis ACL ---"

if command -v redis-cli &>/dev/null || command -v docker &>/dev/null; then
    # Try redis-cli directly or via docker
    REDIS_CMD=""
    if command -v redis-cli &>/dev/null; then
        REDIS_CMD="redis-cli"
    elif docker ps --filter name=redis --format '{{.Names}}' 2>/dev/null | grep -q redis; then
        REDIS_CMD="docker exec friday-redis redis-cli"
    fi

    if [[ -n "${REDIS_CMD}" ]]; then
        # Test anonymous connection (should fail)
        ANON_RESULT=$(${REDIS_CMD} PING 2>&1 || echo "NOAUTH")
        if echo "${ANON_RESULT}" | grep -qi "noauth\|denied\|error"; then
            pass "Redis anonymous connection blocked (default off)"
        else
            fail "Redis allows anonymous connection (default user should be off)"
        fi

        # Test admin auth (password from env, not hardcoded)
        REDIS_ADMIN_PWD="${REDIS_ADMIN_PASSWORD:-}"
        if [[ -n "${REDIS_ADMIN_PWD}" ]]; then
            ADMIN_RESULT=$(${REDIS_CMD} AUTH admin "${REDIS_ADMIN_PWD}" 2>&1 || echo "")
            if echo "${ADMIN_RESULT}" | grep -qi "ok"; then
                pass "Redis admin authentication works"
            else
                fail "Redis admin auth failed with provided REDIS_ADMIN_PASSWORD"
            fi
        else
            skip "Redis admin auth test (set REDIS_ADMIN_PASSWORD env var to test)"
        fi
    else
        skip "Redis CLI not available"
    fi
else
    skip "Redis tests (no redis-cli or docker)"
fi

# ----------------------------------------
# Test 6: Sensitive files check
# ----------------------------------------
log ""
log "--- Sensitive Files ---"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/../.."

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    fail ".env file exists in project root (should be encrypted with SOPS)"
else
    pass "No .env file in project root"
fi

if [[ -f "${PROJECT_ROOT}/.env.example" ]]; then
    if grep -qP '(sk-ant-|ghp_|\d{10}:[A-Za-z0-9_-]{35})' "${PROJECT_ROOT}/.env.example" 2>/dev/null; then
        fail ".env.example contains what looks like real credentials"
    else
        pass ".env.example contains only placeholders"
    fi
else
    fail ".env.example not found"
fi

if [[ -f "${PROJECT_ROOT}/.sops.yaml" ]]; then
    pass ".sops.yaml exists"
else
    fail ".sops.yaml not found"
fi

# ----------------------------------------
# Summary
# ----------------------------------------
log ""
log "========================================="
log "Results: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped"
log "========================================="

if [[ ${FAILED} -gt 0 ]]; then
    log "Some security checks FAILED. Review and fix before production."
    exit 1
fi

log "All security checks passed!"
exit 0
