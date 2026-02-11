# Workflow Technique : Envoi Emails Approuvés

**Story 2.6** : Pipeline complet email reçu → brouillon → validation → envoi → confirmation

---

## Vue d'Ensemble

```
Email reçu → Classification → Brouillon → [Approve] → Envoi → ✅ Confirmation
                                             ↓             ↓
                                     Receipt approved   Receipt executed
                                             ↓             ↓
                                        DB update    Writing example
```

---

## Diagramme Séquence Complet

```mermaid
sequenceDiagram
    participant EmailEngine as EmailEngine
    participant RedisStreams as Redis Streams
    participant Consumer as Email Consumer
    participant Classifier as Email Classifier
    participant DraftAgent as Draft Reply Agent
    participant DB as PostgreSQL
    participant Bot as Friday Bot
    participant Mainteneur as Mainteneur
    participant Telegram as Telegram API
    participant ActionExecutor as Action Executor

    %% Réception email (Story 2.1)
    EmailEngine->>RedisStreams: email.received event
    Consumer->>RedisStreams: XREAD group (email_processor)
    RedisStreams-->>Consumer: email.received payload

    %% Classification (Story 2.2)
    Consumer->>Classifier: classify_email()
    Classifier->>DB: SELECT correction_rules
    Classifier->>DB: INSERT receipt (trust=propose)
    Classifier->>Telegram: Notification topic Email

    %% Génération brouillon (Story 2.5)
    Note over DraftAgent: Trigger auto ou commande /draft
    DraftAgent->>DB: FETCH email + writing_examples (top 5)
    DraftAgent->>DB: FETCH correction_rules
    DraftAgent->>DraftAgent: Build prompt (few-shot + rules)
    DraftAgent->>DraftAgent: Claude Sonnet 4.5 (temp=0.7)
    DraftAgent->>DB: INSERT receipt (status=pending, trust=propose)
    DraftAgent->>Telegram: Notification topic Actions + inline buttons

    %% Validation Mainteneur (Story 2.6)
    Mainteneur->>Telegram: Clic [Approve] button
    Telegram->>Bot: Callback approve_{receipt_id}
    Bot->>Bot: Verify OWNER_USER_ID
    Bot->>DB: UPDATE receipt (status=approved, validated_by, validated_at)
    Bot->>Telegram: Edit message "✅ Brouillon approuvé"
    Bot->>ActionExecutor: execute_action("email.draft_reply", receipt_id)

    %% Envoi EmailEngine (Story 2.6)
    ActionExecutor->>DB: SELECT receipt (status=approved)
    ActionExecutor->>DB: SELECT email_original (for threading)
    ActionExecutor->>ActionExecutor: determine_account_id()
    ActionExecutor->>EmailEngine: POST /v1/account/{accountId}/submit
    Note right of EmailEngine: inReplyTo + references<br/>3 retries avec backoff

    alt Envoi réussi
        EmailEngine-->>ActionExecutor: 200 OK + messageId
        ActionExecutor->>ActionExecutor: Anonymize recipient + subject (Presidio)
        ActionExecutor->>Telegram: Notification topic Email (confirmation)
        ActionExecutor->>DB: UPDATE receipt (status=executed, executed_at)
        ActionExecutor->>DB: INSERT writing_example (few-shot learning)
        ActionExecutor-->>Bot: Success
    else Envoi échoué
        EmailEngine-->>ActionExecutor: 500 Error (after 3 retries)
        ActionExecutor->>DB: UPDATE receipt (status=failed)
        ActionExecutor->>ActionExecutor: Anonymize recipient (Presidio)
        ActionExecutor->>Telegram: Notification topic System (échec)
        ActionExecutor-->>Bot: EmailEngineError raised
    end

    %% Consultation historique (Story 2.6)
    Mainteneur->>Telegram: /journal
    Telegram->>Bot: journal_command()
    Bot->>DB: SELECT action_receipts (LIMIT 20)
    Bot->>Telegram: Liste emails envoyés + autres actions

    Mainteneur->>Telegram: /receipt {receipt_id}
    Telegram->>Bot: receipt_command(receipt_id)
    Bot->>DB: SELECT receipt (with payload)
    Bot->>Telegram: Détails complets (Email Details + payload)
```

---

## Composants & Responsabilités

### 1. EmailEngine (Service externe)

**Rôle** : Réception IMAP + Envoi SMTP

**API Endpoints** :
- `GET /v1/account/{accountId}/messages` — Récupération emails
- `POST /v1/account/{accountId}/submit` — Envoi email
- Webhook : `POST /webhooks/emailengine` → Redis Streams

**Threading** : Gère automatiquement `inReplyTo` + `references` si fournis

**Retry** : 3 tentatives automatiques avec backoff exponentiel

### 2. Redis Streams (Event Bus)

**Events critiques** :
- `email.received` — Nouvel email IMAP reçu
- `email.classified` — Email classifié
- `email.draft_ready` — Brouillon prêt validation
- `email.sent` — Email envoyé avec succès

**Consumer groups** :
- `email_processor` — Traite emails reçus
- `notification_sender` — Envoie notifications Telegram

### 3. PostgreSQL (State Store)

**Tables principales** :
- `ingestion.emails` — Emails bruts + métadonnées
- `core.action_receipts` — Receipts Trust Layer (status transitions)
- `core.writing_examples` — Exemples few-shot learning
- `core.correction_rules` — Règles correction feedback loop

**Status transitions** :
```
pending → approved → executed  (succès)
pending → approved → failed    (échec EmailEngine)
```

### 4. Friday Bot (Telegram Interface)

**Handlers** :
- `/draft` — Génération brouillon manuelle
- `/journal` — Consultation historique actions
- `/receipt` — Détail complet action

**Callbacks** :
- `approve_{receipt_id}` — Validation brouillon → envoi
- `reject_{receipt_id}` — Rejet brouillon
- `edit_{receipt_id}` — Modification brouillon (stub MVP)

**Topics Telegram** :
- **Email & Communications** — Notifications confirmation envoi
- **Actions & Validations** — Inline buttons validation
- **System & Alerts** — Alertes échec envoi

### 5. Action Executor (Story 2.6)

**Fonction principale** : `send_email_via_emailengine()`

**Workflow interne** :
1. Load receipt + email original
2. Verify status='approved'
3. Call EmailEngine API (retry 3x)
4. **Story 2.6 : Notifications** :
   - Succès → Anonymize + notify topic Email
   - Échec → Anonymize + notify topic System
5. Update receipt status (executed/failed)
6. Store writing_example (si succès)

---

## Points d'Attention Critiques

### RGPD & Anonymisation

**RÈGLE** : Toute notification Telegram DOIT anonymiser PII via Presidio

```python
# ✅ CORRECT
recipient_anon = await presidio_anonymize(recipient_email)
subject_anon = await presidio_anonymize(subject)
await bot.send_message(text=f"Email envoyé à {recipient_anon}")

# ❌ WRONG - PII leak
await bot.send_message(text=f"Email envoyé à {recipient_email}")
```

### Error Handling

**RÈGLE** : Notification échec ne bloque JAMAIS workflow

```python
try:
    await send_email_confirmation_notification(...)
except Exception as e:
    logger.warning(f"notification_failed: {e}")
    pass  # Continue workflow
```

### Status Transitions

**RÈGLE** : Receipt status DOIT suivre séquence stricte

```
pending (brouillon prêt)
  ↓ (clic Approve)
approved (validé Mainteneur)
  ↓ (envoi EmailEngine)
executed (envoyé) OU failed (échec)
```

**Anti-pattern** : Passer directement de `pending` → `executed` (skip approved)

---

## Métriques Performance

| Métrique | Cible | Mesure |
|----------|-------|--------|
| **Latence envoi** | <5s | Clic Approve → confirmation |
| **Fiabilité** | >99% | Taux de succès envoi (si EmailEngine healthy) |
| **Retry** | 3 tentatives | Backoff 1s, 2s |
| **Coût** | $0 | Pas d'appel LLM (seulement EmailEngine) |

---

## Dépendances Stories

- **Story 1.6** : Trust Layer (`@friday_action`, receipt status transitions)
- **Story 1.10** : Inline buttons Telegram (callbacks approve/reject)
- **Story 1.11** : Commandes Telegram (`/journal`, `/receipt`)
- **Story 2.1** : EmailEngine Integration (send_message API)
- **Story 2.5** : Brouillons Réponse Email (génération + few-shot learning)

---

**Auteur** : Claude Sonnet 4.5
**Date** : 2026-02-11
**Version** : 1.0.0
**Story** : 2.6 Envoi Emails Approuvés
