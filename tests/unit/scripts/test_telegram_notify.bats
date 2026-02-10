#!/usr/bin/env bats
# Tests unitaires pour scripts/telegram-notify.sh
# Story 1.13 - AC5

setup() {
    # Variables de test
    export TELEGRAM_BOT_TOKEN="test_bot_token_123"
    export TELEGRAM_CHAT_ID="test_chat_id_456"
    export TOPIC_SYSTEM_ID="789"

    # Mock curl pour éviter appels API réels
    export PATH="$BATS_TEST_DIRNAME/mocks:$PATH"
}

teardown() {
    # Cleanup
    rm -f /tmp/telegram_notify_test_*.log
}

@test "telegram-notify.sh envoie message avec token et chat_id" {
    # Mock curl qui log les paramètres
    cat > "$BATS_TEST_DIRNAME/mocks/curl" <<'EOF'
#!/usr/bin/env bash
# Mock curl - log params et exit 0
echo "$@" > /tmp/telegram_notify_test_curl.log
exit 0
EOF
    chmod +x "$BATS_TEST_DIRNAME/mocks/curl"

    # Créer dossier mocks si n'existe pas
    mkdir -p "$BATS_TEST_DIRNAME/mocks"

    # Appeler script
    run bash scripts/telegram-notify.sh "Test message"

    [ "$status" -eq 0 ]
    [[ "$output" =~ "notification sent" ]]

    # Vérifier que curl a été appelé avec les bons params
    [ -f /tmp/telegram_notify_test_curl.log ]
    curl_args=$(cat /tmp/telegram_notify_test_curl.log)
    [[ "$curl_args" =~ "test_bot_token_123" ]]
    [[ "$curl_args" =~ "test_chat_id_456" ]]
}

@test "telegram-notify.sh ajoute message_thread_id si TOPIC_SYSTEM_ID défini" {
    mkdir -p "$BATS_TEST_DIRNAME/mocks"
    cat > "$BATS_TEST_DIRNAME/mocks/curl" <<'EOF'
#!/usr/bin/env bash
echo "$@" > /tmp/telegram_notify_test_topic.log
exit 0
EOF
    chmod +x "$BATS_TEST_DIRNAME/mocks/curl"

    run bash scripts/telegram-notify.sh "Topic test"

    [ "$status" -eq 0 ]

    # Vérifier que message_thread_id est présent
    curl_args=$(cat /tmp/telegram_notify_test_topic.log)
    [[ "$curl_args" =~ "message_thread_id=789" ]]
}

@test "telegram-notify.sh skip gracefully si TELEGRAM_BOT_TOKEN manquant" {
    unset TELEGRAM_BOT_TOKEN

    run bash scripts/telegram-notify.sh "Test sans token"

    # Exit 0 même si pas de token (optionnel)
    [ "$status" -eq 0 ]
    [[ "$output" =~ "not set" ]] || [[ "$output" =~ "skipped" ]]
}

@test "telegram-notify.sh échoue si aucun argument" {
    run bash scripts/telegram-notify.sh

    # Exit 1 si pas de message
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Usage" ]]
}

@test "telegram-notify.sh respecte timeout 30s (AC5)" {
    mkdir -p "$BATS_TEST_DIRNAME/mocks"

    # Mock curl qui vérifie --max-time 30
    cat > "$BATS_TEST_DIRNAME/mocks/curl" <<'EOF'
#!/usr/bin/env bash
# Vérifier que --max-time 30 est présent
if [[ "$*" =~ "--max-time 30" ]] || [[ "$*" =~ "--max-time=30" ]]; then
    echo "TIMEOUT_OK" > /tmp/telegram_notify_test_timeout.log
    exit 0
else
    echo "TIMEOUT_MISSING" > /tmp/telegram_notify_test_timeout.log
    exit 1
fi
EOF
    chmod +x "$BATS_TEST_DIRNAME/mocks/curl"

    run bash scripts/telegram-notify.sh "Timeout test"

    [ "$status" -eq 0 ]

    # Vérifier que timeout est configuré
    timeout_check=$(cat /tmp/telegram_notify_test_timeout.log)
    [[ "$timeout_check" == "TIMEOUT_OK" ]]
}

@test "telegram-notify.sh encode message en Markdown" {
    mkdir -p "$BATS_TEST_DIRNAME/mocks"
    cat > "$BATS_TEST_DIRNAME/mocks/curl" <<'EOF'
#!/usr/bin/env bash
echo "$@" > /tmp/telegram_notify_test_markdown.log
exit 0
EOF
    chmod +x "$BATS_TEST_DIRNAME/mocks/curl"

    run bash scripts/telegram-notify.sh "**Bold** _italic_"

    [ "$status" -eq 0 ]

    # Vérifier parse_mode=Markdown
    curl_args=$(cat /tmp/telegram_notify_test_markdown.log)
    [[ "$curl_args" =~ "parse_mode=Markdown" ]]
}

@test "telegram-notify.sh retourne exit 1 si curl échoue" {
    mkdir -p "$BATS_TEST_DIRNAME/mocks"

    # Mock curl qui échoue
    cat > "$BATS_TEST_DIRNAME/mocks/curl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
    chmod +x "$BATS_TEST_DIRNAME/mocks/curl"

    run bash scripts/telegram-notify.sh "Test échec"

    # Exit 1 si curl échoue
    [ "$status" -eq 1 ]
    [[ "$output" =~ "failed" ]]
}
