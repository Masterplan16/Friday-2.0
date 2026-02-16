# Variables d'Environnement Google Calendar API

## 📋 Variables Requises

Ajouter ces variables dans `.env.enc` (chiffré SOPS/age) :

```bash
# ============================================
# Google Calendar API Configuration
# ============================================

# Enable/Disable Google Calendar sync
GOOGLE_CALENDAR_ENABLED=true

# OAuth2 Credentials (from google_client_secret.json)
GOOGLE_CLIENT_ID=1234567890-abcdefghijklmnop.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-abcdefghijklmnopqrstuvwx

# SOPS Encryption for token.json
GOOGLE_CALENDAR_SOPS_ENABLED=true

# Sync Configuration (optional - defaults in calendar_config.yaml)
GOOGLE_CALENDAR_SYNC_INTERVAL_MINUTES=30
GOOGLE_CALENDAR_SYNC_PAST_DAYS=7
GOOGLE_CALENDAR_SYNC_FUTURE_DAYS=90

# Webhook Configuration (optional - AC7)
GOOGLE_CALENDAR_WEBHOOK_ENABLED=false
GOOGLE_CALENDAR_WEBHOOK_URL=https://friday-vps.tailscale.net/api/v1/webhooks/google-calendar
GOOGLE_CALENDAR_WEBHOOK_TOKEN=<random_secret_token>
```

## 🔧 Comment Obtenir les Valeurs

### GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET

1. Télécharger `google_client_secret.json` depuis Google Cloud Console (voir [config/google_client_secret.README.md](../config/google_client_secret.README.md))
2. Extraire les valeurs :

```bash
# Déchiffrer le fichier (si déjà chiffré)
sops --input-type json --output-type json -d config/google_client_secret.json.enc > /tmp/client_secret.json

# Extraire CLIENT_ID
cat /tmp/client_secret.json | jq -r '.installed.client_id'

# Extraire CLIENT_SECRET
cat /tmp/client_secret.json | jq -r '.installed.client_secret'

# Nettoyer
rm /tmp/client_secret.json
```

3. Copier les valeurs dans `.env` (fichier temporaire)

### GOOGLE_CALENDAR_WEBHOOK_TOKEN

Générer un token aléatoire sécurisé :

```bash
# Générer token 32 caractères
openssl rand -hex 32
```

## 🔐 Chiffrement SOPS

Après avoir modifié `.env`, chiffrer avec SOPS :

```bash
# Chiffrer .env
./scripts/encrypt-env.sh

# Vérifier chiffrement
./scripts/decrypt-env.sh
cat .env | grep GOOGLE_CALENDAR
```

**CRITIQUE :** JAMAIS commit `.env` non chiffré. Seul `.env.enc` doit être dans Git.

## 🚀 Validation

Vérifier que les variables sont correctement chargées :

```bash
# Sur VPS (après déploiement)
ssh friday-vps
cd /opt/friday-2.0
./scripts/decrypt-env.sh
source .env

# Tester variables
echo $GOOGLE_CALENDAR_ENABLED
echo $GOOGLE_CLIENT_ID
```

## 📚 Références

- Story 7.2 AC1 : OAuth2 Authentication
- [config/google_client_secret.README.md](../config/google_client_secret.README.md) : Setup OAuth2
- [scripts/encrypt-env.sh](../scripts/encrypt-env.sh) : Chiffrement SOPS
