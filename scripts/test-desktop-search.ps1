#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Test rapide Desktop Search setup

.DESCRIPTION
    Verifie que Claude CLI, Tailscale, Redis VPS et venv sont operationnels.

.EXAMPLE
    .\test-desktop-search.ps1

.NOTES
    Story 3.3 - Desktop Search via Claude CLI
    Date: 2026-02-16
#>

$ErrorActionPreference = "Continue"  # Continue meme si erreurs
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Friday 2.0 - Test Desktop Search Setup ===" -ForegroundColor Cyan
Write-Host ""

$allOk = $true

# Test 1: Venv existe
Write-Host "[1/5] Test venv Python..." -ForegroundColor Yellow
$venvActivate = Join-Path $ProjectRoot '.venv\Scripts\Activate.ps1'
if (Test-Path $venvActivate) {
    Write-Host "  OK venv existe" -ForegroundColor Green
    . $venvActivate  # Dot sourcing pour modifier l'environnement actuel
} else {
    Write-Host "  ERREUR venv introuvable: $venvActivate" -ForegroundColor Red
    $allOk = $false
}

# Test 2: Claude CLI
Write-Host "[2/5] Test Claude CLI..." -ForegroundColor Yellow
$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if ($null -eq $claudeCmd) {
    Write-Host "  ERREUR Claude CLI introuvable" -ForegroundColor Red
    Write-Host "    PATH: $($env:PATH.Split(';') | Select-Object -First 3)" -ForegroundColor DarkGray
    $allOk = $false
} else {
    $claudeVersion = & $claudeCmd --version 2>&1
    Write-Host "  OK Claude CLI: $claudeVersion" -ForegroundColor Green
    Write-Host "    Chemin: $($claudeCmd.Source)" -ForegroundColor DarkGray
}

# Test 3: Tailscale
Write-Host "[3/5] Test Tailscale..." -ForegroundColor Yellow
try {
    $tailscaleStatus = tailscale status 2>&1
    if ($tailscaleStatus -match "friday-vps") {
        Write-Host "  OK Tailscale connecte (friday-vps accessible)" -ForegroundColor Green
    } else {
        Write-Host "  ATTENTION VPS friday-vps introuvable dans Tailscale" -ForegroundColor Yellow
        Write-Host "    Status: $($tailscaleStatus | Select-Object -First 3)" -ForegroundColor DarkGray
        $allOk = $false
    }
} catch {
    Write-Host "  ERREUR Tailscale non demarre" -ForegroundColor Red
    $allOk = $false
}

# Test 4: Ping VPS
Write-Host "[4/5] Test connexion VPS..." -ForegroundColor Yellow
$pingResult = Test-Connection -ComputerName friday-vps -Count 1 -Quiet
if ($pingResult) {
    Write-Host "  OK VPS friday-vps accessible" -ForegroundColor Green
} else {
    Write-Host "  ERREUR VPS friday-vps inaccessible" -ForegroundColor Red
    $allOk = $false
}

# Test 5: Fichiers Python Desktop Search
Write-Host "[5/5] Test fichiers Python..." -ForegroundColor Yellow
$consumerPath = Join-Path $ProjectRoot 'agents\src\tools\desktop_search_consumer.py'
$wrapperPath = Join-Path $ProjectRoot 'agents\src\tools\desktop_search_wrapper.py'

if ((Test-Path $consumerPath) -and (Test-Path $wrapperPath)) {
    Write-Host "  OK Fichiers Python Desktop Search presents" -ForegroundColor Green
} else {
    Write-Host "  ERREUR Fichiers Python manquants" -ForegroundColor Red
    if (-not (Test-Path $consumerPath)) {
        Write-Host "    Manquant: desktop_search_consumer.py" -ForegroundColor Red
    }
    if (-not (Test-Path $wrapperPath)) {
        Write-Host "    Manquant: desktop_search_wrapper.py" -ForegroundColor Red
    }
    $allOk = $false
}

# Resultat final
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($allOk) {
    Write-Host "SUCCES Tous les tests passes" -ForegroundColor Green
    Write-Host ""
    Write-Host "Pret pour demarrage:" -ForegroundColor Yellow
    Write-Host "  .\scripts\setup-desktop-search.ps1" -ForegroundColor White
} else {
    Write-Host "ECHEC Certains tests ont echoue" -ForegroundColor Red
    Write-Host ""
    Write-Host "Voir les erreurs ci-dessus et corriger avant de lancer setup." -ForegroundColor Yellow
}
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
