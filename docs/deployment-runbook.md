# Deployment Runbook - Friday 2.0

**Last Updated**: 2026-02-10
**Story**: 1.16 - CI/CD Pipeline GitHub Actions
**Target**: VPS-4 OVH (48 Go RAM, 12 vCores, 300 Go SSD)

---

## 📋 Table des matières

1. [Prérequis](#prérequis)
2. [Procédure de déploiement standard](#procédure-de-déploiement-standard)
3. [Troubleshooting](#troubleshooting)
4. [Commandes utiles](#commandes-utiles)
5. [Rollback manuel](#rollback-manuel)
6. [Monitoring post-déploiement](#monitoring-post-déploiement)

---

## 🔧 Prérequis

### 1. Tailscale VPN connecté

Le déploiement se fait **uniquement via Tailscale mesh VPN** (Story 1.4). Pas de port SSH ouvert sur Internet public.

**Vérifier connexion Tailscale :**
```bash
tailscale status
```

**Output attendu :**
```
100.x.x.x   friday-vps    tagged-devices    linux   active; direct 51.x.x.x:41641
```

**Si Tailscale déconnecté :**
```bash
# Sur machine locale
sudo tailscale up

# Vérifier que friday-vps est visible
tailscale status | grep friday-vps
```

---

### 2. Clés SSH configurées

**Vérifier accès SSH au VPS :**
```bash
ssh friday-vps "echo 'SSH OK'"
# Output attendu: SSH OK
```

**Configuration SSH (~/.ssh/config) :**
```
Host friday-vps
    HostName 100.x.x.x  # Adresse Tailscale du VPS
    User friday
    IdentityFile ~/.ssh/id_ed25519_friday
    StrictHostKeyChecking yes
```

**Si SSH échoue :**
1. Vérifier que la clé SSH est ajoutée : `ssh-add ~/.ssh/id_ed25519_friday`
2. Vérifier les permissions : `chmod 600 ~/.ssh/id_ed25519_friday`
3. Vérifier que Tailscale est connecté (voir section précédente)

---

### 3. Variables d'environnement

Le script `deploy.sh` nécessite ces variables pour les notifications Telegram :

```bash
# .env (local)
TELEGRAM_BOT_TOKEN=<token>
TOPIC_SYSTEM_ID=<thread_id>
```

**Vérifier variables :**
```bash
source .env
echo "Token: ${TELEGRAM_BOT_TOKEN:0:10}..."
echo "Topic: $TOPIC_SYSTEM_ID"
```

**Comportement si variables manquantes :**
- Le déploiement **continue** (non-bloquant)
- Un warning est affiché : `Telegram credentials not configured - skipping notification`

---

### 4. Backup script disponible

Le script `deploy.sh` appelle `scripts/backup.sh` avant déploiement.

**Vérifier backup script existe :**
```bash
ls -lh scripts/backup.sh
# Output: -rwxr-xr-x ... scripts/backup.sh
```

**Si backup.sh manquant :**
- Le déploiement **affiche un warning** mais continue (Story 1.12 pas encore implémentée)
- Créer un backup manuel avant déploiement : voir section [Rollback manuel](#rollback-manuel)

---

## 🚀 Procédure de déploiement standard

### Étape 1 : Vérifier prérequis

```bash
# 1. Tailscale connecté
tailscale status | grep friday-vps

# 2. SSH fonctionne
ssh friday-vps "echo 'OK'"

# 3. Variables Telegram configurées (optionnel)
source .env
echo ${TELEGRAM_BOT_TOKEN:0:10}
```

---

### Étape 2 : Exécuter script de déploiement

```bash
cd /path/to/Friday-2.0
./scripts/deploy.sh
```

**Output attendu :**
```
==================================================
Friday 2.0 - Deployment Script
==================================================
VPS Host: friday-vps
Commit: a1b2c3d
==================================================

::notice::Verifying Tailscale connection...
::notice::Tailscale connection verified - friday-vps is reachable

::notice::Running pre-deployment backup...
::notice::Backup completed successfully

::notice::Starting deployment to friday-vps...
::notice::Pulling latest code from git...
::notice::Pulling Docker images...
::notice::Building and restarting services...
::notice::Deployment commands completed

::notice::Running healthcheck (3 retries, 5s delay)...
::notice::Healthcheck attempt 1/3...
::notice::Healthcheck PASSED on attempt 1

::notice::✅ Deployment SUCCESSFUL
```

**Notification Telegram (topic System) :**
```
✅ Déploiement réussi

VPS: friday-vps
Commit: a1b2c3d
Healthcheck: PASS
```

---

### Étape 3 : Vérifier déploiement

**1. Vérifier services actifs :**
```bash
ssh friday-vps "cd /opt/friday-2.0 && docker compose ps"
```

**Output attendu :**
```
NAME                STATUS              PORTS
friday-postgres     Up 2 minutes       5432/tcp
friday-redis        Up 2 minutes       6379/tcp
friday-gateway      Up 2 minutes       0.0.0.0:8000->8000/tcp
...
```

**2. Vérifier healthcheck manuellement :**
```bash
ssh friday-vps "curl -s http://localhost:8000/api/v1/health | jq"
```

**Output attendu :**
```json
{
  "status": "healthy",
  "services": {
    "database": "healthy",
    "redis": "healthy",
    "gateway": "healthy",
    ...
  }
}
```

**3. Vérifier logs (pas d'erreurs) :**
```bash
ssh friday-vps "cd /opt/friday-2.0 && docker compose logs --tail=50"
```

---

## 🛠️ Troubleshooting

### Problème 1 : Healthcheck échoue

**Symptôme :**
```
::error::Healthcheck FAILED after 3 attempts
::error::Deployment failed - initiating rollback...
```

**Diagnostic :**
```bash
# 1. Vérifier services Docker actifs
ssh friday-vps "docker ps"

# 2. Vérifier logs Gateway (healthcheck endpoint)
ssh friday-vps "docker compose logs friday-gateway --tail=100"

# 3. Vérifier PostgreSQL opérationnel
ssh friday-vps "docker compose exec postgres pg_isready"

# 4. Vérifier Redis opérationnel
ssh friday-vps "docker compose exec redis redis-cli ping"
```

**Solutions courantes :**

| Cause | Solution |
|-------|----------|
| PostgreSQL pas démarré | `ssh friday-vps "docker compose restart postgres"` |
| Redis pas démarré | `ssh friday-vps "docker compose restart redis"` |
| Gateway erreur config | Vérifier `.env` sur VPS : `ssh friday-vps "cat /opt/friday-2.0/.env"` |
| Migrations non appliquées | Appliquer migrations : `ssh friday-vps "cd /opt/friday-2.0 && python scripts/apply_migrations.py"` |

---

### Problème 2 : Rollback échoué

**Symptôme :**
```
::error::Rollback failed
fatal: You are in 'detached HEAD' state
```

**Solution - Rollback manuel :**

Voir section [Rollback manuel](#rollback-manuel).

---

### Problème 3 : Tailscale déconnecté

**Symptôme :**
```
::error::Tailscale not connected. Run 'sudo tailscale up' first.
```

**Solution :**
```bash
# Sur machine locale
sudo tailscale up

# Vérifier connexion
tailscale status

# Si pas de connexion après 10s
sudo systemctl restart tailscaled
tailscale up
```

---

### Problème 4 : VPS host non trouvé

**Symptôme :**
```
::error::VPS host 'friday-vps' not found in Tailscale network
```

**Solution :**
```bash
# Lister hosts Tailscale disponibles
tailscale status

# Si friday-vps manquant : vérifier sur le VPS
ssh <ip_tailscale_vps> "sudo tailscale status"

# Redémarrer Tailscale sur VPS si nécessaire
ssh <ip_tailscale_vps> "sudo systemctl restart tailscaled && sudo tailscale up"
```

---

### Problème 5 : Backup échoue

**Symptôme :**
```
::error::Backup failed - aborting deployment
```

**Solutions :**

1. **Vérifier espace disque VPS :**
```bash
ssh friday-vps "df -h /opt/friday-2.0"
# Si <10% libre : nettoyer anciens backups
ssh friday-vps "ls -lht /opt/friday-2.0/backups/"
```

2. **Vérifier PostgreSQL accessible :**
```bash
ssh friday-vps "docker compose exec postgres pg_dump --version"
```

3. **Exécuter backup manuellement :**
```bash
ssh friday-vps "cd /opt/friday-2.0 && ./scripts/backup.sh"
```

---

## 📚 Commandes utiles

### Logs

```bash
# Logs tous services (temps réel)
ssh friday-vps "cd /opt/friday-2.0 && docker compose logs -f"

# Logs service spécifique
ssh friday-vps "cd /opt/friday-2.0 && docker compose logs -f friday-gateway"

# Logs dernières 100 lignes
ssh friday-vps "cd /opt/friday-2.0 && docker compose logs --tail=100"

# Logs avec timestamps
ssh friday-vps "cd /opt/friday-2.0 && docker compose logs -f --timestamps"
```

---

### Status Services

```bash
# Services actifs
ssh friday-vps "cd /opt/friday-2.0 && docker compose ps"

# Ressources CPU/RAM
ssh friday-vps "docker stats --no-stream"

# Healthcheck manuel
ssh friday-vps "curl -s http://localhost:8000/api/v1/health | jq"

# Status Tailscale
ssh friday-vps "sudo tailscale status"
```

---

### Redémarrage Services

```bash
# Redémarrer service spécifique
ssh friday-vps "cd /opt/friday-2.0 && docker compose restart friday-gateway"

# Redémarrer tous services
ssh friday-vps "cd /opt/friday-2.0 && docker compose restart"

# Rebuild complet
ssh friday-vps "cd /opt/friday-2.0 && docker compose down && docker compose up -d --build"
```

---

### Monitoring RAM (Story 1.13 - Self-Healing)

```bash
# RAM usage actuel
ssh friday-vps "free -h"

# Alertes si >85% (40.8 Go sur VPS-4 48 Go)
ssh friday-vps "cd /opt/friday-2.0 && ./scripts/monitor-ram.sh"
```

---

## 🔄 Rollback manuel

Si le rollback automatique échoue ou si vous devez revenir à une version spécifique :

### Étape 1 : Identifier version cible

```bash
# Voir derniers commits déployés
ssh friday-vps "cd /opt/friday-2.0 && git log --oneline -10"

# Exemple output :
# a1b2c3d (HEAD) feat: nouvelle feature
# e4f5g6h feat: feature précédente  <- Version stable
# i7j8k9l fix: bug fix
```

---

### Étape 2 : Arrêter services actuels

```bash
ssh friday-vps "cd /opt/friday-2.0 && docker compose down"
```

---

### Étape 3 : Revenir au commit stable

```bash
# Revenir à un commit spécifique
ssh friday-vps "cd /opt/friday-2.0 && git checkout e4f5g6h"

# OU revenir au commit précédent
ssh friday-vps "cd /opt/friday-2.0 && git checkout HEAD~1"

# OU revenir à une branche
ssh friday-vps "cd /opt/friday-2.0 && git checkout master && git pull"
```

---

### Étape 4 : Redémarrer services

```bash
ssh friday-vps "cd /opt/friday-2.0 && docker compose up -d"
```

---

### Étape 5 : Vérifier healthcheck

```bash
# Attendre 10s puis vérifier
sleep 10
ssh friday-vps "curl -s http://localhost:8000/api/v1/health | jq '.status'"
# Output attendu: "healthy"
```

---

### Étape 6 : Notification manuelle (optionnel)

```bash
# Notifier équipe du rollback
# (Remplacer $TOKEN et $TOPIC par vraies valeurs)
curl -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
  -d "chat_id=$TOPIC" \
  -d "text=⚠️ Rollback manuel effectué - Version: e4f5g6h" \
  -d "parse_mode=HTML"
```

---

## 📊 Monitoring post-déploiement

### Dashboard recommandé

```bash
# Commande à exécuter après déploiement (5-10 min)
ssh friday-vps "cd /opt/friday-2.0 && watch -n 5 'docker stats --no-stream; echo; curl -s http://localhost:8000/api/v1/health | jq'"
```

**Output attendu :**
```
CONTAINER           CPU %   MEM USAGE / LIMIT     MEM %
friday-postgres     2.5%    450MiB / 48GiB        0.9%
friday-redis        1.2%    120MiB / 48GiB        0.25%
friday-gateway      5.0%    250MiB / 48GiB        0.52%
...

{
  "status": "healthy",
  "services": { ... }
}
```

---

### Alertes à surveiller (1h post-déploiement)

| Métrique | Seuil normal | Seuil alerte | Action si dépassé |
|----------|--------------|--------------|-------------------|
| RAM totale | <70% (33.6 Go) | >85% (40.8 Go) | Vérifier fuites mémoire, redémarrer service lourd |
| CPU Gateway | <20% | >50% | Vérifier logs erreurs, charge inhabituelle |
| Healthcheck | 100% success | 1 échec | Investiguer logs, vérifier PostgreSQL/Redis |
| Erreurs logs | 0-5/min | >20/min | Vérifier stack traces, rollback si critique |

---

### Commandes monitoring continues

```bash
# Logs erreurs uniquement (temps réel)
ssh friday-vps "cd /opt/friday-2.0 && docker compose logs -f | grep -i error"

# RAM usage par service
ssh friday-vps "docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'"

# Taux erreurs HTTP (si logs structurés JSON)
ssh friday-vps "cd /opt/friday-2.0 && docker compose logs friday-gateway | jq -r 'select(.level==\"ERROR\")' | wc -l"
```

---

## 🔗 Références

<!-- LOW #17 FIX: Doc self-contained, pas de dépendances vers stories TODO -->
- **Tailscale VPN Setup** : [docs/tailscale-setup.md](../docs/tailscale-setup.md)
- **Backup automatique** : À implémenter (voir script `scripts/backup.sh` pour détails)
- **Self-Healing** : Monitoring RAM via `scripts/monitor-ram.sh` (seuil 85%)
- **Architecture complète** : [_docs/architecture-friday-2.0.md](../_docs/architecture-friday-2.0.md)

---

## 📝 Notes de version

| Date | Version | Changements |
|------|---------|-------------|
| 2026-02-10 | 1.0 | Version initiale (Story 1.16) |

---

**Questions / Support** : Créer issue GitHub ou contacter mainteneur via Telegram.
