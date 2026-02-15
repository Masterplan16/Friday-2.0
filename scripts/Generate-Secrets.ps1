# Generate-Secrets.ps1 - Génération automatique des secrets manquants pour Friday 2.0
#
# Usage:
#   .\scripts\Generate-Secrets.ps1
#
# Ce script:
#   1. Lit le .env existant (ou crée depuis .env.example)
#   2. Génère les clés/passwords manquants
#   3. Préserve les valeurs existantes (ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, etc.)
#   4. Crée .env.new avec toutes les valeurs complètes
#
# SÉCURITÉ: Le fichier .env généré contient des secrets sensibles.
# Chiffrer avec SOPS avant commit: ./scripts/encrypt-env.sh

param(
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $ProjectRoot) {
    $ProjectRoot = "C:\Users\lopez\Desktop\Friday 2.0"
}

$EnvFilePath = Join-Path $ProjectRoot $EnvFile
$EnvNewPath = Join-Path $ProjectRoot ".env.new"
$EnvExamplePath = Join-Path $ProjectRoot ".env.example"

Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Blue
Write-Host "  Friday 2.0 - Générateur automatique de secrets" -ForegroundColor Blue
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Blue
Write-Host ""

# Fonction: Générer un password aléatoire (base64, 32 bytes)
function Generate-Password {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

# Fonction: Générer une clé hex (64 caractères)
function Generate-HexKey {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ($bytes | ForEach-Object { $_.ToString("x2") }) -join ''
}

# Fonction: Lire une valeur du .env existant
function Get-EnvValue {
    param(
        [string]$Key,
        [string]$FilePath = $EnvFilePath
    )

    if (Test-Path $FilePath) {
        $content = Get-Content $FilePath -Raw
        if ($content -match "(?m)^$Key=(.*)$") {
            return $matches[1].Trim()
        }
    }
    return ""
}

# Vérifier si .env existe
if (-not (Test-Path $EnvFilePath)) {
    if (Test-Path $EnvExamplePath) {
        Write-Host "⚠️  Aucun .env trouvé. Copie depuis .env.example..." -ForegroundColor Yellow
        Copy-Item $EnvExamplePath $EnvFilePath
        Write-Host "✓ .env créé depuis .env.example" -ForegroundColor Green
    } else {
        Write-Host "❌ Erreur: .env.example introuvable!" -ForegroundColor Red
        exit 1
    }
}

Write-Host "📋 Analyse du fichier .env existant..." -ForegroundColor Blue
Write-Host ""

$missingCount = 0
$generatedCount = 0

# Créer le nouveau .env
$envContent = @"
# Friday 2.0 - Environment Variables
# Généré automatiquement par scripts/Generate-Secrets.ps1
# Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss UTC')
#
# ⚠️  IMPORTANT: Ce fichier contient des secrets sensibles
# Chiffrer avant commit: ./scripts/encrypt-env.sh

# ============================================
# PostgreSQL Database
# ============================================

"@

# PostgreSQL
$postgresDb = Get-EnvValue "POSTGRES_DB"
if ([string]::IsNullOrEmpty($postgresDb)) { $postgresDb = "friday" }
$envContent += "POSTGRES_DB=$postgresDb`n"

$postgresUser = Get-EnvValue "POSTGRES_USER"
if ([string]::IsNullOrEmpty($postgresUser)) { $postgresUser = "friday" }
$envContent += "POSTGRES_USER=$postgresUser`n"

$postgresPassword = Get-EnvValue "POSTGRES_PASSWORD"
if ([string]::IsNullOrEmpty($postgresPassword) -or $postgresPassword -like "changeme*") {
    $postgresPassword = Generate-Password
    Write-Host "✓ Généré: POSTGRES_PASSWORD" -ForegroundColor Green
    $generatedCount++
} else {
    Write-Host "→ Préservé: POSTGRES_PASSWORD (existant)" -ForegroundColor Blue
}
$envContent += "POSTGRES_PASSWORD=$postgresPassword`n"

# Redis passwords
$envContent += @"

# ============================================
# Redis - Passwords par service (ACL)
# ============================================

"@

$redisPassword = Get-EnvValue "REDIS_PASSWORD"
if ([string]::IsNullOrEmpty($redisPassword) -or $redisPassword -like "changeme*") {
    $redisPassword = Generate-Password
    Write-Host "✓ Généré: REDIS_PASSWORD" -ForegroundColor Green
    $generatedCount++
} else {
    Write-Host "→ Préservé: REDIS_PASSWORD (existant)" -ForegroundColor Blue
}
$envContent += "REDIS_PASSWORD=$redisPassword`n"

# Générer passwords Redis par service
$services = @("GATEWAY", "BOT", "EMAIL", "ALERTING", "METRICS", "DOCUMENT_PROCESSOR")
foreach ($service in $services) {
    $varName = "REDIS_${service}_PASSWORD"
    $currentValue = Get-EnvValue $varName

    if ([string]::IsNullOrEmpty($currentValue) -or $currentValue -like "changeme*") {
        $newValue = Generate-Password
        Write-Host "✓ Généré: $varName" -ForegroundColor Green
        $generatedCount++
    } else {
        $newValue = $currentValue
        Write-Host "→ Préservé: $varName (existant)" -ForegroundColor Blue
    }

    $envContent += "${varName}=$newValue`n"
}

# n8n
$envContent += @"

# ============================================
# n8n Workflow Automation
# ============================================

"@

$n8nHost = Get-EnvValue "N8N_HOST"
if ([string]::IsNullOrEmpty($n8nHost)) { $n8nHost = "n8n.friday.local" }
$envContent += "N8N_HOST=$n8nHost`n"

$n8nEncryptionKey = Get-EnvValue "N8N_ENCRYPTION_KEY"
if ([string]::IsNullOrEmpty($n8nEncryptionKey) -or $n8nEncryptionKey -like "changeme*") {
    $n8nEncryptionKey = Generate-HexKey
    Write-Host "✓ Généré: N8N_ENCRYPTION_KEY" -ForegroundColor Green
    $generatedCount++
} else {
    Write-Host "→ Préservé: N8N_ENCRYPTION_KEY (existant)" -ForegroundColor Blue
}
$envContent += "N8N_ENCRYPTION_KEY=$n8nEncryptionKey`n"

# API Security
$envContent += @"

# ============================================
# API Security
# ============================================

"@

$apiToken = Get-EnvValue "API_TOKEN"
if ([string]::IsNullOrEmpty($apiToken) -or $apiToken -like "changeme*") {
    $apiToken = Generate-HexKey
    Write-Host "✓ Généré: API_TOKEN" -ForegroundColor Green
    $generatedCount++
} else {
    Write-Host "→ Préservé: API_TOKEN (existant)" -ForegroundColor Blue
}
$envContent += "API_TOKEN=$apiToken`n"

# LLM Provider
$envContent += @"

# ============================================
# LLM Provider - Claude Sonnet 4.5 (D17)
# ============================================

"@

$anthropicApiKey = Get-EnvValue "ANTHROPIC_API_KEY"
if ([string]::IsNullOrEmpty($anthropicApiKey) -or $anthropicApiKey -like "your_*") {
    Write-Host "⚠️  ANTHROPIC_API_KEY manquante - À configurer manuellement" -ForegroundColor Yellow
    $envContent += "ANTHROPIC_API_KEY=your_anthropic_api_key_here`n"
    $missingCount++
} else {
    Write-Host "→ Préservé: ANTHROPIC_API_KEY (existant)" -ForegroundColor Blue
    $envContent += "ANTHROPIC_API_KEY=$anthropicApiKey`n"
}

# Embeddings Provider
$envContent += @"

# ============================================
# Embeddings Provider - Voyage AI (Story 6.2)
# ============================================

"@

$voyageApiKey = Get-EnvValue "VOYAGE_API_KEY"
if ([string]::IsNullOrEmpty($voyageApiKey) -or $voyageApiKey -like "your_*") {
    Write-Host "⚠️  VOYAGE_API_KEY manquante (optionnel Day 1)" -ForegroundColor Yellow
    $envContent += "# VOYAGE_API_KEY=your_voyage_api_key_here`n"
} else {
    Write-Host "→ Préservé: VOYAGE_API_KEY (existant)" -ForegroundColor Blue
    $envContent += "VOYAGE_API_KEY=$voyageApiKey`n"
}

$envContent += "EMBEDDING_PROVIDER=voyage`n"
$envContent += "EMBEDDING_DIMENSIONS=1024`n"

# Memorystore
$envContent += @"

# ============================================
# Memorystore Provider (Story 6.3)
# ============================================

"@

$envContent += "MEMORYSTORE_PROVIDER=postgresql`n"

# Telegram
$envContent += @"

# ============================================
# Telegram Bot (Story 1.9)
# ============================================

"@

$telegramBotToken = Get-EnvValue "TELEGRAM_BOT_TOKEN"
if ([string]::IsNullOrEmpty($telegramBotToken) -or $telegramBotToken -like "your_*") {
    Write-Host "⚠️  TELEGRAM_BOT_TOKEN manquante - À configurer manuellement" -ForegroundColor Yellow
    $envContent += "TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here`n"
    $missingCount++
} else {
    Write-Host "→ Préservé: TELEGRAM_BOT_TOKEN (existant)" -ForegroundColor Blue
    $envContent += "TELEGRAM_BOT_TOKEN=$telegramBotToken`n"
}

$telegramSupergroupId = Get-EnvValue "TELEGRAM_SUPERGROUP_ID"
if ([string]::IsNullOrEmpty($telegramSupergroupId) -or $telegramSupergroupId -eq "-1001234567890") {
    Write-Host "⚠️  TELEGRAM_SUPERGROUP_ID manquante - À configurer manuellement" -ForegroundColor Yellow
    $envContent += "TELEGRAM_SUPERGROUP_ID=-1001234567890`n"
    $missingCount++
} else {
    Write-Host "→ Préservé: TELEGRAM_SUPERGROUP_ID (existant)" -ForegroundColor Blue
    $envContent += "TELEGRAM_SUPERGROUP_ID=$telegramSupergroupId`n"
}

$ownerUserId = Get-EnvValue "OWNER_USER_ID"
if ([string]::IsNullOrEmpty($ownerUserId) -or $ownerUserId -eq "123456789") {
    Write-Host "⚠️  OWNER_USER_ID manquante - À configurer manuellement" -ForegroundColor Yellow
    $envContent += "OWNER_USER_ID=123456789`n"
    $missingCount++
} else {
    Write-Host "→ Préservé: OWNER_USER_ID (existant)" -ForegroundColor Blue
    $envContent += "OWNER_USER_ID=$ownerUserId`n"
}

# Topics Telegram
$envContent += "`n# Thread IDs des 5 topics Telegram`n"
$topics = @{
    "TOPIC_CHAT_PROACTIVE_ID" = "2"
    "TOPIC_EMAIL_ID" = "3"
    "TOPIC_ACTIONS_ID" = "4"
    "TOPIC_SYSTEM_ID" = "5"
    "TOPIC_METRICS_ID" = "6"
}

foreach ($topic in $topics.Keys) {
    $value = Get-EnvValue $topic
    if ([string]::IsNullOrEmpty($value)) {
        $value = $topics[$topic]
        Write-Host "⚠️  $topic défaut: $value (à vérifier)" -ForegroundColor Yellow
    } else {
        Write-Host "→ Préservé: $topic (existant)" -ForegroundColor Blue
    }
    $envContent += "${topic}=$value`n"
}

# Backup & Encryption
$envContent += @"

# ============================================
# Backup & Encryption (Story 1.12)
# ============================================

"@

$agePublicKey = Get-EnvValue "AGE_PUBLIC_KEY"
if ([string]::IsNullOrEmpty($agePublicKey) -or $agePublicKey -like "age1x*") {
    Write-Host "⚠️  AGE_PUBLIC_KEY manquante - Générer avec: bash scripts/generate-age-keypair.sh" -ForegroundColor Yellow
    $envContent += "AGE_PUBLIC_KEY=age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`n"
    $missingCount++
} else {
    Write-Host "→ Préservé: AGE_PUBLIC_KEY (existant)" -ForegroundColor Blue
    $envContent += "AGE_PUBLIC_KEY=$agePublicKey`n"
}

$tailscalePcHostname = Get-EnvValue "TAILSCALE_PC_HOSTNAME"
if ([string]::IsNullOrEmpty($tailscalePcHostname)) { $tailscalePcHostname = "mainteneur-pc" }
$envContent += "TAILSCALE_PC_HOSTNAME=$tailscalePcHostname`n"

# PGP Encryption (D25: renomme depuis EMAILENGINE_ENCRYPTION_KEY)
$envContent += @"

# ============================================
# PGP Encryption - pgcrypto pour emails raw (D25)
# ============================================

"@

$pgpEncryptionKey = Get-EnvValue "PGP_ENCRYPTION_KEY"
# Fallback: essayer ancien nom si nouveau absent
if ([string]::IsNullOrEmpty($pgpEncryptionKey)) {
    $pgpEncryptionKey = Get-EnvValue "EMAILENGINE_ENCRYPTION_KEY"
}
if ([string]::IsNullOrEmpty($pgpEncryptionKey) -or $pgpEncryptionKey -like "changeme*") {
    $pgpEncryptionKey = Generate-HexKey
    Write-Host "✓ Généré: PGP_ENCRYPTION_KEY" -ForegroundColor Green
    $generatedCount++
} else {
    Write-Host "→ Préservé: PGP_ENCRYPTION_KEY (existant)" -ForegroundColor Blue
}
$envContent += "PGP_ENCRYPTION_KEY=$pgpEncryptionKey`n"

# [RETIRÉ D25] WEBHOOK_SECRET et EMAILENGINE_SECRET ne sont plus nécessaires

# Attachments Storage
$envContent += @"

# ============================================
# Attachments Storage (Story 2.4)
# ============================================

"@

$attachmentsStoragePath = Get-EnvValue "ATTACHMENTS_STORAGE_PATH"
if ([string]::IsNullOrEmpty($attachmentsStoragePath)) { $attachmentsStoragePath = "C:\Friday\attachments" }
$envContent += "ATTACHMENTS_STORAGE_PATH=$attachmentsStoragePath`n"

# Monitoring
$envContent += @"

# ============================================
# Monitoring & Logging
# ============================================

"@

$envContent += "LOG_LEVEL=INFO`n"
$envContent += "ENVIRONMENT=production`n"

# Écrire le fichier
$envContent | Out-File -FilePath $EnvNewPath -Encoding UTF8 -NoNewline

# Résumé final
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Blue
Write-Host "✓ Génération terminée !" -ForegroundColor Green
Write-Host ""
Write-Host "📊 Secrets générés automatiquement : $generatedCount" -ForegroundColor Green
Write-Host "⚠️  Variables à configurer manuellement : $missingCount" -ForegroundColor Yellow
Write-Host ""

if ($missingCount -gt 0) {
    Write-Host "Variables manquantes :" -ForegroundColor Yellow
    Write-Host "  - ANTHROPIC_API_KEY (requis)" -ForegroundColor Yellow
    Write-Host "  - TELEGRAM_BOT_TOKEN (requis)" -ForegroundColor Yellow
    Write-Host "  - TELEGRAM_SUPERGROUP_ID (requis)" -ForegroundColor Yellow
    Write-Host "  - OWNER_USER_ID (requis)" -ForegroundColor Yellow
    Write-Host "  - AGE_PUBLIC_KEY (backup)" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "📁 Fichier généré : .env.new" -ForegroundColor Blue
Write-Host ""
Write-Host "Prochaines étapes :" -ForegroundColor Blue
Write-Host "  1. Ouvrir .env.new : notepad .env.new" -ForegroundColor Blue
Write-Host "  2. Ajouter les clés manquantes manuellement" -ForegroundColor Blue
Write-Host "  3. Remplacer .env : Move-Item .env.new .env -Force" -ForegroundColor Blue
Write-Host "  4. Vérifier : bash scripts/verify_env.sh --env-file .env" -ForegroundColor Blue
Write-Host "  5. Chiffrer : ./scripts/encrypt-env.sh" -ForegroundColor Blue
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Blue
