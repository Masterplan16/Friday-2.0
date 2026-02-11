# Story 3.8 - Scan & Déduplication PC-wide

**Epic** : 3 - Archiviste & Recherche Documentaire
**Estimation** : M (12-18h)
**Status** : backlog
**Dépendances** : Story 3.5 (Surveillance dossiers Photos/Documents)

---

## 📋 Objectif

Scanner **tous les fichiers** du PC Mainteneur (`C:\Users\lopez\`) pour détecter et supprimer intelligemment les doublons via SHA256, avec chemins prioritaires et règles de sélection.

---

## 🎯 User Story

**En tant que** Mainteneur,
**Je veux** scanner l'intégralité de mon PC pour détecter les doublons (photos, documents, vidéos, etc.),
**Afin de** libérer de l'espace disque en gardant automatiquement la meilleure copie selon des règles de priorité claires.

---

## ✅ Acceptance Criteria

### AC1 - Scan PC-wide avec exclusions système

```python
# Chemin racine
SCAN_ROOT = r"C:\Users\lopez\"

# Exclusions (système Windows + cache)
EXCLUDED_FOLDERS = [
    "AppData",
    "Application Data",
    ".cache",
    ".vscode",
    ".claude",
    "node_modules",
    "__pycache__",
]
```

- **Scan récursif** de tous sous-dossiers (hors exclusions)
- **Types supportés** : photos (jpg, png, heic, raw), documents (pdf, docx, xlsx), vidéos (mp4, mov, avi), tous autres fichiers
- **Logging** : progression (X/Y fichiers scannés, X Go traités)

### AC2 - Calcul SHA256 universel

- **Hash SHA256** calculé pour chaque fichier (taille > 0 octet)
- **Stockage** : `C:\Friday\scan-cache\sha256.db` (SQLite local pour perf)
- **Format table** :
  ```sql
  CREATE TABLE file_hashes (
      sha256 TEXT PRIMARY KEY,
      file_path TEXT NOT NULL,
      size_bytes INTEGER,
      resolution TEXT,      -- Pour photos (ex: "4032x3024")
      exif_date TEXT,       -- Pour photos (YYYY-MM-DD HH:MM:SS)
      created_at TIMESTAMP,
      UNIQUE(file_path)
  );
  ```
- **Incremental** : si fichier déjà scanné (mtime identique) → skip recalcul

### AC3 - Détection doublons avec groupes

- **Groupes de doublons** : regrouper par SHA256
- **Filtrer** : garder seulement groupes avec ≥2 fichiers
- **Logging** : `X groupes de doublons détectés, Y Go récupérables`

### AC4 - Règles de priorité intelligentes

**Ordre prioritaire pour garder LE fichier** :

1. **Emplacement** (ordre décroissant) :
   - `C:\Users\lopez\BeeStation\Photos\` (priorité absolue photos)
   - `C:\Users\lopez\BeeStation\Documents\` (priorité absolue documents)
   - Tous autres emplacements (égalité)

2. **Résolution** (photos uniquement) :
   - Plus haute résolution gagne (ex: 4032x3024 > 1920x1080)
   - Si non-photo ou résolution identique → critère suivant

3. **Date EXIF** (photos uniquement) :
   - Date EXIF la plus ancienne gagne (= original)
   - Si non-photo ou pas de date EXIF → critère suivant

4. **Nom de fichier** :
   - Nom le plus court gagne (ex: `IMG_1234.jpg` > `IMG_1234 (copie 2).jpg`)
   - Si égalité parfaite → garder le premier alphabétiquement

**Implémentation** :
```python
def select_file_to_keep(duplicate_group: list[FileHash]) -> FileHash:
    """
    Retourne le fichier à GARDER selon règles de priorité.
    Les autres fichiers du groupe seront supprimés.
    """
    # 1. Trier par emplacement prioritaire
    # 2. Si égalité → trier par résolution (desc)
    # 3. Si égalité → trier par date EXIF (asc)
    # 4. Si égalité → trier par longueur nom (asc)
    # 5. Si égalité → trier par nom (alpha)
    return sorted(duplicate_group, key=priority_key)[0]
```

### AC5 - Mode Dry-Run obligatoire avec rapport CSV

**Workflow** :
1. Scan complet → détection doublons → **DRY-RUN** (aucune suppression)
2. Génération rapport CSV détaillé
3. Envoi CSV via Telegram (document)
4. User valide → exécution réelle
5. Logging suppressions effectives

**Format rapport CSV** :
```csv
sha256,action,file_path,size_mb,resolution,exif_date,reason
abc123...,KEEP,C:\Users\lopez\BeeStation\Photos\Paris\IMG_1234.jpg,2.5,4032x3024,2024-01-15 14:30:00,Emplacement prioritaire
abc123...,DELETE,C:\Users\lopez\OneDrive\Photos\IMG_1234.jpg,2.5,4032x3024,2024-01-15 14:30:00,Doublon (emplacement inférieur)
abc123...,DELETE,C:\Users\lopez\Downloads\IMG_1234 (2).jpg,2.5,4032x3024,2024-01-15 14:30:00,Doublon (nom plus long)
```

**Colonnes** :
- `sha256` : Hash du groupe
- `action` : KEEP | DELETE
- `file_path` : Chemin complet
- `size_mb` : Taille en Mo (2 décimales)
- `resolution` : Pour photos (ex: "4032x3024")
- `exif_date` : Pour photos (ex: "2024-01-15 14:30:00")
- `reason` : Explication décision (français)

### AC6 - Commande Telegram `/scan-photos-pc`

```
User: /scan-photos-pc

Friday:
🔍 Scan PC démarré
📁 Racine : C:\Users\lopez\
⏱️ Estimation : 15-30 min pour 100+ Go

[30 min plus tard]

Friday:
✅ Scan terminé
📊 Résultat :
- 45 230 fichiers scannés (127 Go)
- 18 groupes de doublons détectés
- 🗑️ 32.4 Go récupérables (453 fichiers à supprimer)

📄 Rapport CSV joint (scan-doublons-2026-02-11.csv)

Commandes :
/exec-dedup - Exécuter suppressions
/cancel-dedup - Annuler
```

**Sécurités** :
- Timeout user : 7 jours (après → annulation auto)
- `/exec-dedup` demande **confirmation finale** avec inline buttons [Confirmer] [Annuler]
- Logging complet : fichiers supprimés → `C:\Friday\logs\dedup-2026-02-11.log`

### AC7 - Trust Layer & Action Receipt

```python
@friday_action(module="archiviste", action="dedup_scan", trust_default="auto")
async def scan_pc_for_duplicates() -> ActionResult:
    """
    Scan PC-wide, dry-run automatique.
    La suppression réelle nécessite validation user (trust=propose).
    """
    # Scan + SHA256 + détection doublons
    report = await execute_scan()

    return ActionResult(
        input_summary="Scan PC complet (C:\\Users\\lopez\\)",
        output_summary=f"→ {report.duplicate_groups} groupes, {report.recoverable_gb:.1f} Go récupérables",
        confidence=1.0,  # Scan déterministe
        reasoning=f"SHA256 sur {report.total_files} fichiers, {len(EXCLUDED_FOLDERS)} dossiers exclus",
        payload={
            "total_files": report.total_files,
            "total_gb": report.total_gb,
            "duplicate_groups": report.duplicate_groups,
            "recoverable_gb": report.recoverable_gb,
            "csv_path": report.csv_path,
        }
    )

@friday_action(module="archiviste", action="dedup_execute", trust_default="propose")
async def execute_deduplication(csv_path: str) -> ActionResult:
    """
    Suppression effective des doublons.
    Trust=propose → user DOIT valider via Telegram.
    """
    deleted_files = await delete_duplicates_from_csv(csv_path)

    return ActionResult(
        input_summary=f"Suppression doublons ({len(deleted_files)} fichiers)",
        output_summary=f"→ {sum(f.size_mb for f in deleted_files):.1f} Go libérés",
        confidence=1.0,
        reasoning=f"SHA256 match + règles priorité appliquées",
        payload={
            "deleted_files": [f.path for f in deleted_files],
            "freed_gb": sum(f.size_mb for f in deleted_files) / 1024,
        }
    )
```

---

## 🧪 Tests

### Test 1 - Scan avec exclusions système
```python
@pytest.mark.asyncio
async def test_scan_excludes_system_folders():
    scan = PCScan(root=r"C:\Users\lopez\")
    files = await scan.collect_files()

    # Vérifier aucun fichier dans AppData, .cache, etc.
    for f in files:
        assert "AppData" not in f.path
        assert ".cache" not in f.path
```

### Test 2 - Détection doublons SHA256
```python
@pytest.mark.asyncio
async def test_sha256_detects_duplicates():
    # Créer 3 fichiers identiques (contenu) dans dossiers différents
    files = [
        create_temp_file("BeeStation/Photos/test.jpg", content=PHOTO_BYTES),
        create_temp_file("OneDrive/test.jpg", content=PHOTO_BYTES),
        create_temp_file("Downloads/test (2).jpg", content=PHOTO_BYTES),
    ]

    scan = PCScan(root=temp_dir)
    duplicates = await scan.find_duplicates()

    assert len(duplicates) == 1  # 1 groupe de 3 fichiers
    assert len(duplicates[0].files) == 3
```

### Test 3 - Règles priorité emplacement
```python
@pytest.mark.asyncio
async def test_priority_keeps_beestation_photos():
    group = DuplicateGroup(sha256="abc123", files=[
        FileHash(path=r"C:\Users\lopez\BeeStation\Photos\test.jpg", size_bytes=1000),
        FileHash(path=r"C:\Users\lopez\OneDrive\test.jpg", size_bytes=1000),
        FileHash(path=r"C:\Users\lopez\Downloads\test.jpg", size_bytes=1000),
    ])

    to_keep = select_file_to_keep(group.files)

    assert to_keep.path == r"C:\Users\lopez\BeeStation\Photos\test.jpg"
```

### Test 4 - Règles priorité résolution
```python
@pytest.mark.asyncio
async def test_priority_keeps_highest_resolution():
    # Même emplacement (non-prioritaire), résolutions différentes
    group = DuplicateGroup(sha256="abc123", files=[
        FileHash(path=r"C:\Users\lopez\OneDrive\test1.jpg", resolution="1920x1080"),
        FileHash(path=r"C:\Users\lopez\OneDrive\test2.jpg", resolution="4032x3024"),  # Meilleure
        FileHash(path=r"C:\Users\lopez\OneDrive\test3.jpg", resolution="1920x1080"),
    ])

    to_keep = select_file_to_keep(group.files)

    assert to_keep.path == r"C:\Users\lopez\OneDrive\test2.jpg"
    assert to_keep.resolution == "4032x3024"
```

### Test 5 - Dry-run ne supprime rien
```python
@pytest.mark.asyncio
async def test_dryrun_does_not_delete():
    files_before = count_files(temp_dir)

    report = await scan_and_generate_csv(temp_dir, dry_run=True)

    files_after = count_files(temp_dir)
    assert files_before == files_after  # Aucune suppression
    assert os.path.exists(report.csv_path)  # CSV créé
```

### Test 6 - Rapport CSV complet
```python
@pytest.mark.asyncio
async def test_csv_report_format():
    report = await generate_dedup_report()

    df = pd.read_csv(report.csv_path)

    # Vérifier colonnes obligatoires
    assert set(df.columns) == {"sha256", "action", "file_path", "size_mb", "resolution", "exif_date", "reason"}

    # Vérifier 1 seul KEEP par groupe SHA256
    for sha, group in df.groupby("sha256"):
        assert group[group["action"] == "KEEP"].shape[0] == 1
```

---

## 📊 Métriques de succès

- **Performance** : Scan 100 Go en <30 min (SSD)
- **Précision** : 100% fiabilité SHA256 (0 faux positifs)
- **UX** : Dry-run CSV validé avant toute suppression
- **Trust** : Scan auto, suppression propose (validation obligatoire)

---

## 🔗 Dépendances techniques

- **SHA256** : `hashlib` (Python stdlib)
- **EXIF** : `pillow` (déjà installé Story 3.5)
- **SQLite** : Cache local SHA256 pour scan incrémental
- **CSV** : `pandas` pour génération rapport
- **Telegram** : Envoi document CSV + inline buttons validation

---

## 📝 Notes implémentation

### Scope Story 3.8
- **IN SCOPE** : Déduplication uniquement (scan + suppression doublons)
- **OUT OF SCOPE** : Classification/organisation automatique des documents (user le fera manuellement après scan)

### Chemins prioritaires
- **Photos** : `C:\Users\lopez\BeeStation\Photos\` (priorité absolue)
- **Documents** : `C:\Users\lopez\BeeStation\Documents\` (priorité absolue)
- User déplacera manuellement les documents vers Archives après déduplication

### Scan incrémental (optionnel Story 3.8.1 future)
- SQLite cache permet réscan partiel (vérifier mtime avant recalcul SHA256)
- Commande `/rescan-pc` pour forcer full rescan

### Gestion erreurs
- Fichier verrouillé (en cours d'utilisation) → skip + log warning
- Permission denied → skip + log warning
- Fichier supprimé entre scan et exécution → skip + log info

---

## 🚀 Déploiement

1. **Agent archiviste** : `agents/src/agents/archiviste/dedup_scanner.py`
2. **Commande Telegram** : `bot/handlers/commands.py` (ajout `/scan-photos-pc`)
3. **Cache SQLite** : Créer `C:\Friday\scan-cache\` (mkdir auto si absent)
4. **Logs** : `C:\Friday\logs\dedup-*.log` (rotation 30 jours)

---

## 🎯 Impact utilisateur

**Avant** : 100+ Go photos cumulées 25 ans, triples/quadruples manuels impossibles à gérer
**Après** : Scan automatique, rapport CSV clair, suppression intelligente validée par user

**Gain estimé** : 30-50 Go libérés (30-50% doublons typiques sur 25 ans de photos)
