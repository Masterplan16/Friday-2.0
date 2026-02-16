# Specification Technique - Watchdog Detection Fichiers (Story 3.5)

## Vue d'ensemble

Le module Watchdog surveille automatiquement des dossiers configures pour detecter
l'arrivee de nouveaux fichiers (scans, CSVs, documents). Les evenements sont publies
dans Redis Streams `document.received` pour traitement aval par le pipeline Archiviste.

## Architecture

```
Scanner physique / Import CSV / Copie manuelle
    |
    v
C:\Users\lopez\BeeStation\Friday\Transit\{Scans|Finance|Documents}\
    |
    v
[Watchdog Observer] (watchdog Python, 1 observer par dossier)
    |
    v
[Event Handler] (filtre extensions, valide path, stabilisation fichier)
    |
    v
Redis Streams "document.received" (format plat, maxlen=10000)
    |
    v
[Consumer OCR Pipeline] (Story 3.1) / [n8n CSV Workflow] (Story 8.1)
```

## Composants

### 1. Configuration (`config/watchdog.yaml`)

Configuration YAML avec hot-reload (<10s) :

```yaml
watchdog:
  enabled: true
  polling_interval_seconds: 1
  stabilization_delay_seconds: 1.0
  paths:
    - path: "C:\\Users\\lopez\\BeeStation\\Friday\\Transit\\Scans\\"
      recursive: false
      extensions: [".pdf", ".png", ".jpg", ".jpeg"]
      source_label: "scanner_physique"
      workflow_target: "ocr_pipeline"
```

| Champ | Type | Description |
|-------|------|-------------|
| `enabled` | bool | Active/desactive le watchdog global |
| `polling_interval_seconds` | int (1-10) | Intervalle polling filesystem |
| `stabilization_delay_seconds` | float (0-10) | Delai attente ecriture complete |
| `paths[].path` | string | Chemin absolu dossier surveille |
| `paths[].recursive` | bool | Inclure sous-dossiers |
| `paths[].extensions` | list[string] | Extensions autorisees (dot prefix) |
| `paths[].source_label` | string | Label source pour routing |
| `paths[].workflow_target` | string? | n8n workflow ID cible |

### 2. Config Manager (`watchdog_config.py`)

- Pydantic v2 validation (PathConfig, WatchdogConfigSchema)
- Hot-reload : verifie mtime toutes les 5s, recharge si modifie
- Callbacks on_reload pour notification composants dependants

### 3. Observer (`watchdog_observer.py`)

- `FridayWatchdogObserver` : orchestrateur principal
- 1 Observer watchdog par dossier configure
- Support PollingObserver (NFS/Docker) ou natif (Windows/Linux)
- Connexion Redis async
- Graceful shutdown (stop + join threads)

### 4. Event Handler (`watchdog_handler.py`)

- `FridayWatchdogHandler(FileSystemEventHandler)`
- Gere `on_created` et `on_moved` (copie/deplacement dans dossier)
- Filtre extensions (whitelist)
- Validation path traversal (`Path.resolve()`)
- Stabilisation fichier (attente ecriture complete)
- Bridge sync->async via `asyncio.run_coroutine_threadsafe()`
- Retry backoff exponentiel (1s, 2s, 4s, max 3 tentatives)

## Format Event Redis

```python
# Format plat Redis Streams (coherent avec attachment_extractor.py)
{
    "filename": "2026-02-16_Facture_EDF_150EUR.pdf",
    "filepath": "C:\\Users\\lopez\\BeeStation\\Friday\\Transit\\Scans\\...",
    "extension": ".pdf",
    "source": "scanner_physique",
    "workflow_target": "ocr_pipeline",
    "detected_at": "2026-02-16T14:30:00+00:00",
    "size_bytes": "1234",
}
```

Stream : `document.received` (maxlen=10000, dot notation)

## Securite

- **Path traversal** : `Path.resolve()` + `is_relative_to()` (Python 3.9+, résistant aux préfixes similaires)
- **Extension whitelist** : seules les extensions configurees sont traitees
- **Source label validation** : regex `[a-zA-Z0-9_-]+` uniquement
- **Pas d'executables** : `.exe`, `.bat`, `.cmd` etc. bloques par whitelist
- **Pas de credentials** : watchdog lit filesystem local, pas d'API externe

## Performance

| Metrique | Objectif | Mesure |
|----------|----------|--------|
| Latence detection | <2s | Polling 1s + processing |
| Latence detection -> Redis | <500ms | Mesure dans tests E2E |
| RAM process | <100 Mo | Watchdog daemon threads legers |
| CPU idle | <2% | Polling natif OS |
| Batch 20 fichiers | <5s total | Test integration valide |

## Gestion Erreurs (AC5)

Apres echec persistant (3 retries) :
1. Fichier deplace vers `error_directory/{YYYY-MM-DD}/` (configurable dans watchdog.yaml)
2. Event `pipeline.error` publie dans Redis Streams (best effort)
3. Le bot Telegram consomme `pipeline.error` → alerte topic System

## Tests

- **44 tests unitaires** : config validation, handler logic, observer lifecycle, error dir, pipeline error
- **3 tests integration** : filesystem reel, batch detection, hot-reload
- **2 tests E2E** : pipeline OCR, pipeline CSV

Total : **49 tests**

## Dependances

- `watchdog>=5.0.3` (filesystem events, cross-platform)
- `pyyaml>=6.0.2` (config parsing, deja installe)
- `redis>=5.0.0` (Redis Streams, deja installe)
- `pydantic>=2.9.0` (config validation, deja installe)
- `structlog>=24.4.0` (logging JSON, deja installe)

## Hot-Reload (AC7)

Le Config Manager verifie le mtime de `watchdog.yaml` toutes les 5 secondes.
Si modifie :
1. Recharge et valide la configuration
2. Arrete les observers existants
3. Cree de nouveaux observers pour les nouveaux dossiers
4. Publie `system.notification` via Redis Pub/Sub (le bot route vers Telegram topic System)

## Troubleshooting

| Probleme | Cause | Solution |
|----------|-------|----------|
| Fichier pas detecte | Extension pas dans whitelist | Verifier `extensions` dans config |
| Detection lente | Polling interval trop haut | Reduire `polling_interval_seconds` |
| Fichier tronque | Ecriture pas terminee | Augmenter `stabilization_delay_seconds` |
| Path traversal bloque | Fichier hors watched_root | Verifier config `path` |
| Redis publish failed | Redis down | Retry automatique 3x, alerte System |
