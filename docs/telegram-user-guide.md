# Friday 2.0 - Guide Utilisateur Telegram

**Date** : 2026-02-05
**Version** : 1.0
**Pour** : Mainteneur (utilisateur final)

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
/status          Dashboard temps réel (services, dernières actions)
/journal         20 dernières actions chronologiques
/receipt <id>    Détail d'une action (-v pour sous-étapes)
/confiance       Accuracy par module/action
/stats           Métriques globales agrégées
/budget          Consommation API Claude du mois
```

**Flag `-v` (verbose)** : Ajoutez `-v` à toute commande pour plus de détails.
```
/confiance -v    Ajoute colonnes recommandation + alertes rétrogradation
/receipt abc -v  Affiche les sous-étapes détaillées
/journal -v      Ajoute input_summary et reasoning
```

**Exemple `/status`** :
```
Dashboard Friday 2.0

SERVICES
  PostgreSQL : OK
  Redis : OK
  Bot : OK (uptime 2j 14h)

5 DERNIERES ACTIONS
  email.classify - auto (95%) - il y a 3min
  archiviste.ocr - auto (92%) - il y a 15min
  ...
```

**Exemple `/budget`** :
```
Budget API Claude - Fevrier 2026

Tokens input : 1,234,567
Tokens output : 456,789
Cout estime : 10.32 EUR
Budget mensuel : 45.00 EUR
Utilisation : 22.9%
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
🤖 Friday : "Bonjour Mainteneur ! J'ai vérifié tes emails : 2 urgents détectés. Veux-tu les résumer ?"
👤 Toi : "Oui"
🤖 Friday : "Voici les résumés..."
```

**💡 Astuce** : La conversation est **continue** - Friday se souvient du contexte dans ce topic.

---

## 🌟 Commandes VIP & Urgence (Story 2.3)

### Gérer vos expéditeurs VIP

Friday peut détecter automatiquement les emails importants via le système VIP. Vous pouvez désigner manuellement des expéditeurs comme VIP pour recevoir des notifications prioritaires.

**Commandes disponibles :**

```
/vip add <email> <label>    Ajouter un expéditeur VIP
/vip list                    Lister tous les VIPs actifs
/vip remove <email>          Retirer un VIP (soft delete)
```

### Exemples d'usage

**Ajouter un VIP :**
```
/vip add doyen@univ-med.fr Doyen Faculté Médecine
```
→ Friday confirmera :
```
✅ VIP ajouté avec succès

Email (anonymisé) : [EMAIL_a1b2c3d4]
Label : Doyen Faculté Médecine
Source : Ajout manuel
```

**Lister vos VIPs :**
```
/vip list
```
→ Friday affichera :
```
📋 Liste des VIPs (3 total)

👤 Doyen Faculté Médecine
   Email : [EMAIL_a1b2c3d4]
   Emails reçus : 15 | Dernier : 2026-02-10

👤 Comptable SCM
   Email : [EMAIL_e5f6g7h8]
   Emails reçus : 42 | Dernier : 2026-02-11
```

**Retirer un VIP :**
```
/vip remove doyen@univ-med.fr
```

### Détection urgence automatique

Friday détecte automatiquement les emails urgents via un algorithme multi-facteurs :
- **Facteur VIP** : Expéditeur VIP (poids 0.5)
- **Facteur keywords** : Mots-clés urgence ("URGENT", "deadline", "avant demain", etc.)
- **Facteur deadline** : Patterns de deadline détectés

**Seuil urgence** : Score >= 0.6 → Email classé urgent

**Notifications :**
- Email VIP → Topic **Email & Communications**
- Email URGENT → Topic **Actions & Validations** (notification push)

### Confidentialité & Sécurité

- ✅ Emails VIP **anonymisés via Presidio** avant stockage (RGPD)
- ✅ Hash SHA256 utilisé pour lookup (pas d'accès PII)
- ✅ Seul le **Mainteneur** peut ajouter/retirer des VIPs

---

## 📬 Topic 2 : Email & Communications

### Rôle
Notifications automatiques liées à vos emails et communications.

### Ce que vous verrez ici

**Classifications automatiques (Story 2.2) :**

Friday classifie automatiquement vos emails en 8 catégories grâce à Claude Sonnet 4.5 :

```
📧 Email classifié

De : compta@urssaf.fr
Sujet : Cotisations SELARL Q4 2025
Catégorie : 💰 finance (92%)

📋 Reasoning : Expéditeur @urssaf.fr, mots-clés cotisations

#email #finance
```

**8 catégories disponibles :**

| Emoji | Catégorie | Description |
|-------|-----------|-------------|
| 🏥 | `medical` | Cabinet médical SELARL (patients, CPAM, planning) |
| 💰 | `finance` | Comptabilité, banques, impôts (5 périmètres) |
| 🎓 | `faculty` | Enseignement universitaire (étudiants, examens) |
| 🔬 | `research` | Recherche académique (thèses, publications) |
| 👤 | `personnel` | Vie personnelle (amis, achats, loisirs) |
| 🚨 | `urgent` | Action immédiate requise (VIP, deadline <24h) |
| 🗑️ | `spam` | Publicités commerciales, newsletters |
| ❓ | `unknown` | Emails inclassables ou ambigus |

**Cold start mode** : Les 10-20 premiers emails nécessitent **systématiquement** votre validation (mode calibrage). Ensuite, si accuracy >= 90%, Friday passe en mode automatique.

**Pièces jointes extraites (Story 2.4) :**

Friday extrait automatiquement les pièces jointes de vos emails et vous notifie dans ce topic. Chaque notification inclut un bouton pour consulter l'email original.

**Exemple avec 3 fichiers :**
```
📎 3 pièces jointes extraites

Email : Carrefour Drive - Facture commande
Taille totale : 2.45 Mo

Fichiers :
  • facture_202602.pdf (1.2 Mo)
  • bon_livraison.pdf (0.8 Mo)
  • photo_produit.jpg (0.45 Mo)

→ Stockées en zone transit (24h)

[View Email 📧]
```

**Exemple avec plus de 5 fichiers :**
```
📎 8 pièces jointes extraites

Email : URSSAF - Documents cotisations Q4
Taille totale : 12.3 Mo

Fichiers :
  • declaration_trimestre.pdf (2.1 Mo)
  • bordereau_paiement.pdf (1.8 Mo)
  • recapitulatif_charges.xlsx (3.2 Mo)
  • justificatifs_2025.zip (4.5 Mo)
  • notice_explicative.pdf (0.5 Mo)
  ... et 3 autre(s)

→ Stockées en zone transit (24h)

[View Email 📧]
```

**Sécurité & Validation :**
- ✅ **MIME types autorisés** : 18 types (PDF, Office, images, archives, texte)
- ✅ **Types bloqués** : 25+ types dangereux (exe, dll, bat, scripts...)
- ✅ **Taille max** : 25 Mo par fichier
- ✅ **Sanitization** : Noms de fichiers nettoyés (path traversal, command injection)

**Zone transit :**
Les fichiers sont stockés temporairement dans `/var/friday/transit/attachments/` pendant 24h. Après traitement par l'Archiviste (Epic 3), ils sont déplacés vers leur localisation finale (BeeStation/NAS) et la zone transit est automatiquement nettoyée (cleanup quotidien 03:05).

**Cas particuliers :**
- Si **0 fichiers** extraits (tous bloqués ou échec) → **Pas de notification**
- Si **échec extraction** → Logged dans Topic System & Alerts
- Si **fichier bloqué** (MIME/taille) → Visible uniquement dans logs détaillés

**Emails urgents :**
```
🚨 Email urgent détecté !
De : Université Paris
Sujet : Deadline mémoire M2
Échéance : 2026-02-15
```

### Corriger une classification erronée

Si Friday se trompe de catégorie, 2 méthodes :

**Méthode 1 : Via bouton [Correct]** (si trust=propose)

1. Cliquer `[Correct]` sur notification
2. Sélectionner bonne catégorie parmi 8 boutons
3. Friday enregistre la correction + détecte patterns automatiquement

**Méthode 2 : Commande `/correct`**

```
/correct email-abc123 finance

✅ Correction enregistrée
Email abc123 : medical → finance

Si ≥2 corrections similaires détectées, Friday proposera une règle automatique.
```

### Quand muter ce topic ?

**Mode Focus** : Vous travaillez sur votre thèse et ne voulez pas être distrait par les notifications email → **Mute 8h**

**Mode Vacances** : Vous ne consultez vos emails que manuellement → **Mute jusqu'à réactivation**

---

## 🤖 Topic 3 : Actions & Validations

### Rôle
Actions nécessitant **votre validation** (trust level = `propose`).

### Ce que vous verrez ici

**Inline buttons pour approbation (Story 1.10) :**
```
📝 Action en attente de validation

Module : email
Action : draft_reply
Input : Email de Sarah (demande info thèse)

Brouillon proposé :
"Bonjour Sarah, voici les informations demandées..."

[Approve] [Reject] [Correct]
```

**Comportement des boutons :**
- **Approve** : L'action est exécutée automatiquement, le message affiche "Approuvé"
- **Reject** : L'action est annulée, le message affiche "Rejeté"
- **Correct** : Friday vous demande la bonne réponse et enregistre une correction

Seul le Mainteneur (OWNER_USER_ID) peut interagir avec les boutons. Un clic sur un bouton déjà traité affiche "Action déjà traitée".

**Timeout configurable :**
Si `validation_timeout_hours` est défini dans `config/telegram.yaml`, les actions non traitées expirent automatiquement après le délai configuré.

**Corrections email classification (Story 2.2) :**

Lorsque vous cliquez `[Correct]` sur une classification email, Friday affiche un clavier inline avec les 8 catégories :

```
📝 Correction classification email

Receipt : `abc12345`
Classification actuelle : → medical (0.92)

**Quelle est la bonne catégorie ?**

[🏥 Medical] [💰 Finance]
[🎓 Faculty] [🔬 Research]
[👤 Personnel] [🚨 Urgent]
[🗑️ Spam] [❓ Unknown]
```

Après sélection :

```
✅ Correction enregistrée

Receipt : `abc12345`
Catégorie originale : medical
Nouvelle catégorie : 💰 finance

Friday apprendra de cette correction lors du pattern detection nightly.
```

**Pattern detection automatique :**

Si ≥2 corrections identiques sont détectées, Friday propose une règle :

```
🤖 Règle proposée (pattern détecté)

Module : email.classify
Conditions : from @urssaf.fr
Output : category = finance
Occurrences : 3 corrections similaires

[Approve] [Reject]
```

**Trust level changes :**
```
Trust level mis à jour
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
Erreur : Anthropic API rate limit exceeded
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
