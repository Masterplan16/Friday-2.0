# Friday 2.0 - Guide Utilisateur Telegram

**Date** : 2026-02-05
**Version** : 1.0
**Pour** : Antonio (utilisateur final)

---

## 🎯 Introduction

Bienvenue dans le guide d'utilisation quotidienne de Friday 2.0 via Telegram ! Ce guide explique comment tirer le meilleur parti des 5 topics spécialisés et personnaliser vos notifications selon vos besoins.

---

## 📱 Accès au Supergroup

### Première connexion

1. Ouvrir Telegram (Desktop ou Mobile)
2. Rechercher **Friday 2.0 Control**
3. Cliquer pour ouvrir

**Par défaut, vous arrivez dans le topic "💬 Chat & Proactive"** - c'est normal et voulu !

### Navigation entre topics

**Sur Desktop :**
- Barre latérale gauche liste tous les topics
- Cliquer sur un topic pour l'ouvrir

**Sur Mobile :**
- Swipe vers la droite pour voir la liste des topics
- Ou toucher le nom du groupe en haut → Topics

---

## 💬 Topic 1 : Chat & Proactive (DEFAULT)

### Rôle
C'est **votre conversation principale avec Friday**. Utilisez ce topic pour :
- Poser des questions à Friday
- Envoyer des commandes
- Répondre aux messages proactifs (heartbeat)
- Recevoir des reminders

### Exemples d'usage

**Commandes disponibles :**
```
/status          Voir l'état du système (services, RAM, dernières actions)
/journal         Afficher les 20 dernières actions
/receipt abc123  Voir le détail d'une action spécifique
/confiance       Tableau des taux de confiance par module
/stats           Métriques globales agrégées
```

**Questions libres :**
```
"Résume mes emails urgents"
"Quelles sont mes deadlines de la semaine ?"
"Qu'est-ce qui est prévu dans mon calendrier demain ?"
```

**Heartbeat (toutes les 30min) :**
Friday initie la conversation :
```
🤖 Friday : "Bonjour Antonio ! J'ai vérifié tes emails : 2 urgents détectés. Veux-tu les résumer ?"
👤 Toi : "Oui"
🤖 Friday : "Voici les résumés..."
```

**💡 Astuce** : La conversation est **continue** - Friday se souvient du contexte dans ce topic.

---

## 📬 Topic 2 : Email & Communications

### Rôle
Notifications automatiques liées à vos emails et communications.

### Ce que vous verrez ici

**Classifications automatiques :**
```
📧 Email classifié : medical
De : Dr. Martin
Sujet : Résultats analyses
Confiance : 95%
```

**Pièces jointes détectées :**
```
📎 Pièce jointe extraite
Email : Carrefour Drive
Fichier : facture_202602.pdf
→ Envoyé à l'Archiviste
```

**Emails urgents :**
```
🚨 Email urgent détecté !
De : Université Paris
Sujet : Deadline mémoire M2
Échéance : 2026-02-15
```

### Quand muter ce topic ?

**Mode Focus** : Vous travaillez sur votre thèse et ne voulez pas être distrait par les notifications email → **Mute 8h**

**Mode Vacances** : Vous ne consultez vos emails que manuellement → **Mute jusqu'à réactivation**

---

## 🤖 Topic 3 : Actions & Validations

### Rôle
Actions nécessitant **votre validation** (trust level = `propose`).

### Ce que vous verrez ici

**Inline buttons pour approbation :**
```
📝 Action en attente de validation

Module : email
Action : draft_reply
Input : Email de Sarah (demande info thèse)

Brouillon proposé :
"Bonjour Sarah, voici les informations demandées..."

[✅ Approuver] [✏️ Modifier] [❌ Rejeter]
```

**Corrections appliquées :**
```
✏️ Correction enregistrée
Tu as corrigé : "Email URSSAF → finance (était: professional)"
→ Pattern détecté (2 occurrences similaires)
→ Règle proposée : SI email contient "URSSAF" ALORS finance
[✅ Créer règle] [❌ Ignorer]
```

**Trust level changes :**
```
📈 Trust level mis à jour
email.classify : propose → auto
Raison : Accuracy 97% sur 3 semaines
```

### Quand muter ce topic ?

**JAMAIS** (ou très rarement) - Ce topic contient les actions nécessitant **votre décision**.

**Exception** : Mode Vacances si vous ne voulez **rien approuver** pendant votre absence.

---

## 🚨 Topic 4 : System & Alerts

### Rôle
Santé du système et alertes critiques.

### Ce que vous verrez ici

**Alertes RAM :**
```
⚠️ Alerte RAM
Utilisation : 87% (42 Go / 48 Go)
Services actifs : Ollama, Whisper, Kokoro, Surya
Recommandation : Vérifier si processus bloqué
```

**Services down/up :**
```
🔴 Service DOWN
PostgreSQL : Connexion perdue
Impact : Tous modules bloqués
Action : Redémarrage automatique en cours...

✅ Service UP
PostgreSQL : Reconnecté après 30s
Statut : Tous modules opérationnels
```

**Erreurs pipeline critiques :**
```
❌ Erreur critique
Pipeline : email.classify
Erreur : Mistral API rate limit exceeded
Impact : 15 emails en attente
Action : Retry dans 60s
```

**Backups :**
```
✅ Backup réussi
PostgreSQL : Backup quotidien terminé
Taille : 2.4 Go
Stockage : VPS + copie PC via Tailscale
```

### Quand muter ce topic ?

**Mode Deep Work** : Vous gardez **uniquement** ce topic actif pour les alertes critiques → **Mute tous les autres**

**JAMAIS en Mode Normal** : Vous devez être informé des problèmes système.

---

## 📊 Topic 5 : Metrics & Logs

### Rôle
Statistiques, métriques, logs non-critiques (verbose).

### Ce que vous verrez ici

**Actions auto (trust=auto) :**
```
✅ Action exécutée
email.classify : Email URSSAF → finance
Confiance : 96%
Durée : 1.2s
```

**Métriques nightly :**
```
📊 Métriques hebdomadaires
email.classify : 147 emails traités, 3 corrigés (98% accuracy)
archiviste.ocr : 24 documents, 1 corrigé (96% accuracy)
finance.categorize : 18 transactions, 0 corrigé (100% accuracy)
```

**Logs détaillés :**
```
[2026-02-05 14:23:15] INFO: Heartbeat check completed (3 emails pending)
[2026-02-05 14:23:18] DEBUG: Cache hit for sender "sarah@example.com"
[2026-02-05 14:23:20] INFO: Email classification took 1.1s
```

### Quand muter ce topic ?

**Mode Normal** : Si le volume devient trop élevé → **Mute**

**Mode Focus / Deep Work** : Toujours muté → **Consulter manuellement si besoin**

---

## 🎚️ Stratégies de Muting

### Scénarios d'usage

| Contexte | Topics actifs | Topics mutés | Rationale |
|----------|---------------|--------------|-----------|
| **Mode Normal** | Tous (5/5) | Aucun | Visibilité totale, filtrage manuel si besoin |
| **Mode Focus** | Chat, Actions, System (3/5) | Email, Metrics | Concentré sur validations + alertes uniquement |
| **Mode Deep Work** | System uniquement (1/5) | Tous sauf System | Alertes critiques seulement, zéro distraction |
| **Mode Vacances** | Aucun (0/5) | Tous | Check manuel quand vous voulez |

### Comment muter un topic

**Sur Desktop :**
1. Clic droit sur le topic → **Mute**
2. Choisir durée : 1h, 8h, Until I turn it back on
3. ✅ Topic muté (icône 🔕 apparaît)

**Sur Mobile :**
1. Long press sur le topic → **Mute**
2. Choisir durée
3. ✅ Topic muté

**Pour unmute :** Même procédure, sélectionner "Unmute"

---

## 💡 Astuces & Best Practices

### 1. Progressive Disclosure

**Principe** : Voir seulement ce dont vous avez besoin.

- **Matin (Mode Normal)** : Tous topics actifs → Check rapide de tout
- **Travail thèse (Mode Focus)** : Mute Email + Metrics → Concentration
- **Réunion importante (Mode Deep Work)** : Mute tout sauf System → Alerte critique uniquement

### 2. Historique Consultable

**Même muté, un topic garde son historique.**

Exemple : Metrics est muté toute la journée, mais vous voulez voir les stats du soir :
1. Ouvrir topic **📊 Metrics & Logs**
2. Scroller pour voir l'historique
3. Topic reste muté → Pas de notifications

### 3. Notifications Push Personnalisées

**Sur Mobile**, vous pouvez configurer par topic :
1. Paramètres du supergroup → **Notifications**
2. **Custom Notifications per Topic**
3. Configurer :
   - 💬 Chat & Proactive → Son + Vibration
   - 🤖 Actions & Validations → Son + Vibration (priorité)
   - 🚨 System & Alerts → Son fort + Vibration
   - 📬 Email → Silencieux (badge seulement)
   - 📊 Metrics → Désactivées

### 4. Do Not Disturb Natif

**Utiliser les fonctionnalités téléphone :**
- **iOS** : Focus modes (Travail, Sommeil, etc.)
- **Android** : Do Not Disturb + Scheduled silence

**Avantage** : Configurations sauvegardées, activation automatique selon heure/lieu.

### 5. Search & Filtres

**Rechercher dans un topic spécifique :**
1. Ouvrir le topic
2. Cliquer sur l'icône 🔍 (search)
3. Taper mot-clé : "URSSAF", "backup", "urgent"
4. ✅ Résultats filtrés dans ce topic uniquement

---

## ❓ Questions Fréquentes (FAQ)

### Je ne vois pas les topics sur mobile ?

**Cause** : Version Telegram trop ancienne ou fonctionnalité pas activée.

**Solution** :
1. Mettre à jour Telegram vers dernière version
2. Ou utiliser Telegram Desktop comme fallback

### Puis-je créer des topics supplémentaires ?

**Réponse** : Oui, mais Friday ne les utilisera pas automatiquement.

Les 5 topics sont codés en dur dans `config/telegram.yaml`. Ajouter un 6e topic nécessite modification code (Story future).

### Puis-je renommer les topics ?

**Réponse** : Oui, mais attention !

Friday route par `thread_id`, pas par nom. Renommer n'affecte pas le routing. Mais gardez les noms cohérents pour éviter confusion.

### Je ne reçois plus de notifications ?

**Checklist** :
1. ✅ Bot Friday est admin du groupe ?
2. ✅ Topics pas mutés ?
3. ✅ Notifications Telegram activées sur téléphone ?
4. ✅ Services Friday opérationnels ? (`/status`)

### Puis-je archiver/supprimer un topic ?

**Non recommandé.**

Friday envoie des messages vers les 5 topics. Supprimer un topic causera des erreurs dans les logs bot.

Si vous ne voulez JAMAIS voir un topic → **Mute permanent** au lieu de supprimer.

---

## 🔗 Ressources Additionnelles

- [Setup Guide](telegram-topics-setup.md) - Si besoin reconfiguration
- [Architecture Topics (addendum §11)](_docs/architecture-addendum-20260205.md#11-stratégie-de-notification--telegram-topics-architecture)
- [Commandes Telegram complètes (CLAUDE.md)](../CLAUDE.md#commandes-telegram-trust)
- [Decision Log - Rationale](DECISION_LOG.md#2026-02-05--stratégie-de-notification---telegram-topics-architecture)

---

## 🆘 Support

Besoin d'aide ? Posez la question directement à Friday dans le topic **💬 Chat & Proactive** :

```
"Friday, comment je fais pour muter un topic ?"
"Friday, pourquoi je ne vois pas les topics sur mobile ?"
"Friday, rappelle-moi les commandes disponibles"
```

---

**Profitez de Friday 2.0 !** 🚀
