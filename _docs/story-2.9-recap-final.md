# Story 2.9 - Configuration Pipeline Email - Récapitulatif Final

> **[SUPERSEDE D25]** : EmailEngine a été remplacé par IMAP direct (aioimaplib + aiosmtplib) le 2026-02-13.
> Ce document est conservé comme référence historique. Les sections relatives à EmailEngine (webhooks, access token, UI config) ne sont plus applicables.
> Voir : `_docs/plan-d25-emailengine-to-imap-direct.md` pour le nouveau plan.

**Date** : 2026-02-13
**Status** : ~~95% complété~~ **[SUPERSEDE D25]** — EmailEngine retiré, remplacé par imap-fetcher daemon

---

## ✅ Réalisations

### 1. ~~Configuration EmailEngine~~ [SUPERSEDE D25 : remplacé par imap-fetcher] (3/4 comptes)

| Compte | Email | Status | Notes |
|--------|-------|--------|-------|
| account_faculty | antonio.lopez@umontpellier.fr | ✅ Connected | Zimbra Université |
| account_personal | contact.antoniolopez@gmail.com | ✅ Connected | Gmail 2 |
| account_professional | lopez.tonio@gmail.com | ✅ Connected | Gmail 1 |
| account_protonmail | contact.antoniolopez@proton.me | ❌ Auth Error | Bridge configuré mais "no such user" depuis VPS |

~~**Access Token** : `REDACTED_EMAILENGINE_TOKEN`~~ **[SUPERSEDE D25 : token EmailEngine obsolète]**

### 2. Sécurité & Secrets

#### Rotation Redis ACL (10 utilisateurs)
- ✅ Nouveaux mots de passe 32 caractères générés
- ✅ ACL appliqués via `redis-cli ACL SETUSER`
- ✅ Tous services redémarrés avec nouveaux credentials
- ✅ Scripts créés :
  - `scripts/Generate-NewRedisPasswords.ps1` (génération)
  - `scripts/rotate-redis-passwords.sh` (rotation VPS)

#### Secrets Management
- ✅ `WEBHOOK_SECRET` généré : `REVOKED_WEBHOOK_SECRET`
- ~~✅ `EMAILENGINE_SECRET` et `EMAILENGINE_ENCRYPTION_KEY` configurés~~ **[SUPERSEDE D25 : variables retirées]**
- ✅ `.env` et `.env.email` chiffrés avec SOPS
- ✅ `.gitignore` mis à jour (config/redis.acl, run_migrations_temp.py, .env.decrypted)

### 3. ~~Infrastructure Webhook~~ [SUPERSEDE D25 : webhooks EmailEngine retirés, remplacés par IMAP IDLE + polling → Redis Streams]

#### ~~Gateway modifications~~ [SUPERSEDE D25]
- ~~✅ Support webhook global EmailEngine (`/emailengine/all`)~~
- ~~✅ Extraction `account_id` depuis payload (source de vérité)~~
- ~~✅ Signature HMAC-SHA256 optionnelle (sécurisé par réseau Docker)~~
- ~~✅ Fichier : `services/gateway/routes/webhooks.py`~~
- ~~✅ Commit : `43990e7` - feat(webhooks): support EmailEngine global webhook URL~~

#### Redis Streams
- ✅ Consumer group `email-processor` créé sur stream `emails:received`
- ✅ Tous services healthy après redémarrage

### 4. Pipeline Email

- ✅ `PIPELINE_ENABLED=true` configuré
- ⚠️ `ANTHROPIC_API_KEY` = placeholder (à remplacer)
- ✅ Service `friday-email-processor` healthy
- ✅ Presidio anonymization prêt

---

## ⚠️ Actions Manuelles Requises

### ~~Action 1 : Configurer Webhooks EmailEngine~~ [SUPERSEDE D25 : plus nécessaire, imap-fetcher publie directement sur Redis Streams]

~~**Problème** : L'API `/v1/settings` ne persiste pas la configuration~~

~~**Solution** : Configuration via interface web~~

~~**Steps** :~~
~~1. Interface web : `http://localhost:3001` (tunnel SSH ouvert)~~
~~2. Menu → **Configuration** → **Webhooks**~~
~~3. Webhooks Enabled = `true`~~
~~4. Webhook URL = `http://friday-gateway:8000/api/v1/webhooks/emailengine/all`~~
~~5. Save~~

~~**Guide détaillé** : `scripts/configure-emailengine-webhooks.md`~~

### Action 2 : Configurer ANTHROPIC_API_KEY (CRITIQUE)

**Fichier** : `/opt/friday/.env` sur VPS

**Steps** :
```bash
ssh friday-vps
cd /opt/friday
nano .env  # Remplacer placeholder_will_set_later par vraie API key
sops -e .env > .env.enc
docker restart friday-email-processor friday-gateway
```

### Action 3 : ProtonMail Bridge (OPTIONNEL)

**Problème** : "no such user" depuis VPS malgré Bridge configuré

**Hypothèses** :
- Firewall Tailscale bloque 100.100.4.31:1143
- Bridge nécessite restart après ajout compte
- Rate limiting actif

**Credentials confirmés** (depuis screenshot) :
- Username: `contact.antoniolopez@proton.me`
- Password: `REDACTED_PROTONMAIL_BRIDGE_PASSWORD`
- Host: `100.100.4.31:1143` (Tailscale)
- Security: STARTTLS

**Debug** :
```bash
# Test connexion depuis VPS
ssh friday-vps "nc -zv 100.100.4.31 1143"

# Si timeout → vérifier Tailscale sur PC
# Si connexion OK mais auth fail → restart Bridge + attendre 5 min
```

---

## 🧪 Test E2E

### Prérequis
1. ~~✅ Webhooks EmailEngine configurés (Action 1)~~ [SUPERSEDE D25]
2. ✅ ANTHROPIC_API_KEY configurée (Action 2)

### Procédure Test

**Script automatisé** : `scripts/test-email-pipeline-e2e.sh`

```bash
ssh friday-vps 'bash -s' < scripts/test-email-pipeline-e2e.sh
```

**Test manuel** :
1. Envoyer email test → `antonio.lopez@umontpellier.fr`
2. Vérifier logs :
   ```bash
   # Gateway (webhook reçu)
   ssh friday-vps "docker logs friday-gateway --tail 50 | grep webhook"
   
   # Redis Streams (événement publié)
   ssh friday-vps bash <<'EOF'
   cd /opt/friday && source .env
   docker exec friday-redis redis-cli --user admin --pass "$REDIS_ADMIN_PASSWORD" \
     XREAD COUNT 1 STREAMS emails:received 0
   EOF
   
   # Email-processor (traitement)
   ssh friday-vps "docker logs friday-email-processor --tail 50"
   ```

---

## 📊 État Système Actuel

### Services Docker

| Service | Status | Port | Notes |
|---------|--------|------|-------|
| friday-postgres | ✅ Healthy | 5432 | - |
| friday-redis | ✅ Healthy | 6379 | ACL rotated |
| friday-gateway | ✅ Healthy | 8000 | Webhook endpoint ready |
| ~~friday-emailengine~~ | ~~✅ Healthy~~ | ~~3000~~ | ~~3/4 comptes connected~~ **[SUPERSEDE D25 : retiré, remplacé par friday-imap-fetcher]** |
| friday-email-processor | ✅ Healthy | - | Consumer group created |
| friday-presidio-analyzer | ✅ Healthy | 5001 | - |
| friday-presidio-anonymizer | ✅ Healthy | 5002 | - |

### Configuration Files

| Fichier | Status | Location |
|---------|--------|----------|
| `.env` | ✅ Chiffré | VPS `/opt/friday/.env.enc` |
| `.env.email` | ✅ Chiffré | VPS `/opt/friday/.env.email.enc` |
| `config/redis.acl` | ✅ Généré | VPS `/opt/friday/config/redis.acl` (gitignored) |

### Commits

```
43990e7 - feat(webhooks): support EmailEngine global webhook URL + optional HMAC signature
f5b5b10 - security: remove default Redis password fallbacks from docker-compose
6561d36 - security: add redis.acl.template and generation scripts
```

---

## 📝 Fichiers Créés/Modifiés

### Nouveaux fichiers
- `scripts/Generate-NewRedisPasswords.ps1` - Génération passwords Redis
- `scripts/rotate-redis-passwords.sh` - Rotation ACL Redis
- ~~`scripts/configure-emailengine-webhooks.md` - Guide config webhooks~~ [SUPERSEDE D25]
- `scripts/test-email-pipeline-e2e.sh` - Test E2E automatisé
- `config/redis.acl.template` - Template ACL Redis
- `scripts/generate-redis-acl.sh` - Génération redis.acl

### Fichiers modifiés
- ~~`services/gateway/routes/webhooks.py` - Support webhook global~~ [SUPERSEDE D25 : endpoint webhook EmailEngine retiré]
- `docker-compose.yml` - Suppression default passwords
- `docker-compose.services.yml` - Suppression default passwords
- `.gitignore` - Ajout config/redis.acl, run_migrations_temp.py

---

## 🚀 Prochaines Étapes

### ~~Phase C.6 - Finalisation Webhooks~~ [SUPERSEDE D25]
1. ~~☐ Configurer webhooks EmailEngine via UI (Action 1)~~ [SUPERSEDE D25]
2. ☐ Configurer ANTHROPIC_API_KEY (Action 2) — toujours requis
3. ☐ Test E2E : envoyer email → vérifier logs complets
4. ~~☐ Valider flux : EmailEngine → Gateway → Redis → Processor~~ → Nouveau flux : imap-fetcher → Redis Streams → Processor

### Phase D - Migration Historique (Phase 2)
- ☐ Migration 108k emails (Story 2.9 Phase D)
- ☐ Script : `scripts/migrate_emails.py` (déjà existant)
- ☐ Nécessite : Webhooks + API key configurés

---

## 📞 Support

~~**Tunnel SSH EmailEngine** : `http://localhost:3001`~~ [SUPERSEDE D25]
**Logs en temps réel** : `ssh friday-vps "docker logs -f friday-email-processor"`
**Redis CLI** : `ssh friday-vps "docker exec -it friday-redis redis-cli --user admin --pass <PASSWORD>"`

---

**Dernière mise à jour** : 2026-02-13 (D25 : annotations ajoutées, EmailEngine retiré)
**Prochaine action** : ~~Configuration webhooks EmailEngine via interface web~~ → Validation imap-fetcher daemon
