---
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
workflowStatus: complete
completedAt: 2026-02-08
inputDocuments:
  # PRD
  - _bmad-output/planning-artifacts/prd.md
  # Architecture
  - _docs/architecture-friday-2.0.md
  - _docs/architecture-addendum-20260205.md
  - _docs/friday-2.0-analyse-besoins.md
  - _docs/analyse-fonctionnelle-complete.md
  # Documentation technique
  - docs/implementation-roadmap.md
  - docs/DECISION_LOG.md
  - docs/testing-strategy-ai.md
  - docs/ai-models-policy.md
  - docs/n8n-workflows-spec.md
  - docs/playwright-automation-spec.md
  - agents/docs/heartbeat-engine-spec.md
  # Securite & infra
  - docs/secrets-management.md
  - docs/redis-streams-setup.md
  - docs/redis-acl-setup.md
  - docs/tailscale-setup.md
  - docs/pc-backup-setup.md
  - docs/presidio-mapping-decision.md
  # Telegram
  - docs/telegram-topics-setup.md
  - docs/telegram-user-guide.md
  # Revues
  - docs/analyse-adversariale-rapport-final.md
  - docs/code-review-final-corrections.md
  # Config & scripts
  - config/trust_levels.yaml
  - tests/fixtures/README.md
  - CLAUDE.md
  - .env.example
  - .sops.yaml
  # Infrastructure existante
  - docker-compose.yml
  - docker-compose.services.yml
  - database/migrations/001-012_*.sql
  - scripts/apply_migrations.py
  - scripts/migrate_emails.py
  - scripts/monitor-ram.sh
  - scripts/verify_env.sh
  - scripts/setup-redis-streams.sh
  - scripts/extract_telegram_thread_ids.py
  # Code existant
  - agents/src/tools/anonymize.py
  - agents/src/middleware/models.py
  - agents/src/middleware/trust.py
  - agents/src/adapters/memorystore.py
  - services/alerting/listener.py
  - services/metrics/nightly.py
  - services/email-processor/consumer.py
  - services/document-indexer/consumer.py
  - services/monitoring/emailengine_health.py  # [HISTORIQUE D25] EmailEngine → IMAP direct
  - tests/e2e/test_backup_restore.sh
epicsCoverage:
  totalFRs: 151
  totalNFRs: 29
  totalEpics: 20
  mvpEpics: 7
  growthEpics: 6
  visionEpics: 7
  orphanedFRs: 0
---

> **Mis a jour 2026-02-09** : D17 (Claude remplace Mistral), D19 (pgvector remplace Qdrant Day 1)

# Friday 2.0 - Epic Breakdown

## Overview

Ce document fournit le decoupage complet en epics et stories pour Friday 2.0, decomposant les 151 exigences fonctionnelles (FR1-FR152, FR130 retire comme doublon de FR21) et 29 exigences non-fonctionnelles en 20 epics implementables.

**Structure** : 3 fichiers de detail par phase + cet index.

| Phase | Epic Breakdown | Stories (Sprint) | Epics | FRs | Stories |
|-------|---------------|-----------------|-------|-----|---------|
| MVP Day 1 | [epics-mvp.md](epics-mvp.md) | [sprint-1-mvp.md](sprint-1-mvp.md) | 1-7 | 82 | 45 |
| Growth Month 1-3 | [epics-growth.md](epics-growth.md) | [sprint-2-growth.md](sprint-2-growth.md) | 8-13 | 33 | 22 |
| Vision 3+ mois | [epics-vision.md](epics-vision.md) | [sprint-3-vision.md](sprint-3-vision.md) | 14-20 | 36 | ~26 |

---

## Requirements Inventory

### Functional Requirements (FR1-FR152, 151 uniques)

**Email & Communications (FR1-FR7)**

- FR1 : Friday peut classifier automatiquement les emails entrants des 4 comptes IMAP
- FR2 : Mainteneur peut visualiser et corriger les classifications via inline buttons Telegram
- FR3 : Friday peut extraire les pieces jointes et les transmettre au module Archiviste
- FR4 : Friday peut rediger des brouillons de reponse email soumis a validation
- FR5 : Mainteneur peut designer des expediteurs VIP via commande Telegram /vip
- FR6 : Friday peut detecter les emails urgents (VIP + patterns appris)
- FR7 : Friday peut traiter un backlog d'emails non lus par lots priorises (cold start)

**Gestion documentaire (FR8-FR13)**

- FR8 : Friday peut effectuer l'OCR sur images et PDF
- FR9 : Friday peut renommer les documents avec une convention standardisee
- FR10 : Friday peut classer les documents dans une arborescence configurable et évolutive (pro/finance/universite/recherche/perso — D24)
- FR11 : Mainteneur peut rechercher des documents par requete semantique
- FR12 : Friday peut suivre les dates d'expiration de garanties et notifier proactivement
- FR13 : Mainteneur peut rechercher des documents par requete vocale

**Interface & Communication (FR14-FR19)**

- FR14 : Mainteneur peut interagir avec Friday via messages texte Telegram
- FR15 : Mainteneur peut interagir avec Friday via messages vocaux Telegram
- FR16 : Friday peut router ses notifications vers le topic Telegram approprie (Chat/Email/Actions/System/Metrics)
- FR17 : Mainteneur peut valider ou rejeter les actions proposees via inline buttons
- FR18 : Mainteneur peut consulter la liste des commandes disponibles via /help
- FR19 : Friday peut repondre en synthese vocale (TTS)

**Proactivite & Intelligence (FR20-FR25)**

- FR20 : Friday peut envoyer un briefing matinal a 8h agregant les informations pertinentes
- FR21 : Friday peut envoyer un digest soir a 18h resumant l'activite de la journee
- FR22 : Friday peut envoyer un rapport hebdomadaire automatique (trust, tendances, budget API)
- FR23 : Friday peut verifier proactivement les situations urgentes selon le contexte (Heartbeat)
- FR24 : Friday peut determiner la priorite des checks selon heure, jour, et activite utilisateur
- FR25 : Friday peut rester silencieux quand rien de notable n'est detecte

**Trust & Apprentissage (FR26-FR33)**

- FR26 : Chaque action Friday produit un recu standardise (confidence, reasoning, input/output)
- FR27 : Les actions s'executent selon leur trust level assigne (auto/propose/blocked)
- FR28 : Mainteneur peut corriger les actions de Friday, declenchant l'apprentissage
- FR29 : Friday peut detecter des patterns de correction et proposer de nouvelles regles
- FR30 : Les trust levels se retrogradent automatiquement si accuracy < seuil
- FR31 : Mainteneur peut promouvoir manuellement un trust level apres accuracy soutenue
- FR32 : Mainteneur peut consulter les metriques de confiance par module via /confiance
- FR33 : Mainteneur peut consulter le detail d'un recu d'action via /receipt

**Securite & Conformite (FR34-FR37)**

- FR34 : Tout texte est anonymise via Presidio avant tout appel LLM cloud
- FR35 : Friday stoppe le traitement si le service d'anonymisation est indisponible (fail-explicit)
- FR36 : Les backups sont chiffres et synchronises vers le PC d'Mainteneur quotidiennement
- FR37 : Les donnees financieres sont classees dans le bon perimetre (SELARL/SCM/SCI Ravas/SCI Malbosc/Perso) sans contamination croisee

**Graphe de connaissances & Memoire (FR38-FR40)**

- FR38 : Friday peut construire et maintenir une memoire persistante a partir du contenu traite
- FR39 : Friday peut generer des embeddings pour la recherche semantique
- FR40 : Friday peut lier des informations entre sources (emails, documents, calendrier)

**Agenda & Calendrier (FR41-FR42)**

- FR41 : Friday peut detecter les informations d'evenements dans les emails et transcriptions
- FR42 : Friday peut gerer le contexte multi-casquettes (medecin, enseignant, chercheur)

**Operations & Stabilite (FR43-FR46)**

- FR43 : Les services redemarrent automatiquement en cas d'echec
- FR44 : L'usage RAM est surveille avec actions de recovery automatique
- FR45 : Friday peut alerter Mainteneur sur les problemes systeme via Telegram
- FR46 : Les 110k emails historiques peuvent etre migres avec checkpointing et reprise

**Personnalisation (FR47)**

- FR47 : Mainteneur peut configurer la personnalite de Friday (ton, tutoiement, humour, verbosite)

**Veille & Gouvernance modele (FR48-FR50)**

- FR48 : Friday peut executer un benchmark mensuel automatise comparant le modele LLM actuel aux concurrents
- FR49 : Friday peut alerter Mainteneur si un modele concurrent est significativement superieur
- FR50 : Mainteneur peut declencher une migration de provider LLM via changement d'adaptateur

**Tuteur These (FR51-FR55)**

- FR51 : Friday peut analyser la structure methodologique d'une these Google Docs (IMRAD, design, population, criteres)
- FR52 : Friday peut inserer des suggestions en mode revision dans Google Docs
- FR53 : Friday peut gerer 4 theses en parallele max
- FR54 : Friday peut verifier la qualite statistique et methodologique
- FR55 : Friday peut anonymiser le contenu des theses via Presidio avant traitement LLM

**Check These (FR56-FR58)**

- FR56 : Friday peut verifier l'existence reelle des references citees (anti-hallucination via PubMed/CrossRef/Semantic Scholar)
- FR57 : Friday peut detecter les journaux predateurs
- FR58 : Friday peut identifier les articles cles manquants dans la bibliographie

**Suivi Financier & Anomalies (FR59-FR62)**

- FR59 : Friday peut importer et classifier les releves bancaires CSV sur 5 perimetres
- FR60 : Friday peut suivre les depenses, tresorerie et evolution des comptes par perimetre
- FR61 : Friday peut detecter les anomalies financieres (factures doubles, depenses inhabituelles)
- FR62 : Friday peut auditer les abonnements (nombre, cout total, utilisation reelle)

**Plaud Note (FR63-FR66)**

- FR63 : Friday peut transcrire les enregistrements audio Plaud Note
- FR64 : Friday peut generer un compte-rendu structure depuis une transcription
- FR65 : Friday peut extraire les actions, taches et evenements d'une transcription
- FR66 : Friday peut router les informations extraites vers les modules (taches, agenda, theses, biblio)

**Veilleur Droit (FR67-FR70)**

- FR67 : Friday peut analyser un contrat a la demande (pro, perso, universitaire)
- FR68 : Friday peut resumer un contrat et comparer ses versions
- FR69 : Friday peut detecter les clauses abusives (recall >= 95%)
- FR70 : Friday peut anonymiser les contrats via Presidio avant traitement LLM

**Self-Healing Avance (FR71-FR73)**

- FR71 : Friday peut detecter les connecteurs externes casses (~~EmailEngine~~ serveurs IMAP `[HISTORIQUE D25]`, APIs tierces)
- FR72 : Friday peut detecter le drift d'accuracy des modules IA
- FR73 : Friday peut detecter les patterns de degradation et envoyer des alertes proactives

**Aide Consultation (FR74-FR77)**

- FR74 : Friday peut interpreter des traces ECG (PDF anonymise)
- FR75 : Friday peut verifier les interactions medicamenteuses
- FR76 : Friday peut acceder aux recommandations HAS en temps reel
- FR77 : Friday peut calculer les posologies et acceder aux bases Vidal/Antibioclic

**Menus & Courses (FR78-FR80)**

- FR78 : Friday peut planifier les menus hebdomadaires (preferences famille 3 personnes, saison, agenda)
- FR79 : Friday peut generer automatiquement la liste de courses
- FR80 : Friday peut envoyer les recettes du jour chaque matin

**Coach Remise en Forme (FR81-FR83)**

- FR81 : Friday peut proposer un programme sportif adapte et progressif
- FR82 : Friday peut integrer les seances sportives dans l'agenda selon les creneaux libres
- FR83 : Friday peut ajuster les recommandations selon l'agenda et les menus

**Entretien Cyclique (FR84-FR85)**

- FR84 : Friday peut suivre les cycles d'entretien (vidange, CT, chaudiere, detartrage)
- FR85 : Friday peut envoyer des rappels proactifs avec possibilite de prise de RDV

**Enseignement Medical (FR86-FR89)**

- FR86 : Friday peut creer des vignettes cliniques TCS a partir du programme d'etudes
- FR87 : Friday peut simuler un panel d'experts pour la correction des TCS
- FR88 : Friday peut creer des ECOS (Examens Cliniques Objectifs Structures)
- FR89 : Friday peut mettre a jour les cours existants avec les dernieres recommandations

**Investissement & Gestion Projets (FR90-FR91)**

- FR90 : Friday peut aider a la decision d'achat complexe basee sur la situation financiere reelle
- FR91 : Friday peut gerer les projets ponctuels (changement voiture, travaux)

**Photos & Collection (FR92-FR96)**

- FR92 : Friday peut indexer et classer les photos BeeStation
- FR93 : Friday peut rechercher des photos par contenu, date ou evenement
- FR94 : Friday peut gerer l'inventaire de la collection de jeux video (photos, etat, edition, plateforme)
- FR95 : Friday peut suivre la valeur marche et les variations de cote des jeux video
- FR96 : Friday peut faire de la veille prix et envoyer des alertes

**CV & Mode HS (FR97-FR100)**

- FR97 : Friday peut maintenir automatiquement le CV academique (publications, theses, enseignement)
- FR98 : Friday peut envoyer des reponses automatiques aux mails non urgents en mode HS
- FR99 : Friday peut alerter les thesards de l'indisponibilite d'Mainteneur
- FR100 : Friday peut preparer un briefing de reprise au retour

**Optimisation Fiscale (FR101)**

- FR101 : Friday peut suggerer des optimisations fiscales inter-structures (SELARL/SCM/SCI)

**FRs additionnelles — Gap Analysis (FR102-FR152)**

- FR102 : Friday peut synchroniser Google Calendar de maniere bidirectionnelle (lecture + ecriture)
- FR103 : Friday peut detecter les nouveaux fichiers dans un dossier surveille (watchdog)
- FR104 : Friday peut envoyer les emails approuves par Mainteneur via ~~EmailEngine~~ aiosmtplib `[HISTORIQUE D25]`
- FR105 : Mainteneur peut gerer les correction_rules (lister, modifier, supprimer) via Telegram
- FR106 : Mainteneur peut suivre le budget API en temps reel via /budget
- FR107 : Friday peut purger automatiquement les donnees temporaires (mappings 30j, logs 7j, backups 30j)
- FR108 : Mainteneur peut modifier l'arborescence de classement documentaire
- FR109 : Friday peut extraire des taches depuis emails/transcriptions et les creer dans le systeme de taches
- FR110 : Mainteneur peut envoyer des fichiers (photo/document) via Telegram pour traitement
- FR111 : Friday peut envoyer les fichiers retrouves via Telegram (PDF complet, pas juste lien)
- FR112 : Friday peut traiter un dossier complet en batch a la demande ("range mes Downloads")
- FR113 : Friday peut nettoyer automatiquement la zone de transit VPS + rotation des logs >7j + backups >30j
- FR114 : Friday peut envoyer un message d'onboarding Telegram (guide topics + commandes)
- FR115 : Friday peut auto-recovery RAM par priorite (kill TTS avant STT, notifie Mainteneur)
- FR116 : Friday peut indexer la base documentaire du programme d'etudes medicales (RAG pgvector) [D19]
- FR117 : Friday peut generer le briefing matinal en version audio vocale (TTS Kokoro)
- FR118 : Friday peut surveiller les conflits de calendrier (Heartbeat Phase 3)
- FR119 : Friday peut envoyer des rappels de suivi patients (Heartbeat Phase 3)
- FR120 : Friday peut envoyer des rappels de renouvellement de contrats (Heartbeat Phase 3)
- FR121 : Friday peut envoyer des rappels d'entretien equipements (Heartbeat Phase 3)
- FR122 : Mainteneur peut overrider manuellement un trust level via /trust set
- FR123 : Friday peut importer des CSV bancaires via workflow n8n dedie
- FR124 : Friday peut traiter des fichiers via workflow n8n dedie
- FR125 : Friday peut surveiller les nouveaux enregistrements Plaud via workflow n8n (GDrive watch)
- FR126 : Friday peut executer un script cleanup-disk automatique (cron)
- FR127 : Friday peut detecter les restarts anormaux de services (crash loop)
- FR128 : Friday peut coacher en mode trust=blocked avec validation medicale obligatoire
- FR129 : Friday peut apprendre le style redactionnel d'Mainteneur (table core.writing_examples, few-shot injection)
- ~~FR130~~ : **RETIRE** — doublon de FR21 (digest soir)
- FR131 : Friday peut surveiller les images Docker via Watchtower (MONITOR_ONLY, alerte sans auto-update)
- FR132 : Friday peut verifier la sante des APIs externes (cron 30min, Anthropic, ~~EmailEngine OAuth~~ serveurs IMAP `[HISTORIQUE D25]`)
- FR133 : Friday peut collecter les metriques LLM par modele (table core.llm_metrics : accuracy, latence, cout)
- FR134 : Friday peut basculer automatiquement de modele si le budget est depasse (cost-aware routing)
- FR135 : Friday peut automatiser la prise de RDV Doctolib (Playwright, P2)
- FR136 : Friday peut consulter les factures fournisseurs EDF/Free (Playwright, P3)
- FR137 : Friday peut exporter les CSV bancaires automatiquement (Playwright fallback)
- FR138 : Friday peut generer un resume structure de reunion/consultation depuis Plaud Note (distinct de la transcription brute)
- FR139 : Friday peut rechercher les articles mentionnes dans une conversation Plaud sur PubMed et les ajouter a la bibliographie
- FR140 : Friday peut rechercher des photos par contenu visuel, date ou evenement (recherche semantique)
- FR141 : Friday peut verifier rapidement les interactions medicamenteuses en consultation
- FR142 : Friday peut acceder en temps reel aux bases de reference medicales (Vidal, Antibioclic, recommandations HAS)
- FR143 : Friday peut calculer rapidement les posologies en consultation
- FR144 : Friday peut comparer les versions d'un contrat (highlight des changements entre v1 et v2)
- FR145 : Friday peut detecter les articles cles manquants dans un domaine (completion bibliographique proactive)
- FR146 : Friday peut simuler un panel d'experts pour la correction des vignettes cliniques TCS
- FR147 : Friday peut auditer les abonnements avec inventaire complet, cout total mensuel et utilisation reelle
- FR148 : Friday peut exporter les factures classees par structure/mois pour le comptable (preparation dossier comptable)
- FR149 : Friday peut faire de la veille prix eBay/PriceCharting pour la collection JV + alertes variations de cote
- FR150 : Friday peut generer un document preuve pour assurance habitation (inventaire valorise collection JV)
- FR151 : Friday peut envoyer les recettes du jour chaque matin via Telegram (push quotidien)
- FR152 : Friday peut preparer un briefing de reprise complet au retour de vacances (resume de ce qui s'est passe pendant l'absence)

### NonFunctional Requirements (NFR1-NFR29)

**Performance (NFR1-NFR5)**

- NFR1 : Classification email < 30s par email
- NFR2 : Briefing matinal genere < 60s, pret avant 8h00
- NFR3 : Desktop Search reponse < 3s pour top-5 resultats
- NFR4 : Vocal round-trip (STT + LLM + TTS) <= 30s
- NFR5 : Pipeline OCR + classement < 45s par document

**Securite (NFR6-NFR11)**

- NFR6 : Anonymisation PII exhaustive — 100% PII detectees, 0 fuite sur dataset test
- NFR7 : Fail-explicit Presidio — STOP complet si indisponible, JAMAIS de fallback silencieux
- NFR8 : Zero exposition Internet — 0 port expose (tout via Tailscale)
- NFR9 : Secrets chiffres — 0 secret en clair (age/SOPS)
- NFR10 : Backup chiffre age — 100% chiffre, restore teste mensuel
- NFR11 : Redis ACL — Moindre privilege par service

**Fiabilite (NFR12-NFR16)**

- NFR12 : Disponibilite >= 99% uptime mensuel (~7h downtime max)
- NFR13 : Self-Healing < 30s (Docker restart), < 2min (auto-recover-ram)
- NFR14 : RAM stable <= 85% (VPS-4 48 Go) en continu
- NFR15 : Zero email perdu — Redis Streams, delivery garanti
- NFR16 : Backup quotidien fiable — 100% jours avec backup reussi

**Integration (NFR17-NFR20)**

- NFR17 : Anthropic API resilience — retry 3 tentatives, backoff exponentiel, alerte System
- NFR18 : ~~EmailEngine~~ IMAP resilience `[HISTORIQUE D25]` — alerte immediate, IMAP direct (aioimaplib)
- NFR19 : Telegram API resilience — queue messages, retry, log local
- NFR20 : Google Docs API (post-MVP) — skip thesis review si indisponible, notifier Mainteneur

**Maintenabilite (NFR21-NFR24)**

- NFR21 : Adaptateurs swappables — changement provider = 1 fichier + 1 env var
- NFR22 : Logs structures — 100% JSON structure (structlog), zero print(), zero emoji dans logs
- NFR23 : Migrations reversibles — backup pre-migration automatique, rollback possible
- NFR24 : Monitoring sans overhead — 0 Go additionnel (scripts bash + cron, pas Prometheus)

**Cout (NFR25-NFR26)**

- NFR25 : Budget mensuel maitrise <= 75 EUR/mois (VPS + API + veille)
- NFR26 : Cout migration ponctuel <= 50 EUR (Claude API)

**Veille & Gouvernance (NFR27-NFR29)**

- NFR27 : Benchmark mensuel automatise — 1er du mois, rapport dans Metrics
- NFR28 : Alerte obsolescence — si concurrent > 10% superieur sur >= 3 metriques
- NFR29 : Migration modele rapide — < 1 jour (adaptateur llm.py + env var)

### Additional Requirements

**Architecture (AR1-AR21)** — Voir PRD section Architecture

**Decisions (D1-D18)** — Voir PRD section Decisions

**Addendum (ADD1-ADD13)** — Voir PRD section Addendum

**Exigences techniques (I, T, C, S, X)** — Voir PRD section Exigences techniques

---

## FR Coverage Map

**151 FRs sur 20 Epics — 0 FR orpheline**

| Epic | Phase | Titre | FRs | Count |
|------|-------|-------|-----|-------|
| **1** | MVP | Socle Operationnel & Controle | FR14, FR16-18, FR26-36, FR43-45, FR105-107, FR113-115, FR122, FR126-127, FR131 | 28 |
| **2** | MVP | Pipeline Email Intelligent | FR1-7, FR104, FR109, FR129 | 10 |
| **3** | MVP | Archiviste & Recherche Documentaire | FR8-12, FR103, FR108, FR110-112, FR124 | 11 |
| **4** | MVP | Intelligence Proactive & Briefings | FR20-25, FR117 | 7 |
| **5** | MVP | Interaction Vocale & Personnalite | FR13, FR15, FR19, FR47 | 4 |
| **6** | MVP | Memoire Eternelle & Migration | FR38-40, FR46 | 4 |
| **7** | MVP | Agenda & Calendrier Multi-casquettes | FR41-42, FR102, FR118 | 4 |
| **8** | Growth | Suivi Financier & Detection Anomalies | FR37, FR59-62, FR123, FR136-137, FR147-148 | 10 |
| **9** | Growth | Tuteur & Superviseur de Theses | FR51-58, FR145 | 9 |
| **10** | Growth | Veilleur Droit | FR67-70, FR120, FR144 | 6 |
| **11** | Growth | Plaud Note & Transcriptions | FR63-66, FR125, FR138-139 | 7 |
| **12** | Growth | Self-Healing Avance (Tier 3-4) | FR71-73, FR132 | 4 |
| **13** | Growth | Gouvernance & Veille Modele IA | FR48-50, FR133-134 | 5 |
| **14** | Vision | Aide en Consultation Medicale | FR74-77, FR119, FR128, FR135, FR141-143 | 10 |
| **15** | Vision | Menus, Courses & Coach | FR78-83, FR151 | 7 |
| **16** | Vision | Entretien Cyclique & Rappels | FR84-85, FR121 | 3 |
| **17** | Vision | Enseignement Medical (TCS/ECOS/Cours) | FR86-89, FR116, FR146 | 6 |
| **18** | Vision | Gestion Personnelle (Photos, JV, CV, Mode HS) | FR92-100, FR140, FR149-150, FR152 | 13 |
| **19** | Vision | Optimisation Fiscale & Investissement | FR90-91, FR101 | 3 |
| **20** | Vision | Evolution Graphe de Connaissances | — (reevaluation Graphiti/Neo4j aout 2026) | 0 |
| | | **TOTAL** | | **151** |

### NFR Coverage

| NFRs | Epics concernes |
|------|----------------|
| NFR1-NFR5 (Performance) | Epics 2, 3, 4, 5 |
| NFR6-NFR11 (Securite) | Epic 1 (transversal) |
| NFR12-NFR16 (Fiabilite) | Epic 1 (transversal) |
| NFR17-NFR20 (Integration) | Epics 1, 2, 9 |
| NFR21-NFR24 (Maintenabilite) | Epic 1 (transversal) |
| NFR25-NFR26 (Cout) | Epics 1, 6, 13 |
| NFR27-NFR29 (Veille) | Epic 13 |

---

## Epic List

### MVP Day 1 — Epics 1-7 (82 FRs)

Detail complet dans [epics-mvp.md](epics-mvp.md)

| # | Epic | Stories | FRs | Priorite |
|---|------|---------|-----|----------|
| 1 | **Socle Operationnel & Controle** | 15 stories | 28 | CRITIQUE |
| 2 | **Pipeline Email Intelligent** | 7 stories | 10 | CRITIQUE |
| 3 | **Archiviste & Recherche Documentaire** | 7 stories | 11 | HIGH |
| 4 | **Intelligence Proactive & Briefings** | 5 stories | 7 | HIGH |
| 5 | **Interaction Vocale & Personnalite** | 4 stories | 4 | MEDIUM |
| 6 | **Memoire Eternelle & Migration** | 4 stories | 4 | HIGH |
| 7 | **Agenda & Calendrier Multi-casquettes** | 3 stories | 4 | MEDIUM |

### Growth Month 1-3 — Epics 8-13 (33 FRs)

Detail dans [epics-growth.md](epics-growth.md)

| # | Epic | Stories | FRs | Priorite |
|---|------|---------|-----|----------|
| 8 | **Suivi Financier & Detection Anomalies** | 5 stories | 10 | HIGH |
| 9 | **Tuteur & Superviseur de Theses** | 4 stories | 9 | HIGH |
| 10 | **Veilleur Droit** | 3 stories | 6 | MEDIUM |
| 11 | **Plaud Note & Transcriptions** | 4 stories | 7 | MEDIUM |
| 12 | **Self-Healing Avance (Tier 3-4)** | 3 stories | 4 | MEDIUM |
| 13 | **Gouvernance & Veille Modele IA** | 3 stories | 5 | MEDIUM |

### Vision 3+ mois — Epics 14-20 (36 FRs)

Detail dans [epics-vision.md](epics-vision.md)

| # | Epic | FRs | Priorite |
|---|------|-----|----------|
| 14 | **Aide en Consultation Medicale** | 10 | HIGH |
| 15 | **Menus, Courses & Coach** | 7 | LOW |
| 16 | **Entretien Cyclique & Rappels** | 3 | LOW |
| 17 | **Enseignement Medical (TCS/ECOS/Cours)** | 6 | MEDIUM |
| 18 | **Gestion Personnelle (Photos, JV, CV, Mode HS)** | 13 | LOW |
| 19 | **Optimisation Fiscale & Investissement** | 3 | LOW |
| 20 | **Evolution Graphe de Connaissances** | 0 | MEDIUM |

---

## Dependances inter-epics

```
Epic 1 (Socle) ──► Prerequis a TOUS les autres epics
    ├── Epic 2 (Email) ──► Epic 3 (Archiviste) [PJ → classement]
    │       ├── Epic 8 (Finance) [classification emails financiers]
    │       └── Epic 9 (These) [detection emails thesards]
    ├── Epic 4 (Proactivite) ──► depend de Epic 2, 3 pour contenu briefing
    ├── Epic 5 (Vocal) ──► transversal (STT/TTS utilise par tous)
    ├── Epic 6 (Memoire) ──► alimente Epic 3, 4 (recherche semantique)
    └── Epic 7 (Agenda) ──► alimente Epic 4 (briefing), Epic 15 (menus)

Epic 8 (Finance) ──► depend de Epic 2, 3
Epic 9 (These) ──► depend de Epic 6 (graphe), S2 (Google Docs API)
Epic 10 (Droit) ──► depend de Epic 3 (archiviste)
Epic 11 (Plaud) ──► depend de Epic 5 (STT), Epic 9 (biblio, FR139)
Epic 12 (Self-Healing) ──► depend de Epic 1 (Tier 1-2 stable)
Epic 13 (Gouvernance) ──► depend de Epic 1 (infra LLM)

Epic 14 (Consultation) ──► depend de Epic 1, APIs externes (S7)
Epic 15 (Menus) ──► depend de Epic 7 (agenda)
Epic 16 (Entretien) ──► depend de Epic 4 (heartbeat)
Epic 17 (Enseignement) ──► depend de Epic 9 (these/biblio)
Epic 18 (Personnel) ──► depend de Epic 3 (archiviste), Epic 5 (photos)
Epic 19 (Fiscal) ──► depend de Epic 8 (finance)
Epic 20 (Graphe) ──► depend de Epic 6 (memoire), evaluation externe
```
