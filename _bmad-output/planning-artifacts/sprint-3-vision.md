> **Mis a jour 2026-02-09** : D17 (Claude remplace Mistral), D19 (pgvector remplace Qdrant Day 1)

# Sprint 3 — Vision 3+ mois (Epics 14-20)

**36 FRs | ~25 stories**

Prerequis : Sprint 1 (MVP) + Sprint 2 (Growth) stables.

Les stories de ce sprint seront detaillees (AC Given/When/Then) au moment de l'implementation, quand les modules fondation seront stabilises. Les descriptions ci-dessous fournissent la structure et la direction.

---

## Epic 14 : Aide en Consultation Medicale

Outils d'aide a la decision clinique. **Tout en trust=blocked** — validation medicale humaine obligatoire.

### Story 14.1 : Interpretation Traces ECG

As a Mainteneur (medecin),
I want soumettre un ECG en PDF pour obtenir une interpretation assistee,
So que j'aie un second avis rapide en consultation.

**Acceptance Criteria:**

**Given** Mainteneur envoie un PDF d'ECG via Telegram
**When** le PDF est anonymise (Presidio) et analyse par Claude Sonnet 4.5
**Then** une interpretation est generee avec : rythme, frequence, anomalies detectees (FR74)
**And** le trust level est "blocked" — analyse seule, aucune action (FR128)
**And** un avertissement rappelle que c'est un outil d'aide, pas un diagnostic

---

### Story 14.2 : Verification Interactions Medicamenteuses

As a Mainteneur (medecin),
I want verifier rapidement les interactions entre medicaments,
So que je prescrive en securite.

**Acceptance Criteria:**

**Given** Mainteneur demande "interactions entre metformine et ramipril"
**When** les bases BDPM/Vidal sont interrogees (S7)
**Then** les interactions connues sont listees avec niveau de gravite (FR75, FR141)
**And** le trust level est "blocked"

---

### Story 14.3 : Recommandations HAS & Posologies

As a Mainteneur (medecin),
I want acceder rapidement aux recommandations HAS et calculer des posologies,
So que je puisse repondre aux questions cliniques en consultation.

**Acceptance Criteria:**

**Given** Mainteneur demande "recommandation HAS diabete type 2"
**When** les bases de reference sont interrogees
**Then** les recommandations actuelles sont affichees (FR76, FR142)

**Given** Mainteneur demande "posologie amoxicilline enfant 25kg"
**When** le calcul est effectue via Vidal/Antibioclic (S7)
**Then** la posologie recommandee est affichee avec references (FR77, FR143)
**And** le trust level est "blocked"

---

### Story 14.4 : Rappels Suivi Patients

As a Mainteneur (medecin),
I want etre rappele pour les suivis de patients,
So que je n'oublie aucune consultation de controle.

**Acceptance Criteria:**

**Given** un suivi patient est enregistre (post-consultation, post-intervention)
**When** la date de suivi approche
**Then** un rappel proactif est envoye dans le topic Chat (FR119, Heartbeat Phase 3)
**And** le trust level est "propose" (Mainteneur decide de l'action)

---

### Story 14.5 : Automatisation Doctolib

As a Mainteneur,
I want que Friday puisse prendre des RDV sur Doctolib,
So que je n'aie pas a naviguer manuellement sur le site.

**Acceptance Criteria:**

**Given** Mainteneur demande "prends un RDV dentiste semaine prochaine"
**When** le bot Playwright navigue sur Doctolib (T12)
**Then** les creneaux disponibles sont presentes a Mainteneur via inline buttons (FR135)
**And** le trust level est "propose" (validation avant reservation)

---

### Story 14.6 : Coach Medical trust=blocked

As a systeme Friday,
I want que TOUTES les fonctionnalites medicales soient strictement encadrees,
So qu'aucune action medicale ne soit executee automatiquement.

**Acceptance Criteria:**

**Given** n'importe quelle action du domaine medical
**When** elle est executee via @friday_action
**Then** le trust level est TOUJOURS "blocked" (FR128)
**And** seule l'analyse est retournee, jamais d'action automatique
**And** un disclaimer est inclus dans chaque reponse medicale

---

## Epic 15 : Menus, Courses & Coach

Planification alimentaire et sportive pour la famille.

### Story 15.1 : Planification Menus Hebdomadaires

As a Mainteneur,
I want que Friday planifie les menus de la semaine,
So que ma famille mange equilibre sans que je passe du temps a planifier.

**Acceptance Criteria:**

**Given** les preferences alimentaires de la famille (3 personnes) sont configurees
**When** la planification hebdomadaire est declenchee (dimanche soir)
**Then** les menus de la semaine sont proposes avec : petit-dejeuner, dejeuner, diner (FR78)
**And** les menus tiennent compte de la saison et de l'agenda (jours charges = repas simples)
**And** le trust level est "propose"

---

### Story 15.2 : Generation Liste de Courses

As a Mainteneur,
I want une liste de courses generee automatiquement depuis les menus,
So que je n'oublie rien au supermarche.

**Acceptance Criteria:**

**Given** les menus de la semaine sont approuves
**When** la liste de courses est generee
**Then** les ingredients sont listes par rayon (fruits/legumes, boucherie, epicerie, etc.) (FR79)
**And** les quantites sont calculees pour 3 personnes

---

### Story 15.3 : Recettes du Jour

As a Mainteneur,
I want recevoir les recettes du jour chaque matin,
So que je sache quoi preparer sans chercher.

**Acceptance Criteria:**

**Given** les menus du jour sont planifies
**When** il est 7h30 (avant le briefing matinal)
**Then** les recettes du jour sont envoyees dans le topic Chat (FR80, FR151)
**And** chaque recette contient : ingredients, temps de preparation, etapes

---

### Story 15.4 : Programme Sportif & Integration Agenda

As a Mainteneur,
I want un programme sportif adapte integre a mon agenda,
So que le sport soit planifie autour de mes contraintes.

**Acceptance Criteria:**

**Given** les objectifs sportifs d'Mainteneur sont configures
**When** le programme est genere
**Then** les seances sont adaptees au niveau et progressives (FR81)
**And** les seances sont integrees dans l'agenda selon les creneaux libres (FR82)
**And** les recommandations tiennent compte de l'agenda et des menus (FR83)

---

## Epic 16 : Entretien Cyclique & Rappels

Suivi maintenance vehicule, chaudiere, equipements.

### Story 16.1 : Suivi Cycles Entretien

As a Mainteneur,
I want que Friday suive les cycles d'entretien de mes equipements,
So que je n'oublie jamais une vidange ou un controle technique.

**Acceptance Criteria:**

**Given** les equipements sont enregistres avec leurs cycles (vidange 15000km, CT 2 ans, chaudiere 1 an)
**When** un cycle approche
**Then** un rappel proactif est envoye 30j/15j/7j avant l'echeance (FR84, FR85, FR121)

---

### Story 16.2 : Proposition Prise de RDV

As a Mainteneur,
I want que Friday propose de prendre RDV quand un entretien approche,
So que je n'aie qu'a valider.

**Acceptance Criteria:**

**Given** un rappel d'entretien est envoye
**When** Mainteneur souhaite agir
**Then** Friday propose des actions : recherche garage, prise RDV (Playwright si supporte) (FR85)
**And** le trust level est "propose"

---

## Epic 17 : Enseignement Medical (TCS/ECOS/Cours)

Creation de materiel pedagogique pour l'enseignement medical.

### Story 17.1 : Indexation Programme Etudes

As a Mainteneur (enseignant),
I want que la base documentaire du programme medical soit indexee,
So que Friday puisse creer du contenu pedagogique aligne.

**Acceptance Criteria:**

**Given** les documents du programme d'etudes sont fournis
**When** l'indexation RAG dans pgvector (PostgreSQL) s'execute (S12) [D19]
**Then** les documents sont disponibles pour recherche semantique (FR116)
**And** les items de competence sont identifies et stockes

---

### Story 17.2 : Generateur TCS

As a Mainteneur (enseignant),
I want generer des vignettes cliniques TCS a partir du programme,
So que je puisse creer des exercices pedagogiques rapidement.

**Acceptance Criteria:**

**Given** un item de competence est selectionne
**When** Friday genere une vignette TCS
**Then** elle contient : scenario clinique, question, options, reponses du panel (FR86)
**And** un panel d'experts est simule pour la correction (FR87, FR146)
**And** le trust level est "propose" (Mainteneur valide avant utilisation)

---

### Story 17.3 : Generateur ECOS

As a Mainteneur (enseignant),
I want generer des examens cliniques objectifs structures,
So que je puisse preparer les evaluations pratiques.

**Acceptance Criteria:**

**Given** un theme clinique est selectionne
**When** Friday genere un ECOS
**Then** il contient : scenario patient, checklist competences, grille evaluation (FR88)
**And** le trust level est "propose"

---

### Story 17.4 : Actualisateur Cours

As a Mainteneur (enseignant),
I want que mes cours existants soient mis a jour avec les dernieres recommandations,
So que le contenu soit toujours a jour.

**Acceptance Criteria:**

**Given** un cours existant est soumis pour mise a jour
**When** les recommandations HAS les plus recentes sont verifiees
**Then** les sections obsoletes sont identifiees et des mises a jour sont proposees (FR89)
**And** le trust level est "propose"

---

## Epic 18 : Gestion Personnelle (Photos, JV, CV, Mode HS)

### Story 18.1 : Indexation Photos BeeStation

As a Mainteneur,
I want que mes photos BeeStation soient indexees et classees,
So que je puisse retrouver n'importe quelle photo facilement.

**Acceptance Criteria:**

**Given** des photos sont presentes sur la BeeStation
**When** l'indexation est declenchee (transit VPS ephemere)
**Then** les photos sont analysees : contenu, date, evenement, personnes (FR92)
**And** les fichiers originaux restent sur BeeStation + copie PC (JAMAIS de stockage permanent VPS)

---

### Story 18.2 : Recherche Photos Semantique

As a Mainteneur,
I want rechercher mes photos par description ("vacances corse 2024", "gateau anniversaire"),
So que je n'aie pas a parcourir des dossiers.

**Acceptance Criteria:**

**Given** les photos sont indexees avec embeddings dans pgvector (PostgreSQL) [D19]
**When** Mainteneur envoie une requete de recherche
**Then** les photos correspondantes sont retournees via Telegram (FR93, FR140)

---

### Story 18.3 : Inventaire Collection JV

As a Mainteneur,
I want un inventaire complet de ma collection de jeux video,
So que je connaisse la valeur de ma collection.

**Acceptance Criteria:**

**Given** Mainteneur soumet des photos/descriptions de ses jeux
**When** Friday analyse les jeux
**Then** un inventaire est cree : titre, plateforme, edition, etat, photo (FR94)

---

### Story 18.4 : Veille Prix & Valeur JV

As a Mainteneur,
I want suivre la valeur de ma collection et etre alerte des bonnes affaires,
So que je puisse vendre ou acheter au bon moment.

**Acceptance Criteria:**

**Given** un inventaire JV existe
**When** la veille prix s'execute (eBay, PriceCharting)
**Then** la valeur de chaque jeu est mise a jour (FR95, FR149)
**And** les variations de cote significatives sont signalees (FR96)

---

### Story 18.5 : Document Preuve Assurance JV

As a Mainteneur,
I want generer un document d'inventaire valorise pour mon assurance,
So que ma collection soit couverte en cas de sinistre.

**Acceptance Criteria:**

**Given** l'inventaire JV avec valeurs est a jour
**When** Mainteneur demande un export assurance
**Then** un document PDF est genere : inventaire complet avec photos, valeurs, total (FR150)

---

### Story 18.6 : CV Academique Auto-Maintenu

As a Mainteneur (enseignant-chercheur),
I want que mon CV academique se mette a jour automatiquement,
So que je n'aie plus a le faire manuellement.

**Acceptance Criteria:**

**Given** Friday connait les publications, theses dirigees, et enseignements d'Mainteneur
**When** un nouvel element est detecte (nouvelle publication, soutenance these)
**Then** le CV academique est mis a jour automatiquement (FR97)
**And** le trust level est "propose"

---

### Story 18.7 : Mode HS / Vacances

As a Mainteneur,
I want activer un mode vacances qui gere les emails en mon absence,
So que je puisse deconnecter sereinement.

**Acceptance Criteria:**

**Given** Mainteneur active le mode HS via Telegram (/hs on)
**When** des emails non urgents arrivent
**Then** des reponses automatiques sont envoyees (FR98)
**And** les thesards sont alertes de l'indisponibilite d'Mainteneur (FR99)

**Given** Mainteneur desactive le mode HS (/hs off)
**When** il reprend le travail
**Then** un briefing de reprise complet est genere : resume de tout ce qui s'est passe pendant l'absence (FR100, FR152)
**And** le briefing est envoye dans le topic Chat

---

## Epic 19 : Optimisation Fiscale & Investissement

### Story 19.1 : Aide Decision Achat Complexe

As a Mainteneur,
I want une analyse basee sur ma situation financiere reelle avant un achat important,
So que je prenne des decisions eclairees.

**Acceptance Criteria:**

**Given** Mainteneur soumet un projet d'achat (voiture, travaux)
**When** Friday analyse la situation financiere (5 perimetres)
**Then** un rapport est genere : capacite financiere, impact tresorerie, recommandation (FR90, FR91)
**And** le trust level est "propose" (JAMAIS d'action automatique sur les finances)

---

### Story 19.2 : Suggestions Optimisation Fiscale

As a Mainteneur,
I want des suggestions d'optimisation fiscale entre mes structures,
So que je minimise ma charge fiscale legalement.

**Acceptance Criteria:**

**Given** les donnees financieres des 5 perimetres sont disponibles
**When** l'analyse fiscale est declenchee
**Then** des suggestions inter-structures (SELARL/SCM/SCI) sont proposees (FR101)
**And** le trust level est "propose"
**And** un disclaimer rappelle de consulter un expert-comptable

---

## Epic 20 : Evolution Graphe de Connaissances

**Point de decision — pas d'implementation immediate.**

### Story 20.1 : Evaluation Technique Graphiti/Neo4j

As a Mainteneur,
I want evaluer si une migration du graphe de connaissances est pertinente,
So que Friday utilise le meilleur outil disponible.

**Acceptance Criteria:**

**Given** nous sommes en aout 2026 (ADD13)
**When** l'evaluation technique est menee
**Then** les criteres sont verifies : Graphiti > 500 stars GitHub, doc API complete, tests 100k+ entites
**And** une recommandation est formulee : migrer vers Graphiti, migrer vers Neo4j CE, ou rester sur PostgreSQL + pgvector (KISS) [D19]
**And** aucune migration n'est effectuee sans validation explicite d'Mainteneur

---

## Resume Sprint 3

| Epic | Stories | FRs | Contrainte cle |
|------|---------|-----|---------------|
| 14. Consultation | 6 | 10 | trust=blocked obligatoire |
| 15. Menus & Coach | 4 | 7 | preferences famille |
| 16. Entretien | 2 | 3 | Heartbeat Phase 3 |
| 17. Enseignement | 4 | 6 | RAG programme medical |
| 18. Personnel | 7 | 13 | modules varies |
| 19. Fiscal | 2 | 3 | donnees financieres accumulees |
| 20. Graphe | 1 | 0 | decision aout 2026 |
| **TOTAL** | **~26** | **36** | |
