# Secrets Management - Friday 2.0

**Date** : 2026-02-05
**Version** : 1.0.0
**Objectif** : Guide complet pour chiffrer/déchiffrer les secrets avec age/SOPS

---

## 🔐 Principe

Friday 2.0 utilise **age** (chiffrement) + **SOPS** (gestion fichiers chiffrés) pour protéger les secrets (.env, credentials).

**Règles absolues** :
- ❌ JAMAIS de `.env` en clair dans git
- ❌ JAMAIS de credentials en default dans le code
- ✅ Fichiers chiffrés commitables : `.env.enc`, `secrets.yaml.enc`
- ✅ Déchiffrement local uniquement (clé privée sur machine dev)

---

## 📦 Installation

### **1. Installer age**

**macOS** :
```bash
brew install age
```

**Linux** :
```bash
# Debian/Ubuntu
sudo apt install age

# Arch
sudo pacman -S age
```

**Windows** :
```powershell
# Via scoop
scoop install age

# Ou télécharger depuis https://github.com/FiloSottile/age/releases
```

### **2. Installer SOPS**

**macOS** :
```bash
brew install sops
```

**Linux** :
```bash
# Télécharger depuis GitHub releases
wget https://github.com/getsops/sops/releases/download/v3.8.1/sops-v3.8.1.linux.amd64
sudo mv sops-v3.8.1.linux.amd64 /usr/local/bin/sops
sudo chmod +x /usr/local/bin/sops
```

**Windows** :
```powershell
scoop install sops
```

---

## 🔑 Setup initial (une seule fois)

### **1. Générer une paire de clés age**

```bash
# Générer clé privée + publique
age-keygen -o ~/.age/friday-key.txt

# Afficher la clé publique (pour partager avec équipe)
grep 'public key:' ~/.age/friday-key.txt
```

**Output exemple** :
```
# created: 2026-02-10T09:15:42Z
# public key: age17zcpkgjxdyk6g34anhymukncq49dtf6k4f3vgp5fchsv04a8quzq7rjn8t
AGE-SECRET-KEY-1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

**⚠️ CRITIQUE** :
- **Clé privée** (`AGE-SECRET-KEY-1...`) = SECRET, ne JAMAIS commiter
- **Clé publique** (`age17zcpkg...`) = Partageable, utilisée pour chiffrer
- **Clé publique actuelle projet Friday 2.0** : `age17zcpkgjxdyk6g34anhymukncq49dtf6k4f3vgp5fchsv04a8quzq7rjn8t`

### **2. Configurer SOPS**

Créer `.sops.yaml` à la racine du projet :

```yaml
# .sops.yaml
creation_rules:
  # Fichiers .env (sources non chiffrées)
  - path_regex: \.env$
    age: age17zcpkgjxdyk6g34anhymukncq49dtf6k4f3vgp5fchsv04a8quzq7rjn8t  # Clé publique Mainteneur

  # Fichiers .env chiffrés (pour édition in-place)
  - path_regex: \.env\.enc$
    age: age17zcpkgjxdyk6g34anhymukncq49dtf6k4f3vgp5fchsv04a8quzq7rjn8t  # Clé publique Mainteneur

  # Fichiers secrets YAML/JSON
  - path_regex: secrets.*\.(yaml|json)$
    age: age17zcpkgjxdyk6g34anhymukncq49dtf6k4f3vgp5fchsv04a8quzq7rjn8t

  # Fichiers secrets YAML/JSON chiffrés
  - path_regex: secrets.*\.(yaml|json)\.enc$
    age: age17zcpkgjxdyk6g34anhymukncq49dtf6k4f3vgp5fchsv04a8quzq7rjn8t
```

**Ce fichier PEUT être commité** (contient seulement la clé publique).

---

## 🔒 Workflow : Chiffrer les secrets

### **Chiffrer le fichier .env**

```bash
# 1. Créer .env en clair (temporaire)
cat > .env <<EOF
DATABASE_URL=postgresql://friday:password@localhost:5432/friday
REDIS_PASSWORD=super_secret_redis
ANTHROPIC_API_KEY=sk-ant-abc123def456
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHI
EOF

# 2. Chiffrer avec SOPS (spécifier format dotenv)
export SOPS_AGE_KEY_FILE=~/.age/friday-key.txt
sops --input-type dotenv --output-type dotenv -e .env > .env.enc

# 3. Vérifier que .env.enc est chiffré
cat .env.enc  # Doit montrer du contenu chiffré avec metadata sops_*

# 4. SUPPRIMER .env en clair
rm .env

# 5. Commiter .env.enc
git add .env.enc
git commit -m "Add encrypted secrets"
```

**⚠️ Important** : `.gitignore` doit contenir `.env` (pas `.env.enc`) :
```gitignore
# .gitignore
.env
!.env.example
!.env.enc
```

---

## 🔓 Workflow : Déchiffrer les secrets (dev local)

### **Méthode 1 : Déchiffrer en fichier temporaire**

```bash
# Déchiffrer .env.enc → .env (temporaire)
export SOPS_AGE_KEY_FILE=~/.age/friday-key.txt
sops --input-type dotenv --output-type dotenv -d .env.enc > .env

# Utiliser normalement
docker compose up -d

# Supprimer .env après usage
rm .env
```

### **Méthode 2 : Déchiffrer à la volée (sans fichier)**

```bash
# Export variables d'environnement directement
export SOPS_AGE_KEY_FILE=~/.age/friday-key.txt
export $(sops --input-type dotenv --output-type dotenv -d .env.enc | xargs)

# Vérifier
echo $DATABASE_URL
```

### **Méthode 3 : Script automatique**

Créer `scripts/load-secrets.sh` :

```bash
#!/bin/bash
# scripts/load-secrets.sh

if [ ! -f .env.enc ]; then
    echo "❌ .env.enc not found. Run: sops -e .env > .env.enc"
    exit 1
fi

echo "🔓 Déchiffrement des secrets..."
sops -d .env.enc > .env

echo "✅ Secrets déchiffrés dans .env (temporaire)"
echo "⚠️  N'oubliez pas de supprimer .env après usage !"
```

Usage :
```bash
./scripts/load-secrets.sh
docker compose up -d
rm .env  # Nettoyer après
```

---

## 👥 Partage de secrets avec l'équipe

### **Ajouter un nouveau développeur**

1. **Le dev génère sa clé age** :
   ```bash
   age-keygen -o ~/.age/friday-key.txt
   grep 'public key:' ~/.age/friday-key.txt
   # Envoie sa clé publique (age1xxx...) via canal sécurisé
   ```

2. **Admin ajoute la clé publique au .sops.yaml** :
   ```yaml
   creation_rules:
     - path_regex: \.env\.enc$
       age: >-
         age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq,  # Mainteneur
         age1yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy   # Nouveau dev
   ```

3. **Admin re-chiffre les secrets** avec les nouvelles clés :
   ```bash
   # Déchiffrer (avec ancienne config)
   sops -d .env.enc > .env

   # Re-chiffrer (avec nouvelle config incluant nouveau dev)
   sops -e .env > .env.enc

   # Commit
   git add .env.enc .sops.yaml
   git commit -m "Add dev key to secrets"

   # Cleanup
   rm .env
   ```

---

## 🔄 Rotation de clés

### **Quand ?**
- Départ d'un membre de l'équipe
- Clé compromise
- Tous les 6-12 mois (best practice)

### **Comment ?**

```bash
# 1. Générer nouvelle clé age
age-keygen -o ~/.age/friday-key-new.txt

# 2. Déchiffrer avec ancienne clé
export SOPS_AGE_KEY_FILE=~/.age/friday-key.txt
sops -d .env.enc > .env

# 3. Mettre à jour .sops.yaml avec nouvelle clé publique
# (éditer manuellement)

# 4. Re-chiffrer avec nouvelle clé
export SOPS_AGE_KEY_FILE=~/.age/friday-key-new.txt
sops -e .env > .env.enc

# 5. Commit
git add .env.enc .sops.yaml
git commit -m "Rotate age encryption keys"

# 6. Cleanup
rm .env
mv ~/.age/friday-key.txt ~/.age/friday-key-old.txt.bak
mv ~/.age/friday-key-new.txt ~/.age/friday-key.txt
```

---

## 🧪 Validation du setup

**Script de test** :

```bash
# scripts/test_secrets.sh

echo "🧪 Test secrets management..."

# 1. Créer fichier test
echo "TEST_SECRET=hello123" > .env.test

# 2. Chiffrer
sops -e .env.test > .env.test.enc
echo "✅ Chiffrement OK"

# 3. Déchiffrer
sops -d .env.test.enc > .env.test.dec
echo "✅ Déchiffrement OK"

# 4. Vérifier contenu identique
if diff .env.test .env.test.dec > /dev/null; then
    echo "✅ Contenu identique - Setup SOPS valide !"
else
    echo "❌ Erreur - Contenu différent"
    exit 1
fi

# 5. Cleanup
rm .env.test .env.test.enc .env.test.dec
```

---

## 🚨 Troubleshooting

### **Erreur : "no age identity found"**

```bash
# Solution: Spécifier le chemin de la clé
export SOPS_AGE_KEY_FILE=~/.age/friday-key.txt
sops -d .env.enc
```

### **Erreur : "MAC mismatch"**

Fichier chiffré avec une clé différente. Demander au propriétaire de re-chiffrer ou obtenir la bonne clé privée.

### **Fichier .env committé par erreur**

```bash
# 1. Supprimer du commit (mais garder en local)
git rm --cached .env

# 2. Ajouter à .gitignore si pas déjà fait
echo ".env" >> .gitignore

# 3. Commit
git commit -m "Remove .env from git tracking"

# 4. Vérifier historique git
git log --all --full-history -- .env

# 5. Si .env était dans l'historique, purger (ATTENTION: réécrit historique)
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty --tag-name-filter cat -- --all
```

---

## 📋 Checklist setup développeur

- [ ] age installé (`age --version`)
- [ ] SOPS installé (`sops --version`)
- [ ] Clé age générée (`~/.age/friday-key.txt`)
- [ ] Clé publique partagée avec admin
- [ ] `.sops.yaml` présent dans le projet
- [ ] `.env.enc` déchiffrable (`sops -d .env.enc`)
- [ ] Test secrets réussi (`./scripts/test_secrets.sh`)

---

**Créé le** : 2026-02-05
**Version** : 1.0.0
**Contributeur** : Claude (Code Review Adversarial - Issue #5)
