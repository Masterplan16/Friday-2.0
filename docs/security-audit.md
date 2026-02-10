# Security Audit - Friday 2.0

**Date création** : 2026-02-10
**Version** : 1.0.0
**Objectif** : Guide audit sécurité mensuel et procédures de scan historique Git

---

## 🔍 Scan historique Git pour secrets

### Outils recommandés

| Outil | Usage | Installation |
|-------|-------|--------------|
| **git-secrets** | Scan historique + hooks pre-commit | `curl -L https://raw.githubusercontent.com/awslabs/git-secrets/master/git-secrets -o ~/bin/git-secrets && chmod +x ~/bin/git-secrets` |
| **truffleHog** | Scan entropie haute (alternative) | `pip install truffleHog` |

---

## 📋 Procédure scan mensuel

**Fréquence** : 1er du mois
**Durée estimée** : 10 minutes

### Étape 1 : Installer git-secrets (si pas déjà fait)

```bash
cd ~/bin
curl -L https://raw.githubusercontent.com/awslabs/git-secrets/master/git-secrets -o git-secrets
chmod +x git-secrets
```

### Étape 2 : Configurer patterns Friday

```bash
cd /path/to/friday-2.0

# Installer hooks
git secrets --install

# Ajouter patterns Telegram
git secrets --add 'TELEGRAM_BOT_TOKEN\s*=\s*["\'"'"'][0-9]{8,}:[A-Za-z0-9_-]{30,}["\'"'"']'

# Ajouter patterns Anthropic API
git secrets --add 'sk-ant-[a-zA-Z0-9_-]{40,}'

# Ajouter patterns age private keys
git secrets --add 'AGE-SECRET-KEY-1[A-Z0-9]{58}'

# Ajouter patterns PostgreSQL avec password
git secrets --add 'postgresql://[^:]+:[^@]+@'

# Ajouter patterns Redis password
git secrets --add 'REDIS_PASSWORD\s*=\s*["\'"'"'][^"\'"'"']{8,}["\'"'"']'
```

### Étape 3 : Marquer faux positifs autorisés

```bash
# Exemple fictif dans docs
git secrets --add --allowed 'AGE-SECRET-KEY-1X{58}'

# Variable bash (pas hardcodé)
git secrets --add --allowed 'REDIS_PASSWORD="\$\{REDIS_PASSWORD:-\}"'
```

### Étape 4 : Scanner historique complet

```bash
# Scan historique (peut prendre 1-2 min)
git secrets --scan-history

# Si succès → Aucun secret détecté ✅
# Si erreur → Analyser détections ci-dessous
```

### Étape 5 : Analyser détections

Si `git secrets --scan-history` échoue :

1. **Examiner détections** :
   ```bash
   git secrets --scan-history 2>&1 | grep ":" | head -20
   ```

2. **Distinguer faux positifs vs vrais secrets** :
   - **Faux positif** : Exemple fictif, variable bash, commentaire
   - **Vrai secret** : Token réel, password hardcodé, clé privée

3. **Actions selon type** :
   - **Faux positif** : Ajouter pattern allowed (étape 3)
   - **Vrai secret** : NETTOYER HISTORIQUE (étape 6)

### Étape 6 : Nettoyer historique si secret détecté (CRITIQUE)

⚠️ **ATTENTION** : Réécriture historique = force push requis

**Option A : BFG Repo-Cleaner (recommandé)**

```bash
# Télécharger BFG
wget https://repo1.maven.org/maven2/com/madgag/bfg/1.14.0/bfg-1.14.0.jar

# Créer fichier patterns à remplacer
cat > secrets.txt <<EOF
TELEGRAM_BOT_TOKEN=1234567890:ABC***  # Remplacer par ***REMOVED***
sk-ant-abc123def456***               # Remplacer par ***REMOVED***
EOF

# Nettoyer historique
java -jar bfg-1.14.0.jar --replace-text secrets.txt .git

# Reflog + garbage collection
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force push (ATTENTION: réécrit historique)
git push --force --all
git push --force --tags
```

**Option B : git filter-branch (natif mais plus lent)**

```bash
# Supprimer fichier de tous les commits
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty --tag-name-filter cat -- --all

# Cleanup
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

---

## 🧪 Tests validation

### Test 1 : Hooks pre-commit bloquent nouveaux secrets

```bash
# Créer fichier avec secret test
echo "TELEGRAM_BOT_TOKEN='1234567890:ABCdefGHIjklMNOpqrsTUVwxyz12345678'" > test-secret.txt

# Tenter commit
git add test-secret.txt
git commit -m "test"

# DOIT ÉCHOUER avec message : [ERROR] Matched one or more prohibited patterns
# Si bloqué → ✅ Hooks fonctionnent
# Si commit réussit → ❌ Hooks non installés
```

### Test 2 : Scan historique passe

```bash
# Scanner historique complet
git secrets --scan-history

# DOIT retourner exit code 0 (succès)
# Si 0 → ✅ Historique propre
# Si 1 → ❌ Secrets détectés (analyser)
```

### Test 3 : Patterns détectent secrets réels

```bash
# Créer fichier test avec vrai format token
echo "TELEGRAM_BOT_TOKEN=REVOKED_TELEGRAM_TOKEN_1" > test.txt

# Scanner fichier
git secrets --scan test.txt

# DOIT ÉCHOUER (secret détecté)
# Cleanup
rm test.txt
```

---

## 📅 Checklist audit mensuel

**Date audit** : _________

- [ ] git-secrets installé et à jour
- [ ] Patterns Friday configurés (5 patterns minimum)
- [ ] Faux positifs autorisés documentés
- [ ] Scan historique exécuté (`git secrets --scan-history`)
- [ ] Aucun secret réel détecté dans historique
- [ ] Hooks pre-commit testés et fonctionnels
- [ ] Permissions GitHub reviewées (collaborators, tokens)
- [ ] Dependabot alerts reviewées et corrigées
- [ ] Rotation tokens si >90 jours depuis dernière rotation
- [ ] Backup chiffré testé (restore test)

---

## 🚨 Procédure incident (secret exposé)

### Phase 1 : Containment (dans les 30 min)

1. **Révoquer immédiatement le secret exposé** :
   - Telegram : `/revoke` via @BotFather
   - Anthropic API : Revoke key via dashboard
   - PostgreSQL : `ALTER USER friday PASSWORD 'nouveau'`

2. **Générer nouveau secret** :
   - Telegram : `/token` via @BotFather
   - Anthropic : Create new API key
   - PostgreSQL : Password aléatoire 32+ caractères

3. **Mettre à jour `.env.enc`** :
   ```bash
   ./scripts/load-secrets.sh
   # Éditer .env avec nouveau secret
   sops -e .env > .env.enc
   rm .env
   git add .env.enc
   git commit -m "security: rotate exposed secret"
   ```

### Phase 2 : Eradication (dans les 2h)

4. **Nettoyer historique Git** (voir étape 6 ci-dessus)

5. **Force push** :
   ```bash
   git push --force --all
   git push --force --tags
   ```

6. **Notifier collaborateurs** (si repo partagé) :
   - "Git history rewritten, please re-clone"

### Phase 3 : Recovery (dans les 24h)

7. **Tester services avec nouveaux secrets**

8. **Vérifier aucune utilisation ancien secret** :
   - Logs Telegram API (unauthorized attempts)
   - Logs Anthropic API (invalid key errors)

9. **Documenter incident** :
   - Date exposition
   - Secret exposé (type, pas valeur)
   - Actions prises
   - Leçons apprises

---

## 📚 Références

- **git-secrets GitHub** : https://github.com/awslabs/git-secrets
- **truffleHog** : https://github.com/trufflesecurity/truffleHog
- **BFG Repo-Cleaner** : https://rtyley.github.io/bfg-repo-cleaner/
- **OWASP Secrets Management** : https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

---

**Créé le** : 2026-02-10
**Contributeur** : Claude Sonnet 4.5 (Story 1.17 - Préparation Repository Public)
