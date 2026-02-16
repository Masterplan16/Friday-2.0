# Archiviste - Suivi Garanties (Story 3.4)

Documentation technique du pipeline de suivi automatique des garanties.

---

## Vue d'ensemble

Le module Warranty Tracking detecte automatiquement les informations de garantie dans les documents scannes (factures, bons de garantie), les stocke dans PostgreSQL, et envoie des alertes proactives via Telegram avant expiration.

**Pipeline** : OCR (Story 3.1) -> Extraction Claude -> Validation Pydantic -> PostgreSQL + Knowledge Graph -> Heartbeat alertes

---

## Architecture

### Composants

| Fichier | Responsabilite | Lignes |
|---------|---------------|--------|
| `warranty_extractor.py` | Extraction LLM + Presidio + Trust Layer | ~270 |
| `warranty_models.py` | Pydantic models + enum categories | ~95 |
| `warranty_prompts.py` | Few-shot 5 exemples + correction_rules | ~140 |
| `warranty_db.py` | CRUD asyncpg (insert, query, expire, alerts) | ~295 |
| `warranty_orchestrator.py` | Pipeline complet : extract -> store -> notify | ~270 |
| `warranty_expiry.py` | Heartbeat check quotidien 02:00 UTC | ~205 |
| `warranty_commands.py` | Commandes Telegram /warranties | ~210 |
| `warranty_callbacks.py` | Inline buttons Approve/Edit/Delete | ~170 |

### Flux de donnees

```
Document OCR (Story 3.1)
    |
    v
warranty_extractor.py
    |-- Presidio anonymize (RGPD)
    |-- Claude Sonnet 4.5 (few-shot)
    |-- Pydantic validation
    |-- Presidio deanonymize
    |
    v
warranty_orchestrator.py
    |-- insert_warranty() -> knowledge.warranties
    |-- create_warranty_reminder_node() -> knowledge.nodes
    |-- Redis Streams: warranty.extracted
    |-- Telegram: topic Actions (inline buttons)
    |
    v
Heartbeat check quotidien (02:00 UTC)
    |-- 60j -> MEDIUM (informatif)
    |-- 30j -> HIGH (action recommandee)
    |-- 7j -> CRITICAL (ignore quiet hours)
    |-- 0j -> expired (auto-update status)
```

---

## Base de donnees

### Migration 040 : `knowledge.warranties`

| Colonne | Type | Description |
|---------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| item_name | VARCHAR(500) | Nom produit |
| item_category | VARCHAR(100) | electronics/appliances/automotive/medical/furniture/other |
| vendor | VARCHAR(255) | Fournisseur (nullable) |
| purchase_date | DATE | Date achat |
| warranty_duration_months | INT | Duree en mois (1-120) |
| expiration_date | DATE | Calculee (purchase_date + duration) |
| purchase_amount | DECIMAL(10,2) | Montant en EUR (nullable) |
| document_id | UUID FK | Reference ingestion.document_metadata |
| status | VARCHAR(50) | active / expired / claimed |
| metadata | JSONB | Donnees supplementaires |

### Migration 040 : `knowledge.warranty_alerts`

Anti-spam : UNIQUE(warranty_id, alert_type)

| Colonne | Type | Description |
|---------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| warranty_id | UUID FK | Reference knowledge.warranties |
| alert_type | VARCHAR(50) | 60_days / 30_days / 7_days / expired |
| notified_at | TIMESTAMPTZ | Timestamp notification |

### Migration 041 : Helper function

`knowledge.create_warranty_reminder_node(UUID, VARCHAR, DATE)` -> cree un node type='reminder' dans knowledge.nodes.

---

## Categories de garantie

| Categorie | Exemples |
|-----------|----------|
| electronics | Imprimantes, ordinateurs, telephones, cameras |
| appliances | Lave-linge, refrigerateur, lave-vaisselle |
| automotive | Batteries, pneus, pieces auto |
| medical | Materiel cabinet (otoscope, tensiometre) |
| furniture | Bureaux, chaises, etageres |
| other | Non categorise |

---

## Trust Layer

- **Decorateur** : `@friday_action(module="archiviste", action="extract_warranty", trust_default="propose")`
- **Day 1** : trust=propose -> inline buttons Telegram (Approuver/Corriger/Ignorer)
- **Promotion** : propose -> auto si accuracy >=95% sur 3 semaines (Story 1.8)
- **Retrogradation** : auto -> propose si accuracy <90% + echantillon >=10

---

## Securite RGPD

1. **Presidio anonymise** le texte OCR AVANT appel Claude
2. **Fail-explicit** : NotImplementedError si Presidio crash (JAMAIS de fallback silencieux)
3. **Deanonymisation** apres extraction pour vendor/item_name
4. **Mapping ephemere** : Redis TTL 15min (pas PostgreSQL)

---

## Heartbeat Check

**Schedule** : Daily 02:00 UTC (cron via nightly.py)

| Seuil | Priorite | Quiet Hours |
|-------|----------|-------------|
| 60 jours | MEDIUM | Respecte (22h-8h) |
| 30 jours | HIGH | Respecte (22h-8h) |
| 7 jours | CRITICAL | **Ignore** quiet hours |
| 0 jours | expired | Auto-update status |

**Anti-spam** : Table `warranty_alerts` avec UNIQUE(warranty_id, alert_type) -> une seule notification par type.

---

## Commandes Telegram

| Commande | Description |
|----------|-------------|
| `/warranties` | Liste toutes garanties actives groupees par categorie |
| `/warranty_expiring` | Garanties expirant dans <60 jours |
| `/warranty_stats` | Statistiques agregees (total, montant, prochaine expiration) |

### Inline Buttons (topic Actions)

| Bouton | Action |
|--------|--------|
| Approuver | Confirme la garantie detectee |
| Corriger | Invite l'utilisateur a corriger (dates, montants) |
| Ignorer | Supprime la garantie (faux positif) |

---

## Redis Events

**Transport** : Redis Streams (evenement critique)

```json
{
  "event_type": "warranty.extracted",
  "warranty_id": "uuid",
  "document_id": "uuid",
  "item_name": "HP DeskJet 3720",
  "item_category": "electronics",
  "confidence": "0.92",
  "trust_level": "propose"
}
```

---

## Performance (AC7)

- **Timeout global** : 10s (`asyncio.wait_for`)
- **Latence cible** : <10s pipeline complet
  - Anonymisation : <1s
  - Claude API : <5s
  - DB insert : <2s
  - Notification : <1s
- **Logs structures** : `extract_duration_ms`, `db_insert_duration_ms`, `total_latency_ms`

---

## Tests

| Type | Fichier | Tests |
|------|---------|-------|
| Unit | test_warranty_extractor.py | 18 |
| Unit | test_warranty_db.py | 12 |
| Unit | test_warranty_orchestrator.py | 11 |
| Unit | test_heartbeat_warranty_expiry.py | 14 |
| Integration | test_warranty_pipeline.py | 5 |
| E2E | test_warranty_tracking_e2e.py | 7 |
| **Total** | | **67** |

**Pyramide** : 55 unit (82%) + 5 integration (7%) + 7 E2E (10%)

---

## Budget Claude API

~$2.70/mois (150k tokens/mois, 20 documents/jour x 500 tokens/doc)

Budget total Friday : ~$27.36/mois (Stories 3.1-3.4) sous seuil $45.

---

**Version** : 1.0.0 (2026-02-16)
**Story** : 3.4 - Suivi Garanties
**Epic** : 3 - Archiviste & Recherche Documentaire
