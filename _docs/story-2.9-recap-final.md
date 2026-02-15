# Story 2.9 - Pipeline Email IMAP Direct - Récapitulatif Final

> **D25 (2026-02-13)** : EmailEngine retiré, remplacé par IMAP direct (aioimaplib).
> Ce document reflète l'état final post-déploiement du pipeline email.

**Date** : 2026-02-15
**Status** : **Opérationnel** — 3/4 comptes connectés, pipeline fonctionnel

---

## Architecture Pipeline Email

```
IMAP Servers (Gmail, Zimbra, ProtonMail Bridge)
    │
    ▼
friday-imap-fetcher (aioimaplib, IDLE + polling)
    │  UID SEARCH UNSEEN → BODY.PEEK[] → Presidio anonymize → Redis XADD
    ▼
Redis Streams: emails:received
    │  Consumer group: email-processor
    ▼
friday-email-processor (consumer.py)
    │  IMAP re-fetch → anonymize → classify (LLM) → PostgreSQL → Telegram
    ▼
Telegram Topic 📬 Email & Communications
```

---

## Réalisations

### 1. IMAP Fetcher Daemon (D25)

Container Docker dédié `friday-imap-fetcher` avec :
- **aioimaplib** 2.0.1 pour connexions IMAP async
- **IMAP IDLE** pour Gmail/Zimbra (notification push)
- **Polling** pour ProtonMail Bridge (pas de support IDLE)
- **Déduplication** via Redis SETs `seen_uids:{account_id}` (TTL 7j)
- **Anonymisation Presidio** avant publication dans Redis Streams

### 2. Comptes IMAP Connectés

| Compte | Label | Status | Mode | Notes |
|--------|-------|--------|------|-------|
| gmail1 | Gmail Pro | **Connecté** | IDLE | App Password |
| gmail2 | Gmail Perso | **Connecté** | IDLE | App Password |
| universite | Zimbra UM | **Connecté** | IDLE | Credentials directs |
| proton | ProtonMail Bridge | **Non connecté** | Polling | Bridge hors ligne (PC éteint) |

### 3. Bugs Corrigés (2026-02-15)

#### Bug 1 : UID Search (critique)

**Problème** : `self._imap.search("UNSEEN")` retournait des **numéros de séquence** (instables) au lieu d'UIDs (stables). Après reconnexion IMAP, les numéros de séquence changent → la déduplication Redis échoue → republication de tous les emails non lus.

**Fix** : `self._imap.uid("search", "UNSEEN")` — retourne des UIDs stables persistant entre sessions.

**Fichier** : `services/email_processor/imap_fetcher.py`

#### Bug 2 : Body manquant (critique)

**Problème** : `BODY.PEEK[HEADER]` ne récupérait que les en-têtes, pas le corps de l'email. Le classifier recevait un body vide → "0% caviardé" → catégorie "inconnu" systématique.

**Fix** :
- `BODY.PEEK[HEADER]` → `BODY.PEEK[]` (email complet headers + body)
- Ajout de `_extract_body_text(msg)` : extraction text/plain puis fallback text/html
- Ajout de `_has_attachments(msg)` : détection pièces jointes
- Troncature body à 2000 chars avant publication Redis Streams

**Fichier** : `services/email_processor/imap_fetcher.py`

#### Bug 3 : Notifications excessives (mineur)

**Problème** : 3 notifications Telegram par email (validation trust=propose sur Actions topic + receipt sur Metrics + notification consumer sur Email topic).

**Fix** : `email.classify` trust level changé de `propose` → `auto`. Le middleware trust crée un receipt sans notification Telegram. Seul le consumer envoie 1 notification sur le topic Email.

**Fichiers** :
- `agents/src/agents/email/classifier.py` : `trust_default="auto"`
- `config/trust_levels.yaml` : `email.classify: auto` (deux entrées)

### 4. Problèmes Déploiement VPS Résolus

| Problème | Cause | Fix |
|----------|-------|-----|
| Redis ACL crash au démarrage | Commentaires `#` non supportés dans fichiers ACL | `grep -v '^#'` pour nettoyer |
| Redis URL parsing error | `#` dans mot de passe interprété comme fragment URL | Variable `REDIS_EMAIL_PASSWORD_ENCODED` avec `%23` |
| IMAP credentials manquants | Variables `IMAP_ACCOUNT_*` absentes de `.env` | Mapping depuis `.env.email` (GMAIL_PRO_* → IMAP_ACCOUNT_GMAIL1_*, etc.) |
| Redis ACL permissions | `sismember`/`sadd` manquants pour user `friday_email` | Ajout `+sadd +sismember +srem +smembers` |
| Docker network overlap | Conflit réseau au `docker compose up` | `--project-name friday-20` pour matcher réseau existant |
| 189 emails backlog | Anciens messages spam dans le stream | `XTRIM MAXLEN 0` + `DEL seen_uids:*` + reset consumer group |

### 5. Sécurité & Secrets

- Redis ACL : 10 utilisateurs avec mots de passe 32 caractères
- `.env` et `.env.email` chiffrés SOPS/age
- Presidio anonymisation opérationnel (obligatoire avant tout appel LLM)
- Mapping Presidio éphémère en mémoire (jamais persisté)

---

## État Système Actuel (2026-02-15)

### Services Docker

| Service | Status | Notes |
|---------|--------|-------|
| friday-postgres | Healthy | PostgreSQL 16 + pgvector |
| friday-redis | Healthy | ACL appliqués, Streams configurés |
| friday-imap-fetcher | Healthy | 3/4 comptes IDLE |
| friday-email-processor | Healthy | Consumer group actif |
| friday-presidio-analyzer | Healthy | spaCy FR |
| friday-presidio-anonymizer | Healthy | - |
| friday-bot | Healthy | 5 topics Telegram |

### Redis Streams

- Stream : `emails:received`
- Consumer group : `email-processor`
- Backlog : **0** (nettoyé 2026-02-15)
- Dédup SETs : recréés proprement avec UIDs

### Fichiers Modifiés (session 2026-02-15)

| Fichier | Modification |
|---------|-------------|
| `services/email_processor/imap_fetcher.py` | UID search + BODY.PEEK[] + helpers extraction |
| `agents/src/agents/email/classifier.py` | trust_default propose → auto |
| `config/trust_levels.yaml` | email.classify propose → auto |

### Fichiers VPS Modifiés

| Fichier VPS | Modification |
|-------------|-------------|
| `/opt/friday/config/redis.acl` | Commentaires supprimés, commandes SET ajoutées |
| `/opt/friday/.env` | `REDIS_EMAIL_PASSWORD_ENCODED` + `IMAP_ACCOUNT_*` variables |
| `/opt/friday/docker-compose.yml` | `REDIS_EMAIL_PASSWORD` → `REDIS_EMAIL_PASSWORD_ENCODED` dans REDIS_URL |

---

## Actions Restantes

### ProtonMail Bridge (non bloquant)

**Status** : Bridge hors ligne — le PC Mainteneur doit être allumé avec ProtonMail Bridge actif pour que le compte `proton` se connecte.

**Debug** :
```bash
# Vérifier connectivité depuis VPS
ssh friday-vps "nc -zv <bridge_tailscale_ip> 1143"

# Si timeout → Bridge pas démarré ou Tailscale déconnecté sur PC
# Si connexion OK → vérifier logs imap-fetcher
ssh friday-vps "docker logs friday-imap-fetcher --tail 50 | grep proton"
```

### Git Push (non bloquant)

Le commit local `f5eac88` n'a pas pu être pushé (DNS GitHub inaccessible). À pusher manuellement :
```bash
git push origin master
```

### Phase D - Migration Historique (Phase 2)

- Migration 108k emails (`scripts/migrate_emails.py`)
- Nécessite pipeline E2E validé sur quelques emails réels

---

## Commits Associés

```
f5eac88 - fix(imap-fetcher): UID search + full body fetch + reduce notifications
8e8a453 - fix(imap-fetcher): extract anonymized_text from AnonymizationResult
f6c96a5 - fix(imap-fetcher): add ProtonMail Bridge SSL certificate support
```

---

## Leçons Apprises

1. **IMAP UID vs séquence** : Toujours utiliser `uid("search", ...)` et `uid("fetch", ...)` avec aioimaplib. Les numéros de séquence sont instables entre sessions.
2. **Redis ACL** : Les fichiers `.acl` ne supportent PAS les commentaires `#` (contrairement à `redis.conf`).
3. **URL encoding** : Les caractères spéciaux (`#`, `@`, etc.) dans les mots de passe Redis doivent être URL-encodés quand utilisés dans une URI.
4. **Trust level calibration** : `propose` sur une action haute fréquence (classify) génère trop de notifications. Utiliser `auto` pour les actions de classification, réserver `propose` pour les actions modificatrices.

---

**Dernière mise à jour** : 2026-02-15
**Pipeline** : Opérationnel (3/4 comptes, en attente ProtonMail Bridge)
