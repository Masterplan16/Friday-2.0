# FRIDAY 2.0 - Analyse des Besoins

> **Document produit par** : Mary (Business Analyst BMAD)
> **Date** : 1er février 2026
> **Utilisateur** : Antonio
> **Statut** : Analyse terminée, prêt pour l'Architect

---

## 1. Vision

**Friday 2.0** est un **second cerveau personnel à mémoire éternelle**, proactif, vocal et apprenant. Il remplace l'ancien espace Friday de MiraIdesk (qui se recentre exclusivement sur Jarvis en vue d'un SaaS).

Friday 2.0 n'est pas une application. C'est un **écosystème d'intelligence personnelle** qui ingère, comprend, agit, communique, apprend et analyse.

| Caractéristique | Description |
|----------------|-------------|
| Utilisateur unique | Antonio (extension famille envisageable plus tard) |
| Usage | Strictement individuel, jamais commercialisé |
| Périmètre | Vie professionnelle ET personnelle |
| Philosophie | Le système travaille en permanence, pousse l'info au bon moment, l'utilisateur ne va pas chercher |

---

## 2. Concept central : le Second Cerveau

### Mémoire éternelle
Rien ne s'oublie. Toute information entrante est indexée dans un **graphe de connaissances** avec des relations sémantiques. La recherche se fait par sens, pas par mots-clés.

> "Qu'est-ce que j'avais lu sur les inhibiteurs SGLT2 il y a 6 mois ?"
> "Quel était le problème méthodologique de Julie dont on a discuté en novembre ?"

### Routage intelligent
Chaque donnée entrante est analysée et envoyée aux bonnes compétences :

```
Un seul mail peut contenir :
  → une PJ (Archiviste)
  → une tâche (Moteur Vie)
  → un événement (Agenda)
  → une info sur une thèse (Tuteur Thèse)

Une seule transcription Plaud peut contenir :
  → des actions à faire (tâches)
  → une discussion sur une thèse (suivi)
  → une info contractuelle (Veilleur Droit)
```

### Proactivité
Friday 2.0 ne répond pas juste quand on lui parle. Elle prévient :

> "Le bail du cabinet arrive à échéance dans 60 jours."
> "Julie n'a pas touché à son Google Doc depuis 18 jours. Soutenance dans 5 semaines."
> "3ème nuit en dessous de 6h. Semaine chargée. On allège le programme sportif ?"
> "Contrôle technique dans 6 semaines. Je prends RDV ?"

### Apprentissage
Le système s'améliore avec les corrections d'Antonio. Au bout de 6 mois, Friday connaît ses préférences, son style, ses seuils.

### Personnalité paramétrable
Le ton, le tutoiement/vouvoiement, l'humour, le style de communication sont configurables par l'utilisateur.

---

## 3. Sources de données (entrées)

| Source | Mode d'ingestion |
|--------|-----------------|
| 4 comptes mails | Via Thunderbird |
| Documents scannés | Scanner physique |
| Photos | Téléphone → BeeStation |
| Transcriptions audio | Plaud Note |
| Google Docs | Thèses partagées avec étudiants |
| Téléchargements | Dossier en vrac sur PC |
| Relevés bancaires | Import CSV manuel (SELARL, SCM, 2 SCI, perso) |
| PDF ECG | Anonymisé manuellement par l'utilisateur |
| Contrats/baux | Scan ou PDF |
| Programme études médicales | Base documentaire fournie par l'utilisateur |
| Apple Watch Ultra | Sommeil, fréquence cardiaque, activité |
| Photos BeeStation | Photos stockées sur Synology BeeStation |

---

## 4. Compétences (modules)

### 4.1 Quotidien - flux continu

#### Moteur Vie (5/5)
- **Desktop Search sémantique** : recherche par sens dans tous les fichiers locaux (PDF, Docx, articles, thèses, cours)
- **Pipeline mail** : 4 comptes via Thunderbird, ~20 mails/jour minimum
  - Classement automatique par catégories prédéfinies
  - Extraction des tâches à réaliser et référencement
  - Priorisation par ordre d'urgence
  - Extraction des pièces jointes → envoi vers l'Archiviste
  - Brouillons de réponse (rédaction dans le style d'Antonio)

#### L'Archiviste (5/5)
- **Ingestion multi-source** : scans, PJ des mails, photos téléphone, téléchargements
- **OCR** automatique
- **Renommage intelligent** (pas "scan_001.pdf")
- **Classement automatique** par catégories : un dossier en vrac → tout classé
- **Recherche** : retrouver n'importe quel document facilement
- **Données sensibles** : factures, comptes, contrats → anonymisation réversible avant traitement LLM
- **Suivi des garanties** : chaque achat = facture archivée + date d'expiration de garantie trackée

#### Agenda (5/5)
- Extraction automatique d'événements depuis les mails et transcriptions
- **Ultra complet** : toutes les casquettes (cabinet, fac, recherche, thèses, perso)
- Gestion intelligente du temps multi-casquettes
- Intégration avec le coach sportif et les menus
- Au minimum aussi bien que l'ancien Friday, voire mieux

#### Briefing matinal intelligent
- Résumé quotidien agrégé de TOUS les modules
- Mails urgents, tâches du jour, avancement thèses, alertes contrats/échéances, finances, entretien cyclique
- Livrable par Discord, vocal, ou notification push

#### Plaud Note (4/5)
- Transcription audio → compte rendu automatique
- **Cascade d'actions** à partir d'une seule transcription :
  - Résumé de réunion
  - Actions détectées → tâches créées
  - Dates mentionnées → ajoutées à l'agenda
  - Points sur une thèse → notés dans le suivi
  - Articles mentionnés → recherchés et ajoutés à la biblio

#### Photos (BeeStation)
- Indexation et classement des photos stockées sur le BeeStation
- Recherche par contenu/date/événement
- Organisation automatique

### 4.2 Professionnel - médecin

#### Aide en consultation (4/5)
- **ECG-Reader** : interprétation de tracés ECG (PDF anonymisé) en contexte de soins
- **Interactions médicamenteuses** : vérification rapide
- **Recommandations HAS** : accès temps réel aux dernières recos
- **Posologies** : calcul rapide
- Accès aux bases de référence (Vidal, Antibioclic, etc.)
- Via commande vocale ou téléphone, rapide

#### Veilleur Droit (5/5)
- Analyse à la demande de tout contrat (pro/perso/universitaire)
- Résumé, comparaison de versions, détection de clauses abusives, audit juridique
- Données sensibles → anonymisation réversible avant traitement LLM

### 4.3 Professionnel - enseignant

#### Tuteur Thèse (5/5)
- Pré-correction méthodologique sur Google Docs partagés
- 4 thèses en parallèle maximum
- Vérifie : structure (IMRAD), méthodologie, design, statistiques, rédaction
- Sortie : commentaires dans le Google Doc
- Inspiré des capacités existantes de Jarvis (PICO, analyses quali/quanti, etc.)

#### Check Thèse (5/5)
- Anti-hallucination : vérifier que les références citées existent réellement
- Qualité des sources : niveau de preuve, journal prédateur
- Complétude bibliographique : articles clés manquants dans le domaine
- Sur les mêmes Google Docs que le Tuteur Thèse

#### Générateur TCS (3/5)
- Création de vignettes cliniques (Tests de Concordance de Script)
- **Simulation d'un panel d'experts** pour la correction
- Base = programme complet des études médicales fourni par Antonio

#### Générateur ECOS (3/5)
- Création d'Examens Cliniques Objectifs Structurés
- Méthodes fournies par Antonio
- Même base programme que les TCS

#### Actualisateur de cours (3/5)
- Mise à jour de cours **existants** avec les dernières données et recommandations
- Pas de création from scratch
- Process de conception de formation à implémenter (fournis par Antonio)

### 4.4 Financier

#### Suivi financier (5/5)
- **5 périmètres** : SELARL, SCM, 2 SCI, perso
- Dépenses, évolution des comptes, trésorerie
- Import CSV manuel depuis les sites bancaires
- Ne remplace pas le comptable, prépare le travail
- Classement factures par structure/mois pour export comptable

#### Détection d'anomalies
- Facture en double, dépense inhabituelle, seuil de trésorerie
- Audit des abonnements : nombre, coût total, utilisation réelle
- "Tu as 11 abonnements pour 142€/mois. Disney+ non utilisé depuis 5 mois."

#### Optimisation fiscale inter-structures (nice to have)
- Suggestions d'optimisation entre SELARL, SCM, SCI, perso
- Doit être fiable et sourcé (Legifrance)
- Ne remplace pas le comptable

#### Aide à l'investissement (3/5)
- Décision d'achat complexe basée sur la situation financière réelle
- Comparatif technique
- Gestion de projets ponctuels (changement de voiture, travaux, etc.)

### 4.5 Personnel

#### Menus & Courses
- Planification de menus hebdomadaires
- Prise en compte : préférences famille (3 personnes), saison, agenda (jour chargé = plat rapide), objectifs sportifs
- Génération automatique de la liste de courses
- **Commande automatique sur Carrefour Drive**
- Recettes du jour envoyées chaque matin
- Validation par Antonio (vocale possible)

#### Coach remise en forme
- Programme sportif adapté au niveau, progressif
- Intégré à l'agenda (créneaux possibles selon la semaine)
- Lié aux menus (nutrition adaptée aux objectifs)
- **Apple Watch Ultra** : suivi sommeil, FC, activité
- Ajustement intelligent : mauvaise nuit → séance allégée, semaine chargée → menus simples
- Coaching intelligent, pas condescendant (Antonio est médecin)

#### Entretien cyclique
- Vidange voiture, contrôle technique, révision chaudière, détartrage, etc.
- Suivi automatique des cycles
- Rappels proactifs avec possibilité de prise de RDV

#### Gestionnaire de collection jeux vidéo
- Inventaire complet avec photos, état, édition, plateforme
- Valeur : prix d'achat + valeur actuelle (cote marché)
- Veille prix (eBay, PriceCharting, etc.)
- Alertes sur les variations de cote
- Preuve pour assurance

#### CV académique (nice to have)
- Auto-maintenu : publications, thèses dirigées, enseignement, responsabilités
- Éditable par Antonio
- Prêt pour candidatures, évaluations, dossiers de promotion
- Un autre projet pourrait s'en occuper à terme

#### Mode HS / Vacances (paramétrable)
- Réponses automatiques aux mails non urgents
- Alerte aux thésards : "Antonio est indisponible jusqu'au X"
- Tâches critiques flaggées pour le retour
- Briefing de reprise prêt au retour

---

## 5. Canaux de communication

> **📝 Décision architecturale** : Telegram remplace Discord comme canal principal (mobile-first, vocal natif bidirectionnel, meilleure confidentialité, API bot supérieure, notifications push natives)

| Canal | Usage | Priorité |
|-------|-------|----------|
| **Telegram** | Interface principale : texte, vocal (STT/TTS), envoi/réception fichiers, boutons inline, notifications push | Principal (100% Day 1) |
| **Vocal entrant (téléphone/PC)** | Commander Friday par la voix (voiture, entre patients) via Telegram ou interface dédiée | Élevée |
| **Vocal sortant (TTS)** | Briefing lu, réponses parlées (Kokoro TTS sur VPS + Piper fallback) | Élevée |
| **Enceinte connectée maison** | Wake word, interaction ambiante type Alexa | Nice to have (non prioritaire) |
| **Notifications proactives** | Alertes intelligentes poussées au bon moment via Telegram + ntfy | Élevée |
| **Mode consultation express** | Photo/question rapide → réponse en 30 secondes via Telegram | Élevée |

---

## 6. Services transversaux

#### Anonymisation réversible
- Pseudonymisation avant tout traitement LLM
- Mapping chiffré local pour pouvoir requêter après
- Solutions envisagées : Microsoft Presidio ou équivalent open source
- Attention : à trop anonymiser, on perd la capacité de recherche

#### Mémoire éternelle / Graphe de connaissances
- Indexation sémantique de toutes les données
- Relations entre entités (personnes, documents, événements, lieux)
- Jamais de purge, jamais d'oubli

#### Apprentissage continu
- Le système note les corrections de l'utilisateur et s'améliore
- Préférences de classification, style de rédaction, seuils d'urgence

---

## 7. Interconnexions entre modules

```
Moteur Vie (PJ extraites) ────────→ Archiviste
Archiviste (comptes/tréso) ────────→ Suivi financier
Archiviste (factures) ─────────────→ Garanties
Suivi financier ───────────────────→ Aide investissement
Tuteur Thèse ←──(même doc)──────→ Check Thèse
TCS ←──(même base programme)────→ ECOS
Agenda ←───────────────────────→ Coach sportif
Coach sportif ←────────────────→ Menus & Courses
Plaud Note (transcription) ────────→ Tâches + Agenda + Thèses + Biblio
Apple Watch (santé) ───────────────→ Coach sportif + Menus
CSV bancaires ─────────────────────→ Suivi financier → Abonnements
Mails (événements) ────────────────→ Agenda
Briefing ←─────(agrège tout)────→ Tous les modules
```

---

## 8. Contraintes techniques

| Contrainte | Valeur |
|------------|--------|
| **Budget** | 50€/mois maximum (VPS + APIs cloud). Estimation réelle : ~36-42€/mois (VPS-4 25€ + Mistral 6-9€ + Deepgram 3-5€ + divers 2-3€) |
| **Serveur** | OVH VPS-4 : 48 Go RAM / 12 vCores / 300 Go NVMe (~25€ TTC/mois) - Tous services lourds résidents simultanément |
| **Laptop utilisateur** | Dell Pro Max 16 (Core Ultra 7 255H, 32 Go RAM, pas de GPU). **AUCUN modèle IA ne tourne sur le laptop** - rôle = stockage documents uniquement |
| **Stockage** | Synology BeeStation (photos) + PC (documents locaux) + VPS (index + métadonnées uniquement) |
| **Confidentialité** | Anonymisation réversible via Presidio + spaCy-fr AVANT tout traitement LLM cloud (obligatoire RGPD) |
| **Architecture IA** | Hybride VPS/cloud : Ollama VPS (données sensibles) + Mistral cloud (raisonnement complexe) |
| **LLM local VPS** | Mistral Nemo 12B + Ministral 3B via Ollama sur VPS (CPU suffisant, données ne sortent pas) |
| **Interface principale** | Telegram bot (mobile-first, vocal natif bidirectionnel, meilleure confidentialité que Discord) - 100% Day 1 |
| **Mails** | 4 comptes via EmailEngine (auto-hébergé Docker). Thunderbird reste interface utilisateur optionnelle |
| **Thèses** | Google Docs partagés avec étudiants (API v1 - limitation : Suggestions au lieu de commentaires ancrés) |
| **Données santé** | Apple Watch Ultra (sommeil, FC, activité) - **Intégration à définir** (export manuel CSV ou app tierce) |
| **Usage** | Strictement individuel, jamais commercialisé |
| **Extension** | Foyer de 3 (épouse + fille 10 ans), extension famille envisageable plus tard |

---

## 9. Ce qui reste dans Jarvis / MiraIdesk

Les éléments suivants ne font **pas** partie de Friday 2.0 :

- Méta-Analyste PRISMA (reste dans Jarvis)
- Contrôle pré-soumission de publications (Jarvis)
- Veille scientifique PubMed/Cochrane/HAS (Jarvis)
- Gestion bibliographique Zotero (Jarvis)
- Rédaction académique (Jarvis)
- Gestion CARMF/URSSAF/DPC (comptable)
- Gestion des SCI (déjà gérée)

---

## 10. Prochaine étape

Ce document d'analyse des besoins est prêt à être transmis à l'**Architect** pour :
1. Définir l'architecture technique (quels outils, où ils tournent, comment ils communiquent)
2. Choisir le stack technologique
3. Concevoir le graphe de connaissances / mémoire éternelle
4. Définir l'architecture hybride locale/cloud
5. Planifier les phases d'implémentation
