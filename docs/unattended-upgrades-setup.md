# Unattended Upgrades Setup - Friday 2.0

**Story 1.13 - AC4** : Configuration OS updates automatiques
**Date** : 2026-02-10
**Status** : Ready for deployment

---

## 📋 Vue d'ensemble

Friday 2.0 utilise `unattended-upgrades` (Ubuntu/Debian) pour appliquer automatiquement les mises à jour de sécurité OS, garantissant un VPS sécurisé 24/7 sans intervention manuelle.

**Caractéristiques** :
- ✅ Security updates automatiques (nightly)
- ✅ Auto-reboot si kernel update (max 1x/semaine, 03:30)
- ✅ Notifications Telegram avant/après reboot
- ✅ Docker restart policy garantit redémarrage services

---

## 🚀 Installation

### Prérequis

- Ubuntu/Debian (testé sur Ubuntu 22.04 LTS)
- Accès root (sudo)
- Variables d'environnement Telegram configurées (optionnel)

### Installation automatique

```bash
# Exécuter script setup
sudo bash /opt/friday/scripts/setup-unattended-upgrades.sh
```

Le script configure automatiquement :
1. Package `unattended-upgrades`
2. Fichier `/etc/apt/apt.conf.d/50unattended-upgrades`
3. Fichier `/etc/apt/apt.conf.d/20auto-upgrades`
4. Hooks Telegram (pre/post reboot)
5. Service systemd `friday-post-reboot.service`

---

## ⚙️ Configuration

### Fichier principal : `/etc/apt/apt.conf.d/50unattended-upgrades`

```bash
// Security updates only (NOT feature updates)
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
};

// Auto-reboot si kernel update
Unattended-Upgrade::Automatic-Reboot "true";

// Reboot time: 03:30 (après backup quotidien 03h00)
Unattended-Upgrade::Automatic-Reboot-Time "03:30";

// Reboot même si utilisateurs connectés (VPS sans GUI)
Unattended-Upgrade::Automatic-Reboot-WithUsers "true";
```

### Fichier activation : `/etc/apt/apt.conf.d/20auto-upgrades`

```bash
APT::Periodic::Update-Package-Lists "1";         # Update daily
APT::Periodic::Download-Upgradeable-Packages "1"; # Download daily
APT::Periodic::AutocleanInterval "7";            # Clean weekly
APT::Periodic::Unattended-Upgrade "1";           # Upgrade daily
```

---

## 🔔 Notifications Telegram

### Pre-reboot Hook

**Fichier** : `/etc/apt/apt.conf.d/51friday-telegram-hooks`

```bash
// Notification AVANT reboot (quand /var/run/reboot-required existe)
DPkg::Pre-Invoke {
    "if [ -f /var/run/reboot-required ]; then /opt/friday/scripts/telegram-notify.sh 'OS reboot imminent (kernel update) - Friday services will restart automatically'; fi";
};
```

**Message Telegram** :
```
🚨 OS reboot imminent (kernel update)
Friday services will restart automatically
```

### Post-reboot Service

**Fichier** : `/etc/systemd/system/friday-post-reboot.service`

```ini
[Unit]
Description=Friday post-reboot notification
After=docker.service network-online.target

[Service]
Type=oneshot
ExecStart=/opt/friday/scripts/telegram-notify.sh "✅ Friday VPS Rebooted"
ExecStartPost=/opt/friday/scripts/healthcheck-all.sh

[Install]
WantedBy=multi-user.target
```

**Message Telegram** :
```
✅ Friday VPS Rebooted

OS security updates applied successfully.
Timestamp: 2026-02-10T03:35:00Z

Healthcheck in progress...
```

Suivi par healthcheck complet (tous services critiques).

---

## 🧪 Tests & Validation

### Test dry-run (simulation)

```bash
# Simuler upgrade sans appliquer
sudo unattended-upgrade --dry-run --debug
```

### Vérifier configuration

```bash
# Status service
sudo systemctl status unattended-upgrades

# Logs upgrades
sudo cat /var/log/unattended-upgrades/unattended-upgrades.log

# Vérifier reboot requis
ls -la /var/run/reboot-required
```

### Forcer upgrade immédiat (test)

```bash
# Déclencher upgrade maintenant
sudo unattended-upgrade --debug
```

### Test notification Telegram

```bash
# Test helper script
sudo /opt/friday/scripts/telegram-notify.sh "Test notification Friday"

# Vérifier envoi
# → Devrait apparaître dans topic System Telegram
```

### Test healthcheck post-reboot

```bash
# Exécuter manuellement
sudo /opt/friday/scripts/healthcheck-all.sh

# Vérifier exit code
echo $?  # 0 = success, 1 = failed
```

---

## 📊 Monitoring & Logs

### Logs upgrades

```bash
# Logs principal
tail -f /var/log/unattended-upgrades/unattended-upgrades.log

# Logs dpkg
tail -f /var/log/unattended-upgrades/unattended-upgrades-dpkg.log
```

### Statistiques

```bash
# Dernières mises à jour installées
grep "INFO Packages that will be upgraded" /var/log/unattended-upgrades/unattended-upgrades.log | tail -n 20

# Derniers reboots
last reboot | head -n 10
```

### Historique reboots

```bash
# Via systemd journal
journalctl -u friday-post-reboot.service

# Via base de données Friday (après migration 020)
psql -c "SELECT * FROM core.recovery_events WHERE event_type='os_reboot' ORDER BY created_at DESC LIMIT 10"
```

---

## 🛠️ Troubleshooting

### Service ne démarre pas

```bash
# Vérifier status
sudo systemctl status unattended-upgrades

# Vérifier configuration
sudo unattended-upgrade --dry-run --debug

# Réinstaller
sudo apt-get install --reinstall unattended-upgrades
```

### Notifications Telegram non envoyées

```bash
# Vérifier variables d'environnement
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID
echo $TOPIC_SYSTEM_ID

# Test direct
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  -d "text=Test" \
  -d "message_thread_id=${TOPIC_SYSTEM_ID}"
```

### Reboot ne se déclenche pas

```bash
# Vérifier /var/run/reboot-required existe
ls -la /var/run/reboot-required

# Vérifier configuration reboot
grep "Automatic-Reboot" /etc/apt/apt.conf.d/50unattended-upgrades

# Forcer reboot manuel si nécessaire
sudo reboot
```

### Services Docker ne redémarrent pas après reboot

```bash
# Vérifier restart policies
bash /opt/friday/scripts/validate-docker-restart-policy.sh docker-compose.yml

# Vérifier status services
docker ps -a

# Restart manuel si nécessaire
docker compose up -d
```

---

## 🔐 Sécurité

### Security-only updates

**IMPORTANT** : Seules les mises à jour de sécurité sont appliquées automatiquement.

Les mises à jour de fonctionnalités (`-updates`) sont **désactivées** pour éviter les regressions inattendues.

### Blacklist packages

Pour exclure des packages spécifiques (ex: PostgreSQL) :

```bash
# Éditer /etc/apt/apt.conf.d/50unattended-upgrades
Unattended-Upgrade::Package-Blacklist {
    "postgresql-16";  # Ne jamais auto-update PostgreSQL
    "redis-server";   # Exemple
};
```

### Timing reboot

**Reboot time configuré** : **03:30** (après backup quotidien 03h00)

**Fréquence max** : 1x/semaine (kernel updates rares)

---

## 📚 Références

- [Ubuntu Unattended Upgrades Guide](https://help.ubuntu.com/community/AutomaticSecurityUpdates)
- [Debian Unattended Upgrades Wiki](https://wiki.debian.org/UnattendedUpgrades)
- Story 1.13 - AC4 : [1-13-self-healing-tier-1-2.md](../_bmad-output/implementation-artifacts/1-13-self-healing-tier-1-2.md)

---

**Date création** : 2026-02-10
**Auteur** : Dev Agent (Claude Sonnet 4.5)
**Story** : 1.13 - Self-Healing Tier 1-2
