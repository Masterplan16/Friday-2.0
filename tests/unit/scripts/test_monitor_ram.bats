#!/usr/bin/env bats
# Tests unitaires pour scripts/monitor-ram.sh
# Story 1.13 - Task 1.3: Améliorer monitor-ram.sh (AC2)

# Setup: Variables d'environnement
setup() {
    export RAM_ALERT_THRESHOLD_PCT=85
    export TELEGRAM_BOT_TOKEN=""
    export TELEGRAM_CHAT_ID=""
}

@test "monitor-ram.sh outputs human-readable format by default" {
    # Exécuter sans flag
    run bash scripts/monitor-ram.sh

    # Vérifications : output contient les sections attendues
    [[ "$output" =~ "Friday 2.0 - Monitoring Système" ]]
    [[ "$output" =~ "RAM" ]]
    [[ "$output" =~ "CPU" ]]
    [[ "$output" =~ "Disque" ]]
}

@test "monitor-ram.sh --json outputs structured JSON" {
    # Exécuter avec flag --json
    run bash scripts/monitor-ram.sh --json

    # Vérifications : output est du JSON valide
    echo "$output" | jq . > /dev/null  # Échoue si pas du JSON valide
    [ "$?" -eq 0 ]

    # Vérifier clés JSON attendues
    [[ "$output" =~ '"ram_usage_pct"' ]]
    [[ "$output" =~ '"ram_used_gb"' ]]
    [[ "$output" =~ '"ram_total_gb"' ]]
    [[ "$output" =~ '"cpu_usage_pct"' ]]
    [[ "$output" =~ '"disk_usage_pct"' ]]
    [[ "$output" =~ '"timestamp"' ]]
}

@test "monitor-ram.sh --json includes alert status" {
    # Exécuter avec flag --json
    run bash scripts/monitor-ram.sh --json

    # Vérifier présence du champ alert_status
    [[ "$output" =~ '"alert_status"' ]]

    # Vérifier valeurs possibles : "ok" ou "alert"
    echo "$output" | jq -e '.alert_status == "ok" or .alert_status == "alert"' > /dev/null
    [ "$?" -eq 0 ]
}

@test "monitor-ram.sh --help displays usage documentation" {
    # Exécuter avec flag --help
    run bash scripts/monitor-ram.sh --help

    # Vérifications : output contient documentation
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Usage:" ]]
    [[ "$output" =~ "--json" ]]
    [[ "$output" =~ "--telegram" ]]
    [[ "$output" =~ "--help" ]]
}

@test "monitor-ram.sh --telegram flag is documented in help" {
    # Exécuter avec flag --help
    run bash scripts/monitor-ram.sh --help

    # Vérifier que --telegram est documenté
    [[ "$output" =~ "--telegram" ]]
    [[ "$output" =~ "Envoyer alerte" ]] || [[ "$output" =~ "Send alert" ]]
}

# Cleanup
teardown() {
    unset RAM_ALERT_THRESHOLD_PCT
    unset TELEGRAM_BOT_TOKEN
    unset TELEGRAM_CHAT_ID
}
