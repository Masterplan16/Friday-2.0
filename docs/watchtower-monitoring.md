# Watchtower Docker Image Monitoring

**Story 1.14** - Surveillance des mises à jour d'images Docker sans auto-update

---

## 🎯 Vue d'ensemble

Watchtower surveille les images Docker utilisées par Friday 2.0 et envoie des notifications Telegram (topic System) lorsqu'une nouvelle version est disponible. **JAMAIS d'auto-update** - le Mainteneur décide manuellement quand mettre à jour.

### Caractéristiques

- ✅ Mode **MONITOR_ONLY** (pas d'auto-update)
- ✅ Vérification **quotidienne à 03h00** (après backup)
- ✅ Notifications **Telegram topic System** via Shoutrrr
- ✅ **Docker socket read-only** (sécurité)
- ✅ Resource usage minimal (~100 MB RAM)

---

## 🚀 Démarrage

### Prérequis

- Docker Compose
- Variables d'environnement :
  - `TELEGRAM_BOT_TOKEN` (Story 1.9)
  - `TOPIC_SYSTEM_ID` (Story 1.9)

### Lancement

```bash
# Démarrer tous les services (inclut Watchtower)
docker compose -f docker-compose.yml -f docker-compose.services.yml up -d

# Vérifier Watchtower est running
docker ps | grep watchtower

# Expected output:
# friday-watchtower   containrrr/watchtower:latest   ...   Up X minutes
```

---

## 📋 Configuration

### Variables d'environnement

| Variable | Valeur | Description |
|----------|--------|-------------|
| `WATCHTOWER_MONITOR_ONLY` | `true` | **CRITICAL** - Pas d'auto-update, notifications seulement |
| `WATCHTOWER_POLL_INTERVAL` | `86400` | Fallback 24h (si schedule échoue) |
| `WATCHTOWER_SCHEDULE` | `0 0 3 * * *` | Cron 03h00 daily (prioritaire) |
| `WATCHTOWER_NOTIFICATIONS` | `shoutrrr` | Backend notifications (supporte Telegram) |
| `WATCHTOWER_NOTIFICATION_URL` | `telegram://...` | URL Telegram via Shoutrrr |
| `WATCHTOWER_CLEANUP` | `false` | Pas de cleanup auto images |

### Volumes

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro  # Read-only CRITICAL
```

**Rationale read-only** : Watchtower monitor-only n'a PAS besoin d'écriture sur le socket Docker. Defense in depth.

### Labels

```yaml
labels:
  - "com.centurylinklabs.watchtower.enable=false"
```

Watchtower ne se surveille pas lui-même (évite récursion).

---

## 🔔 Notifications Telegram

### Format message (automatique)

```
🔔 Docker Update Available

Service: postgres
Current: 16.1
New: 16.2

Command:
docker compose pull postgres
docker compose up -d postgres
```

### Topic utilisé

**Topic System** (`TOPIC_SYSTEM_ID`) - Notifications infrastructure non-critiques.

### Fréquence

1x par jour maximum (check à 03h00). Si plusieurs services outdated, regroupés en un seul message.

---

## 🛠️ Workflow Manuel Update

Lorsqu'une notification est reçue :

### 1. Évaluer l'update

- Consulter les release notes du service
- Identifier breaking changes potentiels
- Vérifier compatibilité Friday 2.0

### 2. Tester en local (optionnel mais recommandé)

```bash
# Pull nouvelle image
docker pull <service>:<new-tag>

# Test en local si possible
docker run --rm <service>:<new-tag> --version
```

### 3. Update production

```bash
# Commande suggérée dans la notification Telegram
docker compose pull <service>
docker compose up -d <service>

# Exemple :
docker compose pull postgres
docker compose up -d postgres
```

### 4. Vérifier healthcheck

```bash
# Vérifier le service est healthy
docker ps | grep <service>

# Vérifier logs pour erreurs
docker logs <service> --tail 50

# Test healthcheck global
curl http://localhost:8000/api/v1/health
```

### 5. Rollback si nécessaire

Si le service échoue après update :

```bash
# Arrêter le service
docker compose down <service>

# Re-démarrer (utilisera l'image cache précédente)
docker compose up -d <service>

# Alternative : spécifier tag précédent explicitement
docker pull <service>:<old-tag>
docker compose up -d <service>
```

---

## 🔍 Monitoring & Troubleshooting

### Vérifier logs Watchtower

```bash
# Derniers 50 logs
docker logs watchtower --tail 50

# Logs en temps réel
docker logs -f watchtower

# Filtrer updates détectés
docker logs watchtower | grep -i "found new"
```

### Vérifier resource usage

```bash
# Stats en temps réel
docker stats watchtower

# Expected:
# CONTAINER         CPU %     MEM USAGE / LIMIT     MEM %
# friday-watchtower 0.01%     80MiB / 200MiB        40%
```

**Seuils** :
- RAM : < 200 MB (limit), ~100 MB (normal)
- CPU : < 5% (spike pendant check 03h00)

### Trigger manuel check (debug)

```bash
# Forcer un check immédiat (debug uniquement)
docker exec watchtower /watchtower --run-once

# Note: Ceci ne remplace PAS le schedule automatique
# Utiliser UNIQUEMENT pour debug/test
```

### Problèmes courants

#### ❌ Pas de notifications reçues

**Symptômes** : Watchtower tourne, mais aucune notification Telegram.

**Debug** :
```bash
# Vérifier env vars
docker inspect watchtower | grep -i telegram

# Vérifier logs erreurs
docker logs watchtower | grep -i error

# Tester URL Shoutrrr manuellement
# (nécessite shoutrrr CLI ou curl)
```

**Solutions** :
1. Vérifier `TELEGRAM_BOT_TOKEN` et `TOPIC_SYSTEM_ID` corrects
2. Vérifier bot Telegram a accès au topic System
3. Vérifier pas de firewall bloquant Telegram API

#### ❌ Watchtower ne démarre pas

**Symptômes** : Container en état `Restarting` ou `Exited`.

**Debug** :
```bash
docker logs watchtower --tail 100
```

**Solutions** :
1. Vérifier `/var/run/docker.sock` accessible
2. Vérifier pas de conflit de port (Watchtower n'expose pas de port par défaut)
3. Vérifier syntax YAML `docker-compose.services.yml`

#### ❌ Auto-update se produit (CRITICAL)

**Symptômes** : Container mis à jour automatiquement sans validation manuelle.

**Impact** : **CRITIQUE** - AC4 violé, risque de régression/downtime.

**Debug** :
```bash
# Vérifier MONITOR_ONLY est bien true
docker inspect watchtower | grep MONITOR_ONLY

# Expected: "WATCHTOWER_MONITOR_ONLY=true"
```

**Actions immédiates** :
1. Arrêter Watchtower immédiatement : `docker stop watchtower`
2. Vérifier configuration `docker-compose.services.yml`
3. Corriger `WATCHTOWER_MONITOR_ONLY=true`
4. Relancer : `docker compose up -d watchtower`
5. Créer incident post-mortem

---

## 🧪 Tests

### Unit tests

```bash
pytest tests/unit/infra/test_watchtower_config.py -v
```

**Coverage** : 6 tests
- Service watchtower exists
- MONITOR_ONLY=true
- Docker socket read-only
- Schedule configured
- Telegram notification URL
- Self-exclusion label

### Integration tests

```bash
pytest tests/integration/test_watchtower_notifications.py -v
```

**Coverage** : 4 tests
- Détection nouvelle image
- Monitor-only behavior (CRITICAL)
- Notifications Telegram
- Config validation

### E2E test

```bash
bash tests/e2e/test_watchtower_end_to_end.sh
```

**Scénario** : Image v1 → v2 disponible → Notification Telegram → Pas d'auto-update

---

## 📚 Références

### Documentation officielle

- [Watchtower Arguments](https://containrrr.dev/watchtower/arguments/) - Options configuration
- [Watchtower Container Selection](https://containrrr.dev/watchtower/container-selection/) - Labels opt-in/opt-out
- [Shoutrrr Telegram](https://containrrr.dev/shoutrrr/v0.8/services/telegram/) - Format URL notifications

### Architecture Friday 2.0

- **[_docs/architecture-friday-2.0.md](_docs/architecture-friday-2.0.md)** - Architecture globale
- **[_bmad-output/planning-artifacts/epics-mvp.md](_bmad-output/planning-artifacts/epics-mvp.md)** - Epic 1 Story 1.14

### Stories dépendances

- **Story 1.1** - Docker Compose infrastructure
- **Story 1.9** - Bot Telegram topic System
- **Story 1.13** - Self-healing (timing coordination 03h00-03h30)

---

## 🔐 Sécurité

### Read-only Docker socket

Watchtower n'a besoin que de **lire** l'état des containers (mode monitor-only). Le socket est monté en **read-only** `:ro`.

**Impact si compromis** : Attaquant peut lire état containers, mais PAS créer/modifier/supprimer.

### Exclusion de services sensibles

Services qui NE doivent PAS être surveillés peuvent opt-out :

```yaml
labels:
  - "com.centurylinklabs.watchtower.enable=false"
```

**Exemples** :
- Services de développement local (tags `dev`, `test`)
- Services critiques nécessitant validation manuelle extensive

### Notifications chiffrées

Communications Telegram chiffrées end-to-end via HTTPS Telegram Bot API.

---

## ⚙️ Customisation

### Surveillance sélective (opt-in)

Par défaut, Watchtower surveille **tous** les containers sauf ceux avec `enable=false`.

Pour inverser (opt-in uniquement) :

```yaml
environment:
  - WATCHTOWER_LABEL_ENABLE=true  # Surveille UNIQUEMENT containers avec label enable=true
```

**Non recommandé** pour Friday 2.0 (15+ services, opt-out sélectif plus simple).

### Modifier schedule

```yaml
environment:
  # Cron format: second minute hour day month weekday
  - WATCHTOWER_SCHEDULE=0 0 2 * * *  # 02h00 au lieu de 03h00
```

**Rationale 03h00 actuel** :
- Backup PostgreSQL = 03h00 (Story 1.12)
- OS updates/reboot = 03h30 (Story 1.13)
- Briefing matinal = 08h00 (Story 4.2)

### Notification custom format (avancé)

Watchtower ne supporte pas de template custom facilement. Pour format avancé :

**Option A** : Parser logs Watchtower + script Python custom

```python
# scripts/watchtower-notify-custom.py
import subprocess

logs = subprocess.run(["docker", "logs", "watchtower", "--tail", "100"], ...)
# Parse logs + envoyer message custom Telegram
```

**Option B** : Utiliser webhook HTTP + service intermédiaire

Non implémenté dans Story 1.14 (scope minimal). À considérer si besoins évoluent.

---

**Version** : 1.0.0 (2026-02-10)
**Story** : 1.14 - Monitoring Docker Images
**Mainteneur** : Antonio
