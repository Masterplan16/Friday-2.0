#!/usr/bin/env bats
# Tests unitaires pour scripts/validate-docker-restart-policy.sh
# Story 1.13 - AC1: Validation restart policy Docker

# Setup: Créer répertoire fixtures si n'existe pas
setup() {
    export TEST_DIR="${BATS_TEST_DIRNAME}/../../fixtures"
    mkdir -p "${TEST_DIR}"
}

@test "validate-restart-policy passes if all services have restart" {
    # Créer docker-compose de test avec tous services ayant restart: unless-stopped
    cat > "${TEST_DIR}/docker-compose-valid.yml" <<EOF
version: '3.8'
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
  redis:
    image: redis:7
    restart: unless-stopped
  gateway:
    image: friday-gateway
    restart: unless-stopped
EOF

    # Exécuter script de validation
    run bash scripts/validate-docker-restart-policy.sh "${TEST_DIR}/docker-compose-valid.yml"

    # Vérifications
    [ "$status" -eq 0 ]
    [[ "$output" =~ "All services have restart policy" ]] || [[ "$output" =~ "OK" ]] || [[ "$output" =~ "✓" ]]
}

@test "validate-restart-policy fails if service missing restart" {
    # Créer docker-compose de test avec service SANS restart policy
    cat > "${TEST_DIR}/docker-compose-invalid.yml" <<EOF
version: '3.8'
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
  redis:
    image: redis:7
    # MISSING restart policy
  gateway:
    image: friday-gateway
    restart: unless-stopped
EOF

    # Exécuter script de validation
    run bash scripts/validate-docker-restart-policy.sh "${TEST_DIR}/docker-compose-invalid.yml"

    # Vérifications
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Missing restart policy" ]] || [[ "$output" =~ "redis" ]]
}

@test "validate-restart-policy lists all missing services" {
    # Créer docker-compose de test avec PLUSIEURS services sans restart policy
    cat > "${TEST_DIR}/docker-compose-multiple-invalid.yml" <<EOF
version: '3.8'
services:
  postgres:
    image: postgres:16
    # MISSING restart policy
  redis:
    image: redis:7
    # MISSING restart policy
  gateway:
    image: friday-gateway
    restart: unless-stopped
  n8n:
    image: n8nio/n8n
    # MISSING restart policy
EOF

    # Exécuter script de validation
    run bash scripts/validate-docker-restart-policy.sh "${TEST_DIR}/docker-compose-multiple-invalid.yml"

    # Vérifications
    [ "$status" -eq 1 ]
    [[ "$output" =~ "postgres" ]]
    [[ "$output" =~ "redis" ]]
    [[ "$output" =~ "n8n" ]]
}

# Cleanup: Supprimer fichiers de test
teardown() {
    rm -f "${TEST_DIR}/docker-compose-valid.yml"
    rm -f "${TEST_DIR}/docker-compose-invalid.yml"
    rm -f "${TEST_DIR}/docker-compose-multiple-invalid.yml"
}
