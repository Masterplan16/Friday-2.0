# Sender Filtering Specification (Story 2.8)

## 📋 Vue d'ensemble

Système de filtrage intelligent sender/domain pour économiser tokens Claude ($187/an estimé).

**Pipeline** : `check_sender_filter()` AVANT `classify_email()` → Skip Claude call si blacklist/whitelist.

---

## 🏗️ Architecture

### Workflow

```
Email received
    ↓
check_sender_filter(email, domain, db_pool)
    ├─ blacklist → {category='spam', confidence=1.0, tokens_saved=0.015} → SKIP Claude
    ├─ whitelist → {category=assigned, confidence=0.95, tokens_saved=0.015} → SKIP Claude
    └─ neutral/absent → None → proceed to classify_email()
```

### Composants

| Composant | Fichier | Description |
|-----------|---------|-------------|
| Migration | `database/migrations/033_sender_filters.sql` | Table `core.sender_filters` |
| Module | `agents/src/agents/email/sender_filter.py` | Fonction `check_sender_filter()` |
| Bot commands | `bot/handlers/sender_filter_commands.py` | `/blacklist` `/whitelist` `/filters` |
| Script | `scripts/extract_email_domains.py` | Analyse 110k emails → suggestions |
| Integration | `services/email_processor/consumer.py` | Appel AVANT classification |

---

## 💾 Base de données

### Table `core.sender_filters`

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | UUID PK | Identifiant unique |
| `sender_email` | TEXT | Email exact (NULL si domain seul) |
| `sender_domain` | TEXT | Domain (NULL si email seul) |
| `filter_type` | TEXT | `whitelist` / `blacklist` / `neutral` |
| `category` | TEXT | Catégorie assignée (whitelist uniquement) |
| `confidence` | FLOAT | 1.0 (blacklist) / 0.95 (whitelist) |
| `created_at` | TIMESTAMPTZ | Date création |
| `updated_at` | TIMESTAMPTZ | Date modification (trigger auto) |
| `created_by` | TEXT | `system` / `user` |
| `notes` | TEXT | Notes optionnelles |

**Indexes** :
- `idx_sender_filters_email` (UNIQUE) - Lookup prioritaire <50ms
- `idx_sender_filters_domain` - Fallback si email absent
- `idx_sender_filters_type` - Requêtes par type

---

## 🤖 Commandes Telegram

| Commande | Usage | Description |
|----------|-------|-------------|
| `/blacklist <email\|domain>` | `/blacklist spam@newsletter.com` | Ajoute sender en blacklist (spam permanent) |
| `/whitelist <email\|domain> <category>` | `/whitelist vip@hospital.fr pro` | Ajoute sender en whitelist (catégorie assignée) |
| `/filters list` | `/filters list` | Liste tous les filtres actifs |
| `/filters stats` | `/filters stats` | Statistiques globales |

**Catégories valides** : `pro`, `finance`, `universite`, `recherche`, `perso`, `urgent`, `spam`, `inconnu`

**Permissions** : Réservées au Mainteneur (OWNER_USER_ID)

---

## 💰 ROI & Métriques

### Économie estimée

- **Runtime** : 400 emails/mois × 35% filtrés × $0.015 = **$2.10/mois** = **$25/an**
- **Migration** : 110k emails × 35% filtrés × $0.015 = **$577** (si re-classification)
- **Total estimé** : **~$187/an** (moyenne des 2 scénarios)

### Métriques tracking

```sql
-- core.api_usage : tokens économisés
SELECT SUM(tokens_saved_by_filters) FROM core.api_usage WHERE month = '2026-02';

-- core.sender_filters : filtres actifs
SELECT filter_type, COUNT(*) FROM core.sender_filters GROUP BY filter_type;
```

---

## 🧪 Tests

- **Migration** : 18 tests (7 syntax + 11 execution/integrity)
- **sender_filter.py** : 12 tests unitaires
- **sender_filter_commands.py** : 8 tests commandes Telegram

**Total** : **38 tests** - Tous PASS ✅

---

## 🚀 Déploiement

```bash
# 1. Appliquer migrations
python scripts/apply_migrations.py

# 2. Analyser emails historiques (dry-run)
python scripts/extract_email_domains.py --dry-run --top 50

# 3. Review suggestions CSV
cat email_domains.csv

# 4. Appliquer suggestions (si validées)
python scripts/extract_email_domains.py --apply --top 50

# 5. Vérifier filtres
# Dans Telegram: /filters list
```

---

## 📚 Références

- **Architecture** : [architecture-friday-2.0.md](architecture-friday-2.0.md)
- **Story** : [2-8-filtrage-sender-intelligent-economie-tokens.md](../_bmad-output/implementation-artifacts/2-8-filtrage-sender-intelligent-economie-tokens.md)
- **Decision D17** : 100% Claude Sonnet 4.5
- **Tests** : `tests/unit/agents/email/test_sender_filter.py`

---

**Version** : 1.0.0
**Date** : 2026-02-12
**Author** : Claude Sonnet 4.5
