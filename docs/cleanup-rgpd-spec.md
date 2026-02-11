# Cleanup & Purge RGPD - Spécification Complète

**Story** : 1.15 - Cleanup automatisé + purge RGPD
**Version** : 1.0
**Date** : 2026-02-10
**Status** : Implémenté

---

## 📋 Vue d'Ensemble

Le système de cleanup automatisé Friday 2.0 effectue 5 opérations quotidiennes pour gérer l'espace disque et respecter les contraintes RGPD :

1. **Purge mappings Presidio** : >30 jours (droit à l'oubli)
2. **Rotation logs Docker** : >7 jours
3. **Rotation logs journald** : >7 jours
4. **Rotation backups VPS** : >30 jours (retention_policy='keep_7_days')
5. **Cleanup zone transit** : fichiers >24h

**Cron** : `5 3 * * *` (03:05 quotidien, après backup 03:00)
**Notification** : Telegram topic System (breakdown par opération)

---

## 🎯 Retention Policies

### Mappings Presidio (RGPD Compliance)

| Donnée | Durée | Storage | Justification |
|--------|-------|---------|---------------|
| Mapping PII (en mémoire) | Durée requête LLM | Mémoire | Éphémère, supprimé après déanonymisation |
| Mapping chiffré (audit trail) | **30 jours** | `core.action_receipts.encrypted_mapping` (pgcrypto) | Debugging via `/receipt <id> --decrypt` |
| **Purge définitive** | **Après 30 jours** | NULL (supprimé) | **RGPD - Droit à l'oubli** |

**Colonne audit** : `purged_at TIMESTAMPTZ` (migration 022)

**Requête cleanup** :
```sql
UPDATE core.action_receipts
SET encrypted_mapping = NULL, purged_at = NOW()
WHERE created_at < NOW() - INTERVAL '30 days'
  AND encrypted_mapping IS NOT NULL
  AND purged_at IS NULL;
```

**Vérification** :
```bash
psql -U friday -d friday -c \
  "SELECT COUNT(*) FROM core.action_receipts
   WHERE encrypted_mapping IS NOT NULL
     AND created_at < NOW() - INTERVAL '30 days';"
# Résultat attendu: 0 (tous purgés)
```

---

### Logs Docker + Journald

| Log Type | Durée | Commande | Rationale |
|----------|-------|----------|-----------|
| Docker containers/images/build cache | **7 jours** | `docker system prune -f --filter "until=168h"` | Standard production |
| Journald system logs | **7 jours** | `journalctl --vacuum-time=7d` | Debugging récent possible |

**Rationale 7 jours** :
- Problèmes récents identifiables en 1 semaine
- Équilibre traçabilité vs espace disque
- Compliance rotation standard

**Vérification** :
```bash
# Docker
docker system df -v  # Avant cleanup
docker system prune -f --filter "until=168h"
docker system df -v  # Après cleanup (reduced usage)

# Journald
journalctl --disk-usage  # Avant cleanup
journalctl --vacuum-time=7d
journalctl --disk-usage  # Après cleanup
```

---

### Backups VPS vs PC

| Location | Retention Policy | Durée | Cleanup Auto |
|----------|------------------|-------|--------------|
| **VPS** | `keep_7_days` | **30 jours max** | ✅ Supprimé après 30j |
| **PC** | `keep_30_days` | Permanent | ❌ Gestion manuelle Mainteneur |
| **Archives** | `keep_forever` | Permanent | ❌ Jamais cleanup |

**Colonne audit** : `deleted_at TIMESTAMPTZ` (migration 023)

**Soft delete pattern** :
```sql
-- Mark backups as deleted (soft delete)
UPDATE core.backup_metadata
SET deleted_at = NOW()
WHERE retention_policy = 'keep_7_days'
  AND backup_date < NOW() - INTERVAL '30 days'
  AND deleted_at IS NULL;
```

**Suppression fichiers** :
```bash
# Get list from database
BACKUPS=$(psql -U friday -d friday -tAc \
    "SELECT filename FROM core.backup_metadata
     WHERE retention_policy = 'keep_7_days'
       AND backup_date < NOW() - INTERVAL '30 days'
       AND deleted_at IS NULL;")

# Delete files from /backups
for filename in $BACKUPS; do
    rm -f "/backups/$filename"
done
```

**Vérification** :
```bash
# Count old VPS backups (should be 0 after cleanup)
psql -U friday -d friday -c \
  "SELECT COUNT(*) FROM core.backup_metadata
   WHERE retention_policy = 'keep_7_days'
     AND backup_date < NOW() - INTERVAL '30 days'
     AND deleted_at IS NULL;"
```

---

### Zone Transit (Fichiers Temporaires)

| Répertoire | Durée | Cleanup | Rationale |
|------------|-------|---------|-----------|
| `/data/transit/uploads/` | **24 heures** | `find -mtime +1 -delete` | Fichiers traités en <1h normalement |

**Workflow normal** :
1. Fichier arrive (Telegram/Syncthing) → `/data/transit/uploads/`
2. Archiviste traite (OCR, classification) → quelques minutes
3. Fichier final sync PC (Syncthing) → <1h
4. Fichier source supprimé

**Cas anormal** : Fichier bloqué (erreur traitement, sync échoué) → cleanup après 24h

**Commande cleanup** :
```bash
# Delete files older than 24h
find /data/transit/uploads/ -type f -mtime +1 -delete
```

**Note** : `-type f` = seulement fichiers, préserve subdirectories

**Vérification** :
```bash
# List files >24h (should be 0 after cleanup)
find /data/transit/uploads/ -type f -mtime +1 | wc -l
```

---

## ⏰ Timing & Coordination Cron

### Timeline Nuit

| Heure | Opération | Story | Cron |
|-------|-----------|-------|------|
| 03:00 | Backup PostgreSQL | 1.12 | `0 3 * * *` |
| 03:00 | Watchtower check images | 1.14 | `0 3 * * *` |
| **03:05** | **Cleanup disk** | **1.15** | **`5 3 * * *`** |
| 03:30 | OS unattended-upgrades | 1.13 | `30 3 * * *` |
| 08:00 | Briefing matinal | 4.2 | `0 8 * * *` |

**Rationale 03:05** :
- Cleanup APRÈS backup (backup crée fichier, cleanup peut supprimer anciens)
- 5 min marge = suffisant pour backup PostgreSQL (~1-2 min sur VPS-4 48 Go)

### Configuration Cron

```bash
# Installer cron entry
crontab -e

# Ajouter ligne :
5 3 * * * /opt/friday-2.0/scripts/cleanup-disk.sh >> /var/log/friday/cleanup-disk.log 2>&1
```

**Vérification** :
```bash
# Lister cron entries
crontab -l | grep cleanup-disk

# Check logs
tail -f /var/log/friday/cleanup-disk.log
```

---

## 📊 Notification Telegram

### Format Message (Success)

```
🧹 Cleanup Quotidien - 2026-02-10 03:05

✅ Status: Success

📊 Espace libéré:
  • Presidio mappings: 125 enregistrements purgés
  • Logs Docker: 1.2 GB
  • Logs journald: 450 MB
  • Backups VPS: 3.8 GB (2 fichiers)
  • Zone transit: 85 MB

💾 Total libéré: 5.5 GB
⏱️  Durée: 42s
```

### Format Message (Partial - avec erreurs)

```
🧹 Cleanup Quotidien - 2026-02-10 03:05

⚠️  Status: Partial

✅ Presidio mappings: OK (125 purgés)
✅ Logs Docker: OK (1.2 GB)
❌ Logs journald: ERREUR (permission denied)
✅ Backups VPS: OK (3.8 GB)
✅ Zone transit: OK (85 MB)

💾 Total libéré: 5.1 GB
⏱️  Durée: 38s

⚠️  Vérifier logs: /var/log/friday/cleanup-disk.log
```

**Topic** : System (notifications infrastructure non-critiques)

---

## 🛠️ Utilisation

### Exécution Manuelle

```bash
# Cleanup normal
bash scripts/cleanup-disk.sh

# Dry-run (preview sans suppression réelle)
bash scripts/cleanup-disk.sh --dry-run

# Check logs
tail -f /var/log/friday/cleanup-disk.log
```

### Variables d'Environnement

```bash
# Database
POSTGRES_USER=friday
POSTGRES_DB=friday
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Telegram
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_SUPERGROUP_ID=<chat_id>
TOPIC_SYSTEM_ID=<thread_id>

# Paths
TRANSIT_DIR=/data/transit/uploads
LOG_FILE=/var/log/friday/cleanup-disk.log
```

---

## 🧪 Tests

### Tests Unitaires (4 tests)

```bash
# Test Presidio cleanup SQL
pytest tests/unit/test_cleanup_presidio.py -v

# Test commandes Docker/journald
pytest tests/unit/test_cleanup_logs.py -v

# Test retention_policy backups
pytest tests/unit/test_cleanup_backups.py -v

# Test find command transit
pytest tests/unit/test_cleanup_transit.py -v
```

### Tests Intégration (2 tests)

```bash
# Test E2E cleanup complet
bash tests/integration/test_cleanup_end_to_end.sh

# Test partial failure handling
bash tests/integration/test_cleanup_partial_failure.sh
```

**Coverage Goals** :
- Script cleanup-disk.sh : 80%+
- Migrations SQL : 100%
- Notification Telegram : 80%+

---

## 🚨 Troubleshooting

### Problème : Mappings Presidio non purgés

**Symptôme** :
```bash
psql -U friday -d friday -c \
  "SELECT COUNT(*) FROM core.action_receipts
   WHERE encrypted_mapping IS NOT NULL
     AND created_at < NOW() - INTERVAL '30 days';"
# Résultat: > 0 (devrait être 0)
```

**Solutions** :
1. Vérifier migration 022 appliquée :
   ```bash
   psql -U friday -d friday -c \
     "SELECT column_name FROM information_schema.columns
      WHERE table_name='action_receipts' AND column_name='purged_at';"
   # Devrait retourner: purged_at
   ```
2. Exécuter cleanup manuel :
   ```bash
   bash scripts/cleanup-disk.sh
   ```
3. Vérifier logs :
   ```bash
   grep "Presidio" /var/log/friday/cleanup-disk.log
   ```

---

### Problème : Docker prune échoue (permission denied)

**Symptôme** :
```
ERROR: Cannot connect to the Docker daemon
```

**Solutions** :
1. Vérifier Docker daemon actif :
   ```bash
   systemctl status docker
   ```
2. Vérifier permissions user :
   ```bash
   groups friday  # Devrait inclure 'docker'
   sudo usermod -aG docker friday
   ```
3. Relancer Docker :
   ```bash
   sudo systemctl restart docker
   ```

---

### Problème : Backups VPS toujours présents après cleanup

**Symptôme** :
```bash
ls -lh /backups/*.dump.age | wc -l
# Résultat: > expected (backups >30j toujours présents)
```

**Solutions** :
1. Vérifier migration 023 appliquée :
   ```bash
   psql -U friday -d friday -c \
     "SELECT column_name FROM information_schema.columns
      WHERE table_name='backup_metadata' AND column_name='deleted_at';"
   ```
2. Vérifier retention_policy dans DB :
   ```bash
   psql -U friday -d friday -c \
     "SELECT filename, backup_date, retention_policy, deleted_at
      FROM core.backup_metadata
      WHERE backup_date < NOW() - INTERVAL '30 days'
      ORDER BY backup_date DESC;"
   ```
3. Cleanup manuel :
   ```bash
   bash scripts/cleanup-disk.sh
   ```

---

### Problème : Notification Telegram non reçue

**Symptôme** : Aucun message dans topic System après cleanup

**Solutions** :
1. Vérifier variables env :
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_SUPERGROUP_ID
   echo $TOPIC_SYSTEM_ID
   ```
2. Tester curl manuel :
   ```bash
   curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
     -d "chat_id=${TELEGRAM_SUPERGROUP_ID}" \
     -d "message_thread_id=${TOPIC_SYSTEM_ID}" \
     -d "text=Test cleanup notification" \
     -d "parse_mode=HTML"
   ```
3. Vérifier logs script :
   ```bash
   grep "Telegram" /var/log/friday/cleanup-disk.log
   ```

---

### Problème : Zone transit fichiers récents supprimés

**Symptôme** : Fichiers <24h incorrectement supprimés

**Solutions** :
1. Vérifier timestamp fichiers :
   ```bash
   ls -lt /data/transit/uploads/
   ```
2. Tester find command (dry-run) :
   ```bash
   find /data/transit/uploads/ -type f -mtime +1 -print
   # Devrait lister SEULEMENT fichiers >24h
   ```
3. Vérifier system clock :
   ```bash
   date  # Vérifier date/heure système correcte
   timedatectl status
   ```

---

## 📚 Références

### Documentation Architecture

- [_docs/architecture-friday-2.0.md](_docs/architecture-friday-2.0.md) — VPS-4 48 Go, budget, zone transit
- [_docs/architecture-addendum-20260205.md](_docs/architecture-addendum-20260205.md) — Section 9.1 : Lifecycle mapping Presidio, purge 30 jours

### Code Existant

- [database/migrations/019_backup_metadata.sql](../database/migrations/019_backup_metadata.sql) — Table backup_metadata avec retention_policy
- [database/migrations/011_trust_system.sql](../database/migrations/011_trust_system.sql) — Table action_receipts (encrypted_mapping)
- [scripts/monitor-ram.sh](../scripts/monitor-ram.sh) — Pattern script bash + Telegram notification

### Standards RGPD

- **Droit à l'oubli** : Mappings PII supprimés définitivement après 30 jours
- **Audit trail** : Colonnes `purged_at`, `deleted_at` pour traçabilité
- **Minimisation données** : Texte anonymisé reste (analyse Trust Layer possible), mapping supprimé

---

**Version** : 1.0
**Dernière mise à jour** : 2026-02-10
**Mainteneurs** : Friday 2.0 Team
