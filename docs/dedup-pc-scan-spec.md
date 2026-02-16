# Scan & Deduplication PC - Specification technique

> Story 3.8 | Epic 3 : Archiviste & Recherche Documentaire

## Vue d'ensemble

Module de detection et suppression des fichiers dupliques sur le PC du Mainteneur,
declenche via commande Telegram `/scan_dedup`.

## Architecture

```
Telegram /scan_dedup
    |
    v
bot/handlers/dedup_commands.py  (rate limiting, owner check)
    |
    v
agents/src/agents/dedup/scanner.py  (AC1+AC2: scan recursif SHA256)
    |
    v
agents/src/agents/dedup/priority_engine.py  (AC3: keeper selection)
    |
    v
agents/src/agents/dedup/report_generator.py  (AC5: CSV dry-run)
    |
    v
[Preview Telegram + Inline Buttons]
    |
    v
agents/src/agents/dedup/deleter.py  (AC6+AC7: safety + send2trash)
    |
    v
database/migrations/042_dedup_jobs.sql  (audit trail)
```

## Modules

### Scanner (`scanner.py`)

- Scan recursif via `Path.rglob("*")`
- SHA256 chunked (65536 bytes) via `asyncio.to_thread()`
- Chemins prioritaires scannes en premier (BeeStation > Desktop > Downloads)
- Deduplication Windows case-insensitive via `file_path.resolve()`
- Exclusions intelligentes : chemins systeme, dossiers dev, extensions, taille
- Support annulation et timeout configurable

### Priority Engine (`priority_engine.py`)

| Source | Score |
|--------|-------|
| BeeStation/Photos, BeeStation/Documents | 100 |
| BeeStation/Archives | 90 |
| BeeStation (other) | 80 |
| Desktop | 50 |
| Downloads | 30 |
| Inconnu | 0 |

Bonus additionnels :
- Resolution image 4K (+50), HD (+30), SD (+10)
- EXIF DateTimeOriginal (+20)
- Nom descriptif >20 chars (+30), 10-20 (+15), <10 (+5)
- Pattern generique IMG_*, DSC_*, Screenshot_* (0)
- Suffixe copie (1), _copy (-10)

### Report Generator (`report_generator.py`)

CSV avec :
- Header statistiques (date, fichiers scannes, groupes, espace)
- Colonnes : group_id, hash, file_path, size, action, priority_score, reason
- Encodage UTF-8

### Deleter (`deleter.py`)

4 safety checks avant chaque suppression :
1. Fichier existe encore
2. Hash identique (pas modifie depuis scan)
3. Pas dans zone exclue (Windows, $Recycle.Bin)
4. Keeper existe dans le groupe

Suppression via `send2trash` (Corbeille Windows, rollback possible).

## Commandes Telegram

| Commande | Description |
|----------|-------------|
| `/scan_dedup` | Lance un scan (owner only, 1 max simultane) |

### Boutons inline

- **Voir rapport** : Envoie CSV en fichier
- **Lancer suppression** : Preview + confirmation
- **CONFIRMER** : Execute la suppression batch
- **Annuler** : Annule l'operation

## Migration SQL

`database/migrations/042_dedup_jobs.sql` :
- Table `core.dedup_jobs` (audit trail)
- Colonnes : dedup_id, scan_root, total_scanned, duplicate_groups, etc.
- Status : scanning, report_ready, deleting, completed, failed, cancelled

## Tests

- **Unit** : 67 tests (scanner, priority, report, deleter, commands)
- **Integration** : 5 tests (full scan, priority, CSV, deletion safety)
- **E2E** : 1 test (workflow complet scan -> delete)

## Dependances

- `send2trash` >= 1.8.0 (Corbeille Windows)
- `Pillow` >= 10.0 (resolution/EXIF, optionnel)
- `structlog` (logging JSON)
- `pydantic` v2 (models)
