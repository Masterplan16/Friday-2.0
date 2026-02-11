#!/bin/bash
# Test EmailEngine healthcheck - Story 2.1 Subtask 1.4
# Vérifie que EmailEngine est opérationnel et que les comptes IMAP sont connectés
#
# Usage:
#   bash scripts/test_emailengine_health.sh [--verbose]
#
# Prérequis:
#   - EmailEngine container running
#   - EMAILENGINE_SECRET dans .env
#   - 4 comptes configurés (via setup_emailengine_accounts.py)

set -euo pipefail

# ============================================
# Configuration
# ============================================

EMAILENGINE_URL="${EMAILENGINE_URL:-http://localhost:3000}"
EMAILENGINE_SECRET="${EMAILENGINE_SECRET:-}"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

VERBOSE=false
if [[ "${1:-}" == "--verbose" ]]; then
    VERBOSE=true
fi

# Compteurs
TESTS_PASSED=0
TESTS_FAILED=0

# ============================================
# Functions
# ============================================

log_info() {
    echo -e "${BLUE}ℹ${NC} $*"
}

log_success() {
    echo -e "${GREEN}✅${NC} $*"
    ((TESTS_PASSED++))
}

log_error() {
    echo -e "${RED}❌${NC} $*"
    ((TESTS_FAILED++))
}

log_warning() {
    echo -e "${YELLOW}⚠️${NC} $*"
}

# ============================================
# Vérification Prérequis
# ============================================

log_info "Starting EmailEngine health tests..."
echo ""

# Vérifier EMAILENGINE_SECRET
if [[ -z "$EMAILENGINE_SECRET" ]]; then
    log_error "EMAILENGINE_SECRET not set in environment"
    log_info "Please set EMAILENGINE_SECRET in .env or export it"
    exit 1
fi

# ============================================
# Test 1: Healthcheck endpoint
# ============================================

log_info "Test 1: Healthcheck endpoint (GET /health)"

if curl -s -f -o /dev/null -w "%{http_code}" "$EMAILENGINE_URL/health" | grep -q "200"; then
    log_success "Healthcheck endpoint returned 200 OK"

    if [[ "$VERBOSE" == "true" ]]; then
        HEALTH_RESPONSE=$(curl -s "$EMAILENGINE_URL/health")
        echo "   Response: $HEALTH_RESPONSE"
    fi
else
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$EMAILENGINE_URL/health" || echo "connection_failed")
    log_error "Healthcheck failed (HTTP $HTTP_CODE)"

    if [[ "$HTTP_CODE" == "connection_failed" ]]; then
        log_error "Cannot connect to EmailEngine at $EMAILENGINE_URL"
        log_info "Is the container running? Try: docker compose ps emailengine"
        exit 1
    fi
fi

echo ""

# ============================================
# Test 2: API Authentication
# ============================================

log_info "Test 2: API Authentication (GET /v1/accounts)"

AUTH_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Authorization: Bearer $EMAILENGINE_SECRET" \
    "$EMAILENGINE_URL/v1/accounts" || echo -e "\nconnection_failed")

HTTP_CODE=$(echo "$AUTH_RESPONSE" | tail -1)
BODY=$(echo "$AUTH_RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" == "200" ]]; then
    log_success "API authentication successful"

    # Compter le nombre de comptes
    ACCOUNT_COUNT=$(echo "$BODY" | grep -o '"account"' | wc -l || echo 0)
    log_info "   Found $ACCOUNT_COUNT account(s) configured"

    if [[ "$VERBOSE" == "true" ]]; then
        echo "   Response: $BODY"
    fi
elif [[ "$HTTP_CODE" == "401" ]]; then
    log_error "Authentication failed (HTTP 401 - Invalid EMAILENGINE_SECRET)"
else
    log_error "API request failed (HTTP $HTTP_CODE)"
fi

echo ""

# ============================================
# Test 3: Account Status (4 comptes attendus)
# ============================================

log_info "Test 3: Account Status (4 comptes IMAP attendus)"

EXPECTED_ACCOUNTS=("account-medical" "account-faculty" "account-research" "account-personal")

for ACCOUNT_ID in "${EXPECTED_ACCOUNTS[@]}"; do
    log_info "   Checking: $ACCOUNT_ID"

    ACCOUNT_RESPONSE=$(curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer $EMAILENGINE_SECRET" \
        "$EMAILENGINE_URL/v1/account/$ACCOUNT_ID" 2>/dev/null || echo -e "\nfailed")

    HTTP_CODE=$(echo "$ACCOUNT_RESPONSE" | tail -1)
    BODY=$(echo "$ACCOUNT_RESPONSE" | head -n -1)

    if [[ "$HTTP_CODE" == "200" ]]; then
        # Extraire state (connected, disconnected, error)
        STATE=$(echo "$BODY" | grep -o '"state":"[^"]*"' | cut -d'"' -f4 || echo "unknown")

        if [[ "$STATE" == "connected" ]]; then
            log_success "   $ACCOUNT_ID: connected"
        elif [[ "$STATE" == "disconnected" ]]; then
            log_warning "   $ACCOUNT_ID: disconnected (not yet synced)"
        elif [[ "$STATE" == "authenticationError" ]] || [[ "$STATE" == "connectError" ]]; then
            log_error "   $ACCOUNT_ID: $STATE (check credentials)"

            if [[ "$VERBOSE" == "true" ]]; then
                ERROR_MSG=$(echo "$BODY" | grep -o '"lastErrorMessage":"[^"]*"' | cut -d'"' -f4 || echo "")
                if [[ -n "$ERROR_MSG" ]]; then
                    echo "      Error: $ERROR_MSG"
                fi
            fi
        else
            log_warning "   $ACCOUNT_ID: state=$STATE"
        fi

        if [[ "$VERBOSE" == "true" ]]; then
            echo "      Full response: $BODY"
        fi
    elif [[ "$HTTP_CODE" == "404" ]]; then
        log_error "   $ACCOUNT_ID: not found (run setup_emailengine_accounts.py first)"
    else
        log_error "   $ACCOUNT_ID: HTTP $HTTP_CODE"
    fi
done

echo ""

# ============================================
# Test 4: Webhook Configuration (optionnel)
# ============================================

log_info "Test 4: Webhook Configuration (checking first account)"

FIRST_ACCOUNT="${EXPECTED_ACCOUNTS[0]}"
WEBHOOK_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Authorization: Bearer $EMAILENGINE_SECRET" \
    "$EMAILENGINE_URL/v1/account/$FIRST_ACCOUNT/webhooks" 2>/dev/null || echo -e "\nfailed")

HTTP_CODE=$(echo "$WEBHOOK_RESPONSE" | tail -1)
BODY=$(echo "$WEBHOOK_RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" == "200" ]]; then
    # Vérifier si des webhooks sont configurés
    WEBHOOK_COUNT=$(echo "$BODY" | grep -o '"url"' | wc -l || echo 0)

    if [[ "$WEBHOOK_COUNT" -gt 0 ]]; then
        log_success "Webhooks configured ($WEBHOOK_COUNT webhook(s))"

        if [[ "$VERBOSE" == "true" ]]; then
            echo "   Webhooks: $BODY"
        fi
    else
        log_warning "No webhooks configured yet (Task 2 pending)"
    fi
else
    log_warning "Could not check webhooks (HTTP $HTTP_CODE)"
fi

echo ""

# ============================================
# Résumé Final
# ============================================

echo "========================================"
echo "EmailEngine Health Test Summary"
echo "========================================"
echo -e "${GREEN}✅ Tests passed: $TESTS_PASSED${NC}"
echo -e "${RED}❌ Tests failed: $TESTS_FAILED${NC}"
echo ""

if [[ $TESTS_FAILED -eq 0 ]]; then
    log_success "All tests passed! EmailEngine is healthy."
    exit 0
else
    log_error "Some tests failed. Check logs above."
    exit 1
fi
