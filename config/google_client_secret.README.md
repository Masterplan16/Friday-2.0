# Configuration Google OAuth2 Client Secret

## 📋 Prérequis

Fichier requis pour l'authentification Google Calendar API (Story 7.2).

## 🔧 Setup

### 1. Créer le client OAuth2 dans Google Cloud Console

1. Aller sur [Google Cloud Console](https://console.cloud.google.com)
2. Créer ou sélectionner un projet
3. Activer **Google Calendar API** :
   - APIs & Services → Library
   - Rechercher "Google Calendar API"
   - Cliquer "Enable"
4. Configurer OAuth2 Consent Screen :
   - APIs & Services → OAuth consent screen
   - User Type: External (pour usage personnel)
   - App name: "Friday 2.0"
   - User support email: votre email
   - Developer contact: votre email
   - Scopes: Ajouter `.../auth/calendar` et `.../auth/calendar.events`
   - Test users: Ajouter votre email Gmail
5. Créer OAuth2 Client ID :
   - APIs & Services → Credentials
   - Create Credentials → OAuth client ID
   - Application type: **Desktop app**
   - Name: "Friday 2.0 Desktop"
   - Télécharger le JSON → Sauvegarder comme `google_client_secret.json`

### 2. Chiffrer avec SOPS

```bash
# Copier le fichier téléchargé
cp ~/Downloads/client_secret_*.json config/google_client_secret.json

# Chiffrer avec SOPS (age)
sops --input-type json --output-type json -e config/google_client_secret.json > config/google_client_secret.json.enc

# Supprimer le fichier non chiffré (CRITIQUE - NE PAS COMMIT EN CLAIR)
rm config/google_client_secret.json

# Vérifier le chiffrement
sops --input-type json --output-type json -d config/google_client_secret.json.enc | jq .
```

### 3. Ajouter au .gitignore

Le fichier `.gitignore` doit contenir :

```
# Google OAuth2 credentials - NEVER commit unencrypted
config/google_client_secret.json
config/token.json
```

Seuls les fichiers `.enc` (chiffrés) peuvent être commit.

## 📝 Variables d'environnement requises

Ajouter dans `.env.enc` :

```bash
# Google Calendar API
GOOGLE_CLIENT_ID=<client_id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<client_secret>
GOOGLE_CALENDAR_ENABLED=true
GOOGLE_CALENDAR_SOPS_ENABLED=true
```

**Note:** Extraire `GOOGLE_CLIENT_ID` et `GOOGLE_CLIENT_SECRET` du fichier `google_client_secret.json` téléchargé.

## 🔐 Sécurité

- ✅ TOUJOURS chiffrer avec SOPS avant commit
- ❌ JAMAIS commit `google_client_secret.json` en clair
- ❌ JAMAIS commit `token.json` (généré après OAuth2 flow)
- ✅ Utiliser SOPS decrypt uniquement en production VPS

## 🚀 First-run Authentication

Lors du premier démarrage :

1. Friday détecte absence de `token.json.enc`
2. Lance OAuth2 flow → Navigateur s'ouvre
3. Connexion Gmail → Accepter scopes Calendar
4. Token sauvegardé dans `token.json.enc` (auto-chiffré)
5. Refresh automatique toutes les 1h

## 📚 References

- [Google Calendar API - Python Quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)
- [OAuth2 for Installed Apps](https://developers.google.com/identity/protocols/oauth2/native-app)
- [SOPS Encryption](https://github.com/getsops/sops)
