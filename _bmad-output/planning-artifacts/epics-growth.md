# Friday 2.0 - Epics Growth Month 1-3 (Epics 8-13)

**33 FRs | 22 stories | Detail moyen**

Prerequis : MVP (Epics 1-7) operationnel et stable.

---

## Epic 8 : Suivi Financier & Detection Anomalies

**10 FRs | 5 stories | HIGH**

Classification 5 perimetres, import CSV, detection anomalies, audit abonnements, export comptable.

**FRs** : FR37, FR59-FR62, FR123, FR136, FR137, FR147, FR148

**Dependances** : Epic 1 (socle), Epic 2 (emails financiers), Epic 3 (archiviste factures)

### Story 8.1 : Import & Classification Bancaire

**FRs** : FR37, FR59, FR123, FR137

**Description** : Importer les releves CSV bancaires et classifier sur 5 perimetres (SELARL, SCM, SCI Ravas, SCI Malbosc, Perso).

**Acceptance Criteria** :
- Import CSV via dossier surveille ou workflow n8n dedie (FR59, FR123)
- Classification LLM par perimetre sans contamination croisee (FR37)
- Export CSV bancaire automatique via Playwright fallback si banque le permet (FR137)
- Trust level = propose Day 1 pour classification financiere
- Precision anomalies >= 90% (US7)

**Estimation** : L

---

### Story 8.2 : Suivi Depenses & Tresorerie

**FRs** : FR60

**Description** : Suivre les depenses, tresorerie et evolution des comptes par perimetre.

**Acceptance Criteria** :
- Dashboard par perimetre : solde, depenses mois, evolution
- Comparaison mois precedent
- Alertes seuils configurables

**Estimation** : M

---

### Story 8.3 : Detection Anomalies Financieres

**FRs** : FR61

**Description** : Detecter factures doubles, depenses inhabituelles.

**Acceptance Criteria** :
- Detection factures en double (meme montant + meme fournisseur + delai < 30j)
- Detection depenses inhabituelles (> 2 ecarts-types)
- Trust level = propose (validation Mainteneur)
- 0 faux negatif critique (US7)

**Estimation** : M

---

### Story 8.4 : Audit Abonnements

**FRs** : FR62, FR147

**Description** : Inventaire abonnements avec cout total et utilisation reelle.

**Acceptance Criteria** :
- Inventaire complet des abonnements detectes (FR62)
- Cout total mensuel calcule
- Detection abonnements non utilises (FR147 : "Disney+ non utilise depuis 5 mois")
- Rapport periodique dans topic Metrics

**Estimation** : M

---

### Story 8.5 : Export Comptable & Factures

**FRs** : FR148, FR136

**Description** : Preparer dossier comptable et consulter factures fournisseurs.

**Acceptance Criteria** :
- Export factures classees par structure/mois pour comptable (FR148)
- Consultation factures EDF/Free via Playwright (FR136, P3)
- Format export : CSV/PDF classe par perimetre

**Estimation** : M

---

## Epic 9 : Tuteur & Superviseur de Theses

**9 FRs | 4 stories | HIGH**

Pre-correction methodologique Google Docs, anti-hallucination references, 4 theses parallele.

**FRs** : FR51-FR58, FR145

**NFRs** : NFR20 (Google Docs resilience)

**Dependances** : Epic 1 (socle), Epic 6 (graphe connaissances)

### Story 9.1 : Integration Google Docs API

**FRs** : FR52, FR53

**Description** : Connecter Google Docs API v1 pour inserer des suggestions en mode revision.

**Acceptance Criteria** :
- Google Docs API v1 Suggestions (pas commentaires ancres — S2)
- Support 4 theses en parallele max (FR53)
- Insertion suggestions mode revision (FR52)
- Trust level = propose (Mainteneur valide avant push vers thesard)

**Estimation** : M

---

### Story 9.2 : Analyse Methodologique These

**FRs** : FR51, FR54, FR55

**Description** : Analyser la structure methodologique et la qualite statistique.

**Acceptance Criteria** :
- Analyse IMRAD, design, population, criteres inclusion/exclusion (FR51)
- Verification qualite statistique et methodologique (FR54)
- Contenu these anonymise Presidio avant LLM cloud (FR55)
- Suggestions actionables en mode revision

**Estimation** : L

---

### Story 9.3 : Anti-Hallucination References

**FRs** : FR56, FR57

**Description** : Verifier l'existence des references citees et detecter les journaux predateurs.

**Acceptance Criteria** :
- Verification via PubMed, CrossRef, Semantic Scholar (FR56, T11)
- Detection journaux predateurs (Beall's list, etc.) (FR57)
- Rapport : references valides, non trouvees, journaux suspects

**Estimation** : M

---

### Story 9.4 : Completion Bibliographique

**FRs** : FR58, FR145

**Description** : Identifier les articles cles manquants et completer la bibliographie.

**Acceptance Criteria** :
- Detection articles cles manquants dans le domaine (FR58, FR145)
- Recherche proactive dans PubMed/Semantic Scholar
- Suggestions d'ajout avec justification
- Trust level = propose

**Estimation** : M

---

## Epic 10 : Veilleur Droit

**6 FRs | 3 stories | MEDIUM**

Analyse contrats, detection clauses abusives, comparaison versions, rappels renouvellement.

**FRs** : FR67-FR70, FR120, FR144

**Dependances** : Epic 1 (socle), Epic 3 (archiviste)

### Story 10.1 : Analyse Contrat a la Demande

**FRs** : FR67, FR70

**Description** : Analyser un contrat (pro, perso, universitaire) avec anonymisation.

**Acceptance Criteria** :
- Upload contrat via Telegram → analyse LLM (FR67)
- Anonymisation Presidio avant traitement (FR70)
- Resume structure : parties, objet, duree, clauses cles
- Trust level = propose

**Estimation** : M

---

### Story 10.2 : Detection Clauses Abusives & Versions

**FRs** : FR68, FR69, FR144

**Description** : Detecter les clauses abusives et comparer les versions.

**Acceptance Criteria** :
- Detection clauses abusives (recall >= 95%) (FR69)
- Resume contrat + comparaison versions (FR68)
- Highlight changements entre v1 et v2 (FR144)
- APIs juridiques : Legifrance PISTE (S8) si disponible

**Estimation** : L

---

### Story 10.3 : Rappels Renouvellement Contrats

**FRs** : FR120

**Description** : Heartbeat Phase 3 — rappels proactifs de renouvellement.

**Acceptance Criteria** :
- Detection dates d'echeance contrats (FR120)
- Rappel 30j/15j/7j avant echeance
- Notification dans topic Chat & Proactive

**Estimation** : S

---

## Epic 11 : Plaud Note & Transcriptions

**7 FRs | 4 stories | MEDIUM**

Transcription audio, compte-rendu structure, extraction actions, routage cascade.

**FRs** : FR63-FR66, FR125, FR138, FR139

**Dependances** : Epic 1 (socle), Epic 5 (STT)

### Story 11.1 : Integration Plaud Note & Transcription

**FRs** : FR63, FR125

**Description** : Surveiller les enregistrements Plaud via GDrive et transcrire.

**Acceptance Criteria** :
- Workflow n8n surveille GDrive pour nouveaux fichiers Plaud (FR125, S9)
- Transcription audio via Faster-Whisper (FR63)
- Fichier transcrit stocke

**Estimation** : M

---

### Story 11.2 : Compte-Rendu Structure

**FRs** : FR64, FR138

**Description** : Generer un resume structure de reunion/consultation.

**Acceptance Criteria** :
- Resume structure distinct de la transcription brute (FR64, FR138)
- Sections : participants, sujets abordes, decisions, actions
- Anonymisation Presidio avant LLM

**Estimation** : M

---

### Story 11.3 : Extraction & Routage Cascade

**FRs** : FR65, FR66

**Description** : Extraire actions/taches/evenements et router vers les modules.

**Acceptance Criteria** :
- Extraction taches → systeme taches (FR65)
- Extraction evenements → agenda (FR66)
- Routage vers modules : theses (si these mentionnee), biblio (FR139), finance, etc.
- Trust level = propose pour actions extraites

**Estimation** : M

---

### Story 11.4 : Lien Plaud → Bibliographie PubMed

**FRs** : FR139

**Description** : Rechercher les articles mentionnes dans une conversation sur PubMed.

**Acceptance Criteria** :
- Detection mentions d'articles/auteurs dans transcription (FR139)
- Recherche automatique PubMed/Semantic Scholar
- Ajout a la bibliographie de la these concernee
- Trust level = propose

**Estimation** : M

---

## Epic 12 : Self-Healing Avance (Tier 3-4)

**4 FRs | 3 stories | MEDIUM**

Detection connecteurs casses, drift accuracy, patterns degradation, healthcheck APIs.

**FRs** : FR71-FR73, FR132

**Dependances** : Epic 1 (Tier 1-2 stable)

### Story 12.1 : Detection Connecteurs Externes

**FRs** : FR71, FR132

**Description** : Detecter les connecteurs externes casses (~~EmailEngine~~ serveurs IMAP `[HISTORIQUE D25]`, APIs tierces).

**Acceptance Criteria** :
- Healthcheck APIs externes cron 30min (FR132) : Anthropic, ~~EmailEngine OAuth~~ serveurs IMAP `[HISTORIQUE D25]`, etc.
- Detection panne connecteur (FR71)
- Alerte System immediate avec suggestion de resolution
- Tentative reconnexion automatique

**Estimation** : M

---

### Story 12.2 : Detection Drift Accuracy

**FRs** : FR72

**Description** : Detecter la degradation progressive de l'accuracy des modules.

**Acceptance Criteria** :
- Analyse tendances accuracy sur 4 semaines glissantes (FR72)
- Detection degradation progressive (pente negative significative)
- Alerte System avec module concerne et recommandation

**Estimation** : M

---

### Story 12.3 : Patterns Degradation & Alertes Proactives

**FRs** : FR73

**Description** : Detecter des patterns de degradation avant que ca ne devienne critique.

**Acceptance Criteria** :
- Correlation multi-indicateurs : accuracy + latence + erreurs (FR73)
- Alertes proactives (prediction degradation future)
- Propositions de resolution dans topic System

**Estimation** : M

---

## Epic 13 : Gouvernance & Veille Modele IA

**5 FRs | 3 stories | MEDIUM**

Benchmark mensuel, alerte obsolescence, metriques LLM, bascule budget.

**FRs** : FR48-FR50, FR133, FR134

**NFRs** : NFR27-NFR29

**Dependances** : Epic 1 (socle LLM)

### Story 13.1 : Benchmark Mensuel Automatise

**FRs** : FR48, FR49

**Description** : Executer un benchmark mensuel comparant Claude Sonnet 4.5 aux concurrents.

**Acceptance Criteria** :
- Suite 10-15 taches representatives Friday (D18)
- Execution sur modele actuel + 2-3 concurrents
- Metriques : accuracy, structured output fidelity, latence, cout/token, qualite francais
- Alerte si concurrent > 10% superieur sur >= 3 metriques (FR49, NFR28)
- Rapport mensuel pousse dans Metrics (NFR27)
- Cron n8n 1er du mois, ~$2-3/mois

**Estimation** : L

---

### Story 13.2 : Metriques LLM par Modele

**FRs** : FR133

**Description** : Collecter les metriques LLM detaillees.

**Acceptance Criteria** :
- Table core.llm_metrics : accuracy, latence, cout par appel (FR133)
- Dashboard via /budget : consommation mois, projection
- Historique consultable

**Estimation** : M

---

### Story 13.3 : Cost-Aware Routing & Migration

**FRs** : FR50, FR134

**Description** : Basculer automatiquement si budget depasse, migration via adaptateur.

**Acceptance Criteria** :
- Si budget mensuel API depasse seuil → alerte + bascule vers modele moins couteux (FR134)
- Migration provider LLM = 1 fichier adaptateur + 1 env var (FR50, NFR21, NFR29)
- Anti-piege : 3 mois de superiorite consistante avant migration definitive

**Estimation** : M

---

## Resume Growth

| Epic | Stories | FRs | Estimation totale |
|------|---------|-----|-------------------|
| 8. Finance | 5 | 10 | L |
| 9. Theses | 4 | 9 | L |
| 10. Droit | 3 | 6 | M-L |
| 11. Plaud | 4 | 7 | M-L |
| 12. Self-Healing | 3 | 4 | M |
| 13. Gouvernance | 3 | 5 | M-L |
| **TOTAL** | **22** | **33** | |

**Sequence suggeree** :
1. Epic 8 (Finance) — besoin metier prioritaire apres email
2. Epic 9 (Theses) — Julie soutenance dans 6 semaines (J4)
3. Epic 11 (Plaud) — alimente theses (FR139)
4. Epic 10 (Droit) — analyse contrats existants
5. Epic 12 (Self-Healing Avance) — consolide stabilite
6. Epic 13 (Gouvernance) — benchmark mensuel, peut attendre
