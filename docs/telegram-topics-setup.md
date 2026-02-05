# Telegram Topics - Guide de Setup

**Date** : 2026-02-05
**Version** : 1.0
**Pour** : Story 1.6.2 - Supergroup Setup

---

## 📋 Vue d'ensemble

Ce guide explique comment configurer le supergroup Telegram "Friday 2.0 Control" avec 5 topics spécialisés pour la stratégie de notification de Friday.

**Durée estimée** : 15 minutes

---

## ✅ Prérequis

Avant de commencer, assurez-vous d'avoir :

- [ ] Compte Telegram actif
- [ ] Telegram Desktop installé (obligatoire - mobile ne supporte pas la création de topics)
- [ ] Bot Friday créé via @BotFather (voir [addendum §5.2](_docs/architecture-addendum-20260205.md#52-guide-complet-obtention-variables))
- [ ] `TELEGRAM_BOT_TOKEN` dans votre fichier `.env`
- [ ] Python 3.11+ installé (pour script extraction thread IDs)

---

## 📝 Étape 1 : Créer le Supergroup Telegram

### 1.1 Créer un groupe standard

1. Ouvrir **Telegram Desktop** (obligatoire)
2. Cliquer sur le menu ☰ → **New Group**
3. Nommer le groupe : `Friday 2.0 Control`
4. Ajouter **au moins 1 autre membre** (requis pour conversion en supergroup)
   - Peut être un compte temporaire ou un ami
   - Vous pourrez le retirer après conversion

### 1.2 Convertir en Supergroup

1. Ouvrir les **Paramètres du groupe** (⋮ en haut à droite)
2. Cliquer sur **Convert to Supergroup**
3. Confirmer la conversion
4. ✅ Votre groupe est maintenant un supergroup

**Note** : Cette conversion est irréversible mais nécessaire pour activer les topics.

---

## 🔧 Étape 2 : Activer les Topics

### 2.1 Accéder aux paramètres Topics

1. Dans le supergroup, cliquer sur le nom du groupe en haut
2. Cliquer sur **Edit** (icône crayon)
3. Descendre jusqu'à la section **Topics**

### 2.2 Activer la fonctionnalité

1. Toggle **Enable Topics** → ON
2. Le supergroup va se réorganiser
3. Un topic "General" est créé automatiquement (c'est normal)

**Note** : Le topic "General" sera renommé en "Chat & Proactive" à l'étape suivante.

---

## 📂 Étape 3 : Créer les 5 Topics

### 3.1 Renommer le topic General

1. Clic droit sur **General** → **Edit Topic**
2. Nom : `💬 Chat & Proactive`
3. Icon : 💬 (copier-coller l'emoji)
4. Sauvegarder

### 3.2 Créer les 4 topics restants

Pour chaque topic ci-dessous, cliquer sur **+ New Topic** :

#### Topic 2 : Email & Communications
- **Nom** : `📬 Email & Communications`
- **Icon** : 📬
- **Description** (optionnelle) : Classifications email, pièces jointes, emails urgents

#### Topic 3 : Actions & Validations
- **Nom** : `🤖 Actions & Validations`
- **Icon** : 🤖
- **Description** : Actions nécessitant validation (inline buttons)

#### Topic 4 : System & Alerts
- **Nom** : `🚨 System & Alerts`
- **Icon** : 🚨
- **Description** : Santé système, alertes critiques, erreurs

#### Topic 5 : Metrics & Logs
- **Nom** : `📊 Metrics & Logs`
- **Icon** : 📊
- **Description** : Stats, métriques, logs non-critiques

### 3.3 Vérification

Vous devriez maintenant voir **5 topics** dans la barre latérale gauche :
1. 💬 Chat & Proactive
2. 📬 Email & Communications
3. 🤖 Actions & Validations
4. 🚨 System & Alerts
5. 📊 Metrics & Logs

---

## 🤖 Étape 4 : Ajouter le Bot Friday

### 4.1 Ajouter le bot au groupe

1. Dans le supergroup, cliquer sur **Add Members**
2. Rechercher votre bot (ex: `@friday_antonio_bot`)
3. Ajouter le bot au groupe

### 4.2 Promouvoir en administrateur

1. Aller dans **Paramètres du groupe** → **Administrators**
2. Cliquer sur **Add Administrator**
3. Sélectionner le bot Friday
4. Activer les permissions suivantes :
   - ✅ **Post Messages** (obligatoire)
   - ✅ **Edit Messages of Others** (optionnel mais recommandé)
   - ✅ **Delete Messages** (optionnel)
   - ✅ **Manage Topics** (obligatoire)
   - ✅ **Pin Messages** (optionnel)
5. Sauvegarder

**Note** : Le bot DOIT avoir les droits "Post Messages" et "Manage Topics" pour fonctionner.

### 4.3 Retirer le membre temporaire (optionnel)

Si vous aviez ajouté un membre temporaire à l'étape 1.1, vous pouvez maintenant le retirer :
1. Paramètres du groupe → **Members**
2. Trouver le membre → **Remove from Group**

---

## 🔑 Étape 5 : Extraire les Thread IDs

Chaque topic a un identifiant unique (`thread_id`) que Friday doit connaître pour router les messages correctement.

### 5.1 Obtenir le Chat ID du supergroup

1. Ajouter le bot [@userinfobot](https://t.me/userinfobot) **temporairement** au supergroup
2. @userinfobot va poster un message avec l'ID du groupe
3. Copier le **Chat ID** (ex: `-1001234567890`)
4. Retirer @userinfobot du groupe

### 5.2 Utiliser le script d'extraction

Nous fournissons un script Python pour extraire automatiquement les thread IDs :

```bash
# Depuis le dossier racine Friday 2.0
python scripts/extract_telegram_thread_ids.py
```

**Le script va :**
1. Se connecter au bot Telegram (utilise `TELEGRAM_BOT_TOKEN` dans `.env`)
2. Lister tous les topics du supergroup
3. Afficher les thread IDs de chaque topic
4. Générer un fichier `.env.telegram-topics` prêt à copier

### 5.3 Exemple de sortie

```bash
✅ Supergroup trouvé : Friday 2.0 Control
   Chat ID : -1001234567890

📂 Topics détectés :

1. 💬 Chat & Proactive
   thread_id: 2

2. 📬 Email & Communications
   thread_id: 3

3. 🤖 Actions & Validations
   thread_id: 4

4. 🚨 System & Alerts
   thread_id: 5

5. 📊 Metrics & Logs
   thread_id: 6

✅ Fichier généré : .env.telegram-topics
```

### 5.4 Ajouter à votre `.env`

Copier le contenu du fichier `.env.telegram-topics` généré dans votre fichier `.env` principal :

```bash
# Telegram Topics Configuration
TELEGRAM_SUPERGROUP_ID=-1001234567890
TOPIC_CHAT_PROACTIVE_ID=2
TOPIC_EMAIL_ID=3
TOPIC_ACTIONS_ID=4
TOPIC_SYSTEM_ID=5
TOPIC_METRICS_ID=6
```

**⚠️ IMPORTANT** : Chiffrer votre `.env` avec age/SOPS avant de committer (voir [docs/secrets-management.md](secrets-management.md)).

---

## ✅ Étape 6 : Validation

### 6.1 Test manuel

1. Envoyer un message dans le topic **💬 Chat & Proactive** : `Hello Friday!`
2. Le bot devrait **voir** le message (vérifier les logs bot)

### 6.2 Test automatisé (Story 1.6.5)

Une fois Story 1.6.3-1.6.4 implémentées, lancer les tests E2E :

```bash
pytest tests/e2e/test_telegram_topics.py -v
```

**Tests couverts :**
- Routage correct vers chaque topic
- Réponse bot dans Chat & Proactive
- Inline buttons dans Actions & Validations
- Pas de message perdu

---

## 🚨 Dépannage

### Le bot ne voit pas les messages

**Causes possibles :**
- Bot pas administrateur → Retour étape 4.2
- Topics désactivés → Retour étape 2
- Token bot incorrect → Vérifier `.env`

**Solution :**
```bash
# Tester la connexion bot
python -c "
from telegram import Bot
import os
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
print(bot.get_me())
"
```

### Thread IDs incorrects

**Symptôme :** Messages routés vers mauvais topics

**Solution :**
1. Re-lancer `scripts/extract_telegram_thread_ids.py`
2. Vérifier que l'ordre des topics correspond
3. Mettre à jour `.env`
4. Redémarrer services Friday

### Topics pas visibles sur mobile

**Cause :** Version Telegram mobile trop ancienne

**Solution :**
- Mettre à jour Telegram vers dernière version
- Utiliser Telegram Desktop comme fallback

---

## 📚 Ressources Additionnelles

- [Architecture Telegram Topics (addendum §11)](_docs/architecture-addendum-20260205.md#11-stratégie-de-notification--telegram-topics-architecture)
- [User Guide Telegram](telegram-user-guide.md)
- [Telegram Bot API - Topics](https://core.telegram.org/bots/api#forum-topic-management)
- [Decision Log - Stratégie Notification](DECISION_LOG.md#2026-02-05--stratégie-de-notification---telegram-topics-architecture)

---

**Setup terminé !** 🎉

Passer maintenant à Story 1.6.3 pour implémenter le routing bot.
