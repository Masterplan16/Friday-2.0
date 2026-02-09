> **Mis a jour 2026-02-09** : D17 (Claude remplace Mistral), D19 (pgvector remplace Qdrant Day 1)

# Friday 2.0 - Epics Vision 3+ mois (Epics 14-20)

**36 FRs | Detail leger**

Prerequis : MVP (Epics 1-7) + Growth (Epics 8-13) operationnels.

Ces epics sont definis a haut niveau. Les stories detaillees seront elaborees quand le MVP et Growth seront stables.

---

## Epic 14 : Aide en Consultation Medicale

**10 FRs | HIGH**

Outils d'aide a la decision clinique en temps reel.

**FRs** : FR74-FR77, FR119, FR128, FR135, FR141-FR143

**Dependances** : Epic 1 (socle), APIs externes (S7 : BDPM, Vidal, Antibioclic)

**Contrainte critique** : **Trust level = blocked** pour toute fonctionnalite medicale (FR128). Validation medicale humaine obligatoire. Friday n'executera JAMAIS d'action medicale en autonomie.

| Story | FRs | Description |
|-------|-----|-------------|
| 14.1 Interpretation ECG | FR74 | Lecture traces ECG PDF anonymise, suggestions diagnostiques |
| 14.2 Interactions medicamenteuses | FR75, FR141 | Verification interactions via bases BDPM/Vidal |
| 14.3 Recommandations HAS & Posologies | FR76, FR77, FR142, FR143 | Acces temps reel HAS, calcul posologies, Vidal/Antibioclic |
| 14.4 Rappels suivi patients | FR119 | Heartbeat Phase 3 — rappels consultations de suivi |
| 14.5 Automatisation Doctolib | FR135 | Prise de RDV via Playwright (P2) |
| 14.6 Coach medical trust=blocked | FR128 | Encadrement strict : analyse seule, jamais d'action auto |

---

## Epic 15 : Menus, Courses & Coach

**7 FRs | LOW**

Planification menus, liste courses, programme sportif.

**FRs** : FR78-FR83, FR151

**Dependances** : Epic 7 (agenda)

| Story | FRs | Description |
|-------|-----|-------------|
| 15.1 Planification menus | FR78 | Menus hebdo (preferences famille 3 pers, saison, agenda) |
| 15.2 Liste de courses | FR79 | Generation auto depuis menus planifies |
| 15.3 Recettes du jour | FR80, FR151 | Push quotidien matin via Telegram |
| 15.4 Programme sportif | FR81, FR82, FR83 | Programme adapte, integration agenda, ajustement cross-module |

---

## Epic 16 : Entretien Cyclique & Rappels

**3 FRs | LOW**

Suivi maintenance vehicule, chaudiere, equipements.

**FRs** : FR84-FR85, FR121

**Dependances** : Epic 4 (Heartbeat Engine)

| Story | FRs | Description |
|-------|-----|-------------|
| 16.1 Suivi cycles entretien | FR84 | Vidange, CT, chaudiere, detartrage — dates + intervalles |
| 16.2 Rappels proactifs | FR85, FR121 | Notifications 30j/15j/7j avant echeance, proposition RDV |

---

## Epic 17 : Enseignement Medical (TCS/ECOS/Cours)

**6 FRs | MEDIUM**

Creation materiel pedagogique pour enseignement medical.

**FRs** : FR86-FR89, FR116, FR146

**Dependances** : Epic 9 (these/biblio), Epic 6 (graphe connaissances)

| Story | FRs | Description |
|-------|-----|-------------|
| 17.1 Indexation programme etudes | FR116 | RAG pgvector (PostgreSQL) base documentaire programme medical (S12) [D19] |
| 17.2 Generateur TCS | FR86, FR146 | Vignettes cliniques + simulation panel experts correction |
| 17.3 Generateur ECOS | FR88 | Examens Cliniques Objectifs Structures |
| 17.4 Actualisateur cours | FR89 | MAJ cours existants avec dernieres recommandations HAS |

**Note** : FR87 (simulation panel experts TCS) = meme fonctionnalite que FR146 (clarification Round 6).

---

## Epic 18 : Gestion Personnelle (Photos, JV, CV, Mode HS)

**13 FRs | LOW**

Regroupement modules personnels : photos, collection JV, CV academique, mode HS/vacances.

**FRs** : FR92-FR100, FR140, FR149-FR150, FR152

**Dependances** : Epic 3 (archiviste), Epic 5 (vocal)

### Sous-domaine Photos BeeStation

| Story | FRs | Description |
|-------|-----|-------------|
| 18.1 Indexation photos | FR92 | Classement photos BeeStation (transit VPS ephemere → BeeStation + copie PC) |
| 18.2 Recherche photos | FR93, FR140 | Recherche par contenu visuel, date, evenement (semantique) |

### Sous-domaine Collection JV

| Story | FRs | Description |
|-------|-----|-------------|
| 18.3 Inventaire JV | FR94 | Photos, etat, edition, plateforme |
| 18.4 Veille prix & valeur | FR95, FR96, FR149 | Suivi valeur marche, veille eBay/PriceCharting, alertes cote |
| 18.5 Document assurance | FR150 | Inventaire valorise pour assurance habitation |

### Sous-domaine CV & Mode HS

| Story | FRs | Description |
|-------|-----|-------------|
| 18.6 CV academique auto | FR97 | MAJ auto publications, theses dirigees, enseignement |
| 18.7 Mode HS/Vacances | FR98, FR99, FR100, FR152 | Reponses auto mails, alerte thesards, briefing reprise complet |

---

## Epic 19 : Optimisation Fiscale & Investissement

**3 FRs | LOW**

Aide decision financiere complexe.

**FRs** : FR90-FR91, FR101

**Dependances** : Epic 8 (suivi financier)

**Contrainte** : Trust level = propose minimum. Decisions financieres = validation humaine obligatoire.

| Story | FRs | Description |
|-------|-----|-------------|
| 19.1 Aide decision achat | FR90, FR91 | Analyse basee sur situation financiere reelle, gestion projets ponctuels |
| 19.2 Optimisation fiscale | FR101 | Suggestions inter-structures SELARL/SCM/SCI |

---

## Epic 20 : Evolution Graphe de Connaissances

**0 FRs | MEDIUM**

Point de decision, pas d'implementation immediate.

**Dependances** : Epic 6 (memoire), evaluation externe Graphiti/Neo4j

**Description** : Reevaluation du graphe de connaissances aout 2026 (ADD13).

**Criteres de decision** :
- Graphiti v1.0 stable : > 500 stars GitHub, doc API complete, tests 100k+ entites
- Si criteres atteints → migration vers Graphiti
- Si non → Neo4j Community Edition
- Si PostgreSQL knowledge.* + pgvector suffisent → pas de migration (KISS) [D19]

**Action** : Evaluation technique en aout 2026. Pas de story tant que le verdict n'est pas rendu.

---

## Resume Vision

| Epic | FRs | Priorite | Dependance cle |
|------|-----|----------|---------------|
| 14. Consultation | 10 | HIGH | APIs medicales (S7), trust=blocked |
| 15. Menus & Coach | 7 | LOW | Agenda (Epic 7) |
| 16. Entretien | 3 | LOW | Heartbeat (Epic 4) |
| 17. Enseignement | 6 | MEDIUM | Theses (Epic 9), RAG (S12) |
| 18. Personnel | 13 | LOW | Archiviste (Epic 3) |
| 19. Fiscal | 3 | LOW | Finance (Epic 8) |
| 20. Graphe | 0 | MEDIUM | Decision aout 2026 |
| **TOTAL** | **36** | | |

**Sequence suggeree** :
1. Epic 14 (Consultation) — valeur metier haute, besoin quotidien
2. Epic 17 (Enseignement) — besoin recurrent enseignement medical
3. Epic 16 (Entretien) — simple, heartbeat checks additionnels
4. Epic 15 (Menus) — qualite de vie
5. Epic 18 (Personnel) — modules utilitaires varies
6. Epic 19 (Fiscal) — necessite donnees financieres accumulees
7. Epic 20 (Graphe) — decision technique, pas d'urgence
