# 🚀 Déploiement Cleanup RGPD sur VPS Friday

## ✅ Étape 1 : Connexion au VPS

```bash
# Depuis ton PC Windows (PowerShell ou Git Bash)
ssh -i ~/.ssh/id_ed25519_friday friday@friday-vps
```

## 📦 Étape 2 : Déployer les scripts

**Les fichiers sont déjà uploadés dans `/tmp/`** via scp depuis ton PC.

Exécute ces commandes **sur le VPS** :

```bash
# 1. Créer répertoires Friday
sudo mkdir -p /opt/friday-2.0/scripts
sudo mkdir -p /opt/friday-2.0/config/logrotate.d

# 2. Copier scripts
sudo cp /tmp/cleanup-disk.sh /opt/friday-2.0/scripts/
sudo cp /tmp/install-cron-cleanup.sh /opt/friday-2.0/scripts/
sudo cp /tmp/validate-cleanup.sh /opt/friday-2.0/scripts/
sudo cp /tmp/friday-cleanup /opt/friday-2.0/config/logrotate.d/

# 3. Rendre scripts exécutables
sudo chmod +x /opt/friday-2.0/scripts/*.sh

# 4. Fixer ownership
sudo chown -R friday:friday /opt/friday-2.0/

# 5. Vérifier déploiement
ls -lh /opt/friday-2.0/scripts/
```

**Résultat attendu** :
```
-rwxr-xr-x 1 friday friday  16K cleanup-disk.sh
-rwxr-xr-x 1 friday friday 4.2K install-cron-cleanup.sh
-rwxr-xr-x 1 friday friday 7.1K validate-cleanup.sh
```

## ⏰ Étape 3 : Installer le cron (03:05 quotidien)

```bash
# Sur le VPS
sudo bash /opt/friday-2.0/scripts/install-cron-cleanup.sh
```

**Ce script va** :
- ✅ Créer cron entry `5 3 * * *` (03:05 quotidien)
- ✅ Créer `/var/log/friday/`
- ✅ Installer config logrotate
- ✅ Tester dry-run

## 🧪 Étape 4 : Test manuel immédiat (optionnel)

```bash
# Sur le VPS - Test immédiat sans attendre 03:05
sudo -u friday bash /opt/friday-2.0/scripts/cleanup-disk.sh
```

**Vérifier le résultat** :
```bash
# Voir les logs
tail -20 /var/log/friday/cleanup-disk.log

# Vérifier notification Telegram (topic System)
```

## ✅ Étape 5 : Validation finale

```bash
# Sur le VPS
bash /opt/friday-2.0/scripts/validate-cleanup.sh
```

**6 vérifications** :
1. ✅ Purge Presidio (mappings >30j = 0)
2. ✅ Rotation logs Docker + journald
3. ✅ Rotation backups VPS (>30j = 0)
4. ✅ Cleanup zone transit (fichiers >24h = 0)
5. ✅ Cron actif + timing correct `5 3 * * *`
6. ✅ Notification Telegram topic System

**Exit code** :
- `0` = PASS (green ou yellow warnings)
- `1` = FAIL (red errors)

## 📊 Commandes utiles post-déploiement

```bash
# Voir cron installé
crontab -l | grep cleanup

# Voir logs cleanup
tail -f /var/log/friday/cleanup-disk.log

# Tester notification Telegram
bash /opt/friday-2.0/scripts/cleanup-disk.sh --dry-run

# Vérifier espace disque
df -h

# Vérifier taille logs Docker
docker system df

# Vérifier taille logs journald
journalctl --disk-usage
```

## 🎯 Résumé

| Étape | Commande | Statut |
|-------|----------|--------|
| 1. Connexion VPS | `ssh -i ~/.ssh/id_ed25519_friday friday@friday-vps` | ✅ OK |
| 2. Upload fichiers | `scp ...` (déjà fait depuis PC) | ✅ OK |
| 3. Déployer scripts | Voir Étape 2 ci-dessus | ⏳ À faire |
| 4. Installer cron | `sudo bash install-cron-cleanup.sh` | ⏳ À faire |
| 5. Validation | `bash validate-cleanup.sh` | ⏳ À faire |

## 🚨 Troubleshooting

### Erreur "Permission denied" lors de sudo
```bash
# Vérifier que tu es bien l'utilisateur friday
whoami

# Vérifier droits sudo
sudo -l
```

### Cron ne s'exécute pas
```bash
# Vérifier service cron actif
systemctl status cron

# Voir logs cron
grep CRON /var/log/syslog | tail -20
```

### Logs cleanup vides
```bash
# Vérifier permissions répertoire logs
ls -ld /var/log/friday/

# Exécuter manuellement pour debug
bash -x /opt/friday-2.0/scripts/cleanup-disk.sh 2>&1 | tee /tmp/cleanup-debug.log
```

---

**Story 1.15 : Cleanup & Purge RGPD** — Ready for production deployment 🚀
