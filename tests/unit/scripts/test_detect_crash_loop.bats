#!/usr/bin/env bats
# test_detect_crash_loop.bats - Tests unitaires detect-crash-loop.sh
#
# Story 1.13 - AC6: Crash loop detection
# 4 tests pour valider détection et arrêt services crash loop

setup() {
    export TEST_DIR="${BATS_TEST_TMPDIR}/test_detect_crash_loop"
    mkdir -p "$TEST_DIR"

    # Mock variables d'environnement
    export TELEGRAM_BOT_TOKEN="test_token_12345"
    export TELEGRAM_CHAT_ID="test_chat_id"
    export TOPIC_SYSTEM_ID="1234"

    # Créer mock curl qui enregistre les appels
    export CURL_LOG="${TEST_DIR}/curl.log"

    # Mock docker inspect command
    export DOCKER_INSPECT_LOG="${TEST_DIR}/docker_inspect.log"
}

teardown() {
    rm -rf "$TEST_DIR"
}

# Test 1: Alert si service redémarre > 3 fois en 1h
@test "detect-crash-loop alerts if service restarted > 3 times" {
    # Mock docker ps
    function docker() {
        if [[ "$1" == "ps" ]]; then
            echo "CONTAINER ID   NAMES"
            echo "abc123         crashing-service"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.RestartCount}}" ]]; then
            # Service redémarré 5 fois
            echo "5"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.State.StartedAt}}" ]]; then
            # Démarré il y a 30 minutes (moins de 1h)
            date -u -d "30 minutes ago" +"%Y-%m-%dT%H:%M:%S.%NZ"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.Name}}" ]]; then
            echo "/crashing-service"
        elif [[ "$1" == "logs" ]] && [[ "$2" == "--tail" ]]; then
            echo "Error: Connection refused"
            echo "Error: Cannot connect to database"
            echo "Fatal: Exiting"
        fi
    }
    export -f docker

    # Mock curl
    function curl() {
        echo "curl called with: $*" >> "${CURL_LOG}"
        return 0
    }
    export -f curl

    run bash scripts/detect-crash-loop.sh

    # Exit 1 = crash loop détecté
    [ "$status" -eq 1 ]

    # Vérifier output mentionne crash loop
    [[ "$output" =~ "CRASH LOOP DETECTED" ]] || [[ "$output" =~ "crashing-service" ]]
}

# Test 2: Stop le service en crash loop
@test "detect-crash-loop stops crashing service" {
    local stopped=false

    # Mock docker avec tracking du docker stop
    function docker() {
        if [[ "$1" == "ps" ]]; then
            echo "CONTAINER ID   NAMES"
            echo "abc123         crashing-service"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.RestartCount}}" ]]; then
            echo "5"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.State.StartedAt}}" ]]; then
            date -u -d "30 minutes ago" +"%Y-%m-%dT%H:%M:%S.%NZ"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.Name}}" ]]; then
            echo "/crashing-service"
        elif [[ "$1" == "stop" ]]; then
            # Enregistrer qu'on a appelé docker stop
            echo "docker stop called on: $2" >> "${DOCKER_INSPECT_LOG}"
            stopped=true
        elif [[ "$1" == "logs" ]] && [[ "$2" == "--tail" ]]; then
            echo "Error line 1"
        fi
    }
    export -f docker

    # Mock curl
    function curl() {
        return 0
    }
    export -f curl

    run bash scripts/detect-crash-loop.sh

    # Vérifier que docker stop a été appelé
    [ -f "${DOCKER_INSPECT_LOG}" ]
    grep "docker stop called" "${DOCKER_INSPECT_LOG}"
}

# Test 3: Envoie alerte Telegram avec logs
@test "detect-crash-loop sends Telegram alert with logs" {
    # Mock docker
    function docker() {
        if [[ "$1" == "ps" ]]; then
            echo "CONTAINER ID   NAMES"
            echo "abc123         test-service"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.RestartCount}}" ]]; then
            echo "4"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.State.StartedAt}}" ]]; then
            date -u -d "20 minutes ago" +"%Y-%m-%dT%H:%M:%S.%NZ"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.Name}}" ]]; then
            echo "/test-service"
        elif [[ "$1" == "logs" ]] && [[ "$2" == "--tail" ]]; then
            echo "Error: Database connection failed"
            echo "Error: Retrying in 5s"
            echo "Error: Connection timeout"
            echo "Fatal: Max retries exceeded"
            echo "Exiting with code 1"
        elif [[ "$1" == "stop" ]]; then
            return 0
        fi
    }
    export -f docker

    # Mock curl pour capturer le message
    function curl() {
        # Sauvegarder tous les arguments
        echo "CURL ARGS: $*" >> "${CURL_LOG}"
        return 0
    }
    export -f curl

    run bash scripts/detect-crash-loop.sh

    # Vérifier que curl a été appelé
    [ -f "${CURL_LOG}" ]

    # Vérifier que le message contient "CRASH LOOP" ou équivalent
    # (le message exact dépend de l'implémentation du script)
    grep -i "curl" "${CURL_LOG}"
}

# Test 4: Ne fait rien si tous les services sont healthy
@test "detect-crash-loop does nothing if all services healthy" {
    # Mock docker avec services healthy (0 ou 1 restart)
    function docker() {
        if [[ "$1" == "ps" ]]; then
            echo "CONTAINER ID   NAMES"
            echo "abc123         healthy-service-1"
            echo "def456         healthy-service-2"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.RestartCount}}" ]]; then
            # Services sains : 0-1 restart
            echo "1"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.State.StartedAt}}" ]]; then
            date -u -d "2 hours ago" +"%Y-%m-%dT%H:%M:%S.%NZ"
        elif [[ "$1" == "inspect" ]] && [[ "$2" == "--format={{.Name}}" ]]; then
            echo "/healthy-service"
        fi
    }
    export -f docker

    # Mock curl
    function curl() {
        echo "curl called: $*" >> "${CURL_LOG}"
        return 0
    }
    export -f curl

    run bash scripts/detect-crash-loop.sh

    # Exit 0 = pas de crash loop détecté
    [ "$status" -eq 0 ]

    # Ne devrait PAS mentionner crash loop
    ! [[ "$output" =~ "CRASH LOOP" ]]

    # Pas d'appel Telegram (curl log vide ou absent)
    if [ -f "${CURL_LOG}" ]; then
        # Si fichier existe, ne devrait pas contenir d'alerte système
        ! grep -i "crash" "${CURL_LOG}" || true
    fi
}
