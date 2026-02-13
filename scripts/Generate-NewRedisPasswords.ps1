# Génère de nouveaux mots de passe Redis sécurisés (32 caractères, alphanumeric + special)
# Usage: .\scripts\Generate-NewRedisPasswords.ps1

$ErrorActionPreference = "Stop"

function New-SecurePassword {
    param(
        [int]$Length = 32
    )

    # Caractères autorisés (alphanumeric + quelques spéciaux compatibles URL)
    $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_@#%"

    $password = -join ((1..$Length) | ForEach-Object {
        $chars[(Get-Random -Minimum 0 -Maximum $chars.Length)]
    })

    return $password
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Génération nouveaux mots de passe Redis" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$passwords = @{
    "REDIS_ADMIN_PASSWORD" = New-SecurePassword
    "REDIS_GATEWAY_PASSWORD" = New-SecurePassword
    "REDIS_AGENTS_PASSWORD" = New-SecurePassword
    "REDIS_ALERTING_PASSWORD" = New-SecurePassword
    "REDIS_METRICS_PASSWORD" = New-SecurePassword
    "REDIS_N8N_PASSWORD" = New-SecurePassword
    "REDIS_BOT_PASSWORD" = New-SecurePassword
    "REDIS_EMAIL_PASSWORD" = New-SecurePassword
    "REDIS_DOCUMENT_PROCESSOR_PASSWORD" = New-SecurePassword
    "REDIS_EMAILENGINE_PASSWORD" = New-SecurePassword
}

# Afficher les nouveaux mots de passe
Write-Host "Nouveaux mots de passe générés :" -ForegroundColor Green
Write-Host ""
foreach ($key in $passwords.Keys | Sort-Object) {
    Write-Host "$key=$($passwords[$key])" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Étapes suivantes :" -ForegroundColor Cyan
Write-Host "1. Copier ces variables dans un fichier temporaire" -ForegroundColor White
Write-Host "2. Sur le VPS : créer /tmp/new-redis-passwords.env" -ForegroundColor White
Write-Host "3. Exécuter le script de rotation Redis ACL" -ForegroundColor White
Write-Host "4. Mettre à jour .env.enc avec sops" -ForegroundColor White
Write-Host "5. Redémarrer les services Friday" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Exporter au format .env
$envContent = ""
foreach ($key in $passwords.Keys | Sort-Object) {
    $envContent += "$key=$($passwords[$key])`n"
}

# Sauvegarder dans un fichier temporaire LOCAL (à transférer sur VPS)
$tempFile = "c:\Users\lopez\Desktop\Friday 2.0\new-redis-passwords.env"
$envContent | Out-File -FilePath $tempFile -Encoding UTF8 -NoNewline
Write-Host "Fichier généré : $tempFile" -ForegroundColor Green
Write-Host "ATTENTION : Ce fichier contient des secrets, à supprimer après utilisation !" -ForegroundColor Red
Write-Host ""
