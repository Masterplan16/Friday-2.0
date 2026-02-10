# Friday 2.0 - Guide de Stockage Sécurisé de la Clé Privée age

**Story 1.12 - Task 1.2 - Subtask 1.2.3**

---

## 🎯 Objectif

Ce guide explique comment stocker de manière sécurisée la clé privée age générée pour les backups chiffrés de Friday 2.0.

**RÈGLE ABSOLUE** : La clé privée age **NE DOIT JAMAIS** être sur le VPS. Elle reste **UNIQUEMENT** sur le PC du Mainteneur.

---

## 🔐 Principe de Sécurité

### Chiffrement Asymétrique age

| Composant | Localisation | Usage | Sensibilité |
|-----------|--------------|-------|-------------|
| **Clé Publique** | VPS (`.env.enc`) | Chiffrer backups | ✅ Peut être partagée |
| **Clé Privée** | PC Mainteneur | Déchiffrer backups | ❌ TOP SECRET |

**Défense en profondeur** :
- Si le VPS est compromis → Backups chiffrés sont illisibles sans la clé privée PC
- Attaquant doit compromettre DEUX systèmes (VPS + PC) pour accéder aux données

---

## 📁 Emplacement Recommandé (Par OS)

### Linux / macOS

**Emplacement** : `~/.age/friday-backup-key.txt`

```bash
# Permissions strictes
chmod 600 ~/.age/friday-backup-key.txt
chmod 700 ~/.age

# Vérifier
ls -la ~/.age/
# Output attendu: -rw------- (600)
```

**Partition chiffrée** :
- **Linux** : LUKS (disk encryption setup via Ubuntu installer)
- **macOS** : FileVault (Préférences Système → Sécurité → FileVault)

### Windows

**Emplacement** : `C:\Users\<user>\.age\friday-backup-key.txt`

```powershell
# Créer dossier
mkdir $env:USERPROFILE\.age

# Stocker clé
# (copier contenu depuis script generate-age-keypair.sh)
notepad $env:USERPROFILE\.age\friday-backup-key.txt

# Permissions NTFS
icacls "$env:USERPROFILE\.age\friday-backup-key.txt" /inheritance:r
icacls "$env:USERPROFILE\.age\friday-backup-key.txt" /grant:r "$env:USERNAME:(R,W)"
```

**Partition chiffrée** : BitLocker (Panneau de configuration → Chiffrement de lecteur BitLocker)

---

## 🛡️ Niveaux de Sécurité (Choisir selon profil)

### Niveau 1 : Basique (Minimum acceptable)

✅ **Setup rapide, sécurité correcte**

1. Stocker clé dans `~/.age/friday-backup-key.txt`
2. Permissions 600 (Linux/macOS) ou NTFS restreintes (Windows)
3. Partition OS chiffrée (BitLocker/LUKS/FileVault)

**Protection contre** : Vol physique PC, accès non autorisé au disque

---

### Niveau 2 : Standard (Recommandé)

✅ **Équilibre sécurité/praticité**

**Tout du Niveau 1 +**

4. Backup clé dans **password manager** (1Password, Bitwarden, KeePass)
5. Note sécurisée avec :
   ```
   Titre: Friday 2.0 Backup - age Private Key
   Type: Secure Note
   Contenu: [copier clé privée complète depuis friday-backup-key.txt]
   ```

**Protection contre** : Perte/crash du PC, oubli mot de passe, corruption disque

**Password Managers recommandés** :
- [1Password](https://1password.com/) - Payant, UI excellente
- [Bitwarden](https://bitwarden.com/) - Open-source, gratuit/premium
- [KeePassXC](https://keepassxc.org/) - Open-source, local, gratuit

---

### Niveau 3 : Paranoïaque (Maximum sécurité)

✅ **Pour données ultra-sensibles**

**Tout du Niveau 2 +**

6. **Clé privée elle-même chiffrée** avec passphrase :
   ```bash
   # Chiffrer la clé privée
   age -p < ~/.age/friday-backup-key.txt > ~/.age/friday-backup-key.txt.age

   # Supprimer clé en clair
   shred -u ~/.age/friday-backup-key.txt  # Linux
   # ou
   rm -P ~/.age/friday-backup-key.txt     # macOS
   ```

7. **Yubikey ou FIDO2** pour protection physique (optionnel, advanced)

8. **Backup offline** : Copie de la clé sur clé USB chiffrée, stockée dans coffre-fort physique

**Protection contre** : Attaque sophistiquée, malware, vol password manager

---

## ✅ Checklist Stockage Sécurisé

Cocher après setup :

- [ ] Clé privée stockée dans `~/.age/friday-backup-key.txt` (ou équivalent Windows)
- [ ] Permissions 600 (Linux/macOS) ou NTFS restreintes (Windows)
- [ ] Partition OS chiffrée activée (BitLocker/LUKS/FileVault)
- [ ] Clé privée **JAMAIS** commitée dans git (vérifier avec `git grep AGE-SECRET-KEY`)
- [ ] Clé privée **JAMAIS** envoyée par email/Slack/autre
- [ ] Backup clé dans password manager (Niveau 2+)
- [ ] Test de déchiffrement réussi (voir section Tests ci-dessous)

---

## 🧪 Tests de Validation

### Test 1 : Déchiffrement fonctionnel

```bash
# Créer fichier test chiffré
echo "Friday 2.0 test backup" | age -r <AGE_PUBLIC_KEY> > test.age

# Déchiffrer avec clé privée
age -d -i ~/.age/friday-backup-key.txt test.age

# Output attendu: Friday 2.0 test backup
```

### Test 2 : Clé privée absente du repo

```bash
cd /path/to/Friday-2.0

# Chercher clé privée dans repo (doit retourner 0 résultats)
git grep -i "AGE-SECRET-KEY"

# Exit code attendu: 1 (aucun match trouvé)
```

### Test 3 : Permissions correctes

```bash
# Linux/macOS
stat -c "%a" ~/.age/friday-backup-key.txt
# Output attendu: 600

# Windows PowerShell
icacls "$env:USERPROFILE\.age\friday-backup-key.txt"
# Doit montrer : Utilisateur uniquement (R,W)
```

---

## 🚨 Que Faire en Cas de Compromission Suspectée ?

**Si vous pensez que la clé privée a été compromise** :

1. **IMMÉDIATEMENT** : Générer nouveau keypair :
   ```bash
   bash scripts/generate-age-keypair.sh
   ```

2. Mettre à jour `AGE_PUBLIC_KEY` dans `.env.enc` (VPS) avec nouvelle clé publique

3. **Re-chiffrer tous les backups existants** :
   ```bash
   # Déchiffrer avec ancienne clé
   age -d -i ~/.age/old-key.txt backup.dump.gz.age > backup.dump.gz

   # Re-chiffrer avec nouvelle clé
   age -r <NEW_PUBLIC_KEY> < backup.dump.gz > backup.dump.gz.age
   ```

4. Détruire ancienne clé privée de manière sécurisée :
   ```bash
   shred -u -n 7 ~/.age/old-key.txt  # Linux
   # ou
   rm -P ~/.age/old-key.txt          # macOS
   ```

5. Enquêter sur la cause de la compromission

---

## 📚 Références

- **age Documentation** : [https://github.com/FiloSottile/age](https://github.com/FiloSottile/age)
- **age Best Practices** : [https://blog.sandipb.net/2023/07/06/age-encryption-cookbook/](https://blog.sandipb.net/2023/07/06/age-encryption-cookbook/)
- **SOPS + age** : [docs/secrets-management.md](./secrets-management.md)

---

## ℹ️ Support

**Questions ou problèmes ?**
- Consulter : [docs/backup-and-recovery-runbook.md](./backup-and-recovery-runbook.md)
- Telegram : Commande `/help backup`

---

**Dernière mise à jour** : 2026-02-10 (Story 1.12 - Task 1.2)
