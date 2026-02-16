#!/usr/bin/env python3
"""Script d'initialisation OAuth2 Google Calendar pour Friday 2.0.

Ce script doit etre execute UNE FOIS sur un PC avec navigateur pour obtenir
le token OAuth2 initial. Le token chiffre sera ensuite copie sur le VPS.

Usage:
    python scripts/google_oauth_init.py

Prerequis:
    - config/google_client_secret.json existe (telecharge depuis Google Cloud Console)
    - SOPS installe (choco install sops sur Windows)
    - age key configuree (~/.age/friday-key.txt)

Ce que fait le script:
    1. Ouvre le navigateur pour autoriser Friday 2.0
    2. Sauvegarde config/google_token.json (temporaire)
    3. Chiffre avec SOPS -> config/google_token.json.enc
    4. Supprime config/google_token.json
    5. Affiche instructions pour copier sur VPS

Note:
    Le token a une duree de vie de 1h, mais contient un refresh_token
    qui permet au daemon VPS de le renouveler automatiquement.
"""

import json
import subprocess
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("ERROR: google-auth-oauthlib n'est pas installe.")
    print("Installation:")
    print("  pip install google-auth-oauthlib==1.2.1")
    sys.exit(1)

# Scopes requis pour Google Calendar
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

# Chemins
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_SECRET_PATH = PROJECT_ROOT / "config" / "google_client_secret.json"
TOKEN_PATH = PROJECT_ROOT / "config" / "google_token.json"
TOKEN_ENC_PATH = PROJECT_ROOT / "config" / "google_token.json.enc"


def main():
    """Point d'entree principal."""
    print("=" * 60)
    print("Friday 2.0 - Initialisation OAuth2 Google Calendar")
    print("=" * 60)
    print()

    # Verifier que client_secret.json existe
    if not CLIENT_SECRET_PATH.exists():
        print(f"ERROR: {CLIENT_SECRET_PATH} introuvable.")
        print()
        print("Instructions:")
        print("1. Aller sur https://console.cloud.google.com/")
        print("2. Creer un projet (ou selectionner un existant)")
        print("3. Activer Google Calendar API")
        print("4. Creer OAuth2 Client ID (Type: Application de bureau)")
        print("5. Telecharger client_secret.json")
        print(f"6. Placer dans {CLIENT_SECRET_PATH}")
        print()
        print("Voir: config/google_client_secret.README.md pour details")
        sys.exit(1)

    print(f"[OK] Client secret trouve: {CLIENT_SECRET_PATH}")
    print()

    # Verifier que SOPS est installe
    try:
        subprocess.run(["sops", "--version"], capture_output=True, check=True)
        print("[OK] SOPS installe")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: SOPS n'est pas installe.")
        print()
        print("Installation Windows:")
        print("  choco install sops")
        print()
        print("Installation Linux/macOS:")
        print("  voir https://github.com/getsops/sops#download")
        sys.exit(1)

    print()
    print("=" * 60)
    print("Etape 1/5 : OAuth2 Flow (ouverture navigateur)")
    print("=" * 60)
    print()
    print("Un navigateur va s'ouvrir pour autoriser Friday 2.0.")
    print("Connectez-vous avec votre compte Google et acceptez les permissions.")
    print()

    try:
        # Creer le flow OAuth2
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), CALENDAR_SCOPES)

        # Lancer le serveur local et ouvrir le navigateur
        print("Ouverture du navigateur...")
        creds = flow.run_local_server(port=0)
        print()
        print("[OK] Autorisation reussie !")
        print()

    except Exception as e:
        print(f"ERROR: OAuth2 flow echoue: {e}")
        sys.exit(1)

    # Etape 2 : Sauvegarder token.json (temporaire)
    print("=" * 60)
    print("Etape 2/5 : Sauvegarde token.json")
    print("=" * 60)
    print()

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else [],
    }

    if hasattr(creds, "expiry") and creds.expiry:
        token_data["expiry"] = creds.expiry.isoformat()

    TOKEN_PATH.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    print(f"[OK] Token sauvegarde: {TOKEN_PATH}")
    print()

    # Etape 3 : Chiffrer avec SOPS
    print("=" * 60)
    print("Etape 3/5 : Chiffrement SOPS")
    print("=" * 60)
    print()

    try:
        result = subprocess.run(
            [
                "sops",
                "--input-type",
                "json",
                "--output-type",
                "json",
                "-e",
                str(TOKEN_PATH),
            ],
            capture_output=True,
            check=True,
            text=True,
        )

        TOKEN_ENC_PATH.write_text(result.stdout, encoding="utf-8")
        print(f"[OK] Token chiffre: {TOKEN_ENC_PATH}")
        print()

    except subprocess.CalledProcessError as e:
        print(f"ERROR: SOPS chiffrement echoue: {e.stderr}")
        print()
        print("Verifiez que votre cle age est configuree:")
        print("  ~/.age/friday-key.txt (Linux/macOS)")
        print("  %USERPROFILE%\\.age\\friday-key.txt (Windows)")
        sys.exit(1)

    # Etape 4 : Supprimer token.json non chiffre
    print("=" * 60)
    print("Etape 4/5 : Suppression token non chiffre")
    print("=" * 60)
    print()

    TOKEN_PATH.unlink()
    print(f"[OK] {TOKEN_PATH} supprime (securite)")
    print()

    # Etape 5 : Instructions copie VPS
    print("=" * 60)
    print("Etape 5/5 : Copie sur VPS")
    print("=" * 60)
    print()
    print("Le token OAuth2 chiffre est pret !")
    print()
    print("Instructions pour copier sur le VPS:")
    print()
    print(f'  scp "{TOKEN_ENC_PATH}" friday-vps:/opt/friday-2.0/config/google_token.json.enc')
    print()
    print("Puis redemarrer le service calendar-sync:")
    print()
    print("  ssh friday-vps 'docker restart friday-calendar-sync'")
    print()
    print("Verifier les logs:")
    print()
    print("  ssh friday-vps 'docker logs friday-calendar-sync --tail 30'")
    print()
    print("=" * 60)
    print("[OK] TERMINE")
    print("=" * 60)


if __name__ == "__main__":
    main()
