# Decision Log - Friday 2.0

**Purpose** : Historique chronologique des décisions architecturales majeures

---

## 2026-02-08 : Self-Healing Infrastructure - Automatisation 4 Tiers

**Décision** : Implémenter Story 1.7 avec architecture à 4 tiers (Tier 1-2 Day 1, Tier 3-4 progressifs)

**Problématique identifiée** :
- Maintenance Friday 2.0 estimée à 2-4h/mois (monitoring, mises à jour, connecteurs cassés)
- Risque fatigue opérationnelle sur projet long terme (10 ans visés)
- Question Antonio : *"Est-ce que la maintenance peut s'automatiser ?"*

**Architecture retenue** :

**Philosophie** : Automatiser le "contenant" (infrastructure), garder la main sur le "contenu" (logique métier)

| Tier | Niveau | Automatisation | Validation humaine | Gain temps/mois |
|------|--------|----------------|-------------------|-----------------|
| **Tier 1** | OS/Linux | ✅ Auto (unattended-upgrades, cleanup) | ❌ Aucune | ~45 min |
| **Tier 2** | Services Docker | ✅ Auto-restart + Alerte | ⚠️ Après coup | ~60 min |
| **Tier 3** | Connecteurs externes | ❌ Détection uniquement | ✅ Avant fix | ~35 min |
| **Tier 4** | Logique métier | ❌ Proposition uniquement | ✅ Obligatoire | ~50 min |

**Total gain** : ~3h/mois (maintenance résiduelle : ~1h/mois validations Tier 4)

**Composants Tier 1-2 (Day 1 - Story 1.7)** :
- `unattended-upgrades` : Mises à jour sécurité Linux auto + reboot 4h
- `cleanup-disk.sh` : Nettoyage logs/backups (cron 3h)
- `watchtower` : Détection nouvelles versions Docker (mode MONITOR_ONLY)
- `monitor-restarts.sh` : Alerte redémarrages anormaux (cron 15min)
- `auto-recover-ram.sh` : Kill service lourd si RAM >90% (cron 5min)
- `check-external-apis.sh` : Healthcheck APIs externes (cron 30min)

**Composants Tier 3-4 (progressif - Stories futures)** :
- `check-playwright-scripts.sh` : Test login Carrefour (sans action réelle)
- `pattern_detector.py` : Détection patterns corrections (proposition règles)
- `trust_drift_detector.py` : Alerte baisse accuracy modules

**Rationale** :
- **Infrastructure fail-safe** : Services crashent → Redémarrent auto. RAM critique → Tue service lourd auto (préserve PostgreSQL/Gateway)
- **Logique fail-explicit** : Presidio crash → STOP + alerte. Playwright cassé → Alerte + fix manuel (évite commande erronée Carrefour)
- **Validation humaine préservée** : Cohérent avec Trust Layer (humain dans la boucle pour décisions métier)
- **RGPD/Médical** : Panne franche > réparation auto risquée (zéro tolérance erreurs silencieuses)

**Alternatives considérées** :
1. **Zero Maintenance (auto-fix tout)** : Rejetée car risque dérive silencieuse (ex: auto-adjust prompts → perte qualité invisible)
2. **Kubernetes + rolling updates** : Rejetée car budget (50€/mois) incompatible cluster multi-nœuds
3. **Tier 1-2 auto (retenue) + Tier 3-4 détection/alerte** : Équilibre stabilité/contrôle optimal

**Frontière critique** :
```
CONTENANT (Auto OK) :
- Patch kernel Linux → Auto + reboot 4h
- PostgreSQL 16.6→16.7 (bugfix) → Détection auto, upgrade manuel
- Redémarrage Redis crashé → Auto (Docker restart policy)
- RAM >90% → Kill Kokoro TTS auto + alerte

CONTENU (Manuel obligatoire) :
- n8n 1.69→1.70 → Manuel (breaking changes possibles)
- LangGraph 0.2.45→0.3.0 → Manuel (API change)
- Script carrefour_drive.py cassé → Détection + fix manuel (risque 50 paquets pâtes)
- Prompt système email classifier → Proposition via Trust Layer (dérive silencieuse)
```

**Documents impactés** :
- `docs/DECISION_LOG.md` (ce fichier)
- `docs/implementation-roadmap.md` (ajout Story 1.7)
- `CLAUDE.md` (section First Implementation Priority)
- `scripts/tier1-os/setup-unattended-upgrades.sh` (à créer)
- `scripts/tier2-docker/monitor-restarts.sh` (à créer)
- `scripts/tier2-docker/auto-recover-ram.sh` (à créer)
- `docker-compose.services.yml` (ajout watchtower)
- `config/crontab-friday.txt` (à créer - centralise tous crons)

**Implémentation** : Story 1.7 (8-12h dev + tests) après Story 1.5, avant Story 2

**Rollback plan** : Si auto-recovery RAM cause instabilités → Désactiver `auto-recover-ram.sh`, garder alerting uniquement

**Ressources** :
- Discussion Gemini analyse : 2026-02-08 (comparaison Friday vs OpenClaw, maintenance)
- Consultation BMad Master : 2026-02-08 (proposition 4 tiers)

---

## 2026-02-05 : Stratégie de Notification - Telegram Topics Architecture

**Décision** : Supergroup Telegram avec 5 topics spécialisés (vs canal unique initial)

**Problématique identifiée** :
- Architecture initiale : "canal unique Telegram + progressive disclosure"
- Risque critique : Chaos informationnel si tout mélangé (alertes système + validations trust + heartbeat + métriques + conversations)
- Question Antonio : *"Si tout arrive sur le même canal que le bot... tout ça risque d'être illisible"*

**Architecture retenue** :

Supergroup "Friday 2.0 Control" avec **5 topics** :

1. **💬 Chat & Proactive** (DEFAULT, bidirectionnel)
   - Conversations Antonio ↔ Friday
   - Commandes (`/status`, `/journal`, etc.)
   - Heartbeat proactif (Friday initie)
   - Reminders et suggestions

2. **📬 Email & Communications**
   - Classifications email (auto)
   - Pièces jointes détectées
   - Emails urgents

3. **🤖 Actions & Validations**
   - Actions trust=propose (inline buttons)
   - Corrections appliquées
   - Trust level changes

4. **🚨 System & Alerts**
   - RAM >85%, services down
   - Pipeline errors critiques
   - Security events

5. **📊 Metrics & Logs**
   - Actions auto (trust=auto)
   - Métriques nightly
   - Logs non-critiques

**Rationale** :
- **Séparation Signal vs Noise** : Antonio peut muter topics non-urgents selon contexte (Mode Focus, Deep Work, Vacances)
- **Conversation continue** : Topic 1 bidirectionnel préserve contexte (heartbeat → question → réponse dans même fil)
- **Pas de quiet hours codées** : Utiliser fonctionnalités natives téléphone (DND, Focus modes)
- **Filtrage granulaire** : Par module (email, finance, thesis) + priorité (critical, warning, info)

**Alternatives considérées** :
1. **Canal unique avec filtrage intelligent** : Rejetée car impossibilité de mute sélectif (tout ou rien)
2. **2-3 canaux séparés** : Rejetée car perte de contexte entre canaux, Antonio préfère topics
3. **6 topics (Chat + Proactive séparés)** : Rejetée car fragmente conversation naturelle
4. **5 topics avec fusion Chat + Proactive** : Retenue (suggestion Antonio validée par équipe)

**Routing Logic** :
```python
if event.source in ["heartbeat", "proactive"] → Chat & Proactive
elif event.module in ["email", "desktop_search"] → Email & Communications
elif event.type.startswith("action.") → Actions & Validations
elif event.priority in ["critical", "warning"] → System & Alerts
else → Metrics & Logs
```

**Impact Stories** :
- **Story 1.5** : Alerting service doit router multi-topics (+4h dev, +2h tests)
- **Story 2.5** : Heartbeat s'affiche dans Chat & Proactive (compatible)
- **Nouvelle Story 1.6** : Telegram Topics Implementation (17-18h total)
  - 1.6.1 : Documentation (6h)
  - 1.6.2 : Setup supergroup manuel Antonio (15min)
  - 1.6.3 : Bot routing implementation (4h dev + 1h tests)
  - 1.6.4 : Inline buttons + commands (3h dev + 1h tests)
  - 1.6.5 : E2E testing + deployment (2h tests + 1h deploy)

**Bénéfices** :
- ✅ Filtrage granulaire (mute selon contexte utilisateur)
- ✅ Conversation continue préservée (Topic 1 bidirectionnel)
- ✅ Séparation critique vs informatif (Topic 4 vs Topic 5)
- ✅ Contrôle natif Telegram (mute/unmute, notifications par topic)
- ✅ Scalabilité : Ajout topic si besoin (ex: "Finance" si volume élevé)

**Documents impactés** :
- `_docs/architecture-addendum-20260205.md` (section 11 créée)
- `CLAUDE.md` (section Observability & Trust Layer mise à jour)
- `docs/DECISION_LOG.md` (ce fichier)
- `docs/telegram-topics-setup.md` (à créer - Story 1.6.1)
- `docs/telegram-user-guide.md` (à créer - Story 1.6.1)

**Rollback plan** : Si complexité topics trop élevée → Revenir à 2 canaux séparés (Control + Logs)

**Ressources** :
- Discussion complète : Session Party Mode 2026-02-05 (Antonio + Winston + Mary + Amelia)
- Diagramme architecture : Section 11.2 addendum (Mermaid)
- Configuration technique : Section 11.6 addendum (`config/telegram.yaml`)

---

## 2026-02-05 : Décision OpenClaw - Friday Natif + Heartbeat custom

**Décision** : Rejeter intégration OpenClaw Day 1, implémenter Heartbeat natif dans Friday

**Raison** :
- Score décisionnel Antonio : 20/100 points
  - Multi-chat (WhatsApp, Discord) : NON → +0
  - Skills identifiées (≥10) : NON → +0
  - Heartbeat critique Day 1 : OUI → +20
  - Risque acceptable : INCERTAIN → +0
- ROI négatif : Coût intégration (70h) vs bénéfice unique heartbeat (10h économisées)
- Risque supply chain : 341/2857 skills malicieux (12% registry ClawHub)
- Redondances : OpenClaw n'apporte rien que Friday n'ait déjà (Trust Layer, Presidio, mémoire persistante)

**Alternatives considérées** :
1. **OpenClaw complet Day 1** : Rejetée car coût 70h + risques moyens + ROI -86% pour seul bénéfice heartbeat
2. **OpenClaw POC avril (Phase 1)** : Rejetée car Antonio n'a pas besoin multi-chat ni skills
3. **Heartbeat natif Friday (retenue)** : Coût 10h, zéro risque, contrôle total, intégration native Trust Layer

**Implémentation retenue** :
- **Story 2.5 : Heartbeat Engine natif** (~10h dev)
  - Class `FridayHeartbeat` avec interval configurable
  - LLM décide dynamiquement quoi vérifier (vs cron fixe)
  - Registration checks avec priorités (high/medium/low)
  - Context-aware (heure, dernière activité, calendrier)
  - Intégration native Trust Layer + Telegram

**Bénéfices vs OpenClaw** :
- ✅ Contrôle total code (pas de dépendance externe)
- ✅ Intégration native `@friday_action` decorator
- ✅ Pas de risque supply chain
- ✅ Maintenance 2h/an vs 20h/an OpenClaw
- ✅ Debugging 1 système vs 2 systèmes
- ✅ Coût 10h vs 70h (-86%)

**Porte de sortie** : Réévaluation OpenClaw août 2026 si besoins évoluent (multi-chat, skills auditées identifiées)

**Documents impactés** :
- `docs/DECISION_LOG.md` (ce fichier)
- `agents/docs/heartbeat-engine-spec.md` (à créer - Story 2.5)
- `_docs/architecture-addendum-20260205.md` (section 4 OpenClaw mise à jour)
- `CLAUDE.md` (ajout Story 2.5 timeline)
- `_docs/analyse-fonctionnelle-complete.md` (section Heartbeat transversal)

**Rollback plan** : Si Heartbeat natif insuffisant en Q3 2026 → POC OpenClaw avec defense-in-depth (Docker hardenée + Presidio)

**Ressources** :
- Analyse comparative complète : Session Party Mode 2026-02-05
- Documentation OpenClaw récente : v2026.2.3 (février 2026)
- Score décisionnel : <30 points → Option 1 (Friday natif)

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
