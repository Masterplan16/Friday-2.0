# n8n Workflows - Spécifications Day 1

**Date** : 2026-02-09
**Version** : 1.2.0 (D19 : pgvector remplace Qdrant Day 1)
**Auteur** : Architecture Friday 2.0

---

## Vue d'ensemble

Ce document spécifie les **3 workflows n8n critiques** pour le Day 1 de Friday 2.0. Ces workflows orchestrent les pipelines d'ingestion et les tâches système.

**Frontière n8n vs LangGraph** :
- **n8n** → Workflows data (ingestion, cron, webhooks, fichiers)
- **LangGraph** → Logique agent IA (décisions, raisonnement, multi-steps)

---

## Workflow 1 : Email Ingestion Pipeline

**Fichier** : `n8n-workflows/email-ingestion.json`
**Priorité** : **CRITIQUE** (socle du Moteur Vie)
**Description** : Ingestion automatique des emails via EmailEngine → Classification → Stockage PostgreSQL → Événements Redis

### Diagramme

```
[EmailEngine Webhook] → [Validation] → [Appel FastAPI Gateway]
                                            ↓
                                    [Classification LLM]
                                            ↓
                                    [Insert PostgreSQL]
                                            ↓
                                    [Publish Redis event]
                                            ↓
                                    [Trigger agents downstream]
```

### Nodes détaillés

| # | Node | Type | Configuration |
|---|------|------|---------------|
| 1 | **Email Received** | Webhook | Trigger : POST `/webhook/emailengine`<br>Authentification : Bearer token (env `N8N_WEBHOOK_SECRET`)<br>Payload : JSON EmailEngine |
| 2 | **Validate Payload** | Function | Valider structure : `{account, messageId, from, to, subject, text, html, attachments}`<br>Rejeter si invalide → Log error |
| 3 | **Extract Attachments** | Code | Extraire liste PJ : `attachments.map(a => ({filename: a.filename, contentId: a.contentId}))`<br>Stocker paths temporaires |
| 4 | **Call Classification API** | HTTP Request | POST `http://gateway:8000/api/v1/emails/classify`<br>Body : `{subject, text_preview: text.slice(0, 500), sender: from.address}`<br>Headers : `Authorization: Bearer ${FRIDAY_API_KEY}`<br>Response : `{category, priority, confidence, keywords}` |

> **Note** : Cet endpoint sera cree dans Story 2 (Email Agent). Il n'existe pas en Story 1.
> En attendant, le workflow utilise un webhook passif qui stocke les emails bruts dans `ingestion.emails`.
| 5 | **Insert Email PostgreSQL** | Postgres | Schema : `ingestion.emails`<br>Columns : `message_id, account, sender, recipients, subject, body_text, body_html, category, priority, confidence, received_at, processed_at`<br>Return `id` (UUID) |
| 6 | **Publish Redis Event** | Redis Streams | Stream : `email.received`<br>Payload : `{email_id, category, priority, has_attachments}`<br>**Note : Redis Streams (pas Pub/Sub) pour garantir delivery même si consumer temporairement down** |
| 7 | **Trigger Attachment Processing** | Condition | If `attachments.length > 0` :<br>  → POST `http://gateway:8000/api/v1/documents/process-attachments`<br>  Body : `{email_id, attachments}` |
| 8 | **Error Handler** | On Error | Log error → `core.pipeline_errors`<br>Send Telegram alert via `http://bot:3000/alert` |

### Variables d'environnement requises

```env
N8N_WEBHOOK_SECRET=<secret_token>
FRIDAY_API_KEY=<api_key>
EMAILENGINE_WEBHOOK_URL=http://n8n:5678/webhook/emailengine
POSTGRES_CONN=postgresql://friday:password@postgres:5432/friday
REDIS_URL=redis://redis:6379
```

### Configuration EmailEngine (externe à n8n)

EmailEngine doit envoyer un webhook pour chaque nouvel email :
```bash
# Configurer EmailEngine pour appeler le webhook n8n
curl -X POST http://emailengine:3000/v1/settings/webhooks \
  -H "Authorization: Bearer $EMAILENGINE_TOKEN" \
  -d '{
    "url": "http://n8n:5678/webhook/emailengine",
    "events": ["messageNew"]
  }'
```

---

## Workflow 2 : Briefing Daily

**Fichier** : `n8n-workflows/briefing-daily.json`
**Priorité** : **HAUTE** (module Briefing matinal)
**Description** : Génération quotidienne du briefing matinal → Agrégation données tous modules → Envoi Telegram

### Diagramme

```
[Cron 7h00] → [Aggregate Data] → [Generate Briefing] → [Send Telegram]
                    ↓                    ↓                    ↓
             [PostgreSQL]          [LLM API]         [Telegram Bot]
           (emails, tasks,     (résumé structuré)
            events, alerts)
```

### Nodes détaillés

| # | Node | Type | Configuration |
|---|------|------|---------------|
| 1 | **Daily Trigger** | Cron | Schedule : `0 7 * * *` (7h00 tous les jours)<br>Timezone : `Europe/Paris` |
| 2 | **Get Pending Tasks** | Postgres | Query : `SELECT title, priority, due_date FROM core.tasks WHERE status='pending' AND assigned_to='Mainteneur' ORDER BY priority DESC, due_date ASC LIMIT 10` |
| 3 | **Get Today Events** | Postgres | Query : `SELECT title, date_start, location FROM core.events WHERE DATE(date_start) = CURRENT_DATE ORDER BY date_start ASC` |

> **Dependance** : Les tables `core.tasks` et `core.events` doivent etre creees dans la migration 002_core_tables.sql (Story 1). Le Briefing Daily (Story 4) ne fonctionnera pleinement qu'apres Story 2+ (donnees reelles).
| 4 | **Get Urgent Emails** | Postgres | Query : `SELECT subject, sender, category FROM ingestion.emails WHERE priority='high' AND processed_at > NOW() - INTERVAL '24 hours' ORDER BY received_at DESC LIMIT 5` |
| 5 | **Get Trust Alerts** | Postgres | Query : `SELECT module, action, status, confidence FROM core.action_receipts WHERE status='pending' AND created_at > NOW() - INTERVAL '24 hours'` |
| 6 | **Get Module Summaries** | HTTP Request | POST `http://gateway:8000/api/v1/modules/daily-summaries`<br>Response : `{finance: {...}, thesis: {...}, legal: {...}}` |
| 7 | **Aggregate Data** | Code | Construire objet JSON :<br>`{tasks, events, emails, alerts, module_summaries, date: new Date().toISOString()}` |
| 8 | **Generate Briefing** | HTTP Request | POST `http://gateway:8000/api/v1/briefing/generate`<br>Body : aggregated data<br>Response : `{briefing_text, briefing_tts_url}` (LLM génère résumé structuré) |
| 9 | **Send Telegram Text** | HTTP Request | POST `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`<br>Body : `{chat_id: ${TELEGRAM_CHAT_ID}, text: briefing_text, parse_mode: 'Markdown'}` |
| 10 | **Send Telegram Voice** | HTTP Request | POST `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendVoice`<br>Body : `{chat_id: ${TELEGRAM_CHAT_ID}, voice: briefing_tts_url}` (Kokoro TTS généré par Gateway) |
| 11 | **Log Completion** | Postgres | Insert `core.system_logs` : `{event: 'briefing.sent', status: 'success', timestamp: NOW()}` |
| 12 | **Error Handler** | On Error | Log error → Telegram alert "Briefing quotidien échoué" |

### Variables d'environnement requises

```env
TELEGRAM_BOT_TOKEN=<bot_token>
TELEGRAM_CHAT_ID=<antonio_chat_id>
POSTGRES_CONN=postgresql://friday:password@postgres:5432/friday
FRIDAY_API_KEY=<api_key>
```

### Notifications proactives

Le briefing inclut automatiquement :
- ✅ Tâches urgentes du jour
- ✅ Événements agenda
- ✅ Emails prioritaires non traités
- ✅ Alertes Trust Layer (actions en attente validation)
- ✅ Résumés modules (thèses, finance, contrats, etc.)

---

## Workflow 3 : Backup Daily

**Fichier** : `n8n-workflows/backup-daily.json`
**Priorité** : **CRITIQUE** (résilience système)
**Description** : Backup quotidien PostgreSQL (+ pgvector D19) → Sync vers PC via Tailscale → Retention 7 jours

### Diagramme

```
[Cron 3h00] → [Backup PostgreSQL (+ pgvector D19)]
                    ↓
              [Compress .gz]
                    ↓
              [Sync Tailscale]
                    ↓
              [Cleanup old backups (>7 jours)]
```

> **[D19] pgvector remplace Qdrant Day 1** : Les embeddings sont stockes dans PostgreSQL via pgvector.
> Le pg_dump sauvegarde tout (schemas core, ingestion, knowledge + embeddings pgvector) en une seule operation.
> Pas de snapshot Qdrant separe necessaire.

### Nodes détaillés

| # | Node | Type | Configuration |
|---|------|------|---------------|
| 1 | **Nightly Trigger** | Cron | Schedule : `0 3 * * *` (3h00 tous les jours)<br>Timezone : `Europe/Paris` |
| 2 | **Backup PostgreSQL** | Execute Command | Command : `pg_dump -h postgres -U friday -d friday -F c -f /backups/postgres_$(date +%Y%m%d_%H%M%S).dump`<br>Working dir : `/opt/friday/backups`<br>Timeout : 10 min |

> **Configuration Docker** : Le volume `/backups` doit etre monte dans docker-compose.yml :
> ```yaml
> n8n:
>   volumes:
>     - friday_backups:/backups
> ```
| 3 | **Compress PostgreSQL Backup** | Execute Command | Command : `gzip -9 /backups/postgres_*.dump` (compress le dernier dump) |
| ~~4~~ | ~~**Backup Qdrant Snapshots**~~ | ~~HTTP Request~~ | **[D19] Supprime.** pgvector integre dans PostgreSQL, sauvegarde via pg_dump (pas de snapshot Qdrant separe). Les embeddings sont inclus dans le dump PostgreSQL du node 2. |
| ~~5~~ | ~~**Backup Knowledge Schema**~~ | ~~Execute Command~~ | **[D19] Supprime.** Le schema knowledge.* (incluant les tables pgvector) est sauvegarde par le pg_dump global du node 2. Un backup separe du schema knowledge n'est plus necessaire. |
| ~~6~~ | ~~**Compress Knowledge Backup**~~ | ~~Execute Command~~ | **[D19] Supprime.** Plus de dump knowledge separe a compresser. |
| 7 | **Sync to PC via Tailscale** | Execute Command | Command : `rsync -avz --progress /backups/ mainteneur@${TAILSCALE_PC_HOSTNAME}:/mnt/backups/friday-vps/`<br>(Tailscale permet rsync direct VPS vers PC via hostname Tailscale)<br>Timeout : 30 min |
| 8 | **Cleanup Old Backups (VPS)** | Execute Command | Command : `find /backups -name "*.dump.gz" -mtime +7 -delete`<br>(Supprime fichiers >7 jours) [D19] Plus de fichiers .snapshot Qdrant a nettoyer. |
| 9 | **Verify Backup Size** | Code | Check file sizes :<br>`ls -lh /backups/postgres_latest.dump.gz`<br>If < 10 MB → Warning (backup potentiellement incomplet)<br>[D19] Un seul dump PostgreSQL a verifier (inclut pgvector). |
| 10 | **Log Success** | Postgres | Insert `core.system_logs` : `{event: 'backup.completed', status: 'success', backup_size_mb, timestamp}` |
| 11 | **Send Telegram Confirmation** | HTTP Request | POST Telegram : "Backup quotidien termine — PostgreSQL (+ pgvector D19): X MB (core+ingestion+knowledge)" |
| 11 | **Error Handler** | On Error | Log error → Telegram alert "🚨 Backup échoué — Vérifier logs VPS" |

### Variables d'environnement requises

```env
POSTGRES_CONN=postgresql://friday:password@postgres:5432/friday
TAILSCALE_PC_HOSTNAME=mainteneur-pc
TELEGRAM_BOT_TOKEN=<bot_token>
TELEGRAM_CHAT_ID=<antonio_chat_id>
```

> **[D19]** : La variable `QDRANT_URL` a ete retiree. pgvector remplace Qdrant Day 1 — les embeddings sont dans PostgreSQL, sauvegardes via pg_dump.

> **Note (2026-02-05)** : La variable `ZEP_URL` a ete supprimee suite au code review adversarial. Zep a cesse ses operations en 2024.
>
> **Note (2026-02-09, D19)** : `QDRANT_URL` retiree. pgvector remplace Qdrant Day 1. Le graphe de connaissances utilise desormais PostgreSQL (+ pgvector D19) pour le schema knowledge.* et les embeddings, via `adapters/memorystore.py`. Reevaluation Qdrant possible post-Day 1 si besoin de recherche vectorielle avancee (filtrage, scoring hybride).

> **Recommandation** : Utiliser le hostname Tailscale (`mainteneur-pc`) au lieu de l'IP pour eviter les problemes de rotation d'adresse. Ex: `TAILSCALE_PC_HOSTNAME=mainteneur-pc`

### Configuration SSH/rsync (PC)

Le PC Mainteneur doit :
1. Être connecté à Tailscale
2. Avoir un utilisateur `mainteneur` avec clé SSH autorisée depuis le VPS
3. Avoir un dossier `/mnt/backups/friday-vps/` avec permissions write

```bash
# Sur le PC Mainteneur
mkdir -p /mnt/backups/friday-vps
chmod 755 /mnt/backups/friday-vps

# Autoriser clé SSH du VPS
cat vps_id_rsa.pub >> ~/.ssh/authorized_keys
```

### Strategie de restauration

En cas de disaster recovery :
```bash
# 1. Restaurer PostgreSQL complet (core + ingestion + knowledge + pgvector embeddings)
gunzip postgres_20260205_030000.dump.gz
pg_restore -h localhost -U friday -d friday -c postgres_20260205_030000.dump
```

> **[D19] pgvector restaure automatiquement avec pg_restore.** Un seul dump contient tout : schemas core, ingestion, knowledge, et les embeddings pgvector. Pas de restauration Qdrant separee necessaire.
>
> **Note historique (2026-02-05)** : Les etapes de restauration Zep ont ete supprimees (Zep ferme 2024). Les etapes de restauration Qdrant ont ete supprimees avec D19 (pgvector remplace Qdrant Day 1). Reevaluation Qdrant possible post-Day 1.

---

## Workflows additionnels (non Day 1)

Ces workflows seront implémentés post-Story 1 :

| Workflow | Description | Priorité |
|----------|-------------|----------|
| `csv-import.json` | Import automatique CSV bancaires depuis dossier surveillé | P1 |
| `plaud-watch.json` | Watch Google Drive pour nouveaux fichiers Plaud Note | P1 |
| `file-processing.json` | Pipeline OCR + classification documents uploadés via Telegram | P1 |
| `calendar-sync.json` | Sync bidirectionnel Google Calendar ↔ Friday | P2 |
| `thesis-reminder.json` | Vérification hebdomadaire activité étudiants thèses | P2 |
| `warranty-reminder.json` | Alertes proactives garanties arrivant à expiration | P2 |

---

## Tests des workflows n8n

**Méthode** : Tests manuels via n8n UI + tests automatisés via API n8n

### Tests manuels (n8n UI)

1. **Email Ingestion** :
   - Envoyer email test → Vérifier webhook reçu → Vérifier classification → Vérifier insert PostgreSQL → Vérifier Redis event
2. **Briefing Daily** :
   - Trigger manuel → Vérifier agrégation données → Vérifier génération briefing → Vérifier envoi Telegram
3. **Backup Daily** :
   - Trigger manuel → Vérifier backup PostgreSQL créé → Vérifier sync Tailscale → Vérifier cleanup

### Tests automatisés (API n8n)

```bash
# Activer un workflow
curl -X PATCH http://n8n:5678/api/v1/workflows/{workflow_id} \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  -d '{"active": true}'

# Trigger manuel d'un workflow
curl -X POST http://n8n:5678/webhook-test/email-ingestion \
  -d @test_email_payload.json

# Vérifier exécutions
curl -X GET http://n8n:5678/api/v1/executions?workflowId={workflow_id} \
  -H "X-N8N-API-KEY: $N8N_API_KEY"
```

---

## Maintenance & Monitoring

### Logs

Les workflows publient des evenements via Redis. **Important** : les evenements critiques utilisent **Redis Streams** (garantie de delivery), les evenements informatifs utilisent Pub/Sub (fire-and-forget).

> **Redis Streams vs Pub/Sub** :
> - **Redis Streams** (delivery garantie) : evenements critiques tels que `email.received`, `document.processed`, `pipeline.error`, `service.down`, `trust.level.changed`, `action.corrected`, `action.validated`
> - **Redis Pub/Sub** (fire-and-forget) : evenements informatifs tels que `agent.completed`, `pipeline.completed`, logs de monitoring
>
> Les evenements critiques necessitent Redis Streams car un consumer temporairement indisponible ne doit pas perdre de messages. Les evenements informatifs tolerent la perte occasionnelle.

```bash
# Suivre les logs informatifs en temps reel (Pub/Sub)
redis-cli SUBSCRIBE pipeline.completed pipeline.error

# Lire les evenements critiques (Streams)
redis-cli XREAD COUNT 10 STREAMS email.received document.processed 0 0
```

### Alertes

Les erreurs workflow déclenchent automatiquement :
1. Insert `core.pipeline_errors` (PostgreSQL)
2. Redis event `pipeline.error` → Telegram alert
3. Log structuré JSON → `logs/n8n.log`

### Performance

| Workflow | Fréquence | Durée moyenne | Timeout max |
|----------|-----------|---------------|-------------|
| Email Ingestion | Event-driven (~20/jour) | ~2-5s | 30s |
| Briefing Daily | 1x/jour (7h00) | ~10-15s | 60s |
| Backup Daily | 1x/jour (3h00) | ~5-10 min | 30 min |

---

**Version** : 1.2.0
**Derniere mise a jour** : 2026-02-09 (D19 : pgvector remplace Qdrant Day 1)
