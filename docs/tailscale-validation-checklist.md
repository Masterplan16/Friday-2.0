# Tailscale VPN - Checklist de Validation

**Story 1.12 - Task 1.3**
**Dépendance** : Story 1.4 (Tailscale VPN & Sécurité Réseau) doit être complétée

---

## 🎯 Objectif

Valider que Tailscale VPN est correctement configuré pour permettre le sync chiffré des backups du VPS vers le PC Mainteneur.

---

## ✅ Checklist de Validation

### 1️⃣ Installation Tailscale (Sur VPS ET PC)

**VPS:**
```bash
# Vérifier installation
tailscale version

# Output attendu: v1.x.x ou supérieur
```

**PC Mainteneur:**
```bash
# Windows PowerShell
tailscale version

# macOS/Linux
tailscale version
```

- [ ] Tailscale installé sur VPS
- [ ] Tailscale installé sur PC Mainteneur
- [ ] Versions >= v1.x.x

---

### 2️⃣ Authentification & Connexion

**Sur VPS:**
```bash
sudo tailscale status
```

**Vérifications:**
- [ ] Status affiche liste des devices (pas "logged out")
- [ ] VPS apparaît dans la liste avec son hostname
- [ ] Adresse IP Tailscale assignée (100.x.x.x)

**Sur PC Mainteneur:**
```bash
tailscale status
```

- [ ] PC apparaît dans la liste
- [ ] Hostname = `mainteneur-pc` (ou custom défini)
- [ ] Adresse IP Tailscale assignée

---

### 3️⃣ Connectivité Réseau (VPS ↔ PC)

**Depuis VPS, ping vers PC:**
```bash
# Obtenir IP du PC
PC_IP=$(tailscale status | grep mainteneur-pc | awk '{print $1}')

# Test ping
ping -c 3 $PC_IP
```

- [ ] Ping réussi (0% packet loss)
- [ ] Latence raisonnable (<100ms si même pays)

**Depuis PC, ping vers VPS:**
```bash
# Obtenir IP du VPS
VPS_IP=$(tailscale status | grep friday-vps | awk '{print $1}')

# Test ping
ping -n 3 $VPS_IP  # Windows
ping -c 3 $VPS_IP  # Linux/macOS
```

- [ ] Ping réussi (0% packet loss)

---

### 4️⃣ SSH via Tailscale (VPS → PC)

**Prérequis:**
1. SSHD actif sur PC Mainteneur
2. Clé SSH générée et autorisée

**Générer clé SSH sur VPS (si pas déjà fait):**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/friday_backup_key -N ""
```

**Copier clé publique vers PC:**
```bash
# Via Tailscale
ssh-copy-id -i ~/.ssh/friday_backup_key mainteneur@mainteneur-pc
```

**Test connexion:**
```bash
ssh -i ~/.ssh/friday_backup_key mainteneur@mainteneur-pc "echo 'SSH OK'"
```

- [ ] Connexion SSH réussie sans mot de passe
- [ ] Output: "SSH OK"

---

### 5️⃣ Sécurité Tailscale (Dashboard Web)

**URL:** [https://login.tailscale.com/admin/settings/security](https://login.tailscale.com/admin/settings/security)

**Vérifications obligatoires:**

- [ ] **Two-factor authentication (2FA)** : ✅ **Enabled**
- [ ] **Device authorization** : ✅ **Required**
- [ ] Devices VPS & PC = **Approved** (pas "Pending")

**Screenshot recommandé** : Capturer page settings pour audit futur

---

### 6️⃣ Variables Environnement

**Fichier `.env` (ou `.env.enc`) sur VPS:**

```bash
# Vérifier variable
grep TAILSCALE_PC_HOSTNAME .env.example
```

- [ ] `TAILSCALE_PC_HOSTNAME=mainteneur-pc` configuré
- [ ] Hostname correspond au vrai hostname Tailscale du PC

**Test validation automatique:**
```bash
bash scripts/validate-tailscale-connectivity.sh
```

- [ ] Script passe tous les tests (exit code 0)

---

### 7️⃣ Test End-to-End (rsync via Tailscale)

**Créer fichier test sur VPS:**
```bash
mkdir -p /tmp/backup-test
echo "Friday 2.0 backup test $(date)" > /tmp/backup-test/test-file.txt
```

**Sync vers PC via Tailscale:**
```bash
rsync -avz --progress /tmp/backup-test/ mainteneur@mainteneur-pc:/tmp/friday-backup-test/
```

**Vérifier sur PC:**
```bash
# Sur PC
cat /tmp/friday-backup-test/test-file.txt
```

- [ ] Fichier transféré avec succès
- [ ] Contenu identique sur VPS et PC
- [ ] Transfert via Tailscale (pas Internet public)

**Cleanup:**
```bash
# VPS
rm -rf /tmp/backup-test

# PC
rm -rf /tmp/friday-backup-test
```

---

## 🚨 Troubleshooting

### Problème: PC non visible dans `tailscale status`

**Causes possibles:**
1. PC éteint ou en veille
2. Tailscale non démarré sur PC
3. Devices pas sur le même Tailnet (vérifier compte)

**Solution:**
```bash
# Sur PC, redémarrer Tailscale
sudo tailscale down && sudo tailscale up
```

---

### Problème: Ping fonctionne mais SSH échoue

**Causes possibles:**
1. SSHD non actif sur PC
2. Firewall bloque port 22
3. Clé SSH non autorisée

**Solution:**
```bash
# Sur PC, vérifier SSHD
sudo systemctl status sshd  # Linux
# ou
Get-Service sshd  # Windows PowerShell

# Autoriser clé manuellement
mkdir -p ~/.ssh
echo "<PUBLIC_KEY>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

---

### Problème: rsync échoue avec "Permission denied"

**Causes possibles:**
1. Dossier destination n'existe pas
2. Permissions insuffisantes

**Solution:**
```bash
# Sur PC, créer dossier avec bonnes permissions
mkdir -p /mnt/backups/friday-vps
chmod 755 /mnt/backups/friday-vps
chown $USER:$USER /mnt/backups/friday-vps
```

---

## 📊 Validation Finale

**Toutes les cases cochées ?**

- [ ] 1️⃣ Installation (VPS + PC) ✅
- [ ] 2️⃣ Authentification ✅
- [ ] 3️⃣ Connectivité ping ✅
- [ ] 4️⃣ SSH fonctionnel ✅
- [ ] 5️⃣ Sécurité 2FA + Device Auth ✅
- [ ] 6️⃣ Variables env configurées ✅
- [ ] 7️⃣ Test rsync réussi ✅

**Si OUI** → Task 1.3 validée ✅ → Continuer avec Task 2.1 (scripts/backup.sh)

**Si NON** → Résoudre problèmes via section Troubleshooting ou consulter [Story 1.4 docs](../stories/1-4-tailscale-vpn-securite-reseau.md)

---

## 📚 Références

- **Story 1.4** : Tailscale VPN & Sécurité Réseau (dépendance)
- **Tailscale Docs** : [https://tailscale.com/kb/](https://tailscale.com/kb/)
- **SSH Best Practices** : [https://www.ssh.com/academy/ssh/keygen](https://www.ssh.com/academy/ssh/keygen)

---

**Dernière mise à jour** : 2026-02-10 (Story 1.12 - Task 1.3)
