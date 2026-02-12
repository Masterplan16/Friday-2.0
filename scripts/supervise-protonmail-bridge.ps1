# Supervision ProtonMail Bridge avec auto-restart + alertes Telegram
# Story 2.9 / Phase B.3 — A executer sur PC Mainteneur (Windows)
#
# Usage:
#   .\scripts\supervise-protonmail-bridge.ps1
#
# Pre-requis:
#   - Variables d'environnement TELEGRAM_BOT_TOKEN, TELEGRAM_SUPERGROUP_ID, TOPIC_SYSTEM_ID
#   - ProtonMail Bridge installe sur le PC
#   - Tailscale connecte (VPS peut atteindre pc-mainteneur:1143)

param(
    [string]$TelegramToken = $env:TELEGRAM_BOT_TOKEN,
    [string]$ChatId = $env:TELEGRAM_SUPERGROUP_ID,
    [string]$TopicId = $env:TOPIC_SYSTEM_ID
)

function Send-TelegramAlert {
    param([string]$Message)
    if (-not $TelegramToken -or -not $ChatId) {
        Write-Host "[WARN] Telegram credentials missing, alert not sent: $Message"
        return
    }
    $url = "https://api.telegram.org/bot$TelegramToken/sendMessage"
    $body = @{
        chat_id = $ChatId
        message_thread_id = $TopicId
        text = $Message
    } | ConvertTo-Json
    try {
        Invoke-RestMethod -Uri $url -Method Post -Body $body -ContentType "application/json" | Out-Null
    } catch {
        Write-Host "[ERROR] Failed to send Telegram alert: $_"
    }
}

# Detecter le nom reel du process au demarrage
# (peut etre "protonmail-bridge", "ProtonMailBridge", "bridge", etc. selon la version)
$BridgeProcessName = $null
$PossibleNames = @("protonmail-bridge", "ProtonMailBridge", "bridge", "Proton Mail Bridge")
foreach ($name in $PossibleNames) {
    if (Get-Process $name -ErrorAction SilentlyContinue) {
        $BridgeProcessName = $name
        Write-Host "[OK] Detected Bridge process name: $BridgeProcessName"
        break
    }
}

if (-not $BridgeProcessName) {
    Write-Host "[WARN] ProtonMail Bridge not running. Starting it..."
    Start-Process "C:\Program Files\ProtonMail\Bridge\protonmail-bridge.exe"
    Start-Sleep 15

    # Re-detect
    foreach ($name in $PossibleNames) {
        if (Get-Process $name -ErrorAction SilentlyContinue) {
            $BridgeProcessName = $name
            break
        }
    }
    if (-not $BridgeProcessName) {
        Write-Host "[FATAL] Cannot detect ProtonMail Bridge process name. Check installation."
        Send-TelegramAlert "FATAL: ProtonMail Bridge cannot start on PC Mainteneur"
        exit 1
    }
    Write-Host "[OK] Detected Bridge process name after start: $BridgeProcessName"
}

Write-Host "[INFO] Supervision active. Checking every 5 minutes. Ctrl+C to stop."
Send-TelegramAlert "ProtonMail Bridge supervision started on PC Mainteneur"

while ($true) {
    $process = Get-Process $BridgeProcessName -ErrorAction SilentlyContinue

    if (-not $process) {
        Write-Host "[$(Get-Date)] ProtonMail Bridge DOWN - Redemarrage..."
        Send-TelegramAlert "ProtonMail Bridge down - Redemarrage automatique"

        Start-Process "C:\Program Files\ProtonMail\Bridge\protonmail-bridge.exe"
        Start-Sleep 15

        # Verifier redemarrage OK
        $process = Get-Process $BridgeProcessName -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "[$(Get-Date)] ProtonMail Bridge redemarre OK"
            Send-TelegramAlert "ProtonMail Bridge redemarre OK"
        } else {
            Write-Host "[$(Get-Date)] ProtonMail Bridge FAILED to restart"
            Send-TelegramAlert "ProtonMail Bridge FAILED to restart - INTERVENTION REQUISE"
        }
    }

    Start-Sleep 300  # Check toutes les 5 min
}
