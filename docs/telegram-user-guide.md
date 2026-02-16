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
Alerte RAM
Utilisation : 87% (42 Go / 48 Go)
Services actifs : Whisper, Kokoro, Surya
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

## 📝 Brouillons Réponse Email (Story 2.5)

### Qu'est-ce que c'est ?

Friday génère automatiquement des brouillons de réponse email en apprenant votre style au fil du temps (few-shot learning).

**Workflow :**
```
Email reçu → Classification → Brouillon généré →
Topic Actions (inline buttons) → [Approve] → Email envoyé
```

---

### Commande `/draft`

**Usage :** Générer manuellement un brouillon pour un email reçu.

```
/draft <email_id>
```

**Exemple :**
```
User:
/draft f47ac10b-58cc-4372-a567-0e02b2c3d479

Friday:
⏳ Génération brouillon en cours...

Email: Question about appointment
Expéditeur: john@example.com

Vous recevrez une notification dans le topic Actions dès que le brouillon sera prêt.
```

**Trouver email_id :**
- Notifications emails (topic Email) incluent l'ID
- Ou commande `/recent_emails` (Story future)

---

### Notification Brouillon (Topic Actions)

Quand un brouillon est prêt, vous recevez une notification dans le **Topic 🤖 Actions & Validations** :

```
📝 Brouillon réponse email prêt

De: john.doe@example.com
Sujet: Re: Question about appointment

Brouillon :
---
Bonjour,

Oui, vous pouvez reprogrammer votre rendez-vous pour la semaine prochaine.
Merci de me confirmer vos disponibilités.

Cordialement,
Dr. [NOM]
---

Voulez-vous envoyer ce brouillon ?

[✅ Approve] [❌ Reject] [✏️ Edit]
```

---

### Actions Inline Buttons

| Bouton | Action | Résultat |
|--------|--------|----------|
| **✅ Approve** | Envoie l'email immédiatement | ✅ Email envoyé + notification topic Email |
| **❌ Reject** | Annule l'envoi | ❌ Brouillon rejeté (message édité) |
| **✏️ Edit** | Modifier avant envoi | ⚠️ Fonctionnalité à venir (Story 2.5.1) |

---

### Apprentissage Automatique (Few-Shot Learning)

**Comment ça marche ?**

1. **Day 1** : Friday utilise un style formel standard français
2. **Après 3-5 emails approuvés** : Friday apprend votre style
3. **Après 10+ emails** : Friday écrit exactement comme vous

**Caractéristiques apprises :**
- Formules de politesse ("Cordialement" vs "Bien à vous")
- Niveau de formalité (tutoiement ou non)
- Structure email (salutation, corps, signature)
- Verbosité (concis vs détaillé)

**Stockage :** Chaque brouillon approuvé est stocké dans `core.writing_examples` pour améliorer les brouillons futurs.

---

### Sécurité & RGPD

✅ **Anonymisation Presidio** : Toutes les données sensibles (noms, emails, termes médicaux) sont anonymisées AVANT envoi à Claude cloud.

✅ **Validation obligatoire** : Friday ne vous jamais envoyer un email automatiquement, même après 100% de brouillons parfaits. Vous devez TOUJOURS cliquer [Approve].

✅ **Fail-explicit** : Si Presidio est indisponible, Friday refuse de générer des brouillons plutôt que de risquer une fuite RGPD.

---

### Exemples d'Usage

**Scénario 1 : Email professionnel standard**

```
Email reçu: "Bonjour Dr. [NOM], pouvez-vous me confirmer mon RDV du 15 février ?"

Brouillon Friday:
"Bonjour,
Je confirme votre rendez-vous du 15 février à 14h30.
Cordialement,
Dr. [NOM]"

[✅ Approve] → Email envoyé en 2 secondes
```

**Scénario 2 : Email académique**

```
Email reçu: "Dear Professor [NOM], I would like to discuss my thesis progress..."

Brouillon Friday:
"Dear [Student Name],
I am available this Thursday at 3pm in my office.
Best regards,
Prof. [NOM]"

[✅ Approve] → Email envoyé
```

**Scénario 3 : Email urgent**

```
Email reçu: "URGENT: Patient needs immediate consultation"

Brouillon Friday:
"Je me rends disponible immédiatement. Merci de me contacter au XXX."

[✅ Approve] → Réponse envoyée en quelques secondes
```

---

### Configuration Style (optionnel)

**Par défaut** : Formel, vouvoiement, concis

**Personnaliser** (via base de données `core.user_settings.preferences`) :

```json
{
  "writing_style": {
    "tone": "informal",        // "formal" ou "informal"
    "tutoiement": true,        // true ou false
    "verbosity": "detailed"    // "concise" ou "detailed"
  }
}
```

**Commande future** : `/configure_writing_style` (Story 2.5.2)

---

### Troubleshooting

**❌ Brouillon incohérent / style incorrect**

**Causes :**
- Pas assez d'exemples (< 3 emails approuvés) → Continuez à approuver des brouillons
- Type email différent → Friday apprend séparément style professionnel vs médical vs académique

**❌ Bouton [Approve] ne fonctionne pas**

**Causes :**
- Vous n'êtes pas le Mainteneur → Seul OWNER_USER_ID peut approuver
- Receipt déjà traité → Vérifiez si message édité dit "✅ Brouillon approuvé"

**❌ Email non envoyé après Approve**

**Checklist :**
1. Verifier logs : `docker compose logs friday-bot | grep smtp_send`
2. Verifier imap-fetcher operationnel : `docker compose ps friday-imap-fetcher` [D25]
3. Verifier credentials IMAP/SMTP dans `.env.email.enc`

---

### Metriques & Budget

**Cout par brouillon** : ~$0.03-0.05 (Claude Sonnet 4.5)

**Budget mensuel estime** (50 brouillons/mois) : ~$2-3

**Latence** : <10s (generation brouillon + notification Telegram)

---

## Envoi Emails Approuves (Story 2.6)

Friday envoie automatiquement les emails que vous avez approuves via inline buttons Telegram, avec notifications completes et historique consultable.

### Workflow Complet : Brouillon -> Validation -> Envoi

**Etape 1 : Brouillon pret** (Story 2.5)
- Email recu -> Classification -> Brouillon genere
- Notification topic **Actions & Validations** avec inline buttons

**Etape 2 : Validation Mainteneur** (Story 2.6)
- Clic sur bouton **[Approve]**
- Receipt status : `pending` -> `approved`

**Etape 3 : Envoi SMTP direct** (Story 2.6) [D25 : aiosmtplib remplace EmailEngine]
- Friday envoie email via aiosmtplib (adaptateur `adapters/email.py`)
- Compte IMAP/SMTP automatiquement selectionne (professional/medical/academic/personal)
- Threading correct : `In-Reply-To` + `References` (conversation coherente)
- **Retry automatique** : 3 tentatives si echec (backoff exponentiel 1s, 2s)
- Latence : **<5s** entre clic Approve -> confirmation

**Étape 4 : Confirmation** (Story 2.6)
- Receipt status : `approved` → `executed`
- **Notification topic Email & Communications** :

```
✅ Email envoyé avec succès

Destinataire: [NAME_42]@[DOMAIN_13]
Sujet: Re: [SUBJECT_88]

📨 Compte: professional
⏱️  Envoyé le: 2026-02-11 14:30:00

[📋 Voir dans /journal]
```

- Writing example stocké automatiquement (amélioration future few-shot)

**Étape 5 : Historique** (Story 2.6)
- Consultable via `/journal` et `/receipt [id]`

### Notifications Telegram

#### ✅ Confirmation Envoi (Topic Email)

**Quand** : Email envoyé avec succès via EmailEngine

**Contenu** :
- Destinataire anonymisé (via Presidio, RGPD)
- Sujet anonymisé
- Compte IMAP utilisé
- Timestamp envoi
- Inline button `[📋 Voir dans /journal]` → détail complet

**Anonymisation** : Aucune PII en clair dans notification (protection RGPD même si historique Telegram fuite)

#### ⚠️ Échec Envoi (Topic System)

**Quand** : EmailEngine échoue après 3 tentatives

**Contenu** :

```
⚠️ Échec envoi email

Destinataire: [NAME_1]@[DOMAIN_1]
Erreur: EmailEngine send failed: 500 - Internal Server Error

Action requise: Vérifier EmailEngine + compte IMAP
Receipt ID: uuid-123
```

**Actions** :
1. Vérifier EmailEngine opérationnel : `docker compose ps | grep emailengine`
2. Consulter logs : `docker compose logs emailengine`
3. Vérifier compte IMAP configuré dans EmailEngine dashboard

### Commandes Consultation Historique

#### `/journal` — 20 dernières actions

**Usage** :
```
/journal              # Toutes actions (emails, classification, archiviste, etc.)
/journal email        # Filtrer uniquement emails
/journal -v           # Mode verbose (affiche input_summary)
```

**Exemple sortie** :

```
**Journal** (20 dernières actions)

`2026-02-11 14:30` ✅ Email envoyé → [NAME_42]@[DOMAIN_13] 95.0%
`2026-02-11 14:25` ⏳ email.classify ⏳ 92.0%
`2026-02-11 14:20` ✅ Email envoyé → [NAME_7]@[DOMAIN_2] 94.0%
```

**Format emails** : Affichage spécial avec recipient anonymisé (pour lisibilité vs format générique `module.action`)

#### `/journal email` — Filtrer emails uniquement

**Usage** : `/journal email` → Affiche uniquement actions `module='email'`

**Utile pour** : Consulter rapidement historique envois sans autres actions (classification, archiviste, etc.)

#### `/receipt [id]` — Détail complet action

**Usage** :
```
/receipt <receipt_id>         # Détail complet receipt
/receipt <receipt_id> -v      # Mode verbose (payload JSON complet)
```

**Exemple sortie emails envoyés** :

```
**Receipt** `uuid-123...`

Module: `email.draft_reply`
Trust: propose
Status: ✅ executed
Confidence: 94.0%
Input: Email de john@example.com...
Output: [NAME_42]@[DOMAIN_13]
Reasoning: Réponse générée par Claude Sonnet 4.5...
Created: 2026-02-11 14:25:00

**Email Details**
Compte IMAP: `account_professional`
Type: professional
Message ID: `<sent-456@example.com>...`

Brouillon (extrait):
---
Bonjour,

Voici ma réponse à votre question...

Cordialement,
Dr. [NOM]
---
```

**Mode verbose (`-v`)** : Affiche JSON payload complet (draft_body, account_id, email_type, message_id, timestamps)

### Troubleshooting Envoi Emails

#### Email non envoye apres clic [Approve]

**Checklist** :

1. **Verifier imap-fetcher operationnel** [D25 : remplace EmailEngine] :
   ```bash
   docker compose ps | grep friday-imap-fetcher
   # Doit afficher "Up" (healthy)
   ```

2. **Consulter logs imap-fetcher** :
   ```bash
   docker compose logs friday-imap-fetcher --tail=50
   # Chercher erreurs SMTP, timeout, auth failed
   ```

3. **Verifier credentials IMAP/SMTP** :
   - Verifier `.env.email.enc` (dechiffrer via `sops -d`)
   - Verifier App Passwords valides

4. **Consulter receipt status** :
   ```
   /receipt <receipt_id>
   # Si status='failed' → Voir erreur dans logs
   ```

5. **Vérifier notification System** :
   - Topic **System & Alerts** doit contenir alerte échec avec détails erreur

#### ⚠️ Notification "Échec envoi email" reçue

**Causes fréquentes** :

| Erreur | Cause | Solution |
|--------|-------|----------|
| `SMTP connection refused` | Serveur SMTP inaccessible | Verifier config SMTP dans `.env.email.enc` [D25] |
| `Account not found` | Compte IMAP non configure | Ajouter variables `IMAP_ACCOUNT_*` dans `.env.email.enc` |
| `Authentication failed` | Credentials IMAP/SMTP invalides | Regenerer App Password et mettre a jour `.env.email.enc` |
| `Connection timeout` | Reseau SMTP inaccessible | Verifier firewall + DNS |

**Retry** : Friday retente automatiquement 3 fois (1s, 2s backoff). Si echec persiste apres 3 tentatives -> alerte System.

#### 📋 Historique `/journal` vide ou incomplet

**Causes** :
- Aucun email envoyé récemment → Normal si pas d'activité
- Receipt non créé → Vérifier Trust Layer fonctionnel (Story 1.6)

**Vérification** :
```sql
-- Via psql (administrateur uniquement)
SELECT id, module, action_type, status, created_at
FROM core.action_receipts
WHERE module='email'
ORDER BY created_at DESC LIMIT 20;
```

### Sécurité & RGPD

**Anonymisation systématique** :
- ✅ Recipient et Subject **toujours anonymisés** dans notifications Telegram
- ✅ Mapping Presidio éphémère (mémoire uniquement, jamais persisté)
- ✅ Payload receipt chiffré pgcrypto (colonnes sensibles)

**Protection données** :
- Historique Telegram cloud → Notifications anonymisées (protection si fuite)
- Logs structurés JSON → Pas de PII en clair
- Database PostgreSQL → Chiffrement pgcrypto colonnes sensibles

### Métriques Story 2.6

**Latence** : <5s (clic Approve → confirmation envoi)

**Fiabilité** :
- Retry 3 tentatives automatiques
- Taux de succès cible : >99% (si EmailEngine healthy)

**Cout** : $0 (pas d'appel LLM, envoi SMTP direct gratuit) [D25 : plus de licence EmailEngine]

**Budget mensuel total** (avec Story 2.5 brouillons) : ~$2-3/mois (50 emails)

**Commande** : `/budget` pour voir consommation API temps réel (Story 1.11)

---

## Archiviste - Classification & Arborescence (Story 3.2)

### Commande `/arbo`

Gestion de l'arborescence des documents Friday.

**Commandes disponibles :**

```
/arbo                          Afficher l'arborescence (ASCII tree)
/arbo stats                    Statistiques documents par categorie
/arbo add <category> <path>    Ajouter dossier
/arbo remove <path>            Supprimer dossier
```

**Exemple `/arbo` :**
```
Arborescence Friday
C:/Users/lopez/BeeStation/Friday/Archives

├── pro/ (Documents professionnels cabinet medical)
│   ├── patients/ (Dossiers patients anonymises)
│   └── administratif/ (Documents administratifs cabinet)
├── finance/ (Documents financiers - 5 perimetres OFFICIELS)
│   ├── selarl/ (Cabinet medical SELARL)
│   ├── scm/ (SCM Societe Civile de Moyens)
│   ├── sci_ravas/ (SCI Ravas)
│   ├── sci_malbosc/ (SCI Malbosc)
│   └── personal/ (Finances personnelles)
├── universite/ (Documents universitaires enseignement)
│   ├── theses/ (Encadrement theses doctorales)
│   └── cours/ (Supports de cours)
├── recherche/ (Documents recherche scientifique)
│   ├── publications/ (Articles, communications scientifiques)
│   └── projets/ (Dossiers projets de recherche)
└── perso/ (Documents personnels)
    ├── famille/ (Documents famille)
    ├── voyages/ (Documents voyages)
    └── divers/ (Documents personnels divers)
```

**Exemple `/arbo stats` :**
```
Statistiques classification

Total documents : 156
Classifies : 142
Non classifies : 14

  finance/selarl : 45
  pro : 32
  finance/scm : 18
  universite : 15
  recherche : 12
  perso : 10
  finance/personal : 6
  finance/sci_ravas : 3
  finance/sci_malbosc : 1
```

### Protections

- **Owner-only** : Seul le Mainteneur peut executer `/arbo`
- **Perimetres finance proteges** : Impossible de modifier ou supprimer les 5 perimetres racine (selarl, scm, sci_ravas, sci_malbosc, personal)
- **Categories racine protegees** : Impossible de supprimer pro, finance, universite, recherche, perso

### Notifications classification

Quand un document est classe (trust=propose), notification dans **Topic Actions & Validations** :

```
Document classe (validation requise)

Document : doc-123
Categorie : Finance > SELARL
Destination : finance/selarl
Confiance : 94%

[Approuver] [Corriger] [Rejeter]
```

**Boutons :**
- **Approuver** : Classification acceptee, document deplace
- **Corriger** : Affiche liste categories, si finance alors sous-menu perimetres
- **Rejeter** : Classification rejetee, document reste en transit

---

## Archiviste - Recherche Semantique (Story 3.3)

### Commande `/search`

Recherche semantique dans tous vos documents indexes via pgvector (embeddings Voyage AI voyage-4-large, 1024 dimensions).

**Commandes disponibles :**

```
/search <query>                          Recherche semantique (top-5)
/search <query> --category=finance       Filtrer par categorie
/search <query> --after=2026-01-01       Documents apres date
/search <query> --before=2026-12-31      Documents avant date
```

**Filtres combinables :**
```
/search facture plombier --category=finance --after=2026-01-01
/search diabete SGLT2 --category=recherche
/search contrat assurance --category=perso --before=2026-06-30
```

### Exemple `/search` :

```
/search facture plombier 2026

Resultats pour: facture plombier 2026

3 documents trouves

1. 2026-01-15_Facture_Plombier_350EUR.pdf
   Score: 95%
   Categorie: finance
   Facture plombier intervention urgente fuite tuyau cabinet...

2. 2025-12-01_Facture_Plombier_Maison.pdf
   Score: 87%
   Categorie: perso
   Facture plombier intervention maison personnelle fuite...

3. 2026-02-05_Facture_Materiel_Medical.pdf
   Score: 72%
   Categorie: pro
   Facture equipement medical tensiometre stethoscope...

[Ouvrir] [Details]
```

### Boutons inline

| Bouton | Action |
|--------|--------|
| **Ouvrir** | Ouvre le fichier (lien `file:///` vers chemin local) |
| **Details** | Affiche metadonnees completes (nom, chemin, categorie, sous-categorie, confiance, date creation) |

### Categories disponibles pour filtre `--category`

| Categorie | Description |
|-----------|-------------|
| `pro` | Documents professionnels cabinet medical |
| `finance` | Documents financiers (5 perimetres) |
| `universite` | Documents universitaires enseignement |
| `recherche` | Documents recherche scientifique |
| `perso` | Documents personnels |

### Desktop Search (D23)

En complement de la recherche pgvector, Friday peut aussi chercher dans vos fichiers locaux via Claude Code CLI sur votre PC :

- **Phase 1** : Claude CLI sur PC Mainteneur (disponibilite quand PC allume)
- **Phase 2** : Migration vers NAS Synology DS725+ (disponibilite 24/7)

Le Desktop Search est automatiquement utilise quand le PC est disponible. Si le PC est eteint, la recherche pgvector seule est utilisee (fallback transparent).

### Performance

- Latence recherche : < 2s pour top-5 sur 100k documents (AC6)
- Latence embedding : < 1s par document
- Index HNSW pgvector 0.8.0 (m=16, ef_construction=64)

### Securite

- Anonymisation Presidio AVANT envoi query a Voyage AI (RGPD)
- Trust level : `auto` (recherche = lecture seule, pas de modification)
- Resultats filtres par permissions utilisateur

---

## 📅 Google Calendar Sync (Story 7.2)

### Qu'est-ce que c'est ?

Friday synchronise automatiquement les événements entre votre base de connaissances PostgreSQL et **3 calendriers Google Calendar** correspondant à vos casquettes professionnelles :

| Casquette | Calendrier | Couleur |
|-----------|-----------|---------|
| 🩺 Médecin | Calendrier principal (primary) | Rouge |
| 👨‍🏫 Enseignant | Calendrier Enseignant | Vert |
| 🔬 Chercheur | Calendrier Chercheur | Bleu |

**Synchronisation bidirectionnelle** : Modifications dans Friday → Google Calendar et vice-versa (last-write-wins en cas de conflit).

**Sync automatique** : Toutes les 30 minutes via daemon + backup quotidien 06:00 via n8n.

---

### Commandes disponibles

#### `/calendar sync` — Forcer synchronisation manuelle

**Usage** :
```
/calendar sync
```

**Réponse** :
```
⏳ Synchronisation Google Calendar en cours...

✅ Synchronisation terminée
Événements créés : 2
Événements mis à jour : 1
Prochaine sync automatique : 14:30
```

**Utilité** : Forcer la synchronisation avant une consultation urgente de votre calendrier Google.

---

### Notifications Telegram

#### ✅ Événement ajouté à Google Calendar (Topic Actions)

Après ajout d'un événement dans Friday, notification dans **Topic 🤖 Actions & Validations** :

```
✅ Événement ajouté à Google Calendar

Titre : Consultation cardio
📆 Date : Mardi 17 février 2026, 14h00-15h00
📍 Lieu : Cabinet médical
🎭 Casquette : Médecin

🔗 Voir dans Google Calendar
```

#### 🔄 Modification détectée (Topic Email)

Quand vous modifiez un événement dans Google Calendar web, notification dans **Topic 📬 Email & Communications** :

```
🔄 Événement modifié dans Google Calendar

Modifications détectées :

Heure :
❌ Mardi 18 février 2026, 14h00-15h00
✅ Mardi 18 février 2026, 15h00-16h00

Lieu :
❌ Salle A
✅ Salle B

🔗 Voir dans Google Calendar
```

---

### Troubleshooting

**❌ Sync échoue après 3 tentatives**

Alerte dans **Topic 🚨 System & Alerts** :
```
🚨 Google Calendar sync: 3 échecs consécutifs
Dernière erreur: 429 Rate Limit Exceeded
Vérifiez les credentials OAuth2 et la config.
```

**Solutions** :
1. Vérifier OAuth2 token valide : `docker logs friday-calendar-sync`
2. Vérifier quota Google Calendar API : [Google Cloud Console](https://console.cloud.google.com/)
3. Réduire fréquence sync : Modifier `sync_interval_minutes` dans `config/calendar_config.yaml`

---

## 🗓️ Multi-casquettes & Conflits Calendrier (Story 7.3)

### Qu'est-ce que c'est ?

Friday gère vos **3 rôles professionnels** (médecin, enseignant, chercheur) et détecte automatiquement les **conflits d'agenda** entre casquettes.

**3 casquettes** :
- 🩺 **Médecin** : Consultations, gardes, formations médicales
- 🎓 **Enseignant** : Cours, TD, TP, examens, réunions pédagogiques
- 🔬 **Chercheur** : Conférences, publications, réunions labo

**Auto-détection contexte** (5 règles priorité) :
1. **Manuel** (max) : Vous avez défini via `/casquette`
2. **Event** : Événement en cours dans calendrier
3. **Time** : Tranche horaire typique (14h = médecin)
4. **Last Event** : Dernier événement <2h
5. **Default** : Casquette par défaut (médecin)

**Influence classification** : Le contexte actuel crée un bias **LÉGER** sur classification email/événements.
- Email @chu.fr + contexte=medecin → favorise catégorie "pro"
- "Réunion équipe" + contexte=enseignant → favorise casquette=enseignant

---

### Commande `/casquette`

Changer manuellement votre casquette actuelle (override toutes autres règles).

**Usage** :
```
/casquette
```

**Exemple** :
```
User : /casquette

Friday : Sélectionnez votre casquette actuelle :

[🩺 Médecin] [🎓 Enseignant] [🔬 Chercheur]
```

**Après sélection (ex: Enseignant)** :
```
✅ Casquette changée : Enseignant

Vos emails et événements seront désormais biaisés vers l'enseignement.
Pour revenir à l'auto-détection, utilisez à nouveau /casquette.
```

**Effet** :
- Contexte reste `enseignant` jusqu'à prochain changement manuel
- Emails @univ.fr → favorise catégorie "universite"
- Événements ambigus → favorise casquette "enseignant"

---

### Commande `/conflits`

Afficher les conflits calendrier non résolus (7 jours par défaut).

**Usage** :
```
/conflits           # 7 prochains jours
/conflits 14j       # 14 prochains jours
/conflits 30j       # 30 prochains jours
```

**Exemple** :
```
User : /conflits

Friday :
⚠️ 2 conflits calendrier détectés dans les 7 prochains jours

1. 🩺 Consultation Dr Dupont ↔ 🎓 Cours L2 Anatomie
   📅 Demain 14h30-15h00 | Chevauchement : 30 minutes
   📍 Cabinet médical ↔ Amphi B

   [Annuler cours] [Reporter consultation] [Accepter les 2]

2. 🔬 Séminaire labo ↔ 🎓 Réunion péda
   📅 Vendredi 16h00-17h30 | Chevauchement : 30 minutes
   📍 Labo 301 ↔ Salle B203

   [Annuler réunion] [Reporter séminaire] [Accepter les 2]

Utilisez les boutons pour résoudre chaque conflit.
```

**Aucun conflit** :
```
✅ Aucun conflit calendrier dans les 7 prochains jours
```

---

### Résolution Conflits - Boutons Inline

#### 1. Annuler événement
```
User : Clique [Annuler cours]

Friday : ✅ Événement annulé : Cours L2 Anatomie
         Conflit résolu. L'autre événement est conservé.
```

**Effet** :
- Événement supprimé (marqué `deleted=TRUE`)
- Conflit marqué `resolved=TRUE` avec `resolution_type='cancel'`

#### 2. Reporter événement (dialogue multi-étapes)
```
User : Clique [Reporter consultation]

Friday : 📅 Nouvelle date/heure pour "Consultation Dr Dupont" ?
         (Format libre : "demain 16h", "vendredi 10h30", "2026-03-15 14h")

User : demain 16h

Friday : ✅ "Consultation Dr Dupont" reportée demain 16h
         Conflit résolu. L'autre événement est conservé.
```

**État machine** : Redis `conflict:reschedule:{user_id}` (TTL 15 min)

**Formats date acceptés** :
- Relatifs : `demain`, `après-demain`, `lundi prochain`
- Absolus : `2026-03-15`, `15 mars`
- Heures : `14h`, `14h30`, `14:30`

#### 3. Accepter les 2 événements
```
User : Clique [Accepter les 2]

Friday : ✅ Conflit accepté : les 2 événements sont conservés
         (Consultation Dr Dupont + Cours L2 Anatomie)

         Vous avez confirmé pouvoir gérer ce multi-casquette.
```

**Effet** :
- Les 2 événements restent inchangés
- Conflit marqué `resolved=TRUE` avec `resolution_type='accept'`
- Plus de notifications pour ce conflit

---

### Notifications Automatiques (Heartbeat)

Friday vérifie les conflits **toutes les 2h (08h-22h)** sur les **7 prochains jours**.

**Notification Topic 🤖 Actions & Validations** :
```
⚠️ 1 conflit calendrier détecté dans les 7 prochains jours

📅 Demain 14h30 : 🩺 Consultation Dr Dupont ↔ 🎓 Cours L2 Anatomie
   Chevauchement : 30 minutes

Utilisez /conflits pour voir les détails et résoudre.
```

**Quiet hours** : Skip notifications 22h-08h (configuré dans Heartbeat Engine)

**Fréquence** :
- Check toutes les 2h pendant journée
- Notification 1x par conflit (pas de spam)
- Re-notification si conflit non résolu après 24h

---

### Briefing Multi-casquettes

Le briefing quotidien (08h) groupe vos événements par casquette.

**Exemple `/briefing` (appelé automatiquement 08h)** :
```
📅 Briefing du 2026-02-17 (Lundi)

🩺 MÉDECIN (2 événements)
  10h00-10h30 : Consultation Dr Martin (Cabinet)
  14h30-18h00 : Garde CHU (CHU Toulouse)

🎓 ENSEIGNANT (1 événement)
  14h00-16h00 : Cours L2 Anatomie (Amphi B)
    ⚠️ Conflit avec Garde CHU (14h30-18h00) - Chevauchement : 1h30

🔬 CHERCHEUR (1 événement)
  16h30-18h00 : Séminaire recherche (Labo 301)

Total : 4 événements · 1 conflit à résoudre
```

**Ordre** : Chronologique global (pas par casquette)

---

### Métriques & Observability

**Métriques collectées** :
- `context_updates_total` : Total changements contexte
- `context_updates_by_source` : Changements par source (manual, event, time, etc.)
- `conflicts_detected_total` : Total conflits détectés
- `conflicts_resolved_total` : Conflits résolus (par type : cancel/reschedule/accept)
- `classification_with_context_bias` : Classifications avec contexte vs sans

**Logs structurés** (JSON) :
```json
{
  "timestamp": "2026-02-17T14:30:00Z",
  "service": "context-manager",
  "level": "INFO",
  "message": "Context updated",
  "context": {
    "old_casquette": "medecin",
    "new_casquette": "enseignant",
    "source": "event",
    "event_id": "abc-123"
  }
}
```

---

### Documentation Complète

**Guide technique détaillé** : [docs/multi-casquettes-conflicts.md](../multi-casquettes-conflicts.md) (~650 lignes)
- Architecture tables PostgreSQL
- Allen's interval algebra (13 relations temporelles)
- Pipeline auto-détection contexte
- Algorithme détection conflits
- Influence contexte sur classification
- Tests (125 tests : unit, intégration, E2E)
- Troubleshooting

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
