#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Démarre le Desktop Search consumer Friday 2.0

.DESCRIPTION
    Script simple pour démarrer le consumer Desktop Search.
    Charge automatiquement .env.desktop si existe.

.EXAMPLE
    .\start-desktop-search.ps1

.NOTES
    Story 3.3 - Desktop Search via Claude CLI
    Date: 2026-02-16
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Friday 2.0 - Desktop Search Consumer ===" -ForegroundColor Cyan
Write-Host ""

# Charger .env.desktop si existe
$envFile = Join-Path $ProjectRoot ".env.desktop"
if (Test-Path $envFile) {
    Write-Host "Chargement configuration: .env.desktop" -ForegroundColor Yellow
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
            Write-Host "  $name=$value" -ForegroundColor DarkGray
        }
    }
    Write-Host ""
} else {
    Write-Host "⚠ Fichier .env.desktop introuvable" -ForegroundColor Yellow
    Write-Host "  Lancer d'abord: .\scripts\setup-desktop-search.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# Activer venv si existe
$venvActivate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    Write-Host "Activation virtualenv..." -ForegroundColor Yellow
    . $venvActivate  # Dot sourcing pour modifier l'environnement actuel
    Write-Host ""
}

# Vérifier Claude CLI disponible
try {
    $null = claude --version 2>&1
} catch {
    Write-Host "✗ Claude CLI non trouvé" -ForegroundColor Red
    Write-Host "  Installer: npm install -g @anthropic-ai/claude-code" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# Démarrer consumer
Write-Host "Démarrage consumer (Ctrl+C pour arrêter)..." -ForegroundColor Green
Write-Host ""

python -m agents.src.tools.desktop_search_consumer
