#!/usr/bin/env bats
# Tests unitaires pour scripts/auto-recover-ram.sh
# Story 1.13 - AC3: Auto-recover-ram si > 91% (kill services par priorité)

# Setup: Variables d'environnement
setup() {
    export RAM_PCT=85  # Default: sous le seuil
    export TELEGRAM_BOT_TOKEN="test_token"
    export TELEGRAM_CHAT_ID="test_chat"
    export TOPIC_SYSTEM_ID="123"
}

@test "auto-recover-ram exits 0 if RAM below 91% (no recovery needed)" {
    # RAM à 85% (en dessous du seuil 91%)
    export RAM_PCT=85

    # Exécuter script
    run bash scripts/auto-recover-ram.sh

    # Vérifications
    [ "$status" -eq 0 ]
    [[ "$output" =~ "RAM OK" ]] || [[ "$output" =~ "No recovery" ]] || [[ "$output" =~ "below threshold" ]]
}

@test "auto-recover-ram kills TTS first if RAM > 91%" {
    # RAM à 92% (au-dessus du seuil 91%)
    export RAM_PCT=92

    # Mock docker stop command
    function docker() {
        if [[ "$1" == "stop" ]]; then
            echo "Stopping $2"
            return 0
        elif [[ "$1" == "ps" ]]; then
            # Simuler liste services
            echo "kokoro-tts"
            echo "faster-whisper"
            echo "surya-ocr"
            return 0
        fi
    }
    export -f docker

    # Exécuter script
    run bash scripts/auto-recover-ram.sh

    # Vérifications : kokoro-tts devrait être le premier service tué (Priority 1)
    [[ "$output" =~ "kokoro-tts" ]] || [[ "$output" =~ "TTS" ]]
}

@test "auto-recover-ram never kills protected services (postgres, redis, gateway, bot, n8n)" {
    # RAM très haute (95%)
    export RAM_PCT=95

    # Mock docker stop : fail si service protégé
    function docker() {
        if [[ "$1" == "stop" ]]; then
            if [[ "$2" == "postgres" ]] || [[ "$2" == "redis" ]] || [[ "$2" == "friday-gateway" ]] || [[ "$2" == "friday-bot" ]] || [[ "$2" == "n8n" ]]; then
                echo "ERROR: Attempting to kill protected service $2"
                return 1
            fi
            echo "Stopping $2"
            return 0
        fi
    }
    export -f docker

    # Exécuter script
    run bash scripts/auto-recover-ram.sh

    # Vérifications : aucun service protégé ne devrait être tué
    ! [[ "$output" =~ "Stopping postgres" ]]
    ! [[ "$output" =~ "Stopping redis" ]]
    ! [[ "$output" =~ "Stopping friday-gateway" ]]
    ! [[ "$output" =~ "Stopping friday-bot" ]]
    ! [[ "$output" =~ "Stopping n8n" ]]
}

@test "auto-recover-ram kills max 3 services (safety guard)" {
    # RAM très haute (95%)
    export RAM_PCT=95

    # Mock docker stop : compter nombre de stops
    STOP_COUNT=0
    function docker() {
        if [[ "$1" == "stop" ]]; then
            ((STOP_COUNT++))
            echo "Stopping $2 (count: $STOP_COUNT)"
            # Simuler RAM qui ne descend jamais (pour tester safety guard)
            export RAM_PCT=95
            return 0
        fi
    }
    export -f docker

    # Exécuter script
    run bash scripts/auto-recover-ram.sh

    # Vérifications : max 3 services tués
    # Compter occurrences de "Stopping" dans output
    stop_count=$(echo "$output" | grep -c "Stopping" || echo 0)
    [ "$stop_count" -le 3 ]
}

@test "auto-recover-ram sends Telegram notification on success" {
    # RAM à 92%
    export RAM_PCT=92

    # Mock curl pour capturer requête Telegram
    function curl() {
        if [[ "$*" =~ "telegram" ]]; then
            echo "Telegram notification sent: $*" >> /tmp/telegram_mock.log
            return 0
        fi
    }
    export -f curl

    # Mock docker pour simuler recovery success
    function docker() {
        if [[ "$1" == "stop" ]]; then
            # Simuler RAM qui descend après kill
            export RAM_PCT=82
            return 0
        fi
    }
    export -f docker

    # Nettoyer log précédent
    rm -f /tmp/telegram_mock.log

    # Exécuter script
    run bash scripts/auto-recover-ram.sh

    # Vérifications : notification Telegram envoyée
    [ -f /tmp/telegram_mock.log ]
    grep -q "Telegram notification sent" /tmp/telegram_mock.log

    # Cleanup
    rm -f /tmp/telegram_mock.log
}

# Cleanup
teardown() {
    unset RAM_PCT
    unset TELEGRAM_BOT_TOKEN
    unset TELEGRAM_CHAT_ID
    unset TOPIC_SYSTEM_ID
    rm -f /tmp/telegram_mock.log
}
