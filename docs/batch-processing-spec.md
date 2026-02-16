# Batch Processing Specification

**Story**: 3.7 - Traitement Batch Dossier
**Status**: Implementation Complete
**Date**: 2026-02-16

## Vue d'ensemble

Le système de traitement batch permet de traiter automatiquement des dossiers entiers de fichiers via une simple commande Telegram "Range mes Downloads".

## Architecture

```
Telegram Command "Range mes Downloads"
    ↓
Intent Detection (Claude Sonnet 4.5)
    ↓
Security Validation (path traversal, zones autorisées)
    ↓
Confirmation [Lancer/Annuler/Options]
    ↓
Batch Processor Scan Récursif
    ↓
Déduplication SHA256
    ↓
Pipeline Archiviste (OCR → Classification → Sync)
    ↓
Progress Updates Telegram (throttle 5s)
    ↓
Rapport Final
```

## Composants

### 1. Intent Detection (`bot/handlers/batch_commands.py`)
- **Rôle** : Détecter intention "traiter dossier batch" via Claude Sonnet 4.5
- **AC** : AC1 (Intent detection), AC7 (Security validation)
- **Tests** : 15 tests unitaires
- **Lignes** : ~450

### 2. Batch Processor (`agents/src/agents/archiviste/batch_processor.py`)
- **Rôle** : Scan dossier, déduplication, traitement pipeline
- **AC** : AC2 (Pipeline complet), AC6 (Error handling)
- **Tests** : 17 tests unitaires
- **Lignes** : ~600

### 3. Progress Tracker (`agents/src/agents/archiviste/batch_progress.py`)
- **Rôle** : Tracker progression, update Telegram
- **AC** : AC3 (Progress tracking)
- **Tests** : 8 tests unitaires
- **Lignes** : ~250

### 4. Database Migration (`database/migrations/039_batch_jobs.sql`)
- **Rôle** : Table audit trail batch jobs
- **AC** : AC4 (Audit trail)
- **Lignes** : ~100

## Commandes Telegram

```
Mainteneur: "Range mes Downloads"
Friday: 📦 42 fichiers détectés dans C:\Users\lopez\Downloads

        Lancer le traitement ?

        [✅ Lancer] [🔧 Options] [❌ Annuler]

Mainteneur: [clique Lancer]

Friday: 📦 Traitement batch : batch_abc123
        ⏳ Progression : 15/42 fichiers (35%)
        ✅ Traités : 12
        ⚠️ Échecs : 3
        ⏱️ Temps écoulé : 5m12s
        📊 Catégories :
          • Finance : 8 fichiers
          • Pro : 4 fichiers

        [⏸️ Pause] [❌ Annuler] [📋 Détails]

... (après completion)

Friday: ✅ Traitement batch terminé !

        📁 Dossier : C:\Users\lopez\Downloads
        ⏱️ Durée totale : 18m45s
        📊 Résultats :
          • 42 fichiers détectés
          • 38 traités avec succès (90%)
          • 3 échecs (7%)
          • 1 skip (déjà traité)

        📂 Classement :
          • Finance/selarl : 15 fichiers
          • Pro/factures : 8 fichiers
          • Perso/vehicule : 7 fichiers
          • Universite/admin : 5 fichiers
          • Recherche/articles : 3 fichiers

        ⚠️ Échecs :
          1. document_corrompu.pdf (OCR failed)
          2. scan_illisible.jpg (confidence <0.3)
          3. facture_incomplete.docx (metadata extraction failed)

        [Retraiter échecs] [Archive source] [OK]
```

## Sécurité

### Zones Autorisées
- `C:\Users\lopez\Downloads\`
- `C:\Users\lopez\Desktop\`
- `C:\Users\lopez\BeeStation\Friday\Transit\`

### Protections
- ✅ Path traversal (`..` interdits)
- ✅ Zones système interdites (C:\Windows\)
- ✅ Quota 1000 fichiers max
- ✅ Extensions whitelist validation
- ✅ Rate limiting 5 fichiers/min

## Performance

### Rate Limiting
- **5 fichiers/minute** (protection VPS)
- **Timeout 5 min** par fichier
- **1 batch actif** maximum

### Déduplication
- **SHA256 hash** check via `ingestion.document_metadata`
- **Skip automatique** fichiers déjà traités

### Fichiers Système Skips
- Extensions : `.tmp`, `.cache`, `.log`, `.bak`
- Noms : `desktop.ini`, `.DS_Store`, `thumbs.db`
- Dossiers : `.git/`, `.svn/`, `__pycache__/`
- Office temp : `~$*.docx`

## Tests

### Pyramide (80/15/5)
- **43 tests unitaires** (mock Telegram, Claude, Redis, PostgreSQL)
- **8 tests integration** (Redis réel, PostgreSQL réel)
- **3 tests E2E** (pipeline complet)

### Coverage
- **AC1** : Intent detection (3 tests)
- **AC2** : Pipeline complet (20 tests)
- **AC3** : Progress tracking (8 tests)
- **AC4** : Rapport final (4 tests)
- **AC5** : Filtres (6 tests)
- **AC6** : Error handling (7 tests)
- **AC7** : Sécurité (7 tests)

## Troubleshooting

### Batch Timeout
**Symptôme** : Fichier timeout après 5 min

**Solution** :
1. Vérifier logs `batch_file_failed`
2. Relancer traitement manuel via `/retry`

### Rate Limit Dépassé
**Symptôme** : "rate_limit_waiting" dans logs

**Solution** : Normal, rate limiting actif (5 fichiers/min)

### Quota Dépassé
**Symptôme** : "Trop de fichiers détectés (>1000)"

**Solution** :
1. Filtrer par extensions : [Options]
2. Traiter par sous-dossiers
3. Augmenter quota (CLAUDE.md, nécessite approval)

## Références

- **Story** : [3-7-traitement-batch-dossier.md](_bmad-output/implementation-artifacts/3-7-traitement-batch-dossier.md)
- **PRD** : FR112
- **Architecture** : [architecture-friday-2.0.md](_docs/architecture-friday-2.0.md)
- **Stories dépendantes** : 3.1-3.6 (Pipeline Archiviste), 1.9 (Bot Telegram)
