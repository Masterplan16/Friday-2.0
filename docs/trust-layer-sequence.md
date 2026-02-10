# Trust Layer - Diagrammes de séquence

**Version** : 1.0 (2026-02-09)
**Story** : 1.6 - Trust Layer Middleware

---

## Séquence 1 : Exécution d'une action (trust=auto)

```mermaid
sequenceDiagram
    participant M as Module (email)
    participant D as @friday_action
    participant TM as TrustManager
    participant PG as PostgreSQL
    participant L as LLM (Claude)
    participant T as Telegram

    M->>D: classify_email(email)
    activate D

    D->>TM: get_trust_level("email", "classify")
    TM-->>D: "auto"

    D->>PG: SELECT correction_rules WHERE module='email'
    PG-->>D: [rules...]

    D->>D: format_rules_for_prompt(rules)
    D->>D: inject rules in kwargs["_rules_prompt"]

    D->>M: await func(email, **kwargs)
    activate M
    M->>L: classify(email, rules_prompt)
    L-->>M: category="urgent"
    M-->>D: ActionResult(category="urgent", confidence=0.95)
    deactivate M

    D->>D: result.module = "email"
    D->>D: result.action_type = "classify"
    D->>D: result.trust_level = "auto"
    D->>D: result.status = "auto"

    D->>TM: create_receipt(result)
    TM->>PG: INSERT INTO core.action_receipts
    PG-->>TM: receipt_id
    TM-->>D: receipt_id

    D->>D: result.payload["receipt_id"] = receipt_id

    D->>T: notify topic Metrics (after execution)
    T-->>D: ok

    D-->>M: ActionResult (enriched)
    deactivate D

    Note over M,T: Action exécutée automatiquement + tracée + notifiée
```

---

## Séquence 2 : Exécution avec validation (trust=propose)

```mermaid
sequenceDiagram
    participant M as Module (email)
    participant D as @friday_action
    participant TM as TrustManager
    participant PG as PostgreSQL
    participant L as LLM
    participant T as Telegram
    participant A as Mainteneur

    M->>D: draft_email_reply(email)
    activate D

    D->>TM: get_trust_level("email", "draft")
    TM-->>D: "propose"

    D->>PG: SELECT correction_rules WHERE module='email'
    PG-->>D: [rules...]

    D->>M: await func(email, **kwargs)
    activate M
    M->>L: draft_reply(email, rules)
    L-->>M: draft_text
    M-->>D: ActionResult(draft_text, confidence=0.85)
    deactivate M

    D->>D: result.status = "pending"
    D->>D: result.trust_level = "propose"

    D->>TM: create_receipt(result)
    TM->>PG: INSERT INTO core.action_receipts (status='pending')
    PG-->>TM: receipt_id

    D->>TM: send_telegram_validation(result)
    TM->>T: send message to topic Actions with inline buttons
    T-->>TM: message_id

    D-->>M: ActionResult (pending validation)
    deactivate D

    Note over T,A: Mainteneur reçoit notification<br/>avec boutons [Approve] [Reject]

    alt Mainteneur approuve
        A->>T: click [Approve]
        T->>PG: UPDATE action_receipts SET status='approved'
        T->>M: execute_approved_action(receipt_id)
        M-->>T: action executed
        T->>A: ✅ Action exécutée
    else Mainteneur rejette
        A->>T: click [Reject]
        T->>PG: UPDATE action_receipts SET status='rejected'
        T->>A: ❌ Action annulée
    end
```

---

## Séquence 3 : Action bloquée (trust=blocked)

```mermaid
sequenceDiagram
    participant M as Module (medical)
    participant D as @friday_action
    participant TM as TrustManager
    participant PG as PostgreSQL
    participant L as LLM
    participant T as Telegram

    M->>D: analyze_medical_document(doc)
    activate D

    D->>TM: get_trust_level("medical", "analyze")
    TM-->>D: "blocked"

    D->>PG: SELECT correction_rules
    PG-->>D: [rules...]

    D->>M: await func(doc, **kwargs)
    activate M
    M->>L: analyze(doc, readonly=true)
    L-->>M: analysis (lecture seule)
    M-->>D: ActionResult(analysis, confidence=0.90)
    deactivate M

    D->>D: result.status = "blocked"
    D->>D: result.trust_level = "blocked"

    D->>TM: create_receipt(result)
    TM->>PG: INSERT INTO core.action_receipts (status='blocked')
    PG-->>TM: receipt_id

    D->>T: notify topic System (alerte action blocked)
    T-->>D: ok

    D-->>M: ActionResult (analysis only, no action)
    deactivate D

    Note over M,T: Analyse effectuée<br/>AUCUNE action entreprise<br/>(données sensibles)
```

---

## Séquence 4 : Feedback Loop (correction → règle)

```mermaid
sequenceDiagram
    participant A as Mainteneur
    participant T as Telegram
    participant PG as PostgreSQL
    participant S as System (nightly)
    participant D as @friday_action
    participant M as Module

    Note over A,T: 1. Mainteneur détecte erreur

    A->>T: /journal
    T->>PG: SELECT * FROM core.action_receipts ORDER BY created_at DESC LIMIT 20
    PG-->>T: [receipts...]
    T-->>A: 📋 20 dernières actions

    A->>T: /receipt abc123
    T->>PG: SELECT * FROM core.action_receipts WHERE id='abc123'
    PG-->>T: receipt details
    T-->>A: 📄 Détails action<br/>Input: Email de urgent@example.com<br/>Output: → Category: general<br/>❌ ERREUR détectée

    Note over A,T: 2. Mainteneur corrige manuellement

    A->>T: /correct abc123 category=urgent
    T->>PG: UPDATE action_receipts SET status='corrected'
    T->>PG: INSERT INTO manual_corrections (receipt_id, correction)
    PG-->>T: ok
    T-->>A: ✅ Correction enregistrée

    Note over S,PG: 3. Système détecte pattern (nightly)

    S->>PG: SELECT receipts with similar errors
    PG-->>S: 2 corrections identiques<br/>sender contains "@urgent.com"<br/>→ should be "urgent"

    S->>PG: INSERT INTO correction_rules (conditions, output)
    PG-->>S: rule_id

    S->>T: propose rule to Mainteneur
    T-->>A: 💡 Nouvelle règle proposée<br/>[Règle prio 5] SI sender_contains @urgent.com<br/>ALORS category=urgent<br/>[Approve] [Reject]

    Note over A,T: 4. Mainteneur valide règle

    A->>T: click [Approve]
    T->>PG: UPDATE correction_rules SET active=true
    PG-->>T: ok
    T-->>A: ✅ Règle activée

    Note over D,M: 5. Règle appliquée aux prochaines actions

    M->>D: classify_email(email from urgent@example.com)
    D->>PG: SELECT correction_rules WHERE module='email'
    PG-->>D: [rules including new rule prio 5]
    D->>D: inject rules in prompt
    D->>M: execute with rules
    M-->>D: ActionResult(category="urgent") ✅
    D->>PG: INSERT receipt + UPDATE rule.hit_count++
```

---

## Séquence 5 : Rétrogradation automatique (accuracy < 90%)

```mermaid
sequenceDiagram
    participant S as Nightly Script
    participant PG as PostgreSQL
    participant Y as trust_levels.yaml
    participant T as Telegram
    participant A as Mainteneur

    Note over S: Exécution nightly (cron 02:00)

    S->>PG: SELECT receipts WHERE created_at > NOW() - INTERVAL '7 days'<br/>GROUP BY module, action_type
    PG-->>S: metrics per module/action

    S->>S: calculate accuracy = 1 - (corrected / total)

    loop For each module/action
        alt accuracy < 90% AND total >= 10
            S->>S: trigger retrogradation
            S->>PG: INSERT INTO trust_metrics (accuracy, recommended_trust_level)
            PG-->>S: ok

            S->>Y: update trust_levels.yaml<br/>email.classify: auto → propose
            Y-->>S: file updated

            S->>T: notify topic System
            T->>A: 🔻 Rétrogradation automatique<br/>Module: email.classify<br/>auto → propose<br/>Accuracy: 87% (13/100 corrigées)

            S->>PG: INSERT INTO events (trust.level.changed)
            PG-->>S: ok
        else accuracy >= 95% AND total >= 10
            S->>PG: INSERT INTO trust_metrics (can_promotion=true)
            PG-->>S: ok

            S->>T: suggest promotion (manual approval required)
            T->>A: ⬆️ Promotion possible<br/>Module: email.classify<br/>Accuracy: 97% (3/100 corrigées)<br/>Validation requise [Approve] [Reject]

            Note over A: Décision manuelle Mainteneur
        end
    end
```

---

## Légende

### Acteurs

| Acteur | Description |
|--------|-------------|
| **M** (Module) | Module métier (email, archiviste, etc.) |
| **D** (@friday_action) | Décorateur Trust Layer |
| **TM** (TrustManager) | Gestionnaire du Trust Layer |
| **PG** (PostgreSQL) | Base de données (receipts, rules, metrics) |
| **L** (LLM) | Claude Sonnet 4.5 API |
| **T** (Telegram) | Bot Telegram (5 topics) |
| **A** (Mainteneur) | Utilisateur final |
| **S** (System) | Scripts nightly/monitoring |
| **Y** (YAML) | Fichier config/trust_levels.yaml |

### Statuts receipt

| Statut | Signification |
|--------|---------------|
| **auto** | Action exécutée automatiquement |
| **pending** | En attente de validation Telegram |
| **approved** | Validée par Mainteneur via inline button |
| **rejected** | Refusée par Mainteneur ou erreur |
| **corrected** | Corrigée manuellement par Mainteneur |

### Trust levels

| Level | Comportement |
|-------|--------------|
| **auto** | Exécute + notifie après |
| **propose** | Prépare + attend validation |
| **blocked** | Analyse seule, jamais d'action |

---

## Voir aussi

- [Guide d'utilisation](./trust-layer-usage.md) - Documentation complète
- [Architecture addendum §7](../_docs/architecture-addendum-20260205.md#7) - Formules
- [Migration 011](../database/migrations/011_trust_system.sql) - Tables SQL
