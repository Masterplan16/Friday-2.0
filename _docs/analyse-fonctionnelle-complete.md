# Analyse Fonctionnelle Complète - Friday 2.0

**Date** : 5 février 2026
**Objectif** : Vérifier la cohérence de l'architecture avant implémentation
**Status** : En cours de validation avec Antonio

---

## TABLE DES MATIÈRES

1. [Architecture Globale](#1-architecture-globale)
2. [Répartition Stockage PC / VPS / BeeStation](#2-répartition-stockage)
3. [Mesures de Sécurité Transversales](#3-mesures-de-sécurité-transversales)
   - 3.1 [Contrôle de la "salle des machines"](#31-contrôle-de-la-salle-des-machines)
   - 3.2 [Précautions vis-à-vis des erreurs et hallucinations (Trust Layer)](#32-précautions-vis-à-vis-des-erreurs-et-hallucinations-trust-layer)
   - 3.3 [Heartbeat Engine (Proactivité Native)](#33-heartbeat-engine-proactivité-native)
4. [Modules Fonctionnels (1-23)](#4-modules-fonctionnels)
5. [Synthèse des Incohérences Détectées](#5-synthèse-des-incohérences)

---

## 1. ARCHITECTURE GLOBALE

### 1.1 Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                         ANTONIO (Utilisateur)                    │
│  - Dell Pro Max 16 (32 Go RAM, Core Ultra 7, PAS de GPU)       │
│  - Telegram (interface principale)                              │
│  - Thunderbird (lecture emails optionnelle)                     │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   │ Tailscale VPN (TOUT passe par là)
                   │
        ┌──────────┴────────────┬────────────────┐
        │                       │                 │
┌───────▼──────────┐   ┌───────▼──────────┐   ┌─▼──────────────┐
│   PC ANTONIO     │   │   VPS OVH        │   │  BEESTATION    │
│  (Stockage)      │   │  (Cerveau)       │   │  (Photos)      │
│                  │   │                  │   │                │
│ • Documents      │   │ • PostgreSQL     │   │ • Photos       │
│ • Archives       │   │ • Redis          │   │ • Synology     │
│ • Photos synchro │   │ • pgvector (D19) │   │   Drive        │
│ • Téléchargements│   │ • n8n            │   │ • PAS de       │
│ • CSV bancaires  │   │ • Claude API     │   │   Tailscale    │
│ • Scans          │   │ • FastAPI        │   │ • PAS de       │
│                  │   │ • Telegram Bot   │   │   packages     │
│ Syncthing client │   │ • Presidio       │   │   tiers        │
│ Zone transit     │   │ • EmailEngine    │   │                │
│ /uploads/        │   │ • Faster-Whisper │   └────────────────┘
│ /downloads/      │   │ • Kokoro TTS     │          │
│                  │   │ • Surya OCR      │          │
└──────────────────┘   │                  │          │
         ▲             │ VPS-4 48 Go RAM  │          │
         │             │ 12 vCores        │          │
         │             │ 300 Go SSD       │          │
         │             │ ~25 € TTC/mois   │          │
         │             └──────────────────┘          │
         │                                            │
         └────────────────────────────────────────────┘
                    Synology Drive Client
```

### 1.2 Principe architectural fondamental

**PC = STOCKAGE PRIMAIRE** (la source de vérité pour les fichiers)
**VPS = CERVEAU** (traitement IA, index, métadonnées)
**BeeStation = STOCKAGE PHOTOS** (via PC comme pont)

---

## 2. RÉPARTITION STOCKAGE

### 2.1 Principe général

| Type de données | Stocké sur PC | Stocké sur VPS | Stocké sur BeeStation |
|-----------------|---------------|----------------|------------------------|
| **Fichiers originaux** | ✅ OUI (source de vérité) | ❌ NON (zone transit éphémère) | Photos uniquement |
| **Index / métadonnées** | ❌ NON | ✅ OUI (PostgreSQL) | ❌ NON |
| **Embeddings vectoriels** | ❌ NON | ✅ OUI (pgvector dans PostgreSQL) (D19) | ❌ NON |
| **Graphe de connaissances** | ❌ NON | ✅ OUI (PostgreSQL knowledge.*) | ❌ NON |
| **Emails bruts** | ❌ NON (dans EmailEngine) | ✅ OUI (PostgreSQL ingestion.emails) | ❌ NON |
| **Photos** | ✅ OUI (copie via Synology Drive) | ❌ NON (transit éphémère) | ✅ OUI (stockage principal) |

### 2.2 Flux détaillés par source

#### 2.2.1 Emails (EmailEngine)

```
Mail arrive (IMAP) → EmailEngine (VPS)
                         ↓
            n8n webhook détecte nouveau mail
                         ↓
            Insert PostgreSQL (ingestion.emails_raw)
                         ↓
            Publish Redis Stream event (email.received)
                         ↓
            Agent Email (LangGraph) traite :
              - Classification
              - Extraction tâches
              - Extraction PJ → Transit VPS
                         ↓
            PJ traitée (OCR, renommage)
                         ↓
            Syncthing sync → PC (~/Documents/Archives/...)
                         ↓
            Suppression PJ du transit VPS
```

**Stockage final** :
- Email brut : PostgreSQL VPS (ingestion.emails_raw)
- Métadonnées : PostgreSQL VPS (ingestion.emails + knowledge.*)
- PJ traitée : PC (~/Documents/Archives/...)
- Index PJ : pgvector VPS (D19)

#### 2.2.2 Scanner physique

```
Scan → PC (~/Documents/Uploads/)
         ↓
   Watchdog détecte nouveau fichier
         ↓
   Syncthing sync → VPS (/data/transit/uploads/)
         ↓
   n8n détecte → Déclenche OCR
         ↓
   Surya OCR + Marker
         ↓
   Agent Archiviste traite :
     - Renommage intelligent
     - Classification
     - Extraction métadonnées
         ↓
   Fichier renommé/classé
         ↓
   Syncthing sync → PC (~/Documents/Archives/[catégorie]/[nom_intelligent].pdf)
         ↓
   Suppression du transit VPS
```

**Stockage final** :
- Fichier original : PC (~/Documents/Archives/...)
- Métadonnées : PostgreSQL VPS (ingestion.documents)
- Contenu OCR : PostgreSQL VPS (knowledge.documents_content)
- Index vectoriel : pgvector VPS (D19)

#### 2.2.3 Photos BeeStation

```
Téléphone → BeeStation (stockage Synology)
                ↓
    Synology Drive Client (PC)
                ↓
    ~/Photos/BeeStation/ (copie locale PC)
                ↓
    Syncthing sync → VPS (/data/transit/photos/)
                ↓
    Agent Photos traite :
      - Extraction métadonnées EXIF
      - Génération embeddings visuels (via LLM vision)
      - Classification (événement, lieu, personnes)
                ↓
    Indexation PostgreSQL + pgvector (D19)
                ↓
    Suppression du transit VPS
```

**Stockage final** :
- Photos originales : BeeStation (source de vérité)
- Copie locale : PC (~/Photos/BeeStation/)
- Métadonnées : PostgreSQL VPS (ingestion.photos)
- Embeddings visuels : pgvector VPS (D19)

**IMPORTANT** : Le VPS ne garde JAMAIS les photos en permanence (transit éphémère uniquement).

#### 2.2.4 Plaud Note (transcriptions audio)

```
Enregistrement Plaud Note → Google Drive (upload auto Plaud)
                               ↓
              n8n watch Google Drive (API polling)
                               ↓
              Nouveau fichier détecté
                               ↓
              Téléchargement sur VPS (/data/transit/plaud/)
                               ↓
              Faster-Whisper (transcription)
                               ↓
              Agent Plaud traite :
                - Résumé
                - Extraction tâches
                - Extraction dates/événements
                - Extraction mentions thèses
                               ↓
              Transcription brute + enrichie
                               ↓
              Syncthing sync → PC (~/Documents/Plaud/[date]_[sujet].txt)
                               ↓
              Suppression du transit VPS
```

**Stockage final** :
- Audio original : Google Drive (Plaud Note)
- Transcription : PC (~/Documents/Plaud/)
- Métadonnées : PostgreSQL VPS (ingestion.transcriptions)
- Tâches extraites : PostgreSQL VPS (core.tasks)

#### 2.2.5 CSV bancaires

```
Téléchargement CSV banque → PC (~/Documents/Finance/Import/)
                                ↓
                   Watchdog détecte
                                ↓
                   Syncthing sync → VPS (/data/transit/finance/)
                                ↓
                   n8n parse CSV (Papa Parse)
                                ↓
                   Insert PostgreSQL brut (ingestion.transactions_raw)
                                ↓
                   Agent Finance classifie (LLM)
                                ↓
                   Insert PostgreSQL enrichi (knowledge.transactions)
                                ↓
                   Export CSV classifié
                                ↓
                   Syncthing sync → PC (~/Documents/Finance/[SELARL|SCM|SCI1|SCI2|Perso]/[année]/[mois]/)
                                ↓
                   Suppression du transit VPS
```

**Stockage final** :
- CSV brut : PC (~/Documents/Finance/Import/)
- CSV classifié : PC (~/Documents/Finance/[structure]/...)
- Transactions : PostgreSQL VPS (knowledge.transactions)

#### 2.2.6 Google Docs (thèses étudiants)

```
Étudiant modifie Google Doc
         ↓
   n8n watch Google Drive (API polling)
         ↓
   Nouveau changement détecté
         ↓
   Export Docx sur VPS (/data/transit/theses/)
         ↓
   Agent Tuteur Thèse analyse :
     - Structure IMRAD
     - Méthodologie
     - Statistiques
     - Rédaction
         ↓
   Génération commentaires
         ↓
   Google Docs API (insertion Suggestions)
         ↓
   Copie Docx analysé
         ↓
   Syncthing sync → PC (~/Documents/Theses/[nom_etudiant]/[date]_version.docx)
         ↓
   Suppression du transit VPS
```

**Stockage final** :
- Document source : Google Drive (partagé avec étudiant)
- Copie versionnée : PC (~/Documents/Theses/[nom_etudiant]/)
- Métadonnées analyse : PostgreSQL VPS (knowledge.thesis_reviews)

### 2.3 Zone de transit VPS

**Principe** : Le VPS utilise une zone de transit éphémère. Aucun fichier ne reste en permanence (sauf index/métadonnées).

```
/data/transit/
  ├── uploads/       # Scans, téléchargements
  ├── photos/        # Photos BeeStation
  ├── plaud/         # Transcriptions Plaud Note
  ├── finance/       # CSV bancaires
  ├── theses/        # Export Google Docs
  └── email_attachments/  # PJ emails
```

**Durée de vie** :
- Fichier arrive → Traitement (OCR, classification, renommage) → Sync vers PC → **Suppression immédiate**
- Durée maximale : 15 minutes (timeout)
- Nettoyage automatique : Cron quotidien (3h00) supprime tout fichier >1h dans /data/transit/

**Justification** :
- VPS = 300 Go SSD (limité)
- Éviter saturation disque
- Sécurité (données sensibles ne restent pas)

---

## 3. MESURES DE SÉCURITÉ TRANSVERSALES

### 3.1 Contrôle de la "salle des machines"

| Mesure | Implémentation | Objectif |
|--------|----------------|----------|
| **Tailscale VPN** | Tous les services internes uniquement accessibles via Tailscale. Aucun port exposé sur Internet public. | Isolation réseau complète |
| **Authentification 2FA Tailscale** | Obligatoire pour tous les appareils (PC, téléphone, VPS). Configuration manuelle dans dashboard Tailscale. | Prévention accès non autorisé |
| **SSH désactivé publiquement** | SSH uniquement via Tailscale (IP 100.x.x.x). Port 22 fermé sur Internet. | Prévention brute-force |
| **Secrets chiffrés (age/SOPS)** | Tous les secrets (API keys, passwords) chiffrés avec age. Déchiffrement au runtime uniquement. | Prévention fuite credentials dans git |
| **Redis ACL** | Moindre privilège par service (voir docs/redis-acl-setup.md). Service email ne peut pas écrire dans finance. | Isolation latérale |
| **PostgreSQL schemas** | 3 schemas séparés (core, ingestion, knowledge). JAMAIS de table dans public. | Isolation données |
| **Presidio anonymization** | OBLIGATOIRE avant tout appel LLM cloud. Mapping éphémère Redis (TTL court, JAMAIS PostgreSQL). | RGPD, prévention fuite PII |
| **pgcrypto** | Colonnes sensibles chiffrées (données médicales, financières). | Chiffrement at-rest |
| **Firewall VPS** | UFW configuré : DENY all, ALLOW 51820/udp (Tailscale), ALLOW 80/443 (Caddy interne). | Réduction surface d'attaque |
| **Backup chiffré** | pg_dump quotidien chiffré avec age avant sync Tailscale vers PC. | Protection backup vol PC |
| **EmailEngine isolation** | EmailEngine dans conteneur Docker séparé. Credentials IMAP chiffrés avec SOPS. | Isolation compte mails |

### 3.2 Précautions vis-à-vis des erreurs et hallucinations (Trust Layer)

**COMPOSANT CRITIQUE** : Le Trust Layer est le système de contrôle qui compense les erreurs/hallucinations des LLM.

#### 3.2.1 Trust Levels (3 niveaux)

| Niveau | Comportement | Exemples | Risque si erreur |
|--------|-------------|----------|------------------|
| 🟢 **AUTO** | Friday exécute, Mainteneur notifié après coup | OCR, renommage fichier, indexation, extraction PJ | Gênant (mauvais classement) |
| 🟡 **PROPOSE** | Friday prépare, Mainteneur valide avant (inline buttons Telegram) | Classification email, création tâche, ajout agenda, import finance | Perte de temps |
| 🔴 **BLOCKED** | Friday analyse, JAMAIS d'action autonome | Envoi mail, conseil médical, analyse juridique, communication thésards | Conséquence réelle (réputation, légal, santé) |

**Initialisation Day 1** :
- Tous les modules démarrent en mode **PROPOSE** (validation humaine obligatoire)
- Promotion vers AUTO : après 3 semaines + accuracy >95% + validation manuelle Antonio
- Blocage permanent : modules médicaux, juridiques, communication externe

#### 3.2.2 Middleware `@friday_action` (obligatoire)

**Principe** : Chaque action de chaque module DOIT passer par ce décorateur.

```python
@friday_action(module="email", action="classify", trust_default="propose")
async def classify_email(email: Email) -> ActionResult:
    # 1. Charge correction_rules du module
    rules = await db.fetch(
        "SELECT conditions, output FROM core.correction_rules "
        "WHERE module='email' AND active=true"
    )
    # 2. Injecte règles dans le prompt (hiérarchie: règle > LLM)
    prompt = f"Règles prioritaires: {format_rules(rules)}..."
    response = await llm_adapter.complete(prompt=prompt)
    # 3. Retourne ActionResult standardisé
    return ActionResult(
        input_summary=f"Email de {email.sender}: {email.subject}",
        output_summary=f"→ {response.category}",
        confidence=response.score,
        reasoning=f"Mots-clés: {response.keywords}..."
    )
```

**Le décorateur gère automatiquement** :
1. Création receipt dans `core.action_receipts` (traçabilité totale)
2. Vérification trust level actuel (SELECT PostgreSQL)
3. Si AUTO → exécute + log
4. Si PROPOSE → envoie validation Telegram (inline buttons Approve/Reject)
5. Si BLOCKED → présente analyse sans agir
6. Si erreur → alerte Telegram temps réel

#### 3.2.3 ActionResult (modèle obligatoire)

```python
class ActionResult(BaseModel):
    input_summary: str       # Ce qui est entré (visible Antonio)
    output_summary: str      # Ce qui a été fait (visible Antonio)
    confidence: float        # 0.0-1.0, confidence MIN de tous les steps
    reasoning: str           # Pourquoi cette décision (visible Antonio)
    payload: dict = {}       # Données techniques (optionnel)
    steps: list[StepDetail] = []  # Sous-étapes (détail technique)
```

**Principe** : Antonio voit TOUJOURS ce que Friday a fait, avec quel niveau de confiance, et pourquoi.

#### 3.2.4 Feedback Loop (correction → règle explicite)

**Cycle** :
1. Antonio corrige une action Friday (via Telegram)
2. Correction stockée dans `core.action_receipts.correction`
3. Friday détecte pattern récurrent (2+ corrections similaires)
4. Friday propose une règle explicite (via Telegram)
5. Antonio valide → règle active dans `core.correction_rules`
6. Règles injectées dans prompts LLM (hiérarchie : **règle > jugement LLM**)

**PAS de RAG pour corrections** : ~50 règles max → un SELECT suffit.

**Exemple** :
```json
// core.correction_rules
{
  "module": "email",
  "action": "classify",
  "conditions": {"keywords": ["URSSAF"], "confidence_lt": 0.8},
  "output": {"category": "finance", "priority": "high"}
}
```

#### 3.2.5 Rétrogradation automatique

**Formule** (voir addendum section 7) :
- Si `accuracy < 90%` sur 1 semaine ET échantillon ≥10 actions
- → Rétrogradation AUTO → PROPOSE (AUTOMATIQUE, pas besoin d'intervention Antonio)
- Anti-oscillation : 2 semaines minimum avant nouvelle promotion

**Justification** : Si Friday fait >10% d'erreurs, arrêt automatique du mode autonome.

#### 3.2.6 Metriques de confiance

**2 métriques distinctes** :
- `model_confidence` : ce que le LLM pense (technique, interne)
- `historical_accuracy` : taux de réussite réel basé sur corrections Mainteneur (métier, visible)

**C'est `historical_accuracy` qui détermine promotions/rétrogradations.**

```sql
CREATE TABLE core.trust_metrics (
    module TEXT NOT NULL,
    action_type TEXT NOT NULL,
    week_start DATE NOT NULL,
    total INT DEFAULT 0,
    correct INT DEFAULT 0,
    corrected INT DEFAULT 0,
    accuracy FLOAT GENERATED ALWAYS AS
        (correct::float / NULLIF(total, 0)) STORED,
    PRIMARY KEY (module, action_type, week_start)
);
```

Calcul quotidien (cron 18h00) :
- Agrégation journalière
- Détection rétrogradations
- Génération résumé soir Telegram

#### 3.2.7 Commandes Telegram (introspection)

| Commande | Usage | Exemple |
|----------|-------|---------|
| `/status` | État salle des machines (services, RAM, disque, dernières actions) | "PostgreSQL ✅, Redis ✅, Ollama ⚠️ (charge CPU élevée)" |
| `/journal` | 20 dernières actions avec timestamps | "14:32 Email classé → Cabinet (AUTO) ✅" |
| `/journal finance` | Filtre par module | Actions finance des 7 derniers jours |
| `/receipt <id>` | Détail complet d'une action | Input, output, confidence, reasoning |
| `/receipt <id> -v` | Détail technique (steps, durées, modèle) | Sous-actions, temps OCR, tokens LLM |
| `/confiance` | Tableau accuracy par module | "Email: 94.2%, Finance: 88.1% (⚠️ sous seuil)" |
| `/stats` | Volumes semaine | "47 actions, 2 validations, 1 correction" |

**Progressive disclosure** (UX) :
- Niveau 1 : Résumé soir automatique (Antonio voit sans rien faire)
- Niveau 2 : `/journal` si besoin de creuser
- Niveau 3 : `/receipt -v` si besoin du détail technique

**99% du temps, Mainteneur reste au niveau 1.** Le Trust Layer fonctionne quand Antonio n'a PAS besoin de l'utiliser.

#### 3.2.8 Alertes temps réel (erreurs critiques)

Via Redis Streams → Telegram (service alerting/listener.py) :

| Event | Déclencheur | Exemple Telegram |
|-------|-------------|------------------|
| `pipeline.error` | Exception non récupérable | "❌ Pipeline emails KO (ConnectionError)" |
| `service.down` | Service injoignable >5min | "🚨 Faster-Whisper down depuis 10min" |
| `trust.level.changed` | Rétrogradation automatique | "⚠️ Classification email → PROPOSE (accuracy 84%)" |
| `ram.threshold.exceeded` | RAM >85% pendant >5min | "🧠 RAM 87% - surveiller" |

---

## 3.3 Heartbeat Engine (Proactivité Native)

### 3.3.1 Décision architecturale (2026-02-05)

**Problématique** : Friday doit être **proactif**, pas seulement réactif. Antonio ne doit PAS avoir à demander "Y a-t-il des emails urgents ?". Friday doit surveiller automatiquement et notifier UNIQUEMENT si important.

**Alternatives considérées** :

| Approche | Coût | Bénéfices | Décision |
|----------|------|-----------|----------|
| **Cron n8n manuel** | 0h (existant) | Simple, stable | ❌ Configuration fixe, pas d'intelligence |
| **OpenClaw complet** | 70h | Heartbeat + 50+ intégrations + 1715 skills | ❌ ROI -86%, risque supply chain 12% |
| **Heartbeat natif Friday** | 10h | Intelligence décisionnelle, intégration Trust Layer | ✅ **Retenu** |

**Score décisionnel Antonio** : 20/100 points
- Multi-chat (WhatsApp, Discord) : ❌ NON → +0
- Skills identifiées (≥10) : ❌ NON → +0
- Heartbeat critique Day 1 : ✅ OUI → +20
- Risque acceptable : ⚠️ INCERTAIN → +0

**Conclusion** : Antonio a besoin du heartbeat proactif (critique) MAIS pas de multi-chat ni skills OpenClaw → Heartbeat natif = 100% du bénéfice recherché pour 14% du coût OpenClaw.

### 3.3.2 Architecture Heartbeat Engine

```
┌────────────────────────────────────────────────────────────┐
│                   HEARTBEAT ENGINE                          │
└────────────────────────────────────────────────────────────┘

asyncio background task (non-bloquant)
            ↓
   Sleep interval (default 30min)
            ↓
   ┌──────────────────┐
   │ 1. Get Context   │ ← Heure, dernière activité, calendrier
   └────────┬─────────┘
            ↓
   ┌──────────────────┐
   │ 2. LLM Decision  │ ← "Quels checks exécuter maintenant ?"
   └────────┬─────────┘  (high: toujours, medium/low: si pertinent)
            ↓
   ┌──────────────────┐
   │ 3. Execute Checks│ ← Async parallèle (check_urgent_emails, etc.)
   └────────┬─────────┘
            ↓
   ┌──────────────────┐
   │ 4. Filter Results│ ← Garder SEULEMENT si notify=True
   └────────┬─────────┘
            ↓
   ┌──────────────────┐
   │ 5. Notify Telegram│ ← Batch notification (max 1 par tick)
   └──────────────────┘
```

**Composants** :
- `FridayHeartbeat` (`agents/src/core/heartbeat.py`) : Orchestrateur principal
- `ContextProvider` (`agents/src/core/context.py`) : Contexte actuel (heure, activité, calendrier)
- `CheckRegistry` : Enregistrement checks avec priorités (high/medium/low)
- `LLMDecider` : LLM décide dynamiquement quels checks exécuter
- Configuration : `config/heartbeat.yaml`

### 3.3.3 Checks Day 1

| Check | Priorité | Description | Module source |
|-------|----------|-------------|---------------|
| `check_urgent_emails` | **high** (toujours) | Emails urgents non lus | Module 1 (Email) |
| `check_financial_alerts` | **medium** (si pertinent) | Alertes financières, échéances cotisations | Module 14 (Finance) |
| `check_upcoming_deadlines` | **medium** (si pertinent) | Échéances contrats proches | Module 8 (Droit) |
| `check_thesis_reminders` | **low** (si temps) | Deadlines thèses étudiants | Module 9 (Thèse) |

**Quiet hours** : 22h00-08h00 (pas de notifications pendant sommeil Antonio)

### 3.3.4 Exemple d'usage concret

**Scénario : Mardi 14h30, Mainteneur entre deux consultations**

**En arrière-plan (invisible pour Antonio)** :
```
Heartbeat tick déclenché (interval 30min)
         ↓
Contexte récupéré :
  - Heure : 14h30 (mardi)
  - Dernière activité : 10h15 (consultation)
  - Prochain événement : 15h00 (patient suivant)
         ↓
LLM décide (Claude Sonnet 4.5) :
  - check_urgent_emails : HIGH → EXÉCUTER (toujours)
  - check_financial_alerts : MEDIUM → EXÉCUTER (échéance URSSAF 28/02 proche)
  - check_thesis_reminders : LOW → SKIP (pas prioritaire maintenant)
         ↓
Exécution parallèle :
  - check_urgent_emails → 2 emails urgents détectés
  - check_financial_alerts → Échéance URSSAF dans 13 jours
         ↓
Filtrage : 2 notifications à envoyer
         ↓
Notification Telegram batch
```

**Antonio reçoit (notification Telegram unique)** :
```
🔔 HEARTBEAT (14:30)

📧 2 emails urgents non lus
• Dr. Martin : Réunion cabinet urgent
• CPAM : Anomalie télétransmission
[Voir résumé]

💰 Alerte : Cotisations URSSAF échéance 28/02 (13j)
[Créer tâche]
```

Antonio clique [Créer tâche] → Action exécutée via Trust Layer (PROPOSE, validation inline buttons)

### 3.3.5 Intégration Trust Layer

**Principe** : Heartbeat notifie → Antonio clique inline button → Action exécutée via `@friday_action`

```python
@friday_action(module="finance", action="create_task_from_alert", trust_default="propose")
async def create_task_from_alert(alert: FinancialAlert) -> ActionResult:
    """Crée tâche depuis alerte heartbeat (après validation Antonio)"""
    task = await db.fetchrow(
        """INSERT INTO core.tasks (title, due_date, priority, module)
           VALUES ($1, $2, $3, $4) RETURNING id""",
        alert.description, alert.deadline, 'high', 'finance'
    )
    return ActionResult(
        input_summary=f"Alerte : {alert.description}",
        output_summary=f"Tâche créée : {alert.description}",
        confidence=1.0,
        reasoning="Création automatique depuis alerte heartbeat"
    )
```

**Avantages vs cron n8n manuel** :
- ✅ Intelligence décisionnelle (LLM choisit selon contexte)
- ✅ Priorités dynamiques (high: toujours, medium/low: si pertinent)
- ✅ Quiet hours (respecte sommeil Antonio)
- ✅ Intégration native Trust Layer
- ✅ Batch notifications (1 message groupé vs N messages séparés)

**Monitoring** : Endpoint FastAPI `/api/v1/heartbeat/status` (checks registered, last run, notifications)

**Documentation technique complète** : [agents/docs/heartbeat-engine-spec.md](../agents/docs/heartbeat-engine-spec.md)

---

## 4. MODULES FONCTIONNELS

**Note** : Cette section sera complétée module par module avec validation Antonio.

### ✅ MODULE 1 : Moteur Vie (Email + Desktop Search)

#### 4.1.1 Description

**Priorité** : 5/5 (critique)
**Couche technique** : Ingestion + Intelligence

**Composants** :
1. **Pipeline Email** : 4 comptes IMAP (via EmailEngine)
   - ~20 mails/jour minimum (estimation conservatrice, 110k mails dans Thunderbird donc ~600/mois en réel)
   - Classification automatique (Cabinet, Personnel, Thèses, Administratif, etc.)
   - Extraction tâches
   - Extraction PJ → Archiviste
   - Brouillons de réponse

2. **Desktop Search Sémantique** :
   - Recherche par sens dans tous fichiers locaux PC
   - PDF, Docx, articles, thèses, cours
   - Index vectoriel (pgvector dans PostgreSQL) (D19)

#### 4.1.2 Exemple d'usage concret avec Telegram

**SCÉNARIO RÉEL : Journée type d'Antonio**

**7h30 - Dans la voiture, trajet cabinet**

Antonio reçoit notification vocale Telegram (Kokoro TTS) :
```
🎤 Friday (vocal)
"Bonjour Antonio. 3 nouveaux mails cette nuit.

1. URSSAF - Échéance cotisations 28 février
   → J'ai classé en Finance, priorité haute
   → Je propose de créer une tâche ?

2. Julie (thèse) - Version chapitre méthodologie
   → PJ extraite : chapitre3_v2.docx
   → J'ai détecté 2 points à vérifier (stats)
   → Je lance l'analyse Tuteur Thèse ?

3. Dr. Martin - Planning réunion cabinet
   → PJ extraite : planning_Q1.pdf
   → Il propose 3 dates, je prépare une réponse ?"
```

Antonio répond (message vocal Telegram) :
```
🎤 Antonio
"OK pour l'URSSAF, crée la tâche.
Pour Julie, oui lance l'analyse.
Pour Dr. Martin, propose le mardi 12 à 14h."
```

Friday répond instantanément (Faster-Whisper transcrit + traite) :
```
✅ Fait :
- Tâche créée : "Payer cotisations URSSAF" (échéance 28/02)
- Analyse thèse Julie lancée (résultat dans ~10min)
- Brouillon mail Dr. Martin prêt

📧 Brouillon pour Dr. Martin :
"Bonjour Dr. Martin,
Merci pour le planning. Je te propose le mardi 12/02 à 14h pour cette réunion.
À bientôt,
Antonio"

[Envoyer maintenant] [Modifier] [Reporter]
```

Antonio clique [Envoyer maintenant] → Mail envoyé

---

**14h30 - Entre deux consultations**

Antonio a 5 minutes, il veut retrouver un article :
```
🎤 Mainteneur (message vocal Telegram)
"Friday, retrouve ce que j'avais lu sur les inhibiteurs SGLT2
pour l'insuffisance cardiaque, c'était il y a environ 6 mois"
```

```
Friday (texte Telegram, réponse immédiate)
🔍 J'ai trouvé 3 documents pertinents :

1. 📄 Article ESC Guidelines SGLT2 (août 2025)
   Chemin : ~/Documents/Veille/Cardio/esc_sglt2_ic_2025.pdf
   Extrait : "...recommandation classe I pour SGLT2i
   chez patients IC à FEVG réduite..."
   [Ouvrir] [Envoyer extrait]

2. 📄 Fiche patient Mme Dupont (sept 2025)
   Chemin : lien base patients (anonymisé)
   Extrait : "...initiation Jardiance 10mg..."
   [Ouvrir fiche]

3. 📄 Recommandations HAS (juillet 2025)
   URL : https://has-sante.fr/...
   [Ouvrir lien]

💡 Note : Tu as aussi consulté Antibioclic
    sur ce sujet le 15/09/2025
```

Antonio clique [Envoyer extrait] → Friday envoie le PDF complet par Telegram

---

**18h00 - Résumé de journée**

Friday envoie automatiquement :
```
📊 RÉSUMÉ 05/02

📧 Emails traités : 8
  ✅ 5 classés automatiquement (Cabinet, Finance, Thèses)
  🟡 2 validés par toi (brouillons envoyés)
  ⏸️ 1 en attente (contrat SCI, je propose Veilleur Droit ?)

📁 Documents archivés : 3
  - Planning_Q1.pdf → ~/Documents/Cabinet/Planning/
  - Facture_EDF_SELARL.pdf → ~/Documents/Finance/SELARL/2026/02/
  - Chapitre3_Julie_v2.docx → ~/Documents/Theses/Julie/

✅ Tâches créées : 2
  - URSSAF cotisations (échéance 28/02)
  - Relancer Julie (thèse inactive 18j)

🎓 Thèse Julie : Analyse chapitre 3 terminée
   → 2 suggestions méthodologiques ajoutées dans Google Doc
   [Voir détail]

📈 CONFIANCE JOUR : 96.2% (1 validation / 8 actions)

[Journal complet] [Stats semaine]
```

#### 4.1.3 Exemple d'usage concret sur PC

**SCÉNARIO RÉEL : Antonio au bureau**

**Matin - Lecture emails classique**

Antonio ouvre Thunderbird sur son PC :
- Il voit ses 4 comptes mails synchronisés normalement
- Rien ne change dans son workflow habituel
- Il lit, répond, classe manuellement s'il le souhaite

**En arrière-plan (invisible pour Antonio)** :
```
EmailEngine (VPS) synchronise IMAP en temps réel
         ↓
Friday détecte nouveaux mails
         ↓
Classification automatique
         ↓
Extraction PJ → Transit VPS → OCR Surya
         ↓
Syncthing sync vers PC
         ↓
~/Documents/Archives/[categorie]/[nom_intelligent].pdf
```

Antonio ne voit rien de tout ça. Il reçoit juste une notification Telegram si besoin de validation.

---

**Midi - Scan facture restaurant**

Antonio scanne une facture au cabinet :
```
Scanner physique → PC (~/Documents/Uploads/scan_001.pdf)
```

**En arrière-plan (invisible pour Antonio)** :
```
Watchdog détecte nouveau fichier ~/Documents/Uploads/
         ↓
Syncthing sync → VPS (/data/transit/uploads/)
         ↓
n8n détecte → Déclenche pipeline Archiviste
         ↓
OCR Surya (extraction texte)
         ↓
Agent Archiviste analyse :
  - Type : Facture restaurant
  - Date : 05/02/2026
  - Montant : 87,50 €
  - Structure : SELARL (détection auto via mots-clés)
         ↓
Renommage intelligent :
  scan_001.pdf → 2026-02-05_Facture_Restaurant_LeBistrot_87-50.pdf
         ↓
Syncthing sync → PC
  ~/Documents/Finance/SELARL/2026/02/2026-02-05_Facture_Restaurant_LeBistrot_87-50.pdf
         ↓
Suppression ~/Documents/Uploads/scan_001.pdf
```

**15 secondes après le scan**, Mainteneur reçoit notification Telegram :
```
📄 Document archivé
2026-02-05_Facture_Restaurant_LeBistrot_87-50.pdf
→ Finance/SELARL/2026/02/

✅ Classement validé automatiquement (confiance 94%)
💰 Montant détecté : 87,50 € (repas déductible)

[Voir fichier] [Corriger classement]
```

Antonio clique [Voir fichier] si besoin, sinon il continue sa journée.

---

**Soir - Recherche document local**

Antonio cherche un ancien article sur son PC. Au lieu de fouiller les dossiers, il envoie message Telegram :
```
🎤 Mainteneur (vocal)
"Friday, retrouve l'article sur la fibrillation auriculaire
que j'avais téléchargé pour le cours de cardiologie"
```

```
Friday (réponse Telegram)
🔍 J'ai trouvé 2 documents :

1. 📄 ESC_Guidelines_FA_2024.pdf (94% pertinence)
   Emplacement : ~/Documents/Enseignement/Cardio/Cours/
   Date : Téléchargé le 12/11/2025
   [📂 Ouvrir dossier PC] [📧 Envoyer fichier]

2. 📄 Algorithme_Anticoag_FA.pdf (78% pertinence)
   Emplacement : ~/Documents/Veille/Cardio/
   Date : Téléchargé le 03/09/2025
   [📂 Ouvrir dossier PC] [📧 Envoyer fichier]
```

Antonio clique [📂 Ouvrir dossier PC] → Explorateur Windows s'ouvre directement sur le bon dossier, fichier sélectionné.

**OU**

Antonio clique [📧 Envoyer fichier] → Friday envoie le PDF complet par Telegram (pratique si Antonio n'est pas devant son PC à ce moment-là).

---

**Architecture invisible pour Antonio** :

```
PC (~/Documents/)
  ↓ Watchdog surveille changements
  ↓
VPS - Module Desktop Search
  ↓ Extraction contenu (OCR si nécessaire)
  ↓ Génération embeddings (via adaptateur)
  ↓ Insert pgvector + PostgreSQL metadata (D19)
  ↓
Index à jour en permanence

Requête Mainteneur (Telegram) → Embedding query
                                   ↓
                         pgvector similarity search (D19)
                                   ↓
                         Résultats → Telegram
```

**Clé** : Antonio ne touche JAMAIS au VPS. Il travaille normalement sur son PC, Friday indexe en arrière-plan.

#### 4.1.4 Architecture technique

```
┌─────────────────────────────────────────────────────────┐
│                    EMAIL PIPELINE                        │
└─────────────────────────────────────────────────────────┘

4 comptes IMAP → EmailEngine (VPS, conteneur Docker)
                      ↓
         n8n webhook (email-ingestion.json)
                      ↓
         Insert PostgreSQL (ingestion.emails_raw)
                      ↓
         Publish Redis Stream (email.received)
                      ↓
         Agent Email (agents/src/agents/email/agent.py)
                      ↓
         ┌─────────────┴─────────────┐
         │                           │
    Classification              Extraction PJ
    (Claude Sonnet 4.5)         (save transit VPS)
         │                           │
         │                           ↓
         │                     Archiviste traite PJ
         │                           │
         ↓                           ↓
    Insert metadata           Fichier classé
    PostgreSQL                      │
         │                           ↓
         │                     Sync PC (Syncthing)
         │                           │
         ↓                           ↓
    Telegram notification      Suppression transit VPS

┌─────────────────────────────────────────────────────────┐
│                  DESKTOP SEARCH                          │
└─────────────────────────────────────────────────────────┘

Fichiers PC (~/Documents/) → Watchdog détecte changements
                                  ↓
                   Module Desktop Search index fichiers
                   (agents/src/agents/desktop_search/)
                                  ↓
                   Extraction contenu (OCR si PDF image)
                                  ↓
                   Génération embeddings (via adaptateur)
                                  ↓
                   Insert pgvector (table: knowledge.embeddings) (D19)
                                  ↓
                   Insert PostgreSQL metadata

Requête Mainteneur (Telegram vocal) → Embedding query
                                         ↓
                               pgvector similarity search (D19)
                                         ↓
                               Top 5 résultats → Telegram
```

#### 4.1.5 Stockage

| Donnée | PC | VPS | Justification |
|--------|----|-----|---------------|
| Email brut | ❌ | ✅ PostgreSQL (ingestion.emails_raw) | Source de vérité emails = VPS |
| Metadata email | ❌ | ✅ PostgreSQL (ingestion.emails) | Index et classification |
| PJ email | ✅ ~/Documents/Archives/ | ❌ Transit éphémère | Stockage permanent = PC |
| Embeddings PJ | ❌ | ✅ pgvector (knowledge.embeddings) (D19) | Recherche sémantique VPS |
| Documents desktop | ✅ ~/Documents/ | ❌ PAS de copie | Source de vérité = PC |
| Index desktop | ❌ | ✅ pgvector + PostgreSQL metadata (D19) | Recherche sémantique VPS |

#### 4.1.6 Mesures de sécurité spécifiques

| Risque | Mesure | Implémentation |
|--------|--------|----------------|
| **Fuite credentials IMAP** | Chiffrement SOPS | `config/secrets/emailengine.enc.yaml` |
| **PII dans emails** | Presidio AVANT LLM cloud | `agents/src/tools/anonymize.py` |
| **Classification erronée** | Trust Level PROPOSE Day 1 | Validation humaine systématique |
| **Brouillon inapproprié** | Trust Level BLOCKED permanent | JAMAIS d'envoi auto sans validation |
| **PJ sensible exposée** | Transit VPS éphémère (<15min) | Cron nettoyage + Syncthing immediate |

#### 4.1.7 Trust Level initial

| Action | Trust Level Day 1 | Justification |
|--------|-------------------|---------------|
| Classification email | **PROPOSE** | Erreur = email perdu/mal classé (perte temps) |
| Extraction PJ | **AUTO** | Erreur = PJ mal nommée (gênant, pas critique) |
| Extraction tâches | **PROPOSE** | Erreur = tâche oubliée/mal priorisée (perte temps) |
| Brouillon réponse | **BLOCKED** | Erreur = réputation (conséquence réelle) |
| Desktop search | **AUTO** | Recherche = pas d'action, juste résultats |

---

### ✅ MODULE 2 : Archiviste

#### 4.2.1 Description

**Priorité** : 5/5 (critique)
**Couche technique** : Ingestion + Intelligence

**Composants** :
1. **Ingestion multi-source** :
   - Scans (scanner physique)
   - PJ emails (via Module 1)
   - Photos téléphone (via BeeStation)
   - Téléchargements PC (dossier vrac)

2. **OCR automatique** :
   - Surya (précision, multilingue)
   - Marker (fallback, rapidité)
   - Extraction texte intégral

3. **Renommage intelligent** :
   - Analyse contenu document
   - Génération nom descriptif (pas "scan_001.pdf")
   - Format : `YYYY-MM-DD_Type_Emetteur_Montant.ext`

4. **Classement automatique** :
   - Catégories prédéfinies (Finance, Cabinet, Personnel, Administratif, Contrats, Garanties, etc.)
   - Détection automatique structure (SELARL, SCM, SCI1, SCI2, Perso)
   - Sous-dossiers intelligents (année/mois)

5. **Suivi des garanties** :
   - Détection achats avec garantie
   - Extraction date d'achat + durée garantie
   - Alerte avant expiration (60j, 30j, 7j)

6. **Recherche sémantique** :
   - Index vectoriel (pgvector dans PostgreSQL) (D19)
   - Recherche par sens (via Module 1 Desktop Search)

#### 4.2.2 Exemple d'usage concret avec Telegram

**SCÉNARIO RÉEL : Antonio gère ses documents**

**Lundi 9h00 - Cabinet, entre deux patients**

Antonio scanne une facture d'électricité au cabinet :
```
Scanner physique → PC (~/Documents/Uploads/scan_001.pdf)
```

**15 secondes plus tard**, notification Telegram :
```
📄 Friday (notification)
Document scanné analysé

Type : Facture électricité EDF
Émetteur : EDF Entreprises
Montant : 342,18 €
Date : Janvier 2026
Structure détectée : SELARL

✅ Renommé :
2026-01-15_Facture_EDF_SELARL_342-18.pdf

✅ Classé :
~/Documents/Finance/SELARL/2026/01/

🤖 Trust : PROPOSE (validation nécessaire)
[✅ Valider] [✏️ Corriger] [📂 Voir]
```

Antonio clique [✅ Valider] → Archivage confirmé

---

**Mardi 14h30 - Antonio reçoit un colis Amazon**

Antonio prend en photo la facture avec son téléphone :
```
Téléphone → BeeStation (auto-sync)
          ↓
BeeStation → PC (Synology Drive Client)
          ↓
PC → VPS (Syncthing détecte image facture)
```

**1 minute plus tard**, notification Telegram :
```
📸 Friday (notification)
Photo facture détectée

Type : Facture Amazon
Article : Imprimante HP DeskJet
Montant : 149,99 €
Date achat : 04/02/2026

✅ Renommé et classé :
2026-02-04_Facture_Amazon_Imprimante_HP_149-99.pdf
→ ~/Documents/Achats/2026/02/

⚠️ Garantie détectée : 2 ans
📅 Expiration : 04/02/2028
J'ai créé une alerte 60j avant l'expiration.

[✅ OK] [Modifier]
```

Antonio clique [✅ OK]

---

**Mercredi 18h00 - Antonio cherche un ancien contrat**

Antonio envoie message vocal Telegram :
```
🎤 Antonio
"Friday, retrouve le contrat de bail du cabinet,
je crois qu'il arrive à échéance bientôt"
```

```
Friday (réponse Telegram)
🔍 Contrat trouvé

📄 2021-03-01_Bail_Commercial_Cabinet_RueVoltaire.pdf
Emplacement : ~/Documents/Contrats/Cabinet/
Date signature : 01/03/2021
Durée : 3+3+3 ans

⚠️ ALERTE : Échéance renouvellement dans 47 jours
Date limite décision : 15/03/2026

📋 Extrait clé :
"...clause résiliation article 5 : préavis 6 mois..."

[📂 Ouvrir fichier] [📧 Envoyer PDF] [📊 Résumé complet]
```

Antonio clique [📊 Résumé complet] → Friday génère analyse complète (via Module 8 Veilleur Droit)

---

**Jeudi matin - Dossier téléchargements en vrac**

Antonio a téléchargé 15 PDF médicaux hier soir dans ~/Downloads/. Il envoie :
```
🎤 Mainteneur (vocal Telegram)
"Friday, peux-tu ranger mon dossier Downloads ?"
```

```
Friday (réponse Telegram)
🧹 Nettoyage ~/Downloads/ en cours...

Détecté : 15 fichiers
  - 8 articles médicaux
  - 4 factures diverses
  - 2 brochures formations
  - 1 contrat assurance

⏳ Analyse et classement : ~2 minutes

[OK, préviens-moi quand c'est fait]
```

Antonio clique [OK, préviens-moi quand c'est fait]

**2 minutes plus tard** :
```
✅ Friday
Rangement ~/Downloads/ terminé

📚 8 articles médicaux → ~/Documents/Veille/[spécialité]/
  - Cardio (3), Diabéto (2), Néphrologie (3)

💰 4 factures → ~/Documents/Finance/[structure]/2026/02/
  - SELARL (2), Perso (2)

🎓 2 brochures → ~/Documents/Formations/2026/

📋 1 contrat → ~/Documents/Contrats/Assurance/

Tous renommés intelligemment.

[📊 Voir détail] [↩️ Annuler classement]
```

#### 4.2.3 Exemple d'usage concret sur PC

**SCÉNARIO RÉEL : Antonio au bureau**

**Matin - Scan rapide factures**

Antonio scanne 5 factures d'affilée :
```
Scanner → PC (~/Documents/Uploads/)
  - scan_001.pdf (facture téléphone)
  - scan_002.pdf (facture internet)
  - scan_003.pdf (facture comptable)
  - scan_004.pdf (facture fournitures bureau)
  - scan_005.pdf (contrat assurance cabinet)
```

**En arrière-plan (invisible pour Antonio)** :
```
Watchdog détecte 5 nouveaux fichiers
         ↓
Syncthing sync → VPS (/data/transit/uploads/)
         ↓
n8n déclenche pipeline Archiviste (batch 5 fichiers)
         ↓
OCR parallèle Surya (5 threads)
         ↓
Agent Archiviste analyse chaque fichier :
  - Extraction métadonnées (émetteur, date, montant, type)
  - Classification (Finance, Contrats, etc.)
  - Détection structure (SELARL/SCM/SCI/Perso)
  - Génération nom intelligent
         ↓
Renommage et classement :
  1. 2026-02-05_Facture_Orange_SELARL_89-90.pdf
     → ~/Documents/Finance/SELARL/2026/02/

  2. 2026-02-05_Facture_SFR_Fibre_Cabinet_39-99.pdf
     → ~/Documents/Finance/SELARL/2026/02/

  3. 2026-01-31_Facture_Comptable_Janvier_450-00.pdf
     → ~/Documents/Finance/SELARL/2026/01/

  4. 2026-02-03_Facture_OfficeDepot_Fournitures_127-54.pdf
     → ~/Documents/Finance/SELARL/2026/02/

  5. 2026-02-01_Contrat_Assurance_Cabinet_MMA.pdf
     → ~/Documents/Contrats/Assurance/
         ↓
Syncthing sync → PC (classement automatique)
         ↓
Suppression ~/Documents/Uploads/ (dossier vide)
```

**30 secondes après le dernier scan**, Mainteneur reçoit notification Telegram :
```
✅ 5 documents archivés

💰 4 factures → Finance/SELARL/
📋 1 contrat → Contrats/Assurance/

Trust : 4 AUTO (confiance 92-96%)
        1 PROPOSE (contrat assurance - validation nécessaire)

[Valider contrat] [Voir tous]
```

Antonio clique [Valider contrat]

---

**Midi - Téléchargement article médical**

Antonio télécharge un PDF depuis PubMed :
```
Chrome → ~/Downloads/pubmed_article_123456.pdf
```

**En arrière-plan** :
```
Watchdog détecte nouveau fichier ~/Downloads/
         ↓
Syncthing sync → VPS
         ↓
Agent Archiviste détecte : article scientifique
         ↓
Extraction métadonnées :
  - Titre : "SGLT2 inhibitors in heart failure"
  - Auteurs : Smith et al.
  - Journal : NEJM
  - Date : 2025
  - Domaine : Cardiologie
         ↓
Renommage :
  pubmed_article_123456.pdf → 2025_Smith_SGLT2_inhibitors_HF_NEJM.pdf
         ↓
Classement :
  ~/Documents/Veille/Cardio/2025/2025_Smith_SGLT2_inhibitors_HF_NEJM.pdf
         ↓
Indexation vectorielle (pgvector) (D19)
         ↓
Syncthing sync → PC
```

**Antonio ne voit rien**. L'article est classé automatiquement. Il le retrouvera via Desktop Search (Module 1) quand il en aura besoin.

---

**Soir - Vérification garanties avant expiration**

Antonio consulte son PC, ouvre Explorateur Windows :
```
~/Documents/Achats/Garanties_Actives/
```

**Ce dossier est généré automatiquement par Friday** :
```
Garanties_Actives/ (vue synthétique)
  ├── En_cours/ (toutes les garanties actives)
  │   ├── 2024-03-15_Garantie_MacBook_Pro_Expire_2027-03-15.lnk → lien vers facture originale
  │   ├── 2025-11-20_Garantie_iPhone_Expire_2027-11-20.lnk
  │   └── ...
  │
  ├── Expire_sous_60j/ (alertes proches)
  │   └── 2024-03-01_Garantie_Imprimante_Canon_Expire_2026-03-01.lnk
  │
  └── Expirées/ (archives)
      └── 2022-01-10_Garantie_Disque_Dur_Expiree_2024-01-10.lnk
```

Antonio voit immédiatement qu'une garantie expire bientôt (imprimante Canon).

**En parallèle, Friday envoie rappel Telegram** :
```
⚠️ Garantie bientôt expirée

📄 Imprimante Canon G3020
Date achat : 01/03/2024
Garantie : 2 ans
Expiration : 01/03/2026 (24 jours)

💡 Actions possibles :
  - Prolonger garantie constructeur ?
  - Problèmes à signaler avant expiration ?
  - Rien à faire → archiver

[🛠️ Problème à signaler] [✅ Tout va bien]
```

#### 4.2.4 Architecture technique

```
┌─────────────────────────────────────────────────────────┐
│                  PIPELINE ARCHIVISTE                     │
└─────────────────────────────────────────────────────────┘

Sources multiples :
  - Scanner physique → PC (~/Documents/Uploads/)
  - PJ emails → Transit VPS (via Module 1)
  - Photos factures → BeeStation → PC → Transit VPS
  - Téléchargements → PC (~/Downloads/)
                    ↓
      Syncthing sync → VPS (/data/transit/uploads/)
                    ↓
      n8n webhook (file-processing.json)
                    ↓
      Détection type fichier (file_detection.py)
                    ↓
      ┌─────────────┴─────────────┐
      │                           │
  OCR (si PDF image)         Extraction métadonnées
  Surya + Marker             (si PDF natif/texte)
      │                           │
      └─────────────┬─────────────┘
                    ↓
      Agent Archiviste (agents/src/agents/archiviste/agent.py)
                    ↓
      Analyse contenu (Claude Sonnet 4.5, anonymisé via Presidio)
                    ↓
      Extraction :
        - Type (facture, contrat, article, brochure, etc.)
        - Émetteur
        - Date
        - Montant (si applicable)
        - Structure (SELARL/SCM/SCI/Perso)
        - Domaine (médical, juridique, etc.)
        - Garantie (si achat avec garantie)
                    ↓
      Génération nom intelligent :
        Format : YYYY-MM-DD_Type_Emetteur_Details_Montant.ext
                    ↓
      Classification automatique :
        Règles explicites (core.correction_rules)
        + LLM (si pas de règle)
                    ↓
      Détermination chemin :
        ~/Documents/[Catégorie]/[Structure]/[Année]/[Mois]/[Nom].ext
                    ↓
      ┌─────────────┴─────────────┐
      │                           │
  Garantie détectée ?        Pas de garantie
      │                           │
  Insert PostgreSQL              │
  (knowledge.warranties)         │
  + Création alertes             │
      │                           │
      └─────────────┬─────────────┘
                    ↓
      Indexation vectorielle :
        - Génération embeddings (via adaptateur)
        - Insert pgvector (table: knowledge.embeddings) (D19)
        - Insert PostgreSQL metadata (ingestion.documents)
                    ↓
      Syncthing sync → PC (chemin final)
                    ↓
      Suppression transit VPS
                    ↓
      Notification Telegram (si PROPOSE, inline buttons)
```

#### 4.2.5 Stockage

| Donnée | PC | VPS | Justification |
|--------|----|-----|---------------|
| **Documents originaux** | ✅ ~/Documents/[catégorie]/ | ❌ Transit éphémère | Source de vérité = PC |
| **Metadata documents** | ❌ | ✅ PostgreSQL (ingestion.documents) | Index et classification |
| **Embeddings** | ❌ | ✅ pgvector (table: knowledge.embeddings) (D19) | Recherche sémantique |
| **Warranties tracking** | ❌ | ✅ PostgreSQL (knowledge.warranties) | Alertes expiration |
| **Liens symboliques garanties** | ✅ ~/Documents/Achats/Garanties_Actives/ | ❌ | Vue synthétique locale |

**Flux fichiers sensibles** (factures, contrats) :
- Presidio anonymise AVANT appel LLM cloud
- Si document ultra-sensible → Ollama VPS uniquement (pas de sortie cloud)
- Mapping éphémère Redis (TTL 15min, JAMAIS PostgreSQL)

#### 4.2.6 Mesures de sécurité spécifiques

| Risque | Mesure | Implémentation |
|--------|--------|----------------|
| **Fuite PII (factures, contrats)** | Presidio AVANT LLM cloud | `agents/src/tools/anonymize.py` |
| **Document ultra-sensible (contrat cabinet)** | Ollama VPS uniquement | Détection automatique via règles |
| **Classement erroné** | Trust Level PROPOSE Day 1 | Validation humaine systématique |
| **Perte document (suppression accidentelle)** | Backup quotidien PC → VPS | `scripts/backup.sh` (7j rotation) |
| **Garantie oubliée** | Alertes 60j/30j/7j avant expiration | Cron quotidien `services/metrics/nightly.py` |
| **Transit VPS saturé** | Nettoyage automatique <15min | Cron `scripts/cleanup-transit.sh` |

#### 4.2.7 Trust Level initial

| Action | Trust Level Day 1 | Justification |
|--------|-------------------|---------------|
| OCR extraction | **AUTO** | Extraction technique, pas de décision métier |
| Renommage fichier | **PROPOSE** | Erreur = nom incorrect (gênant pour recherche) |
| Classement dossier | **PROPOSE** | Erreur = document perdu/mal classé (perte temps) |
| Détection garantie | **PROPOSE** | Erreur = alerte manquée (conséquence réelle) |
| Nettoyage ~/Downloads/ | **PROPOSE** | Erreur = fichier supprimé par erreur (perte de données) |

**Promotion vers AUTO** : Après 3 semaines + accuracy >95% + validation Antonio

---

---

### 📋 MODULE 3-23 : [À COMPLÉTER]

**Note** : Pour chaque module, même structure que Module 1.

---

## 5. SYNTHÈSE DES INCOHÉRENCES DÉTECTÉES

### 5.1 Incohérences résolues

| # | Incohérence | Résolution | Status |
|---|-------------|------------|--------|
| 1 | Apple Watch Ultra | ❌ ABANDONNÉE - Hors scope définitivement | ✅ RÉSOLU |
| 2 | Stockage photos BeeStation | ✅ Transit VPS éphémère uniquement, stockage permanent BeeStation + copie PC | ✅ RÉSOLU |
| 3 | Google Docs thèses | ✅ Sauvegarde locale PC obligatoire (pas juste backup hebdomadaire) | ✅ RÉSOLU |
| 4 | Desktop Search | ✅ Module séparé (pas sous-module email) | ✅ RÉSOLU |

### 5.2 Questions restantes à valider

1. **Trust Levels** : Confirmé initialisation différenciée (auto/propose/blocked selon risque) ?
2. **CSV bancaires** : Antonio télécharge manuellement depuis sites bancaires → upload PC → sync VPS ?
3. **Exemples concrets** : Les scénarios Telegram + PC correspondent à l'usage réel attendu ?

---

## 6. PROCHAINES ÉTAPES

### Étape 1 : Validation Module 1 (Email + Desktop Search) ✅ EN COURS
- [ ] Antonio valide exemples Telegram
- [ ] Antonio valide exemples PC
- [ ] Antonio valide architecture stockage
- [ ] Antonio valide mesures sécurité
- [ ] Antonio confirme Trust Levels initiaux

### Étape 2 : Validation Module 2 (Archiviste)
### Étape 3 : Validation Modules 3-23
### Étape 4 : Synthèse finale incohérences
### Étape 5 : GO / NO-GO implémentation

---

**FIN DU DOCUMENT - Version 1.0**
