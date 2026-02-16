#!/usr/bin/env python3
"""Script simple pour décrypter .env.enc et ouvrir dans notepad."""
import os
import subprocess
import sys

# Définir la clé age
os.environ["SOPS_AGE_KEY_FILE"] = os.path.expanduser("~/.age/friday-key.txt")

# Décrypter
print("Décryptage de .env.enc...")
try:
    result = subprocess.run(
        [
            r"C:\Users\lopez\bin\sops.exe",
            "-d",
            "--input-type",
            "dotenv",
            "--output-type",
            "dotenv",
            ".env.enc",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # Écrire dans fichier temporaire
    with open(".env.decrypted", "w", encoding="utf-8") as f:
        f.write(result.stdout)

    print("✅ Fichier décrypté : .env.decrypted")
    print("📝 Ouverture dans notepad...")

    # Ouvrir notepad
    subprocess.run(["notepad", ".env.decrypted"], check=True)

    # Demander si on re-chiffre
    response = input("\nVoulez-vous re-chiffrer le fichier ? (o/n) : ")
    if response.lower() == "o":
        print("Re-chiffrement...")
        with open(".env.decrypted", "r", encoding="utf-8") as f:
            content = f.read()

        result = subprocess.run(
            [r"C:\Users\lopez\bin\sops.exe", "-e", "/dev/stdin"],
            input=content,
            capture_output=True,
            text=True,
            check=True,
        )

        with open(".env.enc", "w", encoding="utf-8") as f:
            f.write(result.stdout)

        os.remove(".env.decrypted")
        print("✅ Fichier re-chiffré et .env.decrypted supprimé")
    else:
        print("⚠️  N'oubliez pas de supprimer .env.decrypted")

except subprocess.CalledProcessError as e:
    print(f"❌ Erreur : {e}")
    print(f"Sortie : {e.stderr}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Erreur : {e}")
    sys.exit(1)
