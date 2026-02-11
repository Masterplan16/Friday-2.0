---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-06-innovation', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish', 'step-12-complete']
workflowStatus: complete
completedAt: 2026-02-08
inputDocuments:
  # Documents principaux
  - _docs/architecture-friday-2.0.md
  - _docs/friday-2.0-analyse-besoins.md
  - _docs/analyse-fonctionnelle-complete.md
  - _docs/architecture-addendum-20260205.md
  # Documentation technique
  - docs/implementation-roadmap.md
  - docs/DECISION_LOG.md
  - docs/ai-models-policy.md
  - docs/n8n-workflows-spec.md
  - docs/testing-strategy-ai.md
  - docs/playwright-automation-spec.md
  - docs/secrets-management.md
  - docs/redis-streams-setup.md
  - docs/redis-acl-setup.md
  - docs/pc-backup-setup.md
  - docs/tailscale-setup.md
  - docs/presidio-mapping-decision.md
  - docs/telegram-topics-setup.md
  - docs/telegram-user-guide.md
  - docs/analyse-adversariale-rapport-final.md
  - docs/code-review-final-corrections.md
  # Specs agents & config
  - agents/docs/heartbeat-engine-spec.md
  - config/trust_levels.yaml
  - tests/fixtures/README.md
  # Infrastructure
  - docker-compose.yml
  - docker-compose.services.yml
  - .sops.yaml
  # Code existant
  - agents/src/tools/anonymize.py
  - agents/src/middleware/models.py
  - agents/src/middleware/trust.py
  - agents/src/adapters/memorystore.py
  - services/alerting/listener.py
  - services/metrics/nightly.py
  - services/email-processor/consumer.py
  - services/document-indexer/consumer.py
  - services/monitoring/emailengine_health.py
  # Scripts
  - scripts/apply_migrations.py
  - scripts/migrate_emails.py
  - scripts/monitor-ram.sh
  - scripts/verify_env.sh
  - scripts/setup-redis-streams.sh
  - scripts/extract_telegram_thread_ids.py
  # Migrations SQL (12 fichiers)
  - database/migrations/001-012_*.sql
  # Tests
  - tests/e2e/test_backup_restore.sh
  # Projet
  - README.md
  - CLAUDE.md
  # BMAD existant
  - _bmad-output/planning-artifacts/epics.md
documentCounts:
  briefCount: 0
  researchCount: 0
  brainstormingCount: 0
  projectDocsCount: 25
classification:
  projectType: "Self-hosted AI Personal Assistant Platform"
  domain: "Personal Productivity with Sensitive Data (Finance/Legal)"
  complexity: "high"
  projectContext: "brownfield"
  keyDriver: "RGPD + data sensitivity"
  delivery: "incremental-strict"
decisions:
  - id: D1
    description: "Apple Watch Ultra abandonee definitivement - nettoyer toutes references residuelles"
  - id: D2
    description: "Vocal STT/TTS Day 1 (Faster-Whisper + Kokoro TTS via Telegram)"
  - id: D3
    description: "Graphe de connaissances Day 1 = PostgreSQL knowledge.* + pgvector embeddings (pas Graphiti) [D19 : Qdrant remplace par pgvector Day 1]"
  - id: D4
    description: "n8n = orchestrateur/trigger, Python = logique IA metier"
  - id: D5
    description: "Desktop Search Day 1 (remonte de Month 1)"
  - id: D6
    description: "Personnalite configurable Day 1 via YAML simple (pas OpenClaw)"
  - id: D7
    description: "VIP email = commande Telegram /vip + apprentissage Trust Layer (pas YAML statique)"
  - id: D8
    description: "Arborescence documents validée (pro/finance/universite/recherche/perso), évolutive (D24 update)"
  - id: D9
    description: "Design push-first : Friday pousse tout proactivement, commandes manuelles en fallback"
  - id: D10
    description: "Liste commandes Telegram visible via /help ou message epingle"
  - id: D11
    description: "[SUPERSEDE par D17] Claude retire de la politique modeles"
  - id: D12
    description: "Ollama local retire (pas de GPU VPS, Presidio suffit, zero donnees ultra-sensibles) — libere ~8 Go RAM"
  - id: D13
    description: "[SUPERSEDE par D17] Strategie 100% Mistral (Large + Small)"
  - id: D14
    description: "[SUPERSEDE par D17] Gemini Flash retire"
  - id: D15
    description: "VPS-4 (48 Go, 25 EUR) comme baseline — cohabitation Friday 2.0 + Jarvis Friday"
  - id: D16
    description: "Cold start emails non lus = batch par lots 10-20, trust=propose, calibrage initial Friday"
  - id: D17
    description: "100% Claude Sonnet 4.5 — meilleur structured output, instruction following et consistance. Un seul modele, zero routing, budget API ~45 EUR/mois"
  - id: D18
    description: "Veille mensuelle modele LLM — benchmark automatise + alerte si modele alternatif significativement superieur"
---

> **Mis a jour 2026-02-09** : D17 (Claude remplace Mistral), D19 (pgvector remplace Qdrant Day 1)

# Product Requirements Document - Friday 2.0

**Author:** Mainteneur
**Date:** 2026-02-08

## Executive Summary

**Friday 2.0** est un ecosysteme d'intelligence personnelle auto-heberge, proactif et apprenant. Assistant IA personnel a memoire eternelle pour Mainteneur (medecin, enseignant-chercheur). Single-user, jamais commercialise.

**Differentiateur** : Second cerveau qui ingere, comprend, agit, communique, apprend et analyse — pousse l'information au bon moment sans qu'Mainteneur aille la chercher.

**Type** : Self-hosted AI Personal Assistant Platform
**Domaine** : Personal Productivity with Sensitive Data (Finance/Legal)
**Complexite** : HIGH (convergence IA multi-domaine + RGPD + contraintes hardware VPS 48 Go)
**Contexte** : Brownfield (architecture definie, code partiellement implemente)

## Success Criteria

### User Success

| ID | Critere | Mesure | Seuil | Priorite |
|----|---------|--------|-------|----------|
| US1 | Emails tries sans intervention | Accuracy classification automatique sur 4 comptes IMAP (~20 mails/jour) | >=85% accuracy, 0 email urgent manque | **CRITIQUE** (priorite #1 Mainteneur) |
| US2 | Documents retrouvables instantanement | Desktop Search semantique temps de reponse + pertinence top-5 | <3s, resultats pertinents dans top-5 | Day 1 |
| US3 | Proactivite utile | Ratio notifications Heartbeat jugees utiles par Mainteneur | >=80% notifications pertinentes | Day 1 |
| US4 | Briefing matinal complet | Agregation toutes infos necessaires pour demarrer la journee | <2min de lecture, 0 info critique manquee | Day 1 |
| US5 | Vocal operationnel | Question voix via Telegram -> reponse complete | <=30s (STT + LLM + TTS) | Day 1 |
| US6 | Theses supervisees efficacement | Suggestions methodologiques pertinentes via Google Docs API | Temps review reduit, feedback actionnable | Month 1-3 |
| US7 | Finances visibles | 5 perimetres consolides, anomalies detectees | Precision anomalies >=90%, 0 faux negatif critique | Month 1-3 |

### Technical Success

| ID | Critere | Mesure | Seuil |
|----|---------|--------|-------|
| TS1 | Stabilite systeme | Tous services operationnels sans crash ni intervention manuelle | **"Tout fonctionne sans planter"** (critere #1 Mainteneur) |
| TS2 | RAM stable | Usage memoire VPS-4 48 Go en permanence | <=85% (<=40.8 Go) |
| TS3 | RGPD respecte | PII anonymisees avant tout LLM cloud (Presidio + spaCy-fr) | 100% PII sur dataset test, 0 fuite |
| TS4 | Trust Layer fiable | Accuracy par module/action avec retrogradation automatique | >=90% accuracy, echantillon >=10 |
| TS5 | Self-healing operationnel | Services redemarrent auto, RAM auto-recovered, alertes fonctionnelles | <=1h/mois maintenance residuelle |
| TS6 | Budget respecte | Cout mensuel total (VPS + APIs cloud + veille) | <=75 EUR/mois |
| TS7 | Backup fiable | Backup quotidien chiffre + sync PC + restore teste | Restore fonctionnel teste mensuellement |

### Measurable Outcomes

**Moment "aha" defini par Mainteneur** : Quand tout fonctionne sans planter — stabilite systeme = critere de succes fondamental.

**Indicateur principal** : Pipeline email operationnel de bout en bout (reception -> anonymisation -> classification -> extraction PJ -> archivage -> notification Telegram) sans intervention humaine et sans crash.

**Validation MVP** : Friday tourne 7 jours consecutifs sans intervention manuelle, emails correctement traites, briefing matinal envoye chaque jour, Heartbeat fonctionnel, aucun service down non-recupere.

## Product Scope

### MVP - Day 1

Infrastructure et premiers modules metier formant un systeme autonome et stable.

| Composant | Description |
|-----------|-------------|
| **Infrastructure** | Docker Compose (PostgreSQL 16 avec pgvector, Redis 7, n8n 1.69.2+, Caddy), Tailscale VPN, age/SOPS secrets [D19] |
| **Trust Layer** | @friday_action middleware, ActionResult, 3 trust levels (auto/propose/blocked), correction_rules |
| **Anonymisation** | Presidio + spaCy-fr, mapping ephemere Redis TTL court |
| **Bot Telegram** | 5 topics (Chat, Email, Actions, System, Metrics), commandes /status /journal /receipt /confiance /stats, inline buttons validation |
| **Pipeline Mail** | 4 comptes IMAP via EmailEngine, classification, extraction PJ, brouillons reponse (trust=propose) |
| **Archiviste** | OCR (Surya), renommage intelligent, classement automatique, suivi garanties |
| **Agenda** | Extraction evenements depuis mails/transcriptions, multi-casquettes |
| **Briefing matinal** | Agregation quotidienne tous modules, envoye via Telegram |
| **Desktop Search** | Recherche semantique fichiers locaux PC via pgvector (PostgreSQL) embeddings [D19] |
| **Graphe de connaissances** | PostgreSQL knowledge.* + pgvector embeddings (pas Graphiti Day 1) [D19] |
| **Vocal** | Faster-Whisper STT + Kokoro TTS via Telegram |
| **Heartbeat Engine** | Proactivite context-aware (interval 30min, quiet hours 22h-8h) |
| **Self-Healing Tier 1-2** | Docker restart, unattended-upgrades, auto-recover-ram, monitor-restarts |
| **Personnalite** | Configurable via YAML (tone, tutoiement, humour, verbosite) |
| **Migration emails** | 110k emails existants (batch nuit, ~18-24h, ~$45 Claude API) |

### Growth Features - Month 1-3

| Composant | Description |
|-----------|-------------|
| **Tuteur These** | Pre-correction methodologique Google Docs (4 theses parallele max) |
| **Check These** | Anti-hallucination references, detection journaux predateurs |
| **Suivi financier** | 5 perimetres (SELARL, SCM, 2 SCI, perso), import CSV, classification |
| **Detection anomalies** | Factures double, depenses inhabituelles, audit abonnements |
| **Plaud Note** | Transcription audio -> cascade actions (resume, taches, agenda, these) |
| **Veilleur Droit** | Analyse contrats, detection clauses abusives (recall >=95%) |
| **Self-Healing Tier 3-4** | Detection connecteurs casses, drift accuracy, pattern detection |

### Vision - 3+ mois

| Composant | Description |
|-----------|-------------|
| Aide en consultation | ECG-Reader, interactions medicamenteuses, recos HAS |
| Menus & Courses | Planification hebdomadaire + liste courses auto-generee |
| Coach remise en forme | Programme sportif adapte (sans Apple Watch, donnees agenda/menus) |
| Entretien cyclique | Vidange, CT, chaudiere — rappels proactifs |
| Generateur TCS/ECOS | Vignettes cliniques + examens structures (enseignement medical) |
| Actualisateur cours | Mise a jour cours existants avec dernieres recommandations |
| Aide investissement | Decision achat complexe basee sur situation financiere reelle |
| Photos BeeStation | Indexation et classement photos |
| Collection JV | Inventaire, valeur marche, veille prix |
| CV academique | Auto-maintenu (publications, theses, enseignement) |
| Mode HS/Vacances | Reponses auto, alertes thesards, briefing reprise |
| Optimisation fiscale | Suggestions inter-structures (SELARL/SCM/SCI) |
| Graphiti/Neo4j | Reevaluation graphe relationnel avance (aout 2026) |

## User Journeys

### J1 — Mainteneur : Journee type (Happy Path)

**8h00 — Petit-dejeuner.** Telephone vibre : briefing matinal Friday dans le topic Chat Telegram.

> "Bonjour Mainteneur. 3 emails urgents (Dr. Martin — resultat labo, Doyen — convocation jury jeudi, comptable — TVA a signer). 12 emails classes automatiquement. 2 PJ archivees (facture EDF → finance/selarl/2026/02-Fevrier, courrier ARS → Cabinet/Admin). Julie n'a pas touche son Google Doc depuis 12 jours — soutenance dans 6 semaines. CT voiture dans 45 jours."

Mainteneur lit en 90 secondes. Un email du doyen est mal classe — il corrige via inline button. Friday note la correction.

**8h30 — En voiture.** Mainteneur envoie un vocal Telegram : "Friday, qu'est-ce que j'avais lu sur les inhibiteurs SGLT2 le mois dernier ?". Friday transcrit (Faster-Whisper), cherche dans pgvector (PostgreSQL), repond en vocal (Kokoro TTS) avec les 3 documents les plus pertinents.

**9h-12h — Consultations.** Friday travaille en silence. Emails classes en continu. PJ facture OCR-ee, renommee `2026-02-08_Facture_Labo-Cerba_145EUR.pdf`, classee dans finance/selarl/2026/02-Fevrier. Email VIP (comptable) → notification dans topic Email.

**14h — Entre deux patients.** 2 actions en attente dans Actions : brouillon reponse email (trust=propose), classement financier incertain (confiance 0.72). Mainteneur approuve le brouillon, corrige le classement. Friday apprend.

**18h — Digest soir automatique** dans Metrics : 18 emails traites, 2 corrections, accuracy 89%, 4 documents archives, 0 alerte systeme. Mainteneur n'a rien demande — Friday a pousse l'info.

### J2 — Mainteneur : Urgence en consultation (Edge Case)

**10h15 — En pleine consultation.** Email du doyen (VIP) : "Jury these Julie annule URGENT". Friday detecte urgence (VIP + mot-cle) → notification push dans topic Email.

**10h30 — Fin consultation.** Mainteneur lit le resume Friday + brouillon reponse (trust=propose). Modifie une phrase, approuve. Friday envoie via EmailEngine. 2 minutes au lieu de 10.

**Scenario d'echec :** Presidio crash → Friday STOP (fail-explicit), email non traite, alerte dans topic System. Self-Healing tente restart. Echec apres 2 tentatives → alerte Telegram Mainteneur.

### J3 — Friday : Monitoring proactif (Push-first)

Mainteneur ne tape JAMAIS /status. Tout est pousse automatiquement :

- **18h quotidien** : Digest soir dans Metrics (emails, corrections, accuracy, documents, alertes)
- **Dimanche soir** : Rapport hebdomadaire auto (tableau trust par module, tendances accuracy, budget API consomme)
- **Immediatement** : Alerte dans System si RAM >85%, service down, retrogradation trust
- **Immediatement** : Notification dans Actions si trust level change

Les commandes /status, /journal, /confiance, /receipt, /stats, /help restent disponibles en fallback. /help affiche la liste complete des commandes.

**Scenario Self-Healing :** RAM 87% → alerte System. RAM 91% → auto-recover-ram tue Kokoro TTS (priorite basse). Mainteneur recoit : "RAM critique 91% — Kokoro TTS arrete. Vocal TTS indisponible. STT toujours fonctionnel."

### J4 — Julie (Thesarde) : Interaction indirecte

Julie ouvre son Google Doc. Elle decouvre des suggestions en mode revision :

> Suggestion : "Section Methodologie : preciser le design (phenomenologique ? ancre ?), population cible, criteres inclusion/exclusion, methode echantillonnage."

> Suggestion : "Reference Dupont et al. 2019 non trouvee dans PubMed. Verifier existence ou remplacer."

Julie ne sait pas que Friday existe. Elle pense qu'Mainteneur a ecrit les suggestions manuellement. Cote Friday : action tuteur_these.review executee avec trust=propose, Mainteneur a valide avant push. Contenu these anonymise via Presidio avant traitement LLM cloud.

### J5 — Friday : Agent autonome (Heartbeat & Nightly)

**14h30 — Heartbeat** (interval 30min). Contexte : mardi, jour ouvrable, derniere activite Mainteneur il y a 45min. LLM decideur selectionne checks :
- check_urgent_emails (HIGH) → 0 urgent non traite
- check_financial_alerts (MEDIUM) → RAS
- check_thesis_reminders (LOW) → skippe

Rien a signaler → Friday ne notifie PAS (80%+ du temps = silence = comportement voulu).

**03h00 — Cron nightly** (n8n) :
1. Backup PostgreSQL chiffre (age) → sync Tailscale vers PC
2. nightly.py calcule metriques trust → core.trust_metrics
3. cleanup-disk supprime logs >7j, backups >30

**03h15 — Incident.** Redis OOM restart. Docker restart policy relance en 8s. monitor-restarts detecte 1 restart (seuil 2/h, pas d'alerte). Incident logge dans core.events.

### Arborescence de classement documents

```
C:\Users\lopez\BeeStation\Friday\Archives\
├── pro/                          # Cabinet médical SELARL
│   ├── factures/YYYY/MM-Mois/
│   ├── contrats/
│   └── admin/
├── universite/                   # Faculté médecine
│   ├── theses/Prenom_Nom/
│   ├── cours/
│   └── admin/
├── recherche/                    # Recherche académique
│   ├── publications/
│   ├── colloques/
│   └── revues/
├── finance/                      # 5 périmètres financiers
│   ├── selarl/YYYY/MM-Mois/
│   ├── scm/YYYY/MM-Mois/
│   ├── sci_ravas/YYYY/MM-Mois/   # SCI Ravas
│   ├── sci_malbosc/YYYY/MM-Mois/ # SCI Malbosc
│   └── personal/YYYY/MM-Mois/
└── perso/                        # Vie personnelle
    ├── assurances/
    ├── vehicule/
    ├── maison/
    ├── garanties/
    │   ├── actives/
    │   └── expirees/
    └── divers/
```

Classement par LLM (trust=propose les premieres semaines, puis auto apres stabilisation). Arborescence evolutive.

### Journey Requirements Summary

| Journey | Capacites revelees |
|---------|-------------------|
| J1 — Journee type | Briefing matinal 8h, classification email, OCR/archivage PJ avec arborescence, Desktop Search vocal, digest soir 18h, inline buttons correction |
| J2 — Urgence | VIP detection (/vip + apprentissage), notification push urgente, brouillon reponse, fail-explicit Presidio |
| J3 — Monitoring | Design push-first, digest soir auto, rapport hebdo auto, alertes immediates, /help liste commandes |
| J4 — Thesarde | Google Docs API Suggestions, anti-hallucination, anonymisation these, trust=propose, transparence (Julie ne sait pas) |
| J5 — Friday autonome | Heartbeat context-aware, quiet hours, backup chiffre, nightly metrics, Docker restart, cleanup |

## Domain-Specific Requirements

### Clarification critique : Donnees medicales

**Aucune donnee medicale patient ne transite dans les 4 comptes IMAP geres par Friday.** Les donnees medicales (dossiers patients, resultats labo, correspondance medicale sensible) transitent sur des systemes securises separes (messagerie sante dediee) que Friday ne gere pas.

**Consequences architecturales :**
- pgcrypto pour donnees patients : **NON NECESSAIRE** Day 1 (pas de donnees patients dans Friday)
- Ollama local obligatoire pour emails medicaux : **NON** (les emails medicaux patients ne passent pas par Friday)
- Dossier Cabinet/Patients/ dans arborescence : **SUPPRIME**
- Classification domaine : Finance/Legal (pas Healthcare pour les flux Friday)

### Compliance & Reglementaire

| Regle | Application | Mesure |
|-------|-------------|--------|
| **RGPD** | Presidio + spaCy-fr avant tout LLM cloud | 100% PII anonymisees sur dataset test |
| **Mapping Presidio** | Ephemere Redis (TTL court), JAMAIS stocke en clair | Aucune persistance du mapping |
| **Donnees financieres** | 5 perimetres (SELARL, SCM, 2 SCI, perso) | Classification correcte, pas de fuite inter-perimetre |
| **Secret professionnel** | Emails cabinet = confidentiels (pas patients, mais admin/contrats/facturation) | Anonymisation avant LLM cloud |
| **Google Docs theses** | Contenu these anonymise avant traitement LLM | Presidio sur texte these |
| **Backup chiffre** | age encryption sur backups PostgreSQL | Restore teste mensuellement |

### Contraintes techniques

| Contrainte | Detail |
|------------|--------|
| **VPS-4 OVH** | 48 Go RAM, 12 vCores, 300 Go SSD, ~25 EUR/mois (D15) |
| **Tous services residents** | Pas d'exclusion mutuelle (~8 Go services lourds + ~8 Go socle, ~32-37 Go marge) |
| **Tailscale** | Rien expose sur Internet public, 2FA obligatoire |
| **Redis ACL** | Moindre privilege par service |
| **age/SOPS** | Secrets chiffres, jamais de .env en clair dans git |
| **Fail-explicit** | Presidio crash → STOP (pas de fallback silencieux avec PII) |

### Risques domaine

Voir section consolidee **Project Scoping > Risques et mitigations** pour la table complete.

## Innovation & Novel Patterns

### Patterns innovants detectes

**1. Trust Layer adaptatif** — Systeme de confiance auto-calibre a 3 niveaux (auto/propose/blocked) avec retrogradation automatique (accuracy <90%), promotion manuelle, anti-oscillation 2 semaines. Pas un RBAC classique — une confiance vivante entre humain et IA.

**2. Design push-first** — Friday pousse TOUTE l'information proactivement (briefing 8h, digest 18h, rapport hebdo, alertes immediates). Les commandes manuelles (/status, /journal, etc.) sont du fallback. Inverse du pattern command-driven habituel.

**3. Heartbeat Engine context-aware** — Le LLM decide dynamiquement quels checks effectuer en fonction du contexte (heure, jour, derniere activite, agenda). Proactivite intelligente, pas une liste statique de cron jobs.

**4. Fail-explicit RGPD** — Si Presidio crash, Friday STOP. Pas de degradation gracieuse qui laisserait passer du PII. Anti-pattern delibere du "graceful degradation" quand la securite est en jeu.

**5. Ecosysteme IA single-user auto-heberge** — Convergence de 23 modules IA sur un seul VPS personnel, zero exposition Internet publique. Ni commercial, ni multi-tenant — optimise pour un seul utilisateur.

**6. Feedback loop deterministe** — ~50 regles max via SELECT SQL injectees dans les prompts. Deliberement pas de RAG pour les corrections — simplicite et reproductibilite.

### Strategie LLM (D17 — supersede D11/D13/D14)

**Decision majeure** : 100% Claude Sonnet 4.5. Un seul modele, zero routing, zero complexite de dispatch.

**Pourquoi Claude Sonnet 4.5 :**
- #1 instruction following (suivi consignes structurees Trust Layer)
- #1 structured output (JSON ActionResult, classification, extraction)
- #1 consistance (reproductibilite critique pour feedback loop)
- Tool calling mature et fiable (vs Mistral Large 3 : "malformed tool names" rapporte)
- Excellent en francais

**Modele unique pour toutes les taches** : Classification emails, brouillon reponse, categorisation financiere, thesis review, anti-hallucination, resume, Heartbeat decideur, Desktop Search, classement documents, briefing matinal, OCR post-processing — tout passe par Claude Sonnet 4.5.

**Supprime** : Ollama local (pas de GPU, Presidio suffit), Mistral (remplace par Claude), Gemini Flash (remplace par Claude).

**Impact RAM** : Ollama retire → VPS-4 (48 Go, ~25 EUR/mois) suffit. Marge ~32-37 Go.

**Tarification** : $3/$15 per 1M tokens (input/output). Estimation ~45 EUR/mois pour le volume Friday.

**Regle absolue** : Presidio anonymisation AVANT tout appel Claude. Zero exception.

### Veille obsolescence modele (D18)

**Systeme d'alerte mensuel** pour s'assurer que le modele utilise reste optimal :

| Composant | Detail |
|-----------|--------|
| **Benchmark mensuel automatise** | Suite de 10-15 taches representives Friday (classification email, extraction JSON, resume FR, tool calling) executees sur le modele actuel + 2-3 concurrents |
| **Metriques comparees** | Accuracy, structured output fidelity, latence, cout/token, qualite francais |
| **Seuil d'alerte** | Concurrent >10% superieur sur >=3 metriques simultanees → notification Telegram topic System |
| **Rapport mensuel** | Push automatique dans Metrics : tableau comparatif, tendances, recommandation (garder/evaluer/migrer) |
| **Migration facilitee** | Adaptateur llm.py swappable — changement de provider = 1 fichier + 1 env var |

**Declencheur** : Cron n8n mensuel (1er du mois). Cout benchmark : ~$2-3/mois (quelques centaines d'appels test).

**Anti-piege** : Ne PAS changer de modele sur un seul benchmark — exiger 3 mois de superiorite consistante avant migration.

### Validation

- Trust Layer : Metriques accuracy par module/action, retrogradation automatique = validation continue
- Push-first : Critere US3 (>=80% notifications jugees pertinentes par Mainteneur)
- Heartbeat : Monitoring ratio signal/bruit (80%+ du temps = silence = bon comportement)
- Fail-explicit : Tests integration Presidio crash → pipeline STOP

### Risques innovation

Voir section consolidee **Project Scoping > Risques et mitigations** pour la table complete.

## Self-hosted AI Assistant — Exigences specifiques

### Vue d'ensemble technique

Architecture event-driven single-user sur VPS personnel (Docker Compose). Interface unique : Telegram (5 topics). Zero interface web publique. Tout LLM via Claude Sonnet 4.5 (Anthropic API) apres anonymisation Presidio. Veille mensuelle automatisee sur obsolescence modele (D18).

### Architecture pipeline

| Composant | Technologie | Role |
|-----------|-------------|------|
| Orchestrateur workflows | n8n 1.69.2+ | Triggers, cron, enchainement |
| Logique metier IA | Python (LangGraph 0.2.45+) | Agents, classification, generation |
| API interne | FastAPI | Gateway, healthcheck, endpoints |
| BDD | PostgreSQL 16 (3 schemas) | core, ingestion, knowledge |
| Vectorstore | pgvector (PostgreSQL) | Embeddings, Desktop Search [D19] |
| Cache/Events | Redis 7 | Streams (critique) + Pub/Sub (informatif) |
| Reverse proxy | Caddy | TLS interne, routing services |
| VPN | Tailscale | Zero exposition publique |
| STT | Faster-Whisper (local) | Transcription vocale (~4 Go RAM) |
| TTS | Kokoro TTS (local) | Synthese vocale (~2 Go RAM) |
| OCR | Surya (local) | Extraction texte documents (~2 Go RAM) |

### Interface utilisateur

- **Telegram uniquement** — pas de web UI, pas de dashboard
- 5 topics specialises (Chat, Email, Actions, System, Metrics)
- Inline buttons pour validations trust=propose
- Commandes /help, /status, /journal, /receipt, /confiance, /stats, /vip
- Vocal bidirectionnel (Faster-Whisper STT + Kokoro TTS)

### Deploiement & Operations

- Docker Compose unique (pas Kubernetes, pas Swarm)
- VPS-4 OVH (48 Go RAM, 12 vCores, 300 Go SSD, ~25 EUR/mois)
- Migrations SQL numerotees (asyncpg brut, pas d'ORM)
- Backup quotidien chiffre age → sync PC via Tailscale
- Self-Healing tiers 1-4 (Docker restart → auto-recover-ram → drift detection)
- Monitoring via scripts + Telegram (pas Prometheus)

### Securite & Isolation

- Tailscale mesh VPN (2FA, device authorization manuelle)
- Redis ACL par service
- age/SOPS pour secrets
- Presidio fail-explicit avant tout LLM cloud
- Aucun port expose sur Internet public

### Adaptateurs swappables

| Adaptateur | Day 1 | Remplacable par |
|------------|-------|-----------------|
| llm.py | Claude Sonnet 4.5 (Anthropic) | Tout provider LLM (migration via D18 veille) |
| vectorstore.py | pgvector (PostgreSQL) [D19] | Qdrant (si >300k vecteurs), Milvus |
| memorystore.py | PostgreSQL + pgvector [D19] | Graphiti/Neo4j (reevaluation aout 2026) |
| filesync.py | Syncthing | rsync, rclone |
| email.py | EmailEngine | IMAP direct |

## Project Scoping & Developpement phase

### Strategie MVP

**Approche** : Tout Day 1 en bloc — pas de cercles progressifs. Friday doit etre complet et utilisable au quotidien des le premier jour.

**Philosophie** : Problem-solving MVP — le minimum pour que Friday remplace le traitement manuel des emails, documents, et informations quotidiennes d'Mainteneur.

**Budget mensuel** : ~25 EUR VPS + ~45 EUR API Claude Sonnet 4.5 + ~3 EUR benchmark veille = **~73 EUR/mois**

### MVP Day 1 — Composants (tous simultanes)

| # | Composant | Justification MVP |
|---|-----------|-------------------|
| 1 | Infrastructure Docker | Prerequis a tout |
| 2 | Trust Layer | Prerequis a tout module |
| 3 | Presidio anonymisation | Prerequis RGPD |
| 4 | Bot Telegram (5 topics) | Interface unique |
| 5 | Pipeline Mail | Besoin #1 Mainteneur |
| 6 | Archiviste (OCR + classement) | Inseparable du pipeline mail (PJ) |
| 7 | Briefing matinal | Push-first, valeur quotidienne |
| 8 | Desktop Search | Retrouver instantanement |
| 9 | Vocal STT/TTS | Usage en voiture |
| 10 | Heartbeat Engine | Proactivite context-aware |
| 11 | Graphe de connaissances | Memoire persistante |
| 12 | Self-Healing Tier 1-2 | Stabilite (TS1) |
| 13 | Personnalite YAML | Ton Friday configurable |
| 14 | Migration 110k emails | Base de connaissances initiale |
| 15 | Agenda | Extraction evenements mails |

### Cold Start (D16)

Au demarrage, ~100 emails non lus dans les 4 comptes IMAP. Traitement par batch de 10-20, tout en trust=propose. Mainteneur valide les premiers lots → Friday se calibre. Les corrections alimentent immediatement les correction_rules.

### Post-MVP (Month 1-3)

| Composant | Dependance |
|-----------|-----------|
| Tuteur These | Pipeline mail + Google Docs API |
| Check These | Graphe connaissances + PubMed |
| Suivi financier | Pipeline mail + classification |
| Detection anomalies | Suivi financier |
| Plaud Note | Vocal STT + pipeline actions |
| Veilleur Droit | Archiviste + classification |
| Self-Healing Tier 3-4 | Tier 1-2 stable |

### Vision (3+ mois)

Aide consultation, Menus & Courses, Coach, Entretien cyclique, Generateur TCS/ECOS, Actualisateur cours, Aide investissement, Photos BeeStation, Collection JV, CV academique, Mode HS/Vacances, Optimisation fiscale, Graphiti/Neo4j.

### Risques et mitigations (consolide)

| # | Risque | Impact | Mitigation |
|---|--------|--------|------------|
| R1 | Fuite PII vers LLM cloud | RGPD violation | Presidio obligatoire, fail-explicit, tests dataset |
| R2 | RAM VPS-4 saturee | Services down | monitor-ram.sh (seuil 85%), auto-recover-ram, Self-Healing |
| R3 | Accuracy trust degrades | Actions incorrectes | Retrogradation auto (<90%), echantillon >=10, anti-oscillation 2 semaines |
| R4 | Pipeline email fragile (5+ maillons) | Emails non traites | Trust=propose Day 1, fail-explicit, Self-Healing, alerte System |
| R5 | Confusion perimetres financiers | Erreurs comptables | Classification stricte 5 perimetres, trust=propose Day 1 |
| R6 | Anthropic API indisponible | Tous modules bloques | Retry automatique, alertes, adaptateur swappable + veille D18 |
| R7 | Dependance unique Anthropic (Claude) | Lock-in fournisseur | Adaptateur llm.py (1 fichier), veille mensuelle D18, 3 mois avant migration |
| R8 | EmailEngine indisponible | Pipeline email arrete | Adaptateur email.py swappable IMAP direct, alerte System immediate |
| R9 | Backup corrompu | Perte donnees | Test restore mensuel, backup chiffre age, sync PC via Tailscale |
| R10 | Migration 110k lente/couteuse | Retard demarrage | Batch nuit, ~18-24h, ~$45 Claude API, checkpointing resume |
| R11 | Cold start 100 emails | Surcharge initiale | Batch 10-20, trust=propose, calibrage progressif |
| R12 | Push-first = spam | Mainteneur ignore Friday | Quiet hours 22h-8h, ratio signal/bruit surveille (US3 >=80%) |
| R13 | Trust Layer trop conservateur | Trop de validations manuelles | Seuils ajustables, promotion manuelle Mainteneur |
| R14 | Heartbeat decideur imprecis | Faux positifs/negatifs | Claude Sonnet 4.5, fallback checks statiques |

## Functional Requirements

### Email & Communications

- **FR1** : Friday peut classifier automatiquement les emails entrants des 4 comptes IMAP
- **FR2** : Mainteneur peut visualiser et corriger les classifications via inline buttons Telegram
- **FR3** : Friday peut extraire les pieces jointes et les transmettre au module Archiviste
- **FR4** : Friday peut rediger des brouillons de reponse email soumis a validation
- **FR5** : Mainteneur peut designer des expediteurs VIP via commande Telegram /vip
- **FR6** : Friday peut detecter les emails urgents (VIP + patterns appris)
- **FR7** : Friday peut traiter un backlog d'emails non lus par lots priorises (cold start)

### Gestion documentaire

- **FR8** : Friday peut effectuer l'OCR sur images et PDF
- **FR9** : Friday peut renommer les documents avec une convention standardisee
- **FR10** : Friday peut classer les documents dans une arborescence configurable et évolutive (initiale : pro/finance/universite/recherche/perso — D24)
- **FR11** : Mainteneur peut rechercher des documents par requete semantique
- **FR12** : Friday peut suivre les dates d'expiration de garanties et notifier proactivement
- **FR13** : Mainteneur peut rechercher des documents par requete vocale

### Interface & Communication

- **FR14** : Mainteneur peut interagir avec Friday via messages texte Telegram
- **FR15** : Mainteneur peut interagir avec Friday via messages vocaux Telegram
- **FR16** : Friday peut router ses notifications vers le topic Telegram approprie (Chat/Email/Actions/System/Metrics)
- **FR17** : Mainteneur peut valider ou rejeter les actions proposees via inline buttons
- **FR18** : Mainteneur peut consulter la liste des commandes disponibles via /help
- **FR19** : Friday peut repondre en synthese vocale (TTS)

### Proactivite & Intelligence

- **FR20** : Friday peut envoyer un briefing matinal a 8h agregant les informations pertinentes
- **FR21** : Friday peut envoyer un digest soir a 18h resumant l'activite de la journee
- **FR22** : Friday peut envoyer un rapport hebdomadaire automatique (trust, tendances, budget API)
- **FR23** : Friday peut verifier proactivement les situations urgentes selon le contexte (Heartbeat)
- **FR24** : Friday peut determiner la priorite des checks selon heure, jour, et activite utilisateur
- **FR25** : Friday peut rester silencieux quand rien de notable n'est detecte

### Trust & Apprentissage

- **FR26** : Chaque action Friday produit un recu standardise (confidence, reasoning, input/output)
- **FR27** : Les actions s'executent selon leur trust level assigne (auto/propose/blocked)
- **FR28** : Mainteneur peut corriger les actions de Friday, declenchant l'apprentissage
- **FR29** : Friday peut detecter des patterns de correction et proposer de nouvelles regles
- **FR30** : Les trust levels se retrogradent automatiquement si accuracy < seuil
- **FR31** : Mainteneur peut promouvoir manuellement un trust level apres accuracy soutenue
- **FR32** : Mainteneur peut consulter les metriques de confiance par module via /confiance
- **FR33** : Mainteneur peut consulter le detail d'un recu d'action via /receipt

### Securite & Conformite

- **FR34** : Tout texte est anonymise via Presidio avant tout appel LLM cloud
- **FR35** : Friday stoppe le traitement si le service d'anonymisation est indisponible (fail-explicit)
- **FR36** : Les backups sont chiffres et synchronises vers le PC d'Mainteneur quotidiennement
- **FR37** : Les donnees financieres sont classees dans le bon perimetre (SELARL/SCM/SCI Ravas/SCI Malbosc/Perso) sans contamination croisee

### Graphe de connaissances & Memoire

- **FR38** : Friday peut construire et maintenir une memoire persistante a partir du contenu traite
- **FR39** : Friday peut generer des embeddings pour la recherche semantique
- **FR40** : Friday peut lier des informations entre sources (emails, documents, calendrier)

### Agenda & Calendrier

- **FR41** : Friday peut detecter les informations d'evenements dans les emails et transcriptions
- **FR42** : Friday peut gerer le contexte multi-casquettes (medecin, enseignant, chercheur)

### Operations & Stabilite

- **FR43** : Les services redemarrent automatiquement en cas d'echec
- **FR44** : L'usage RAM est surveille avec actions de recovery automatique
- **FR45** : Friday peut alerter Mainteneur sur les problemes systeme via Telegram
- **FR46** : Les 110k emails historiques peuvent etre migres avec checkpointing et reprise

### Personnalisation

- **FR47** : Mainteneur peut configurer la personnalite de Friday (ton, tutoiement, humour, verbosite)

### Veille & Gouvernance modele

- **FR48** : Friday peut executer un benchmark mensuel automatise comparant le modele LLM actuel aux concurrents
- **FR49** : Friday peut alerter Mainteneur si un modele concurrent est significativement superieur
- **FR50** : Mainteneur peut declencher une migration de provider LLM via changement d'adaptateur

## Non-Functional Requirements

### Performance

| ID | Exigence | Mesure | Seuil |
|----|----------|--------|-------|
| NFR1 | Classification email temps reel | Temps entre reception email et classification complete | <30s par email |
| NFR2 | Briefing matinal genere a temps | Temps de generation du briefing complet | <60s, pret avant 8h00 |
| NFR3 | Desktop Search reponse rapide | Temps entre requete et affichage resultats | <3s pour top-5 resultats |
| NFR4 | Vocal round-trip | Latence complete STT + LLM + TTS | <=30s |
| NFR5 | Pipeline OCR + classement | Temps traitement document (OCR + renommage + archivage) | <45s par document |

### Securite

| ID | Exigence | Mesure | Seuil |
|----|----------|--------|-------|
| NFR6 | Anonymisation PII exhaustive | Taux de detection PII sur dataset test | 100% PII detectees, 0 fuite |
| NFR7 | Fail-explicit Presidio | Comportement si Presidio indisponible | STOP complet, alerte System, JAMAIS de fallback silencieux |
| NFR8 | Zero exposition Internet | Ports ouverts sur IP publique | 0 port expose (tout via Tailscale) |
| NFR9 | Secrets chiffres | Credentials en clair dans le code ou git | 0 secret en clair (age/SOPS) |
| NFR10 | Backup chiffre | Encryption des backups PostgreSQL | 100% chiffre age, restore teste mensuel |
| NFR11 | Redis ACL | Privilege par service Redis | Moindre privilege, separation par service |

### Fiabilite

| ID | Exigence | Mesure | Seuil |
|----|----------|--------|-------|
| NFR12 | Disponibilite services | Uptime des services critiques (PostgreSQL, Redis, FastAPI, Telegram bot) | >=99% uptime mensuel (~7h downtime max) |
| NFR13 | Self-Healing automatique | Temps de recovery apres crash service | <30s (Docker restart), <2min (auto-recover-ram) |
| NFR14 | RAM stable | Usage memoire VPS-4 48 Go | <=85% (<=40.8 Go) en continu |
| NFR15 | Zero email perdu | Emails recus vs emails traites | 0 email perdu (Redis Streams, delivery garanti) |
| NFR16 | Backup quotidien fiable | Succes backup + sync PC | 100% jours avec backup reussi |

### Integration

| ID | Exigence | Mesure | Seuil |
|----|----------|--------|-------|
| NFR17 | Anthropic API resilience | Comportement si API Claude indisponible | Retry automatique (3 tentatives, backoff exponentiel), alerte System |
| NFR18 | EmailEngine resilience | Comportement si EmailEngine crash | Alerte immediate, adaptateur swappable IMAP direct |
| NFR19 | Telegram API resilience | Comportement si Telegram indisponible | Queue messages, retry, log local |
| NFR20 | Google Docs API (post-MVP) | Comportement si API Docs indisponible | Skip thesis review, notifier Mainteneur, retry prochain cycle |

### Maintenabilite

| ID | Exigence | Mesure | Seuil |
|----|----------|--------|-------|
| NFR21 | Adaptateurs swappables | Changement de provider LLM/vectorstore/email | 1 fichier + 1 env var (pas de modification multi-fichiers) |
| NFR22 | Logs structures | Format logs services | 100% JSON structure (structlog), zero print(), zero emoji dans logs |
| NFR23 | Migrations reversibles | Rollback migration SQL | Backup pre-migration automatique, rollback possible |
| NFR24 | Monitoring sans overhead | Overhead RAM du monitoring | 0 Go additionnel (scripts bash + cron, pas Prometheus) |

### Cout

| ID | Exigence | Mesure | Seuil |
|----|----------|--------|-------|
| NFR25 | Budget mensuel maitrise | Cout total (VPS + API + veille) | <=75 EUR/mois |
| NFR26 | Cout migration ponctuel | Cout one-shot migration 110k emails | <=50 EUR (Claude API) |

### Veille & Gouvernance modele

| ID | Exigence | Mesure | Seuil |
|----|----------|--------|-------|
| NFR27 | Benchmark mensuel automatise | Execution suite benchmark sur modele actuel + concurrents | 1er du mois, rapport pousse dans Metrics |
| NFR28 | Alerte obsolescence | Detection modele concurrent significativement superieur | Alerte si >10% superieur sur >=3 metriques simultanees |
| NFR29 | Migration modele rapide | Temps pour basculer vers un nouveau provider LLM | <1 jour (adaptateur llm.py + env var) |
