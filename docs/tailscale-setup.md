# Guide Setup Tailscale + 2FA pour Friday 2.0

**Version** : 1.0.0
**Date** : 2026-02-05
**Auteur** : Claude (Code Review Adversarial)

---

## Objectif

Configurer Tailscale VPN mesh pour Friday 2.0 avec :
- **2FA obligatoire** (Google Authenticator / Authy)
- **Device authorization** activée
- Connexion sécurisée VPS ↔ PC sans exposition SSH publique

---

## Prérequis

- Compte Tailscale gratuit : https://login.tailscale.com/start
- VPS OVH accessible (SSH initial via console OVH ou IP publique temporaire)
- PC Windows 11 avec droits admin
- Google Authenticator ou Authy installé sur smartphone

---

## Étape 1 : Créer compte Tailscale et activer 2FA

### 1.1 Création compte

1. Aller sur https://login.tailscale.com/start
2. Créer compte via Google / GitHub / Microsoft
3. Valider email

### 1.2 Activer 2FA (OBLIGATOIRE)

1. Aller sur https://login.tailscale.com/admin/settings/auth
2. Section **Two-factor authentication**
3. Cliquer **Enable two-factor authentication**
4. Scanner QR code avec Google Authenticator / Authy
5. Entrer code 6 chiffres pour confirmer
6. **Sauvegarder codes de récupération** dans gestionnaire de mots de passe (CRITIQUE)

✅ **Vérification** : Déconnexion puis reconnexion → doit demander code 2FA

---

## Étape 2 : Activer Device Authorization

**IMPORTANT** : Device authorization = tout nouvel appareil nécessite validation manuelle

1. Aller sur https://login.tailscale.com/admin/settings/keys
2. Section **Device authorization**
3. Cocher **Require device authorization**
4. Cliquer **Save**

✅ **Résultat** : Nouveaux devices seront en "pending" jusqu'à approbation manuelle

---

## Étape 3 : Installer Tailscale sur VPS (Ubuntu 22.04)

### 3.1 Connexion SSH initiale (via console OVH)

```bash
# Connexion via console web OVH (pas de Tailscale encore)
ssh root@<IP_VPS_PUBLIQUE>
```

### 3.2 Installation Tailscale

```bash
# Ajouter repo officiel Tailscale
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.noarmor.gpg | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.tailscale-list | sudo tee /etc/apt/sources.list.d/tailscale.list

# Installer Tailscale
sudo apt update
sudo apt install -y tailscale

# Vérifier installation
tailscale version
```

### 3.3 Connecter VPS au réseau Tailscale

```bash
# Se connecter (génère URL d'autorisation)
sudo tailscale up --hostname friday-vps

# Output :
# To authenticate, visit:
#   https://login.tailscale.com/a/abc123xyz
```

**Action** : Copier l'URL, ouvrir dans navigateur, se connecter avec 2FA, **approuver device**

✅ **Vérification** :
```bash
tailscale status
# Doit afficher :
# friday-vps   <votre-compte>   linux   active
# IP Tailscale : 100.x.y.z
```

### 3.4 Configurer hostname permanent

```bash
# Optionnel : Fixer le hostname pour éviter rename
sudo tailscale set --hostname friday-vps
```

---

## Étape 4 : Installer Tailscale sur PC Windows

### 4.1 Télécharger et installer

1. Télécharger : https://tailscale.com/download/windows
2. Exécuter `tailscale-setup.exe`
3. Installer (Next → Next → Finish)

### 4.2 Connecter PC au réseau

1. Cliquer icône Tailscale dans system tray
2. **Log in** → Se connecter avec compte + 2FA
3. Windows affichera "Device needs approval"
4. Aller sur https://login.tailscale.com/admin/machines
5. Trouver votre PC dans "Pending devices"
6. Cliquer **Approve**

✅ **Vérification** : Icône Tailscale verte, "Connected"

---

## Étape 5 : Tester connectivité VPS ↔ PC

### 5.1 Récupérer IP Tailscale VPS

Sur le VPS :
```bash
tailscale ip -4
# Exemple output : 100.64.1.10
```

### 5.2 Tester depuis PC Windows

Ouvrir PowerShell :
```powershell
# Ping VPS via Tailscale
ping 100.64.1.10

# SSH via Tailscale (SANS IP publique !)
ssh root@100.64.1.10
```

✅ **Succès** : SSH fonctionne via Tailscale IP (100.x.y.z)

---

## Étape 6 : Sécuriser SSH (désactiver IP publique)

**CRITIQUE** : Une fois Tailscale fonctionnel, DÉSACTIVER SSH sur IP publique

### 6.1 Configurer SSH pour écouter uniquement sur Tailscale

```bash
# Éditer config SSH
sudo nano /etc/ssh/sshd_config

# Trouver ligne : #ListenAddress 0.0.0.0
# Remplacer par :
ListenAddress 100.64.1.10  # Remplacer par votre IP Tailscale

# Redémarrer SSH
sudo systemctl restart sshd
```

### 6.2 Configurer firewall UFW

```bash
# Autoriser SSH UNIQUEMENT depuis Tailscale (100.x.0.0/16)
sudo ufw allow from 100.64.0.0/10 to any port 22 proto tcp

# Bloquer SSH depuis Internet
sudo ufw deny 22/tcp

# Activer firewall
sudo ufw enable

# Vérifier règles
sudo ufw status numbered
```

✅ **Vérification** :
- SSH via Tailscale (100.x.y.z) → **Fonctionne**
- SSH via IP publique → **Refusé** (timeout ou connection refused)

---

## Étape 7 : Ajouter périphériques supplémentaires (optionnel)

### Smartphone Android/iOS

1. Installer app Tailscale depuis Play Store / App Store
2. Se connecter avec compte + 2FA
3. Approuver device dans https://login.tailscale.com/admin/machines

### Autre PC / Laptop

Répéter Étape 4 pour chaque appareil

---

## Maintenance et bonnes pratiques

### Vérifier devices connectés

Tableau de bord : https://login.tailscale.com/admin/machines

- ✅ **Actifs** : appareils connectés
- ⏸️ **Inactifs** : non vus depuis >7 jours
- ❌ **Révoqués** : désactivés manuellement

### Révoquer un device perdu/volé

1. Aller sur https://login.tailscale.com/admin/machines
2. Cliquer device concerné
3. **Disable key** → Device immédiatement déconnecté

### Renouvellement clés

Key expiry configuré à **90 jours** (Machines > friday-vps > Key expiry dans le dashboard Tailscale).
Tailscale affichera un avertissement avant expiration. Renouveler via le dashboard : Machines > friday-vps > Renew key

### Rotation codes 2FA

Recommandation : Régénérer codes 2FA tous les 12 mois :
1. https://login.tailscale.com/admin/settings/auth
2. **Disable 2FA** → **Enable 2FA** (nouveau QR code)
3. Sauvegarder nouveaux codes récupération

---

## Dépannage

### Problème : "Device needs approval" mais pas de pending device

**Cause** : Device authorization pas activée
**Solution** : Aller sur https://login.tailscale.com/admin/settings/keys → Activer "Require device authorization"

### Problème : SSH via Tailscale timeout

**Cause** : Firewall bloque Tailscale
**Solution** :
```bash
# Sur VPS, autoriser Tailscale dans UFW
sudo ufw allow in on tailscale0
```

### Problème : VPS disparaît de la liste après reboot

**Cause** : Service Tailscale pas démarré
**Solution** :
```bash
# Activer démarrage automatique
sudo systemctl enable tailscaled
sudo systemctl start tailscaled
```

### Problème : Oublié codes récupération 2FA

**GRAVE** : Sans codes récupération, impossible de récupérer compte si perte smartphone

**Prévention** :
1. Sauvegarder codes dans **gestionnaire de mots de passe** (Bitwarden, 1Password)
2. ET imprimer codes sur papier (coffre-fort physique)

---

## Checklist finale validation

- [ ] Compte Tailscale créé
- [ ] 2FA activé (Google Authenticator / Authy)
- [ ] Device authorization activée
- [ ] Key expiry configuré à 90 jours (Machines > friday-vps > Key expiry)
- [ ] Codes récupération 2FA sauvegardés (gestionnaire + papier)
- [ ] VPS connecté à Tailscale (hostname: friday-vps)
- [ ] PC Windows connecté à Tailscale
- [ ] SSH via Tailscale IP fonctionne depuis PC → VPS
- [ ] SSH via IP publique BLOQUÉ (ufw deny 22/tcp)
- [ ] Service tailscaled activé au démarrage VPS

---

## Résumé configuration finale

| Élément | Valeur |
|---------|--------|
| **VPS hostname** | friday-vps |
| **VPS Tailscale IP** | 100.x.y.z (noter dans gestionnaire mots de passe) |
| **SSH access** | UNIQUEMENT via Tailscale (IP publique bloquée) |
| **2FA** | Google Authenticator / Authy (obligatoire) |
| **Device authorization** | Activée (approbation manuelle nouveaux devices) |

---

## Références

- Documentation officielle : https://tailscale.com/kb/
- Best practices 2FA : https://tailscale.com/kb/1277/2fa/
- Firewall setup : https://tailscale.com/kb/1077/secure-server-ubuntu-18-04/

---

**✅ Setup Tailscale terminé ! Votre Friday 2.0 est maintenant accessible UNIQUEMENT via VPN sécurisé.**
