# Fix Tailscale routing avec ProtonVPN
# Ajoute route permanente pour Tailscale (100.0.0.0/8) via interface Wi-Fi
# A executer en PowerShell ADMIN

# Interface Wi-Fi detectee
$wifiIfIndex = 17

Write-Host "Configuration route Tailscale bypass ProtonVPN..." -ForegroundColor Cyan
Write-Host ""

# Supprimer ancienne route si existe
Write-Host "Suppression ancienne route (si existe)..."
route DELETE 100.0.0.0 2>$null

# Ajouter route permanente (-p)
Write-Host "Ajout route permanente: 100.0.0.0/8 via Wi-Fi (ifIndex $wifiIfIndex)..."
route ADD 100.0.0.0 MASK 255.0.0.0 0.0.0.0 IF $wifiIfIndex -p

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Route ajoutee avec succes!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Verification:"
    route PRINT 100.0.0.0
    Write-Host ""
    Write-Host "Test SSH Tailscale:"
    Write-Host "  ssh ubuntu@100.82.171.38" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Erreur lors de l'ajout de la route" -ForegroundColor Red
    Write-Host "Verifiez que PowerShell est lance en ADMIN" -ForegroundColor Yellow
}
