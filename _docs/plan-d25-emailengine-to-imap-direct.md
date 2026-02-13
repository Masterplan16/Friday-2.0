# Plan D25 : Remplacement EmailEngine par IMAP Direct

**Date** : 2026-02-13
**Statut** : Approuve (post-review adversariale)
**Decision** : D25

---

## Contexte

EmailEngine (PostalSys) coute 99 EUR/an — non prevu au budget initial. Le code existant (~2900 lignes, 15+ fichiers) a ete ecrit par Claude Code en ~1 jour, le cout de reecriture est donc negligeable (pas de salaries).

**Decision** : Retirer EmailEngine. Implementer IMAP direct via `aioimaplib` 2.0.1 (IDLE natif) + `aiosmtplib` (envoi). Creer adaptateur `adapters/email.py` obligatoire.

**Impact budget** : 81 EUR/mois -> 73 EUR/mois (economie 99 EUR/an)

---

## Review Adversariale (10 failles identifiees et corrigees)

| # | Faille | Severite | Correction |
|---|--------|----------|------------|
| 1 | IMAP IDLE instable sur ProtonMail Bridge | **Haute** | Polling obligatoire pour ProtonMail, detection IDLE silencieux (heartbeat 30 min) |
| 2 | Pas de deduplication apres crash/reconnexion | **Haute** | Redis SET `seen_uids:{account}` avec TTL 7 jours |
| 3 | Attachments volumineux bloquent le fetch | **Moyenne** | BODYSTRUCTURE d'abord, limite configurable `MAX_ATTACHMENT_SIZE_MB=25` |
| 4 | Pas de test integration IMAP reel | **Moyenne** | Dovecot en Docker pour tests integration |
| 5 | `aioimaplib` — etat du projet inconnu | **Haute** | Verifie : v2.0.1 (jan 2025), maintenu par Iroco, 161 stars, IDLE OK |
| 6 | OAuth2/XOAUTH2 Gmail non gere | **Haute** | Module OAuth2 prepare (pas active Day 1, App Passwords suffisent) |
| 7 | Complexite SMTP sous-estimee | **Moyenne** | Threading In-Reply-To/References, MIME multipart, bounces documentes |
| 8 | SPOF si fetcher integre au consumer | **Moyenne** | Container Docker separe `friday-imap-fetcher` |
| 9 | IDLE timeout 29 min (RFC 2177) | **Haute** | IDLE renew loop toutes les 25 min |
| 10 | Suppression webhooks.py trop agressive | **Faible** | Retirer routes EE seulement, garder le fichier |

---

## Veille Technique (Checklist D21)

- **aioimaplib** 2.0.1 (janvier 2025) : Maintenu par organisation Iroco, 161 GitHub stars, 23/25 commandes IMAP4rev1, RFC 2177 IDLE supporte nativement, asyncio natif, zero runtime dependencies
- **aiosmtplib** : Envoi SMTP async, STARTTLS/TLS, maintenu activement
- **Pas de MCP/skill existant** pour IMAP direct

---

## Phase 0 — Decision & Preparation

### Tache 0.1 : Enregistrer D25 dans `docs/DECISION_LOG.md`
- Contexte, alternatives evaluees, review adversariale, 10 failles corrigees

### Tache 0.2 : Veille technique (checklist D21)
- aioimaplib 2.0.1 — maintenu, IDLE OK, asyncio natif
- aiosmtplib — envoi async, STARTTLS/TLS
- Pas de MCP/skill existant pour IMAP

---

## Phase 1 — Fondations (adaptateur + fetcher + sender)

### Tache 1.1 : Creer `agents/src/adapters/email.py`
- Interface abstraite `EmailAdapter` :
  - `get_message()`, `send_message()`, `download_attachment()`
  - `list_accounts()`, `check_health()`
- Implementation `IMAPDirectAdapter` + `SMTPDirectAdapter`
- Factory `get_email_adapter()` avec `EMAIL_PROVIDER=imap_direct`
- Pattern identique a `adapters/llm.py`

### Tache 1.2 : Creer `services/email_processor/imap_fetcher.py`
*(Corrige failles 1, 2, 3, 8, 9)*

- **Container Docker separe** `friday-imap-fetcher` (faille 8) — PAS integre au consumer
- Daemon asyncio, 4 connexions IMAP concurrentes
- **IMAP IDLE** pour Gmail + Zimbra, **IDLE renew toutes les 25 min** (faille 9, RFC 2177 timeout 29 min)
- **Polling explicite** pour ProtonMail Bridge (faille 1) — intervalle configurable `IMAP_POLL_INTERVAL=60`
- **Detection IDLE silencieux** : heartbeat interne, si aucun IDLE event en 30 min -> force reconnexion (faille 1)
- **Deduplication UIDs** (faille 2) : Redis SET `seen_uids:{account_id}` avec TTL 7 jours. Avant traitement -> `SISMEMBER`. Apres traitement -> `SADD`
- **Streaming attachments** (faille 3) : fetch body structure d'abord (`BODYSTRUCTURE`), si PJ > 25 Mo -> fetch partiel ou skip + alerte Telegram. Limite configurable `MAX_ATTACHMENT_SIZE_MB=25`
- **Reconnexion** : backoff exponentiel (1s, 2s, 4s, 8s, max 60s)
- Sur nouveau mail : fetch -> anonymise via Presidio -> publie `RedisEmailEvent` sur stream `emails:received`
- Format Redis **identique** a l'existant -> consumer inchange
- Graceful shutdown (SIGTERM), logging structure JSON
- Healthcheck : endpoint HTTP simple `/health` ou fichier `/tmp/fetcher-alive` (touch toutes les 30s)

### Tache 1.3 : Creer `services/email_processor/smtp_sender.py`
*(Corrige faille 7)*

- Envoi SMTP via `aiosmtplib`
- **Threading conversation** (faille 7) : gestion `In-Reply-To` + `References` headers
- **MIME multipart** : text/plain + text/html + pieces jointes sortantes
- **Bounces** : catch SMTP errors (550, 553) -> log + alerte, pas de retry sur permanent failure
- Support TLS/STARTTLS, auth multi-comptes
- Retry avec backoff (3 tentatives) sur erreurs transitoires uniquement

### Tache 1.4 : Gestion OAuth2/XOAUTH2
*(Corrige faille 6)*

- Module `services/email_processor/oauth2_manager.py`
- Support Gmail XOAUTH2 (refresh token -> access token)
- Day 1 : App Passwords suffisent. Module **prepare mais pas active**
- Configurable : `GMAIL_AUTH_METHOD=app_password|oauth2`
- Si Google desactive App Passwords -> activer OAuth2 sans reecrire le fetcher

---

## Phase 2 — Integration Docker + Config

### Tache 2.1 : Adapter `docker-compose.yml` + `docker-compose.services.yml`
- Retirer service `emailengine` (container, volume `emailengine-data`, network IP 172.20.0.36, healthcheck)
- Retirer variables `EMAILENGINE_*` du service `email-processor`
- **Ajouter** service `imap-fetcher` :
  - Container separe, `restart: unless-stopped`
  - Healthcheck dedie
  - Depend de : `redis`, `postgres`
  - Meme network `friday-network`
- Liberer Redis DB 2 (etait dedie a EmailEngine)

### Tache 2.2 : Adapter `.env.example` + `.env.email.enc`
- Retirer : `EMAILENGINE_SECRET`, `EMAILENGINE_ENCRYPTION_KEY`, `EMAILENGINE_BASE_URL`, `REDIS_EMAILENGINE_PASSWORD`
- Garder : credentials IMAP/SMTP des 4 comptes (deja dans `.env.email.enc`)
- Ajouter : `EMAIL_PROVIDER=imap_direct`, `IMAP_IDLE_TIMEOUT=300`, `IMAP_POLL_INTERVAL=60`, `MAX_ATTACHMENT_SIZE_MB=25`, `GMAIL_AUTH_METHOD=app_password`

### Tache 2.3 : Adapter `config/redis.acl`
- Retirer ACL user `friday_emailengine`
- Fetcher utilise ACL `friday_email_processor` existant
- Ajouter permissions pour les cles `seen_uids:*` (SET pour deduplication)

---

## Phase 3 — Adaptation pipeline existant

### Tache 3.1 : Adapter `services/email_processor/consumer.py`
- Remplacer `emailengine_client.get_message()` -> `email_adapter.get_message()`
- Attachments via adaptateur au lieu de l'API EmailEngine
- Stream Redis `emails:received` -> **inchange**
- Format `RedisEmailEvent` -> **inchange**

### Tache 3.2 : Adapter `services/gateway/routes/webhooks.py`
*(Corrige faille 10)*

- **Ne PAS supprimer le fichier** — retirer uniquement les routes `/emailengine/*`
- Garder la structure pour futurs webhooks (n8n, etc.)
- L'anonymisation Presidio **migre** dans `imap_fetcher.py`

### Tache 3.3 : Migration DB `032_remove_emailengine_specifics.sql`
- Retirer colonnes specifiques EmailEngine si necessaire
- Garder la table `ingestion.email_accounts` — renommer/adapter colonnes pour IMAP direct
- Ajouter colonne `auth_method TEXT CHECK (auth_method IN ('password','app_password','oauth2'))` si absente

### Tache 3.4 : Adapter les agents email
- `agents/src/agents/email/attachment_extractor.py` -> utiliser adaptateur
- `agents/src/agents/email/draft_reply.py` -> utiliser `smtp_sender` via adaptateur
- `bot/action_executor_draft_reply.py` -> adapter appels

---

## Phase 4 — Tests

### Tache 4.1 : Tests unitaires (mocked)
- Tests `IMAPDirectAdapter` — mocker `aioimaplib`
- Tests `SMTPDirectAdapter` — mocker `aiosmtplib`
- Tests `imap_fetcher.py` : IDLE renew, reconnexion, deduplication UIDs, streaming PJ
- Tests `oauth2_manager.py` : refresh token flow
- **JAMAIS** de connexion IMAP/SMTP reelle en unit tests

### Tache 4.2 : Tests integration avec Dovecot Docker
*(Corrige faille 4)*

- Ajouter `docker-compose.test.yml` avec service Dovecot (serveur IMAP leger)
- Test reel : envoyer un mail dans Dovecot -> fetcher le detecte via IDLE -> arrive dans Redis Streams
- Test reconnexion : kill connexion -> fetcher se reconnecte
- Test deduplication : meme mail 2x -> 1 seul event Redis

### Tache 4.3 : Adapter tests existants
- `tests/unit/gateway/test_webhooks_emailengine.py` -> supprimer (routes retirees)
- `tests/unit/services/test_emailengine_client_send.py` -> remplacer par `test_smtp_sender.py`
- `tests/unit/infra/test_emailengine_config.py` -> remplacer par `test_imap_config.py`
- `tests/unit/infra/test_docker_compose.py` -> adapter (plus de service emailengine)
- `tests/e2e/email-processor/test_email_reception_e2e.py` -> adapter (fetcher au lieu de webhook)
- Tous les tests E2E stories 2.x -> adapter les mocks

---

## Phase 5 — Nettoyage code

### Tache 5.1 : Supprimer le code EmailEngine

| Fichier | Action |
|---------|--------|
| `services/email_processor/emailengine_client.py` | **Supprimer** |
| `scripts/setup_emailengine_4accounts.py` | **Supprimer** |
| `scripts/setup_emailengine_accounts.py` | **Supprimer** (legacy) |
| `scripts/configure_emailengine_webhooks.py` | **Supprimer** |
| `scripts/configure-emailengine-webhooks.md` | **Supprimer** |
| `scripts/test_emailengine_health.sh` | **Remplacer** par `test_imap_health.sh` |
| `services/monitoring/emailengine_health.py` | **Reecrire** -> `imap_health.py` |
| `tests/unit/gateway/test_webhooks_emailengine.py` | **Supprimer** |
| `tests/unit/services/test_emailengine_client_send.py` | **Supprimer** |
| `tests/unit/infra/test_emailengine_config.py` | **Supprimer** |
| `tests/unit/database/test_migration_024_emailengine_accounts.py` | **Adapter** |

---

## Phase 6 — Documentation complete (119 fichiers identifies)

### Tache 6.1 : Architecture & Design (5 fichiers)

| Fichier | Modification |
|---------|-------------|
| `_docs/architecture-friday-2.0.md` | Adaptateur email = IMAP direct. Socle RAM : retirer ~500 Mo EmailEngine |
| `_docs/architecture-addendum-20260205.md` | Mettre a jour references EmailEngine |
| `_docs/analyse-fonctionnelle-complete.md` | Flux donnees : IMAP fetcher remplace EmailEngine |
| `_docs/friday-2.0-analyse-besoins.md` | Module email : IMAP direct |
| `CLAUDE.md` | Tableau adaptateurs : `EmailEngine -> IMAP direct` -> `IMAP direct (aioimaplib)`. Socle RAM : retirer EmailEngine |

### Tache 6.2 : Documentation technique (8+ fichiers)

| Fichier | Action |
|---------|--------|
| `docs/emailengine-integration.md` (447 lignes) | **Reecrire** -> `docs/imap-direct-integration.md` |
| `docs/emailengine-setup-4accounts.md` (228 lignes) | **Reecrire** -> `docs/imap-setup-4accounts.md` |
| `.env.email.README.md` | Retirer variables `EMAILENGINE_*`, documenter nouvelles variables |
| `docs/secrets-management.md` | Retirer secrets EmailEngine |
| `docs/redis-streams-setup.md` | Adapter source evenements (fetcher, pas webhook) |
| `docs/telegram-user-guide.md` | Adapter si mentions EmailEngine |
| `README.md` | Tech Stack : retirer EmailEngine, ajouter `aioimaplib` |
| `docs/implementation-roadmap.md` | Adapter Story 2.1 |

### Tache 6.3 : Stories Epic 2 (9 fichiers)

| Story | Fichier | Modification |
|-------|---------|-------------|
| **2.1** | `2-1-integration-emailengine-reception.md` | **Reecrire** : IMAP fetcher remplace EmailEngine. ACs adaptes |
| **2.2** | `2-2-classification-email-llm.md` | Input vient du fetcher, pas webhook |
| **2.3** | `2-3-detection-vip-urgence.md` | Adapter si depend d'EmailEngine API |
| **2.4** | `2-4-extraction-pieces-jointes.md` | Attachments via IMAP fetch, pas API EE |
| **2.5** | `2-5-brouillon-reponse-email.md` | Envoi via `smtp_sender`, pas EE API |
| **2.6** | `2-6-envoi-emails-approuves.md` | SMTP direct |
| **2.7** | `2-7-extraction-taches-depuis-emails.md` | Verifier references EE |
| **2.8** | `2-8-filtrage-sender-intelligent-economie-tokens.md` | Adapter source donnees |
| **2.9** | `2-9-migration-emails-progressive-deploiement.md` | Deploiement sans EE |

### Tache 6.4 : Sprint & Planning (4+ fichiers)

| Fichier | Modification |
|---------|-------------|
| `sprint-status.yaml` | Story 2.1 : noter rework IMAP direct |
| `epics-mvp.md` | Epic 2 description : IMAP direct |
| `sprint-1-mvp.md` | Adapter |
| Story recap docs (`story-2.5-*`, `story-2.9-*`) | Adapter references |

### Tache 6.5 : Config & Scripts (6+ fichiers)

| Fichier | Modification |
|---------|-------------|
| `.env.example` | Retirer `EMAILENGINE_*`, ajouter `EMAIL_PROVIDER`, `IMAP_*` |
| `scripts/verify_env.sh` | Verifier nouvelles variables, retirer anciennes |
| `scripts/generate-secrets.sh` | Retirer generation secrets EE |
| `scripts/generate-secrets.ps1` / `Generate-Secrets.ps1` | Idem |
| `scripts/rotate-redis-passwords.sh` | Retirer rotation password `friday_emailengine` |
| `config/redis.acl.template` | Retirer user `friday_emailengine` |

---

## Phase 7 — Validation finale

### Tache 7.1 : Tests complets
- Tous les unit tests passent (mocked)
- Tests integration Dovecot passent (IDLE, reconnexion, dedup)
- Tests E2E adaptes passent

### Tache 7.2 : Test VPS staging
- Deployer sur VPS
- Verifier : 4 comptes connectes (3 IDLE + 1 polling ProtonMail)
- Envoyer email test -> arrivee Redis Streams <5s
- Verifier anonymisation Presidio
- Verifier stockage PostgreSQL
- Verifier envoi SMTP (brouillon reponse)
- Verifier RAM liberee (~500 Mo)

### Tache 7.3 : Grep final
- `grep -ri "emailengine" .` -> **0 resultat** (hors DECISION_LOG contexte historique)
- Verifier aucune variable `EMAILENGINE_*` restante

---

## Dependances entre phases

```
Phase 0 (Decision)
    |
    v
Phase 1 (Fondations) -- Tache 1.2 depend de 1.1
    |
    v
Phase 2 (Docker/Config)
    |
    v
Phase 3 (Adaptation pipeline) -- depend de Phase 1 + 2
    |
    +------> Phase 6 (Documentation) -- peut demarrer des Phase 3 terminee
    |
    v
Phase 4 (Tests)
    |
    v
Phase 5 (Nettoyage)
    |
    v
Phase 7 (Validation finale)
```

---

## Risques residuels

| Risque | Probabilite | Impact | Mitigation |
|--------|-------------|--------|------------|
| ProtonMail Bridge auth "no such user" | Haute | Un compte non connecte | Bug pre-existant (identique avec EmailEngine). Debug independant |
| Google desactive App Passwords | Moyenne | Gmail deconnecte | Module OAuth2 prepare (Tache 1.4), activation en ~2h |
| aioimaplib abandonne | Faible | Maintenance lib a assumer | 161 stars, org Iroco. Fallback : `imapclient` sync wrape en thread |
| IDLE silencieux non detecte | Moyenne | Mails perdus pendant heures | Heartbeat 30 min + alerte Telegram si silence |

---

## Inventaire fichiers impactes

**Total identifie** : 119 fichiers referencant EmailEngine

- **Story files** : 11 fichiers (_bmad-output/)
- **Architecture docs** : 5 fichiers (_docs/)
- **Documentation technique** : 8+ fichiers (docs/)
- **Config files** : 5+ fichiers (CLAUDE.md, docker-compose*, .env*)
- **Sprint/planning** : 4+ fichiers
- **Scripts** : 7+ fichiers (scripts/)
- **Source code** : 10+ fichiers (services/, agents/, bot/)
- **Tests** : 14+ fichiers (tests/)
- **Migrations** : 3+ fichiers (database/migrations/)
- **Decision log** : 1 fichier (docs/DECISION_LOG.md)

---

## Comparaison avant/apres

| Critere | EmailEngine | IMAP Direct |
|---------|-------------|-------------|
| Cout/an | 99 EUR | 0 EUR |
| Latence | <1s (push) | 2-5s (IMAP IDLE) |
| RAM | +500 Mo | 0 (fetcher < 50 Mo) |
| Dependance externe | PostalSys | Aucune (libs Python) |
| Pipeline aval | Redis Streams -> consumer | **Identique** |
| OAuth2 | Gere nativement | Module prepare, activable |
| Maintenance | Updates PostalSys | aioimaplib + aiosmtplib |

---

**Version** : 2.0 (post-review adversariale)
**Approuve par** : Masterplan (2026-02-13)
**Prochaine etape** : Execution Phase 0 -> Phase 7
