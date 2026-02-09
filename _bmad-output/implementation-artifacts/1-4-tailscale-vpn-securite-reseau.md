# Story 1.4: Tailscale VPN & Sécurité Réseau

Status: done

## Story

En tant que **développeur Friday 2.0**,
Je veux **configurer Tailscale mesh VPN, durcir SSH, appliquer les Redis ACL, et valider le workflow secrets age/SOPS**,
Afin que **le VPS soit accessible uniquement via VPN sécurisé (zéro exposition Internet publique), avec authentification renforcée et moindre privilège sur tous les services**.

## Acceptance Criteria

1. SSH uniquement accessible via Tailscale (port 22 bloqué sur IP publique via UFW)
2. 2FA TOTP/hardware key activé sur le compte Tailscale (configuration manuelle dashboard)
3. Device authorization manuelle activée (nouveaux appareils en "pending" jusqu'à approbation)
4. Key expiry configuré à 90 jours dans le dashboard Tailscale
5. VPS hostname Tailscale = `friday-vps`
6. Aucun port exposé sur IP publique (tous services sur `127.0.0.1` uniquement)
7. Redis ACL opérationnelles : 6 users avec moindre privilège par service (gateway, agents, alerting, metrics, n8n, emailengine)
8. Workflow secrets age/SOPS fonctionnel : chiffrement/déchiffrement .env vérifié
9. Tests de validation sécurité couvrant tous les ACs
10. Script d'installation Tailscale VPS automatisé

## Tasks / Subtasks

- [x] Task 1 : Créer le script d'installation Tailscale VPS (AC: #5, #10)
  - [x] 1.1 Créer `scripts/setup-tailscale.sh` : installation Tailscale sur Ubuntu 22.04
  - [x] 1.2 Ajouter `--hostname friday-vps` dans le script
  - [x] 1.3 Activer `tailscaled` au démarrage (`systemctl enable tailscaled`)
  - [x] 1.4 Ajouter vérification post-install (`tailscale status`)

- [x] Task 2 : Créer le script de durcissement SSH et firewall (AC: #1, #6)
  - [x] 2.1 Créer `scripts/harden-ssh.sh` : configuration sshd_config (ListenAddress = IP Tailscale)
  - [x] 2.2 Configuration UFW : `allow from 100.64.0.0/10 to any port 22`, `deny 22/tcp`
  - [x] 2.3 Autoriser interface Tailscale dans UFW (`ufw allow in on tailscale0`)
  - [x] 2.4 Ajouter vérification post-durcissement (test SSH Tailscale OK, SSH publique KO)

- [x] Task 3 : Valider et corriger Redis ACL existante (AC: #7)
  - [x] 3.1 Auditer `config/redis.acl` contre les permissions documentées dans addendum 9.2
  - [x] 3.2 Vérifier que `friday_gateway` a : cache read/write + pub/sub + healthcheck streams
  - [x] 3.3 Vérifier que `friday_agents` a : streams + mapping Presidio (TTL éphémère)
  - [x] 3.4 Vérifier que `friday_alerting` a : consommer streams + publier alertes (read + pubsub, pas write arbitraire)
  - [x] 3.5 Vérifier que `friday_n8n` a : cache lecture + pub/sub
  - [x] 3.6 Vérifier que `friday_emailengine` a : accès dédié DB Redis 2
  - [x] 3.7 S'assurer que `user default off` (force auth, pas de connexion anonyme)

- [x] Task 4 : Valider workflow secrets age/SOPS (AC: #8)
  - [x] 4.1 Vérifier `.sops.yaml` : placeholder clé publique age présent
  - [x] 4.2 Créer `scripts/test-sops-workflow.sh` : test chiffrement/déchiffrement roundtrip
  - [x] 4.3 Vérifier `.gitignore` : `.env`, `*.age`, clés privées exclus
  - [x] 4.4 Vérifier `.env.example` : aucune valeur réelle, tous placeholders

- [x] Task 5 : Documentation checklist manuelle Tailscale (AC: #2, #3, #4)
  - [x] 5.1 Vérifier que `docs/tailscale-setup.md` couvre : 2FA, device auth, key expiry 90j
  - [x] 5.2 Corriger key expiry dans le guide si nécessaire (AC dit 90j, guide dit 180j auto)
  - [x] 5.3 Créer checklist de validation opérationnelle dans la story (post-déploiement)

- [x] Task 6 : Écrire les tests de validation sécurité (AC: #9)
  - [x] 6.1 Créer `tests/unit/infra/test_security.py` avec tests automatisables
  - [x] 6.2 Test : tous les ports docker-compose sont `127.0.0.1` (existant dans test_docker_compose.py — vérifier couverture)
  - [x] 6.3 Test : `config/redis.acl` contient 6 users avec `user default off`
  - [x] 6.4 Test : `config/redis.acl` — aucun user n'a `+@all` sauf admin
  - [x] 6.5 Test : `.env.example` ne contient aucun secret réel (pas de token/key valide)
  - [x] 6.6 Test : `.sops.yaml` existe et a une `creation_rules` pour `.env.enc`
  - [x] 6.7 Test : `.gitignore` exclut `.env`, `*.key`, `credentials.json` (fichiers sensibles). Note: `*.age` = fichiers chiffres (safe a commiter)
  - [x] 6.8 Test : `config/Caddyfile` — domaines en `.friday.local` (pas de domaine public)
  - [x] 6.9 Test : scripts Tailscale existent et sont exécutables
  - [x] 6.10 Créer `tests/e2e/test_security_checklist.sh` : validation opérationnelle post-déploiement (SSH, ports, Tailscale)

- [x] Task 7 : Validation finale (AC: tous)
  - [x] 7.1 Exécuter tous les tests (pytest + scripts E2E)
  - [x] 7.2 Vérifier que les tests existants (TestNetworkSecurity, TestRedisACL, TestCaddyfile) passent toujours
  - [x] 7.3 Vérifier zéro régression sur les 143 tests existants (180/180 passent avec les 37 nouveaux)

## Dev Notes

### Nature de cette Story : Ops/Infra (pas Application Code)

Cette story est **principalement opérationnelle** : configuration Tailscale (dashboard manuel), scripts d'installation, durcissement SSH, firewall UFW. Le code applicatif est minimal (scripts bash + tests Python).

**Contrainte critique** : Les étapes 2FA, device authorization et key expiry 90j sont des **configurations manuelles** dans le dashboard Tailscale (https://login.tailscale.com/admin/). Elles ne peuvent PAS être automatisées via script. La story doit documenter et tester leur validation.

### Fichiers existants à NE PAS recréer

| Fichier | Status | Action |
|---------|--------|--------|
| `config/redis.acl` | Complet (31 lignes, 6 users + admin) | Auditer permissions, corriger si nécessaire |
| `config/Caddyfile` | Complet (24 lignes, 3 proxies + health) | Aucune modification |
| `.sops.yaml` | Template (placeholder clé publique) | Valider configuration |
| `.env.example` | Complet (169 lignes, tous placeholders) | Vérifier aucun secret réel |
| `docs/tailscale-setup.md` | Complet (315 lignes) | Corriger key expiry 90j (dit 180j) |
| `docs/redis-acl-setup.md` | Complet (301 lignes) | Référence documentation |
| `docs/secrets-management.md` | Complet (361 lignes) | Référence documentation |

### Tests existants à NE PAS dupliquer

Tests déjà dans `tests/unit/infra/test_docker_compose.py` :
- `TestNetworkSecurity.test_all_ports_localhost_only` — Vérifie ports `127.0.0.1`
- `TestNetworkSecurity.test_friday_network_exists` — Bridge network
- `TestRedisACL.test_redis_acl_file_mounted` — Volume monté
- `TestRedisACL.test_redis_command_loads_acl` — `--aclfile` dans commande Redis
- `TestRedisACL.test_gateway_uses_acl_credentials` — Gateway utilise credentials ACL
- `TestRedisACL.test_redis_acl_file_exists` — Fichier config existe
- `TestRedisACL.test_redis_acl_has_required_users` — 6 users définis
- `TestCaddyfile.*` — 5 tests (existence, montage, proxies n8n/gateway, health)

**Ne PAS réécrire ces tests**. Les nouveaux tests doivent couvrir des aspects **non testés** : permissions détaillées par user, absence de `+@all`, secrets workflow, scripts Tailscale.

### Architecture Guardrails

| Contrainte | Valeur | Source |
|------------|--------|--------|
| **Zéro exposition Internet** | Tous ports `127.0.0.1`, SSH Tailscale only | NFR8, addendum 9.3 |
| **2FA obligatoire** | TOTP ou hardware key sur compte Tailscale | ADD9 |
| **Device authorization** | Config MANUELLE dashboard web Tailscale | addendum 9.3 |
| **Key expiry** | 90 jours (AC) | Story 1.4 AC |
| **VPS hostname** | `friday-vps` | Story 1.4 AC |
| **Redis ACL** | Moindre privilège par service (6 users) | NFR11, addendum 9.2, `docs/redis-acl-setup.md` |
| **Secrets** | age/SOPS, JAMAIS `.env` en clair dans git | NFR9, `docs/secrets-management.md` |
| **Firewall** | UFW : SSH Tailscale only, deny 22/tcp public | `docs/tailscale-setup.md` §6 |
| **Docker network** | Bridge isolé `172.20.0.0/16` | docker-compose.yml |

### Redis ACL : Permissions attendues par service

| User | Clés | Commandes autorisées | Interdit |
|------|------|---------------------|----------|
| `friday_gateway` | `~*` | GET, SET, SETEX, DEL, EXPIRE, TTL, PUBLISH, SUBSCRIBE, XADD, XREADGROUP, XACK, XLEN | DROP, FLUSHDB, CONFIG |
| `friday_agents` | `~stream:*`, `~presidio:mapping:*` | XADD, XREADGROUP, XACK, XPENDING, GET, SETEX, DEL, PUBLISH, SUBSCRIBE | Écriture cache:* |
| `friday_alerting` | `~stream:*` | XREADGROUP, XACK, XADD, XPENDING, SUBSCRIBE | Écriture cache:*, mapping Presidio |
| `friday_metrics` | `~metrics:*` | GET, SET, INCRBY, EXPIRE | Streams, Pub/Sub publish |
| `friday_n8n` | `~cache:*`, `~bull:*`, `~n8n:*` | GET, SET, SETEX, DEL, EXPIRE, LPUSH, RPUSH, LRANGE, PUBLISH, SUBSCRIBE, SELECT | Streams |
| `friday_emailengine` | `~*` | @read, @write, @pubsub, @connection, SELECT | Limité DB Redis 2 |
| `admin` | `~*` | `+@all` (dev/debug only) | N/A (full access) |
| `default` | N/A | **OFF** (aucune connexion anonyme) | TOUT |

### Divergence key expiry (à corriger)

- **AC Story 1.4** : Key expiry = 90 jours
- **docs/tailscale-setup.md** : "Tailscale renouvelle les clés automatiquement tous les 180 jours"
- **Action** : Configurer key expiry à 90j dans le dashboard Tailscale (Settings → Keys → Key expiry). Le guide doit être mis à jour pour refléter 90j au lieu de 180j.
- **Note** : Key expiry se configure par machine dans Tailscale Admin → Machines → friday-vps → Key expiry → 90 days

### Scripts à créer

```
scripts/
├── setup-tailscale.sh       # Installation Tailscale + hostname friday-vps
├── harden-ssh.sh             # SSH ListenAddress Tailscale + UFW deny 22/tcp
└── test-sops-workflow.sh     # Test roundtrip chiffrement/déchiffrement age/SOPS
```

### Tests à créer

```
tests/
├── unit/infra/
│   └── test_security.py      # Tests sécurité : ACL détail, .env, .sops, .gitignore, Caddyfile
└── e2e/
    └── test_security_checklist.sh  # Validation opérationnelle post-déploiement
```

### Checklist manuelle post-déploiement (Tasks Tailscale Dashboard)

Ces étapes **ne peuvent PAS être automatisées** et doivent être faites manuellement :

- [ ] Créer compte Tailscale (https://login.tailscale.com/start)
- [ ] Activer 2FA TOTP (Settings → Auth → Two-factor authentication)
- [ ] Activer Device Authorization (Settings → Keys → Require device authorization)
- [ ] Configurer Key Expiry = 90 jours (Settings → Keys → Key expiry)
- [ ] Sauvegarder codes de récupération 2FA (gestionnaire de mots de passe + papier)
- [ ] Installer Tailscale sur VPS via `scripts/setup-tailscale.sh`
- [ ] Approuver device VPS dans dashboard (Machines → friday-vps → Approve)
- [ ] Installer Tailscale sur PC Windows
- [ ] Approuver device PC dans dashboard
- [ ] Exécuter `scripts/harden-ssh.sh` sur VPS (APRÈS validation SSH Tailscale)
- [ ] Vérifier SSH via Tailscale IP fonctionne
- [ ] Vérifier SSH via IP publique BLOQUÉ (timeout/refused)

### Previous Story Intelligence (Story 1.3)

**Learnings réutilisables** :
- Framework de test robuste en place (pytest + structlog) — 143 tests passent
- Convention commit : `type(scope): message` (conventional commits)
- Pre-commit hooks actifs (black, isort, flake8, mypy)
- Tests dans `tests/unit/` et `tests/integration/`
- Pas d'emojis dans les commits ni les logs

**Pièges à éviter** :
- Ne PAS dupliquer les tests existants dans `test_docker_compose.py`
- Ne PAS mettre de credentials en default dans les scripts
- Utiliser `structlog` pour tout logging (pas de print())
- Vérifier que les scripts bash sont portables (#!/usr/bin/env bash)

**Patterns à réutiliser** :
- Tests avec `pathlib.Path` pour vérifier existence fichiers config
- Lecture/parsing YAML pour vérifier docker-compose
- `read_text()` pour vérifier contenu fichiers config

### Git Intelligence (10 derniers commits)

```
a4e4128 feat(gateway): implement fastapi gateway with healthcheck endpoints
485df7b chore(architecture): claude sonnet 4.5 and pgvector setup, fix story 1.2
926d85b chore(infrastructure): add linting, testing config, and development tooling
024f88e docs(telegram-topics): add setup/user guides and extraction script
024d819 docs(telegram-topics): add notification strategy with 5 topics architecture
981cc7a feat(story1.5): implement trust layer middleware and observability services
3452167 fix: refine documentation and correct migrate_emails atomicity
ef165e1 fix: code review adversarial v2 - 17 issues corrigées + 4 fichiers créés
242daa2 docs(infra): refine architecture docs and add service scaffolding
c41811d docs(infra): finalize trust layer setup with migrations and scripts
```

**Convention commit pour cette story** : `feat(security): implement tailscale vpn and network hardening`

### Project Structure Notes

**Fichiers à créer** :
```
scripts/setup-tailscale.sh            # Script installation Tailscale VPS
scripts/harden-ssh.sh                 # Script durcissement SSH + UFW
scripts/test-sops-workflow.sh         # Test workflow age/SOPS
tests/unit/infra/test_security.py     # Tests sécurité automatisables
tests/e2e/test_security_checklist.sh  # Validation opérationnelle E2E
```

**Fichiers à modifier** :
```
docs/tailscale-setup.md               # Corriger key expiry 90j (pas 180j)
config/redis.acl                      # Corrections si audit révèle des écarts
```

**Fichiers à NE PAS modifier** :
```
config/Caddyfile                      # Déjà correct
.sops.yaml                            # Déjà correct (template)
.env.example                          # Déjà correct
docker-compose.yml                    # Ports déjà 127.0.0.1
tests/unit/infra/test_docker_compose.py  # Tests existants suffisants
```

### Dépendances techniques

**Outils système (VPS Ubuntu 22.04)** :
- `tailscale` : VPN mesh (installé via script)
- `ufw` : Firewall (pré-installé Ubuntu)
- `age` : Chiffrement secrets
- `sops` : Gestion fichiers chiffrés

**Python packages (tests)** :
- `pytest` : Framework tests (déjà installé)
- `pathlib` : Manipulation fichiers (stdlib)
- `re` : Regex pour parsing ACL (stdlib)

### Testing Strategy

**Tests automatisables** (pytest, CI/CD) :
- Vérification fichiers config (redis.acl, .sops.yaml, .env.example, .gitignore)
- Parsing Redis ACL : users, permissions, `default off`
- Vérification Caddyfile : domaines `.friday.local`
- Vérification absence secrets dans fichiers commitables

**Tests opérationnels** (E2E, post-déploiement VPS) :
- SSH via Tailscale IP → succès
- SSH via IP publique → timeout/refused
- Redis AUTH avec credentials ACL → succès
- Redis commandes non autorisées → NOPERM
- `tailscale status` → device `friday-vps` actif

**Coverage** : Les tests unitaires couvrent la configuration statique. Les tests E2E nécessitent un VPS opérationnel.

### References

- [Architecture addendum §9.1-9.4](_docs/architecture-addendum-20260205.md#9-securite---complements) — Anonymisation lifecycle, Redis ACL, Tailscale auth, backups chiffrement
- [Epics MVP](_bmad-output/planning-artifacts/epics-mvp.md) — Story 1.4 ACs, NFR8/NFR9/NFR11
- [docs/tailscale-setup.md](docs/tailscale-setup.md) — Guide complet installation Tailscale + 2FA
- [docs/redis-acl-setup.md](docs/redis-acl-setup.md) — Documentation Redis ACL moindre privilège
- [docs/secrets-management.md](docs/secrets-management.md) — Guide age/SOPS chiffrement
- [config/redis.acl](config/redis.acl) — Configuration ACL existante
- [config/Caddyfile](config/Caddyfile) — Configuration reverse proxy interne
- [.sops.yaml](.sops.yaml) — Configuration SOPS
- [.env.example](.env.example) — Template variables environnement
- [tests/unit/infra/test_docker_compose.py](tests/unit/infra/test_docker_compose.py) — Tests existants sécurité réseau
- [Story 1.3](_bmad-output/implementation-artifacts/1-3-fastapi-gateway-healthcheck.md) — Previous story learnings
- [CLAUDE.md](CLAUDE.md) — Sections sécurité, Redis ACL, Tailscale

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 via BMAD create-story workflow

### Debug Log References

### Completion Notes List

- Story créée par BMAD create-story workflow (2026-02-09)
- Analyse exhaustive : Architecture addendum §9 + Epics MVP + Story 1.3 + Git + exploration codebase
- Nature opérationnelle : scripts bash + tests Python (pas d'application code)
- Fichiers existants audités : redis.acl (31L), Caddyfile (24L), tailscale-setup.md (315L), redis-acl-setup.md (301L), secrets-management.md (361L)
- Tests existants identifiés : TestNetworkSecurity, TestRedisACL, TestCaddyfile (pas de duplication)
- Divergence key expiry identifiée : AC=90j vs doc=180j (à corriger dans guide)
- Checklist manuelle Tailscale dashboard documentée (2FA, device auth, key expiry)
- **Implementation (2026-02-09)** : Claude Opus 4.6 via BMAD dev-story workflow
- Task 1 : `scripts/setup-tailscale.sh` — installation Tailscale, hostname friday-vps, systemctl enable, post-install verification
- Task 2 : `scripts/harden-ssh.sh` — SSH ListenAddress Tailscale, UFW deny 22/tcp + allow Tailscale CGNAT, tailscale0 interface, sshd_config backup
- Task 3 : Redis ACL audit — emailengine +@write corrige (ajout -flushall -flushdb -flushdbnosync)
- Task 4 : `scripts/test-sops-workflow.sh` — roundtrip encrypt/decrypt avec age keypair temporaire, verification .sops.yaml et .gitignore
- Task 5 : `docs/tailscale-setup.md` — key expiry corrigé 180j -> 90j, checklist finale mise à jour
- Task 6 : 38 tests dans `tests/unit/infra/test_security.py` (37 originaux + 1 destructive cmds) + script E2E
- Task 7 : 181/181 tests passent (143 existants + 38 nouveaux), zero regression

### File List

**New files:**
- `scripts/setup-tailscale.sh` — Script installation Tailscale VPS (AC#5, #10)
- `scripts/harden-ssh.sh` — Script durcissement SSH + UFW (AC#1, #6)
- `scripts/test-sops-workflow.sh` — Test workflow secrets age/SOPS (AC#8)
- `tests/unit/infra/test_security.py` — 38 tests securite (AC#9)
- `tests/e2e/test_security_checklist.sh` — Validation operationnelle post-deploiement (AC#9)

**Modified files:**
- `docs/tailscale-setup.md` — Key expiry corrige 180j -> 90j (AC#4), checklist mise a jour

**Modified files (review fixes):**
- `config/redis.acl` — emailengine: ajout -flushall -flushdb -flushdbnosync (AC#7, H1 review)
- `config/Caddyfile` — Domaines .friday.local (AC#6)
- `.sops.yaml` — Template age valide (AC#8)
- `.env.example` — Tous placeholders (AC#8)
- `.gitignore` — Exclut .env, *.key, credentials (AC#8)

## Senior Developer Review (AI)

**Reviewer:** Claude Opus 4.6 (adversarial code review)
**Date:** 2026-02-09
**Outcome:** Approve (all issues fixed)

**Issues found:** 12 (1 HIGH, 6 MEDIUM, 5 LOW) — all fixed
- H1: emailengine Redis ACL `+@write` incluait FLUSHALL/FLUSHDB → ajout `-flushall -flushdb -flushdbnosync`
- M1: setup-tailscale.sh codename Ubuntu hardcode → auto-detection via VERSION_CODENAME
- M2: test_security.py regex fragile pour ports → remplacement par parsing YAML
- M3: test_security.py assertion agents ACL no-op → regex precise pour bare `~*`
- M4: test-sops-workflow.sh cascade echecs → gardes sur variables prerequis
- M5: test_security_checklist.sh password hardcode → lecture depuis env var REDIS_ADMIN_PASSWORD
- M6: Story task 6.7 description `*.age` incorrecte → corrigee (*.age = fichiers chiffres, safe)
- L1: setup-tailscale.sh note `--auth-key` pour CI/CD non-interactif
- L2: harden-ssh.sh regle UFW redondante (100.64.0.0/10) supprimee (tailscale0 couvre tout)
- L3: harden-ssh.sh message suggerait root login → corrige en `user@`
- L4: test_security.py liste TLDs incomplete → approche whitelist (.local/.internal)
- L5: test_security.py code mort supprime (refactoring M2)

**Tests:** 181/181 passent (38 securite + 143 existants), zero regression
**New test:** `test_no_service_user_has_destructive_commands` — verifie qu'aucun service user n'a flushall/flushdb

## Change Log

- 2026-02-09 : Story 1.4 implementee — scripts Tailscale/SSH/SOPS, audit Redis ACL, 37 tests securite, correction doc key expiry
- 2026-02-09 : Code review adversarial — 12 issues (1H, 6M, 5L) corrigees, 181/181 tests, zero regression
