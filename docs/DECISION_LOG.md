# Decision Log - Friday 2.0

**Purpose** : Historique chronologique des décisions architecturales majeures

---

## 2026-02-05 : Code Review Adversarial v2 - Corrections multiples

**Décisions** :
1. **VPS-4 coût réel** : 25,5€ TTC/mois (corrigé partout, était ~24-25€)
2. **Volume emails réel** : 110 000 mails (pas 55k) → coût migration $20-24 USD, durée 18-24h
3. **Apple Watch hors scope** : Complexité excessive, pas d'API serveur → réévaluation >12 mois
4. **Zep → PostgreSQL + Qdrant** : Zep fermé (2024), Graphiti immature → Day 1 = PostgreSQL (knowledge.*) + Qdrant via `adapters/memorystore.py`
5. **Redis Streams vs Pub/Sub clarifié** : Streams = critiques (delivery garanti), Pub/Sub = informatifs (fire-and-forget)
6. **Migration SQL 012 créée** : Table `ingestion.emails_legacy` pour import bulk 110k emails

**Documents impactés** :
- `_docs/friday-2.0-analyse-besoins.md`
- `_docs/architecture-friday-2.0.md` (15+ corrections Zep)
- `docs/implementation-roadmap.md`
- `scripts/migrate_emails.py`
- `database/migrations/012_ingestion_emails_legacy.sql` (créé)

**Raison** : Revue adversariale a identifié 17 issues (6 critiques, 7 moyennes, 4 mineures). Corrections appliquées avant démarrage Story 1.

---

## 2026-02-05 : Code Review Adversarial v1 - 22 issues corrigées

**Décisions** :
1. n8n version = 1.69.2+ (pas 2.4.8)
2. LangGraph version = 0.2.45+ (pas 1.2.0)
3. Mistral model IDs = suffixe -latest
4. correction_rules : UUID PK + scope/priority/source_receipts/hit_count
5. Redis = Streams pour critique, Pub/Sub pour informatif
6. Socle RAM = ~7-9 Go (inclut Zep+EmailEngine+Presidio+Caddy+OS)
7. monitor-ram.sh seuil = 85%
8. Dossier agent = archiviste/ (pas archiver/)
9. Migrations SQL Story 1 = 001-010 (inclut core.tasks + core.events)
10. Tailscale 2FA + device authorization obligatoire
11. Redis ACL moindre privilège par service
12. Mapping Presidio éphémère (jamais stocké)

**Documents impactés** : Multiples (voir CODE_REVIEW_FIXES_2026-02-05.md)

---

## 2026-02-04 : Finalisation Trust Layer

**Décision** : Story 1.5 Observability & Trust Layer AVANT tout module métier

**Composants** :
- Décorateur `@friday_action` obligatoire
- 3 trust levels : auto/propose/blocked
- ActionResult Pydantic model
- Feedback loop via correction_rules (50 max, pas de RAG)
- Rétrogradation auto si accuracy <90% (sample ≥10)

**Documents impactés** :
- `config/trust_levels.yaml` (créé)
- `database/migrations/011_trust_system.sql` (créé)
- `CLAUDE.md` (section Trust Layer)

---

## 2026-02-02 : Architecture complète validée

**Décision** : Stack technique final

**Stack** :
- Python 3.12 + LangGraph 0.2.45+ + n8n 1.69.2+
- PostgreSQL 16 (3 schemas : core, ingestion, knowledge)
- Redis 7 (Streams + Pub/Sub)
- Qdrant (vectorstore)
- Mistral (LLM cloud + Ollama local)
- Telegram (interface principale)
- Tailscale (VPN mesh)

**Documents impactés** :
- `_docs/architecture-friday-2.0.md` (~2500 lignes)
- `_docs/architecture-addendum-20260205.md` (sections 1-10)

---

## 2026-02-01 : Analyse besoins complète

**Décision** : 23 modules fonctionnels répartis en 4 couches

**Modules prioritaires** :
1. Moteur Vie (email pipeline)
2. Archiviste (OCR + renommage)
3. Briefing matinal
4. Tuteur Thèse
5. Veilleur Droit
6. Suivi Financier

**Documents impactés** :
- `_docs/friday-2.0-analyse-besoins.md`

---

## Format des entrées futures

```markdown
## YYYY-MM-DD : Titre décision

**Décision** : Description courte

**Raison** : Pourquoi cette décision

**Alternatives considérées** :
- Option A : rejetée car X
- Option B : retenue car Y

**Documents impactés** :
- `chemin/fichier1.md`
- `chemin/fichier2.py`

**Rollback plan** (si applicable) : Comment revenir en arrière
```

---

**Dernière mise à jour** : 2026-02-05
**Version** : 1.0.0
