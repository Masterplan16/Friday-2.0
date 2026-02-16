# Desktop Search - Guide de démarrage rapide

## Story 3.3 - Desktop Search via Claude Code CLI

### Prérequis ✅

- ✅ Claude Code CLI installé (`claude --version` doit retourner `2.1.32` ou supérieur)
- ✅ Tailscale connecté au VPS (`tailscale status` doit montrer `friday-vps`)
- ✅ Python venv activé (`.venv\Scripts\Activate.ps1`)

---

## 🚀 Démarrage en 1 commande

```powershell
.\scripts\setup-desktop-search.ps1
```

Ce script :
1. ✅ Vérifie Claude CLI disponible
2. ✅ Vérifie Tailscale connecté
3. ✅ Teste connexion Redis VPS
4. ✅ Crée `.env.desktop` avec configuration
5. ✅ Démarre le consumer Desktop Search

**Le consumer reste en avant-plan.** Appuie sur `Ctrl+C` pour arrêter.

---

## 🔧 Configuration manuelle (si besoin)

### Étape 1 : Setup uniquement (sans démarrer)

```powershell
.\scripts\setup-desktop-search.ps1 -ConfigOnly
```

Crée `.env.desktop` avec :

```env
# Redis VPS (via Tailscale)
REDIS_URL=redis://friday-vps:6379/0

# Claude CLI
CLAUDE_CLI_PATH=claude

# Search paths
SEARCH_BASE_PATH=C:\Users\lopez\BeeStation\Friday\Archives

# Consumer identity
DESKTOP_SEARCH_CONSUMER_NAME=desktop-worker-DESKTOP-XXXXX

# Timeouts
DESKTOP_SEARCH_TIMEOUT=30
```

### Étape 2 : Démarrer consumer

```powershell
.\scripts\start-desktop-search.ps1
```

---

## 🧪 Test via Telegram

Une fois le consumer démarré :

1. Ouvre Telegram
2. Envoie `/search` au bot Friday
3. Entre ta query : `"factures électricité 2025"`
4. Attends 2-5s
5. Reçois résultats formatés

---

## 🛠️ Troubleshooting

### Erreur "Claude CLI non trouvé"

**Cause** : Claude CLI pas dans le PATH ou venv pas activé correctement.

**Fix 2026-02-16** : Scripts corrigés avec **dot sourcing** PowerShell (`. $venvActivate` au lieu de `& $venvActivate`).

**Test manuel** :
```powershell
# Vérifier Claude CLI
.\.venv\Scripts\Activate.ps1
claude --version  # Doit afficher 2.1.32 ou supérieur

# Réessayer setup
.\scripts\setup-desktop-search.ps1
```

**Si toujours échoue** : Vérifier que `.venv\Scripts\Activate.ps1` existe
```powershell
Test-Path .\.venv\Scripts\Activate.ps1  # Doit retourner True
```

### Erreur "VPS friday-vps inaccessible"

**Cause** : Tailscale pas connecté ou VPS down.

**Fix** :
```powershell
# Vérifier Tailscale
tailscale status | findstr friday-vps

# Si absent, connecter Tailscale
tailscale up
```

### Erreur "Redis connexion refused"

**Cause** : Redis VPS down ou firewall Tailscale.

**Fix SSH VPS** :
```bash
ssh friday-vps
docker compose ps redis  # Doit montrer "Up"
docker compose logs redis  # Vérifier logs
```

### Consumer crash en boucle

**Cause** : Exception Python non catchée.

**Fix** :
```powershell
# Voir logs détaillés
python -m agents.src.tools.desktop_search_consumer
```

---

## 📊 Architecture

```
┌──────────┐          ┌─────────────┐          ┌──────────────┐
│ Telegram │─/search─→│  VPS Redis  │─Streams─→│  PC Desktop  │
│   Bot    │          │   Streams   │          │   Consumer   │
└──────────┘          └─────────────┘          └──────────────┘
                                                        │
                                                        ▼
                                                ┌──────────────┐
                                                │  Claude CLI  │
                                                │ (prompt mode)│
                                                └──────────────┘
                                                        │
                                                        ▼
                                                ┌──────────────┐
                                                │  Archives/   │
                                                │  200 Go docs │
                                                └──────────────┘
```

**Redis Streams** :
- **Input** : `search.requested` (query + request_id)
- **Output** : `search.completed` (results + request_id)

**Consumer Group** : `desktop-search`
**Consumer Name** : `desktop-worker-{HOSTNAME}`

---

## 🔒 Sécurité

- ✅ **Anonymisation Presidio** appliquée AVANT envoi query au consumer
- ✅ **Tailscale VPN** : Redis jamais exposé publiquement
- ✅ **Redis ACL** : consumer en read-only sur streams search.*

---

## 📈 Phase 2 (Future)

Migrer consumer vers **NAS Synology DS725+** pour disponibilité 24/7.

**Avantages** :
- Disponibilité continue (pas besoin PC allumé)
- Accès direct NAS archives (pas de Synology Drive sync)
- Claude CLI sur DS725+ (CPU x86_64, 8 Go RAM)

**Déferred** : BeeStation incompatible (ARM CPU, limitations Tailscale)

---

**Date** : 2026-02-16
**Story** : 3.3 - Desktop Search via Claude Code CLI
**Décision** : D23 (Claude CLI > agent Python custom)
