# Sprint 2 — Growth Month 1-3 (Epics 8-13)

**22 stories | 33 FRs**

Prerequis : Sprint 1 (MVP) operationnel et stable pendant >= 1 semaine.

---

## Epic 8 : Suivi Financier & Detection Anomalies

Classification 5 perimetres financiers, import CSV, anomalies, audit abonnements, export comptable.

### Story 8.1 : Import & Classification Bancaire

As a Mainteneur,
I want importer mes releves bancaires CSV et les classifier par perimetre,
So que mes 5 structures financieres soient suivies separement.

**Acceptance Criteria:**

**Given** un fichier CSV bancaire est depose dans le dossier surveille ou importe via n8n
**When** le pipeline de classification s'execute
**Then** chaque transaction est classee dans le bon perimetre (SELARL, SCM, SCI-1, SCI-2, Perso) (FR59)
**And** aucune contamination croisee entre perimetres (FR37)
**And** le trust level est "propose" pour les premieres semaines

**Given** un workflow n8n dedie a l'import CSV est configure
**When** un nouveau fichier CSV apparait
**Then** le workflow declenche automatiquement le pipeline de classification (FR123)

**Given** la banque supporte l'export automatique
**When** l'export Playwright est configure
**Then** le CSV est exporte automatiquement (fallback) (FR137)

---

### Story 8.2 : Suivi Depenses & Tresorerie

As a Mainteneur,
I want voir l'evolution de mes depenses et tresorerie par perimetre,
So que je puisse anticiper les problemes financiers.

**Acceptance Criteria:**

**Given** des transactions classees existent pour un perimetre
**When** Mainteneur demande le suivi via Telegram (/finance [perimetre])
**Then** un resume est affiche : solde actuel, depenses du mois, evolution vs mois precedent (FR60)
**And** les tendances significatives sont mises en evidence

---

### Story 8.3 : Detection Anomalies Financieres

As a Mainteneur,
I want etre alerte en cas de facture double ou depense inhabituelle,
So que je detecte les erreurs ou fraudes rapidement.

**Acceptance Criteria:**

**Given** une transaction est identique a une precedente (meme montant + fournisseur + delai < 30j)
**When** le pipeline de detection s'execute
**Then** une alerte "facture potentiellement en double" est envoyee dans le topic Actions (FR61)
**And** le trust level est "propose" (Mainteneur confirme ou ignore)

**Given** une transaction depasse 2 ecarts-types par rapport au fournisseur
**When** le pipeline de detection s'execute
**Then** une alerte "depense inhabituelle" est envoyee avec comparaison historique
**And** precision anomalies >= 90% (US7)

---

### Story 8.4 : Audit Abonnements

As a Mainteneur,
I want un inventaire complet de mes abonnements avec leur utilisation,
So que je puisse identifier ceux que je paie inutilement.

**Acceptance Criteria:**

**Given** les transactions des 6 derniers mois sont analysees
**When** l'audit est declenche (mensuel ou a la demande)
**Then** un rapport liste tous les abonnements detectes : nom, montant, frequence (FR62)
**And** les abonnements non utilises sont signales (ex: "Disney+ non utilise depuis 5 mois") (FR147)
**And** le cout total mensuel des abonnements est calcule

---

### Story 8.5 : Export Comptable & Factures

As a Mainteneur,
I want preparer un dossier comptable par structure et par mois,
So que mon comptable recoive des donnees propres et classees.

**Acceptance Criteria:**

**Given** Mainteneur demande un export comptable pour un perimetre/mois
**When** le rapport est genere
**Then** les factures sont classees par structure/mois au format CSV ou PDF (FR148)

**Given** des factures fournisseurs (EDF, Free) sont consultables en ligne
**When** l'automatisation Playwright est configuree
**Then** les factures sont telechargees et archivees automatiquement (FR136)

---

## Epic 9 : Tuteur & Superviseur de Theses

Pre-correction methodologique, anti-hallucination references, 4 theses en parallele.

### Story 9.1 : Integration Google Docs API

As a Mainteneur,
I want que Friday puisse inserer des suggestions dans les Google Docs de mes thesards,
So que mes corrections soient directement visibles en mode revision.

**Acceptance Criteria:**

**Given** un Google Doc de these est configure pour surveillance
**When** Friday detecte un changement dans le document (webhook ou polling)
**Then** l'analyse est declenchee automatiquement

**Given** Friday a genere des suggestions methodologiques
**When** les suggestions sont approuvees par Mainteneur (trust=propose)
**Then** elles sont inserees en mode revision dans le Google Doc (FR52)
**And** le thesard voit les suggestions sans savoir que Friday existe (J4)

**Given** 4 theses sont actives simultanement
**When** une 5e est ajoutee
**Then** Friday refuse avec un message explicatif (FR53)

---

### Story 9.2 : Analyse Methodologique These

As a Mainteneur,
I want que Friday analyse la structure et la qualite methodologique de chaque these,
So que je puisse guider mes thesards plus efficacement.

**Acceptance Criteria:**

**Given** un chapitre de these est soumis pour analyse
**When** le contenu est anonymise via Presidio (FR55) et analyse par Claude Sonnet 4.5
**Then** Friday identifie : structure IMRAD, design, population cible, criteres inclusion/exclusion, methode d'echantillonnage (FR51)
**And** des suggestions de correction sont generees (FR54)

**Given** des erreurs statistiques ou methodologiques sont detectees
**When** le rapport est genere
**Then** chaque erreur est decrite avec : localisation, nature, suggestion de correction
**And** un niveau de severite est attribue (critique, important, mineur)

---

### Story 9.3 : Anti-Hallucination References

As a Mainteneur,
I want verifier que toutes les references citees existent reellement,
So qu'aucune these ne contienne de references inventees.

**Acceptance Criteria:**

**Given** une bibliographie de these est analysee
**When** chaque reference est verifiee via PubMed, CrossRef, et Semantic Scholar (T11)
**Then** un rapport est genere : references trouvees, non trouvees, references suspectes (FR56)

**Given** un journal est identifie dans la bibliographie
**When** il est croise avec les listes de journaux predateurs (Beall's list)
**Then** une alerte est emise pour chaque journal suspect (FR57)

---

### Story 9.4 : Completion Bibliographique

As a Mainteneur,
I want que Friday identifie les articles cles manquants dans la bibliographie,
So que les theses soient mieux ancrees dans la litterature.

**Acceptance Criteria:**

**Given** le domaine de recherche est identifie depuis le contenu de la these
**When** Friday recherche les articles cles dans PubMed/Semantic Scholar
**Then** une liste d'articles potentiellement manquants est proposee avec justification (FR58, FR145)
**And** le trust level est "propose" (Mainteneur valide les suggestions)

---

## Epic 10 : Veilleur Droit

Analyse de contrats, clauses abusives, comparaison de versions, rappels echeances.

### Story 10.1 : Analyse Contrat a la Demande

As a Mainteneur,
I want soumettre un contrat pour analyse depuis Telegram,
So que je puisse comprendre rapidement les points cles et risques.

**Acceptance Criteria:**

**Given** Mainteneur envoie un contrat (PDF/image) via Telegram
**When** le document est OCR-e et anonymise via Presidio (FR70)
**Then** Claude Sonnet 4.5 analyse le contrat et genere un resume : parties, objet, duree, clauses cles, risques (FR67)
**And** le trust level est "propose"

---

### Story 10.2 : Detection Clauses Abusives & Versions

As a Mainteneur,
I want detecter les clauses abusives et comparer les versions d'un contrat,
So que je puisse negocier en connaissance de cause.

**Acceptance Criteria:**

**Given** un contrat est analyse
**When** le pipeline de detection s'execute
**Then** les clauses potentiellement abusives sont identifiees avec recall >= 95% (FR69)
**And** chaque clause est expliquee avec la raison du signalement

**Given** deux versions d'un meme contrat sont soumises
**When** la comparaison est demandee
**Then** les changements sont mis en evidence (highlight) entre v1 et v2 (FR68, FR144)
**And** les ajouts, suppressions et modifications sont categorises

---

### Story 10.3 : Rappels Renouvellement Contrats

As a Mainteneur,
I want etre prevenu avant l'echeance de mes contrats,
So que je puisse renouveler ou resilier a temps.

**Acceptance Criteria:**

**Given** un contrat avec date d'echeance est enregistre
**When** l'echeance approche (30j, 15j, 7j)
**Then** un rappel proactif est envoye dans le topic Chat (FR120)
**And** le rappel inclut : nom du contrat, date d'echeance, action suggeree

---

## Epic 11 : Plaud Note & Transcriptions

Transcription audio, compte-rendu structure, extraction cascade, lien bibliographique.

### Story 11.1 : Integration Plaud & Transcription

As a Mainteneur,
I want que mes enregistrements Plaud soient transcrits automatiquement,
So que je n'aie pas a retranscrire manuellement mes reunions.

**Acceptance Criteria:**

**Given** un nouvel enregistrement Plaud est detecte sur Google Drive (S9)
**When** le workflow n8n Plaud Watch le detecte (FR125)
**Then** le fichier audio est telecharge et transcrit via Faster-Whisper (FR63)
**And** la transcription est stockee et indexee

---

### Story 11.2 : Compte-Rendu Structure

As a Mainteneur,
I want un resume structure de chaque reunion/consultation,
So que je puisse relire l'essentiel en 30 secondes.

**Acceptance Criteria:**

**Given** une transcription Plaud est disponible
**When** Claude Sonnet 4.5 analyse le texte (anonymise Presidio)
**Then** un compte-rendu structure est genere : participants, sujets, decisions, actions (FR64, FR138)
**And** le CR est distinct de la transcription brute

---

### Story 11.3 : Extraction & Routage Cascade

As a systeme Friday,
I want extraire les actions, taches et evenements d'une transcription et les router,
So que rien ne soit perdu apres une reunion.

**Acceptance Criteria:**

**Given** une transcription contient des actions ("il faut relancer le fournisseur")
**When** l'extraction s'execute
**Then** les taches sont proposees a Mainteneur via inline buttons (FR65)
**And** les evenements sont proposes pour ajout au calendrier

**Given** des informations extraites concernent differents modules
**When** le routage cascade s'execute
**Then** les taches → systeme de taches, les evenements → agenda, les infos these → module these (FR66)

---

### Story 11.4 : Lien Plaud vers Bibliographie PubMed

As a Mainteneur,
I want que les articles mentionnes en reunion soient retrouves et ajoutes a la biblio,
So que je n'oublie pas de referencer ce dont on a parle.

**Acceptance Criteria:**

**Given** une transcription mentionne un auteur ou un titre d'article ("l'etude de Dupont 2023 sur les SGLT2")
**When** Friday detecte la mention
**Then** une recherche PubMed/Semantic Scholar est effectuee automatiquement (FR139)
**And** les resultats sont proposes a Mainteneur pour ajout a la bibliographie de la these concernee (trust=propose)

---

## Epic 12 : Self-Healing Avance (Tier 3-4)

Detection connecteurs casses, drift accuracy, patterns de degradation.

### Story 12.1 : Detection Connecteurs Externes

As a systeme Friday,
I want detecter automatiquement les APIs externes en panne,
So que les problemes soient signales avant qu'ils n'impactent les utilisateurs.

**Acceptance Criteria:**

**Given** un cron 30min est configure
**When** le healthcheck APIs externes s'execute
**Then** chaque API est verifiee : Anthropic, EmailEngine OAuth, Google APIs, PubMed (FR132)
**And** les APIs en panne sont signalees dans le topic System

**Given** EmailEngine perd sa connexion OAuth
**When** le healthcheck detecte l'echec
**Then** une alerte specifique est envoyee avec suggestion de resolution (FR71)
**And** une tentative de reconnexion automatique est effectuee

---

### Story 12.2 : Detection Drift Accuracy

As a systeme Friday,
I want detecter la degradation progressive de l'accuracy,
So que les modules en difficulte soient identifies avant retrogradation.

**Acceptance Criteria:**

**Given** les metriques d'accuracy sont collectees sur 4 semaines
**When** l'analyse de tendance est executee
**Then** une pente negative significative est detectee (FR72)
**And** une alerte proactive est envoyee dans le topic System avec le module concerne

---

### Story 12.3 : Patterns Degradation & Alertes Proactives

As a systeme Friday,
I want detecter les correlations multi-indicateurs de degradation,
So que les pannes soient predites avant de survenir.

**Acceptance Criteria:**

**Given** les indicateurs accuracy, latence et taux d'erreur sont surveilles
**When** une correlation de degradation est detectee (ex: latence monte + accuracy baisse)
**Then** une alerte proactive est envoyee dans le topic System (FR73)
**And** une proposition de resolution est suggeree

---

## Epic 13 : Gouvernance & Veille Modele IA

Benchmark mensuel, metriques LLM, alerte obsolescence, migration facilitee.

### Story 13.1 : Benchmark Mensuel Automatise

As a Mainteneur,
I want un benchmark mensuel comparant Claude aux concurrents,
So que je sache si un meilleur modele existe.

**Acceptance Criteria:**

**Given** le cron n8n du 1er du mois se declenche
**When** la suite de 10-15 taches representatives est executee sur le modele actuel + 2-3 concurrents
**Then** un rapport comparatif est genere : accuracy, structured output, latence, cout/token, qualite FR (FR48)
**And** le rapport est pousse dans le topic Metrics (NFR27)
**And** le cout du benchmark est ~$2-3 (D18)

**Given** un concurrent est > 10% superieur sur >= 3 metriques simultanees
**When** le rapport est genere
**Then** une alerte est envoyee dans le topic System (FR49, NFR28)
**And** la recommandation est : garder, evaluer, ou migrer

---

### Story 13.2 : Metriques LLM par Modele

As a Mainteneur,
I want suivre les metriques detaillees de chaque appel LLM,
So que je puisse optimiser les couts et la qualite.

**Acceptance Criteria:**

**Given** un appel LLM est effectue via l'adaptateur llm.py
**When** la reponse est recue
**Then** les metriques sont enregistrees dans core.llm_metrics : accuracy, latence, cout, tokens (FR133)
**And** les metriques sont consultables via /budget

---

### Story 13.3 : Cost-Aware Routing & Migration

As a Mainteneur,
I want que Friday alerte si le budget API est depasse et puisse changer de modele,
So que les couts restent maitrise sans interruption de service.

**Acceptance Criteria:**

**Given** la consommation API du mois depasse 80% du budget (60 EUR sur 75)
**When** le seuil est atteint
**Then** une alerte est envoyee dans le topic System avec projection fin de mois

**Given** le budget est depasse
**When** le cost-aware routing est actif
**Then** un modele moins couteux est utilise automatiquement pour les taches non-critiques (FR134)
**And** une notification est envoyee a Mainteneur

**Given** une decision de migration de provider LLM est prise
**When** le nouvel adaptateur est deploye
**Then** le changement se fait via 1 fichier (llm.py) + 1 env var (FR50, NFR21, NFR29)
**And** la migration est effective en < 1 jour
