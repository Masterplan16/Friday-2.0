#!/usr/bin/env bash
# Script de déploiement Friday 2.0 sur VPS-4
# Story 1.16 : CI/CD Pipeline GitHub Actions
# Connexion via Tailscale VPN, backup pré-déploiement, healthcheck + rollback

# LOW #15 FIX: Options bash strictes (-e = exit on error, -u = undefined vars error, -o pipefail = pipe failures)
set -euo pipefail

# ────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────

# Hostname Tailscale VPS (configuré Story 1.4)
VPS_HOST="${VPS_HOST:-friday-vps}"

# Telegram notifications
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TOPIC_SYSTEM_ID="${TOPIC_SYSTEM_ID:-}"

# Git commit hash pour traçabilité
COMMIT_HASH=$(git rev-parse --short HEAD)

# Healthcheck config
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://localhost:8000/api/v1/health}"
HEALTHCHECK_RETRIES=3
HEALTHCHECK_DELAY=5

# Rollback config (CRITICAL #2 fix: éviter rollback aveugle vers version cassée)
ROLLBACK_TARGET="${ROLLBACK_TARGET:-}"  # Variable optionnelle: commit hash ou tag stable

# ────────────────────────────────────────────────────────────
# Functions
# ────────────────────────────────────────────────────────────

send_telegram() {
    local message="$1"

    if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ -z "$TOPIC_SYSTEM_ID" ]]; then
        echo "::warning::Telegram credentials not configured - skipping notification"
        return 0
    fi

    # MEDIUM #12 FIX: Validation format credentials Telegram
    if ! [[ "$TELEGRAM_BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]{35,}$ ]]; then
        echo "::warning::Invalid TELEGRAM_BOT_TOKEN format - skipping notification"
        return 0
    fi

    if ! [[ "$TOPIC_SYSTEM_ID" =~ ^-?[0-9]+$ ]]; then
        echo "::warning::Invalid TOPIC_SYSTEM_ID format (must be numeric) - skipping notification"
        return 0
    fi

    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TOPIC_SYSTEM_ID}" \
        -d "text=${message}" \
        -d "parse_mode=HTML" > /dev/null || {
        echo "::warning::Failed to send Telegram notification"
    }
}

healthcheck() {
    echo "::notice::Running healthcheck (${HEALTHCHECK_RETRIES} retries, ${HEALTHCHECK_DELAY}s delay)..."

    for i in $(seq 1 "$HEALTHCHECK_RETRIES"); do
        echo "::notice::Healthcheck attempt $i/$HEALTHCHECK_RETRIES..."

        # MEDIUM #13 FIX: Ajouter timeout curl pour éviter blocage infini
        if ssh "$VPS_HOST" "curl -sf --max-time 10 ${HEALTHCHECK_URL}"; then
            echo "::notice::Healthcheck PASSED on attempt $i"
            return 0
        fi

        if [[ $i -lt $HEALTHCHECK_RETRIES ]]; then
            echo "::warning::Healthcheck failed, retrying in ${HEALTHCHECK_DELAY}s..."
            sleep "$HEALTHCHECK_DELAY"
        fi
    done

    echo "::error::Healthcheck FAILED after ${HEALTHCHECK_RETRIES} attempts"
    return 1
}

rollback() {
    echo "::error::Deployment failed - initiating rollback..."

    # Arrêter services actuels
    ssh "$VPS_HOST" "cd /opt/friday-2.0 && docker compose down"

    # CRITICAL #2 FIX: Rollback intelligent vers version stable
    local rollback_ref="${ROLLBACK_TARGET}"

    if [[ -z "$rollback_ref" ]]; then
        # Pas de ROLLBACK_TARGET défini: chercher dernier tag stable
        rollback_ref=$(ssh "$VPS_HOST" "cd /opt/friday-2.0 && git describe --tags --abbrev=0 2>/dev/null")

        if [[ -z "$rollback_ref" ]]; then
            # Pas de tag: fallback vers HEAD~1 avec warning explicite
            rollback_ref="HEAD~1"
            echo "::warning::No ROLLBACK_TARGET or stable tag found - rolling back to HEAD~1 (may be unstable!)"
            echo "::warning::Set ROLLBACK_TARGET env var to specify safe rollback commit/tag"
        else
            echo "::notice::Rolling back to last stable tag: $rollback_ref"
        fi
    else
        echo "::notice::Rolling back to specified target: $rollback_ref"
    fi

    # Revenir à la version cible
    ssh "$VPS_HOST" "cd /opt/friday-2.0 && git checkout $rollback_ref"

    # Redémarrer avec version précédente
    ssh "$VPS_HOST" "cd /opt/friday-2.0 && docker compose up -d"

    echo "::notice::Rollback completed - version $rollback_ref restored"
}

check_tailscale() {
    echo "::notice::Verifying Tailscale connection..."

    if ! command -v tailscale &> /dev/null; then
        echo "::error::Tailscale not installed. Install from https://tailscale.com/download"
        exit 1
    fi

    if ! tailscale status &> /dev/null; then
        echo "::error::Tailscale not connected. Run 'sudo tailscale up' first."
        exit 1
    fi

    if ! tailscale status | grep -q "$VPS_HOST"; then
        echo "::error::VPS host '$VPS_HOST' not found in Tailscale network"
        echo "Available hosts:"
        tailscale status
        exit 1
    fi

    echo "::notice::Tailscale connection verified - $VPS_HOST is reachable"
}

run_backup() {
    echo "::notice::Running pre-deployment backup..."

    # MEDIUM #10 FIX: Logique cohérente - backup non-critique si Story 1.12 pas implémentée
    if [[ ! -f "./scripts/backup.sh" ]]; then
        echo "::warning::backup.sh not found - skipping backup (Story 1.12 not implemented yet)"
        return 0
    fi

    # Exécuter backup sur VPS
    ssh "$VPS_HOST" "cd /opt/friday-2.0 && ./scripts/backup.sh" || {
        echo "::warning::Backup failed - continuing deployment (non-critical until Story 1.12 complete)"
        return 0
    }

    echo "::notice::Backup completed successfully"
}

deploy() {
    echo "::notice::Starting deployment to $VPS_HOST..."

    # HIGH #5 FIX: Vérifier working tree avant git pull
    echo "::notice::Checking git status on VPS..."
    local git_status=$(ssh "$VPS_HOST" "cd /opt/friday-2.0 && git status --porcelain")

    if [[ -n "$git_status" ]]; then
        echo "::error::VPS working tree is dirty - cannot pull safely"
        echo "::error::Uncommitted changes detected:"
        echo "$git_status"
        echo "::error::Please commit or stash changes on VPS before deploying"
        exit 1
    fi

    # Pull latest code (safe car working tree clean)
    echo "::notice::Pulling latest code from git..."
    ssh "$VPS_HOST" "cd /opt/friday-2.0 && git pull" || {
        echo "::error::git pull failed - check for conflicts or network issues"
        exit 1
    }

    # Pull Docker images
    echo "::notice::Pulling Docker images..."
    ssh "$VPS_HOST" "cd /opt/friday-2.0 && docker compose pull"

    # Build and restart services
    echo "::notice::Building and restarting services..."
    ssh "$VPS_HOST" "cd /opt/friday-2.0 && docker compose up -d --build"

    echo "::notice::Deployment commands completed"
}

# ────────────────────────────────────────────────────────────
# Main Deployment Flow
# ────────────────────────────────────────────────────────────

main() {
    echo "=================================================="
    echo "Friday 2.0 - Deployment Script"
    echo "=================================================="
    echo "VPS Host: $VPS_HOST"
    echo "Commit: $COMMIT_HASH"
    echo "=================================================="
    echo ""

    # 1. Vérifier Tailscale
    check_tailscale
    echo ""

    # 2. Notification début déploiement
    send_telegram "🚀 <b>Déploiement Friday 2.0 démarré</b>

VPS: <code>$VPS_HOST</code>
Commit: <code>$COMMIT_HASH</code>
Statut: En cours..."

    # 3. Backup pré-déploiement
    run_backup
    echo ""

    # 4. Déploiement
    deploy
    echo ""

    # 5. Healthcheck
    if healthcheck; then
        echo ""
        echo "::notice::✅ Deployment SUCCESSFUL"
        send_telegram "✅ <b>Déploiement réussi</b>

VPS: <code>$VPS_HOST</code>
Commit: <code>$COMMIT_HASH</code>
Healthcheck: <b>PASS</b>"
        exit 0
    else
        echo ""
        echo "::error::❌ Deployment FAILED"
        rollback
        send_telegram "❌ <b>Déploiement échoué</b>

VPS: <code>$VPS_HOST</code>
Commit: <code>$COMMIT_HASH</code>
Healthcheck: <b>FAIL</b>
Action: Rollback effectué"
        exit 1
    fi
}

# Execute main function
main "$@"
