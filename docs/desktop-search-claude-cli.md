# Friday 2.0 - Desktop Search via Claude Code CLI

**Story**: 3.3 - Task 6
**Date**: 2026-02-16
**Decision**: D23 (2026-02-10)

---

## Architecture

### Flux complet

```
Telegram /search <query>
    |
    v
VPS: search_commands.py
    |
    v (1) Recherche pgvector (semantic_search.py)
    |
    v (2) Publish search.requested (Redis Streams)
    |
    v
PC Mainteneur: desktop_search_consumer.py
    |
    v
Claude Code CLI (--print, non-interactif)
    |
    v
Publish search.completed (Redis Streams)
    |
    v
VPS: Resultats combines -> Telegram response
```

### Composants

| Composant | Fichier | Tourne sur |
|-----------|---------|------------|
| Wrapper CLI | `agents/src/tools/desktop_search_wrapper.py` | PC Mainteneur |
| Consumer Redis | `agents/src/tools/desktop_search_consumer.py` | PC Mainteneur |
| Commande Telegram | `bot/handlers/search_commands.py` | VPS |
| Recherche pgvector | `agents/src/agents/archiviste/semantic_search.py` | VPS |

---

## Setup PC Mainteneur

### Prerequis

1. **Claude Code CLI** installe :
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

2. **Python 3.12+** avec dependencies :
   ```bash
   pip install redis structlog
   ```

3. **Redis accessible** via Tailscale (VPS) :
   ```
   REDIS_URL=redis://<user>:<pass>@<vps-tailscale-ip>:6379/0
   ```

4. **Dossier Archives** accessible :
   ```
   C:\Users\lopez\BeeStation\Friday\Archives\
   ```

### Variables d'environnement

```bash
# Redis VPS (via Tailscale)
REDIS_URL=redis://friday-search:***@friday-vps:6379/0

# Claude CLI
CLAUDE_CLI_PATH=claude          # ou chemin absolu
SEARCH_BASE_PATH=C:\Users\lopez\BeeStation\Friday\Archives
DESKTOP_SEARCH_TIMEOUT=30       # secondes

# Consumer
DESKTOP_SEARCH_CONSUMER_NAME=desktop-worker-1
```

### Lancement

```bash
# Consumer desktop search (boucle infinie)
python -m agents.src.tools.desktop_search_consumer
```

Le consumer :
1. Se connecte a Redis (VPS via Tailscale)
2. Cree consumer group `desktop-search` si absent
3. Ecoute `search.requested` (XREADGROUP, block 5s)
4. Invoque Claude CLI pour chaque requete
5. Publie resultats sur `search.completed`

---

## Redis Streams

### Events

| Stream | Producteur | Consommateur | Champs |
|--------|-----------|--------------|--------|
| `search.requested` | VPS (search_commands.py) | PC (desktop_search_consumer.py) | query, request_id, max_results |
| `search.completed` | PC (desktop_search_consumer.py) | VPS (search_commands.py) | request_id, query, results (JSON), results_count, completed_at, source |

### Consumer Group

```
Group: desktop-search
Consumer: desktop-worker-1
```

### Setup Redis Streams

```bash
# Sur VPS (inclus dans scripts/setup-redis-streams.sh)
redis-cli XGROUP CREATE search.requested desktop-search 0 MKSTREAM
```

---

## Claude Code CLI - Mode Prompt

### Invocation

```bash
claude --print --output-format json "Search for files matching this query in <base_path>: '<query>'. Return top N results as a JSON array with fields: path, title (filename), excerpt (first 200 chars of content), score (relevance 0-1). Output ONLY the JSON array, no explanation."
```

### Options

| Flag | Description |
|------|-------------|
| `--print` | Non-interactif, stdout seulement |
| `--output-format json` | Sortie JSON structuree |

### Format sortie attendu

```json
[
  {
    "path": "C:\\Users\\lopez\\BeeStation\\Friday\\Archives\\finance\\facture.pdf",
    "title": "facture.pdf",
    "excerpt": "Facture plombier intervention fevrier 2026...",
    "score": 0.92
  }
]
```

### Parsing robuste

Le wrapper gere 3 cas :
1. **JSON array direct** : `[{...}, {...}]`
2. **JSON wrapper** : `{"result": "[{...}]"}`
3. **JSON embede dans texte** : `Here are results:\n[{...}]\nDone.`

Si aucun parsing ne fonctionne, retourne liste vide (pas d'erreur).

---

## Fallback

Si Claude CLI est indisponible (PC eteint, CLI non installe, timeout) :
- Desktop search publie resultats vides sur `search.completed`
- La recherche pgvector (VPS) fonctionne seule
- L'utilisateur obtient les resultats pgvector sans Desktop Search
- Aucune erreur visible pour l'utilisateur

---

## Monitoring

### Metriques

- `search_metrics.record_query()` : Latence, nb resultats, top score
- `search_metrics.check_alert_threshold()` : Alerte si mediane > 2.5s
- `search_metrics.get_stats()` : p50, p95, p99 latences

### Alertes

| Condition | Action |
|-----------|--------|
| Claude CLI timeout (>30s) | Log warning, fallback pgvector |
| 3 echecs consecutifs | Log error (TELEGRAM ALERT) |
| Mediane latence > 2.5s | Alerte Telegram System |

### Logs

```json
{
  "event": "Claude CLI search completed",
  "results_count": 3,
  "query_length": 25,
  "timestamp": "2026-02-16T14:30:00Z"
}
```

---

## Phase 2 : Migration NAS DS725+

**Planifie** : Apres acquisition Synology DS725+ (x86_64)

Changements :
- Consumer tourne sur NAS (24/7) au lieu de PC
- Memes variables d'environnement
- `SEARCH_BASE_PATH` pointe vers stockage NAS local
- Disponibilite 24/7 (vs 8h-22h PC)

**Prerequis NAS** :
- CPU x86_64 (compatible Claude CLI)
- Docker ou Python natif
- Redis accessible via Tailscale
- Synology Drive sync bidirectionnel avec PC
