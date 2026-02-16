#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Cree tunnel SSH vers Redis VPS

.DESCRIPTION
    Forward port local 6379 vers Redis VPS via SSH tunnel.
    Le consumer Desktop Search se connecte a localhost:6379 qui est forward vers le VPS.

.EXAMPLE
    .\start-redis-tunnel.ps1

.NOTES
    Story 3.3 - Desktop Search
    Date: 2026-02-16
#>

$ErrorActionPreference = "Continue"

Write-Host "=== Friday 2.0 - Redis SSH Tunnel ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Creation tunnel SSH : localhost:6379 -> friday-vps:6379" -ForegroundColor Yellow
Write-Host ""
Write-Host "Le tunnel reste ouvert. Appuyer Ctrl+C pour arreter." -ForegroundColor Yellow
Write-Host ""

# Lancer tunnel SSH (bloquant, reste ouvert)
ssh -N -L 6379:localhost:6379 friday-vps
