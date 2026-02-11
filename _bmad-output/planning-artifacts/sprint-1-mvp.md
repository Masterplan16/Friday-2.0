> **Mis a jour 2026-02-09** : D17 (Claude remplace Mistral), D19 (pgvector remplace Qdrant Day 1)

# Sprint 1 — MVP Day 1 (Epics 1-7)

**45 stories | 82 FRs | Priorite CRITIQUE**

Ce sprint livre un Friday 2.0 complet et utilisable au quotidien. Tous les composants MVP sont livres simultanement (pas de cercles progressifs — D9 design push-first).

---

## Epic 1 : Socle Operationnel & Controle

Le socle qui rend tout le reste possible. Infrastructure, Trust Layer, securite RGPD, interface Telegram, Self-Healing, operations quotidiennes.

### Story 1.1 : Infrastructure Docker Compose

As a administrateur systeme,
I want deployer tous les services residents via Docker Compose,
So that l'infrastructure Friday 2.0 soit operationnelle sur le VPS-4.

**Acceptance Criteria:**

**Given** un VPS-4 OVH (48 Go RAM, 12 vCores, 300 Go SSD) vierge avec Docker installe
**When** j'execute `docker compose up -d`
**Then** PostgreSQL 16 (avec pgvector), Redis 7, n8n 1.69.2+, et Caddy demarrent sans erreur [D19]
**And** chaque service repond a son healthcheck interne

**Given** tous les services sont demarres
**When** je mesure l'usage RAM total
**Then** l'usage est inferieur a 40.8 Go (85% de 48 Go — NFR14)
**And** chaque service a une restart policy `unless-stopped`

**Given** un service crashe (ex: Redis OOM)
**When** Docker detecte l'arret
**Then** le service redemarre automatiquement en < 30s (NFR13)

---

### Story 1.2 : Schemas PostgreSQL & Migrations

As a developpeur,
I want appliquer les 12 migrations SQL pour creer les schemas core/ingestion/knowledge,
So that la base de donnees soit prete pour tous les modules Friday.

**Acceptance Criteria:**

**Given** PostgreSQL 16 est demarre et accessible
**When** j'execute `python scripts/apply_migrations.py`
**Then** les 12 migrations (001-012) s'executent dans l'ordre sequentiellement
**And** chaque migration est enregistree dans la table `schema_migrations`

**Given** une migration echoue en cours d'execution
**When** le script detecte l'erreur
**Then** un backup pre-migration est restaure automatiquement
**And** l'etat de la base est identique a avant l'execution

**Given** les migrations sont appliquees
**When** j'inspecte les schemas
**Then** aucune table n'existe dans le schema `public`
**And** les 3 schemas core, ingestion, knowledge contiennent les tables attendues

---

### Story 1.3 : FastAPI Gateway & Healthcheck

As a administrateur systeme,
I want un endpoint de sante qui verifie les 10 services,
So that je puisse connaitre l'etat du systeme en un coup d'oeil.

**Acceptance Criteria:**

**Given** le FastAPI Gateway est demarre
**When** j'appelle `GET /api/v1/health`
**Then** je recois un JSON avec l'etat de 9 services (postgres, redis, n8n, emailengine, presidio, whisper, kokoro, surya, caddy) [D19 : Qdrant retire, pgvector integre a postgres]
**And** 3 etats possibles : healthy (tous critical OK), degraded (non-critical down), unhealthy (critical down)

**Given** un service non-critique (ex: Kokoro TTS) est arrete
**When** j'appelle `GET /api/v1/health`
**Then** le statut global est "degraded" (pas "unhealthy")
**And** le service defaillant est identifie dans la reponse

**Given** un appel healthcheck a ete fait il y a < 5s
**When** un nouveau appel est fait
**Then** le resultat est servi depuis le cache (TTL 5s — ADD6)

---

### Story 1.4 : Tailscale VPN & Securite Reseau

As a administrateur systeme,
I want configurer Tailscale pour que rien ne soit expose sur Internet public,
So that Friday soit accessible uniquement via VPN securise.

**Acceptance Criteria:**

**Given** Tailscale est installe sur le VPS
**When** j'active le mesh VPN
**Then** le VPS est accessible via le hostname `friday-vps` sur le reseau Tailscale
**And** aucun port n'est expose sur l'IP publique (NFR8)

**Given** Tailscale est configure
**When** j'inspecte les parametres d'authentification
**Then** 2FA (TOTP ou hardware key) est active (ADD9)
**And** device authorization manuelle est activee
**And** key expiry est configure a 90 jours

**Given** Redis est demarre
**When** j'inspecte les ACL Redis
**Then** chaque service a un user dedie avec privileges moindres (ADD8)
**And** le user `default` est desactive

---

### Story 1.5 : Presidio Anonymisation & Fail-Explicit

As a utilisateur soucieux du RGPD,
I want que toutes les donnees soient anonymisees avant envoi au LLM cloud,
So that mes informations personnelles ne quittent jamais le VPS en clair.

**Acceptance Criteria:**

**Given** un texte contenant des PII (nom, email, telephone, IBAN)
**When** le texte passe par `presidio_anonymize()`
**Then** toutes les PII sont remplacees par des placeholders `[TYPE_xxx]`
**And** le mapping est stocke ephemerement en memoire uniquement (ADD7)

**Given** le service Presidio est indisponible (crash, timeout)
**When** un module tente d'anonymiser un texte
**Then** une `NotImplementedError` est levee (JAMAIS de fallback silencieux — NFR7)
**And** le pipeline s'arrete completement
**And** une alerte est envoyee dans le topic System Telegram

**Given** le dataset de test PII (tests/fixtures/pii_samples.json)
**When** tous les echantillons sont passes par Presidio
**Then** 100% des PII sont detectees et anonymisees (NFR6)
**And** la latence est < 500ms pour 500 chars, < 1s pour 2000 chars, < 2s pour 5000 chars (ADD1)

---

### Story 1.6 : Trust Layer Middleware

As a module Friday,
I want que chaque action produise un recu standardise selon son trust level,
So that toutes les actions soient tracees et auditables.

**Acceptance Criteria:**

**Given** une fonction decoree avec `@friday_action(module="email", action="classify", trust_default="auto")`
**When** la fonction s'execute avec succes
**Then** un receipt est cree dans `core.action_receipts` avec status="auto"
**And** le receipt contient : input_summary, output_summary, confidence (0.0-1.0), reasoning
**And** une notification est envoyee dans le topic Metrics Telegram

**Given** une fonction decoree avec `trust_default="propose"`
**When** la fonction s'execute
**Then** un receipt est cree avec status="pending"
**And** un message avec inline buttons [Approve] [Reject] [Correct] est envoye dans le topic Actions
**And** l'action n'est PAS executee tant qu'Mainteneur n'a pas approuve

**Given** une fonction decoree avec `trust_default="blocked"`
**When** la fonction s'execute
**Then** un receipt est cree avec status="blocked"
**And** seule l'analyse est retournee, aucune action n'est executee
**And** une notification est envoyee dans le topic System

**Given** un ActionResult avec plusieurs steps
**When** le receipt est cree
**Then** la confidence du receipt est le MIN de tous les steps

---

### Story 1.7 : Feedback Loop & Correction Rules

As a Mainteneur,
I want corriger les actions de Friday et qu'il apprenne de mes corrections,
So that Friday s'ameliore continuellement sans intervention technique.

**Acceptance Criteria:**

**Given** un receipt dans le topic Actions avec inline buttons
**When** Mainteneur clique [Correct] et saisit la correction
**Then** le receipt est mis a jour avec status="corrected" et le champ `correction` est rempli
**And** l'evenement `action.corrected` est publie dans Redis Streams

**Given** 2+ corrections similaires existent pour un meme module/action (similarite >= 0.85)
**When** le nightly pattern detection s'execute (ADD2)
**Then** une proposition de regle est envoyee a Mainteneur via inline buttons dans le topic Actions
**And** la proposition contient : conditions, output attendu, source_receipts

**Given** Mainteneur approuve une proposition de regle
**When** la regle est creee
**Then** elle est inseree dans `core.correction_rules` avec active=true
**And** elle est injectee dans les prompts des prochaines actions du module concerne

**Given** Mainteneur veut gerer les regles existantes
**When** il utilise /rules list, /rules edit [id], /rules delete [id]
**Then** les regles sont listees/modifiees/supprimees dans `core.correction_rules`

---

### Story 1.8 : Trust Metrics & Retrogradation

As a systeme Friday,
I want calculer l'accuracy hebdomadaire et ajuster les trust levels automatiquement,
So that les modules peu fiables soient retrogrades sans intervention humaine.

**Acceptance Criteria:**

**Given** le cron nightly s'execute
**When** les metriques sont calculees pour chaque module/action
**Then** accuracy = 1 - (corrections / total_actions) est stockee dans `core.trust_metrics`
**And** la semaine (lundi-dimanche) est identifiee

**Given** un module/action a accuracy < 90% sur 1 semaine ET echantillon >= 10 actions
**When** le calcul nightly se termine
**Then** le trust level est retrograde de `auto` vers `propose` (FR30)
**And** une notification est envoyee dans le topic System
**And** l'evenement `trust.level.changed` est publie dans Redis Streams

**Given** un module/action a ete retrograde il y a < 2 semaines
**When** les conditions de promotion sont remplies
**Then** la promotion n'est PAS appliquee (anti-oscillation)
**And** le delai restant est indique

**Given** Mainteneur execute `/trust set email classify auto`
**When** la commande est traitee
**Then** le trust level est force a "auto" immediatement (override manuel — FR122)
**And** un receipt d'override est cree

---

### Story 1.9 : Bot Telegram Core & Topics

As a Mainteneur,
I want interagir avec Friday via Telegram avec 5 topics specialises,
So que chaque type d'information ait son propre canal sans melange.

**Acceptance Criteria:**

**Given** le bot Telegram est demarre et connecte au supergroup
**When** Mainteneur envoie un message texte dans le topic Chat
**Then** Friday recoit le message, le traite et repond dans le meme topic

**Given** les 5 topics sont crees (Chat & Proactive, Email, Actions, System, Metrics)
**When** Friday genere une notification email
**Then** elle est routee vers le topic Email (pas Chat, pas System)
**And** le routing suit la logique definie dans ADD11

**Given** Mainteneur tape /help dans n'importe quel topic
**When** le bot recoit la commande
**Then** la liste complete des commandes est affichee avec descriptions courtes
**And** les commandes incluent : /status, /journal, /receipt, /confiance, /stats, /budget, /vip, /trust, /rules, /help

**Given** c'est la premiere connexion d'Mainteneur
**When** le bot detecte un nouvel utilisateur
**Then** un message d'onboarding est envoye avec guide des topics et commandes principales (FR114)

---

### Story 1.10 : Bot Telegram Inline Buttons & Validation

As a Mainteneur,
I want valider ou rejeter les actions proposees via des boutons inline,
So que je puisse controler Friday rapidement sans taper de texte.

**Acceptance Criteria:**

**Given** une action trust=propose est creee (ex: classification email incertaine)
**When** le receipt est genere
**Then** un message apparait dans le topic Actions avec inline buttons [Approve] [Reject] [Correct]
**And** le message contient : input_summary, output_summary, confidence

**Given** Mainteneur clique [Approve]
**When** le callback est traite
**Then** le receipt passe en status="approved"
**And** l'action est executee (ex: email classe dans la categorie proposee)
**And** le message est mis a jour avec un indicateur visuel de confirmation

**Given** Mainteneur clique [Reject]
**When** le callback est traite
**Then** le receipt passe en status="rejected"
**And** l'action n'est PAS executee

**Given** Mainteneur clique [Correct] et saisit "finance" au lieu de "medical"
**When** la correction est enregistree
**Then** le receipt passe en status="corrected" avec correction="finance"
**And** le feedback loop (Story 1.7) prend le relais

---

### Story 1.11 : Commandes Telegram Trust & Budget

As a Mainteneur,
I want consulter les metriques de confiance et le budget API via Telegram,
So que je puisse surveiller la qualite et les couts de Friday.

**Acceptance Criteria:**

**Given** Mainteneur tape /confiance
**When** la commande est traitee
**Then** un tableau est affiche avec : module, action, accuracy%, trust_level, nb_actions (FR32)

**Given** Mainteneur tape /receipt [uuid]
**When** le receipt existe
**Then** le detail complet est affiche : input_summary, output_summary, confidence, reasoning, created_at
**And** avec l'option -v, les steps detailles sont aussi affiches (FR33)

**Given** Mainteneur tape /budget
**When** la commande est traitee
**Then** s'affichent : consommation API Claude mois courant en EUR, projection fin de mois, % du budget utilise
**And** alerte si projection > 75 EUR/mois (NFR25)

**Given** Mainteneur tape /journal
**When** la commande est traitee
**Then** les 20 dernieres actions sont listees avec : timestamp, module, action, status, confidence

---

### Story 1.12 : Backup Chiffre & Sync PC

As a Mainteneur,
I want que mes donnees soient sauvegardees quotidiennement et chiffrees,
So que je ne perde jamais rien meme en cas de panne catastrophique.

**Acceptance Criteria:**

**Given** le cron nightly s'execute a 03h00
**When** le script backup.sh se lance
**Then** un dump PostgreSQL complet est genere
**And** le dump est chiffre avec `age` (NFR10)
**And** le fichier chiffre est synchronise vers le PC d'Mainteneur via Tailscale (rsync)

**Given** un backup chiffre existe sur le PC d'Mainteneur
**When** un test de restore est execute (mensuel)
**Then** le dump est dechiffre et restaure dans une base de test
**And** l'integrite des donnees est verifiee (NFR16)

**Given** le backup quotidien echoue (espace disque, connexion PC)
**When** le script detecte l'echec
**Then** une alerte est envoyee dans le topic System Telegram
**And** le prochain backup est retente automatiquement

---

### Story 1.13 : Self-Healing Tier 1-2

As a systeme Friday,
I want me recuperer automatiquement des pannes courantes,
So qu'Mainteneur n'ait pas a intervenir manuellement.

**Acceptance Criteria:**

**Given** un service Docker crashe (ex: Redis OOM)
**When** Docker detecte l'arret du conteneur
**Then** le service redemarre automatiquement en < 30s (Tier 1 — NFR13)

**Given** la RAM VPS depasse 85%
**When** le script monitor-ram.sh detecte le depassement
**Then** une alerte est envoyee dans le topic System avec le % exact

**Given** la RAM VPS depasse 91%
**When** l'auto-recover-ram se declenche
**Then** les services sont tues par priorite : TTS (Kokoro) d'abord, puis STT (Whisper), puis OCR (Surya) (FR115)
**And** Mainteneur est notifie : "RAM critique 91% — Kokoro TTS arrete. Vocal TTS indisponible."
**And** la recovery complete en < 2min (NFR13)

**Given** un service a redemaree > 3 fois en 1 heure
**When** le monitor-restarts detecte le crash loop
**Then** une alerte critique est envoyee dans le topic System (FR127)
**And** le service n'est PAS relance (eviter crash loop infini)

---

### Story 1.14 : Monitoring Docker Images

As a administrateur systeme,
I want etre notifie quand de nouvelles versions d'images Docker sont disponibles,
So que je puisse decider quand mettre a jour.

**Acceptance Criteria:**

**Given** Watchtower est deploye en mode MONITOR_ONLY
**When** une nouvelle version d'image Docker est detectee
**Then** une notification est envoyee dans le topic System Telegram
**And** aucune mise a jour automatique n'est effectuee (FR131)

---

### Story 1.15 : Cleanup & Purge RGPD

As a systeme soucieux du RGPD,
I want purger automatiquement les donnees temporaires,
So que les donnees personnelles ne persistent pas au-dela du necessaire.

**Acceptance Criteria:**

**Given** le script cleanup-disk s'execute via cron quotidien
**When** des fichiers temporaires existent en zone transit VPS
**Then** les fichiers traites (PJ archivees) sont supprimes (FR113)

**Given** des mappings Presidio ont > 30 jours
**When** la purge s'execute
**Then** les mappings sont supprimes definitivement (FR107)

**Given** des logs ont > 7 jours ou des backups ont > 30 jours
**When** la rotation s'execute
**Then** les fichiers concernes sont supprimes (FR113)
**And** l'espace libere est notifie dans le topic Metrics

---

## Epic 2 : Pipeline Email Intelligent

Le besoin #1 d'Mainteneur : emails tries, PJ archivees, reponses brouillonnees — sans intervention humaine.

### Story 2.1 : Integration EmailEngine & Reception

As a systeme Friday,
I want recevoir les emails des 4 comptes IMAP en temps reel,
So que chaque email soit traite des sa reception.

**Acceptance Criteria:**

**Given** EmailEngine est configure avec 4 comptes IMAP
**When** un nouvel email arrive sur un des comptes
**Then** un evenement `email.received` est publie dans Redis Streams
**And** le consumer Python lit l'evenement et declenche le pipeline

**Given** EmailEngine est temporairement indisponible
**When** le healthcheck detecte la panne
**Then** une alerte est envoyee dans le topic System (NFR18)
**And** les emails sont recuperes au retour du service (aucune perte — NFR15)

---

### Story 2.2 : Classification Email LLM

As a Mainteneur,
I want que mes emails soient automatiquement classes par categorie,
So que je n'aie plus a trier manuellement.

**Acceptance Criteria:**

**Given** un email est recu et anonymise via Presidio
**When** Claude Sonnet 4.5 classifie l'email
**Then** une categorie est assignee (pro, finance, universite, recherche, perso, urgent, spam, inconnu)
**And** les correction_rules actives du module email sont injectees dans le prompt
**And** un receipt est cree avec la confidence de classification

**Given** la classification a un trust level "auto" et confidence >= 0.85
**When** le receipt est cree
**Then** la classification est appliquee automatiquement
**And** une notification discrete est envoyee dans le topic Metrics

**Given** la classification a un trust level "propose" ou confidence < 0.85
**When** le receipt est cree
**Then** un message avec inline buttons est envoye dans le topic Actions
**And** Mainteneur peut approuver, rejeter ou corriger

**Given** c'est le cold start (D16) avec ~100 emails non lus
**When** le traitement batch demarre
**Then** les emails sont traites par lots de 10-20
**And** TOUT est en trust=propose (calibrage initial)

---

### Story 2.3 : Detection VIP & Urgence

As a Mainteneur,
I want etre alerte immediatement pour les emails VIP et urgents,
So que je ne manque jamais un email critique.

**Acceptance Criteria:**

**Given** Mainteneur execute /vip dr.martin@example.com
**When** la commande est traitee
**Then** l'adresse est enregistree comme VIP via le Trust Layer (D7)

**Given** un email arrive d'un expediteur VIP
**When** le pipeline le traite
**Then** une notification push immediate est envoyee dans le topic Email (FR6)
**And** la notification contient : expediteur, objet, resume 1 ligne

**Given** un email non-VIP contient des mots-cles d'urgence appris
**When** le pipeline le traite
**Then** il est marque comme urgent et notifie dans le topic Email
**And** zero email urgent manque (US1)

---

### Story 2.4 : Extraction Pieces Jointes

As a systeme Friday,
I want extraire les PJ des emails et les transmettre a l'Archiviste,
So que les documents soient automatiquement OCR-es et classes.

**Acceptance Criteria:**

**Given** un email contient une ou plusieurs pieces jointes
**When** le pipeline email les detecte
**Then** chaque PJ est extraite et stockee en zone transit VPS
**And** un evenement `document.received` est publie dans Redis Streams pour chaque PJ

**Given** la PJ est un PDF, une image, ou un document Office
**When** l'evenement est publie
**Then** le module Archiviste (Epic 3) prend le relais automatiquement

---

### Story 2.5 : Brouillon Reponse Email

As a Mainteneur,
I want que Friday prepare des brouillons de reponse pour mes emails,
So que je gagne du temps en validant plutot qu'en redigeant.

**Acceptance Criteria:**

**Given** un email necessite une reponse (detecte par LLM)
**When** Claude Sonnet 4.5 genere un brouillon (texte anonymise Presidio)
**Then** le brouillon est presente dans le topic Actions avec inline buttons [Send] [Edit] [Reject]
**And** le trust level est "propose" (FR4)

**Given** des exemples de style redactionnel existent dans core.writing_examples
**When** le brouillon est genere
**Then** le style d'Mainteneur est reproduit via few-shot injection (FR129)

---

### Story 2.6 : Envoi Emails Approuves

As a Mainteneur,
I want envoyer les brouillons approuves directement depuis Telegram,
So que je n'aie pas a ouvrir mon client mail.

**Acceptance Criteria:**

**Given** Mainteneur clique [Send] sur un brouillon de reponse
**When** le callback est traite
**Then** l'email est envoye via EmailEngine depuis le bon compte IMAP (FR104)
**And** un receipt est cree avec status="approved"
**And** une confirmation d'envoi est affichee dans le topic Email

---

### Story 2.7 : Extraction Taches depuis Emails

As a Mainteneur,
I want que les taches mentionnees dans mes emails soient automatiquement detectees,
So que rien ne tombe entre les mailles du filet.

**Acceptance Criteria:**

**Given** un email contient une tache implicite ("merci de me renvoyer le document avant vendredi")
**When** Claude Sonnet 4.5 analyse l'email
**Then** la tache est extraite avec : description, deadline, priorite (FR109)
**And** elle est proposee a Mainteneur via inline buttons dans le topic Actions (trust=propose)

**Given** Mainteneur approuve la tache
**When** le callback est traite
**Then** la tache est creee dans `core.tasks` avec reference a l'email source

---

## Epic 3 : Archiviste & Recherche Documentaire

OCR, renommage, classement, recherche semantique — les documents trouves instantanement.

### Story 3.1 : OCR & Renommage Intelligent

As a Mainteneur,
I want que mes documents soient OCR-es et renommes automatiquement,
So que je retrouve facilement chaque document par son nom.

**Acceptance Criteria:**

**Given** un document PDF ou image arrive en zone transit
**When** Surya OCR extrait le texte
**Then** le texte est disponible pour analyse LLM
**And** la latence totale (OCR + renommage) est < 45s (NFR5)

**Given** le texte OCR est disponible
**When** Claude Sonnet 4.5 analyse le contenu (anonymise Presidio)
**Then** le document est renomme selon la convention : `YYYY-MM-DD_Type_Emetteur_MontantEUR.ext`
**And** le type, l'emetteur et le montant sont extraits du contenu

---

### Story 3.2 : Classement Arborescence

As a Mainteneur,
I want que mes documents soient classes automatiquement dans la bonne arborescence,
So que tout soit range sans effort.

**Acceptance Criteria:**

**Given** un document est renomme (Story 3.1)
**When** Claude Sonnet 4.5 determine la destination
**Then** le document est deplace dans le bon sous-dossier (pro/finance/universite/recherche/perso — D24)
**And** les factures finance sont classees par perimetre/annee/mois (ex: finance/selarl/2026/02-Fevrier/)
**And** les autres documents par categorie (ex: recherche/theses/, universite/cours/)

**Given** le classement est incertain (confidence < 0.80)
**When** le receipt est cree
**Then** le trust level passe a "propose" et Mainteneur valide via inline buttons

**Given** Mainteneur veut modifier l'arborescence
**When** il envoie une commande via Telegram (FR108)
**Then** la nouvelle structure est prise en compte pour les prochains classements

---

### Story 3.3 : Recherche Semantique Documents

As a Mainteneur,
I want rechercher mes documents par requete en langage naturel,
So que je retrouve n'importe quel document en quelques secondes.

**Acceptance Criteria:**

**Given** Mainteneur envoie une requete texte (ex: "facture EDF janvier 2026")
**When** la requete est convertie en embedding et comparee dans pgvector (PostgreSQL) [D19]
**Then** les top-5 resultats les plus pertinents sont retournes en < 3s (NFR3)
**And** chaque resultat contient : nom du fichier, score de pertinence, extrait du contenu

---

### Story 3.4 : Suivi Garanties

As a Mainteneur,
I want etre notifie avant l'expiration de mes garanties,
So que je puisse agir avant qu'il ne soit trop tard.

**Acceptance Criteria:**

**Given** un document contient une date de garantie (detectee par LLM)
**When** le document est archive
**Then** la garantie est enregistree dans knowledge.entities (type=GUARANTEE) avec date d'expiration

**Given** une garantie expire dans < 30 jours
**When** le Heartbeat Engine la detecte
**Then** une notification proactive est envoyee dans le topic Chat (FR12)
**And** le document de garantie original est referencable

---

### Story 3.5 : Detection Nouveaux Fichiers (Watchdog)

As a systeme Friday,
I want detecter automatiquement les nouveaux fichiers dans un dossier surveille,
So que les documents scannes ou importes soient traites sans intervention.

**Acceptance Criteria:**

**Given** un dossier surveille est configure (ex: /data/incoming/)
**When** un nouveau fichier apparait (scan physique, import CSV, drop manuel)
**Then** un evenement `document.received` est publie dans Redis Streams (FR103)
**And** le pipeline Archiviste prend le relais automatiquement

**Given** un workflow n8n est configure pour traitement fichiers
**When** le workflow detecte un nouveau fichier
**Then** le traitement est delegue au pipeline Python (FR124)

---

### Story 3.6 : Fichiers via Telegram

As a Mainteneur,
I want envoyer et recevoir des fichiers directement via Telegram,
So que je puisse archiver ou retrouver des documents depuis mon telephone.

**Acceptance Criteria:**

**Given** Mainteneur envoie un fichier (photo/PDF/document) via Telegram
**When** le bot recoit le fichier
**Then** le fichier est traite par le pipeline Archiviste (OCR → renommage → classement) (FR110)
**And** le resultat est confirme dans le topic Email ou Chat

**Given** Mainteneur demande un fichier ("envoie-moi la facture EDF de janvier")
**When** la recherche semantique trouve le document
**Then** le fichier PDF complet est envoye via Telegram (pas juste un lien) (FR111)

---

### Story 3.7 : Traitement Batch Dossier

As a Mainteneur,
I want pouvoir dire "range mes Downloads" et que tout soit traite,
So que je puisse nettoyer un dossier entier en une commande.

**Acceptance Criteria:**

**Given** Mainteneur envoie "range mes Downloads" via Telegram
**When** le bot identifie le dossier cible
**Then** tous les fichiers du dossier sont traites par le pipeline Archiviste (FR112)
**And** la progression est affichee dans le topic Metrics (X/N fichiers)

**Given** le traitement batch est termine
**When** le rapport est genere
**Then** Mainteneur recoit : N fichiers traites, N classes, N echecs avec raisons

---

## Epic 4 : Intelligence Proactive & Briefings

Friday pousse l'information au bon moment — design push-first (D9).

### Story 4.1 : Heartbeat Engine Core

As a systeme Friday,
I want verifier proactivement les situations urgentes selon le contexte,
So qu'Mainteneur soit prevenu avant de devoir demander.

**Acceptance Criteria:**

**Given** l'interval Heartbeat est de 30 minutes et il est dans les heures actives (8h-22h)
**When** le tick Heartbeat se declenche
**Then** le ContextProvider fournit : heure, jour, weekend, derniere activite Mainteneur, prochain evenement
**And** Claude Sonnet 4.5 decide quels checks executer selon le contexte (FR24)

**Given** le LLM decide d'executer check_urgent_emails (HIGH)
**When** le check s'execute
**Then** les emails urgents non traites sont detectes et signales si necessaire

**Given** il est 23h (quiet hours)
**When** le tick Heartbeat se declenche
**Then** seuls les checks de priorite HIGH sont executes (FR25)
**And** les notifications non-urgentes sont deferrees au lendemain

**Given** aucun check ne detecte d'anomalie
**When** tous les checks sont termines
**Then** Friday ne notifie PAS Mainteneur (80%+ du temps = silence = bon comportement)

---

### Story 4.2 : Briefing Matinal 8h

As a Mainteneur,
I want recevoir un briefing complet chaque matin a 8h,
So que je demarre ma journee informe en 90 secondes.

**Acceptance Criteria:**

**Given** il est 8h00 et le cron n8n se declenche
**When** le briefing est genere par Claude Sonnet 4.5
**Then** le message est envoye dans le topic Chat & Proactive
**And** il contient : emails urgents, PJ archivees, alertes thesards, evenements agenda, rappels
**And** il est lisible en < 2 minutes (US4)
**And** il est genere en < 60s (NFR2)

**Given** le briefing est genere
**When** la version vocale est demandee (ou configuree par defaut)
**Then** une version audio est generee via Kokoro TTS et envoyee comme message vocal (FR117)

---

### Story 4.3 : Digest Soir 18h

As a Mainteneur,
I want recevoir un resume de la journee a 18h,
So que je puisse voir ce que Friday a fait sans avoir a demander.

**Acceptance Criteria:**

**Given** il est 18h00 et le cron n8n se declenche
**When** le digest est genere
**Then** il est envoye dans le topic Metrics
**And** il contient : emails traites, corrections, accuracy du jour, documents archives, alertes

---

### Story 4.4 : Rapport Hebdomadaire

As a Mainteneur,
I want recevoir un rapport hebdomadaire chaque dimanche soir,
So que je puisse suivre les tendances de Friday sur la semaine.

**Acceptance Criteria:**

**Given** c'est dimanche soir et le cron n8n se declenche
**When** le rapport est genere
**Then** il est envoye dans le topic Metrics
**And** il contient : tableau trust par module, tendances accuracy, budget API consomme, comparaison semaine precedente (FR22)

---

### Story 4.5 : Alertes Immediates Push

As a Mainteneur,
I want etre alerte immediatement en cas de probleme critique,
So que je puisse reagir rapidement.

**Acceptance Criteria:**

**Given** la RAM depasse 85%
**When** le monitor detecte le depassement
**Then** une alerte immediate est envoyee dans le topic System

**Given** un service critique est down (PostgreSQL, Redis, FastAPI)
**When** le healthcheck detecte la panne
**Then** une alerte immediate est envoyee dans le topic System avec le service concerne

**Given** un trust level change (retrogradation auto)
**When** l'evenement trust.level.changed est publie
**Then** une notification est envoyee dans le topic Actions

---

## Epic 5 : Interaction Vocale & Personnalite

STT/TTS via Telegram + personnalite configurable — Friday a une voix et un caractere.

### Story 5.1 : STT Faster-Whisper

As a Mainteneur,
I want envoyer des messages vocaux a Friday via Telegram,
So que je puisse interagir en voiture ou les mains occupees.

**Acceptance Criteria:**

**Given** Mainteneur envoie un message vocal Telegram
**When** le bot recoit le fichier audio
**Then** Faster-Whisper (local VPS, ~4 Go RAM) transcrit le message en texte (FR15)
**And** le texte transcrit est traite comme un message texte normal

**Given** un message vocal de 30 secondes
**When** la transcription est effectuee
**Then** le resultat est disponible en < 10 secondes

---

### Story 5.2 : TTS Kokoro

As a Mainteneur,
I want que Friday me reponde en vocal quand c'est pertinent,
So que je puisse ecouter les reponses sans lire.

**Acceptance Criteria:**

**Given** une reponse texte est generee par Friday
**When** le contexte justifie une reponse vocale (message vocal entrant, briefing matinal)
**Then** Kokoro TTS (local VPS, ~2 Go RAM) genere un audio (FR19)
**And** l'audio est envoye comme message vocal Telegram

**Given** un vocal entrant + traitement LLM + generation TTS
**When** le cycle complet s'execute
**Then** la latence totale est <= 30s (NFR4)

---

### Story 5.3 : Recherche Vocale Documents

As a Mainteneur,
I want rechercher des documents par la voix,
So que je puisse retrouver un document en conduisant.

**Acceptance Criteria:**

**Given** Mainteneur envoie un vocal "qu'est-ce que j'avais lu sur les inhibiteurs SGLT2 le mois dernier ?"
**When** le pipeline STT → recherche semantique → LLM → TTS s'execute
**Then** les 3 documents les plus pertinents sont retournes avec extraits (FR13)
**And** la reponse est envoyee en vocal (TTS)

---

### Story 5.4 : Personnalite Configurable

As a Mainteneur,
I want configurer le ton et le style de Friday,
So que Friday s'adapte a mes preferences de communication.

**Acceptance Criteria:**

**Given** un fichier config/personality.yaml existe avec : tone, tutoiement, humour, verbosite
**When** le bot Telegram genere une reponse
**Then** le prompt system inclut les parametres de personnalite (D6)
**And** le ton de la reponse correspond a la configuration (FR47)

**Given** Mainteneur modifie le YAML
**When** le changement est detecte
**Then** la nouvelle personnalite est appliquee sans redemarrage

---

## Epic 6 : Memoire Eternelle & Migration

Friday se souvient de tout — graphe de connaissances + embeddings + migration historique.

### Story 6.1 : Graphe de Connaissances PostgreSQL

As a systeme Friday,
I want construire un graphe de connaissances a partir de tout le contenu traite,
So que les informations soient liees entre elles et exploitables.

**Acceptance Criteria:**

**Given** un email est traite par le pipeline
**When** les entites sont extraites (personnes, organisations, lieux, concepts)
**Then** elles sont stockees dans knowledge.entities avec type, aliases, properties (FR38)
**And** les relations sont stockees dans knowledge.entity_relations (SENT_BY, MENTIONS, etc.)

**Given** un document et un email mentionnent la meme personne
**When** l'entite est reconciliee
**Then** un lien cross-source est cree dans le graphe (FR40)
**And** le mention_count est incremente

---

### Story 6.2 : Embeddings pgvector (PostgreSQL)

As a systeme Friday,
I want generer des embeddings pour chaque contenu traite,
So que la recherche semantique soit precise et rapide.

**Acceptance Criteria:**

**Given** un nouveau contenu est traite (email, document, transcription)
**When** l'embedding est genere
**Then** il est stocke dans pgvector (PostgreSQL) via l'adaptateur vectorstore.py (FR39) [D19]
**And** l'index est mis a jour incrementalement

**Given** l'index pgvector contient N documents [D19]
**When** une requete semantique est executee
**Then** les top-K resultats sont retournes en < 3s (NFR3)

---

### Story 6.3 : Adaptateur Memorystore

As a developpeur,
I want un adaptateur abstrait pour le memorystore,
So que je puisse changer de backend sans toucher au code metier.

**Acceptance Criteria:**

**Given** l'interface abstraite MemoryStore est definie
**When** l'implementation PostgreSQL + pgvector est utilisee (D3, D19)
**Then** les operations CRUD sur les entites et relations fonctionnent
**And** la recherche par embedding retourne des resultats pertinents

**Given** une future migration vers Graphiti/Neo4j est decidee (ADD13)
**When** un nouvel adaptateur est cree
**Then** le code metier ne necessite aucune modification (NFR21)
**And** le changement se fait via 1 fichier + 1 env var

---

### Story 6.4 : Migration 110k Emails Historiques

As a Mainteneur,
I want migrer mes 110k emails historiques dans le graphe de connaissances,
So que Friday ait une base de connaissances riche des le Day 1.

**Acceptance Criteria:**

**Given** les 110k emails sont accessibles via les 4 comptes IMAP
**When** le script de migration est lance (batch nuit)
**Then** la sequence s'execute : PG d'abord (~9h) → graphe (~15-20h) → pgvector embeddings (~6-8h) (ADD12, D19)
**And** le cout total est <= 50 EUR Claude API (NFR26)

**Given** la migration est interrompue (crash, timeout)
**When** le script est relance
**Then** il reprend au dernier checkpoint (pas de retraitement) (FR46)
**And** chaque phase a son propre checkpoint independant

**Given** la migration est terminee
**When** les statistiques sont verifiees
**Then** tous les emails sont indexes avec entites et embeddings
**And** la recherche semantique retourne des resultats pertinents

---

## Epic 7 : Agenda & Calendrier Multi-casquettes

Detection d'evenements, sync Google Calendar, gestion multi-roles.

### Story 7.1 : Detection Evenements

As a Mainteneur,
I want que Friday detecte automatiquement les evenements dans mes emails,
So que je n'oublie aucun rendez-vous ou echeance.

**Acceptance Criteria:**

**Given** un email contient une information d'evenement ("reunion jeudi 14h salle 3")
**When** Claude Sonnet 4.5 analyse l'email
**Then** l'evenement est extrait avec : date, heure, lieu, participants, description (FR41)
**And** l'evenement est propose a Mainteneur via inline buttons (trust=propose)

**Given** Mainteneur approuve l'evenement
**When** le callback est traite
**Then** l'evenement est cree dans Google Calendar (FR102)

---

### Story 7.2 : Sync Google Calendar Bidirectionnelle

As a Mainteneur,
I want que Friday synchronise mon Google Calendar dans les deux sens,
So que les evenements soient toujours a jour.

**Acceptance Criteria:**

**Given** Google Calendar API v3 est connectee (S3)
**When** Friday lit les evenements existants
**Then** les evenements sont disponibles pour le ContextProvider du Heartbeat
**And** les conflits sont detectables

**Given** Mainteneur cree/modifie un evenement dans Google Calendar
**When** la sync bidirectionnelle detecte le changement (FR102)
**Then** l'evenement est mis a jour dans la memoire Friday
**And** le ContextProvider du Heartbeat est informe

---

### Story 7.3 : Multi-casquettes & Conflits Calendrier

As a Mainteneur,
I want que Friday comprenne mes differents roles (medecin, enseignant, chercheur),
So que le contexte soit toujours pertinent.

**Acceptance Criteria:**

**Given** un email arrive dans le compte IMAP de la faculte
**When** Friday le traite
**Then** le contexte "enseignant" est applique pour la classification et les suggestions (FR42)

**Given** deux evenements se chevauchent dans le calendrier
**When** le Heartbeat Engine detecte le conflit
**Then** une alerte est envoyee dans le topic Chat avec les details du conflit (FR118)
**And** Friday suggere des actions (deplacer, annuler, deleguer)
