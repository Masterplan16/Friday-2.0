> **[DEPRECATED D25]** Ce guide est obsolete. EmailEngine (PostalSys, 99 EUR/an) a ete remplace par IMAP direct (aioimaplib + aiosmtplib, gratuit).
> Voir : `_docs/plan-d25-emailengine-to-imap-direct.md` pour le plan de migration.
> Les comptes IMAP sont desormais configures via les variables `IMAP_ACCOUNT_*` dans `.env.email.enc` et geres par le daemon `imap-fetcher`.

# EmailEngine Setup - 4 Comptes IMAP [DEPRECATED D25]

**Date** : 2026-02-12
**Author** : Configuration Masterplan
**Status** : Ready for deployment

---

## Vue d'Ensemble

Configuration EmailEngine pour les 4 comptes email de Masterplan :

1. **Gmail Pro** : Compte professionnel
2. **Gmail Perso** : Compte personnel
3. **Zimbra Universite** : Compte faculte
4. **ProtonMail** : Via Bridge Tailscale

> **IMPORTANT** : Tous les credentials (emails, mots de passe, app passwords)
> sont stockes exclusivement dans `.env.email.enc` (chiffre age/SOPS).
> Ne JAMAIS lister de credentials en clair dans ce document ou dans le code.

---

## Prerequis

### 1. ProtonMail Bridge (PC)

**Le Bridge DOIT tourner en permanence sur le PC Masterplan.**

```powershell
# Verifier Bridge actif
Get-Process | Where-Object {$_.Name -like "*proton*"}

# Verifier port IMAP ouvert
Test-NetConnection -ComputerName 127.0.0.1 -Port 1143

# Verifier Tailscale
tailscale status
```

**Si Bridge pas lance** :
1. Ouvrir ProtonMail Bridge depuis le menu Demarrer
2. S'assurer qu'il demarre automatiquement avec Windows
3. Configuration Bridge :
   - IMAP Port : 1143
   - SMTP Port : 1025
   - Password : voir `PROTON_BRIDGE_PASSWORD` dans `.env.email.enc`

---

### 2. Tailscale VPN

```bash
# Sur VPS
tailscale status

# Tester connectivite VPS -> PC Bridge (utiliser nom DNS Tailscale)
nc -zv pc-mainteneur 1143
```

---

### 3. EmailEngine Docker

```bash
# Sur VPS
docker compose up -d emailengine

# Verifier logs
docker compose logs emailengine

# Test healthcheck
curl http://localhost:3000/health
```

---

## Installation

### Etape 1 : Charger les Credentials

```bash
# Sur VPS Friday
cd /opt/friday

# Dechiffrer credentials email
sops -d .env.email.enc > /tmp/.env.email

# Charger dans l'environnement
export $(cat /tmp/.env.email | xargs)

# Supprimer fichier en clair
rm /tmp/.env.email
```

---

### Etape 2 : Generer Secrets EmailEngine

```bash
# Generer EMAILENGINE_SECRET
openssl rand -hex 32

# Generer EMAILENGINE_ENCRYPTION_KEY
openssl rand -hex 32

# Ajouter dans .env.email.enc via sops
sops .env.email.enc
```

---

### Etape 3 : Configuration Automatique

```bash
# Installation dependances
pip install httpx python-dotenv

# Dry-run (test sans modification)
python scripts/setup_emailengine_4accounts.py --dry-run

# Configuration reelle
python scripts/setup_emailengine_4accounts.py
```

---

## Verification Post-Installation

### Test 1 : Lister les Comptes

```bash
curl -X GET http://localhost:3000/v1/accounts \
  -H "Authorization: Bearer ${EMAILENGINE_SECRET}"
```

### Test 2 : Envoyer Email Test

Envoyer un email test a chaque compte depuis un autre appareil.
Verifier reception :

```bash
sleep 30
docker compose logs emailengine | grep "messageNew"
```

### Test 3 : Verifier Consumer Friday

```bash
docker compose logs email-processor | grep "email_processed"
psql -d friday -c "SELECT account_id, subject_anon FROM ingestion.emails ORDER BY received_at DESC LIMIT 4;"
```

---

## Troubleshooting

### ProtonMail Bridge Injoignable

```bash
# Verifier Bridge tourne sur PC
# Verifier Tailscale connectivity depuis VPS
ping pc-mainteneur
nc -zv pc-mainteneur 1143
```

### Gmail Authentication Failed

1. Verifier App Password (regenerer si necessaire) : https://myaccount.google.com/apppasswords
2. Verifier 2FA active : https://myaccount.google.com/security
3. Mettre a jour credentials dans `.env.email.enc`

### Zimbra Universite Authentication Failed

1. Verifier credentials via webmail
2. Verifier serveur IMAP : `openssl s_client -connect imap.umontpellier.fr:993`
3. Mot de passe expire ? Reinitialiser via ENT universite

---

## Maintenance

### Rotation App Passwords Gmail

**Frequence** : Tous les 6 mois (recommande)

1. Generer nouveau App Password sur Google
2. Mettre a jour `.env.email.enc` via `sops`
3. Reconfigurer compte EmailEngine via API
4. Verifier reconnexion

### Monitoring Continu

```bash
# Ajouter dans crontab VPS (toutes les 5 min)
*/5 * * * * /opt/friday/scripts/check_emailengine_health.sh
```

---

## Securite

**CRITIQUE** : `.env.email` ne doit JAMAIS exister en clair sur disque.

```bash
# Chiffrer avec SOPS
sops -e .env.email > .env.email.enc
rm .env.email

# Dechiffrer temporairement pour utilisation
sops -d .env.email.enc > /tmp/.env.email
export $(cat /tmp/.env.email | xargs)
rm /tmp/.env.email
```

**Dans `.gitignore`** :
```
.env.email
.env.prod
.env.telegram
```

**Uniquement `.env.email.enc` peut etre commite.**

---

**Configuration complete :** 4 comptes IMAP operationnels via `.env.email.enc`.
