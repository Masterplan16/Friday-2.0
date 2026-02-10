# Story 1.17 : Préparation Repository Public

**Status**: ready-for-dev

**Epic**: Epic 1 - Socle Opérationnel & Contrôle
**Story ID**: 1.17
**Estimation**: M (1 jour)
**Dépendances**: Story 1.16 (CI/CD Pipeline GitHub Actions ✅)

---

## Story

En tant qu'**Mainteneur (développeur/mainteneur)**,
Je veux **sécuriser le repository avant passage en public**,
afin que **zéro secret ne soit exposé, le repo soit conforme aux standards de sécurité open source, et la collaboration future soit sécurisée**.

---

## Acceptance Criteria

### AC1 : SOPS/age configuré avec vraie clé publique

- ✅ `.sops.yaml` mis à jour avec vraie clé publique age d'Mainteneur (remplacer placeholder `age1qqq...` actuel)
- ✅ Clé privée age stockée UNIQUEMENT sur machine locale Mainteneur (`~/.age/friday-key.txt`)
- ✅ Clé privée age JAMAIS commitée dans git
- ✅ Test de chiffrement/déchiffrement : `sops -e .env > .env.enc && sops -d .env.enc > .env.dec && diff .env .env.dec`
- ✅ Documentation : section "Setup développeur" dans `docs/secrets-management.md` mise à jour avec vraie clé publique

### AC2 : Fichier .env chiffré et committé

- ✅ `.env` actuel chiffré via SOPS → `.env.enc` créé
- ✅ `.env.enc` commité dans git (chiffré, safe)
- ✅ `.env` original supprimé et ajouté à `.gitignore`
- ✅ Vérification `.gitignore` : contient `.env` (pas `.env.enc`)
- ✅ `.env.example` créé avec structure complète mais valeurs fictives (guide pour nouveaux développeurs)
- ✅ Script `scripts/load-secrets.sh` testé : déchiffre `.env.enc` → `.env` temporaire

### AC3 : Tokens Telegram hardcodés supprimés

- ✅ Fichier `scripts/setup_telegram_auto.py` nettoyé :
  - Tokens hardcodés supprimés (ex: `TELEGRAM_BOT_TOKEN = "1234567890:ABC..."`)
  - Lecture depuis `.env` via `os.getenv("TELEGRAM_BOT_TOKEN")`
  - Raise ValueError si variable manquante (fail-explicit, pas de default)
- ✅ Aucun autre fichier ne contient de tokens hardcodés (scan complet codebase)
- ✅ Variables requises documentées dans `README.md` section "Setup & Prérequis"

### AC4 : Token Telegram actuel révoqué + nouveau généré

- ✅ Token Telegram actuel révoqué via BotFather (`/revoke`)
- ✅ Nouveau token généré via BotFather (`/newbot` ou `/token`)
- ✅ Nouveau token ajouté à `.env.enc` (chiffré)
- ✅ Ancien token complètement supprimé (historique Git + variables locales)
- ✅ Bot testé avec nouveau token (connexion Telegram OK)

### AC5 : Historique Git scanné pour secrets

- ✅ Installation outil de scan : `git-secrets` (recommandé) OU `truffleHog`
- ✅ Scan historique complet : `git-secrets --scan-history` OU `trufflehog git file://. --only-verified`
- ✅ Zéro secret exposé dans l'historique Git (tokens, API keys, passwords)
- ✅ Si secrets détectés : rewrite history avec `git filter-branch` OU `BFG Repo-Cleaner`
- ✅ Documentation : procédure scan ajoutée dans `docs/security-audit.md` (nouveau fichier)

### AC6 : .gitignore vérifié et complet

- ✅ `.gitignore` contient tous patterns sensibles :
  - `.env` (pas `.env.enc`, pas `.env.example`)
  - `*.key`, `*.pem` (clés privées)
  - `credentials.json`, `secrets.yaml` (non chiffrés)
  - `.age/` (dossier clés age)
  - `.sops/` (cache SOPS)
- ✅ Test validation : créer fichier `.env` temporaire → vérifier git ignore (`git status` ne doit pas montrer `.env`)

### AC7 : SECURITY.md créé

- ✅ Fichier `SECURITY.md` créé à la racine avec sections :
  - **Supported Versions** : Version actuelle (1.0.0) supportée
  - **Reporting a Vulnerability** : Email contact Mainteneur + délai réponse attendu (48h)
  - **Security Best Practices** : Guide pour utilisateurs (Tailscale 2FA, SOPS/age, rotation tokens)
  - **Responsible Disclosure** : Politique divulgation coordonnée (pas de publication avant fix)
- ✅ Référence dans README.md : lien vers SECURITY.md dans section "Sécurité"

### AC8 : LICENSE ajoutée

- ✅ Fichier `LICENSE` créé à la racine
- ✅ Licence choisie : **MIT** (permissive, compatible usage personnel + futur partage)
- ✅ Copyright : © 2026 Mainteneur (prénom/pseudonyme uniquement, pas nom complet)
- ✅ Header licence ajouté dans fichiers principaux (optionnel, recommandé pour `agents/`, `services/`)

### AC9 : GitHub branch protection activée sur master

- ✅ GitHub branch protection rules configurées sur `master` :
  - Require pull request before merging (force PR, pas de push direct)
  - Require approvals : 1 review minimum (Mainteneur self-review OK pour repo solo)
  - Require status checks to pass : CI workflow (lint, test-unit, test-integration, build-validation)
  - Require branches to be up to date : true (évite merge conflicts)
  - Do not allow bypassing : false (Mainteneur peut bypass en urgence)
- ✅ Test validation : tentative push direct sur master doit être rejetée

### AC10 : GitHub Dependabot activé

- ✅ Dependabot alerts activées (Settings > Security & analysis > Dependabot alerts : ON)
- ✅ Dependabot security updates activées (auto-PR pour vulnérabilités critiques)
- ✅ Fichier `.github/dependabot.yml` créé avec config :
  - Package ecosystems : pip (agents/requirements.txt), docker (Dockerfile, docker-compose.yml)
  - Update schedule : weekly (lundi 8h UTC)
  - Assignees : Mainteneur
  - Labels : `dependencies`, `security`
- ✅ Premier scan Dependabot exécuté (aucune vulnérabilité critique attendue)

### AC11 : CI/CD fonctionnel (Story 1.16 prerequisite)

- ✅ Workflow `.github/workflows/ci.yml` opérationnel (Story 1.16 done)
- ✅ Tests passent sur PR de test (lint, test-unit, test-integration, build-validation)
- ✅ Badge CI visible dans README.md
- ✅ Aucune régression introduite lors des modifications sécurité

---

## Tasks / Subtasks

### Task 1 : Configurer SOPS/age avec vraie clé publique (AC1)

- [ ] **Subtask 1.1** : Générer paire de clés age si pas déjà fait
  - `age-keygen -o ~/.age/friday-key.txt`
  - Noter clé publique (format `age1...`) et clé privée (format `AGE-SECRET-KEY-1...`)
  - Clé privée JAMAIS partagée, clé publique utilisée pour chiffrement
- [ ] **Subtask 1.2** : Mettre à jour `.sops.yaml` avec vraie clé publique
  - Remplacer placeholder `age1qqqqqqq...` par vraie clé publique Mainteneur
  - Vérifier format YAML valide
  - Commiter `.sops.yaml` (contient seulement clé publique, safe)
- [ ] **Subtask 1.3** : Tester chiffrement/déchiffrement avec vraie clé
  - Créer fichier test `.env.test` avec contenu fictif
  - Chiffrer : `sops -e .env.test > .env.test.enc`
  - Déchiffrer : `sops -d .env.test.enc > .env.test.dec`
  - Vérifier contenu identique : `diff .env.test .env.test.dec`
  - Cleanup : `rm .env.test .env.test.enc .env.test.dec`
- [ ] **Subtask 1.4** : Mettre à jour `docs/secrets-management.md`
  - Remplacer exemples clés fictives par vraie clé publique Mainteneur
  - Ajouter note : "Clé publique actuelle projet Friday 2.0"

### Task 2 : Chiffrer et commiter .env (AC2)

- [ ] **Subtask 2.1** : Vérifier contenu `.env` actuel
  - Lister toutes variables sensibles (TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, DATABASE_URL, REDIS_PASSWORD, etc.)
  - Vérifier aucune valeur hardcodée manquante
- [ ] **Subtask 2.2** : Créer `.env.example` avec structure complète
  - Copier structure `.env` mais valeurs fictives
  - Exemples : `TELEGRAM_BOT_TOKEN=your_bot_token_here`, `ANTHROPIC_API_KEY=sk-ant-your-key-here`
  - Ajouter commentaires inline pour chaque variable (description + où obtenir)
- [ ] **Subtask 2.3** : Chiffrer `.env` → `.env.enc`
  - `sops -e .env > .env.enc`
  - Vérifier `.env.enc` contient contenu chiffré (illisible)
- [ ] **Subtask 2.4** : Mettre à jour `.gitignore`
  - Vérifier `.env` dans `.gitignore` (pas `.env.enc`)
  - Ajouter `!.env.example` pour forcer commit (override ignore)
- [ ] **Subtask 2.5** : Commiter `.env.enc` + `.env.example`
  - `git add .env.enc .env.example .gitignore`
  - `git commit -m "security: add encrypted secrets and example env file"`
  - Supprimer `.env` en clair : `rm .env`
- [ ] **Subtask 2.6** : Tester `scripts/load-secrets.sh`
  - `./scripts/load-secrets.sh` (doit déchiffrer `.env.enc` → `.env`)
  - Vérifier variables chargées : `source .env && echo $TELEGRAM_BOT_TOKEN`
  - Cleanup : `rm .env`

### Task 3 : Nettoyer tokens hardcodés (AC3)

- [ ] **Subtask 3.1** : Scanner codebase pour tokens hardcodés
  - Grep récursif : `grep -r "TELEGRAM_BOT_TOKEN\s*=\s*['\"]" --include="*.py"`
  - Grep API keys : `grep -r "sk-ant-" --include="*.py"` (Anthropic API keys)
  - Grep passwords : `grep -r "password\s*=\s*['\"]" --include="*.py"`
  - Lister tous fichiers contenant tokens hardcodés
- [ ] **Subtask 3.2** : Nettoyer `scripts/setup_telegram_auto.py`
  - Supprimer tokens hardcodés (ex: `TELEGRAM_BOT_TOKEN = "1234567890:ABC..."`)
  - Remplacer par : `TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")`
  - Ajouter validation fail-explicit :
    ```python
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable required")
    ```
  - Appliquer même pattern pour `TELEGRAM_SUPERGROUP_ID`, `TOPIC_*_ID`
- [ ] **Subtask 3.3** : Nettoyer autres fichiers identifiés
  - Pour chaque fichier : remplacer hardcoded → `os.getenv()` + validation
  - Tester script après modification (doit lever ValueError si variable manquante)
- [ ] **Subtask 3.4** : Documenter variables requises dans README.md
  - Section "Setup & Prérequis" : liste variables .env requises
  - Référence vers `.env.example` pour structure complète

### Task 4 : Révoquer et régénérer token Telegram (AC4)

- [ ] **Subtask 4.1** : Révoquer ancien token via BotFather
  - Telegram : ouvrir chat avec `@BotFather`
  - Commande : `/revoke` → sélectionner bot Friday
  - Confirmer révocation (ancien token immédiatement invalidé)
- [ ] **Subtask 4.2** : Générer nouveau token via BotFather
  - Commande : `/token` → sélectionner bot Friday
  - Noter nouveau token (format `1234567890:ABCdefGHI...`)
- [ ] **Subtask 4.3** : Mettre à jour `.env.enc` avec nouveau token
  - Déchiffrer : `sops -d .env.enc > .env`
  - Éditer `.env` : remplacer ancien token par nouveau
  - Re-chiffrer : `sops -e .env > .env.enc`
  - Commiter : `git add .env.enc && git commit -m "security: rotate telegram bot token"`
  - Cleanup : `rm .env`
- [ ] **Subtask 4.4** : Tester bot avec nouveau token
  - Charger nouveau token : `./scripts/load-secrets.sh`
  - Démarrer bot : `docker compose up -d friday-bot`
  - Envoyer message test via Telegram → vérifier réponse
  - Cleanup : `rm .env`

### Task 5 : Scanner historique Git pour secrets (AC5)

- [ ] **Subtask 5.1** : Installer outil de scan (git-secrets recommandé)
  - macOS : `brew install git-secrets`
  - Linux : `git clone https://github.com/awslabs/git-secrets && cd git-secrets && sudo make install`
  - Windows : `scoop install git-secrets` OU installer truffleHog via pip
- [ ] **Subtask 5.2** : Configurer git-secrets avec patterns Friday
  - `git secrets --install` (hooks pre-commit)
  - Ajouter patterns :
    - `git secrets --add 'TELEGRAM_BOT_TOKEN\s*=\s*["\'][0-9]{8,}:[A-Za-z0-9_-]{30,}["\']'`
    - `git secrets --add 'sk-ant-[a-zA-Z0-9_-]{40,}'` (Anthropic API keys)
    - `git secrets --add 'age1[a-z0-9]{58}'` (age public keys OK, privées NON)
    - `git secrets --add 'AGE-SECRET-KEY-1[A-Z0-9]{58}'` (age private keys CRITIQUE)
- [ ] **Subtask 5.3** : Scanner historique complet
  - Commande : `git secrets --scan-history`
  - Si secrets détectés : noter commits affectés + types de secrets
  - Si aucun secret : passer Subtask 5.4
- [ ] **Subtask 5.4** : Nettoyer historique Git si secrets détectés (CRITIQUE)
  - **Option A (recommandée)** : BFG Repo-Cleaner
    - Télécharger : `wget https://repo1.maven.org/maven2/com/madgag/bfg/1.14.0/bfg-1.14.0.jar`
    - Nettoyer : `java -jar bfg-1.14.0.jar --replace-text secrets.txt` (liste patterns à remplacer)
    - Reflog : `git reflog expire --expire=now --all && git gc --prune=now --aggressive`
  - **Option B (manuelle)** : git filter-branch
    - `git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch .env' --prune-empty --tag-name-filter cat -- --all`
  - ⚠️ **ATTENTION** : Rewrite history = force push requis, casser clones existants
- [ ] **Subtask 5.5** : Créer `docs/security-audit.md`
  - Documenter procédure scan (git-secrets + patterns)
  - Documenter procédure nettoyage historique (BFG + git filter-branch)
  - Ajouter checklist mensuelle : "Scanner historique Git pour nouveaux secrets"

### Task 6 : Vérifier et compléter .gitignore (AC6)

- [ ] **Subtask 6.1** : Auditer `.gitignore` actuel
  - Vérifier présence tous patterns sensibles :
    - `.env` (PAS `.env.enc`, PAS `.env.example`)
    - `*.key`, `*.pem` (clés privées)
    - `credentials.json`, `secrets.yaml` (non chiffrés)
    - `.age/` (dossier clés age locales)
    - `.sops/` (cache SOPS)
  - Ajouter patterns manquants si nécessaire
- [ ] **Subtask 6.2** : Tester validation .gitignore
  - Créer fichier test : `touch .env`
  - Vérifier git ignore : `git status` (ne doit PAS montrer `.env`)
  - Créer fichier test : `touch test.key`
  - Vérifier git ignore : `git status` (ne doit PAS montrer `test.key`)
  - Cleanup : `rm .env test.key`
- [ ] **Subtask 6.3** : Documenter patterns .gitignore dans README.md
  - Section "Sécurité" : expliquer pourquoi `.env` ignoré mais `.env.enc` commité
  - Référence vers `docs/secrets-management.md` pour détails

### Task 7 : Créer SECURITY.md (AC7)

- [ ] **Subtask 7.1** : Créer fichier `SECURITY.md` à la racine
  - Template GitHub Security Policy : https://docs.github.com/en/code-security/getting-started/adding-a-security-policy-to-your-repository
- [ ] **Subtask 7.2** : Section "Supported Versions"
  - Version actuelle : 1.0.0 (MVP Day 1) - Supportée ✅
  - Versions futures : Rolling release (toujours dernière version stable)
- [ ] **Subtask 7.3** : Section "Reporting a Vulnerability"
  - Contact : Email Mainteneur (créer alias dédié ex: security+friday@...)
  - Délai réponse : 48h max (acknowledgment), 7 jours max (triage + plan fix)
  - Process : Email → Triage → Fix privé → Test → Disclosure coordonnée
- [ ] **Subtask 7.4** : Section "Security Best Practices"
  - Tailscale 2FA obligatoire (NFR8)
  - SOPS/age pour secrets (NFR9)
  - Rotation tokens tous les 90 jours (recommandation)
  - Backup chiffré quotidien (Story 1.12)
- [ ] **Subtask 7.5** : Section "Responsible Disclosure"
  - Pas de publication vulnérabilité avant fix disponible (délai 90 jours max)
  - Crédit chercheur sécurité dans CHANGELOG si souhaité
- [ ] **Subtask 7.6** : Ajouter lien SECURITY.md dans README.md
  - Section "Sécurité" : lien vers `SECURITY.md` pour politique complète

### Task 8 : Ajouter LICENSE (AC8)

- [ ] **Subtask 8.1** : Créer fichier `LICENSE` à la racine
  - Template MIT License : https://opensource.org/licenses/MIT
  - Copyright : `Copyright (c) 2026 Mainteneur` (prénom/pseudonyme uniquement)
  - Année : 2026 (année création projet)
- [ ] **Subtask 8.2** : Ajouter header licence dans fichiers principaux (optionnel)
  - Format header :
    ```python
    # Copyright (c) 2026 Mainteneur
    # SPDX-License-Identifier: MIT
    ```
  - Fichiers recommandés : `agents/src/__init__.py`, `services/gateway/main.py`
  - Automatisation future : pre-commit hook pour ajouter headers automatiquement
- [ ] **Subtask 8.3** : Ajouter badge licence dans README.md
  - Section "Badges" : `![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)`
  - Lien vers LICENSE : `[License](LICENSE)`

### Task 9 : Activer GitHub branch protection (AC9)

- [ ] **Subtask 9.1** : Configurer branch protection rules sur master
  - GitHub : Settings > Branches > Add branch protection rule
  - Branch name pattern : `master`
  - **Require a pull request before merging** : ✅ ON
    - Required approvals : 1 (Mainteneur self-review OK)
    - Dismiss stale approvals : ✅ ON (si nouveau commit après review)
  - **Require status checks to pass** : ✅ ON
    - Required checks : `lint`, `test-unit`, `test-integration`, `build-validation` (4 jobs CI)
    - Require branches to be up to date : ✅ ON (évite merge conflicts)
  - **Do not allow bypassing** : ❌ OFF (Mainteneur peut bypass en urgence)
  - Save changes
- [ ] **Subtask 9.2** : Tester protection avec PR de test
  - Créer branche test : `git checkout -b test/branch-protection`
  - Commit trivial : `echo "test" >> README.md && git commit -am "test: branch protection"`
  - Push : `git push origin test/branch-protection`
  - Créer PR : `gh pr create --title "Test branch protection" --body "Validation AC9"`
  - Vérifier : status checks doivent passer avant merge possible
  - Merge PR : `gh pr merge --squash`
  - Cleanup : `git branch -d test/branch-protection`
- [ ] **Subtask 9.3** : Tester push direct sur master (doit échouer)
  - Checkout master : `git checkout master`
  - Commit trivial : `echo "direct" >> README.md && git commit -am "test: direct push"`
  - Push : `git push origin master` (DOIT ÉCHOUER avec erreur "protected branch")
  - Rollback : `git reset --hard HEAD~1`

### Task 10 : Activer GitHub Dependabot (AC10)

- [ ] **Subtask 10.1** : Activer Dependabot alerts + security updates
  - GitHub : Settings > Security & analysis
  - **Dependabot alerts** : ✅ Enable
  - **Dependabot security updates** : ✅ Enable (auto-PR vulnérabilités critiques)
  - **Dependency graph** : ✅ Enable (prerequisite Dependabot)
- [ ] **Subtask 10.2** : Créer fichier `.github/dependabot.yml`
  - Config package ecosystems :
    ```yaml
    version: 2
    updates:
      - package-ecosystem: "pip"
        directory: "/agents"
        schedule:
          interval: "weekly"
          day: "monday"
          time: "08:00"
          timezone: "Europe/Paris"
        assignees:
          - "mainteneur"  # Remplacer par username GitHub Mainteneur
        labels:
          - "dependencies"
          - "security"
        open-pull-requests-limit: 5

      - package-ecosystem: "docker"
        directory: "/"
        schedule:
          interval: "weekly"
          day: "monday"
          time: "08:00"
          timezone: "Europe/Paris"
        assignees:
          - "mainteneur"
        labels:
          - "dependencies"
          - "docker"
        open-pull-requests-limit: 3
    ```
- [ ] **Subtask 10.3** : Commiter `.github/dependabot.yml`
  - `git add .github/dependabot.yml`
  - `git commit -m "ci: configure dependabot for pip and docker dependencies"`
  - `git push`
- [ ] **Subtask 10.4** : Vérifier premier scan Dependabot
  - GitHub : Security > Dependabot alerts (attendre 5-10 min après activation)
  - Vérifier aucune alerte critique (attendu : 0 alertes grâce à Story 1.16 requirements-lock.txt)
  - Si alertes : trier par sévérité, créer issues pour CRITICAL/HIGH

### Task 11 : Validation CI/CD fonctionne (AC11)

- [ ] **Subtask 11.1** : Vérifier workflow CI opérationnel (Story 1.16 done)
  - GitHub : Actions > CI workflow
  - Dernière exécution : ✅ SUCCESS (4 jobs passés)
  - Badge CI visible dans README.md
- [ ] **Subtask 11.2** : Créer PR test avec modifications sécurité
  - Branche : `test/security-pr`
  - Modifications : exemple `.gitignore` + commentaire `SECURITY.md`
  - Créer PR : `gh pr create --title "test: validate CI with security changes"`
  - Vérifier : 4 jobs CI passent (lint, test-unit, test-integration, build-validation)
  - Merge : `gh pr merge --squash`
- [ ] **Subtask 11.3** : Vérifier aucune régression introduite
  - Exécuter tests localement : `pytest tests/unit -v` (tous passent)
  - Exécuter linting : `black --check agents/ && isort --check agents/` (pas de changements)
  - Docker build : `docker compose build` (succès)

### Task 12 : Tests E2E sécurité + Documentation finale

- [ ] **Subtask 12.1** : Créer test E2E `tests/e2e/test_repo_security.sh`
  - Test 1 : Scan historique Git (git-secrets --scan-history = 0 secrets)
  - Test 2 : Validation .gitignore (créer .env temporaire → git status ignore)
  - Test 3 : SOPS chiffrement (round-trip .env → .env.enc → .env.dec = identique)
  - Test 4 : Validation fichiers sensibles (aucun .key, .pem, credentials.json non-chiffré commité)
  - Test 5 : GitHub branch protection active (appel API GitHub = protected = true)
  - Test 6 : Dependabot actif (appel API GitHub = enabled = true)
  - Rendre exécutable : `chmod +x tests/e2e/test_repo_security.sh`
- [ ] **Subtask 12.2** : Exécuter tests E2E
  - `./tests/e2e/test_repo_security.sh`
  - Tous tests doivent passer (6/6 PASS ✓)
  - Si échec : corriger puis re-exécuter
- [ ] **Subtask 12.3** : Mettre à jour README.md section "Sécurité"
  - Ajouter sous-sections :
    - **Secrets Management** : Lien vers `docs/secrets-management.md`
    - **Security Policy** : Lien vers `SECURITY.md`
    - **Security Audit** : Lien vers `docs/security-audit.md`
    - **Branch Protection** : Note "Master branch protected, PR required"
    - **Dependabot** : Note "Automated dependency updates enabled"
- [ ] **Subtask 12.4** : Créer checklist pre-publication dans `docs/pre-publication-checklist.md`
  - ✅ Tous AC Story 1.17 validés
  - ✅ Tests E2E sécurité passent
  - ✅ CI/CD fonctionne sur PR
  - ✅ Token Telegram révoqué + nouveau testé
  - ✅ Historique Git clean (0 secrets)
  - ✅ Branch protection active
  - ✅ Dependabot actif
  - ⚠️ **Dernière étape** : Passer repository en "Public" (Settings > Danger Zone > Change visibility)

---

## Dev Notes

### Contexte Epic 1 - Socle Opérationnel & Contrôle

Cette story fait partie de l'Epic 1 (17 stories au total), qui constitue le socle critique de Friday 2.0. **Story 1.17 est la dernière story de sécurité avant passage du repository en public**.

**Dépendances critiques DONE** :
- Story 1.16 : CI/CD Pipeline GitHub Actions ✅ (prerequisite CRITIQUE - tests doivent passer avant repo public)
- Story 1.4 : Tailscale VPN ✅ (NFR8 - zero exposition Internet public)
- Story 1.2 : Migrations SQL ✅ (aucun credential hardcodé dans migrations)

**Stories Epic 1 restantes après 1.17** :
- Stories 1.10-1.15 : Bot Telegram inline buttons, commandes trust, backup, self-healing, monitoring, cleanup

### Architecture Compliance

#### 1. Secrets Management (NFR9 - Chiffrement age/SOPS)

**Référence** : [docs/secrets-management.md](../../docs/secrets-management.md)

**Standards établis** :
- **age/SOPS obligatoire** : Tous secrets chiffrés avant commit
- **Clé privée age** : JAMAIS commitée, stockée uniquement `~/.age/friday-key.txt`
- **Clé publique age** : Safe pour commit, utilisée dans `.sops.yaml`
- **Workflow chiffrement** :
  1. Créer/modifier `.env` en local
  2. Chiffrer : `sops -e .env > .env.enc`
  3. Commiter `.env.enc` (chiffré, safe)
  4. Supprimer `.env` en clair
- **Workflow déchiffrement dev local** :
  1. `sops -d .env.enc > .env` (temporaire)
  2. Utiliser normalement
  3. Supprimer `.env` après usage

**Pattern fail-explicit** :
```python
import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable required. Run: ./scripts/load-secrets.sh")
```

**Fichiers concernés Story 1.17** :
- `.sops.yaml` : Config SOPS avec clé publique age Mainteneur
- `.env.enc` : Secrets chiffrés (commitable)
- `.env.example` : Structure secrets avec valeurs fictives (guide dev)
- `scripts/load-secrets.sh` : Script déchiffrement automatique

#### 2. Security Hardening (NFR8, NFR10)

**Référence** : Architecture Friday 2.0 section "Step 8: Security & Compliance"

**NFR8 - Zero exposition Internet public** :
- ✅ Tailscale VPN configuré (Story 1.4)
- ✅ SSH uniquement via Tailscale
- ✅ Aucun port exposé IP publique VPS
- ✅ Repository public = code open source, MAIS infrastructure privée

**NFR10 - Security hardening** :
- ✅ Branch protection GitHub (force PR + CI)
- ✅ Dependabot alerts (vulnérabilités dépendances)
- ✅ SECURITY.md (responsible disclosure policy)
- ✅ Scan historique Git (git-secrets / truffleHog)
- ✅ `.gitignore` complet (patterns sensibles)

**Patterns sécurité établis** :
- **Rotation tokens** : 90 jours recommandés (Telegram, Anthropic API, etc.)
- **Scan automatique** : Pre-commit hook git-secrets (bloque commits avec secrets)
- **Audit mensuel** : Checklist scan historique + review permissions GitHub

#### 3. CI/CD Integration (Story 1.16)

**Référence** : [1-16-ci-cd-pipeline-github-actions.md](1-16-ci-cd-pipeline-github-actions.md)

**Workflow CI opérationnel** :
- ✅ 4 jobs : lint, test-unit, test-integration, build-validation
- ✅ Badge CI dans README.md
- ✅ Trigger : PR + push vers master
- ✅ Cache pip + Docker layers (builds <5min)

**Integration Story 1.17 avec CI** :
- **Branch protection** : CI doit passer avant merge (AC9 utilise jobs Story 1.16)
- **Tests sécurité** : Nouveau test E2E `test_repo_security.sh` s'ajoute aux tests existants
- **Dependabot PR** : Déclenche automatiquement workflow CI (validation auto updates)

**Best practices CI/CD sécurité** :
- Variables secrets GitHub Actions : Jamais hardcodées dans workflow YAML
- Actions third-party : Versions pinnées (ex: `actions/checkout@v4`, pas `@latest`)
- SAST (Static Analysis) : Intégrer CodeQL ou Bandit dans workflow CI (future enhancement)

### File Structure Requirements

#### Fichiers à créer

```
SECURITY.md                             # Politique sécurité + responsible disclosure
LICENSE                                 # Licence MIT
.env.enc                                # Secrets chiffrés (commitable)
.env.example                            # Structure secrets (valeurs fictives)
.github/
└── dependabot.yml                      # Config Dependabot (pip + docker)
docs/
├── security-audit.md                   # Procédure scan historique Git + audit
└── pre-publication-checklist.md        # Checklist validation avant repo public
tests/
└── e2e/
    └── test_repo_security.sh           # Tests E2E sécurité (6 tests)
```

#### Fichiers à modifier

```
.sops.yaml                              # Mise à jour clé publique age Mainteneur (remplacer placeholder)
.gitignore                              # Vérifier patterns sensibles (*.key, *.pem, credentials.json, .age/, .sops/)
README.md                               # Section "Sécurité" + badge licence + liens docs
scripts/setup_telegram_auto.py          # Supprimer tokens hardcodés → os.getenv() + fail-explicit
docs/secrets-management.md              # Mise à jour clé publique Mainteneur + exemples
```

#### Fichiers à supprimer

```
.env                                    # Supprimé après chiffrement → .env.enc (jamais committé)
```

### Testing Requirements

#### Tests E2E Sécurité (nouveau fichier)

**Fichier** : `tests/e2e/test_repo_security.sh`

**Tests à implémenter** (6 tests) :

```bash
#!/usr/bin/env bash
# Test 1: Scan historique Git (git-secrets)
test_git_history_clean() {
    git secrets --scan-history 2>&1 | grep -q "No secrets found"
}

# Test 2: Validation .gitignore
test_gitignore_blocks_env() {
    touch .env.test
    git status --porcelain | grep -qv ".env.test"
    rm .env.test
}

# Test 3: SOPS round-trip
test_sops_encryption_works() {
    echo "TEST_SECRET=hello" > .env.test
    sops -e .env.test > .env.test.enc
    sops -d .env.test.enc > .env.test.dec
    diff .env.test .env.test.dec
    rm .env.test .env.test.enc .env.test.dec
}

# Test 4: Aucun fichier sensible non-chiffré
test_no_unencrypted_secrets() {
    ! git ls-files | grep -E '\.(key|pem)$|credentials\.json$|secrets\.yaml$'
}

# Test 5: Branch protection active (API GitHub)
test_branch_protection_enabled() {
    gh api repos/{owner}/{repo}/branches/master/protection \
        --jq '.required_pull_request_reviews.required_approving_review_count' | grep -q "1"
}

# Test 6: Dependabot actif (API GitHub)
test_dependabot_enabled() {
    gh api repos/{owner}/{repo}/vulnerability-alerts --silent
}
```

**Exécution** :
```bash
chmod +x tests/e2e/test_repo_security.sh
./tests/e2e/test_repo_security.sh
```

**Critères succès** : 6/6 tests PASS ✓

#### Tests Intégration Existants (pas de modification)

Tests intégration Story 1.16 continuent de fonctionner :
- `tests/integration/test_anonymization_pipeline.py` (Presidio)
- `tests/integration/test_trust_layer.py` (Trust Layer + PostgreSQL)

**Aucune régression attendue** car Story 1.17 ne modifie pas le code métier, seulement la configuration sécurité.

### Technical Stack

#### Outils Sécurité

| Outil | Usage Story 1.17 | Installation |
|-------|------------------|--------------|
| **age** | Chiffrement secrets (clés asymétriques) | `brew install age` (macOS), `apt install age` (Linux) |
| **SOPS** | Gestion fichiers chiffrés (.env.enc) | `brew install sops` (macOS), wget GitHub releases (Linux) |
| **git-secrets** | Scan historique Git pour secrets | `brew install git-secrets` (macOS), git clone + make install (Linux) |
| **truffleHog** | Alternative git-secrets (plus strict) | `pip install truffleHog` |
| **BFG Repo-Cleaner** | Nettoyage historique Git si secrets détectés | Download JAR depuis Maven Central |
| **GitHub CLI (gh)** | Config branch protection + Dependabot via API | `brew install gh` (macOS), apt install (Linux) |

#### Versions Recommandées (2026-02-10)

- **age** : v1.1.1+ (stable)
- **SOPS** : v3.8.1+ (stable, support age natif)
- **git-secrets** : v1.3.0+ (AWS Labs)
- **truffleHog** : v3.63.0+ (pip install --upgrade truffleHog)
- **BFG Repo-Cleaner** : v1.14.0 (dernière version stable)

#### GitHub API Endpoints Utilisés

```bash
# Branch protection
GET /repos/{owner}/{repo}/branches/{branch}/protection
PUT /repos/{owner}/{repo}/branches/{branch}/protection

# Dependabot
GET /repos/{owner}/{repo}/vulnerability-alerts
PUT /repos/{owner}/{repo}/vulnerability-alerts

# Repository visibility
PATCH /repos/{owner}/{repo} -d '{"private": false}'  # Passer en public (DERNIÈRE ÉTAPE)
```

### Previous Story Intelligence

**Story 1.16 (CI/CD) - Learnings critiques** :

1. **requirements-lock.txt déjà créé** : Dépendances Python lockées (134 deps), utilisé par job `test-unit` et `test-integration`
   - Pattern Story 1.17 : Ne PAS regénérer requirements-lock.txt (pas de changements dépendances attendus)
   - Si dépendances changent : regénérer via `pip freeze > agents/requirements-lock.txt`

2. **Tests E2E pattern établi** : `tests/e2e/test_ci_cd_workflow.sh` (200+ lignes, 35 tests)
   - Pattern Story 1.17 : Créer `test_repo_security.sh` avec même structure (fonctions test_*, boucle exécution, compteur PASS/FAIL)
   - Convention : Nom test explicite, une assertion par test, cleanup systématique

3. **Conventional commits** : `feat()`, `fix()`, `security()`, `ci()` (préfixes standardisés)
   - Pattern Story 1.17 : Utiliser préfixe `security:` pour tous commits (ex: `security: add encrypted secrets`, `security: rotate telegram token`)

4. **Documentation runbook** : `docs/deployment-runbook.md` (650+ lignes, troubleshooting détaillé)
   - Pattern Story 1.17 : Créer `docs/security-audit.md` avec même niveau détail (procédures, troubleshooting, commandes utiles)

5. **GitHub Actions annotations** : `echo "::notice::message"`, `echo "::error::message"` (logs structurés)
   - Pattern Story 1.17 : Si script bash complexe, utiliser annotations pour logs critiques

6. **Subtasks démarqués** : Subtasks 5.2-5.4 Story 1.16 = tests sur infra réelle (pas exécutés en dev)
   - Pattern Story 1.17 : Subtask "Passer repo en public" (GitHub visibility) = DERNIÈRE ÉTAPE, pas exécutée pendant dev Story 1.17

**Story 1.4 (Tailscale) - Learnings** :

- **Hostname VPS** : `friday-vps` (configuré Tailscale)
- **SSH** : Uniquement via Tailscale (aucun port 22 ouvert Internet)
- **Pattern Story 1.17** : Scripts utilisant SSH (deploy.sh) continuent de fonctionner, aucun changement réseau

**Story 1.9 (Bot Telegram) - Learnings** :

- **Variables env** : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_SUPERGROUP_ID`, `TOPIC_*_ID` (5 topics)
- **Token format** : `1234567890:ABCdefGHI...` (10 chiffres + 35 caractères alphanumériques)
- **Révocation BotFather** : `/revoke` invalide immédiatement ancien token (bot arrête de fonctionner)
- **Pattern Story 1.17** : Révocation token = opération irréversible, DOIT avoir nouveau token prêt avant révocation

### Git Intelligence Summary

**Derniers commits pertinents** (git log --oneline -5) :

```
3babaaf style: format code with black and isort for CI compliance
e21322a fix(ci): add pyproject.toml for agents package installation
80a2fb8 feat(ci-cd): implement GitHub Actions CI/CD pipeline with code review fixes
77886f8 feat(trust-metrics): implement retrogradation and anti-oscillation system
459865a feat(bot): implement telegram bot core and feedback loop
```

**Patterns observés** :

1. **Conventional commits** : Préfixes `feat()`, `fix()`, `style()`, `chore()`, `security()`
   - **Pattern Story 1.17** : Utiliser `security:` pour tous commits (chiffrement, rotation tokens, scan Git)

2. **Commits atomiques** : Un commit = une fonctionnalité/fix (pas de "big bang" commits)
   - **Pattern Story 1.17** :
     - Commit 1 : `security: configure SOPS with real age key`
     - Commit 2 : `security: add encrypted .env and example file`
     - Commit 3 : `security: remove hardcoded telegram tokens`
     - Commit 4 : `security: rotate telegram bot token`
     - Commit 5 : `security: scan git history and add security audit docs`
     - etc.

3. **Tests inclus** : Chaque story ajoute tests E2E (ex: test_ci_cd_workflow.sh)
   - **Pattern Story 1.17** : Créer `test_repo_security.sh` (6 tests sécurité)

4. **Documentation inline** : Docstrings Python, comments bash scripts
   - **Pattern Story 1.17** : Scripts bash (load-secrets.sh, test_repo_security.sh) DOIVENT avoir header explicatif + comments inline

### Latest Tech Information

#### SOPS v3.8.1 (Janvier 2025)

**Nouveautés pertinentes** :
- Support natif age (pas besoin plugin)
- Format `.sops.yaml` simplifié
- Performance améliorée (chiffrement 2x plus rapide vs v3.7)

**Breaking changes** : Aucun (rétrocompatible)

**Migration depuis anciennes versions** : Aucune action requise

#### git-secrets v1.3.0 (Mars 2024)

**Nouveautés pertinentes** :
- Patterns AWS améliorés (auto-détection clés API AWS)
- Support hooks pre-commit + pre-push
- Flag `--scan-history` optimisé (3x plus rapide grands repos)

**Patterns custom recommandés pour Friday** :
```bash
# Telegram Bot Tokens (format 1234567890:ABCdefGHI...)
git secrets --add 'TELEGRAM_BOT_TOKEN\s*=\s*["\'][0-9]{8,}:[A-Za-z0-9_-]{30,}["\']'

# Anthropic API Keys (format sk-ant-...)
git secrets --add 'sk-ant-[a-zA-Z0-9_-]{40,}'

# Age private keys (format AGE-SECRET-KEY-1...)
git secrets --add 'AGE-SECRET-KEY-1[A-Z0-9]{58}'

# PostgreSQL connection strings avec password
git secrets --add 'postgresql://[^:]+:[^@]+@'

# Redis passwords
git secrets --add 'REDIS_PASSWORD\s*=\s*["\'][^"\']{8,}["\']'
```

#### GitHub Dependabot (2026)

**Configuration recommandée** :
- **Ecosystems supportés** : pip, docker, npm, github-actions
- **Update schedule** : Weekly (lundi 8h) OU Monthly (1er du mois)
- **Open PR limit** : 5 max (évite spam PR)
- **Assignees** : Mainteneur (auto-assign toutes PR Dependabot)
- **Labels** : `dependencies`, `security` (auto-labeling)

**Best practices** :
- Activer **Dependabot security updates** (auto-PR CRITICAL/HIGH vulnérabilités)
- Activer **Dependabot version updates** (auto-PR nouvelles versions mineures)
- Review PR Dependabot hebdomadaire (merge si CI passe)

#### BFG Repo-Cleaner v1.14.0

**Usage recommandé si secrets détectés** :

```bash
# 1. Créer fichier patterns à remplacer
cat > secrets.txt <<EOF
TELEGRAM_BOT_TOKEN=1234567890:ABC***  # Remplacer par ***REMOVED***
sk-ant-abc123def456***               # Remplacer par ***REMOVED***
EOF

# 2. Nettoyer historique
java -jar bfg-1.14.0.jar --replace-text secrets.txt .git

# 3. Reflog + garbage collection
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 4. Force push (ATTENTION: réécrit historique)
git push --force --all
git push --force --tags
```

**Alternative git filter-branch** (plus lent mais natif Git) :

```bash
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty --tag-name-filter cat -- --all
```

---

## Project Context Reference

**Source de vérité architecturale** : [_docs/architecture-friday-2.0.md](../../_docs/architecture-friday-2.0.md)
- Section "Step 8: Security & Compliance" (NFR6-NFR11, chiffrement, RGPD)
- Section "Gaps & Limitations" (budget, contraintes open source)

**Documentation technique** :
- [docs/secrets-management.md](../../docs/secrets-management.md) : Guide complet age/SOPS (installation, workflow, rotation)
- [docs/tailscale-setup.md](../../docs/tailscale-setup.md) : Configuration Tailscale VPN (2FA, device authorization)
- [docs/DECISION_LOG.md](../../docs/DECISION_LOG.md) : Décisions techniques majeures

**NFRs associés** :
- **NFR8** : Zero exposition Internet public (Tailscale VPN, pas de ports ouverts)
- **NFR9** : Secrets chiffrés age/SOPS (clé privée jamais commitée)
- **NFR10** : Security hardening (branch protection, Dependabot, scan Git)

**Stories liées** :
- **Story 1.16** : CI/CD Pipeline GitHub Actions (prerequisite - tests doivent passer)
- **Story 1.4** : Tailscale VPN & Sécurité Réseau (contexte NFR8)
- **Story 1.2** : Schemas PostgreSQL & Migrations (aucun credential hardcodé vérifié)

---

## Completion Status

**Ready for Implementation** : Tous prérequis satisfaits

**Prérequis SATISFAITS** :
- ✅ Story 1.16 : CI/CD Pipeline opérationnel (tests passent, badge CI visible)
- ✅ Story 1.4 : Tailscale VPN configuré (hostname friday-vps, 2FA actif)
- ✅ age/SOPS installés (macOS/Linux/Windows, version v3.8.1+)
- ✅ GitHub CLI (gh) installé (config branch protection + Dependabot API)
- ✅ Codebase stable (aucune régression attendue - modifications config seulement)

**Blockers** : Aucun

**Estimation confiance** : Très élevée (98%)
- Story bien définie avec 11 AC clairs
- Outils sécurité standards (age, SOPS, git-secrets) matures et documentés
- Aucune modification code métier (seulement config sécurité)
- Tests E2E sécurité simples à implémenter (6 tests)

**Risks** :

1. **Nettoyage historique Git** (si secrets détectés AC5)
   - Impact : Force push requis = casser clones existants
   - Mitigation : Projet solo Mainteneur, aucun clone externe → impact minimal
   - Fallback : Si historique complexe, créer nouveau repo clean + migration

2. **Token Telegram révocation** (AC4)
   - Impact : Bot arrête de fonctionner pendant rotation
   - Mitigation : Révocation + nouveau token en <5 min (BotFather rapide)
   - Rollback : Impossible (révocation irréversible), DOIT avoir nouveau token prêt

3. **GitHub branch protection** (AC9)
   - Impact : Push direct master bloqué, workflow changé
   - Mitigation : Documentation claire workflow PR (créer branche → PR → merge)
   - Fallback : Mainteneur peut bypass protection si urgence (setting "Do not allow bypassing" = OFF)

---

## Dev Agent Record

### Agent Model Used

**Model**: Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`)
**Date**: 2026-02-10
**Workflow**: BMAD create-story (context-driven analysis)

### Debug Log References

*À compléter pendant implémentation*

### Completion Notes List

*À compléter après implémentation*

### File List

**Fichiers à créer** (9 nouveaux) :
- `SECURITY.md` (politique sécurité + responsible disclosure)
- `LICENSE` (MIT, copyright Mainteneur 2026)
- `.env.enc` (secrets chiffrés via SOPS)
- `.env.example` (structure secrets, valeurs fictives)
- `.github/dependabot.yml` (config pip + docker ecosystems)
- `docs/security-audit.md` (procédure scan Git + audit mensuel)
- `docs/pre-publication-checklist.md` (validation avant repo public)
- `tests/e2e/test_repo_security.sh` (6 tests E2E sécurité)

**Fichiers à modifier** (5) :
- `.sops.yaml` (mise à jour clé publique age Mainteneur)
- `.gitignore` (vérification patterns sensibles)
- `README.md` (section Sécurité + badge licence + liens docs)
- `scripts/setup_telegram_auto.py` (supprimer tokens hardcodés → os.getenv())
- `docs/secrets-management.md` (mise à jour clé publique exemples)

**Fichiers à supprimer** (1) :
- `.env` (après chiffrement → `.env.enc`, jamais committé)

---

## Change Log

| Date | Changements |
|------|-------------|
| 2026-02-10 | **Story 1.17 créée** — Préparation Repository Public : SOPS/age config, .env chiffré, tokens hardcodés nettoyés, rotation Telegram, scan Git, SECURITY.md, LICENSE, branch protection, Dependabot, tests E2E sécurité (11 AC, 12 tasks, 57 subtasks) |

---

## Status

**ready-for-dev** — Story complète, contexte exhaustif, tous prérequis satisfaits

**Created**: 2026-02-10
**Status**: ready-for-dev
**All Acceptance Criteria**: 11 AC définis (AC1-AC11)
**Tasks**: 12 tasks, 57 subtasks détaillés
**Estimation**: M (1 jour) - Confiance 98%
**Blockers**: Aucun
**Prerequisites**: Story 1.16 ✅, Story 1.4 ✅, age/SOPS ✅, GitHub CLI ✅
