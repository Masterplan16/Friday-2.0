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
Dr. Antonio Lopez
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
Email reçu: "Bonjour Dr. Lopez, pouvez-vous me confirmer mon RDV du 15 février ?"

Brouillon Friday:
"Bonjour,
Je confirme votre rendez-vous du 15 février à 14h30.
Cordialement,
Dr. Antonio Lopez"

[✅ Approve] → Email envoyé en 2 secondes
```

**Scénario 2 : Email académique**

```
Email reçu: "Dear Professor Lopez, I would like to discuss my thesis progress..."

Brouillon Friday:
"Dear [Student Name],
I am available this Thursday at 3pm in my office.
Best regards,
Prof. Antonio Lopez"

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

### Métriques & Budget

**Coût par brouillon** : ~$0.03-0.05 (Claude Sonnet 4.5)

**Budget mensuel estimé** (50 brouillons/mois) : ~$2-3

**Latence** : <10s (génération brouillon + notification Telegram)

**Commande** : `/budget` pour voir consommation API temps réel (Story 1.11)

---

---

## Archiviste OCR & Renommage (Story 3.1)

### Qu'est-ce que c'est ?

Friday scanne automatiquement vos documents (PDF, images) via OCR Surya, extrait les metadonnees (date, type, emetteur, montant) via Claude, et renomme les fichiers selon une convention standardisee.

**Workflow :**
```
Document recu -> OCR Surya -> Presidio anonymisation ->
Claude extraction metadata -> Renommage intelligent ->
Topic Actions (inline buttons) -> [Approve] -> Fichier renomme
```

### Convention de Nommage

**Format :** `YYYY-MM-DD_Type_Emetteur_MontantEUR.ext`

**Exemples :**
- `2026-02-08_Facture_Laboratoire-Cerba_145EUR.pdf`
- `2026-01-15_Courrier_ARS_0EUR.pdf`
- `2025-12-20_Garantie_Boulanger_599EUR.pdf`

### Notifications Telegram

| Topic | Contenu |
|-------|---------|
| **Actions** | Proposition de renommage avec [Approve] [Reject] [Correct] |
| **Metrics** | Document traite (confidence, latence, type) |
| **System** | Erreur OCR Surya, timeout >45s, crash Presidio |

### Trust Layer

- **extract_metadata** : `propose` (Day 1) — validation Telegram requise
- **rename** : `propose` (Day 1) — validation Telegram requise
- **ocr** : `auto` — pas de decision, extraction pure

### Performance

- Latence totale : <45s (seuil, alerte si >35s)
- OCR 1 page : ~5-15s CPU
- OCR 3-5 pages : ~20-30s CPU
- Extraction metadata Claude : ~2-5s

### Securite RGPD

Le texte OCR est **anonymise via Presidio** AVANT tout appel a Claude. Si Presidio est indisponible, le pipeline refuse de traiter le document (fail-explicit). Aucune donnee personnelle n'est envoyee a l'API Claude.

---

**Note :** Inserer ces sections dans telegram-user-guide.md apres les topics, avant la section FAQ.
