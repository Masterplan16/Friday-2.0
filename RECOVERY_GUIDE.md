# Guide de récupération - Friday 2.0 Email Pipeline

**Date**: 2026-02-14
**Contexte**: Résolution problème Presidio + 189 emails pending

---

## 📊 État actuel

### ✅ Problèmes résolus

1. **Presidio fonctionne parfaitement** 🎉
   - Bug résolu : Docker cache + besoin de `--force-recreate`
   - Tous les appels Presidio retournent 200 OK
   - Anonymisation/deanonymisation opérationnelles

2. **Consumer corrigé**
   - `AnonymizationResult.anonymized_text` extraction corrigée
   - Stream name corrigé (`emails:received`)
   - Bytes/string comparison fixé pour `pipeline_enabled`

3. **Trust Layer corrigé**
   - `json.dumps(payload)` pour asyncpg JSONB
   - `classify_email()` accepte `**kwargs` du décorateur

4. **Email accounts initialisés** ✅
   - 3 comptes insérés dans `ingestion.email_accounts`:
     - `account_gmail1` (lopez.tonio@gmail.com)
     - `account_gmail2` (contact.antoniolopez@gmail.com)
     - `account_universite` (antonio.lopez@umontpellier.fr)
   - Script propre : `scripts/init_email_accounts.py`

5. **Spam Telegram stoppé** 🛑
   - Pipeline désactivé : `friday:pipeline_enabled = false`
   - Consumer en mode `'>'` (nouveaux seulement)

### ❌ Bloqueur actuel

**ANTHROPIC_API_KEY invalide**
- Valeur actuelle : `placeholder_will_set_later`
- Erreur : `401 Unauthorized - invalid x-api-key`
- Impact : Impossible de classifier les emails (appels Claude échouent)

### 📦 189 emails pending

Les emails sont toujours dans Redis Streams (status `pending`), **non perdus**.
Ils seront retraités une fois la clé API configurée.

---

## 🔧 Actions requises (Antonio)

### Étape 1 : Configurer ANTHROPIC_API_KEY

```powershell
# Sur PC Windows
cd "C:\Users\lopez\Desktop\Friday 2.0"

# 1. Déchiffrer .env.enc
python decrypt_env.py
# → Crée .env.decrypted

# 2. Éditer .env.decrypted avec Notepad
notepad .env.decrypted

# 3. Remplacer la ligne :
ANTHROPIC_API_KEY=placeholder_will_set_later
# par :
ANTHROPIC_API_KEY=sk-ant-api03-VOTRE_VRAIE_CLE_ICI

# 4. Sauvegarder et fermer

# 5. Rechiffrer avec SOPS
C:\Users\lopez\bin\sops.exe -e .env.decrypted > .env.enc

# 6. Nettoyer le fichier déchiffré
del .env.decrypted

# 7. Copier sur VPS
scp .env.enc ubuntu@54.37.231.98:~/Friday-2.0/.env.enc

# 8. Sur VPS, recréer .env depuis .env.enc
ssh ubuntu@54.37.231.98
cd Friday-2.0
sops -d .env.enc > .env

# 9. Redémarrer les services Docker
docker compose restart
```

### Étape 2 : Vérifier que ça fonctionne

```bash
# Sur VPS
ssh ubuntu@54.37.231.98

# 1. Vérifier que la clé est chargée
docker exec friday-email-processor printenv | grep ANTHROPIC
# Doit afficher : ANTHROPIC_API_KEY=sk-ant-api03-...

# 2. Activer le pipeline
docker exec friday-redis redis-cli SET friday:pipeline_enabled true

# 3. Tester avec 1 nouvel email
# Envoyer un email test à lopez.tonio@gmail.com
# Vérifier les logs :
docker logs friday-email-processor --tail 50 --follow
# Doit voir : classification réussie, email stocké
```

### Étape 3 : Retraiter les 189 pending (OPTIONNEL)

Une fois le test réussi, deux options :

#### Option A : Les ignorer (recommandé si emails déjà lus ailleurs)

```bash
# Supprimer les pending (ACK sans traiter)
cd Friday-2.0
./scripts/reset_pending_emails.sh --delete
```

#### Option B : Les retraiter (si emails importants)

```bash
# 1. Réassigner les pending pour retraitement
cd Friday-2.0
./scripts/reset_pending_emails.sh --reclaim

# 2. Modifier temporairement consumer.py ligne 271
# Changer '>' en '0' pour lire les pending

# 3. Rebuild et redémarrer
docker compose build email-processor
docker compose up -d email-processor --force-recreate

# 4. Surveiller le traitement
docker logs friday-email-processor --tail 100 --follow

# 5. Une fois tous traités (pending=0), remettre '>' et redémarrer
docker compose restart email-processor
```

---

## 📝 Vérifications post-configuration

### Check 1 : Email stocké en base

```bash
ssh ubuntu@54.37.231.98
docker exec friday-postgres psql -U friday -d friday -c \
  'SELECT id, account_id, from_anon, subject_anon, category FROM ingestion.emails LIMIT 5;'
```

Doit afficher les emails classifiés.

### Check 2 : Trust Layer receipts

```bash
docker exec friday-postgres psql -U friday -d friday -c \
  'SELECT module, action_type, confidence, status FROM core.action_receipts ORDER BY created_at DESC LIMIT 5;'
```

Doit afficher les receipts des actions (detect_vip, detect_urgency, classify).

### Check 3 : Redis Streams propre

```bash
docker exec friday-redis redis-cli XINFO GROUPS emails:received
```

Doit afficher `pending: 0` après traitement.

---

## 🆘 Troubleshooting

### Problème : 401 Unauthorized persiste

**Cause** : La clé API n'est pas chargée dans le container

**Solution** :
```bash
# Vérifier que .env contient la vraie clé
ssh ubuntu@54.37.231.98 "cat ~/Friday-2.0/.env | grep ANTHROPIC"

# Si toujours placeholder, refaire Étape 1 complète
# Ne pas oublier le "sops -d .env.enc > .env" sur le VPS
```

### Problème : classify_email() échoue toujours

**Cause** : Quota API dépassé ou clé révoquée

**Solution** :
```bash
# Tester la clé manuellement
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: sk-ant-api03-..." \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-5-20250929","max_tokens":10,"messages":[{"role":"user","content":"test"}]}'
```

### Problème : Spam Telegram reprend

**Cause** : Pipeline réactivé sans clé API valide

**Solution** :
```bash
# Désactiver le pipeline immédiatement
docker exec friday-redis redis-cli SET friday:pipeline_enabled false

# Corriger la clé API
# Puis réactiver après vérification
```

---

## 📚 Fichiers créés/modifiés

### Scripts utilitaires
- `scripts/init_email_accounts.py` - Initialisation email accounts
- `scripts/reset_pending_emails.sh` - Gestion pending Redis

### Corrections code
- `agents/src/tools/anonymize.py` - Presidio fix
- `agents/src/middleware/trust.py` - JSON serialization fix
- `agents/src/agents/email/classifier.py` - **kwargs fix
- `services/email_processor/consumer.py` - Multiple fixes

### Commits importants
- `89d5466` - fix(consumer): use '0' to reprocess pending
- `bd2b042` - fix(trust): serialize payload to JSON
- `078f648` - feat(email): add accounts init script
- `86b75ce` - fix(consumer): revert to '>' to stop spam

---

## ✅ Next Steps (après clé API configurée)

1. **Story 2.2** : Email Classification (classifier.py prêt)
2. **Story 2.3** : VIP Detection (detect_vip prêt)
3. **Story 2.4** : Urgency Detection (detect_urgency prêt)
4. **Story 2.5** : Email Drafting & Sending

**Note** : L'infrastructure est **100% prête**. Seule la clé API manque pour débloquer.

---

**Contact** : Antonio Lopez
**VPS** : 54.37.231.98 (OVH VPS-4, 48 Go RAM)
**Projet** : Friday 2.0 - MVP Sprint 1
