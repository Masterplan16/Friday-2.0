# Self-Healing Runbook - Friday 2.0

**Story 1.13** : Self-Healing Tier 1-2
**Date** : 2026-02-10
**Status** : Production Ready

---

## 📋 Vue d'ensemble

Friday 2.0 implémente un système de self-healing en **4 tiers** pour garantir un uptime de 99%+ (NFR12) avec intervention manuelle minimale.

### Architecture Self-Healing

```
┌─────────────────────────────────────────────────────────┐
│                 INCIDENT DETECTION                      │
│  • RAM > 85%  • Docker crash  • Service loop  • OS     │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                TIER 1: Docker Restart                   │
│  restart: unless-stopped (auto-restart si crash)        │
│  RTO: < 30s (NFR13)                                     │
└────────────────────┬────────────────────────────────────┘
                     │ Si échec ▼
┌─────────────────────────────────────────────────────────┐
│                TIER 2: Auto-Recovery                    │
│  • RAM > 91%: Kill services (TTS→STT→OCR)              │
│  • Crash loop >3: Stop service (prevent infinite)       │
│  • OS updates: Auto-reboot (03:30)                      │
│  RTO: < 2min (NFR13)                                    │
└────────────────────┬────────────────────────────────────┘
                     │ Si échec ▼
┌─────────────────────────────────────────────────────────┐
│                TIER 3-4: Advanced                       │
│  • Détection connecteurs cassés (Epic 12)              │
│  • Détection drift accuracy (Epic 12)                   │
│  • Pattern degradation + ML (Epic 12)                   │
└────────────────────┬────────────────────────────────────┘
                     │ Tous niveaux ▼
┌─────────────────────────────────────────────────────────┐
│             NOTIFICATION & LOGGING                      │
│  Telegram topic System + core.recovery_events           │
└─────────────────────────────────────────────────────────┘
```

---

## 🎯 Tiers Self-Healing

### Tier 1: Docker Restart (AC1)

**Responsabilité** : Redémarrage automatique services crashés

**Mécanisme** :
- Policy `restart: unless-stopped` sur tous services
- Docker daemon gère restart automatiquement
- Pas de code Friday requis (natif Docker)

**RTO** : < 30s (NFR13)

**Vérification** :
```bash
# Valider restart policies
bash scripts/validate-docker-restart-policy.sh docker-compose.yml

# Test crash recovery
docker stop redis
sleep 35
docker ps | grep redis  # Devrait être redémarré
```

**Troubleshooting Tier 1** :
- **Service ne redémarre pas** → Vérifier `docker inspect <service> | jq '.[0].HostConfig.RestartPolicy'`
- **Redémarrage infini** → Vérifier logs `docker logs <service>`, corriger cause racine
- **Restart policy manquant** → Ajouter `restart: unless-stopped` dans docker-compose.yml

---

### Tier 2: Auto-Recovery RAM (AC2, AC3, AC5)

**Responsabilité** : Recovery RAM overload + OS updates

#### Monitoring RAM (AC2)

**Script** : `scripts/monitor-ram.sh`
**Cron** : Toutes les 5 minutes via n8n
**Seuil** : 85% (40.8 Go sur VPS-4 48 Go)

**Alerte** : Telegram topic System si RAM > 85%

**Commandes** :
```bash
# Check RAM manuel
bash scripts/monitor-ram.sh

# Check RAM (JSON output)
bash scripts/monitor-ram.sh --json

# Check RAM + alerte Telegram si > 85%
bash scripts/monitor-ram.sh --telegram
```

#### Auto-Recovery RAM (AC3)

**Script** : `scripts/auto-recover-ram.sh`
**Cron** : Toutes les 5 minutes via n8n (trigger si RAM > 91%)
**Seuil** : 91% (43.7 Go)
**RTO** : < 2 min (NFR13)

**Priority kill order** :
1. **Priority 1** : kokoro-tts (TTS, ~2 Go) — moins critique
2. **Priority 2** : faster-whisper (STT, ~4 Go) — important mais différable
3. **Priority 3** : surya-ocr (OCR, ~2 Go) — essentiel mais pas temps réel

**Services proteges (jamais tues)** : postgres, redis, friday-gateway, friday-bot, n8n, friday-imap-fetcher, presidio [D25 : friday-imap-fetcher remplace emailengine]

**Safety guards** :
- Max 3 services tués par recovery
- Timeout 2 min (NFR13)
- Notification Telegram après chaque recovery

**Commandes** :
```bash
# Test manuel auto-recovery
sudo bash scripts/auto-recover-ram.sh

# Simuler RAM haute (test)
export RAM_PCT=92
bash scripts/auto-recover-ram.sh
```

**Troubleshooting RAM Recovery** :
- **Recovery échoue** → Vérifier logs `/var/log/friday/recovery.log`
- **Services ne redémarrent pas** → Vérifier Docker restart policy (Tier 1)
- **RAM reste haute après recovery** → Identifier service fuyant mémoire : `docker stats`
- **Notification Telegram manquante** → Vérifier env vars `TELEGRAM_BOT_TOKEN`, `TOPIC_SYSTEM_ID`

#### OS Updates (AC4)

**Package** : `unattended-upgrades`
**Setup** : `scripts/setup-unattended-upgrades.sh`
**Reboot time** : 03:30 (après backup 03h00)
**Fréquence** : Max 1x/semaine si kernel update

**Hooks** :
- **Pre-reboot** : Notification Telegram avant reboot
- **Post-reboot** : Notification Telegram + healthcheck complet

**Commandes** :
```bash
# Installer/configurer
sudo bash scripts/setup-unattended-upgrades.sh

# Vérifier status
sudo systemctl status unattended-upgrades

# Logs
sudo tail -f /var/log/unattended-upgrades/unattended-upgrades.log
```

**Troubleshooting OS Updates** :
- **Reboot intempestif** → Vérifier `/var/log/unattended-upgrades/` pour kernel updates
- **Services non redémarrés après reboot** → Exécuter `bash scripts/healthcheck-all.sh`
- **Notifications manquantes** → Vérifier systemd service `friday-post-reboot.service`

---

### Tier 2: Crash Loop Detection (AC6)

**Responsabilité** : Détecter services crashant en boucle et les arrêter

**Script** : `scripts/detect-crash-loop.sh`
**Cron** : Toutes les 10 minutes via n8n
**Threshold** : > 3 restarts en 1h

**Action** : `docker stop <service>` pour prévenir loop infini

**Notification** : Telegram topic System avec logs + diagnostic

**Commandes** :
```bash
# Détection manuelle
bash scripts/detect-crash-loop.sh

# Vérifier RestartCount d'un service
docker inspect --format='{{.RestartCount}}' <service>

# Simuler crash loop (test)
docker run -d --name crash-test --restart unless-stopped alpine sh -c "exit 1"
sleep 60
bash scripts/detect-crash-loop.sh
```

**Troubleshooting Crash Loop** :
- **Faux positif** → Augmenter THRESHOLD_RESTARTS (défaut: 3)
- **Service légitime arrêté** → Restart manuel : `docker start <service>`
- **Cause crash inconnue** → Analyser logs : `docker logs --tail 100 <service>`

---

## 🔔 Notifications Telegram

Toutes les notifications self-healing sont envoyées vers **topic System** (Story 1.9).

### Messages types

**RAM Alert (AC2)** :
```
🟡 Friday RAM Alert

Usage: 87% (41.8/48 GB)
Seuil: 85% (40.8 GB)

Top 5 conteneurs:
• faster-whisper: 4.2 GB
• postgres: 2.1 GB
...

Action: Monitoring continu
```

**Auto-Recovery Success (AC3, AC5)** :
```
✅ Auto-Recovery RAM Successful

Type: RAM overload (91% → 82%)
Services killed: kokoro-tts
RAM freed: ~2 GB
Duration: 18s
Timestamp: 2026-02-10T14:32:05Z

Service will restart automatically when RAM allows.
```

**Crash Loop Detected (AC6)** :
```
🚨 CRASH LOOP DETECTED

Service: surya-ocr
Restarts: 5 in 1h
Status: STOPPED (manual restart required)

Last logs:
RuntimeError: CUDA out of memory

Actions suggérées:
1. Check logs: /recovery surya-ocr
2. Restart: docker start surya-ocr
```

**OS Reboot (AC4)** :
```
🚨 OS reboot imminent (kernel update)
Friday services will restart automatically

---

✅ Friday VPS Rebooted
OS security updates applied successfully.
Healthcheck in progress...
```

---

## 📊 Monitoring & Logs

### Database Tracking

Tous événements recovery sont loggés dans `core.recovery_events` :

```sql
SELECT
    event_type,
    services_affected,
    ram_before,
    ram_after,
    success,
    recovery_duration_seconds,
    created_at
FROM core.recovery_events
ORDER BY created_at DESC
LIMIT 20;
```

### Métriques System

Historique RAM/CPU/Disk dans `core.system_metrics` :

```sql
SELECT
    metric_type,
    value,
    threshold,
    timestamp
FROM core.system_metrics
WHERE metric_type = 'ram_usage_pct'
AND timestamp > NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC;
```

### Commande Telegram `/recovery`

```
/recovery              # 10 derniers événements
/recovery -v           # Détails complets
/recovery stats        # Statistiques (uptime, MTTR)
```

---

## 🛠️ Override Manuel

### Désactiver Auto-Recovery (temporaire)

```bash
# Désactiver workflow n8n auto-recover-ram
n8n workflow:deactivate <workflow_id>

# Désactiver workflow detect-crash-loop
n8n workflow:deactivate <workflow_id>

# Réactiver après maintenance
n8n workflow:activate <workflow_id>
```

### Blacklist service (ne jamais kill)

Éditer `scripts/auto-recover-ram.sh` :

```bash
PROTECTED_SERVICES=(
    "postgres"
    "redis"
    "friday-gateway"
    "friday-bot"
    "n8n"
    "friday-imap-fetcher"   # [D25] remplace emailengine
    "presidio"
    "mon-service-critique"  # Ajouter ici
)
```

### Modifier seuils

```bash
# RAM alert threshold (défaut: 85%)
export RAM_ALERT_THRESHOLD_PCT=90

# RAM recovery threshold (défaut: 91%)
export RAM_RECOVERY_THRESHOLD_PCT=93

# Crash loop threshold (défaut: 3 restarts)
export THRESHOLD_RESTARTS=5
```

---

## 🚨 Common Issues & Solutions

### Issue 1: RAM ne descend pas après recovery

**Symptômes** : Auto-recovery tue services mais RAM reste > 85%

**Causes** :
- Memory leak dans service non lourd
- Cache filesystem important
- PostgreSQL cache trop grand

**Solutions** :
```bash
# Identifier service fuyant
docker stats --no-stream

# Clear filesystem cache (temporaire)
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'

# Réduire PostgreSQL shared_buffers (permanent)
# Éditer postgresql.conf: shared_buffers = 2GB
```

### Issue 2: Service en crash loop après deploy

**Symptômes** : Notification crash loop après mise à jour

**Causes** :
- Nouvelle version bugguée
- Configuration manquante
- Dépendance cassée

**Solutions** :
```bash
# Rollback image Docker
docker tag <service>:<old-version> <service>:latest
docker compose up -d <service>

# Vérifier logs
docker logs --tail 100 <service>

# Restart manuel après fix
docker start <service>
```

### Issue 3: Reboot OS intempestif

**Symptômes** : Reboot sans notification

**Causes** :
- Kernel panic
- OOM killer
- Hardware issue

**Solutions** :
```bash
# Vérifier derniers reboots
last reboot

# Vérifier kernel panic logs
sudo journalctl -k | grep -i "panic\|oom"

# Vérifier OOM kills
dmesg | grep -i "killed process"
```

### Issue 4: Notifications Telegram manquantes

**Symptômes** : Aucune alerte reçue alors que seuil dépassé

**Causes** :
- Variables env non définies
- Topic System ID incorrect
- Token Telegram expiré

**Solutions** :
```bash
# Vérifier env vars
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID
echo $TOPIC_SYSTEM_ID

# Test notification manuel
bash scripts/telegram-notify.sh "Test Friday"

# Vérifier topic ID
# → Comparer avec Telegram app topic thread ID
```

---

## 📚 Références

- **Scripts** : `scripts/monitor-ram.sh`, `scripts/auto-recover-ram.sh`, `scripts/detect-crash-loop.sh`
- **Workflows n8n** : `n8n-workflows/auto-recover-ram.json`, `n8n-workflows/detect-crash-loop.json`
- **Migration** : `database/migrations/020_recovery_events.sql`
- **Story** : [1-13-self-healing-tier-1-2.md](../_bmad-output/implementation-artifacts/1-13-self-healing-tier-1-2.md)
- **Architecture** : [architecture-friday-2.0.md](../architecture-friday-2.0.md) sections contraintes matérielles
- **Unattended Upgrades** : [unattended-upgrades-setup.md](./unattended-upgrades-setup.md)

---

## 📞 Support

Pour assistance :
1. Vérifier logs : `/var/log/friday/`, `docker logs`
2. Exécuter healthcheck : `bash scripts/healthcheck-all.sh`
3. Consulter recovery events : `SELECT * FROM core.recovery_events ORDER BY created_at DESC LIMIT 10`
4. Telegram : `/recovery stats`

**Date** : 2026-02-10
**Version** : 1.0
**Auteur** : Dev Agent (Claude Sonnet 4.5)
