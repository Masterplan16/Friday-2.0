# Story 6.2 - Guide Séparation Git (Issue #1 CRITICAL)

**Date** : 2026-02-11
**Issue** : Contamination cross-story (5 fichiers Story 2.1 mélangés avec Story 6.2)
**Status** : BLOCKER - Action manuelle requise avant merge

---

## 🚨 Problème Identifié

Le dernier commit `5bc8f73` est **Story 2.1** (EmailEngine Integration), pas Story 6.2.
5 fichiers de Story 2.1 sont présents dans `git status` modifié, créant une contamination cross-story.

**Fichiers Story 2.1 contaminés** :
```
M database/migrations/024_emailengine_accounts.sql
M services/email-processor/consumer.py
M services/gateway/routes/webhooks.py
?? tests/unit/email-processor/
?? tests/unit/gateway/test_webhooks_emailengine.py
```

**Fichiers Story 6.2** (17 fichiers) :
```
M _bmad-output/implementation-artifacts/6-2-embeddings-pgvector.md
M _bmad-output/implementation-artifacts/sprint-status.yaml
M agents/src/agents/email/graph_populator.py
M agents/src/adapters/vectorstore.py
M tests/unit/adapters/test_vectorstore.py
M tests/unit/email/test_email_embeddings.py

+ 11 nouveaux fichiers créés (voir File List dans story)
```

---

## ✅ Solution Recommandée

### **Option A : Commits séparés (RECOMMANDÉ)**

Créer 2 commits distincts sur la branche actuelle, puis 2 PRs séparées.

```bash
# 1. Vérifier état actuel
git status

# 2. Commit Story 2.1 SEULEMENT (5 fichiers)
git add database/migrations/024_emailengine_accounts.sql
git add services/email-processor/consumer.py
git add services/gateway/routes/webhooks.py
git add tests/unit/email-processor/
git add tests/unit/gateway/test_webhooks_emailengine.py

git commit -m "feat(story-2.1): Integration EmailEngine & Reception complete

- Migration 024: table ingestion.email_accounts (pgcrypto encrypted credentials)
- Email processor consumer: Redis Streams → EmailEngine fetch → Presidio anonymize → PostgreSQL
- Gateway webhook: EmailEngine messageNew → signature HMAC validation → Redis publish
- Tests: 5+ unit tests email-processor + gateway webhooks

Story: 2.1 - EmailEngine Integration & Reception
Epic: 2 - Pipeline Email Intelligent

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# 3. Commit Story 6.2 (17 fichiers)
git add _bmad-output/implementation-artifacts/6-2-embeddings-pgvector.md
git add _bmad-output/implementation-artifacts/sprint-status.yaml
git add agents/src/agents/email/graph_populator.py
git add agents/src/adapters/vectorstore.py
git add agents/src/agents/archiviste/
git add tests/unit/adapters/test_vectorstore.py
git add tests/unit/email/test_email_embeddings.py
git add tests/unit/archiviste/
git add services/gateway/routes/search.py
git add bot/handlers/search.py
git add services/metrics/api_usage.py
git add docs/embeddings-pgvector.md

# (Vérifier qu'il ne reste rien dans git status avant de commit)
git status

git commit -m "feat(story-6.2): Embeddings pgvector + code review fixes

IMPLEMENTATION:
- Adaptateur vectorstore.py (VoyageAIAdapter + PgvectorStore, 700 lignes)
- Integration Email: graph_populator.py génère embeddings automatiquement
- Integration Archiviste: embedding_generator.py avec chunking documents >10k
- API Gateway: /api/v1/search/semantic endpoint
- Telegram /search handler (stub)
- Tests: 25 PASS (18 vectorstore + 3 email + 4 archiviste)

CODE REVIEW FIXES (12 issues - 11 fixed):
- Issue #2: Test count corrected (25 tests not 24)
- Issue #3-4: AC6/AC7 status updated (PARTIEL not COMPLET)
- Issue #6: Double anonymisation optimized (store results, reuse)
- Issue #8: @pytest.mark.integration décommentés
- Issue #9: Magic numbers → constantes (VOYAGE_DIMENSIONS_DEFAULT, etc.)
- Issue #10: Logging standardized (structlog everywhere)
- Issue #11: Documentation TODO annotated

ACCEPTANCE CRITERIA:
- ✅ AC1-5: COMPLET (embeddings auto, pgvector incremental, search API, adaptateur, integration)
- ⏸️ AC6-7: PARTIEL (monitoring stubs, integration/E2E tests TODO)

Story: 6.2 - Embeddings pgvector
Epic: 6 - Mémoire Éternelle & Migration
Review: BMAD Adversarial Review (12 issues, 11 fixed)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# 4. Vérifier les 2 commits
git log --oneline -3

# 5. Créer 2 PRs séparées (via gh CLI ou GitHub web)
# PR 1: Story 2.1
gh pr create --base master --head <current-branch> --title "feat(story-2.1): EmailEngine Integration & Reception" --body "$(cat <<'EOF'
## Story 2.1 - EmailEngine Integration & Reception

**Epic**: 2 - Pipeline Email Intelligent
**Acceptance Criteria**: AC1-3 complets

### Changements
- ✅ Migration 024: `ingestion.email_accounts` table
- ✅ Email processor consumer: Pipeline Redis → EmailEngine → PostgreSQL
- ✅ Gateway webhook: EmailEngine → Gateway avec HMAC validation

### Tests
- 5+ unit tests (email-processor + gateway webhooks)

### Fichiers modifiés (5)
- `database/migrations/024_emailengine_accounts.sql`
- `services/email-processor/consumer.py`
- `services/gateway/routes/webhooks.py`
- `tests/unit/email-processor/`
- `tests/unit/gateway/test_webhooks_emailengine.py`
EOF
)"

# PR 2: Story 6.2 (après merge de PR 1)
# À créer APRÈS que PR 1 soit mergée pour éviter conflits
```

---

### **Option B : Branches séparées (Alternative)**

Si vous préférez séparer physiquement en branches :

```bash
# 1. Créer branch pour Story 2.1
git checkout -b story-2.1-emailengine

# 2. Stash les changements Story 6.2
git stash push -m "Story 6.2 changes" \
  _bmad-output/ agents/src/adapters/vectorstore.py \
  agents/src/agents/archiviste/ tests/unit/adapters/ \
  tests/unit/email/ tests/unit/archiviste/ \
  services/gateway/routes/search.py bot/handlers/search.py \
  services/metrics/api_usage.py docs/embeddings-pgvector.md

# 3. Commit Story 2.1 sur cette branch
git add database/migrations/024_emailengine_accounts.sql
git add services/email-processor/consumer.py
git add services/gateway/routes/webhooks.py
git add tests/unit/email-processor/
git add tests/unit/gateway/test_webhooks_emailengine.py

git commit -m "feat(story-2.1): EmailEngine Integration & Reception complete

[Même message commit qu'Option A]"

# 4. Push + PR Story 2.1
git push -u origin story-2.1-emailengine
gh pr create --base master --title "feat(story-2.1): EmailEngine Integration"

# 5. Retour à master et créer branch Story 6.2
git checkout master
git checkout -b story-6.2-embeddings-pgvector

# 6. Appliquer stash Story 6.2
git stash pop

# 7. Commit Story 6.2
git add [tous les fichiers Story 6.2]
git commit -m "feat(story-6.2): Embeddings pgvector + code review fixes

[Même message commit qu'Option A]"

# 8. Push + PR Story 6.2
git push -u origin story-6.2-embeddings-pgvector
gh pr create --base master --title "feat(story-6.2): Embeddings pgvector"
```

---

## 📋 Checklist Validation

Avant de créer les PRs, vérifier :

- [ ] `git status` sur branch Story 2.1 montre SEULEMENT 5 fichiers Story 2.1
- [ ] `git status` sur branch Story 6.2 montre SEULEMENT 17 fichiers Story 6.2
- [ ] `git log --oneline` montre commits bien séparés avec messages clairs
- [ ] Aucun fichier `.pyc`, `__pycache__`, `.env` dans les commits
- [ ] Commits signés avec Co-Authored-By Claude
- [ ] Tests passent : `pytest tests/unit/` (pour vérifier pas de régression)

---

## 🎯 Résultat Attendu

**Après séparation** :
- ✅ 2 commits distincts (ou 2 branches)
- ✅ 2 PRs séparées
- ✅ Traçabilité claire (1 story = 1 PR)
- ✅ Code review possible fichier par fichier
- ✅ Merge indépendant (Story 2.1 peut merger avant 6.2)

---

## 📚 Références

- **Story 2.1 file** : `_bmad-output/implementation-artifacts/2-1-emailengine-integration.md`
- **Story 6.2 file** : `_bmad-output/implementation-artifacts/6-2-embeddings-pgvector.md`
- **Code Review Report** : Section "Code Review Findings" dans story 6.2
- **Sprint Status** : `_bmad-output/implementation-artifacts/sprint-status.yaml`

---

**Date création guide** : 2026-02-11
**Créé par** : BMAD Code Review Workflow (Claude Sonnet 4.5)
