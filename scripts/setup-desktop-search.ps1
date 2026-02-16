#!/usr/bin/env pwsh
# Friday 2.0 - Setup Desktop Search Consumer
# Story 3.3 - Desktop Search via Claude CLI
# Date: 2026-02-16

[CmdletBinding()]
param(
    [switch]$ConfigOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Friday 2.0 - Setup Desktop Search Consumer ===" -ForegroundColor Cyan
Write-Host ""

# Activer venv d'abord (Claude CLI peut etre dedans)
$venvActivate = Join-Path $ProjectRoot '.venv\Scripts\Activate.ps1'
if (Test-Path $venvActivate) {
    Write-Host "Activation virtualenv..." -ForegroundColor Yellow
    . $venvActivate  # Dot sourcing pour modifier l'environnement actuel
    Write-Host "  OK Venv active" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "ATTENTION Venv introuvable: $venvActivate" -ForegroundColor Yellow
    Write-Host "  Claude CLI doit etre installe globalement" -ForegroundColor Yellow
    Write-Host ""
}

# Etape 1: Verifier Claude CLI installe
Write-Host "[1/5] Verification Claude CLI..." -ForegroundColor Yellow

$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if ($null -eq $claudeCmd) {
    Write-Host "  ERREUR Claude CLI non trouve" -ForegroundColor Red
    Write-Host ""
    Write-Host "Installation requise:" -ForegroundColor Yellow
    Write-Host "  npm install -g @anthropic-ai/claude-code"
    Write-Host ""
    Write-Host "Note: Verifier aussi PATH npm global:" -ForegroundColor Yellow
    Write-Host "  npm config get prefix" -ForegroundColor DarkGray
    Write-Host ""
    exit 1
}

$claudeVersion = & $claudeCmd --version 2>&1
Write-Host "  OK Claude CLI installe: $claudeVersion" -ForegroundColor Green

# Etape 2: Verifier Tailscale connecte
Write-Host "[2/5] Verification Tailscale..." -ForegroundColor Yellow

try {
    $tailscaleStatus = tailscale status 2>&1
    if ($tailscaleStatus -match "friday-vps") {
        Write-Host "  OK Tailscale connecte (VPS accessible)" -ForegroundColor Green
    }
    else {
        Write-Host "  ATTENTION Tailscale connecte mais VPS 'friday-vps' introuvable" -ForegroundColor Yellow
        Write-Host "    Verifier: tailscale status | findstr friday-vps"
    }
}
catch {
    Write-Host "  ERREUR Tailscale non demarre" -ForegroundColor Red
    Write-Host "    Demarrer Tailscale puis relancer ce script"
    exit 1
}

# Etape 3: Tester connexion Redis VPS
Write-Host "[3/5] Test connexion Redis VPS..." -ForegroundColor Yellow

# Redis via SSH tunnel (localhost:6379 forward vers VPS)
# User friday_agents avec password depuis redis.acl
$redisUrl = "redis://friday_agents:REDACTED_REDIS_PASSWORD@localhost:6379/0"

# Simple ping test
$pingResult = Test-Connection -ComputerName friday-vps -Count 1 -Quiet
if (-not $pingResult) {
    Write-Host "  ERREUR VPS friday-vps inaccessible" -ForegroundColor Red
    Write-Host "    Verifier Tailscale: tailscale status"
    exit 1
}

Write-Host "  OK VPS friday-vps accessible" -ForegroundColor Green
Write-Host "    Note: Redis accessible via SSH tunnel (voir start-redis-tunnel.ps1)" -ForegroundColor DarkGray

# Etape 4: Creer fichier .env.desktop
Write-Host "[4/5] Configuration variables d'environnement..." -ForegroundColor Yellow

$envFile = Join-Path $ProjectRoot ".env.desktop"
$hostname = $env:COMPUTERNAME

$envContent = @"
# Friday 2.0 - Desktop Search Consumer Config
# Genere automatiquement: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

# Redis VPS (via SSH tunnel localhost:6379 -> VPS)
# IMPORTANT: Lancer d'abord le tunnel SSH : .\scripts\start-redis-tunnel.ps1
REDIS_URL=$redisUrl

# Claude CLI
CLAUDE_CLI_PATH=claude

# Search paths
SEARCH_BASE_PATH=C:\Users\lopez\BeeStation\Friday\Archives

# Consumer identity
DESKTOP_SEARCH_CONSUMER_NAME=desktop-worker-$hostname

# Timeouts
DESKTOP_SEARCH_TIMEOUT=30
"@

Set-Content -Path $envFile -Value $envContent -Encoding UTF8
Write-Host "  OK Fichier .env.desktop cree" -ForegroundColor Green

# Etape 5: Demarrer consumer (sauf si -ConfigOnly)
if ($ConfigOnly) {
    Write-Host ""
    Write-Host "=== Configuration terminee ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Pour demarrer le consumer:" -ForegroundColor Yellow
    Write-Host "  .\scripts\start-desktop-search.ps1"
    Write-Host ""
    exit 0
}

Write-Host "[5/5] Demarrage consumer Desktop Search..." -ForegroundColor Yellow

# Charger .env.desktop
Get-Content $envFile | ForEach-Object {
    $line = $_
    if ($line -match '^[^#]') {
        $parts = $line.Split('=', 2)
        if ($parts.Count -eq 2) {
            $name = $parts[0].Trim()
            $value = $parts[1].Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

Write-Host "  OK Variables d'environnement chargees" -ForegroundColor Green
Write-Host ""
Write-Host "=== Demarrage consumer (Ctrl+C pour arreter) ===" -ForegroundColor Cyan
Write-Host ""

# Demarrer consumer (venv deja active au debut du script)
python -m agents.src.tools.desktop_search_consumer
