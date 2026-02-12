# Plan de deploiement — Epic 2 Pipeline Email

**Date** : 2026-02-12
**Statut** : Valide par Masterplan
**Contexte** : Epic 1 (Socle) stories critiques implementees (1.1 review, 1.10 review, stories ops en backlog). Epic 2 (Email) stories 2.1-2.7 code implementees, Story 2.8 non commitee. Epic 6 (Memoire) code implemente. Il reste a : corriger les trous identifies, deployer sur le VPS, et migrer les emails historiques.

---

## Donnees de reference

- **108 386 messages** sur 4 comptes email
- **139 messages non lus**
- **4 comptes IMAP** : Gmail Pro, Gmail Perso, Zimbra Universite, ProtonMail
- **VPS-4 OVH** : 48 Go RAM, 12 vCores, 300 Go SSD
- **LLM** : Claude Sonnet 4.5 (classification ~$0.003/email, extraction entites graphe ~$0.002/email, embeddings Voyage AI ~$0.001/email)
- **Cout unitaire total** : ~$0.006/email non-blackliste (classification + entites + embeddings)
- **Throughput estime** : 5-10 emails/min (avec classification Claude + extraction entites + embeddings)
- **Budget total revu** : $700 (avec marge erreur 50% sur cout unitaire revise)

---

## Semantique des filtres (decision 2026-02-12)

| Filtre | Signification | Traitement | Tokens Claude | Embeddings | Graphe |
|--------|--------------|------------|---------------|------------|--------|
| **VIP** | Critique, traiter en priorite | Analyse prioritaire + notification immediate | Oui | Oui | Oui |
| **whitelist** | Interessant, garder en memoire | Analyse normale | Oui | Oui | Oui |
| **blacklist** | Pas interessant a analyser | Stocker metadonnees, skip analyse | **Non** | **Non** | **Non** |
| **non liste** | Inconnu | Analyse normale (comme whitelist) | Oui | Oui | Oui |

> **IMPORTANT** : blacklist != spam. Un email blackliste peut etre une newsletter legitime,
> une confirmation de commande, etc. C'est juste "pas interessant a investir des tokens Claude".

### Commandes Telegram filtrage

```
/vip <email|domain>              Marquer comme VIP
/blacklist <email|domain>        Marquer comme blacklist (skip analyse)
/whitelist <email|domain>        Marquer comme whitelist (analyser)
/filters                         Lister les filtres actifs
/filters stats                   Statistiques (emails filtres, economie tokens)
/filters delete <email|domain>   Supprimer un filtre
```

---

## Trous identifies (review adversariale 2026-02-12)

| # | Trou | Severite | Impact |
|---|------|----------|--------|
| 1 | Doublon bot Telegram dans docker-compose.yml (`telegram-bot` + `friday-bot`) | CRITIQUE | Conflit polling Telegram en production |
| 2 | `_is_from_mainteneur()` avec emails placeholder hardcodes | CRITIQUE | Protection donnees, emails fictifs dans le code |
| 3 | Credentials en clair dans `docs/emailengine-setup-4accounts.md` (mot de passe ProtonMail Bridge) | CRITIQUE | Fuite credentials si committe |
| 4 | Pas de Dockerfile ni service Docker pour le consumer email (`services/email_processor/consumer.py`) | Haute | Pipeline email ne peut pas tourner en production |
| 5 | Classifier Story 2.2 pas branche dans consumer.py (stub `category="inbox"` ligne 467) | Haute | Tous les emails classes "inbox", classification inutile |
| 6 | Semantique sender_filter incorrecte (whitelist skip Claude, devrait analyser) | Haute | Comportement inverse de la vision Masterplan |
| 7 | `migrate_emails.py` lit depuis `ingestion.emails_legacy` que rien ne remplit | Bloquant | Migration impossible |
| 8 | `migrate_emails.py` ne supporte pas `--since`/`--until`/`--unread-only` | Bloquant | Pas de decoupage par periode |
| 9 | `extract_email_domains.py` lit depuis `ingestion.emails` (table vide avant migration) | Bloquant | Oeuf et poule — CSV impossible a generer |
| 10 | `fix-ssh-port.sh` obsolete (port 22 debloque) | Trivial | Fichier inutile |
| 11 | Story 2.8 pas commitee (15+ fichiers untracked) | Haute | Code pas dans le repo |
| 12 | Aucun kill switch si budget explose ou classifier bug | CRITIQUE | Pas de rollback si production part en vrille |
| 13 | Validation credentials IMAP absente avant deploiement | CRITIQUE | Risque decouvrir credentials invalides apres deploy infra |
| 14 | Healthcheck email-processor vague et non testable | Haute | Impossible detecter crashloop ou queue bloquee |
| 15 | Phase D sans estimation duree ni throughput baseline | Haute | Impossible planifier (6h ou 6 jours ?) |
| 16 | ProtonMail Bridge sur PC = single point of failure | Haute | Migration bloquee si PC s'eteint |
| 17 | Taille PJ non bornee (risque saturation disque VPS) | Moyenne | Email avec 500 Mo PJ peut remplir /var/friday/transit |
| 18 | Format CSV extract_email_domains.py non specifie | Moyenne | Risque erreur humaine lors remplissage |
| 19 | Population graphe knowledge.* totalement opaque | Moyenne | Impossible verifier que cette partie fonctionne |
| 20 | Estimation cout sous-estimee 50% (pas de marge erreur) | Moyenne | Budget reel probable $400-600 vs $260-300 |

---

## PHASE A.0 — Safety Controls & Kill Switch (1h)

**CRITIQUE** : Implementer AVANT tout deploiement pour eviter explosion budget ou classifier hors controle.

### Variables d'environnement (.env)

```bash
# Master kill switch
PIPELINE_ENABLED=false              # false par defaut, activer manuellement apres tests

# Rate limiting global
MAX_EMAILS_PER_HOUR=100             # Limite globale (ajuster apres benchmarks)

# Budget quotidien
MAX_CLAUDE_COST_PER_DAY=50          # Plafond quotidien ($)
ALERT_THRESHOLD_COST=40             # Alerte Telegram a 80% du budget ($)

# Taille PJ
MAX_ATTACHMENT_SIZE_MB=50           # Taille max par piece jointe
MAX_TOTAL_ATTACHMENTS_MB=200        # Taille max toutes PJ d'un email
```

### Commandes Telegram d'urgence

```python
# bot/handlers/pipeline_control.py (NOUVEAU)
@bot.command("pipeline")
async def pipeline_control(update, context):
    """
    /pipeline stop   - Kill switch immediat (PIPELINE_ENABLED=false en Redis)
    /pipeline start  - Redemarre manuellement
    /pipeline status - Etat + conso tokens temps reel
    """

@bot.command("budget")
async def budget_command(update, context):
    """
    Affiche budget LLM aujourd'hui + ce mois + projection fin mois
    Source : table core.llm_usage
    """
```

### Table tracking budget LLM

> **CONFLIT RESOLU** : L'ancienne migration 034 (`ALTER TABLE core.api_usage`) referençait une table
> inexistante. Decision : **reecrire migration 034** avec la table `core.llm_usage` ci-dessous.
> Le code `migrate_emails.py` (qui inserait dans `core.api_usage`) devra etre mis a jour
> pour utiliser `core.llm_usage` a la place.

```sql
-- database/migrations/034_llm_usage_tracking.sql
-- Reecriture migration 034 : core.llm_usage remplace core.api_usage (inexistante)
BEGIN;

CREATE TABLE core.llm_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    provider TEXT NOT NULL,      -- 'anthropic', 'voyage'
    model TEXT NOT NULL,          -- 'claude-sonnet-4-5', 'voyage-2'
    input_tokens INT,
    output_tokens INT,
    cost_usd DECIMAL(10,6),
    context TEXT,                 -- 'email_classification', 'entity_extraction', 'embeddings', etc.
    email_id UUID REFERENCES ingestion.emails(id),
    tokens_saved_by_filters INT DEFAULT 0  -- absorbe ancien 034
);

CREATE INDEX idx_llm_usage_timestamp ON core.llm_usage(timestamp);
CREATE INDEX idx_llm_usage_provider ON core.llm_usage(provider, model);
CREATE INDEX idx_llm_usage_daily ON core.llm_usage(timestamp::date);

COMMENT ON TABLE core.llm_usage IS 'Tracking couts LLM par appel (classification, extraction entites, embeddings). Remplace migration 034.';

COMMIT;
```

### Procedure rollback d'urgence (services)

```bash
# Si probleme detecte en production
ssh vps-friday
cd /opt/friday

# 1. Arreter pipeline IMMEDIATEMENT
docker compose stop email-processor friday-bot

# 2. Analyser les logs
docker compose logs email-processor --tail 200 > /tmp/debug.log
docker compose logs friday-bot --tail 100 >> /tmp/debug.log

# 3. Verifier budget consomme
psql friday -c "SELECT SUM(cost_usd) FROM core.llm_usage WHERE timestamp::date = CURRENT_DATE;"

# 4. Fix code si necessaire
git pull
docker compose build email-processor friday-bot

# 5. Redemarre SEULEMENT apres validation
docker compose up -d email-processor friday-bot
```

### Procedure rollback donnees (re-classification bulk)

> **Scenario** : Des emails ont ete migres avec des classifications erronees
> (bug classifier, prompt mal calibre, absence de correction rules).

```bash
# 1. Identifier les emails mal classes (par periode ou par lot)
psql friday -c "
  SELECT category, COUNT(*), AVG(confidence)
  FROM ingestion.emails
  WHERE received_at BETWEEN '2025-01-01' AND '2025-12-31'
  GROUP BY category ORDER BY count DESC;
"

# 2. Marquer les emails a re-classifier
psql friday -c "
  UPDATE ingestion.emails
  SET category = 'pending_reclassify', processed_at = NULL
  WHERE received_at BETWEEN '2025-01-01' AND '2025-12-31'
    AND confidence < 0.7;  -- Seuil ajustable
"

# 3. Nettoyer graphe et embeddings associes (si necessaire)
psql friday -c "
  DELETE FROM knowledge.embeddings
  WHERE email_id IN (
    SELECT id FROM ingestion.emails WHERE category = 'pending_reclassify'
  );
  DELETE FROM knowledge.edges
  WHERE metadata->>'source' = 'email_pipeline'
    AND metadata->>'email_id' IN (
      SELECT id::text FROM ingestion.emails WHERE category = 'pending_reclassify'
    );
"

# 4. Relancer migration sur les emails marques
python scripts/migrate_emails.py --reclassify --trust-propose --limit 100
# → Valider manuellement, puis --trust-auto pour le reste
```

**Option nucleaire** (si tout est corrompu) :
```bash
# Supprimer toute une periode et remigrer
psql friday -c "
  DELETE FROM knowledge.embeddings WHERE email_id IN (
    SELECT id FROM ingestion.emails WHERE received_at BETWEEN '2025-01-01' AND '2025-12-31'
  );
  DELETE FROM ingestion.emails WHERE received_at BETWEEN '2025-01-01' AND '2025-12-31';
"
# Relancer migration depuis zero pour cette periode
python scripts/migrate_emails.py --since 2025-01-01 --until 2025-12-31 --trust-propose
```

> **Note** : Le parametre `--reclassify` est a implementer dans la reecriture de migrate_emails.py.
> Il doit re-traiter les emails deja en base (UPDATE au lieu de INSERT), sans doublonner.

---

## PHASE A — Corrections code (8-10h, duree revisee)

### A.1 — CRITIQUE : Doublon bot docker-compose.yml (30 min)

**Probleme** : Deux services bot Telegram identiques dans `docker-compose.yml` :
- `telegram-bot` (ligne 234, IP 172.20.0.21) — ancienne version, depend de gateway
- `friday-bot` (ligne 343, IP 172.20.0.24) — version actuelle, autonome, depend postgres + redis

**Decision** : Garder `friday-bot`, supprimer `telegram-bot`.

**Action** :
1. Supprimer service `telegram-bot` de `docker-compose.yml` (lignes 234-250 environ)
2. Optionnel : Renommer `friday-bot` → `telegram-bot` pour coherence naming
3. Verifier que `bot/main.py` utilise bien les 5 topics (variables `TOPIC_*_ID`)
4. Test : `docker compose config | grep -A 10 "telegram-bot\|friday-bot"` (doit montrer 1 seul service)

### A.2 — CRITIQUE : _is_from_mainteneur() vrais emails (30 min)

**Probleme** : `consumer.py` ligne 1155 contient des emails placeholder (`antonio.lopez@example.com`).

**Action** : Lire depuis variable d'environnement `MAINTENEUR_EMAILS` (liste separee par virgules). Jamais hardcode.

**Vrais emails** : Stockes exclusivement dans `.env.email.enc` (chiffre age/SOPS). Ne JAMAIS les lister en clair dans la documentation ou le code.

### A.3 — CRITIQUE : Credentials en clair (30 min)

**Probleme** : `docs/emailengine-setup-4accounts.md` contient le mot de passe ProtonMail Bridge en clair.

**Action** : Retirer tous les credentials du fichier. Remplacer par des references a `.env.email.enc`. Le fichier de documentation ne doit contenir que la procedure, pas les secrets.

### A.4 — Dockerfile + service email-processor (1h)

**Probleme** : Le composant central du pipeline email n'a pas de conteneur Docker.

**Action** :
- Creer `Dockerfile.email-processor`
- Ajouter service `email-processor` dans `docker-compose.yml`
- Healthcheck : verifier que le consumer est connecte a Redis et traite des events

### A.5 — Brancher classifier dans consumer.py (2-3h)

**Probleme** : Le classifier Story 2.2 (`agents/src/agents/email/classifier.py`, 528 lignes, 45 tests PASS) n'est pas appele.

**Action** :
1. Inverser l'ordre : stocker email d'abord (category="pending"), puis classifier (UPDATE)
2. Importer `classify_email` depuis `agents.src.agents.email.classifier`
3. Appeler le classifier pour les emails non filtres (remplacer stub ligne 467-470)

### A.6 — Nouvelle semantique sender_filter (1h)

**Probleme** : Le code actuel de Story 2.8 fait blacklist = "spam" et whitelist = skip Claude. C'est l'inverse de la vision validee.

**Action** :
- Modifier `agents/src/agents/email/sender_filter.py` :
  - blacklist → skip analyse (category = "blacklisted", pas "spam")
  - whitelist → return None (proceed to classify normalement)
  - VIP → return avec flag `is_vip=True` + priorite haute
- Ajouter `filter_type = 'vip'` dans table `core.sender_filters` (CHECK constraint)
- Ajouter commande `/vip <email|domain>` dans `bot/handlers/sender_filter_commands.py`
- Modifier `consumer.py` pour gerer VIP (notification immediate)

### A.7 — Nettoyage (15 min)

Supprimer `scripts/fix-ssh-port.sh` (port 22 debloque, confirme par Masterplan).

### A.8 — Contraintes taille PJ dans consumer.py (30 min)

**Probleme** : Aucune limite sur la taille des pieces jointes. Un email avec 500 Mo de PJ peut saturer `/var/friday/transit/`.

**Action** : Ajouter dans `services/email_processor/consumer.py` fonction `extract_attachments()` :

```python
# Constantes
MAX_ATTACHMENT_SIZE_MB = 50  # Par PJ
MAX_TOTAL_ATTACHMENTS_MB = 200  # Par email

async def extract_attachments(email_data: dict):
    total_size = 0
    attachments = []
    skipped = []

    for att in email_data.get('attachments', []):
        size_mb = att['size'] / (1024 * 1024)

        if size_mb > MAX_ATTACHMENT_SIZE_MB:
            logger.warning(
                f"Skipping large attachment: {att['filename']} ({size_mb:.1f} MB)"
            )
            skipped.append(f"{att['filename']} ({size_mb:.1f} MB)")
            continue

        total_size += size_mb
        if total_size > MAX_TOTAL_ATTACHMENTS_MB:
            logger.warning(f"Max total size reached ({total_size:.1f} MB)")
            break

        attachments.append(att)

    # Notifier si PJ ignorees
    if skipped:
        await notify_telegram(
            f"⚠️ PJ ignorees (trop grosses):\n" + "\n".join(f"- {s}" for s in skipped),
            topic="system"
        )

    return attachments
```

### A.9 — CRITIQUE : Validation credentials IMAP (1h)

**Probleme** : Aucun test de connexion IMAP avant deploiement. Risque de decouvrir credentials invalides apres avoir deploye toute l'infra.

**Action** : Creer `scripts/test_imap_connections.py` :

```python
"""
Teste TOUS les comptes IMAP AVANT Phase B.
Verifie : connexion, count messages, latence reseau.
"""
import imaplib
import os
from datetime import datetime

ACCOUNTS = [
    {
        "name": "Gmail Pro",
        "host": "imap.gmail.com",
        "port": 993,
        "user": os.getenv("GMAIL_PRO_USER"),
        "password": os.getenv("GMAIL_PRO_PASSWORD"),
        "expected_count": 27000,  # Approximatif
    },
    {
        "name": "Gmail Perso",
        "host": "imap.gmail.com",
        "port": 993,
        "user": os.getenv("GMAIL_PERSO_USER"),
        "password": os.getenv("GMAIL_PERSO_PASSWORD"),
        "expected_count": 19000,
    },
    {
        "name": "Zimbra Universite",
        "host": "zimbra.umontpellier.fr",
        "port": 993,
        "user": os.getenv("ZIMBRA_USER"),
        "password": os.getenv("ZIMBRA_PASSWORD"),
        "expected_count": 45000,
    },
    {
        "name": "ProtonMail Bridge",
        "host": os.getenv("PROTON_BRIDGE_HOST", "pc-mainteneur"),  # DNS Tailscale (pas IP hardcodee)
        "port": 1143,
        "user": os.getenv("PROTON_USER"),
        "password": os.getenv("PROTON_BRIDGE_PASSWORD"),
        "expected_count": 17000,
        "tls": False,  # ProtonMail Bridge local via Tailscale
    },
]

# Note : Utiliser les noms DNS Tailscale (ex: pc-mainteneur, vps-friday)
# plutot que les IPs hardcodees (100.100.x.x) qui peuvent changer
# si le device est re-enregistre dans Tailscale.

def test_account(account):
    print(f"\nTesting {account['name']}...")
    start = datetime.now()

    try:
        # Connexion IMAP
        if account.get('tls', True):
            imap = imaplib.IMAP4_SSL(account['host'], account['port'])
        else:
            imap = imaplib.IMAP4(account['host'], account['port'])

        imap.login(account['user'], account['password'])

        # Count messages
        imap.select('INBOX')
        _, data = imap.search(None, 'ALL')
        count = len(data[0].split())

        imap.logout()

        latency = (datetime.now() - start).total_seconds()

        # Validation
        diff_pct = abs(count - account['expected_count']) / account['expected_count'] * 100

        if diff_pct > 20:
            print(f"  ⚠️  Count mismatch: {count} vs {account['expected_count']} expected ({diff_pct:.1f}% diff)")
        else:
            print(f"  ✓ {count} messages")

        if latency > 5:
            print(f"  ⚠️  High latency: {latency:.2f}s")
        else:
            print(f"  ✓ Latency: {latency:.2f}s")

        return True

    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        return False

if __name__ == "__main__":
    results = [test_account(acc) for acc in ACCOUNTS]

    if all(results):
        print("\n✓ ALL ACCOUNTS VALID - Ready for Phase B")
        exit(0)
    else:
        print("\n✗ SOME ACCOUNTS FAILED - Fix before continuing")
        exit(1)
```

**Execution** :
```bash
# Local PC (avant Phase B)
export $(sops -d .env.email.enc | xargs)
python scripts/test_imap_connections.py

# Output attendu :
# Testing Gmail Pro...
#   ✓ 27453 messages
#   ✓ Latency: 1.23s
# ...
# ✓ ALL ACCOUNTS VALID - Ready for Phase B
```

**Si echec ProtonMail Bridge** : Verifier que Bridge tourne sur PC + Tailscale connecte.

### A.10 — Commit + push (30 min)

Committer :
- Story 2.8 (15+ fichiers untracked)
- Toutes les corrections A.1 a A.9
- Migration 034 reecrite : table core.llm_usage (remplace core.api_usage inexistante)
- Scripts utilitaires (setup_emailengine, generate-secrets, fix-tailscale-protonvpn, test_imap_connections)
- bot/handlers/pipeline_control.py (kill switch)
- `.env.email.enc` + `.env.email.README.md`

```bash
git add .
git commit -m "feat(epic2): corrections pre-deploiement + safety controls

- Fix doublon bot Telegram (garder friday-bot)
- Securiser _is_from_mainteneur() avec MAINTENEUR_EMAILS envvar
- Retirer credentials docs/emailengine-setup-4accounts.md
- Dockerfile + service email-processor
- Brancher classifier dans consumer.py
- Nouvelle semantique sender_filter (VIP/whitelist/blacklist)
- Contraintes taille PJ (50 MB/PJ, 200 MB/email)
- Validation credentials IMAP pre-deploiement
- Safety controls : kill switch, budget tracking, rate limiting
- Migration 034 reecrite : core.llm_usage (remplace core.api_usage inexistante)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

git push origin master
```

---

## STORY 2.9 — Migration emails progressive (15-25h)

> **ESTIMATION REVISEE** : L'estimation initiale (8-12h) sous-estimait le travail.
> Story 2.9 inclut : reecriture complete de `migrate_emails.py` (nouvelle source API,
> 9 parametres CLI, checkpoint revu), reecriture de `extract_email_domains.py`
> (nouvelle source API, nouveau format CSV, workflow Telegram), creation de
> `validate_migration.py`, `benchmark_consumer.py`, `supervise-protonmail-bridge.ps1`.
> = 2 scripts a reecrire + 3 scripts a creer.

### Story

En tant que **Masterplan**,
Je veux **migrer les 108k emails historiques progressivement (par annee, du plus recent au plus ancien)**,
Afin de **donner a Friday la connaissance de mon historique email sans exploser le budget tokens**.

### Reecriture migrate_emails.py (A FAIRE — Phase A)

> **ETAT ACTUEL** : Le script existant (942 lignes) lit depuis `ingestion.emails_legacy`,
> ne supporte pas `--since`/`--until`/`--unread-only`/`--trust-*`, et n'utilise pas l'API EmailEngine.
> Il doit etre ENTIEREMENT reecrit pour correspondre a cette specification.

**Source de donnees cible** : API EmailEngine REST (remplace `ingestion.emails_legacy` qui n'est jamais peuplee)

**Parametres CLI** :
```bash
python scripts/migrate_emails.py \
  [--since YYYY-MM-DD]          # Date debut (inclus)
  [--until YYYY-MM-DD]          # Date fin (inclus)
  [--unread-only]               # Seulement non-lus
  [--limit N]                   # Limite nombre emails (pour tests/sample check)
  [--trust-auto]                # Bypass validation Telegram (bulk)
  [--trust-propose]             # Validation Telegram (defaut pour sample)
  [--resume]                    # Reprendre depuis checkpoint (last_processed_id)
  [--reclassify]                # Re-traiter emails deja en base (UPDATE, pas INSERT)
  [--account ACCOUNT_ID]        # Filtrer par compte (optionnel)
```

> **Note** : Pas de `--skip-first`. Le mecanisme `--resume` avec checkpoint
> (fichier JSON contenant `last_processed_id`) garantit une reprise fiable
> meme si l'ordre de retour de l'API EmailEngine change entre deux appels.
> Workflow : `--limit 100` pour sample → valider → `--resume --trust-auto` pour le reste.

**Comportement** :
- Tri : `ORDER BY received_at DESC` (plus recent d'abord)
- Checkpoint : fichier JSON `/tmp/migrate_checkpoint_{since}_{until}.json`
  - Contient : `last_processed_id`, `count_migrated`, `count_skipped`, `timestamp`
- Progression : log toutes les 10 emails, checkpoint toutes les 100
- Validation integrite : compare count EmailEngine API vs count PostgreSQL apres chaque batch 1000
- Errors : retry 3x avec backoff exponentiel, skip email si echec permanent (log + alerte Telegram)

**Sample check OBLIGATOIRE** (securite) :
```python
# Premier run TOUJOURS en mode propose sur 100 emails
if not os.path.exists(f"/tmp/sample_validated_{since}_{until}.flag"):
    logger.info("SAMPLE CHECK MODE: Premiers 100 emails en mode propose")
    limit = 100
    trust_mode = "propose"
    # Apres validation manuelle, creer flag + relancer en --trust-auto
```

### Reecriture extract_email_domains.py (A FAIRE — Phase A)

> **ETAT ACTUEL** : Le script existant lit depuis `ingestion.emails` (table vide avant migration),
> utilise des colonnes differentes (`category_distribution`, `suggested_filter_type`, etc.),
> et genere `filter_type = "neutral"` incompatible avec la nouvelle migration 033.
> Il doit etre reecrit pour utiliser l'API EmailEngine.

**Source de donnees cible** : API EmailEngine REST (headers seulement, 0 token)

**Format CSV strict** :
```csv
domain,email_count,suggestion,action
example.com,1234,whitelist,
spam.com,567,blacklist,blacklist
vip-client.fr,89,vip,vip
newsletter.com,450,blacklist,
important.org,23,whitelist,whitelist
```

**Colonnes** :
- `domain` : Domaine extrait du sender
- `email_count` : Nombre d'emails de ce domaine
- `suggestion` : Suggestion auto (vip si >50 emails pro, blacklist si newsletters, whitelist sinon)
- `action` : A remplir par Mainteneur (`vip`, `whitelist`, `blacklist`, ou vide = pas de filtre)

**Workflow** :
1. Script genere CSV → envoie via `bot.send_document(caption="📊 Remplir colonne 'action'")`
2. Mainteneur telecharge, ouvre dans Excel, remplit colonne `action`
3. Mainteneur renvoie CSV modifie dans topic System
4. Bot detecte document, valide CSV, applique filtres
5. Confirmation Telegram : "✓ 143 filtres appliques : 18 VIP, 58 whitelist, 67 blacklist"

**Validation CSV** :
```python
def validate_csv(csv_path: str):
    with open(csv_path) as f:
        reader = csv.DictReader(f)

        # Verifier headers
        if list(reader.fieldnames) != ["domain", "email_count", "suggestion", "action"]:
            raise ValueError(f"Invalid headers: {reader.fieldnames}")

        for i, row in enumerate(reader, start=2):
            # Verifier action valid
            if row['action'] and row['action'] not in ['vip', 'whitelist', 'blacklist']:
                raise ValueError(f"Line {i}: Invalid action '{row['action']}' (must be vip/whitelist/blacklist or empty)")

            # Verifier domain format
            if not re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', row['domain']):
                raise ValueError(f"Line {i}: Invalid domain '{row['domain']}'")

    return True
```

**Application filtres** :
```python
async def apply_filters_from_csv(csv_path: str):
    stats = {"vip": 0, "whitelist": 0, "blacklist": 0}

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row['action']:
                continue  # Skip vides

            await db.execute(
                """
                INSERT INTO core.sender_filters (filter_type, sender_domain, created_by)
                VALUES ($1, $2, 'system')
                ON CONFLICT (sender_domain) WHERE sender_email IS NULL
                DO UPDATE SET filter_type = EXCLUDED.filter_type, updated_at = NOW()
                """,
                row['action'], row['domain']
            )
            stats[row['action']] += 1

    return stats
```

### Migration 033 — Modifier AVANT commit (pas de migration 035 separee)

**Constat** : La migration `033_sender_filters.sql` (Story 2.8, non commitee) definit actuellement :
```sql
filter_type TEXT NOT NULL CHECK (filter_type IN ('whitelist', 'blacklist', 'neutral'))
```

**Action** : Modifier **directement** la migration 033 (puisqu'elle n'est pas encore commitee) :
1. Remplacer `('whitelist', 'blacklist', 'neutral')` → `('vip', 'whitelist', 'blacklist')`
2. Supprimer `neutral` (un email non liste = traitement normal, pas besoin d'un filtre)
3. Ajouter index partiel VIP pour queries rapides
4. Mettre a jour les COMMENTs pour refleter la nouvelle semantique

```sql
-- Dans 033_sender_filters.sql, remplacer le CHECK :
filter_type TEXT NOT NULL CHECK (filter_type IN ('vip', 'whitelist', 'blacklist')),

-- Ajouter apres les index existants :
CREATE INDEX IF NOT EXISTS idx_sender_filters_vip
    ON core.sender_filters(filter_type)
    WHERE filter_type = 'vip';
```

**Avantage** : Pas de migration ALTER apres coup. Schema propre des le premier deploy.
**Impact** : Zero migration supplementaire (035 supprimee du plan).

### Decoupage par etape (avec durees estimees)

**Benchmark requis** : Avant Phase D, mesurer throughput reel en Phase C.7.5 (test 100 emails).

**Baseline attendue** : 5-10 emails/min (avec classification Claude + embeddings + graphe)

| Etape | Periode | Emails estimes | Commande | Duree estimee | Cout estime |
|-------|---------|----------------|----------|---------------|-------------|
| D.1 | Non-lus | 139 | `--unread-only` | ~15-30 min | ~$0.85 |
| D.2 | 01/01/2026 a aujourd'hui | ~1,500 | `--since 2026-01-01` | ~2.5-5h | ~$9-18 |
| D.3 | 2025 | ~12,000 | `--since 2025-01-01 --until 2025-12-31` | ~20-40h | ~$72-144 |
| D.4 | 2024 | ~15,000 | `--since 2024-01-01 --until 2024-12-31` | ~25-50h | ~$90-180 |
| D.5 | 2023 | ~12,000 | `--since 2023-01-01 --until 2023-12-31` | ~20-40h | ~$72-144 |
| ... | Annee par annee | Variable | ... | Evaluer apres chaque annee | Evaluer |
| D.N | Avant 2006 | ~40,000 | `--until 2005-12-31` | ~70-140h | ~$240-480 |

**Total estime D.1-D.5** : ~90-175h (etaler sur 2-3 semaines avec pauses quotidiennes)

**IMPORTANT** : Durees supposent throughput 5-10 emails/min et 30-40% blacklist. Couts bases sur $0.006/email non-blackliste. Ajuster apres benchmarks Phase C.7.5.

### Plan B — Si Phase D depasse 4 semaines ou $700

**Declencheurs** :
- Apres D.3 (2025) : cout reel > $200 (vs ~$80-160 estime)
- Throughput benchmark < 3 emails/min
- Taux blacklist < 20% (vs 30-40% estime)
- Duree D.3 depasse 50h

**Options** :

| Option | Impact | Economie |
|--------|--------|----------|
| **Blacklist agressif** : Augmenter seuil blacklist (>5 emails/domaine non-pro) | Moins de precision, plus de filtrage | -30-50% cout |
| **Skip extraction entites** : Classification + embeddings seulement (pas de graphe) | Graphe knowledge incomplet pour emails anciens | -33% cout ($0.004 au lieu de $0.006) |
| **Skip embeddings anciens** : Classifier seulement avant 2020 | Recherche semantique limitee avant 2020 | -16% cout ($0.005 au lieu de $0.006) |
| **Stop & evaluate** : Arreter apres 2020, migrer le reste a la demande | Pas de couverture complete | Stop les couts |

**Decision** : Evaluer apres D.3 (2025). Le plan par defaut est de continuer annee par annee.
Si budget depasse $500 apres D.3, appliquer "Skip extraction entites" sur D.4+ (priorite classification + embeddings).

### Traitement par email non-blackliste

Pour chaque email non-blackliste, les 3 phases sont executees :
1. **Classification** (Claude Sonnet 4.5) : ~$0.003/email
2. **Extraction entites pour graphe** (Claude Sonnet 4.5) : ~$0.002/email (personnes, orgs, lieux)
3. **Population graphe** (nodes/edges dans knowledge.*) : $0 (DB locale)
4. **Embeddings** (Voyage AI + pgvector) : ~$0.001/email
- **Total** : ~$0.006/email

> **CORRECTION** : La version precedente omettait le cout d'extraction d'entites (etape 2),
> qui fait un second appel Claude pour alimenter le graphe de connaissances.
> Le cout unitaire passe de $0.004 a $0.006/email.

### Estimation cout avec filtres (REVISEE v2)

**Calcul baseline** :
```
108 386 emails totaux
  - blacklist (~30-40%) : ~35-40k emails skip → $0
  = ~65-75k emails traites
  × $0.006/email (classification + extraction entites + embeddings)
  = ~$390-450 cout baseline
```

**Facteurs d'incertitude (marge erreur 50%)** :
- Retry sur rate limits Claude : +10-15%
- Emails >10k tokens (rares, <5%) : +5-10%
- PJ avec OCR (si >1000 PJ) : +10-15%
- Imprevu (bugs, retraitement) : +10%

**Cout REALISTE avec marge** :
```
$390-450 (baseline)
  × 1.5 (marge erreur 50%)
  = ~$585-675 cout realiste

Budget recommande : $700 (marge confort)
```

**Risque blacklist** : Si seulement 15% d'emails sont blacklistes (au lieu de 30-40%), le cout baseline monte a ~$550, et le cout realiste a ~$825. Le budget $700 serait alors insuffisant.

**Strategie progressive** : Apres chaque etape annuelle, verifier le cout reel et decider de continuer.

**Point de decision** : Si cout D.1-D.3 depasse $200 → reevaluer avant de continuer D.4+.

---

## PHASE B — Connectivite & Infra VPS (3-4h)

| # | Tache | Detail |
|---|-------|--------|
| B.1 | Verifier SSH vers VPS | Cle SSH regeneree, port 22 |
| B.2 | Verifier Tailscale mesh | PC (pc-mainteneur) ↔ VPS (vps-friday) via DNS Tailscale. Verifier `tailscale status` sur les deux machines. |
| B.3 | ProtonMail Bridge + supervision | Demarre sur PC, accessible VPS via Tailscale port 1143 + healthcheck |
| B.4 | Git pull sur VPS | Recuperer tout le code committe |
| B.5 | Secrets | Cle age sur VPS, dechiffrer `.env.enc` + `.env.email.enc` |
| B.6 | Services socle | `docker compose up -d postgres redis` |
| B.7 | Migrations | `python scripts/apply_migrations.py` (001→034, sequence continue) |
| B.8 | Gateway + Caddy | `docker compose up -d caddy gateway` + healthcheck |

### B.3 — ProtonMail Bridge : Setup + Supervision (DETAIL)

**Probleme** : ProtonMail Bridge tourne sur PC. Si PC s'eteint pendant migration → tout bloque.

**Setup initial (PC Windows)** :
1. Demarrer ProtonMail Bridge (`C:\Program Files\ProtonMail\Bridge\protonmail-bridge.exe`)
2. Verifier connexion Tailscale (`tailscale status` — noter le nom DNS Tailscale du PC)
3. Tester depuis VPS : `telnet pc-mainteneur 1143` (utiliser DNS Tailscale, pas IP hardcodee)

**Script supervision (PC)** : `scripts/supervise-protonmail-bridge.ps1`

```powershell
# Supervision ProtonMail Bridge avec auto-restart + alertes Telegram
param(
    [string]$TelegramToken = $env:TELEGRAM_BOT_TOKEN,
    [string]$ChatId = $env:TELEGRAM_SUPERGROUP_ID,
    [string]$TopicId = $env:TOPIC_SYSTEM_ID
)

function Send-TelegramAlert {
    param([string]$Message)
    $url = "https://api.telegram.org/bot$TelegramToken/sendMessage"
    $body = @{
        chat_id = $ChatId
        message_thread_id = $TopicId
        text = $Message
    } | ConvertTo-Json
    Invoke-RestMethod -Uri $url -Method Post -Body $body -ContentType "application/json"
}

# Detecter le nom reel du process au demarrage
# (peut etre "protonmail-bridge", "ProtonMailBridge", "bridge", etc. selon la version)
$BridgeProcessName = $null
$PossibleNames = @("protonmail-bridge", "ProtonMailBridge", "bridge", "Proton Mail Bridge")
foreach ($name in $PossibleNames) {
    if (Get-Process $name -ErrorAction SilentlyContinue) {
        $BridgeProcessName = $name
        Write-Host "Detected Bridge process name: $BridgeProcessName"
        break
    }
}
if (-not $BridgeProcessName) {
    Write-Host "WARNING: ProtonMail Bridge not running. Starting it..."
    Start-Process "C:\Program Files\ProtonMail\Bridge\protonmail-bridge.exe"
    Start-Sleep 15
    # Re-detect
    foreach ($name in $PossibleNames) {
        if (Get-Process $name -ErrorAction SilentlyContinue) {
            $BridgeProcessName = $name
            break
        }
    }
    if (-not $BridgeProcessName) {
        Write-Host "FATAL: Cannot detect ProtonMail Bridge process name. Check installation."
        exit 1
    }
    Write-Host "Detected Bridge process name after start: $BridgeProcessName"
}

while ($true) {
    $process = Get-Process $BridgeProcessName -ErrorAction SilentlyContinue

    if (-not $process) {
        Write-Host "[$(Get-Date)] ProtonMail Bridge DOWN - Redemarrage..."
        Send-TelegramAlert "ProtonMail Bridge down - Redemarrage automatique"

        Start-Process "C:\Program Files\ProtonMail\Bridge\protonmail-bridge.exe"
        Start-Sleep 15  # Attendre demarrage (Bridge peut etre lent)

        # Verifier redemarrage OK
        $process = Get-Process $BridgeProcessName -ErrorAction SilentlyContinue
        if ($process) {
            Send-TelegramAlert "ProtonMail Bridge redemarre OK"
        } else {
            Send-TelegramAlert "ProtonMail Bridge FAILED to restart - INTERVENTION REQUISE"
        }
    }

    Start-Sleep 300  # Check toutes les 5 min
}
```

**Lancer supervision** :
```powershell
# PowerShell en admin
cd C:\Users\lopez\Desktop\Friday 2.0
.\scripts\supervise-protonmail-bridge.ps1
```

**Fallback** : Si Bridge instable → migrer ProtonMail EN DERNIER (Phase D.N, apres autres comptes).

**Alternative future** : Migrer Bridge sur VPS (Docker) si ProtonMail supporte Linux headless.

---

## PHASE C — Email pipeline temps reel (3-4h)

| # | Tache | Detail |
|---|-------|--------|
| C.1 | Services email | `docker compose -f docker-compose.yml -f docker-compose.services.yml up -d emailengine presidio-analyzer presidio-anonymizer` |
| C.2 | Setup comptes | `python scripts/setup_emailengine_4accounts.py` (4 comptes IMAP) |
| C.3 | Webhooks | `python scripts/configure_emailengine_webhooks.py` (EmailEngine → Gateway) |
| C.4 | Telegram | Creer supergroup + 5 topics, extraire thread IDs (script auto), configurer variables `TOPIC_*_ID` |
| C.5 | Bot + Consumer | `docker compose up -d friday-bot email-processor` + verifier healthcheck |
| C.6 | Test bot | `/help` dans Telegram |
| C.7 | **Test E2E** | Envoyer un vrai email → classification Claude → notification Telegram |
| C.7.5 | **Test charge** | 100 emails test → benchmark throughput + latence |
| C.8 | Test filtres | `/blacklist test@spam.com`, `/vip important@chu.fr`, `/filters` |
| C.9 | Activer pipeline | `PIPELINE_ENABLED=true` dans Redis + redemarrer consumer |

### C.4 — Extraction Thread IDs Telegram (DETAIL)

**Script** : `scripts/extract_telegram_thread_ids.py`

```python
"""
Extrait les thread IDs des 5 topics du supergroup Friday.
Output : fichier .env.topics a merger dans .env
"""
import asyncio
from telegram import Bot
import os

TOPICS = [
    "💬 Chat & Proactive",
    "📬 Email & Communications",
    "🤖 Actions & Validations",
    "🚨 System & Alerts",
    "📊 Metrics & Logs",
]

async def extract_topics():
    bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
    chat_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID"))

    # Envoyer message test dans General pour verifier connexion
    await bot.send_message(chat_id, "🔍 Extraction thread IDs en cours...")

    print("Envoyez un message dans CHAQUE topic (dans l'ordre ci-dessous).")
    print("Le bot va afficher les thread IDs.\n")

    for topic in TOPICS:
        print(f"1. Allez dans le topic '{topic}'")
        print(f"2. Envoyez le message : 'test {topic}'")
        input("Appuyez sur Entree apres avoir envoye...")

    print("\nMaintenant, verifiez les derniers messages recus par le bot...")
    # Note : API Telegram ne permet pas de lister directement les topics
    # Workaround manuel : inspecter les messages recus et noter message_thread_id

asyncio.run(extract_topics())
```

**Procedure manuelle alternative** (plus fiable) :
1. Creer supergroup avec topics actives
2. Creer 5 topics avec emojis exacts (ordre important)
3. Envoyer message test dans chaque topic
4. Dans code bot, logger `update.message.message_thread_id` pour chaque message recu
5. Noter les 5 thread IDs et les mettre dans `.env`

### C.5 — Healthcheck email-processor (DETAIL)

**Fichier** : `services/email_processor/healthcheck.py`

```python
"""
Healthcheck pour email-processor consumer.
Verifie : connexion Redis, activite recente, queue non bloquee.
"""
import redis
import sys
import os
import time
from datetime import datetime, timedelta

r = redis.from_url(os.getenv("REDIS_URL"))

try:
    # 1. Verifier connexion Redis
    r.ping()

    # 2. Verifier existence stream
    if not r.exists("emails:received"):
        print("UNHEALTHY: Stream 'emails:received' does not exist")
        sys.exit(1)

    # 3. Verifier consumer group existe
    groups = r.xinfo_groups("emails:received")
    if not any(g['name'] == b'email-processor-group' for g in groups):
        print("UNHEALTHY: Consumer group 'email-processor-group' missing")
        sys.exit(1)

    # 4. Verifier pending messages < 100 (sinon accumulation)
    pending = r.xpending("emails:received", "email-processor-group")
    if pending['pending'] > 100:
        print(f"UNHEALTHY: {pending['pending']} pending messages (threshold: 100)")
        sys.exit(1)

    # 5. Verifier activite recente (detecter consumer zombie)
    last_processed = r.get("email-processor:last_processed_at")
    if last_processed:
        last_ts = float(last_processed)
        idle_seconds = time.time() - last_ts
        # Si des messages pending ET consumer idle >5min → zombie
        if pending['pending'] > 0 and idle_seconds > 300:
            print(f"UNHEALTHY: Consumer idle {idle_seconds:.0f}s with {pending['pending']} pending")
            sys.exit(1)

    # 6. Verifier throughput (si metrique disponible)
    throughput = r.get("email-processor:emails_per_minute")
    if throughput and float(throughput) == 0 and pending['pending'] > 10:
        print(f"UNHEALTHY: 0 emails/min with {pending['pending']} pending")
        sys.exit(1)

    print("HEALTHY")
    sys.exit(0)

except redis.ConnectionError as e:
    print(f"UNHEALTHY: Redis connection failed - {e}")
    sys.exit(1)
except Exception as e:
    print(f"UNHEALTHY: {e}")
    sys.exit(1)
```

**Dockerfile.email-processor** (ajouter) :
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python /app/healthcheck.py || exit 1
```

**Verification** :
```bash
docker compose ps email-processor
# Doit montrer : healthy
```

### C.7.5 — Test de charge 100 emails (BENCHMARK)

**CRITIQUE** : Mesurer throughput AVANT Phase D pour estimer durees realistes.

**Methode** : Injection directe dans Redis Streams (bypass EmailEngine).
Cela teste le consumer isole sans polluer les vraies boites mail.

> **LIMITATION** : Ce benchmark teste le throughput du consumer avec du contenu synthetique.
> Les corps d'email de test sont courts et repetitifs (~120 mots), ce qui produit des reponses
> Claude rapides. Le throughput reel sur de vrais emails (corps longs, PJ, entites complexes)
> sera probablement 20-40% inferieur. Appliquer un facteur de correction conservateur
> sur les resultats avant de planifier Phase D.

**Script** : `tests/load/benchmark_consumer.py`

```python
"""
Injecte 100 faux emails dans Redis Streams pour benchmarker le consumer.
Mesure : throughput, latency, errors, cout tokens, RAM peak.

IMPORTANT : Ne touche PAS aux vrais comptes email.
Les emails de test ont un flag is_benchmark=true pour nettoyage facile.

LIMITATION : Contenu synthetique — throughput reel sera ~20-40% inferieur.
Appliquer facteur correctif 0.6-0.8 sur les resultats.
"""
import asyncio
import json
import os
import time
import uuid

import asyncpg
import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL")
STREAM_KEY = "emails:received"
NUM_EMAILS = 100

# Corpus realiste avec corps de longueur variable pour tester le classifier
# Inclut des sujets de chaque categorie attendue + corps substantiels
TEST_EMAILS = [
    {
        "subject": "Rendez-vous consultation Dr Martin lundi 14h",
        "body": "Bonjour Dr Lopez, je vous confirme le rendez-vous de consultation pour Mme Durand "
                "le lundi 17 fevrier a 14h au cabinet. La patiente presente des douleurs lombaires "
                "chroniques depuis 3 mois. Elle a deja consulte un kinesitherapeute sans amelioration. "
                "Merci de prevoir un examen clinique complet. Cordialement, Secretariat medical.",
    },
    {
        "subject": "Facture EDF n 2026-0234 - Janvier 2026",
        "body": "Cher client, veuillez trouver ci-joint votre facture d'electricite pour la periode "
                "du 01/01/2026 au 31/01/2026. Montant TTC : 187,43 EUR. Reference contrat : "
                "FR-2024-789456. Date limite de paiement : 28/02/2026. Le prelevement automatique "
                "sera effectue le 25/02/2026 sur votre compte bancaire. Pour toute reclamation, "
                "contactez le service client au 09 69 32 15 15.",
    },
    {
        "subject": "Invitation soutenance these M. Dupont - Universite Montpellier",
        "body": "Madame, Monsieur, J'ai le plaisir de vous inviter a la soutenance de these de "
                "M. Pierre Dupont intitulee 'Approches computationnelles pour l'analyse des reseaux "
                "de neurones artificiels appliques a l'imagerie medicale'. La soutenance aura lieu "
                "le 15 mars 2026 a 14h30 en salle des actes, Faculte de Medecine, Universite de "
                "Montpellier. Jury : Pr. Martin (directeur), Dr. Bernard (rapporteur), Pr. Petit.",
    },
    {
        "subject": "Newsletter Carrefour - Promos de la semaine",
        "body": "Decouvrez nos offres exceptionnelles cette semaine ! Fruits et legumes bio -30%. "
                "Electromenager : aspirateur robot a 199 EUR au lieu de 349 EUR. Rayon boucherie : "
                "entrecote de boeuf a 15.99 EUR/kg. Livraison gratuite des 50 EUR d'achats avec "
                "le code CARREFOUR2026. Valable du 12 au 18 fevrier 2026 dans tous les magasins.",
    },
    {
        "subject": "URGENT: Resultat analyse biologique patient ref P-2026-4521",
        "body": "Dr Lopez, resultats urgents pour patient ref P-2026-4521. Glycemie a jeun : "
                "2.45 g/L (norme < 1.10). HbA1c : 9.2% (norme < 6.5%). Creatinine : 18 mg/L "
                "(norme 7-13). DFG estime : 52 mL/min (insuffisance renale moderee). "
                "Recommandation : consultation diabetologie urgente + adaptation traitement. "
                "Laboratoire d'analyses medicales du Lez.",
    },
    {
        "subject": "Rappel reunion SCM vendredi 10h - Ordre du jour",
        "body": "Bonjour a tous, rappel de la reunion SCM ce vendredi 14 fevrier a 10h. "
                "Ordre du jour : 1) Bilan comptable T4 2025 2) Renouvellement bail commercial "
                "3) Investissement materiel echographe 4) Planning vacances ete 2026 "
                "5) Questions diverses. Merci de confirmer votre presence. Dr Martin, Dr Bernard.",
    },
    {
        "subject": "Confirmation commande Amazon #123-456-789",
        "body": "Votre commande a ete confirmee. Livraison estimee : 14-15 fevrier 2026. "
                "Articles : 1x Stethoscope Littmann Classic III (89.99 EUR), "
                "1x Tensiometre bras Omron M7 (79.99 EUR). Total : 169.98 EUR. "
                "Adresse de livraison : Cabinet medical, 15 rue de la Republique, 34000 Montpellier.",
    },
    {
        "subject": "Appel a communications - Congres SFMG 2026 Lyon",
        "body": "La Societe Francaise de Medecine Generale lance son appel a communications pour "
                "le congres annuel 2026 a Lyon (5-7 juin). Themes : IA en medecine generale, "
                "telemedecine post-COVID, prise en charge pluriprofessionnelle. Soumission abstracts "
                "avant le 31 mars 2026 via plateforme en ligne. Format : poster ou communication orale.",
    },
    {
        "subject": "Releve bancaire Janvier 2026 - CIC Montpellier",
        "body": "Releve de compte courant professionnel - Janvier 2026. Solde debut : 15 432.67 EUR. "
                "Mouvements : +12 350.00 (honoraires), +8 200.00 (honoraires), -3 500.00 (loyer), "
                "-1 200.00 (assurance), -890.00 (URSSAF). Solde fin : 30 392.67 EUR. "
                "Prochaine echeance pret : 05/03/2026 - 1 250.00 EUR.",
    },
    {
        "subject": "Re: Bail SCI Ravas - Renouvellement locataire Dupont",
        "body": "Maitre Lopez, suite a notre echange telephonique concernant le renouvellement du "
                "bail de M. Dupont au 23 avenue de Ravas. Le locataire accepte la revision de loyer "
                "a 850 EUR/mois (contre 820 EUR actuellement). Nouvelle duree : 3 ans a compter du "
                "01/04/2026. Je vous envoie le projet de bail pour validation. Cabinet notarial Durand.",
    },
]


async def inject_test_emails():
    r = aioredis.from_url(REDIS_URL)

    print(f"Injecting {NUM_EMAILS} test emails into Redis Streams...")
    start = time.time()

    for i in range(NUM_EMAILS):
        template = TEST_EMAILS[i % len(TEST_EMAILS)]
        email_data = {
            "message_id": f"<benchmark-{uuid.uuid4()}@test.friday>",
            "account_id": "benchmark-account",
            "from": f"test-{i % 10}@benchmark.friday",
            "to": "benchmark-recipient@test.friday",
            "subject": template["subject"],
            "body_text": template["body"],
            "received_at": "2026-02-12T12:00:00Z",
            "is_benchmark": True,
        }
        await r.xadd(STREAM_KEY, {"data": json.dumps(email_data)})

        if (i + 1) % 25 == 0:
            print(f"  Injected {i + 1}/{NUM_EMAILS}")

    elapsed = time.time() - start
    print(f"Injection done in {elapsed:.1f}s\n")
    await r.aclose()
    return start


async def wait_and_measure(injection_start: float, timeout_minutes: int = 20):
    """Attend que le consumer traite les 100 emails, mesure throughput."""
    db = await asyncpg.connect(DATABASE_URL)

    print(f"Waiting for consumer to process (timeout {timeout_minutes}min)...")
    deadline = time.time() + timeout_minutes * 60

    while time.time() < deadline:
        count = await db.fetchval(
            "SELECT COUNT(*) FROM ingestion.emails "
            "WHERE metadata->>'is_benchmark' = 'true'"
        )
        if count >= NUM_EMAILS:
            elapsed = time.time() - injection_start
            throughput = NUM_EMAILS / (elapsed / 60)
            print(f"\n=== BENCHMARK RESULTS ===")
            print(f"Emails processed : {count}/{NUM_EMAILS}")
            print(f"Total time       : {elapsed:.0f}s ({elapsed/60:.1f}min)")
            print(f"Throughput       : {throughput:.1f} emails/min")

            # Cout tokens
            cost = await db.fetchval(
                "SELECT SUM(cost_usd) FROM core.llm_usage "
                "WHERE context = 'benchmark'"
            )
            print(f"Cout tokens      : ${cost or 0:.2f}")
            print(f"Cout/email       : ${(cost or 0)/NUM_EMAILS:.4f}")

            await db.close()
            return True

        print(f"  ... {count}/{NUM_EMAILS} processed")
        await asyncio.sleep(15)

    print(f"\n⚠️ TIMEOUT: Only {count}/{NUM_EMAILS} processed in {timeout_minutes}min")
    await db.close()
    return False


async def cleanup_benchmark():
    """Supprime les donnees de benchmark apres test."""
    db = await asyncpg.connect(DATABASE_URL)
    deleted = await db.fetchval(
        "DELETE FROM ingestion.emails "
        "WHERE metadata->>'is_benchmark' = 'true' "
        "RETURNING COUNT(*)"
    )
    await db.execute("DELETE FROM core.llm_usage WHERE context = 'benchmark'")
    await db.close()
    print(f"\nCleanup: {deleted} benchmark emails supprimees")


if __name__ == "__main__":
    import sys
    if "--cleanup" in sys.argv:
        asyncio.run(cleanup_benchmark())
    else:
        start = asyncio.run(inject_test_emails())
        success = asyncio.run(wait_and_measure(start))
        if not success:
            print("Investiguer logs consumer AVANT Phase D")
            sys.exit(1)
        print("\nPour nettoyer : python benchmark_consumer.py --cleanup")
```

**Metriques attendues** :
- Throughput : 5-10 emails/min (600-1200s pour 100 emails)
- Latence moyenne : <60s par email (injection → classification → DB)
- Erreurs : 0
- RAM peak email-processor : <4 Go
- Cout tokens : ~$0.60 (100 emails x $0.006)

**Avantage vs envoi reel** : Zero pollution des boites mail, nettoyage automatique (`--cleanup`),
reproductible, teste le consumer en isolation.

**Si echec** : Investiguer AVANT Phase D (logs, RAM, rate limits).

> **A partir de C.9 : les tokens Claude commencent a etre consommes sur chaque nouveau mail.**

---

## PHASE D — Migration historique progressive

### Temps 1 — Scanner les domaines (0 token)

```
python scripts/extract_email_domains.py
→ CSV envoye dans Telegram (topic System)
→ Masterplan telecharge, ouvre dans Excel
→ Remplit colonne "action" : vip / whitelist / blacklist / (vide = pas de filtre)
→ Renvoie le CSV valide dans Telegram
→ Friday applique les filtres
→ "143 filtres appliques : 18 VIP, 58 whitelist, 67 blacklist"
```

### Temps 2 — Migrer par annee (WORKFLOW COMPLET)

**IMPORTANT** : Toujours faire sample check (100 emails en mode propose) AVANT bulk auto.

```bash
# Lancer sur le VPS dans tmux
tmux new -s migration
cd /opt/friday
export $(sops -d .env.enc | xargs)
export $(sops -d .env.email.enc | xargs)

# ========== ETAPE D.1 : Non-lus (139 emails) ==========
# Sample check : 50 premiers en mode propose
python scripts/migrate_emails.py --unread-only --limit 50 --trust-propose
# → Valider dans Telegram (/confiance pour voir accuracy)

# Si accuracy ≥95% → continuer en auto (reprend apres le dernier traite)
python scripts/migrate_emails.py --unread-only --trust-auto --resume

# Verification
psql friday -c "SELECT COUNT(*) FROM ingestion.emails WHERE is_read = false;"
# Doit montrer ~139

# ========== ETAPE D.2 : 2026 (~1500 emails) ==========
# Sample check : 100 premiers
python scripts/migrate_emails.py --since 2026-01-01 --limit 100 --trust-propose
# → Valider accuracy

# Bulk (reprend apres les 100 du sample grace au checkpoint)
python scripts/migrate_emails.py --since 2026-01-01 --trust-auto --resume

# Verification integrite
python scripts/validate_migration.py --since 2026-01-01
# Compare count EmailEngine API vs PostgreSQL

# ========== ETAPE D.3 : 2025 (~12000 emails, ~20-40h) ==========
# Sample check
python scripts/migrate_emails.py --since 2025-01-01 --until 2025-12-31 --limit 100 --trust-propose

# Bulk (LONG - etaler sur plusieurs jours, reprend apres sample)
python scripts/migrate_emails.py --since 2025-01-01 --until 2025-12-31 --trust-auto --resume

# PAUSE quotidienne : Ctrl+C propre (sauvegarde checkpoint)
# Reprendre le lendemain :
python scripts/migrate_emails.py --since 2025-01-01 --until 2025-12-31 --trust-auto --resume

# Verification integrite finale
python scripts/validate_migration.py --since 2025-01-01 --until 2025-12-31

# ========== ETAPES D.4, D.5, ... ==========
# Repeter meme workflow pour chaque annee
# Evaluer cout reel apres chaque annee avant de continuer
```

**Commandes utiles pendant migration** :
```bash
# Detacher tmux (migration continue en arriere-plan)
Ctrl+B puis D

# Reattacher
tmux attach -t migration

# Monitoring temps reel (autre terminal SSH)
watch -n 10 'psql friday -c "SELECT COUNT(*) FROM ingestion.emails;"'

# Budget du jour
psql friday -c "SELECT SUM(cost_usd) FROM core.llm_usage WHERE timestamp::date = CURRENT_DATE;"

# Kill d'urgence (si budget explose)
docker compose stop email-processor
```

### Verification apres chaque etape

**Script validation integrite** : `scripts/validate_migration.py`

```python
"""
Compare count EmailEngine API REST vs PostgreSQL pour periode donnee.
Detecte emails manquants (timeout reseau, crash, etc.)
Note : EmailEngine n'a PAS de SDK Python — on utilise httpx sur l'API REST.

Usage:
    python scripts/validate_migration.py --since 2026-01-01
    python scripts/validate_migration.py --since 2025-01-01 --until 2025-12-31
"""
import argparse
import asyncio
import os
import sys

import asyncpg
import httpx

EMAILENGINE_URL = os.getenv("EMAILENGINE_URL", "http://localhost:3000")
EMAILENGINE_TOKEN = os.getenv("EMAILENGINE_ACCESS_TOKEN")


async def count_emailengine_messages(client: httpx.AsyncClient, since: str, until: str = None) -> int:
    """Count messages via EmailEngine REST API (GET /v1/accounts/{id}/messages)."""
    total = 0
    accounts_resp = await client.get(
        f"{EMAILENGINE_URL}/v1/accounts",
        headers={"Authorization": f"Bearer {EMAILENGINE_TOKEN}"},
    )
    accounts_resp.raise_for_status()

    for account in accounts_resp.json().get("accounts", []):
        account_id = account["account"]
        params = {"path": "INBOX", "pageSize": 0}  # pageSize=0 → count only
        if since:
            params["since"] = since
        if until:
            params["until"] = until

        resp = await client.get(
            f"{EMAILENGINE_URL}/v1/account/{account_id}/messages",
            headers={"Authorization": f"Bearer {EMAILENGINE_TOKEN}"},
            params=params,
        )
        resp.raise_for_status()
        total += resp.json().get("total", 0)

    return total


async def validate_migration(since: str, until: str = None):
    async with httpx.AsyncClient(timeout=30) as client:
        # Count EmailEngine API
        ee_count = await count_emailengine_messages(client, since, until)

    # Count PostgreSQL
    db = await asyncpg.connect(os.getenv("DATABASE_URL"))
    query = "SELECT COUNT(*) FROM ingestion.emails WHERE received_at >= $1"
    params = [since]

    if until:
        query += " AND received_at <= $2"
        params.append(until)

    pg_count = await db.fetchval(query, *params)
    await db.close()

    # Compare
    diff = ee_count - pg_count
    diff_pct = (diff / ee_count * 100) if ee_count > 0 else 0

    print(f"\n=== Validation migration ===")
    print(f"Periode : {since} → {until or 'now'}")
    print(f"EmailEngine API : {ee_count} emails")
    print(f"PostgreSQL      : {pg_count} emails")
    print(f"Difference      : {diff} emails ({diff_pct:.1f}%)")

    if abs(diff_pct) > 5:
        print(f"\n WARNING: >5% difference - investigate!")
        return False
    else:
        print(f"\n Integrity check PASSED")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate migration integrity")
    parser.add_argument("--since", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--until", default=None, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()
    success = asyncio.run(validate_migration(args.since, args.until))
    sys.exit(0 if success else 1)
```

**Commandes Telegram** :
```
/filters stats
→ Economie tokens ce mois : $XX (XX emails filtres)

/confiance
→ Accuracy classification par module

/journal
→ 20 dernieres actions (verifier categories)

/budget
→ Depenses aujourd'hui + ce mois + projection
```

**Si erreurs detectees** :
- `/blacklist domaine-problematique.com` (ajuster filtres)
- Correction rules via Trust Layer (Story 1.7)
- Pause migration si accuracy <85% → analyser manuellement 50 emails → corriger prompt classifier

---

## Sequencement & Parallelisme

**Sequencement strict** :

```
PHASE A.0 (safety controls, 1h)
    ↓
PHASE A (corrections code, 8-10h)
    ↓ commit + push
PHASE B (VPS infra, 3-4h)
    ↓
PHASE C (pipeline live temps reel, 4-5h)
    ↓
    [Pipeline live actif - consomme tokens sur nouveaux emails]
    ↓
STORY 2.9 (dev migration scripts, 15-25h) — SEQUENTIEL apres Phase C
    ↓ commit + push
PHASE D (exec migration historique, 90-175h etales sur 2-3 semaines)
```

> **CORRECTION** : Story 2.9 ne peut PAS se chevaucher avec Phase B.
> La reecriture de `migrate_emails.py` et `extract_email_domains.py` utilise
> l'API EmailEngine REST, accessible uniquement APRES Phase C.2 (setup comptes).
> Le developpement peut commencer en local (structure, CLI, tests mocks),
> mais les tests d'integration necessitent l'API EmailEngine operationnelle.

**Dependances** :
- Phase A → Phase B → Phase C : strictement sequentiel
- Story 2.9 dev (structure + tests mocks) : PEUT commencer pendant Phase B/C
- Story 2.9 integration (tests API EmailEngine) : NECESSITE Phase C.2 terminee
- Phase D : NECESSITE Phase C terminee + Story 2.9 terminee

**Planning suggere** :
- Jour 1 : Phase A.0 + A (10-12h) — bloquer la journee
- Jour 2 matin : Phase B (3-4h)
- Jour 2 apres-midi : Phase C (4-5h) + tests
- Jour 3-5 : Story 2.9 dev (15-25h) — structure locale + integration API
- Semaine 2-5 : Phase D progressive (pauses quotidiennes, monitoring)

---

## Flux complet du pipeline email (reference)

```
EmailEngine (4 comptes IMAP)
    ↓ webhook HTTP POST + HMAC-SHA256
Gateway (FastAPI) — services/gateway/routes/webhooks.py
    ├── Valider signature
    ├── Anonymiser via Presidio (from, subject, body preview)
    └── XADD → Redis Streams "emails:received"
    ↓
Consumer (email-processor) — services/email_processor/consumer.py
    ├── XREADGROUP
    ├── Fetch email complet (EmailEngine API, 6 retries backoff)
    ├── check_sender_filter()
    │   ├── VIP → flag prioritaire + notification immediate
    │   ├── blacklist → skip analyse, stocker metadonnees → XACK → FIN
    │   ├── whitelist / non liste → continuer pipeline
    ├── Anonymiser body complet (Presidio)
    ├── Detecter VIP sender + urgence
    ├── Classifier (Claude Sonnet 4.5, @friday_action trust=propose)
    ├── Stocker DB (ingestion.emails anonymise + ingestion.emails_raw chiffre pgcrypto)
    ├── Peupler graphe (agents/src/agents/email/graph_populator.py)
    │   ├── Extraire entites (personnes, orgs, lieux) via Claude
    │   ├── INSERT knowledge.nodes (type='person'|'organization'|'location', name, properties)
    │   ├── INSERT knowledge.edges (source_id, target_id, relation='sent_email'|'works_at'|etc, weight)
    │   └── UPDATE existing nodes (incrementer poids relations)
    ├── Generer embeddings (adapters/vectorstore.py via VectorStoreAdapter)
    │   ├── Appel Voyage AI (embed subject + body summary, model voyage-2)
    │   ├── INSERT knowledge.embeddings (email_id, vector pgvector(1024), metadata)
    │   └── Cout : ~$0.001/email
    ├── Extraire pieces jointes (zone transit VPS)
    ├── Extraire taches (Claude, si category != spam/blacklisted)
    ├── Generer brouillon reponse (Claude, si category pro/medical/academic)
    ├── Notifications Telegram (topic Email ou Actions si urgent)
    └── XACK
    ↓
PostgreSQL
    ├── ingestion.emails (anonymise)
    ├── ingestion.emails_raw (chiffre pgcrypto)
    ├── ingestion.attachments
    ├── knowledge.nodes (entites : personnes, orgs, lieux, concepts)
    ├── knowledge.edges (relations entre entites avec poids)
    └── knowledge.embeddings (vecteurs 1024-dim via Voyage AI + HNSW index)
```

---

## Changelog depuis version initiale

**Version 2.0 (2026-02-12)** — Review adversariale completee, 20 critiques adressees

### Ajouts critiques
- **Phase A.0** : Safety controls (kill switch, budget tracking, rate limiting)
- **Migration 034 reecrite** : Table `core.llm_usage` pour tracking budget LLM
- **A.9** : Validation credentials IMAP pre-deploiement (`test_imap_connections.py`)
- **A.8** : Contraintes taille PJ (50 MB/PJ, 200 MB/email)
- **C.5** : Healthcheck email-processor detaille (Redis streams, pending queue)
- **C.7.5** : Test de charge 100 emails (benchmark throughput AVANT Phase D)
- **C.9** : Activation manuelle pipeline (`PIPELINE_ENABLED=true`)
- **B.3** : Supervision ProtonMail Bridge (`supervise-protonmail-bridge.ps1`)
- **validate_migration.py** : Verification integrite (count EmailEngine vs PostgreSQL)

### Specifications completes
- **Migration 033** : VIP integre directement dans CHECK constraint (pas de migration 035 separee)
- **migrate_emails.py** : Parametres CLI complets + sample check obligatoire + validation integrite
- **extract_email_domains.py** : Format CSV strict + validation + workflow Telegram
- **A.1** : Decision claire (garder `friday-bot`, supprimer `telegram-bot`)
- **Flux pipeline** : Population graphe explicite (`graph_populator.py` + `adapters/vectorstore.py`)

### Estimations revisees
- **Durees Phase D** : 90-175h (vs "6-10h" initial) — etaler sur 2-3 semaines
- **Cout total** : $585-675 realiste (vs $390-450 baseline) — budget recommande $700
- **Throughput** : 5-10 emails/min (baseline a verifier en C.7.5)
- **Phase A** : 8-10h (vs 5-6h) — ajout A.0, A.8, A.9
- **Story 2.9** : 15-25h (vs 8-12h initial) — reecriture complete 2 scripts + creation 3 scripts

### Procedures de securite
- **Rollback services** : Procedure d'urgence (stop services, analyser logs, fix, redeploy)
- **Rollback donnees** : Re-classification bulk, nettoyage graphe/embeddings, option nucleaire (DELETE + remigration)
- **Sample check** : 100 premiers emails en mode `--trust-propose` AVANT bulk `--trust-auto`
- **Validation post-migration** : Script automatique compare counts (seuil 5%)
- **ProtonMail Bridge fallback** : Migrer ProtonMail EN DERNIER si instable
- **Plan B Phase D** : Options si budget/duree depasse (skip entites, skip embeddings anciens, classification legere)

### Planning revise
- Jour 1 : Phase A.0 + A (10-12h)
- Jour 2 : Phase B + C (7-9h)
- Jour 3-5 : Story 2.9 dev (15-25h)
- Semaine 2-5 : Phase D progressive avec monitoring quotidien

---

**Version** : 2.3 (2026-02-12)
**Auteur** : BMad Master + Masterplan
**Review** : Adversariale v4 completee (6 corrections finales)
**Status** : PRET POUR IMPLEMENTATION

### Corrections v2.1 (2026-02-12)
1. **Migration 035 supprimee** : VIP integre directement dans migration 033 (non commitee, modifiable)
2. **--skip-first supprime** : Remplace par `--resume` (checkpoint fiable meme si ordre API change)
3. **validate_migration.py** : SDK inexistant remplace par httpx sur API REST EmailEngine
4. **Benchmark consumer** : Injection Redis Streams au lieu d'envoi vrais emails (zero pollution boites mail)

### Corrections v2.2 (2026-02-12) — Review adversariale v3
1. **Labels "COMPLETE" retires** : `migrate_emails.py` et `extract_email_domains.py` marques "A FAIRE" avec etat actuel documente
2. **Conflit migration 034 resolu** : Migration 034 reecrite (`core.llm_usage` avec `tokens_saved_by_filters`, remplace `core.api_usage` inexistante)
3. **PII retiree du plan** : Emails Antonio remplaces par reference a `.env.email.enc`
4. **Story 2.9 reestimee** : 15-25h (vs 8-12h) — 2 scripts a reecrire + 3 a creer
5. **Cout unitaire corrige** : $0.006/email (ajout extraction entites graphe via Claude, omis precedemment)
6. **Budget revise** : $700 (vs $500) — baseline $390-450, realiste $585-675
7. **validate_migration.py** : argparse au lieu de sys.argv positionnels (coherent avec commandes Phase D)
8. **Rollback donnees** : Procedure complete (re-classification, nettoyage graphe, option nucleaire)
9. **Benchmark ameliore** : Corps d'emails realistes (100-200 mots), limitation documentee, facteur correctif 0.6-0.8
10. **Sequencement corrige** : Story 2.9 ne peut pas chevaucher Phase B (API EmailEngine requise)
11. **Healthcheck ameliore** : Detection consumer zombie (last_processed_at, throughput, pending queue)
12. **Plan B Phase D** : 4 options si budget/duree depasse (blacklist agressif, skip entites, skip embeddings, stop & evaluate) — 100% Sonnet (D17)
13. **IPs Tailscale** : Remplacees par DNS Tailscale (pc-mainteneur, vps-friday)
14. **Contexte clarifie** : Status epics precis (pas "DONE" generique)
15. **ProtonMail Bridge** : Detection automatique du nom process Windows (multi-versions)

### Corrections v2.3 (2026-02-12) — Review adversariale v4
1. **Cout benchmark corrige** : $0.60 (100 x $0.006), pas $0.40 (coherent avec cout unitaire v2.2)
2. **apply_filters_from_csv** : Colonnes SQL alignees sur migration 033 (`sender_domain`/`sender_email` au lieu de `pattern`/`is_domain`)
3. **healthcheck.py** : Ajout `import time` manquant (utilise par `time.time()`)
4. **CLI --reclassify** : Parametre ajoute a la spec CLI de `migrate_emails.py` (deja reference dans rollback)
5. **Migration 034 renumerotee** : L'ancienne 034 (core.api_usage) reecrite en 034 (core.llm_usage), plus de gap 034→036
6. **Option Haiku retiree du Plan B** : 100% Sonnet conformement a D17, 4 options au lieu de 5
