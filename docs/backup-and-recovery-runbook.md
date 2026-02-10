# Friday 2.0 - Backup & Recovery Runbook

**Story 1.12 - Task 4.1**

## 🎯 Recovery Time Objective (RTO)

**Objectif** : < 2 heures du disaster au système opérationnel

---

## 🚨 Scénario Disaster Recovery

### Étape 1: Récupération backup depuis PC (10 min)

```bash
# Sur PC Mainteneur
cd /mnt/backups/friday-vps
LATEST_BACKUP=$(ls -t friday_backup_*.age | head -1)

# Déchiffrer backup avec clé privée
age -d -i ~/.age/friday-backup-key.txt "$LATEST_BACKUP" > restored.dump
```

### Étape 2: Transfert vers nouveau VPS (15 min)

```bash
# Upload vers nouveau VPS via Tailscale
rsync -avz restored.dump mainteneur@new-vps:/tmp/
```

### Étape 3: Restore PostgreSQL (30 min)

```bash
# Sur nouveau VPS
# Créer DB vierge
docker compose up -d postgres

# Appliquer migrations (schemas)
python scripts/apply_migrations.py

# Restore data
pg_restore -U friday -d friday -c /tmp/restored.dump
```

### Étape 4: Vérifications (20 min)

```bash
# Vérifier données restaurées
psql -U friday -d friday -c "SELECT COUNT(*) FROM core.backup_metadata"
psql -U friday -d friday -c "SELECT COUNT(*) FROM ingestion.emails_legacy"

# Démarrer tous services
docker compose up -d

# Vérifier health
curl http://localhost:8000/api/v1/health
```

### Étape 5: Redémarrage services (25 min)

```bash
# n8n, bot, gateway, tous services
docker compose up -d

# Vérifier logs
docker compose logs -f
```

**Total estimé : ~100 min (< 2h RTO ✅)**

---

## 📞 Troubleshooting Commun

### Problème: Backup corrupt

**Solution :** Utiliser backup J-1 ou J-2

### Problème: Clé privée perdue

**Solution :** Récupérer depuis password manager (voir docs/age-private-key-storage-guide.md)

### Problème: PC offline pendant backup 3h

**Solution :** Retry automatique à 9h (workflow n8n)

---

**Dernière mise à jour** : 2026-02-10 (Story 1.12)
