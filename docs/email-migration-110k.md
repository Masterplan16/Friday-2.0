# Migration 110k Emails Historiques - Documentation Technique

**Version**: 1.0
**Date**: 2026-02-11
**Story**: 6.4 - Migration emails historiques

---

## Vue d'ensemble

Migration one-shot de 110 000 emails historiques existants vers Friday 2.0 avec :
- **Phase 1** : Classification Claude Sonnet 4.5 + anonymisation Presidio
- **Phase 2** : Population graphe de connaissances (PostgreSQL + pgvector)
- **Phase 3** : Génération embeddings Voyage AI (1024 dims)

**Durée estimée** : 30-37h (réaliste) | 18-24h (optimiste)
**Coût estimé** : ~$332 USD (~€301 EUR)

---

## Prérequis

### Infrastructure
- PostgreSQL 16 + pgvector 0.6.0 opérationnel
- Redis 7+ opérationnel (mapping Presidio + events)
- Migrations 001-012 appliquées (`scripts/apply_migrations.py`)
- Table `ingestion.emails_legacy` peuplée (110k emails via EmailEngine bulk export)

### Variables d'environnement
```bash
POSTGRES_DSN=postgresql://user:pass@host:5432/friday
ANTHROPIC_API_KEY=sk-ant-...
REDIS_URL=redis://localhost:6379/0
VOYAGE_API_KEY=pa-...  # Pour Phase 3 embeddings
```

### Espace disque
- VPS : >50 Go libres (logs + checkpoints + PostgreSQL growth)
- Backup : ~10 Go (backup PostgreSQL pré-migration)

---

## Architecture Pipeline 3 Phases

```mermaid
sequenceDiagram
    participant Legacy as emails_legacy
    participant Presidio
    participant Claude as Claude Sonnet 4.5
    participant PG as PostgreSQL
    participant Voyage as Voyage AI

    Legacy->>Presidio: Email brut (110k)
    Presidio-->>Legacy: Texte anonymisé
    Legacy->>Claude: Classify (anonymized)
    Claude-->>PG: INSERT ingestion.emails

    PG->>PG: Create nodes (Person, Email)
    PG->>PG: Create edges (SENT_BY, RECEIVED_BY)

    PG->>Presidio: Email text → anonymize
    Presidio-->>Voyage: Generate embedding
    Voyage-->>PG: INSERT knowledge.embeddings
```

---

## Utilisation

### Migration complète
```bash
# Backup OBLIGATOIRE avant migration
./scripts/backup.sh

# Lancer migration (screen session recommandé)
screen -S friday-migration
python scripts/migrate_emails.py

# Détacher : Ctrl+A puis D
# Reattacher : screen -r friday-migration
```

### Options CLI
```bash
# Resume après crash
python scripts/migrate_emails.py --resume

# Dry-run (simulation)
python scripts/migrate_emails.py --dry-run --limit 100

# Limiter nombre emails (tests)
python scripts/migrate_emails.py --limit 1000

# Ajuster rate limit API
python scripts/migrate_emails.py --rate-limit 30  # 30 req/min
```

---

## Monitoring

### Logs
```bash
# Tail logs migration
tail -f logs/migration.log

# Rechercher erreurs
grep -i "error\|fail" logs/migration.log
```

### Métriques temps réel
- **Progress** : Affiché console tous les 10 emails
- **API usage** : Tracking coûts dans `core.api_usage`
- **Échecs** : DLQ dans `core.migration_failed`

### RAM
```bash
# Surveiller RAM pendant migration
watch -n 60 ./scripts/monitor-ram.sh
```

---

## Budget Détaillé

### Claude Sonnet 4.5 (Phase 1 - Classification)
- **Pricing** : $3/1M input + $15/1M output tokens
- **Estimation** : ~600 tokens/email × 110k = 66M tokens
  - Input: 55M × $3/1M = **$165**
  - Output: 11M × $15/1M = **$165**
  - **Subtotal Phase 1** : **~$330**

### Voyage AI (Phase 3 - Embeddings)
- **Pricing** : ~€0.06/1M tokens batch
- **Estimation** : ~300 tokens/email × 110k = 33M tokens
  - **Subtotal Phase 3** : **~$2.20**

### PostgreSQL (Phase 2 - Graphe)
- **Coût** : $0 (local VPS)

### **TOTAL** : **~$332 USD** (~€301 EUR)

---

## Validation Post-Migration

```sql
-- Vérifier counts
SELECT
  (SELECT COUNT(*) FROM ingestion.emails) AS emails_migrated,
  (SELECT COUNT(*) FROM knowledge.nodes WHERE type='email') AS email_nodes,
  (SELECT COUNT(*) FROM knowledge.embeddings) AS embeddings_count;

-- Résultat attendu : ~110k partout (±1% acceptable)

-- Vérifier échecs
SELECT COUNT(*), error_message
FROM core.migration_failed
GROUP BY error_message
ORDER BY COUNT(*) DESC;
```

---

## Troubleshooting

### Erreur : "Presidio service unavailable"
- Vérifier : `docker ps | grep presidio`
- Redémarrer : `docker compose restart presidio`

### Erreur : "Rate limit 429"
- Réduire rate limit : `--rate-limit 30` (défaut 50 RPM)
- Attendre puis `--resume`

### Migration stalled
- Vérifier RAM : `./scripts/monitor-ram.sh`
- Vérifier logs : `tail -f logs/migration.log`
- Resume : `python scripts/migrate_emails.py --resume`

---

## Fichiers Importants

| Fichier | Rôle |
|---------|------|
| `scripts/migrate_emails.py` | Pipeline migration principal (849 lignes) |
| `data/migration_checkpoint.json` | Checkpoint progression (resume) |
| `logs/migration.log` | Logs détaillés migration |
| `database/migrations/012_*.sql` | Table source emails_legacy |

---

## Références

- **Architecture** : `_docs/architecture-friday-2.0.md`
- **Story 6.4** : `_bmad-output/implementation-artifacts/6-4-migration-emails-historiques.md`
- **Runbook** : `docs/runbook-migration-emails.md`
