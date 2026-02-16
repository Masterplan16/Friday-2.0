# Quality Gates - Friday 2.0

**Version:** 1.0.0
**Last Updated:** 2026-02-16

## 🎯 Test Priority Matrix

Friday 2.0 utilise une matrice de priorité à 4 niveaux basée sur le risque et l'impact.

### Priority Levels

| Priority | Criticité | Pass Rate Required | Exécution | Exemples |
|----------|-----------|-------------------|-----------|----------|
| **P0** | CRITIQUE | **100%** | Toujours | Auth, email reception, database integrity, data loss prevention |
| **P1** | HAUTE | **≥ 95%** | Toujours | Email classification, file archiving, calendar conflicts, migrations |
| **P2** | MOYENNE | **≥ 90%** | PR + Nightly | Semantic search, metadata extraction, embeddings |
| **P3** | BASSE | **≥ 85%** | Nightly only | UI polish, documentation, non-critical optimizations |

## 🔒 Mandatory Gates (Block Merge)

### Gate 1: Lint & Code Quality
**Requirement:** 100% pass rate

- `black` - Formatting check
- `isort` - Import sorting
- `flake8` - Linting (zero F401 imports)
- `mypy` - Type checking (warnings OK, migration progressive)
- `sqlfluff` - SQL linting (legacy migrations warnings OK)

**Failure Action:** Block PR merge, display inline errors

---

### Gate 2: Unit Tests
**Requirement:** ≥ 95% pass rate (all P0 + P1 tests)

- Parallel execution across 4 shards × 2 Python versions
- Coverage minimum: 80% overall, 90% pour modules P0/P1
- Execution time limit: 20 min per shard (timeout = fail)

**Failure Action:** Block PR merge, upload failure artifacts

---

### Gate 3: Integration Tests
**Requirement:** ≥ 95% pass rate

- PostgreSQL + Redis services
- All database migrations applied successfully
- P0/P1 integration scenarios pass

**Failure Action:** Block PR merge, upload DB dump + logs

---

### Gate 4: Burn-In (Flaky Detection)
**Requirement:** 10/10 iterations pass (100%)

- Trigger: PRs to master OU schedule hebdomadaire
- Scope: All unit + integration tests
- Reset DB between iterations

**Failure Action:**
- Block PR merge if < 8/10 iterations pass
- Warning if 8-9/10 iterations pass (manual review required)
- Upload iteration-specific failure artifacts

---

## 📊 Quality Gate Enforcement

Le pipeline `test.yml` inclut un job `report` qui enforce ces gates :

```yaml
- name: Quality Gate - Enforce Success
  run: |
    LINT_STATUS="${{ needs.lint.result }}"
    UNIT_STATUS="${{ needs.test-unit.result }}"
    INTEGRATION_STATUS="${{ needs.test-integration.result }}"

    if [ "$LINT_STATUS" != "success" ]; then
      echo "::error::❌ Quality Gate FAILED: Lint stage did not pass"
      exit 1
    fi

    if [ "$UNIT_STATUS" != "success" ]; then
      echo "::error::❌ Quality Gate FAILED: Unit tests did not pass"
      exit 1
    fi

    if [ "$INTEGRATION_STATUS" != "success" ]; then
      echo "::error::❌ Quality Gate FAILED: Integration tests did not pass"
      exit 1
    fi

    echo "::notice::✅ Quality Gate PASSED - All critical stages successful"
```

---

## 🚨 Notifications Strategy

### Telegram Integration (Primary Channel)

Friday 2.0 utilise **Telegram System Topic** pour les notifications CI/CD.

#### Success Notifications

**Trigger:** PR merge vers master après quality gates passés

**Message Format:**
```
✅ CI/CD Success - Build #123

Pipeline: Test Pipeline
Branch: feature/xyz → master
Author: @antonio
Commit: abc1234 "Fix email classification"

📊 Results:
• Lint: ✅ Passed
• Unit Tests: ✅ 1627/1627 (100%)
• Integration Tests: ✅ 45/45 (100%)
• Burn-In: ✅ 10/10 iterations

⏱️ Duration: 12m 34s
```

#### Failure Notifications

**Trigger:** Any quality gate failure

**Message Format:**
```
❌ CI/CD Failure - Build #124

Pipeline: Test Pipeline
Branch: feature/abc
Author: @antonio
Commit: def5678 "Add new feature"

❌ Failed Stage: Unit Tests

📊 Results:
• Lint: ✅ Passed
• Unit Tests: ❌ 1596/1627 (98.1%)
  → 31 tests failed (shard 2/4)
• Integration Tests: ⏭️ Skipped
• Burn-In: ⏭️ Skipped

🔗 Artifacts:
• Test Results: [Download](https://github.com/.../artifacts/123)
• Coverage Report: [View](https://github.com/.../artifacts/124)

⚠️ Action Required: Fix failing tests before merge
```

#### Burn-In Flaky Detection

**Trigger:** Burn-in detects flaky tests (< 10/10 iterations)

**Message Format:**
```
⚠️ Flaky Tests Detected - Build #125

Pipeline: Burn-In Loop
Branch: feature/calendar-sync
Iterations: 7/10 passed (70%)

🔥 Failed Iterations: #3, #7, #9

📋 Likely Flaky Tests:
• test_conflict_detector.py::test_deduplication_same_conflict
• test_briefing_generator.py::test_chronological_order_within_section

🔗 Failure Artifacts:
• Iteration 3: [Download](...)
• Iteration 7: [Download](...)
• Iteration 9: [Download](...)

⚠️ Action Required: Fix flaky tests before merge
```

---

### GitHub Actions Notifications (Secondary)

**Enabled by default:**
- GitHub Step Summary (visual dashboard in PR)
- Inline PR comments (test failures)
- Commit status checks (red/green badges)

---

## 🔧 Webhook Configuration

### Telegram Webhook Setup

**Webhook Endpoint:** `{VPS_URL}/api/v1/webhooks/github`

**GitHub Secrets Required:**
```bash
TELEGRAM_BOT_TOKEN=<bot_token>
TELEGRAM_SUPERGROUP_ID=<chat_id>
TOPIC_SYSTEM_ID=<thread_id>  # System & Alerts topic
```

**Webhook Payload Processing:**
```python
# services/gateway/routes/webhooks.py
@router.post("/github")
async def github_webhook(payload: dict):
    event = payload["event"]
    status = payload["check_run"]["conclusion"]

    if event == "check_run" and status == "failure":
        await send_telegram_notification(
            topic_id=TOPIC_SYSTEM_ID,
            message=format_failure_message(payload)
        )

    return {"status": "ok"}
```

---

## 📈 Metrics & Reporting

### Weekly Quality Report (Automated)

**Trigger:** Cron hebdomadaire (Lundi 09:00 UTC)

**Content:**
- Total builds: X (Y% success rate)
- Average build time: Z minutes
- Flaky test count: N tests
- Test coverage trend: +/-X%
- Top failing tests (if any)

**Delivery:** Telegram Metrics topic + fichier dans `_bmad-output/test-artifacts/weekly-reports/`

---

## 🎯 Continuous Improvement

### Monthly Quality Gate Review

**Process:**
1. Analyser tendances échecs (top 10 tests flaky)
2. Ajuster thresholds si nécessaire (P1 95% → 96% ?)
3. Identifier opportunités optimisation (cache, sharding)
4. Mettre à jour cette doc

**Responsable:** Antonio (Mainteneur)
**Fréquence:** Premier lundi du mois
**Output:** PR update QUALITY_GATES.md

---

## ✅ Pre-Release Checklist

Avant chaque release vers production :

- [ ] Tous quality gates passés (100% Lint, ≥95% Unit/Integration)
- [ ] Burn-in 10/10 iterations passées (zéro flaky tests)
- [ ] Coverage ≥ 80% overall, ≥ 90% pour P0/P1 modules
- [ ] Aucun test skipped sans justification documentée
- [ ] Migrations testées (apply + rollback)
- [ ] Docker build succeeded (reproducible builds)
- [ ] Secrets rotation si nécessaire (âge > 90 jours)

---

**Version History:**
- v1.0.0 (2026-02-16): Initial version - TEA workflow refonte complète
