# Setup PC Backup - Friday 2.0

**Date** : 2026-02-05
**Version** : 1.0.0
**Objectif** : Configuration complète du PC Antonio pour recevoir les backups quotidiens via rsync/Tailscale

---

## 🎯 Vue d'ensemble

Le workflow n8n `backup-daily.json` effectue un `rsync` quotidien (3h du matin) depuis le VPS vers le PC Antonio :

```bash
rsync -avz --progress /backups/ antonio@${TAILSCALE_PC_HOSTNAME}:/mnt/backups/friday-vps/
```

Ce document détaille **TOUTE** la configuration requise sur le PC Antonio.

---

## 📋 Prérequis

| Élément | Requis |
|---------|--------|
| **OS supporté** | Windows 10/11 (WSL2), Linux, macOS |
| **Tailscale** | Installé et connecté (2FA obligatoire) |
| **SSH server** | Actif et accessible via Tailscale |
| **Espace disque** | Minimum 50 Go (estimation backups) |
| **Utilisateur** | Compte `antonio` avec sudo/admin |

---

## 🖥️ Configuration par OS

### **Option 1 : Windows (WSL2 recommandé)**

#### **1.1 Installer WSL2**

```powershell
# PowerShell en admin
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

#### **1.2 Installer SSH server dans WSL**

```bash
# Dans WSL Ubuntu
sudo apt update
sudo apt install openssh-server -y

# Activer SSH
sudo systemctl enable ssh
sudo systemctl start ssh

# Vérifier
sudo systemctl status ssh
```

#### **1.3 Créer utilisateur `antonio` dans WSL**

```bash
# Créer utilisateur (si pas déjà fait)
sudo useradd -m -s /bin/bash antonio
sudo usermod -aG sudo antonio

# Définir mot de passe
sudo passwd antonio
```

#### **1.4 Créer dossier backup**

```bash
# Dans WSL
sudo mkdir -p /mnt/backups/friday-vps
sudo chown antonio:antonio /mnt/backups/friday-vps
sudo chmod 755 /mnt/backups/friday-vps
```

> **Note** : `/mnt/` dans WSL correspond au système de fichiers Windows. Pour accéder depuis Windows : `\\wsl$\Ubuntu-22.04\mnt\backups\friday-vps`

#### **1.5 Obtenir IP WSL pour Tailscale**

```bash
# Dans WSL
ip addr show eth0 | grep inet
```

⚠️ **PROBLÈME** : L'IP WSL change à chaque redémarrage ! Deux solutions :

**Solution A (Recommandée)** : Port forwarding depuis Windows vers WSL

```powershell
# PowerShell en admin
# Forward port 22 de Windows vers WSL
netsh interface portproxy add v4tov4 listenport=22 listenaddress=0.0.0.0 connectport=22 connectaddress=<WSL_IP>

# Exemple si WSL IP = 172.28.176.2
netsh interface portproxy add v4tov4 listenport=22 listenaddress=0.0.0.0 connectport=22 connectaddress=172.28.176.2

# Vérifier
netsh interface portproxy show all
```

Ensuite le VPS se connecte à l'IP Tailscale du PC Windows (le forward redirige vers WSL).

**Solution B** : Tailscale directement dans WSL (plus complexe)

Installer Tailscale dans WSL : https://tailscale.com/kb/1114/wsl/

---

### **Option 2 : Linux natif**

#### **2.1 Installer SSH server**

```bash
# Debian/Ubuntu
sudo apt install openssh-server -y

# Arch
sudo pacman -S openssh

# Activer
sudo systemctl enable sshd
sudo systemctl start sshd
```

#### **2.2 Créer dossier backup**

```bash
sudo mkdir -p /mnt/backups/friday-vps
sudo chown antonio:antonio /mnt/backups/friday-vps
sudo chmod 755 /mnt/backups/friday-vps
```

---

### **Option 3 : macOS**

#### **3.1 Activer SSH server (Remote Login)**

```
System Preferences → Sharing → Remote Login (cocher)
```

#### **3.2 Créer dossier backup**

```bash
sudo mkdir -p /Users/antonio/Backups/friday-vps
sudo chown antonio:staff /Users/antonio/Backups/friday-vps
chmod 755 /Users/antonio/Backups/friday-vps
```

> **Note** : Sur macOS, utiliser `/Users/antonio/Backups/friday-vps` au lieu de `/mnt/backups/friday-vps`. Ajuster la variable `TAILSCALE_PC_BACKUP_PATH` dans n8n.

---

## 🔑 Configuration SSH

### **1. Générer clé SSH sur le VPS**

```bash
# Sur le VPS Friday (via Tailscale SSH)
ssh-gen -t ed25519 -C "friday-vps-backup" -f ~/.ssh/friday_backup_key

# Afficher clé publique
cat ~/.ssh/friday_backup_key.pub
```

### **2. Autoriser clé publique sur le PC**

```bash
# Sur le PC Antonio (WSL/Linux/macOS)
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Copier la clé publique du VPS
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... friday-vps-backup" >> ~/.ssh/authorized_keys

# Permissions
chmod 600 ~/.ssh/authorized_keys
```

### **3. Tester connexion depuis VPS**

```bash
# Sur le VPS
ssh -i ~/.ssh/friday_backup_key antonio@${TAILSCALE_PC_HOSTNAME}

# Si succès → vous êtes connecté au PC !
# Tester rsync
rsync -avz --dry-run /tmp/ antonio@${TAILSCALE_PC_HOSTNAME}:/mnt/backups/friday-vps/test/
```

---

## 🌐 Configuration Tailscale

### **Sur le PC Antonio**

1. Installer Tailscale : https://tailscale.com/download
2. Se connecter avec compte Antonio
3. **ACTIVER 2FA** (obligatoire pour sécurité)
4. **Device authorization** : Settings → Devices → Require device authorization

### **Hostname Tailscale**

Le hostname Tailscale du PC est utilisé dans n8n :

```env
TAILSCALE_PC_HOSTNAME=antonio-pc
```

Pour obtenir le hostname :

```bash
# Sur le PC Antonio
tailscale status

# Exemple output:
# 100.64.1.2   antonio-pc           antonio@     linux   -
```

Le hostname est `antonio-pc` (ou `antonio-pc.tailnet-xxx.ts.net` si FQDN requis).

---

## 💾 Estimation espace disque

| Backup | Taille estimée | Fréquence | Rétention |
|--------|----------------|-----------|-----------|
| **PostgreSQL (core+ingestion)** | ~500 Mo compressé | Quotidien | 7 jours |
| **PostgreSQL (knowledge)** | ~200 Mo compressé | Quotidien | 7 jours |
| **Qdrant snapshots** | ~300 Mo | Quotidien | 7 jours |
| **TOTAL par backup** | **~1 Go** | - | - |
| **TOTAL sur 7 jours** | **~7 Go** | - | Nettoyage auto |

**Marge de sécurité** : Prévoir **30-50 Go** d'espace disque pour backups (inclut croissance future).

---

## 🚨 Que faire si le PC est éteint à 3h du matin ?

**Problème** : Le cron n8n tourne à 3h du matin, mais le PC peut être éteint.

**Solutions** :

### **Solution 1 (Recommandée)** : Retry backup + alerte

Modifier le workflow n8n pour :

1. Tenter rsync à 3h00
2. Si échec (PC offline) :
   - Logger warning
   - Envoyer alerte Telegram : "⚠️ Backup échoué - PC offline. Retry à 9h00."
3. Retry à 9h00 (PC probablement allumé)
4. Si échec encore → Alerte critique

**Code workflow n8n** (node Error Handler) :

```javascript
// Si rsync échoue avec "Connection refused" ou "No route to host"
if (error.includes("refused") || error.includes("No route")) {
  // Planifier retry à 9h00
  await scheduleWorkflow("backup-daily-retry", "0 9 * * *");

  // Alerte Telegram
  await sendTelegram("⚠️ Backup échoué (PC offline). Retry à 9h00.");
}
```

### **Solution 2** : Wake-on-LAN (si PC supporte)

Si le PC supporte Wake-on-LAN :

```bash
# Sur le VPS (avant rsync)
# Envoyer magic packet pour réveiller PC
wakeonlan <MAC_ADDRESS_PC>

# Attendre 30s que PC démarre
sleep 30

# Puis rsync
rsync -avz ...
```

---

## ✅ Checklist validation

- [ ] SSH server actif sur PC (`sudo systemctl status sshd`)
- [ ] Tailscale connecté sur PC (`tailscale status`)
- [ ] Hostname Tailscale correct (`antonio-pc`)
- [ ] Utilisateur `antonio` existe
- [ ] Dossier `/mnt/backups/friday-vps/` créé avec bonnes permissions
- [ ] Clé SSH VPS autorisée (`~/.ssh/authorized_keys`)
- [ ] Test connexion SSH depuis VPS réussi
- [ ] Test rsync dry-run réussi
- [ ] Espace disque >= 50 Go disponible

---

## 🧪 Tests

### **Test 1 : Connexion SSH**

```bash
# Sur VPS
ssh -i ~/.ssh/friday_backup_key antonio@antonio-pc

# Attendu : connexion réussie
```

### **Test 2 : rsync dry-run**

```bash
# Sur VPS
rsync -avz --dry-run /tmp/test.txt antonio@antonio-pc:/mnt/backups/friday-vps/

# Attendu : "sent X bytes  received Y bytes"
```

### **Test 3 : Backup complet**

```bash
# Sur VPS, déclencher manuellement workflow n8n backup-daily
# Vérifier sur PC :
ls -lh /mnt/backups/friday-vps/

# Attendu :
# postgres_20260205_030000.dump.gz
# knowledge_20260205_030000.dump.gz
# qdrant_embeddings_20260205.snapshot
```

---

## 🔧 Troubleshooting

### **Erreur : "Permission denied (publickey)"**

**Cause** : Clé SSH non autorisée ou mauvaises permissions.

**Solution** :
```bash
# Sur PC
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys

# Vérifier que la clé est bien dans authorized_keys
cat ~/.ssh/authorized_keys
```

### **Erreur : "Connection refused"**

**Cause** : SSH server non actif ou port 22 non ouvert.

**Solution** :
```bash
# Vérifier SSH server
sudo systemctl status sshd

# Vérifier port 22 ouvert
sudo netstat -tuln | grep 22
```

### **Erreur : "No route to host"**

**Cause** : Problème Tailscale (PC non connecté au mesh).

**Solution** :
```bash
# Sur PC, vérifier Tailscale
tailscale status

# Si down → redémarrer
sudo tailscale up
```

---

**Créé le** : 2026-02-05
**Version** : 1.0.0
**Contributeur** : Claude (Code Review Adversarial - CRITIQUE #5 fix)
