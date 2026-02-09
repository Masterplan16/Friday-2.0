#!/usr/bin/env bash
# Friday 2.0 - SOPS/age Workflow Validation Script
# Story 1.4 - AC#8 (workflow secrets age/SOPS fonctionnel)
#
# Usage: bash scripts/test-sops-workflow.sh
#
# Prerequisites:
#   - age installed (https://github.com/FiloSottile/age)
#   - sops installed (https://github.com/getsops/sops)
#
# This script tests the complete encrypt/decrypt roundtrip:
#   1. Generates a temporary age keypair
#   2. Creates a test .env file with known content
#   3. Encrypts with sops
#   4. Decrypts with sops
#   5. Verifies roundtrip integrity
#   6. Cleans up all temporary files

set -euo pipefail

TEMP_DIR=""
TEST_PASSED=0
TEST_FAILED=0

log() {
    echo "[SOPS-TEST] $1"
}

cleanup() {
    if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
        rm -rf "${TEMP_DIR}"
        log "Cleaned up temporary files"
    fi
}
trap cleanup EXIT

fail() {
    log "FAIL: $1"
    TEST_FAILED=$((TEST_FAILED + 1))
}

pass() {
    log "PASS: $1"
    TEST_PASSED=$((TEST_PASSED + 1))
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."

    if command -v age &>/dev/null; then
        pass "age is installed ($(age --version 2>&1 || echo 'unknown version'))"
    else
        fail "age is not installed"
        log "Install: https://github.com/FiloSottile/age#installation"
        return 1
    fi

    if command -v sops &>/dev/null; then
        pass "sops is installed ($(sops --version 2>&1 || echo 'unknown version'))"
    else
        fail "sops is not installed"
        log "Install: https://github.com/getsops/sops#install"
        return 1
    fi

    return 0
}

# Test 1: Generate age keypair
test_keygen() {
    log "Test: Generate age keypair..."
    TEMP_DIR=$(mktemp -d)
    AGE_KEY_FILE="${TEMP_DIR}/test-key.txt"

    age-keygen -o "${AGE_KEY_FILE}" 2>/dev/null
    if [[ -f "${AGE_KEY_FILE}" ]]; then
        AGE_PUBLIC_KEY=$(grep -o 'age1[a-z0-9]*' "${AGE_KEY_FILE}" | head -1)
        if [[ -n "${AGE_PUBLIC_KEY}" ]]; then
            pass "age keypair generated (public key: ${AGE_PUBLIC_KEY:0:20}...)"
        else
            fail "Could not extract public key from generated keypair"
            return 1
        fi
    else
        fail "age-keygen did not create key file"
        return 1
    fi
}

# Test 2: Create test .env and encrypt
test_encrypt() {
    log "Test: Encrypt .env with SOPS..."

    if [[ -z "${AGE_KEY_FILE:-}" || -z "${AGE_PUBLIC_KEY:-}" ]]; then
        fail "Skipping encrypt: keygen did not complete"
        return 1
    fi

    # Create test .env content
    TEST_ENV_FILE="${TEMP_DIR}/test.env"
    cat > "${TEST_ENV_FILE}" <<'ENVEOF'
# Test environment file
DATABASE_URL=postgresql://user:password@localhost:5432/testdb
API_KEY=sk-test-1234567890abcdef
SECRET_TOKEN=super_secret_value_123
ENVEOF

    # Create temporary .sops.yaml for this test
    SOPS_CONFIG="${TEMP_DIR}/.sops.yaml"
    cat > "${SOPS_CONFIG}" <<SOPSEOF
creation_rules:
  - path_regex: \.env\.enc$
    age: ${AGE_PUBLIC_KEY}
SOPSEOF

    # Encrypt
    ENCRYPTED_FILE="${TEMP_DIR}/test.env.enc"
    export SOPS_AGE_KEY_FILE="${AGE_KEY_FILE}"

    if sops --config "${SOPS_CONFIG}" -e "${TEST_ENV_FILE}" > "${ENCRYPTED_FILE}" 2>/dev/null; then
        if [[ -s "${ENCRYPTED_FILE}" ]]; then
            pass "File encrypted successfully"
        else
            fail "Encrypted file is empty"
            return 1
        fi
    else
        fail "sops encryption failed"
        return 1
    fi

    # Verify encrypted file does NOT contain plaintext secrets
    if grep -q "super_secret_value_123" "${ENCRYPTED_FILE}"; then
        fail "Encrypted file contains plaintext secret (encryption may have failed)"
        return 1
    else
        pass "Encrypted file does not contain plaintext secrets"
    fi
}

# Test 3: Decrypt and verify roundtrip
test_decrypt() {
    log "Test: Decrypt and verify roundtrip..."

    if [[ -z "${ENCRYPTED_FILE:-}" || ! -f "${ENCRYPTED_FILE:-/nonexistent}" ]]; then
        fail "Skipping decrypt: encrypt did not complete"
        return 1
    fi

    DECRYPTED_FILE="${TEMP_DIR}/test.env.decrypted"
    export SOPS_AGE_KEY_FILE="${AGE_KEY_FILE}"

    if sops --config "${SOPS_CONFIG}" -d "${ENCRYPTED_FILE}" > "${DECRYPTED_FILE}" 2>/dev/null; then
        pass "File decrypted successfully"
    else
        fail "sops decryption failed"
        return 1
    fi

    # Verify content matches original
    if diff -q "${TEST_ENV_FILE}" "${DECRYPTED_FILE}" >/dev/null 2>&1; then
        pass "Roundtrip integrity verified (original == decrypted)"
    else
        fail "Decrypted content does not match original"
        log "--- Original ---"
        cat "${TEST_ENV_FILE}"
        log "--- Decrypted ---"
        cat "${DECRYPTED_FILE}"
        return 1
    fi
}

# Test 4: Verify .sops.yaml project config
test_project_sops_config() {
    log "Test: Verify project .sops.yaml..."

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_SOPS="${SCRIPT_DIR}/../.sops.yaml"

    if [[ -f "${PROJECT_SOPS}" ]]; then
        pass ".sops.yaml exists in project root"
    else
        fail ".sops.yaml not found in project root"
        return 1
    fi

    if grep -q "creation_rules" "${PROJECT_SOPS}"; then
        pass ".sops.yaml has creation_rules section"
    else
        fail ".sops.yaml missing creation_rules"
    fi

    if grep -q 'path_regex.*\.env\.enc' "${PROJECT_SOPS}"; then
        pass ".sops.yaml has .env.enc path regex"
    else
        fail ".sops.yaml missing .env.enc path regex"
    fi
}

# Test 5: Verify .gitignore excludes sensitive files
test_gitignore() {
    log "Test: Verify .gitignore security..."

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    GITIGNORE="${SCRIPT_DIR}/../.gitignore"

    if [[ -f "${GITIGNORE}" ]]; then
        if grep -q "^\.env$" "${GITIGNORE}" || grep -q "^\.env\b" "${GITIGNORE}"; then
            pass ".gitignore excludes .env"
        else
            fail ".gitignore does not exclude .env"
        fi

        if grep -q "credentials\.json" "${GITIGNORE}"; then
            pass ".gitignore excludes credentials.json"
        else
            fail ".gitignore does not exclude credentials.json"
        fi

        if grep -q "\*\.key" "${GITIGNORE}"; then
            pass ".gitignore excludes *.key files"
        else
            fail ".gitignore does not exclude *.key files"
        fi
    else
        fail ".gitignore not found"
    fi
}

# Main
log "========================================="
log "Friday 2.0 - SOPS/age Workflow Test"
log "========================================="

if ! check_prerequisites; then
    log ""
    log "Prerequisites not met. Install age and sops first."
    log "Results: ${TEST_PASSED} passed, ${TEST_FAILED} failed"
    exit 1
fi

test_keygen || true
test_encrypt || true
test_decrypt || true
test_project_sops_config || true
test_gitignore || true

log ""
log "========================================="
log "Results: ${TEST_PASSED} passed, ${TEST_FAILED} failed"
log "========================================="

if [[ ${TEST_FAILED} -gt 0 ]]; then
    exit 1
fi

log "All SOPS/age workflow tests passed!"
exit 0
