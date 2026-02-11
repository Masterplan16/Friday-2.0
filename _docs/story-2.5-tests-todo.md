# Story 2.5 - Tests Restants TODO

**Date création :** 2026-02-11
**Status :** ✅ Tests unitaires 100% | ⏸️ Tests DB/E2E en attente

---

## ✅ Complété

- [x] **Tests unitaires** : 45/45 PASS (100%) — commit 0645a97
  - test_draft_reply.py : 18/18 ✓
  - test_prompts_draft_reply.py : 16/16 ✓
  - test_emailengine_client_send.py : 11/11 ✓
- [x] **Code review** : APPROVED (0 bug critique)
- [x] **Documentation** : README, code review, specs, guide utilisateur
- [x] **Commit** : 0645a97 feat(story-2.5): implement email draft reply

---

## ⏸️ TODO Avant Production

### 1. Tests Intégration DB (6 tests)

**Fichier :** `tests/unit/database/test_migration_032_writing_examples.py`

**Prérequis :**
```bash
# 1. Appliquer migrations
python scripts/apply_migrations.py

# 2. Vérifier PostgreSQL
docker ps | grep friday-postgres
# Port: 5433 (pas 5432 par défaut)

# 3. Lancer tests
pytest tests/unit/database/test_migration_032_writing_examples.py -v
```

**Fixes nécessaires :**
- Aucun (tests déjà prêts, juste besoin de DB)

**Durée estimée :** 5 min

---

### 2. Tests E2E (3 tests critiques)

**Fichier :** `tests/e2e/test_draft_reply_critical.py`

**Prérequis :**
```bash
# 1. Démarrer services
docker compose up -d postgres redis emailengine presidio-analyzer presidio-anonymizer

# 2. Attendre healthcheck
docker compose ps | grep healthy

# 3. Corriger port PostgreSQL dans tests
# Remplacer port=5432 par port=5433 dans test_draft_reply_critical.py:27

# 4. Enlever pytest.skip() ligne 20
# Commenter ou supprimer: pytest.skip("E2E tests requièrent...", allow_module_level=True)

# 5. Lancer tests
pytest tests/e2e/test_draft_reply_critical.py -v --run-e2e
```

**Fixes nécessaires :**
1. ✅ Imports Presidio corrigés (`anonymize_text` vs `presidio_anonymize`) — FAIT
2. ✅ Mocks AnonymizationResult ajoutés — FAIT
3. ⏭️ **TODO : Corriger port PostgreSQL 5432 → 5433** (ligne 27)
4. ⏭️ **TODO : Enlever pytest.skip()** (ligne 20)

**Durée estimée :** 15 min

---

### 3. Validation RGPD Critique

**Test spécifique :** `test_e2e_presidio_anonymization_end_to_end`

**Objectif :** Vérifier que PII n'est JAMAIS envoyée à Claude en clair

**Validations critiques :**
- [ ] Email avec PII (nom, email, SSN) anonymisé AVANT Claude
- [ ] Prompt envoyé à Claude contient UNIQUEMENT placeholders
- [ ] Réponse Claude dé-anonymisée correctement
- [ ] PII restaurée dans draft final
- [ ] Aucun placeholder résiduel

**Durée estimée :** 10 min

---

## 📋 Checklist Complète Avant Production

### Infrastructure
- [ ] PostgreSQL 16 + pgvector (port 5433)
- [ ] Redis 7 (port 6379)
- [ ] EmailEngine API (port 3000)
- [ ] Presidio Analyzer (port 5001)
- [ ] Presidio Anonymizer (port 5002)

### Migrations
- [ ] Migration 032 appliquée (table core.writing_examples)
- [ ] Migrations 001-031 appliquées (dépendances)

### Variables Environnement
- [ ] `ANTHROPIC_API_KEY` configurée
- [ ] `PRESIDIO_ANALYZER_URL` = http://presidio-analyzer:5001
- [ ] `PRESIDIO_ANONYMIZER_URL` = http://presidio-anonymizer:5002
- [ ] `EMAILENGINE_URL` = http://emailengine:3000
- [ ] `EMAILENGINE_SECRET` configuré
- [ ] `DATABASE_URL` configurée (port 5433)

### Tests
- [x] Tests unitaires : 45/45 ✓
- [ ] Tests migration DB : 6/6
- [ ] Tests E2E : 3/3
- [ ] Tests E2E RGPD bout-en-bout validés

### Documentation
- [x] README Story 2.5
- [x] Code review
- [x] Spécifications
- [x] Guide utilisateur Telegram
- [ ] Notes déploiement production (à créer)

---

## 🚀 Commandes Rapides

### Lancer tests DB
```bash
docker compose up -d postgres
sleep 5
python scripts/apply_migrations.py
pytest tests/unit/database/test_migration_032_writing_examples.py -v
```

### Lancer tests E2E
```bash
# Démarrer infra complète
docker compose up -d

# Corriger port + enlever skip
sed -i 's/port=5432/port=5433/' tests/e2e/test_draft_reply_critical.py
sed -i '20s/^/# /' tests/e2e/test_draft_reply_critical.py  # Commenter skip

# Lancer tests
pytest tests/e2e/test_draft_reply_critical.py -v --tb=short
```

### Vérifier healthcheck complet
```bash
docker compose ps
curl http://localhost:5001/health  # Presidio Analyzer
curl http://localhost:5002/health  # Presidio Anonymizer
curl http://localhost:3000/health  # EmailEngine
psql -h localhost -p 5433 -U postgres -d friday_test -c "SELECT 1"  # PostgreSQL
redis-cli -p 6379 ping  # Redis
```

---

## 📝 Notes

- Tests unitaires 100% = **largement suffisant** pour valider code Story 2.5
- Tests DB/E2E = **nice to have** mais pas bloquants pour merge
- Tests E2E **CRITIQUES pour production** (validation RGPD bout-en-bout)
- Prévoir 30 min total pour tests DB + E2E lors du déploiement VPS

---

**Créé par :** Claude Code
**Dernière mise à jour :** 2026-02-11
**Status :** TODO actif (ne pas oublier !)
