> **Mis a jour 2026-02-09** : D17 (Claude remplace Mistral), D19 (pgvector remplace Qdrant Day 1)

# Friday 2.0 - Epics MVP Day 1 (Epics 1-7)

**82 FRs | 45 stories | Detail maximal**

Prerequis : Aucun — ces epics forment le socle complet de Friday 2.0.

---

## Epic 1 : Socle Operationnel & Controle

**28 FRs | 15 stories | CRITIQUE**

Le socle qui rend tout le reste possible. Infrastructure, Trust Layer, securite RGPD, Telegram, Self-Healing, operations.

**FRs** : FR14, FR16, FR17, FR18, FR26-FR36, FR43, FR44, FR45, FR105, FR106, FR107, FR113, FR114, FR115, FR122, FR126, FR127, FR131

**NFRs transversaux** : NFR6-NFR16, NFR21-NFR26

### Story 1.1 : Infrastructure Docker Compose

**Description** : Deployer le socle Docker Compose avec tous les services residents (PostgreSQL 16 avec pgvector, Redis 7, n8n 1.69.2+, Caddy). [D19]

**Acceptance Criteria** :
- `docker compose up -d` demarre tous les services sans erreur
- PostgreSQL accessible avec 3 schemas (core, ingestion, knowledge)
- Redis accessible avec ACL configurees par service (NFR11)
- pgvector (PostgreSQL) operationnel pour stockage vectoriel [D19]
- n8n accessible via reverse proxy Caddy
- Healthcheck endpoint `/api/v1/health` repond 200
- Tous services redemarrent automatiquement (restart: unless-stopped)
- Usage RAM total < 40.8 Go (85% de 48 Go VPS-4) (NFR14)

**Fichiers existants** : docker-compose.yml, docker-compose.services.yml

**Estimation** : S (deja partiellement implemente)

---

### Story 1.2 : Schemas PostgreSQL & Migrations

**Description** : Appliquer les 12 migrations SQL (001-012) pour creer les schemas core, ingestion, knowledge et toutes les tables.

**Acceptance Criteria** :
- Script `apply_migrations.py` execute les 12 migrations dans l'ordre
- Table `schema_migrations` trace les migrations appliquees
- Backup automatique pre-migration
- Rollback possible en cas d'erreur
- Aucune table dans le schema `public`
- Tables trust layer creees (core.action_receipts, core.correction_rules, core.trust_metrics)

**FRs** : Infrastructure pour FR26-FR33

**Fichiers existants** : database/migrations/001-012_*.sql, scripts/apply_migrations.py

**Estimation** : S

---

### Story 1.3 : FastAPI Gateway & Healthcheck

**Description** : Deployer le FastAPI Gateway avec auth simple, OpenAPI, et healthcheck etendu (10 services, 3 etats).

**Acceptance Criteria** :
- `GET /api/v1/health` retourne l'etat de 10 services (ADD6)
- 3 etats : healthy (tous critical OK), degraded (non-critical down), unhealthy (critical down)
- Cache healthcheck 5s TTL
- OpenAPI/Swagger UI accessible
- Auth bearer token simple (single-user)
- Logs structures JSON (NFR22)

**NFRs** : NFR12 (uptime 99%), NFR22 (logs structures)

**Estimation** : M

---

### Story 1.4 : Tailscale VPN & Securite Reseau

**Description** : Configurer Tailscale mesh VPN pour zero exposition Internet publique.

**Acceptance Criteria** :
- SSH uniquement via Tailscale (NFR8)
- 2FA TOTP/hardware key active (ADD9)
- Device authorization manuelle activee
- Key expiry 90 jours configure
- VPS hostname = `friday-vps`
- Aucun port expose sur IP publique
- Redis ACL configurees (gateway: read+write+pubsub, n8n: read+write, alerting: read+pubsub) (ADD8)

**NFRs** : NFR8 (zero exposition), NFR9 (secrets chiffres), NFR11 (Redis ACL)

**Estimation** : M (configuration manuelle dashboard Tailscale)

---

### Story 1.5 : Presidio Anonymisation & Fail-Explicit

**FRs** : FR34, FR35

**Description** : Deployer le pipeline Presidio + spaCy-fr pour anonymisation RGPD avec comportement fail-explicit.

**Acceptance Criteria** :
- Tout texte anonymise avant appel Claude Sonnet 4.5 (FR34)
- Si Presidio crash → NotImplementedError, pipeline STOP, alerte System (FR35, NFR7)
- Mapping ephemere en memoire uniquement pendant requete LLM (ADD7)
- Latence : email 500 chars < 500ms, email 2000 chars < 1s, document 5000 chars < 2s (ADD1)
- Dataset test PII 100% detectees, 0 fuite (NFR6)
- JAMAIS de credentials en default dans le code

**Fichiers existants** : agents/src/tools/anonymize.py

**Estimation** : M

---

### Story 1.6 : Trust Layer Middleware (@friday_action + ActionResult)

**FRs** : FR26, FR27

**Description** : Implementer le decorateur `@friday_action` et le modele `ActionResult` pour que chaque action module produise un recu standardise.

**Acceptance Criteria** :
- Decorateur `@friday_action(module, action, trust_default)` fonctionnel
- ActionResult Pydantic : input_summary, output_summary, confidence (0.0-1.0), reasoning, payload, steps
- Trust level `auto` : execute + cree receipt status="auto" + notifie topic Metrics
- Trust level `propose` : cree receipt status="pending" + envoie inline buttons topic Actions
- Trust level `blocked` : analyse seule, receipt status="blocked", notification System
- Receipt stocke dans core.action_receipts (migration 011)
- Confidence = MIN de tous les steps

**Fichiers existants** : agents/src/middleware/trust.py, agents/src/middleware/models.py

**Estimation** : L

---

### Story 1.7 : Feedback Loop & Correction Rules

**FRs** : FR28, FR29, FR105

**Description** : Implementer le cycle de correction : Antonio corrige → Friday detecte patterns → proposition de regle → validation → regle active.

**Acceptance Criteria** :
- Antonio peut corriger une action via Telegram (FR28)
- Correction stockee dans core.action_receipts.correction
- 2+ corrections similaires → proposition de regle via inline buttons Telegram (FR29)
- Pattern detection : clustering semantique nightly, similarite 0.85 (ADD2)
- CRUD correction_rules via Telegram : /rules list, /rules edit, /rules delete (FR105)
- ~50 regles max → un SELECT suffit, injectees dans les prompts (pas de RAG)
- core.correction_rules avec UUID PK, scope, priority, source_receipts, hit_count

**Estimation** : L

---

### Story 1.8 : Trust Metrics & Retrogradation/Promotion

**FRs** : FR30, FR31, FR122

**Description** : Implementer la retrogradation automatique et la promotion manuelle des trust levels.

**Acceptance Criteria** :
- Nightly metrics : accuracy(module, action, semaine) = 1 - (corrections / total) (ADD5)
- Retrogradation auto → propose si accuracy < 90% + echantillon >= 10 (FR30)
- Retrogradation → blocked si accuracy < 70% (ADD5)
- Promotion manuelle : /trust promote [module] [action] si accuracy >= 95% sur 3 semaines (FR31)
- Anti-oscillation : 2 semaines min entre retrogradation et nouvelle promotion
- Override manuel : /trust set [module] [action] [level] (FR122)
- Metrics stockees dans core.trust_metrics (migration 011)

**Fichiers existants** : services/metrics/nightly.py

**Estimation** : M

---

### Story 1.9 : Bot Telegram - Core & Topics

**FRs** : FR14, FR16, FR18, FR114

**Description** : Deployer le bot Telegram avec supergroup 5 topics et commandes de base.

**Acceptance Criteria** :
- Bot Telegram connecte au supergroup (ADD11)
- 5 topics crees : Chat & Proactive (DEFAULT), Email & Communications, Actions & Validations, System & Alerts, Metrics & Logs
- Antonio peut envoyer des messages texte au bot (FR14)
- Routing automatique des notifications vers le topic correct (FR16)
- Commande /help affiche la liste complete des commandes (FR18)
- Message onboarding envoye a la premiere connexion (FR114)
- 3 modes utilisateur : Normal, Focus (mute Email+Metrics), Deep Work (mute tout sauf System)

**Estimation** : L

---

### Story 1.10 : Bot Telegram - Inline Buttons & Validation

**FRs** : FR17

**Description** : Implementer les inline buttons pour validation/rejet des actions trust=propose.

**Acceptance Criteria** :
- Actions trust=propose → message dans topic Actions avec inline buttons [Approve] [Reject] [Correct]
- Clic Approve → receipt.status = "approved", action executee
- Clic Reject → receipt.status = "rejected", action annulee
- Clic Correct → Antonio saisit correction → receipt.status = "corrected"
- Retour haptic (confirmation visuelle apres clic)
- Timeout configurable (pas de timeout par defaut — attend indefiniment)

**Estimation** : M

---

### Story 1.11 : Commandes Telegram Trust & Budget

**FRs** : FR32, FR33, FR106

**Description** : Implementer les commandes Telegram pour consulter les metriques trust et le budget API.

**Acceptance Criteria** :
- /confiance → tableau accuracy par module/action, trust levels actuels (FR32)
- /receipt [id] → detail complet d'un recu (-v pour steps detailles) (FR33)
- /journal → 20 dernieres actions avec timestamps
- /status → dashboard temps reel (services, dernieres actions)
- /budget → consommation API Claude mois courant, projection, seuil alerte (FR106)
- /stats → metriques globales agregees
- Progressive disclosure : reponses courtes par defaut, -v pour details

**Estimation** : M

---

### Story 1.12 : Backup Chiffre & Sync PC

**FRs** : FR36

**Description** : Deployer le backup quotidien chiffre avec sync vers le PC d'Antonio.

**Acceptance Criteria** :
- Backup PostgreSQL quotidien chiffre age (NFR10)
- Sync vers PC Antonio via Tailscale (rsync)
- En transit : Tailscale/WireGuard TLS (ADD10)
- Au repos VPS : chiffre age
- Au repos PC : BitLocker/LUKS
- Restore teste mensuellement (NFR16)
- Script backup.sh executable via cron (03h00 nightly via n8n)

**Fichiers existants** : tests/e2e/test_backup_restore.sh

**Estimation** : M

---

### Story 1.13 : Self-Healing Tier 1-2

**FRs** : FR43, FR44, FR45, FR115, FR127

**Description** : Implementer le self-healing automatique (restart Docker, auto-recover-ram, detection crash loop).

**Acceptance Criteria** :
- Docker restart policy : unless-stopped sur tous les services (FR43)
- unattended-upgrades configure pour l'OS
- monitor-ram.sh alerte si RAM > 85% dans topic System (FR44, NFR14)
- auto-recover-ram tue les services par priorite (TTS < STT < OCR) si RAM > 91% (FR115)
- Notification Antonio apres chaque recovery automatique (FR45)
- Detection crash loop : > 3 restarts en 1h → alerte System (FR127)
- Self-healing < 30s Docker restart, < 2min auto-recover-ram (NFR13)

**Fichiers existants** : scripts/monitor-ram.sh

**Estimation** : M

---

### Story 1.14 : Monitoring Docker & Images

**FRs** : FR131

**Description** : Deployer Watchtower en mode monitor-only pour surveiller les images Docker.

**Acceptance Criteria** :
- Watchtower deploye en mode MONITOR_ONLY (FR131)
- Alerte Telegram (topic System) si nouvelle version image disponible
- JAMAIS d'auto-update (decision manuelle Antonio)
- Cron quotidien (nuit)

**Estimation** : S

---

### Story 1.15 : Cleanup & Purge RGPD

**FRs** : FR107, FR113, FR126

**Description** : Automatiser le nettoyage des donnees temporaires et la purge RGPD.

**Acceptance Criteria** :
- Purge mappings Presidio > 30 jours (FR107)
- Rotation logs > 7 jours (FR113)
- Rotation backups > 30 jours (FR113)
- Nettoyage zone transit VPS (fichiers temporaires PJ) (FR113)
- Script cleanup-disk executable via cron (FR126)
- Notification Telegram apres chaque cleanup (espace libere)

**Estimation** : S

---

### Story 1.16 : CI/CD Pipeline GitHub Actions

**FRs** : NFR22 (logs structures), NFR23 (reproductibilite)

**Description** : Mettre en place un pipeline CI/CD avec GitHub Actions pour tests automatiques et deploiement manuel securise.

**Acceptance Criteria** :
- Workflow `.github/workflows/ci.yml` avec jobs lint + test-unit + test-integration + build-validation
- Trigger sur PR + push vers master
- Cache pip dependencies + Docker layers (optimisation temps build)
- Script `scripts/deploy.sh` pour deploiement manuel VPS via Tailscale
- Backup PostgreSQL pre-deploiement automatique
- Healthcheck `/api/v1/health` avec retry 3x + rollback si echec
- Notification Telegram succes/echec deploiement
- Documentation `docs/deployment-runbook.md` (troubleshooting)
- Badge GitHub Actions status dans README.md

**NFRs** : NFR22 (logs CI/CD structures JSON), NFR23 (builds reproductibles)

**Dependances** : Stories 1.1-1.3 (Docker + Gateway + Healthcheck)

**Fichiers a creer** : .github/workflows/ci.yml, scripts/deploy.sh, docs/deployment-runbook.md

**Estimation** : M (1 jour)

---

### Story 1.17 : Preparation Repository Public

**FRs** : NFR8 (zero exposition), NFR9 (secrets chiffres), NFR10 (security hardening)

**Description** : Securiser le repository avant passage en public : chiffrement secrets SOPS/age, nettoyage tokens hardcodes, scan historique Git, documentation securite.

**Acceptance Criteria** :
- SOPS/age configure avec vraie cle publique (`.sops.yaml` mis a jour)
- `.env` chiffre via SOPS → `.env.enc` commite (NFR9)
- Tokens Telegram hardcodes supprimes de `scripts/setup_telegram_auto.py` (lecture depuis .env)
- Token Telegram actuel revoque via BotFather + nouveau token genere
- Historique Git scanne avec git-secrets ou truffleHog (zero secret expose)
- `.gitignore` verifie (couvre .env, *.key, credentials.json)
- `SECURITY.md` cree (politique divulgation vulnerabilites)
- `LICENSE` ajoute (MIT/Apache)
- GitHub branch protection activee sur master (force PR)
- GitHub Dependabot active (alerts securite)
- CI/CD fonctionnel (tests passent sur PR) (Story 1.16)

**NFRs** : NFR8 (zero exposition secrets), NFR9 (chiffrement age), NFR10 (security hardening)

**Dependances** : Story 1.16 (CI/CD doit fonctionner avant repo public)

**Fichiers a modifier** : scripts/setup_telegram_auto.py, .sops.yaml

**Fichiers a creer** : SECURITY.md, LICENSE, .env.enc

**Estimation** : M (1 jour)

**CRITIQUE** : Blocker avant passage repo public. Risque securite maximal si token Telegram fuite.

---

## Epic 2 : Pipeline Email Intelligent

**10 FRs | 7 stories | CRITIQUE**

Le besoin #1 d'Antonio. Pipeline complet : reception → anonymisation → classification → extraction PJ → brouillon reponse → envoi.

**FRs** : FR1-FR7, FR104, FR109, FR129

**NFRs** : NFR1 (< 30s/email), NFR15 (zero email perdu), NFR17 (Anthropic resilience), NFR18 (EmailEngine resilience)

**Dependances** : Epic 1 (socle complet)

### Story 2.1 : Integration EmailEngine & Reception

**FRs** : FR1 (partiel)

**Description** : Connecter les 4 comptes IMAP via EmailEngine et publier les emails recus dans Redis Streams.

**Acceptance Criteria** :
- 4 comptes IMAP configures dans EmailEngine
- Email recu → evenement `email.received` dans Redis Streams (delivery garanti)
- Consumer Python lit le stream et declenche le pipeline
- Retry automatique si EmailEngine indisponible (NFR18)
- Zero email perdu (NFR15)

**Fichiers existants** : services/email-processor/consumer.py

**Estimation** : M

---

### Story 2.2 : Classification Email LLM

**FRs** : FR1, FR2, FR7

**Description** : Classifier les emails entrants via Claude Sonnet 4.5 avec injection des correction_rules.

**Acceptance Criteria** :
- Email → Presidio anonymise → Claude Sonnet 4.5 classifie (FR1)
- Categories : medical, finance, faculty, personnel, urgent, spam, etc.
- Correction_rules du module email injectees dans le prompt (FR29)
- Notification classification dans topic Email Telegram
- Antonio peut corriger via inline buttons (FR2)
- Cold start : batch 10-20 emails, trust=propose, calibrage initial (FR7, D16)
- Accuracy >= 85% sur 4 comptes IMAP (US1)
- Latence < 30s par email (NFR1)

**Estimation** : L

---

### Story 2.3 : Detection VIP & Urgence

**FRs** : FR5, FR6

**Description** : Detecter les expediteurs VIP et les emails urgents.

**Acceptance Criteria** :
- Commande /vip [email] pour designer un expediteur VIP (FR5)
- VIP stockes via Trust Layer (apprentissage, pas YAML statique — D7)
- Email VIP → notification push immediate dans topic Email (FR6)
- Detection urgence : VIP + mots-cles appris + patterns
- Zero email urgent manque (US1)

**Estimation** : M

---

### Story 2.4 : Extraction Pieces Jointes

**FRs** : FR3

**Description** : Extraire les PJ des emails et les transmettre au module Archiviste.

**Acceptance Criteria** :
- PJ extraites et stockees en zone transit VPS (FR3)
- Evenement `document.received` publie dans Redis Streams
- Module Archiviste (Epic 3) prend le relais
- Types supportes : PDF, images, documents Office
- Zone transit nettoyee apres archivage (FR113)

**Estimation** : S

---

### Story 2.5 : Brouillon Reponse Email

**FRs** : FR4, FR129

**Description** : Rediger des brouillons de reponse email soumis a validation.

**Acceptance Criteria** :
- Brouillon genere par Claude Sonnet 4.5 (texte anonymise Presidio)
- Trust level = propose (FR4)
- Style redactionnel appris (table core.writing_examples, few-shot injection) (FR129)
- Inline buttons dans topic Actions : [Approve] [Edit] [Reject]
- Approve → envoi via EmailEngine (FR104)

**Estimation** : M

---

### Story 2.6 : Envoi Emails Approuves

**FRs** : FR104

**Description** : Envoyer les emails approuves par Antonio via EmailEngine.

**Acceptance Criteria** :
- Clic Approve → email envoye depuis le bon compte IMAP (FR104)
- Receipt cree avec status="approved"
- Confirmation envoi dans topic Email
- Historique envois consultable via /journal

**Estimation** : S

---

### Story 2.7 : Extraction Taches depuis Emails

**FRs** : FR109

**Description** : Extraire automatiquement les taches mentionnees dans les emails et les creer dans le systeme de taches.

**Acceptance Criteria** :
- LLM detecte les taches implicites dans les emails (FR109)
- Taches creees dans core.tasks avec reference email source
- Trust level = propose (validation Antonio pour les premieres semaines)
- Notification dans topic Actions avec inline buttons

**Estimation** : M

---

## Epic 3 : Archiviste & Recherche Documentaire

**11 FRs | 7 stories | HIGH**

OCR, renommage intelligent, classement arborescence, recherche semantique, suivi garanties.

**FRs** : FR8-FR12, FR103, FR108, FR110, FR111, FR112, FR124

**NFRs** : NFR3 (< 3s recherche), NFR5 (< 45s OCR+classement)

**Dependances** : Epic 1 (socle), Epic 2 (PJ emails)

### Story 3.1 : OCR & Renommage Intelligent

**FRs** : FR8, FR9

**Description** : OCR via Surya + renommage convention standardisee.

**Acceptance Criteria** :
- OCR sur images et PDF via Surya (~2 Go RAM) (FR8)
- Renommage : `YYYY-MM-DD_Type_Emetteur_MontantEUR.ext` (FR9)
- Pipeline : OCR → extraction metadata → LLM renommage (anonymise Presidio)
- Latence < 45s par document (NFR5)

**Estimation** : M

---

### Story 3.2 : Classement Arborescence

**FRs** : FR10, FR108

**Description** : Classer les documents dans l'arborescence configurable.

**Acceptance Criteria** :
- Arborescence initiale : Cabinet/Faculte/Finances/Personnel/Garanties (D8)
- Classification par LLM (trust=propose les premieres semaines, puis auto)
- Antonio peut modifier l'arborescence via commande Telegram (FR108)
- Sous-dossiers : Finances/SELARL/YYYY/MM-Mois/, etc.
- Pas de contamination inter-perimetres financiers (FR37 — Epic 8)

**Estimation** : M

---

### Story 3.3 : Recherche Semantique Documents

**FRs** : FR11

**Description** : Recherche semantique via pgvector (PostgreSQL) embeddings (Desktop Search D5). [D19]

**Acceptance Criteria** :
- Requete texte → top-5 resultats pertinents < 3s (NFR3)
- Embeddings generes via Claude (ou modele embeddings dedie)
- Index pgvector mis a jour a chaque nouveau document [D19]
- Resultats avec score de pertinence et extrait

**Estimation** : M

---

### Story 3.4 : Suivi Garanties

**FRs** : FR12

**Description** : Suivre les dates d'expiration de garanties et notifier proactivement.

**Acceptance Criteria** :
- Detection dates garantie dans les documents (LLM) (FR12)
- Stockage dans knowledge.entities (type=GUARANTEE)
- Heartbeat check : notification 30j avant expiration
- Garanties actives/expirees dans l'arborescence (Garanties/Actives, Garanties/Expirees)

**Estimation** : S

---

### Story 3.5 : Detection Nouveaux Fichiers (Watchdog)

**FRs** : FR103

**Description** : Surveiller un dossier pour detecter les nouveaux fichiers a traiter.

**Acceptance Criteria** :
- Watchdog Python surveille le dossier configure (FR103)
- Nouveau fichier → evenement `document.received` dans Redis Streams
- Support : scanner physique via dossier surveille (S11), import CSV (S6)
- Workflow n8n pour traitement fichiers (FR124)

**Estimation** : S

---

### Story 3.6 : Fichiers via Telegram (envoi/reception)

**FRs** : FR110, FR111

**Description** : Recevoir et envoyer des fichiers via Telegram.

**Acceptance Criteria** :
- Antonio envoie un fichier (photo/document) via Telegram → traitement automatique (FR110)
- Fichier traite par le pipeline Archiviste (OCR → renommage → classement)
- Antonio demande un fichier → Friday envoie le PDF complet via Telegram (FR111)
- Pas juste un lien mais le fichier entier

**Estimation** : M

---

### Story 3.7 : Traitement Batch Dossier

**FRs** : FR112

**Description** : Traiter un dossier complet en batch a la demande.

**Acceptance Criteria** :
- Commande Telegram "range mes Downloads" → traitement batch (FR112)
- Tous les fichiers du dossier passes par le pipeline (OCR → renommage → classement)
- Progression affichee dans topic Metrics
- Rapport final : N fichiers traites, N classes, N echecs

**Estimation** : M

---

## Epic 4 : Intelligence Proactive & Briefings

**7 FRs | 5 stories | HIGH**

Heartbeat Engine, briefings matinaux, digest soir, rapport hebdomadaire. Design push-first.

**FRs** : FR20-FR25, FR117

**NFRs** : NFR2 (briefing < 60s)

**Dependances** : Epic 1 (socle), Epic 2 (emails), Epic 3 (documents)

### Story 4.1 : Heartbeat Engine Core

**FRs** : FR23, FR24, FR25

**Description** : Implementer le Heartbeat Engine context-aware (LLM decide quels checks executer).

**Acceptance Criteria** :
- Interval configurable (default 30min) (FR23)
- LLM decideur : selectionne les checks pertinents selon le contexte (FR24)
- ContextProvider : heure, jour, weekend, derniere activite Antonio, prochain evenement
- Quiet hours 22h-8h (pas de notifications sauf urgence)
- 80%+ du temps = silence = bon comportement (FR25)
- Checks Day 1 : check_urgent_emails (HIGH), check_financial_alerts (MEDIUM), check_thesis_reminders (LOW)
- Checks registration avec priorites (high/medium/low)

**Spec existante** : agents/docs/heartbeat-engine-spec.md

**Estimation** : L

---

### Story 4.2 : Briefing Matinal 8h

**FRs** : FR20, FR117

**Description** : Generer et envoyer le briefing matinal agregant toutes les informations pertinentes.

**Acceptance Criteria** :
- Briefing genere a 8h via cron n8n (FR20)
- Contenu : emails urgents, PJ archivees, alertes thesards, evenements agenda, rappels
- Envoye dans topic Chat & Proactive
- < 2min de lecture (US4)
- Version audio vocale via Kokoro TTS (FR117)
- Genere < 60s (NFR2)

**Estimation** : M

---

### Story 4.3 : Digest Soir 18h

**FRs** : FR21

**Description** : Envoyer le digest automatique resumant l'activite de la journee.

**Acceptance Criteria** :
- Digest genere a 18h via cron n8n (FR21)
- Contenu : emails traites, corrections, accuracy, documents archives, alertes
- Envoye dans topic Metrics
- Format concis (5-10 lignes max)

**Estimation** : S

---

### Story 4.4 : Rapport Hebdomadaire

**FRs** : FR22

**Description** : Generer le rapport hebdomadaire automatique.

**Acceptance Criteria** :
- Rapport genere dimanche soir via cron n8n (FR22)
- Contenu : tableau trust par module, tendances accuracy, budget API consomme
- Envoye dans topic Metrics
- Comparaison semaine precedente (tendances)

**Estimation** : S

---

### Story 4.5 : Alertes Immediates Push

**Description** : Les alertes critiques sont poussees immediatement sans attendre les briefings.

**Acceptance Criteria** :
- RAM > 85% → alerte System immediate (J3)
- Service down → alerte System immediate
- Trust level change → notification Actions
- Email VIP urgent → notification Email immediate
- Retrogradation trust → notification System
- Design push-first (D9) : tout est pousse, commandes en fallback

**Estimation** : S

---

## Epic 5 : Interaction Vocale & Personnalite

**4 FRs | 4 stories | MEDIUM**

STT/TTS via Telegram, personnalite configurable.

**FRs** : FR13, FR15, FR19, FR47

**NFRs** : NFR4 (vocal round-trip <= 30s)

**Dependances** : Epic 1 (socle), Epic 3 (recherche documentaire pour FR13)

### Story 5.1 : STT - Faster-Whisper

**FRs** : FR15

**Description** : Transcrire les messages vocaux Telegram via Faster-Whisper local.

**Acceptance Criteria** :
- Message vocal Telegram → transcription texte (FR15)
- Faster-Whisper local VPS (~4 Go RAM) (D2)
- Transcription < 10s pour message 30s
- Texte transcrit traite comme message texte normal

**Estimation** : M

---

### Story 5.2 : TTS - Kokoro

**FRs** : FR19

**Description** : Repondre en synthese vocale via Kokoro TTS local.

**Acceptance Criteria** :
- Reponse texte → synthese vocale Kokoro (~2 Go RAM) (FR19)
- Audio envoye comme message vocal Telegram
- Qualite intelligible
- Latence totale (STT + LLM + TTS) <= 30s (NFR4)

**Estimation** : M

---

### Story 5.3 : Recherche Vocale Documents

**FRs** : FR13

**Description** : Rechercher des documents par requete vocale.

**Acceptance Criteria** :
- Message vocal → STT → recherche semantique pgvector (PostgreSQL) → resultats (FR13) [D19]
- Top-5 resultats retournes avec extraits
- Reponse vocale optionnelle (TTS)

**Estimation** : S

---

### Story 5.4 : Personnalite Configurable

**FRs** : FR47

**Description** : Configurer la personnalite de Friday via YAML.

**Acceptance Criteria** :
- Fichier YAML : tone, tutoiement, humour, verbosite (FR47, D6)
- Prompt system dynamique genere depuis le YAML
- Pas OpenClaw (D6, ADD4)
- Changeable a chaud sans redemarrage

**Estimation** : S

---

## Epic 6 : Memoire Eternelle & Migration

**4 FRs | 4 stories | HIGH**

Graphe de connaissances PostgreSQL + pgvector, memoire persistante, migration 110k emails. [D19]

**FRs** : FR38, FR39, FR40, FR46

**Dependances** : Epic 1 (socle PostgreSQL + pgvector) [D19]

### Story 6.1 : Graphe de Connaissances PostgreSQL

**FRs** : FR38, FR40

**Description** : Construire le graphe de connaissances dans PostgreSQL knowledge.*.

**Acceptance Criteria** :
- 10 types de noeuds (Person, Email, Document, Event, Task, Entity, Conversation, Transaction, File, Reminder) (AR11)
- 14 types de relations (SENT_BY, RECEIVED_BY, ATTACHED_TO, MENTIONS, RELATED_TO, etc.) (AR12)
- Tables knowledge.entities et knowledge.entity_relations (migration 007)
- Liens cross-source : email → document → personne → evenement (FR40)
- Memoire persistante : informations accumulees au fil du temps (FR38)

**Estimation** : M

---

### Story 6.2 : Embeddings pgvector (PostgreSQL)

**FRs** : FR39

**Description** : Generer et stocker les embeddings pour la recherche semantique.

**Acceptance Criteria** :
- Embeddings generes pour chaque contenu traite (FR39)
- Stockage dans pgvector (PostgreSQL) via adaptateur vectorstore.py [D19]
- Index mis a jour incrementalement
- Recherche semantique fonctionnelle (utilisee par Epic 3 Desktop Search)

**Estimation** : M

---

### Story 6.3 : Adaptateur Memorystore

**Description** : Implementer l'adaptateur memorystore.py (PostgreSQL + pgvector Day 1). [D19]

**Acceptance Criteria** :
- Interface abstraite MemoryStore
- Implementation PostgreSQL (knowledge.*) + pgvector (embeddings) (D3, D19)
- Factory pattern pour futur swap vers Graphiti/Neo4j ou Qdrant si >300k vecteurs (reevaluation aout 2026 — ADD13)
- Tests unitaires avec mocks

**Fichiers existants** : agents/src/adapters/memorystore.py

**Estimation** : M

---

### Story 6.4 : Migration 110k Emails Historiques

**FRs** : FR46

**Description** : Migrer les 110k emails existants avec checkpointing et reprise.

**Acceptance Criteria** :
- Batch nuit, ~18-24h, ~$45 Claude API (NFR26) (FR46)
- Checkpointing : reprise possible apres interruption
- Sequence : PG d'abord (9h) → graphe (15-20h) → pgvector embeddings (6-8h) (ADD12, D19)
- Checkpointing independant par phase
- Progress tracking visible
- Presidio anonymisation avant tout appel Claude

**Fichiers existants** : scripts/migrate_emails.py

**Estimation** : L

---

## Epic 7 : Agenda & Calendrier Multi-casquettes

**4 FRs | 3 stories | MEDIUM**

Detection evenements, multi-casquettes, sync Google Calendar.

**FRs** : FR41, FR42, FR102, FR118

**Dependances** : Epic 1 (socle), Epic 2 (emails)

### Story 7.1 : Detection Evenements

**FRs** : FR41

**Description** : Detecter les evenements dans les emails et transcriptions.

**Acceptance Criteria** :
- LLM extrait les informations d'evenements (date, heure, lieu, participants) (FR41)
- Evenements proposes a Antonio via inline buttons (trust=propose)
- Integration avec Google Calendar (FR102)

**Estimation** : M

---

### Story 7.2 : Sync Google Calendar Bidirectionnelle

**FRs** : FR102

**Description** : Synchroniser Google Calendar en lecture et ecriture.

**Acceptance Criteria** :
- Lecture : recuperation evenements existants (S3)
- Ecriture : creation d'evenements valides par Antonio (FR102)
- Sync bidirectionnelle : modifications Google Calendar refletees dans Friday
- Multi-calendriers (medecin, enseignant, chercheur)
- ContextProvider du Heartbeat utilise les evenements agenda

**Estimation** : M

---

### Story 7.3 : Multi-casquettes & Conflits Calendrier

**FRs** : FR42, FR118

**Description** : Gerer le contexte multi-casquettes et detecter les conflits.

**Acceptance Criteria** :
- 3 casquettes : medecin, enseignant, chercheur (FR42)
- Contexte casquette determine le comportement de Friday (classification, briefing)
- Detection conflits calendrier (Heartbeat Phase 3) : chevauchements → alerte (FR118)

**Estimation** : M

---

## Resume MVP

| Epic | Stories | FRs | Estimation totale |
|------|---------|-----|-------------------|
| 1. Socle Operationnel | 15 | 28 | XL |
| 2. Pipeline Email | 7 | 10 | L |
| 3. Archiviste | 7 | 11 | L |
| 4. Proactivite | 5 | 7 | M-L |
| 5. Vocal | 4 | 4 | M |
| 6. Memoire | 4 | 4 | L |
| 7. Agenda | 3 | 4 | M |
| **TOTAL** | **45** | **68+14 transversaux = 82** | |

**Sequence d'implementation suggeree** :
1. Epic 1 (Socle) — prerequis a tout
2. Epic 6 (Memoire) — PostgreSQL knowledge.* + pgvector necessaires pour Epic 3 [D19]
3. Epic 2 (Email) — besoin #1 Antonio
4. Epic 3 (Archiviste) — inseparable du pipeline email (PJ)
5. Epic 5 (Vocal) — STT/TTS transversal
6. Epic 7 (Agenda) — detecte evenements dans emails
7. Epic 4 (Proactivite) — briefing necessite tous les modules precedents
