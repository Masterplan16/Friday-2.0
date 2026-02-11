# Email Draft Reply - Few-Shot Learning

Génération automatique de brouillons de réponse email avec apprentissage du style rédactionnel via few-shot learning.

**Story:** 2.5 Brouillon Réponse Email
**FR:** FR4 (brouillons validation), FR129 (style appris), FR104 (envoi approuvés)
**NFR:** NFR1 (<30s latence), NFR6 (anonymisation 100%), NFR7 (fail-explicit)

---

## Table des Matières

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Workflow Complet](#workflow-complet)
4. [Few-Shot Learning](#few-shot-learning)
5. [Configuration](#configuration)
6. [Usage Telegram](#usage-telegram)
7. [API & Modules](#api--modules)
8. [Troubleshooting](#troubleshooting)

---

## Vue d'ensemble

Friday génère automatiquement des brouillons de réponse email en utilisant Claude Sonnet 4.5 avec apprentissage progressif du style rédactionnel via few-shot learning.

### Caractéristiques

- ✅ **Génération Claude Sonnet 4.5** : Brouillons contextuels pertinents
- ✅ **Few-Shot Learning** : Apprend le style au fil des emails envoyés
- ✅ **Anonymisation RGPD** : Presidio avant appel LLM cloud
- ✅ **Validation obligatoire** : Trust=propose, jamais d'envoi automatique
- ✅ **Threading email** : Réponses dans bonne conversation
- ✅ **Telegram inline buttons** : Approve/Reject/Edit en un clic

### Flux utilisateur

```
Email reçu → Classification → Génération brouillon →
Notification Telegram (topic Actions) → [Approve][Reject][Edit] →
Email envoyé + Stockage exemple few-shot
```

---

## Architecture

### Composants

| Composant | Fichier | Rôle |
|-----------|---------|------|
| **Agent principal** | `agents/src/agents/email/draft_reply.py` | Orchestration pipeline @friday_action |
| **Prompts LLM** | `agents/src/agents/email/prompts_draft_reply.py` | Construction prompts few-shot |
| **EmailEngine Client** | `services/email_processor/emailengine_client.py` | Envoi emails SMTP |
| **Bot Notifications** | `bot/handlers/draft_reply_notifications.py` | Notifications Telegram |
| **Action Executor** | `bot/action_executor_draft_reply.py` | Exécution après Approve |
| **Commande /draft** | `bot/handlers/draft_commands.py` | Génération manuelle |

### Tables PostgreSQL

**`core.writing_examples`** (Migration 032)

```sql
CREATE TABLE core.writing_examples (
    id UUID PRIMARY KEY,
    email_type VARCHAR(50) NOT NULL,  -- professional/personal/medical/academic
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_by VARCHAR(100) DEFAULT 'Mainteneur',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (email_type IN ('professional', 'personal', 'medical', 'academic'))
);

CREATE INDEX idx_writing_examples_email_type_sent_by
ON core.writing_examples (email_type, sent_by, created_at DESC);
```

### LLM Parameters

| Paramètre | Valeur | Rationale |
|-----------|--------|-----------|
| **Model** | `claude-sonnet-4-5-20250929` | Unique modèle (D17) |
| **Temperature** | `0.7` | Créativité nécessaire vs 0.1 classification |
| **Max Tokens** | `2000` | Réponses emails longues possibles |
| **Cost** | ~$0.03-0.05 / brouillon | $3/$15 per 1M tokens input/output |

---

## Workflow Complet

### Pipeline Génération Brouillon

```python
# 1. Email reçu (consumer.py)
email_received → Redis Stream 'emails:received'

# 2. Classification email (si nécessaire)
category = await classify_email(email)  # professional/medical/academic/personal

# 3. Génération brouillon (draft_reply.py)
@friday_action(module="email", action="draft_reply", trust_default="propose")
async def draft_email_reply(email_id, email_data, db_pool):
    # 3a. Anonymisation Presidio (RGPD)
    email_anon = await presidio_anonymize(email_data['body'])

    # 3b. Load writing_examples (top 5, filtre email_type)
    examples = await load_writing_examples(db_pool, email_type='professional', limit=5)

    # 3c. Load correction_rules (module='email', scope='draft_reply')
    rules = await fetch_correction_rules(db_pool)

    # 3d. Build prompts (system + user)
    system, user = build_draft_reply_prompt(email_anon, email_type, rules, examples)

    # 3e. Call Claude Sonnet 4.5
    draft_anon = await call_claude(system, user, temp=0.7, max_tokens=2000)

    # 3f. Dé-anonymisation
    draft = await presidio_deanonymize(draft_anon)

    # 3g. Return ActionResult (trust=propose → notification Telegram)
    return ActionResult(payload={'draft_body': draft, 'email_original_id': email_id})

# 4. Notification Telegram (topic Actions)
await send_draft_ready_notification(bot, receipt_id, email_from_anon, subject_anon, draft_body)
# Message avec inline buttons [Approve][Reject][Edit]

# 5a. Si Approve → Envoi email + Stockage exemple
await send_email_via_emailengine(receipt_id, db_pool)
INSERT INTO core.writing_examples (email_type, subject, body) VALUES (...)

# 5b. Si Reject → Email non envoyé, feedback implicite enregistré
UPDATE core.action_receipts SET status='rejected'
```

### Threading Email Correct

```python
await emailengine_client.send_message(
    account_id="account_professional",
    recipient_email="john@example.com",
    subject="Re: Your question",
    body_text="Bonjour,\n\nVoici ma réponse...",
    in_reply_to="<original-msg-id@example.com>",  # CRITIQUE pour threading
    references=["<original-msg-id@example.com>"]   # Liste IDs conversation
)
```

---

## Few-Shot Learning

### Principe

Friday apprend le style rédactionnel en observant les brouillons approuvés et envoyés.

- **Day 1 (N=0)** : Style générique basé sur `core.user_settings.preferences.writing_style`
- **Après N brouillons envoyés** : Top 5-10 exemples récents injectés dans prompt Claude

### Configuration Style (user_settings.preferences)

```json
{
  "writing_style": {
    "tone": "formal",           // "formal" | "informal"
    "tutoiement": false,        // true | false
    "verbosity": "concise"      // "concise" | "detailed"
  }
}
```

### Trade-off Qualité vs Coût

| Exemples | Qualité | Coût Tokens | Coût $ | Recommandation |
|----------|---------|-------------|--------|----------------|
| 0 | Baseline | ~200 | $0.01 | Day 1 uniquement |
| 3 | +60% | ~800 | $0.02 | Bon compromis |
| **5** | **+80%** | **~1200** | **$0.03** | **Sweet spot ⭐** |
| 10 | +90% | ~2500 | $0.06 | Rendement décroissant |

**Limite architecture** : Max 10 exemples pour éviter explosion coût.

### Format Few-Shot dans Prompt

```
Exemples du style Mainteneur :
---
Exemple 1:
Sujet: Re: Request for information
Corps:
Bonjour,

Voici les informations demandées.

Bien cordialement,
Dr. Antonio Lopez
---
Exemple 2:
...
```

---

## Configuration

### Variables d'environnement

```bash
# EmailEngine
EMAILENGINE_BASE_URL=http://localhost:3000
EMAILENGINE_SECRET=<bearer_token>

# Telegram
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_SUPERGROUP_ID=<chat_id>
TOPIC_ACTIONS_ID=<thread_id>     # Topic pour brouillons
TOPIC_EMAIL_ID=<thread_id>        # Topic pour confirmations envoi

# PostgreSQL
DATABASE_URL=postgresql://friday:pass@localhost:5432/friday

# Presidio (RGPD)
PRESIDIO_ANALYZER_URL=http://localhost:5001
PRESIDIO_ANONYMIZER_URL=http://localhost:5002
```

### Mapping Comptes IMAP (EmailEngine)

Éditer `services/email_processor/emailengine_client.py` :

```python
def determine_account_id(email_original: dict) -> str:
    recipient = email_original.get('recipient_email')

    account_mapping = {
        "antonio.lopez@example.com": "account_professional",
        "dr.lopez@hospital.fr": "account_medical",
        "lopez@university.fr": "account_academic",
        "personal@gmail.com": "account_personal"
    }

    return account_mapping.get(recipient, "account_professional")
```

---

## Usage Telegram

### Commande `/draft [email_id]`

Générer manuellement un brouillon pour un email reçu.

```
/draft f47ac10b-58cc-4372-a567-0e02b2c3d479
```

**Réponse :**
```
⏳ Génération brouillon en cours...

Email: Question about appointment
Expéditeur: john@example.com

Vous recevrez une notification dans le topic Actions dès que le brouillon sera prêt.
```

### Notification Brouillon Prêt (topic Actions)

```
📝 Brouillon réponse email prêt

De: [NAME_1]@[DOMAIN_1]
Sujet: Re: Question about [MEDICAL_TERM_1]

Brouillon :
---
Bonjour,

Oui, vous pouvez reprogrammer votre rendez-vous pour la semaine prochaine.

Cordialement,
Dr. Antonio Lopez
---

Voulez-vous envoyer ce brouillon ?

[✅ Approve] [❌ Reject] [✏️ Edit]
```

### Actions Inline Buttons

| Bouton | Action | Résultat |
|--------|--------|----------|
| **✅ Approve** | Envoie email + stocke exemple | Topic Email : "✅ Email envoyé : Re: ..." |
| **❌ Reject** | Annule envoi | Message édité : "❌ Brouillon rejeté" |
| **✏️ Edit** | Modifie brouillon (MVP: stub) | "Fonctionnalité Edit à venir (Story 2.5.1)" |

---

## API & Modules

### `draft_email_reply(email_id, email_data, db_pool)`

**Signature :**
```python
@friday_action(module="email", action="draft_reply", trust_default="propose")
async def draft_email_reply(
    email_id: str,
    email_data: dict,
    db_pool: asyncpg.Pool,
    user_preferences: Optional[dict] = None
) -> ActionResult
```

**Returns :**
```python
ActionResult(
    input_summary="Email de [NAME_1]@...: Question about...",
    output_summary="Brouillon réponse (234 caractères)",
    confidence=0.85,
    reasoning="Style cohérent avec 5 exemples précédents + 2 règles appliquées",
    payload={
        'draft_body': "Bonjour,\n\n...",
        'email_original_id': email_id,
        'email_type': 'professional',
        'style_examples_used': 5,
        'correction_rules_used': 2
    }
)
```

### `send_email_via_emailengine(receipt_id, db_pool, ...)`

**Signature :**
```python
async def send_email_via_emailengine(
    receipt_id: str,
    db_pool: asyncpg.Pool,
    http_client: httpx.AsyncClient,
    emailengine_url: str,
    emailengine_secret: str
) -> Dict
```

**Workflow :**
1. Load receipt (status='approved')
2. Extract draft_body + email_original_id
3. Fetch email original
4. Determine account_id
5. Send via EmailEngine (threading correct)
6. UPDATE receipt status='executed'
7. INSERT writing_example

**Returns :**
```python
{
    'success': True,
    'messageId': '<sent-456@example.com>',
    'recipient': 'john@example.com',
    'subject': 'Re: Your question'
}
```

---

## Troubleshooting

### Brouillon Incohérent / Style Incorrect

**Cause 1 : Pas assez d'exemples (N<3)**

Solution : Envoyer quelques brouillons manuels initiaux pour alimenter few-shot learning.

**Cause 2 : Exemples email_type différent**

Vérifier que les exemples stockés correspondent au type email (professional vs medical vs academic).

```sql
SELECT email_type, COUNT(*) FROM core.writing_examples
WHERE sent_by='Mainteneur'
GROUP BY email_type;
```

**Cause 3 : Correction rules contradictoires**

Vérifier les règles actives :
```sql
SELECT * FROM core.correction_rules
WHERE module='email' AND scope='draft_reply' AND active=true
ORDER BY priority DESC;
```

### EmailEngine Erreur 500

**Cause : Compte IMAP invalide**

Vérifier mapping `determine_account_id()` dans `emailengine_client.py`.

**Cause : Token expiré**

Regénérer `EMAILENGINE_SECRET` dans EmailEngine dashboard.

### Presidio Indisponible (NotImplementedError)

**Fail-explicit RGPD** : Si Presidio down → pipeline STOP, jamais d'envoi PII vers Claude cloud.

Vérifier services :
```bash
curl http://localhost:5001/health  # Analyzer
curl http://localhost:5002/health  # Anonymizer
```

Redémarrer si nécessaire :
```bash
docker compose restart presidio-analyzer presidio-anonymizer
```

### Brouillon Non Envoyé Après Approve

**Cause : Exception EmailEngine non catchée**

Vérifier logs :
```bash
docker compose logs -f friday-bot | grep "emailengine_send_failed"
```

**Cause : Receipt status != 'approved'**

Query receipt :
```sql
SELECT id, status, validated_by, executed_at
FROM core.action_receipts
WHERE id='<receipt_uuid>'
```

---

## Architecture Decisions

### Pourquoi trust=propose JAMAIS auto ?

**Rationale :**
- Envoi email = action irréversible
- Risque erreur catastrophique existe même avec 100% accuracy
- Coût validation (5s) << coût email incorrect envoyé
- Médical/professionnel = contexte critique

### Pourquoi limiter à 10 writing_examples max ?

**Rationale :**
- Token cost : 10 exemples ≈ 1500 tokens prompt
- Rendement décroissant : exemples 6-10 apportent <10% qualité
- Sweet spot : 5 exemples = 80% bénéfice, 40% coût vs 10

### Pourquoi température 0.7 (vs 0.1 classification) ?

**Rationale :**
- Classification = déterministe (1 seule bonne réponse)
- Rédaction = créative (plusieurs formulations valides)
- Temp 0.7 = balance cohérence + variété
- Temp 0.1 → brouillons robotiques
- Temp 0.9 → brouillons fantaisistes

---

**Documentation mise à jour** : 2026-02-11
**Version** : 1.0.0
**Story** : 2.5 Brouillon Réponse Email
