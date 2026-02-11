# Detection VIP & Urgence (Story 2.3)

Documentation complete du systeme de detection VIP et urgence pour Friday 2.0.

## Vue d'ensemble

Systeme de detection bi-factoriel pour prioriser automatiquement les emails entrants :
1. **Detection VIP** : Identification expediteurs prioritaires via hash SHA256 (RGPD-compliant)
2. **Detection Urgence** : Analyse multi-facteurs (VIP + keywords + deadline patterns)

**Seuil urgence** : Score >= 0.6 → Email urgent

## Architecture

### Modules

```
agents/src/agents/email/
├── vip_detector.py          # Detection VIP via hash lookup
├── urgency_detector.py       # Detection urgence multi-facteurs
└── README_VIP_URGENCE.md     # Cette documentation
```

### Base de donnees

```sql
-- Table VIP senders (core schema)
core.vip_senders
  - id UUID
  - email_anon TEXT           -- Email anonymise Presidio (ex: [EMAIL_123])
  - email_hash TEXT           -- SHA256(email.lower().strip()) - UNIQUE index
  - label TEXT                -- Label humain (ex: "Doyen Faculte")
  - priority_override TEXT    -- 'high' | 'urgent' | NULL
  - designation_source TEXT   -- 'manual' | 'learned'
  - emails_received_count INT -- Stats activite
  - last_email_at TIMESTAMP
  - active BOOLEAN            -- Soft delete

-- Table keywords urgence (core schema)
core.urgency_keywords
  - id UUID
  - keyword TEXT              -- Keyword urgence (ex: "URGENT", "deadline")
  - weight DOUBLE PRECISION   -- Poids 0.0-1.0
  - context_pattern TEXT      -- Regex pattern optionnel
  - active BOOLEAN
```

## 1. Detection VIP

### Principe RGPD

Lookup **uniquement via hash SHA256**, jamais d'acces email en clair.

```python
# Calcul hash (normalise lowercase + strip)
email_hash = compute_email_hash("Doyen@Univ.FR  ")
# → "a1b2c3d4..." (64 caracteres hex)

# Lookup VIP
result = await detect_vip_sender(
    email_anon="[EMAIL_DOYEN_123]",
    email_hash=email_hash,
    db_pool=db_pool,
)

# Result
result.payload["is_vip"]  # True/False
result.payload["vip"]     # VIPSender object ou None
result.confidence         # 1.0 (lookup binaire)
```

### API

#### `compute_email_hash(email: str) -> str`

Calcule hash SHA256 d'un email avec normalisation.

**Args** :
- `email` : Email original (avant anonymisation)

**Returns** : Hash SHA256 hexdigest (64 caracteres)

**Exemple** :
```python
hash1 = compute_email_hash("doyen@univ.fr")
hash2 = compute_email_hash("Doyen@Univ.FR  ")  # Meme hash (normalise)
assert hash1 == hash2
```

#### `detect_vip_sender(...) -> ActionResult`

Detecte si expediteur est VIP via lookup hash.

**Args** :
- `email_anon` : Email anonymise Presidio
- `email_hash` : SHA256 email original
- `db_pool` : Pool asyncpg PostgreSQL
- `**kwargs` : Parametres injectes par @friday_action

**Returns** :
- `ActionResult` avec `payload["is_vip"]` et `payload["vip"]`
- `confidence = 1.0` (lookup binaire, pas d'incertitude)

**Raises** :
- `VIPDetectorError` : Si lookup echoue

**Trust level** : `auto` (execution automatique + notification)

**Latence cible** : <100ms (index sur email_hash)

#### `update_vip_email_stats(...) -> None`

Met a jour stats VIP (emails_received_count, last_email_at).

**Args** :
- `vip_id` : UUID du VIP
- `db_pool` : Pool asyncpg

**Notes** : Ne raise jamais (stats non critiques)

### Ajout VIP manuel

```sql
-- Via SQL direct (pour MVP, commandes Telegram Story 2.3 Task 5)
INSERT INTO core.vip_senders (
  email_anon,
  email_hash,
  label,
  designation_source,
  added_by,
  active
) VALUES (
  '[EMAIL_DOYEN_abc123]',  -- Anonymise via Presidio
  '...hash...',             -- compute_email_hash('doyen@univ.fr')
  'Doyen Faculte Medecine',
  'manual',
  '...owner_user_id...',
  TRUE
);
```

## 2. Detection Urgence

### Algorithme multi-facteurs

**Score urgence** = VIP_factor + Keywords_factor + Deadline_factor

| Facteur | Poids | Condition |
|---------|-------|-----------|
| **VIP** | 0.5 | Si expediteur VIP detecte |
| **Keywords** | 0.3 | Si >= 1 keyword urgence matche |
| **Deadline** | 0.2 | Si pattern deadline detecte |

**Seuil** : Score >= 0.6 → Email urgent

### Exemples scores

| Cas | VIP | Keywords | Deadline | Score | Urgent ? |
|-----|-----|----------|----------|-------|----------|
| VIP + "URGENT" + "avant demain" | 0.5 | 0.3 | 0.2 | **1.0** | ✅ Oui |
| VIP + "deadline" | 0.5 | 0.3 | 0.0 | **0.8** | ✅ Oui |
| VIP seul | 0.5 | 0.0 | 0.0 | **0.5** | ❌ Non |
| Non-VIP + "URGENT" + deadline | 0.0 | 0.3 | 0.2 | **0.5** | ❌ Non |
| Email normal | 0.0 | 0.0 | 0.0 | **0.0** | ❌ Non |

### API

#### `detect_urgency(...) -> ActionResult`

Detecte urgence via analyse multi-facteurs.

**Args** :
- `email_text` : Texte email anonymise (subject + body)
- `vip_status` : True si VIP detecte
- `db_pool` : Pool asyncpg
- `**kwargs` : Parametres injectes

**Returns** :
- `ActionResult` avec `payload["is_urgent"]` et `payload["urgency"]`
- `confidence` = score urgence (0.0-1.0)

**Trust level** : `auto` (algorithme deterministe)

**Latence cible** : <100ms

#### `check_urgency_keywords(...) -> list[str]`

Verifie presence keywords urgence.

**Args** :
- `text` : Texte email
- `db_pool` : Pool asyncpg

**Returns** : Liste keywords matches (ex: ["URGENT", "deadline"])

**Notes** :
- Recherche case-insensitive
- Keywords depuis `core.urgency_keywords WHERE active=TRUE`
- Mode degrade si erreur DB → retourne []

#### `extract_deadline_patterns(text: str) -> Optional[str]`

Detecte patterns deadline francais.

**Patterns** :
- `avant demain`, `avant le 15`
- `deadline 15`
- `pour demain`, `pour ce soir`
- `d'ici 2 jours`, `d'ici 24 heures`
- `urgent ... demain/aujourd'hui/ce soir`

**Returns** : Premier pattern matche ou None

**Exemple** :
```python
text = "Merci de repondre avant demain matin."
pattern = extract_deadline_patterns(text)
# → "avant demain"
```

## 3. Pipeline complet

Workflow detection VIP + urgence dans consumer email :

```python
# 1. Reception email anonymise
email_anon = "[EMAIL_123]"
email_text = f"{email_anonymized.subject} {email_anonymized.body}"

# 2. Calcul hash email ORIGINAL (avant anonymisation)
email_hash = compute_email_hash(email_original.from)

# 3. Detection VIP
vip_result = await detect_vip_sender(
    email_anon=email_anon,
    email_hash=email_hash,
    db_pool=db_pool,
)
is_vip = vip_result.payload["is_vip"]

# 4. Detection urgence
urgency_result = await detect_urgency(
    email_text=email_text,
    vip_status=is_vip,
    db_pool=db_pool,
)
is_urgent = urgency_result.payload["is_urgent"]

# 5. Mise a jour BDD
if is_urgent:
    await db_pool.execute(
        "UPDATE ingestion.emails SET priority = 'urgent' WHERE id = $1",
        email_id,
    )

# 6. Notification Telegram si urgent
if is_urgent:
    await send_telegram_notification(
        topic="TOPIC_ACTIONS_ID",
        message=f"Email URGENT detecte: {urgency_result.reasoning}",
    )

# 7. Stats VIP si applicable
if is_vip:
    vip_id = vip_result.payload["vip"]["id"]
    await update_vip_email_stats(vip_id, db_pool)
```

## 4. Tests

### Tests unitaires

```bash
# VIP detector (11 tests)
pytest tests/unit/agents/email/test_vip_detector.py -v

# Urgency detector (18 tests)
pytest tests/unit/agents/email/test_urgency_detector.py -v
```

### Tests E2E (AC5 CRITIQUE)

```bash
# Dataset 31 emails + 5 tests E2E
pytest tests/e2e/email/test_urgency_detection_e2e.py -v -m e2e
```

**Acceptance Criteria AC5** :
- ✅ **100% recall VIP** : 12/12 VIP detectes
- ✅ **100% recall urgence** : 5/5 urgents detectes
- ✅ **<10% faux positifs** : Precision >= 90%
- ✅ **Latence <1s/email** : Moyenne <500ms
- ✅ **Edge cases** : 6 cas limites valides

### Dataset test

`tests/fixtures/vip_urgency_dataset.json` contient 31 emails :
- 5 VIP non urgents
- 5 VIP urgents
- 5 non-VIP urgents (score <0.6)
- 10 normaux
- 6 edge cases (VIP spam, phishing, etc.)

## 5. Trust Layer

Toutes les fonctions detection utilisent `@friday_action` decorator :

```python
@friday_action(module="email", action="detect_vip", trust_default="auto")
async def detect_vip_sender(...) -> ActionResult:
    # ...
```

**Trust levels** :
- `detect_vip` : **auto** (lookup simple, pas d'erreur possible)
- `detect_urgency` : **auto** (algorithme deterministe)

**ActionResult** contient :
- `input_summary` : Ce qui est entre
- `output_summary` : Ce qui a ete fait
- `confidence` : Score 0.0-1.0
- `reasoning` : Explication decision
- `payload` : Donnees techniques

**Receipts** : Chaque action cree un receipt dans `core.action_receipts` pour audit.

## 6. Securite RGPD

### Compliance

✅ **Aucun acces PII** : Lookup uniquement via hash SHA256
✅ **Anonymisation Presidio** : Emails anonymises avant stockage
✅ **Hash normalise** : `email.lower().strip()` pour eviter collisions casse
✅ **Soft delete** : `active = FALSE` au lieu de DELETE
✅ **Audit trail** : Tous receipts action_receipts

### Mapping Presidio

**IMPORTANT** : Le mapping Presidio (anonymise ↔ original) est ephemere :
- Stocke en Redis avec TTL court (1 heure)
- JAMAIS stocke en PostgreSQL
- Efface apres traitement email

### Verification compliance

```python
# Hash DOIT etre calcule AVANT anonymisation
email_original = "doyen@univ.fr"
email_hash = compute_email_hash(email_original)  # ✅ Correct

# Puis anonymisation
email_anon = await presidio_anonymize(email_original)  # → "[EMAIL_123]"

# Lookup VIP avec hash (pas d'acces PII)
await detect_vip_sender(email_anon, email_hash, db_pool)  # ✅ Safe
```

## 7. Troubleshooting

### VIP non detecte alors qu'il existe

**Diagnostic** :
```sql
-- Verifier VIP actif
SELECT * FROM core.vip_senders WHERE active = TRUE;

-- Verifier hash matche
SELECT email_hash FROM core.vip_senders WHERE email_anon = '[EMAIL_...]';
```

**Solutions** :
- Verifier que `active = TRUE`
- Verifier hash calcule avec normalisation lowercase + strip
- Verifier email original (pas anonymise) utilise pour compute_hash

### Email urgent non detecte

**Diagnostic** :
```python
# Tester individuellement chaque facteur
is_vip = ...  # Facteur VIP
keywords = await check_urgency_keywords(email_text, db_pool)  # Facteur keywords
deadline = extract_deadline_patterns(email_text)  # Facteur deadline

score = (0.5 if is_vip else 0) + (0.3 if keywords else 0) + (0.2 if deadline else 0)
# Score >= 0.6 → urgent
```

**Solutions** :
- Verifier VIP detecte (facteur 0.5)
- Verifier keywords actifs dans `core.urgency_keywords`
- Verifier patterns deadline matchent (texte francais)
- Verifier seuil 0.6 atteint

### Faux positifs urgence

**Solutions** :
- Ajuster poids keywords (0.3 → 0.2)
- Affiner patterns deadline (plus restrictifs)
- Ajouter filter spam/marketing
- Augmenter seuil urgence (0.6 → 0.7)

## 8. Configuration

### Keywords urgence

Ajouter/modifier keywords :

```sql
-- Ajouter keyword
INSERT INTO core.urgency_keywords (keyword, weight, active)
VALUES ('urgent', 0.5, TRUE);

-- Desactiver keyword
UPDATE core.urgency_keywords SET active = FALSE WHERE keyword = 'important';

-- Ajuster poids
UPDATE core.urgency_keywords SET weight = 0.4 WHERE keyword = 'deadline';
```

### Seed keywords initial

Migration 028 cree 10 keywords par defaut :
- URGENT (0.5)
- urgent (0.5)
- deadline (0.3)
- delai (0.3)
- echeance (0.3)
- avant demain (0.4)
- ce soir (0.4)
- d'ici (0.3)
- prioritaire (0.3)
- aujourd'hui (0.2)

## 9. Performance

### Benchmarks

**VIP detection** :
- Latence : <10ms (index sur email_hash)
- Throughput : >1000 lookups/s

**Urgency detection** :
- Latence : <50ms (keywords DB query + regex)
- Throughput : >500 analyses/s

**Pipeline complet** (VIP + urgence) :
- Latence moyenne : <100ms
- Latence max : <500ms

### Optimisations

✅ **Index PostgreSQL** : `CREATE INDEX ON vip_senders(email_hash)`
✅ **Connection pooling** : asyncpg pool (20 connexions)
✅ **Mode degrade** : Keywords error → continue sans keywords
✅ **Pas de RAG** : Lookup direct (pas d'embeddings)

## 10. Evolutions futures

### Phase 1 (MVP - Complete)
- [x] Detection VIP manuelle
- [x] Detection urgence multi-facteurs
- [x] Tests E2E 31 emails

### Phase 2 (Post-MVP)
- [ ] Commandes Telegram /vip add|list|remove (Task 5)
- [ ] Apprentissage automatique VIP (designation_source='learned')
- [ ] Patterns deadline adaptatifs (ML)
- [ ] Detection spam/phishing VIP compromis

### Phase 3 (Avance)
- [ ] Scoring urgence personnalise par utilisateur
- [ ] Integration calendrier (deadline reelle vs texte)
- [ ] Analyse sentiment (stress/urgence emotionnelle)

## 11. References

- **Story BMAD** : `_bmad-output/implementation-artifacts/2-3-detection-vip-urgence.md`
- **Migrations SQL** : `database/migrations/027_vip_senders.sql`, `028_urgency_keywords.sql`
- **Tests E2E** : `tests/e2e/email/test_urgency_detection_e2e.py`
- **Dataset** : `tests/fixtures/vip_urgency_dataset.json`
- **Architecture** : `_docs/architecture-friday-2.0.md`

---

**Version** : 1.0.0 (2026-02-11)
**Status** : MVP Complete - Tasks 1-4 + 7-8 ✅
**Contact** : Friday 2.0 Development Team
