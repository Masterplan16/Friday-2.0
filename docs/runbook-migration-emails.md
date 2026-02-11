# Runbook Opérationnel - Migration 110k Emails

**Version**: 1.0
**Date**: 2026-02-11
**Mainteneur** : Antonio Lopez

---

## ✅ Checklist Pré-Migration

### Infrastructure
- [ ] PostgreSQL 16 opérationnel (`docker ps | grep postgres`)
- [ ] Redis 7 opérationnel (`docker ps | grep redis`)
- [ ] Migrations 001-012 appliquées (`SELECT version FROM core.schema_versions ORDER BY applied_at DESC LIMIT 1`)
- [ ] Table `ingestion.emails_legacy` peuplée (`SELECT COUNT(*) FROM ingestion.emails_legacy` → doit retourner 110k)

### Credentials & Configuration
- [ ] `POSTGRES_DSN` défini (`echo $POSTGRES_DSN | grep -q postgresql && echo OK`)
- [ ] `ANTHROPIC_API_KEY` valide (tester: `curl https://api.anthropic.com/v1/messages -H "x-api-key: $ANTHROPIC_API_KEY"`)
- [ ] `REDIS_URL` valide (`redis-cli ping` → PONG)
- [ ] `VOYAGE_API_KEY` valide (si Phase 3 embeddings)

### Espace & Resources
- [ ] Espace disque VPS >50 Go libre (`df -h | grep /dev/sda`)
- [ ] RAM disponible >35 Go (`free -h`)
- [ ] Tailscale connecté (pour alertes Telegram + backup PC)

### Backup
- [ ] **CRITIQUE** : Backup PostgreSQL complet (`./scripts/backup.sh`)
- [ ] Backup stocké sur PC Mainteneur (`ls -lh ~/backups/friday/`)
- [ ] Test restore backup (`psql < backup.sql` sur DB test)

---

## 🚀 Lancement Migration

### Étape 1 : Dry-Run Test (RECOMMANDÉ)
```bash
# Test sur échantillon 1000 emails
python scripts/migrate_emails.py --dry-run --limit 1000

# Vérifier logs
tail -50 logs/migration.log

# Résultat attendu : "Progress: 1000/1000 (100%)" sans erreurs critiques
```

### Étape 2 : Migration Réelle
```bash
# Screen session (persiste si SSH déconnecte)
screen -S friday-migration

# Lancer migration
python scripts/migrate_emails.py

# Détacher screen : Ctrl+A puis D
# (Migration continue en background)
```

### Étape 3 : Monitoring Actif
```bash
# Terminal 1 : Logs migration
tail -f logs/migration.log

# Terminal 2 : Monitoring RAM (tous les 60s)
watch -n 60 ./scripts/monitor-ram.sh

# Terminal 3 : API usage tracking
watch -n 300 'psql -c "SELECT SUM(cost_usd) FROM core.api_usage WHERE created_at > NOW() - INTERVAL '"'"'1 day'"'"'"'
```

---

## 📊 Durée & Budget Attendus

### Durée
- **Optimiste** : 18-24h
- **Réaliste** : 30-37h
- **Pessimiste** : 40-50h (si rate limits, RAM issues, etc.)

### Phases
- Phase 1 (Classification) : ~9h (optimiste 6h)
- Phase 2 (Graphe) : ~15-20h (optimiste 12h)
- Phase 3 (Embeddings) : ~6-8h (optimiste 4h)

### Coût
- **Claude Sonnet 4.5** : ~$330
- **Voyage AI** : ~$2
- **Total** : **~$332 USD**

**⚠️ ATTENTION** : Dépasse budget initial PRD ($45) → validation Mainteneur requise avant lancement.

---

## 🔄 Resume Après Interruption

### Scénario : Migration crashée ou stoppée

```bash
# 1. Vérifier dernier checkpoint
cat data/migration_checkpoint.json
# → Noter "processed" count

# 2. Vérifier logs erreur
tail -100 logs/migration.log | grep -i error

# 3. Corriger problème si identifié (RAM, API key, etc.)

# 4. Resume migration
python scripts/migrate_emails.py --resume

# 5. Vérifier reprise correcte
tail -f logs/migration.log
# → Doit afficher "Reprise migration: X/110000 deja traites"
```

---

## ⚠️ Gestion Incidents

### RAM >85% (40.8 Go / 48 Go)
**Symptôme** : `./scripts/monitor-ram.sh` alerte
**Action** :
1. Vérifier processus lourds : `top -o %MEM`
2. Si migration cause : pause Ctrl+C → attendre nettoyage → resume
3. Si autre service : redémarrer service gourmand

### Rate Limit 429 Anthropic
**Symptôme** : Logs "API error 429"
**Action** :
1. Arrêter migration (Ctrl+C)
2. Attendre 1 minute
3. Resume avec rate limit réduit : `python scripts/migrate_emails.py --resume --rate-limit 30`

### Presidio Down
**Symptôme** : "Presidio service unavailable"
**Action** :
1. Vérifier : `docker ps | grep presidio`
2. Redémarrer : `docker compose restart presidio`
3. Resume migration : `python scripts/migrate_emails.py --resume`

### PostgreSQL Connection Lost
**Symptôme** : "connection refused" ou "server closed"
**Action** :
1. Vérifier PG : `docker compose ps postgres`
2. Redémarrer si besoin : `docker compose restart postgres`
3. Attendre 30s (PG init)
4. Resume : `python scripts/migrate_emails.py --resume`

---

## ✅ Validation Post-Migration

### SQL Checks
```sql
-- 1. Vérifier counts emails migrés
SELECT COUNT(*) FROM ingestion.emails;
-- Attendu : ~110000 (±1% acceptable)

-- 2. Vérifier graphe nodes
SELECT COUNT(*) FROM knowledge.nodes WHERE type='email';
-- Attendu : ~110000

-- 3. Vérifier embeddings
SELECT COUNT(*) FROM knowledge.embeddings;
-- Attendu : ~110000

-- 4. Vérifier échecs
SELECT COUNT(*) FROM core.migration_failed;
-- Attendu : <1100 (≤1%)

-- 5. Vérifier coût réel
SELECT SUM(cost_usd) FROM core.api_usage
WHERE context='migration_emails';
-- Attendu : ~$332
```

### Tests Fonctionnels
```bash
# Test recherche sémantique (après migration)
# TODO: Implémenter test recherche après Story 6.x
```

---

## 🧹 Cleanup Post-Migration

### Succès Complet
```bash
# 1. Vérifier validation SQL ✓

# 2. Supprimer checkpoint (auto si 100% succès)
# rm data/migration_checkpoint.json

# 3. Archiver logs
mv logs/migration.log logs/migration_$(date +%Y%m%d).log

# 4. Documenter coût réel dans budget tracking
# (core.api_usage déjà rempli automatiquement)
```

### Échecs Partiels (>1%)
```bash
# 1. Analyser DLQ
psql -c "SELECT error_message, COUNT(*) FROM core.migration_failed GROUP BY error_message"

# 2. Décision Mainteneur :
# Option A : Accepter perte <1%
# Option B : Retry manuel DLQ (script custom)
# Option C : Re-migration complète si échec >5%
```

---

## 📞 Contacts & Support

**Mainteneur** : Antonio Lopez
**Docs Technique** : `docs/email-migration-110k.md`
**Architecture** : `_docs/architecture-friday-2.0.md`
**Issues** : Voir `MIGRATION_COMPLETE_STORY_6.4.md` post-migration

---

**Version** : 1.0
**Dernière mise à jour** : 2026-02-11
