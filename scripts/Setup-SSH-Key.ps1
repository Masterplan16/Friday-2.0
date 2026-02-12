# Setup SSH Key pour connexion VPS sans mot de passe
# Usage: .\scripts\Setup-SSH-Key.ps1

$VPS_IP = "54.37.231.98"
$VPS_USER = "ubuntu"
$SSH_KEY_PATH = "$env:USERPROFILE\.ssh\id_ed25519_friday"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Configuration cle SSH Friday VPS" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Etape 1 : Verifier si cle existe deja
$keyExists = Test-Path $SSH_KEY_PATH
if ($keyExists) {
    Write-Host "Cle SSH trouvee : $SSH_KEY_PATH" -ForegroundColor Green
}
if (-not $keyExists) {
    Write-Host "Generation nouvelle cle SSH..." -ForegroundColor Yellow

    $sshDir = "$env:USERPROFILE\.ssh"
    $dirExists = Test-Path $sshDir
    if (-not $dirExists) {
        New-Item -ItemType Directory -Path $sshDir | Out-Null
    }

    ssh-keygen -t ed25519 -f $SSH_KEY_PATH -N '""' -C "friday-vps-key"

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Cle SSH generee avec succes" -ForegroundColor Green
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Erreur lors de la generation de la cle" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""

# Etape 2 : Copier cle publique vers VPS
Write-Host "Copie de la cle publique vers VPS..." -ForegroundColor Yellow
Write-Host "Vous allez devoir entrer le mot de passe VPS une derniere fois." -ForegroundColor Yellow
Write-Host ""

$publicKey = Get-Content "$SSH_KEY_PATH.pub"
$sshCommand = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$publicKey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo 'Cle ajoutee avec succes'"

ssh "$VPS_USER@$VPS_IP" $sshCommand

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Cle publique copiee sur le VPS" -ForegroundColor Green
}
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Erreur lors de la copie de la cle" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Etape 3 : Tester connexion sans mot de passe
Write-Host "Test connexion SSH sans mot de passe..." -ForegroundColor Yellow

ssh -i $SSH_KEY_PATH -o "StrictHostKeyChecking=no" "$VPS_USER@$VPS_IP" "echo 'Connexion reussie sans mot de passe!'"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Configuration terminee ! SSH fonctionne sans mot de passe" -ForegroundColor Green

    $sshConfigPath = "$env:USERPROFILE\.ssh\config"
    $configEntry = "`n# Friday VPS`nHost friday-vps`n    HostName $VPS_IP`n    User $VPS_USER`n    IdentityFile $SSH_KEY_PATH`n    StrictHostKeyChecking yes`n"

    $configExists = Test-Path $sshConfigPath
    if ($configExists) {
        $configContent = Get-Content $sshConfigPath -Raw
        $hasEntry = $configContent -match "Host friday-vps"
        if (-not $hasEntry) {
            Add-Content -Path $sshConfigPath -Value $configEntry
            Write-Host "Alias 'friday-vps' ajoute" -ForegroundColor Green
        }
    }
    if (-not $configExists) {
        Set-Content -Path $sshConfigPath -Value $configEntry.TrimStart()
        Write-Host "Fichier config cree avec alias 'friday-vps'" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Vous pouvez maintenant vous connecter avec :" -ForegroundColor Cyan
    Write-Host "  ssh friday-vps" -ForegroundColor White
    Write-Host "  OU" -ForegroundColor Yellow
    Write-Host "  ssh -i $SSH_KEY_PATH $VPS_USER@$VPS_IP" -ForegroundColor White
}
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Connexion echouee - verifier configuration" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
