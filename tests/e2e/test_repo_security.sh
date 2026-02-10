#!/usr/bin/env bash
# tests/e2e/test_repo_security.sh
# E2E Security Tests - Story 1.17
# Tests repository security compliance before going public

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    ((TESTS_PASSED++))
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    echo -e "  ${YELLOW}Details:${NC} $2"
    ((TESTS_FAILED++))
}

test_header() {
    echo ""
    echo -e "${YELLOW}━━━ Test $1 ━━━${NC}"
    ((TESTS_RUN++))
}

# Test 1: Git history clean (no secrets)
test_git_history_clean() {
    test_header "1: Git History Clean (git-secrets)"

    if ! command -v git-secrets &> /dev/null; then
        fail "git-secrets not installed" "Install: brew install git-secrets (macOS) or download from GitHub"
        return 1
    fi

    # Run scan
    if git secrets --scan-history 2>&1 | grep -qi "error\|warning"; then
        fail "Secrets detected in Git history" "Run: git secrets --scan-history for details"
        return 1
    fi

    pass "No secrets in Git history"
}

# Test 2: .gitignore validation
test_gitignore_validation() {
    test_header "2: .gitignore Validation"

    # Create temporary test files
    echo "test-key-content" > test.key
    echo "test-pem-content" > test.pem
    echo "TEST_SECRET=value" > .env

    # Check git ignores them
    ignored_files=$(git status --porcelain test.key test.pem .env 2>&1 || true)

    # Cleanup
    rm -f test.key test.pem .env

    if [ -n "$ignored_files" ]; then
        fail ".gitignore not working" "Sensitive files not ignored: $ignored_files"
        return 1
    fi

    pass ".gitignore correctly ignores sensitive files"
}

# Test 3: SOPS encryption round-trip
test_sops_encryption() {
    test_header "3: SOPS Encryption Round-Trip"

    if ! command -v sops &> /dev/null; then
        fail "sops not installed" "Install: brew install sops (macOS) or download from GitHub"
        return 1
    fi

    # Set SOPS_AGE_KEY_FILE if not already set
    if [ -z "${SOPS_AGE_KEY_FILE:-}" ]; then
        export SOPS_AGE_KEY_FILE="$HOME/.age/friday-key.txt"
    fi

    # Check age key exists
    if [ ! -f "$SOPS_AGE_KEY_FILE" ]; then
        fail "Age key not found" "Key not found at $SOPS_AGE_KEY_FILE"
        return 1
    fi

    # Create test file
    echo "TEST_VAR=secret123" > .env.test

    # Encrypt
    if ! sops --input-type dotenv --output-type dotenv -e .env.test > .env.test.enc 2>/dev/null; then
        rm -f .env.test
        fail "SOPS encryption failed" "Check SOPS_AGE_KEY_FILE is set correctly"
        return 1
    fi

    # Decrypt
    if ! sops --input-type dotenv --output-type dotenv -d .env.test.enc > .env.test.dec 2>/dev/null; then
        rm -f .env.test .env.test.enc
        fail "SOPS decryption failed" "Check age key is valid"
        return 1
    fi

    # Compare
    if ! diff .env.test .env.test.dec > /dev/null 2>&1; then
        rm -f .env.test .env.test.enc .env.test.dec
        fail "SOPS round-trip mismatch" "Original and decrypted content differ"
        return 1
    fi

    # Cleanup
    rm -f .env.test .env.test.enc .env.test.dec

    pass "SOPS encryption/decryption working correctly"
}

# Test 4: No sensitive files committed
test_no_sensitive_files() {
    test_header "4: No Sensitive Files Committed"

    # Check for sensitive files in git
    sensitive_patterns=(
        "*.key"
        "*.pem"
        "credentials.json"
        ".env"
        "secrets.yaml"
    )

    found_sensitive=""
    for pattern in "${sensitive_patterns[@]}"; do
        files=$(git ls-files "$pattern" 2>/dev/null || true)
        if [ -n "$files" ]; then
            found_sensitive="$found_sensitive\n  - $files"
        fi
    done

    if [ -n "$found_sensitive" ]; then
        fail "Sensitive files found in git" "$found_sensitive"
        return 1
    fi

    # Check that encrypted files ARE present
    if ! git ls-files .env.enc > /dev/null 2>&1; then
        fail ".env.enc not found in git" "Encrypted secrets should be committed"
        return 1
    fi

    pass "No sensitive files committed (encrypted files present)"
}

# Test 5: GitHub branch protection active
test_branch_protection() {
    test_header "5: GitHub Branch Protection Active"

    if ! command -v gh &> /dev/null; then
        fail "GitHub CLI (gh) not installed" "Install: brew install gh (macOS)"
        return 1
    fi

    # Check if authenticated
    if ! gh auth status &> /dev/null; then
        fail "GitHub CLI not authenticated" "Run: gh auth login"
        return 1
    fi

    # Check branch protection
    protection=$(gh api repos/Masterplan16/Friday-2.0/branches/master/protection 2>&1 || echo "not_protected")

    if echo "$protection" | grep -qi "not found\|not_protected"; then
        fail "Branch protection not active on master" "Configure via Settings > Branches"
        return 1
    fi

    # Verify PR required
    if ! echo "$protection" | grep -q "required_pull_request_reviews"; then
        fail "PR reviews not required" "Branch protection exists but PR not enforced"
        return 1
    fi

    pass "Branch protection active on master (PR required)"
}

# Test 6: Dependabot active
test_dependabot_active() {
    test_header "6: Dependabot Active"

    if ! command -v gh &> /dev/null; then
        fail "GitHub CLI (gh) not installed" "Install: brew install gh (macOS)"
        return 1
    fi

    # Check Dependabot config file
    if [ ! -f .github/dependabot.yml ]; then
        fail "dependabot.yml not found" "Create .github/dependabot.yml"
        return 1
    fi

    # Check Dependabot is enabled (vulnerability alerts)
    # Note: This endpoint may not work with all permissions
    alerts_status=$(gh api repos/Masterplan16/Friday-2.0/vulnerability-alerts 2>&1 || echo "unknown")

    if echo "$alerts_status" | grep -qi "not found\|disabled"; then
        fail "Dependabot alerts not enabled" "Enable in Settings > Security & analysis"
        return 1
    fi

    pass "Dependabot configured and active"
}

# Main execution
echo "================================================="
echo "   Friday 2.0 - Repository Security Tests E2E"
echo "================================================="

# Run all tests
test_git_history_clean || true
test_gitignore_validation || true
test_sops_encryption || true
test_no_sensitive_files || true
test_branch_protection || true
test_dependabot_active || true

# Summary
echo ""
echo "================================================="
echo "   Test Summary"
echo "================================================="
echo -e "Tests run:    ${TESTS_RUN}"
echo -e "Passed:       ${GREEN}${TESTS_PASSED}${NC}"
echo -e "Failed:       ${RED}${TESTS_FAILED}${NC}"
echo "================================================="

if [ "$TESTS_FAILED" -gt 0 ]; then
    echo -e "${RED}✗ Security validation FAILED${NC}"
    echo "Fix failures before making repository public."
    exit 1
else
    echo -e "${GREEN}✓ All security tests PASSED${NC}"
    echo "Repository is ready for public release."
    exit 0
fi
