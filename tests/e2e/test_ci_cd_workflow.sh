#!/usr/bin/env bash
# Test E2E - CI/CD Workflow Validation
# Story 1.16 : CI/CD Pipeline GitHub Actions
# Tests tous les AC (Acceptance Criteria) de la story

set -uo pipefail  # Removed -e to continue on failures

# Colors pour output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Compteurs
PASSED=0
FAILED=0

# Functions
pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    ((PASSED++))
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    ((FAILED++))
}

test_file_exists() {
    local file="$1"
    local description="$2"
    if [[ -f "$file" ]]; then
        pass "$description"
        return 0
    else
        fail "$description - File not found: $file"
        return 1
    fi
}

test_file_contains() {
    local file="$1"
    local pattern="$2"
    local description="$3"
    # Use -F for fixed string matching (not regex)
    # Use -- to prevent pattern starting with - from being interpreted as option
    if grep -qF -- "$pattern" "$file" 2>/dev/null; then
        pass "$description"
        return 0
    else
        fail "$description - Pattern not found: $pattern"
        # MEDIUM #11 FIX: Return 1 pour signaler l'échec (mais script continue car set -uo sans -e)
        return 1
    fi
}

# Test Suite
echo "=================================================="
echo "Story 1.16 - CI/CD Pipeline E2E Tests"
echo "=================================================="
echo ""

# AC1: Workflow CI avec 4 jobs
echo "--- AC1: Workflow CI complet avec 4 jobs ---"
test_file_exists ".github/workflows/ci.yml" "AC1.1: Fichier ci.yml existe"
if [[ -f ".github/workflows/ci.yml" ]]; then
    test_file_contains ".github/workflows/ci.yml" "name: CI" "AC1.2: Workflow nommé 'CI'"
    test_file_contains ".github/workflows/ci.yml" "lint:" "AC1.3: Job 'lint' existe"
    test_file_contains ".github/workflows/ci.yml" "test-unit:" "AC1.4: Job 'test-unit' existe"
    test_file_contains ".github/workflows/ci.yml" "test-integration:" "AC1.5: Job 'test-integration' existe"
    test_file_contains ".github/workflows/ci.yml" "build-validation:" "AC1.6: Job 'build-validation' existe"
    test_file_contains ".github/workflows/ci.yml" "on:" "AC1.7: Section 'on:' trigger existe"
    test_file_contains ".github/workflows/ci.yml" "pull_request" "AC1.8: Trigger sur PR"
    test_file_contains ".github/workflows/ci.yml" "push" "AC1.9: Trigger sur push"
fi
echo ""

# AC2: Cache optimisé
echo "--- AC2: Cache optimisé pour performances ---"
if [[ -f ".github/workflows/ci.yml" ]]; then
    test_file_contains ".github/workflows/ci.yml" "actions/cache" "AC2.1: Utilise actions/cache"
    test_file_contains ".github/workflows/ci.yml" "hashFiles" "AC2.2: Hash files pour clé cache"
fi
echo ""

# AC3: Script déploiement
echo "--- AC3: Script déploiement manuel sécurisé ---"
test_file_exists "scripts/deploy.sh" "AC3.1: Fichier deploy.sh existe"
if [[ -f "scripts/deploy.sh" ]]; then
    test -x "scripts/deploy.sh" && pass "AC3.2: deploy.sh est exécutable" || fail "AC3.2: deploy.sh n'est pas exécutable"
    test_file_contains "scripts/deploy.sh" "#!/usr/bin/env bash" "AC3.3: Shebang correct"
    test_file_contains "scripts/deploy.sh" "set -euo pipefail" "AC3.4: Options bash strictes"
    test_file_contains "scripts/deploy.sh" "friday-vps" "AC3.5: Utilise hostname Tailscale"
    test_file_contains "scripts/deploy.sh" "backup.sh" "AC3.6: Appelle backup.sh"
    test_file_contains "scripts/deploy.sh" "docker compose" "AC3.7: Utilise docker compose"
fi
echo ""

# AC4: Healthcheck avec rollback
echo "--- AC4: Healthcheck robuste avec rollback ---"
if [[ -f "scripts/deploy.sh" ]]; then
    test_file_contains "scripts/deploy.sh" "healthcheck" "AC4.1: Fonction healthcheck existe"
    test_file_contains "scripts/deploy.sh" "/api/v1/health" "AC4.2: Appelle endpoint healthcheck"
    test_file_contains "scripts/deploy.sh" "rollback" "AC4.3: Fonction rollback existe"
    test_file_contains "scripts/deploy.sh" "retries=3" "AC4.4: Retry 3x configuré"
fi
echo ""

# AC5: Notifications Telegram
echo "--- AC5: Notification Telegram déploiement ---"
if [[ -f "scripts/deploy.sh" ]]; then
    test_file_contains "scripts/deploy.sh" "TELEGRAM_BOT_TOKEN" "AC5.1: Utilise TELEGRAM_BOT_TOKEN"
    test_file_contains "scripts/deploy.sh" "TOPIC_SYSTEM_ID" "AC5.2: Utilise TOPIC_SYSTEM_ID"
    test_file_contains "scripts/deploy.sh" "send_telegram" "AC5.3: Fonction send_telegram existe"
    test_file_contains "scripts/deploy.sh" "api.telegram.org" "AC5.4: URL Telegram API"
fi
echo ""

# AC6: Documentation runbook
echo "--- AC6: Documentation troubleshooting ---"
test_file_exists "docs/deployment-runbook.md" "AC6.1: Fichier deployment-runbook.md existe"
if [[ -f "docs/deployment-runbook.md" ]]; then
    test_file_contains "docs/deployment-runbook.md" "Prérequis" "AC6.2: Section Prérequis existe"
    test_file_contains "docs/deployment-runbook.md" "Procédure" "AC6.3: Section Procédure existe"
    test_file_contains "docs/deployment-runbook.md" "Troubleshooting" "AC6.4: Section Troubleshooting existe"
    test_file_contains "docs/deployment-runbook.md" "Rollback" "AC6.5: Section Rollback existe"
fi
echo ""

# AC7: Badge GitHub Actions
echo "--- AC7: Badge GitHub Actions dans README ---"
test_file_exists "README.md" "AC7.1: README.md existe"
if [[ -f "README.md" ]]; then
    test_file_contains "README.md" "workflows/CI/badge.svg" "AC7.2: Badge CI présent dans README"
fi
echo ""

# AC9: Builds reproductibles
echo "--- AC9: Builds reproductibles ---"
test_file_exists "agents/requirements-lock.txt" "AC9.1: requirements-lock.txt existe"
if [[ -f ".github/workflows/ci.yml" ]]; then
    test_file_contains ".github/workflows/ci.yml" "--no-cache" "AC9.2: Build sans cache pour validation"
fi
echo ""

# Résumé
echo "=================================================="
echo "Test Summary"
echo "=================================================="
echo -e "${GREEN}PASSED: $PASSED${NC}"
echo -e "${RED}FAILED: $FAILED${NC}"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
