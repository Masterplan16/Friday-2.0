# Bot Telegram Friday 2.0

**Story 1.9** - Interface utilisateur via Telegram avec support topics.

## Architecture

```
bot/
├── main.py              # Point d'entrée, connexion bot, heartbeat, graceful shutdown
├── config.py            # Chargement config telegram.yaml + envvars
├── routing.py           # Algorithme routage événements → topics
├── models.py            # Pydantic models (TelegramEvent, BotConfig, TopicConfig)
├── action_executor.py   # Exécution actions approuvées (Story 1.10)
├── handlers/
│   ├── commands.py      # /help, /start
│   ├── messages.py      # Messages texte + onboarding nouveaux membres
│   ├── callbacks.py     # Inline buttons Approve/Reject (Story 1.10)
│   ├── corrections.py   # Inline button Correct (Story 1.7/1.10)
│   ├── trust_budget_commands.py  # /confiance, /receipt, /journal, /status, /budget, /stats (Story 1.11)
│   └── formatters.py    # Helpers formatage (confidence, emoji, EUR, timestamps)
└── requirements.txt     # Dépendances Python
```

## Variables d'environnement requises

### Token Telegram (obligatoire)
```bash
TELEGRAM_BOT_TOKEN=<token>                # Via @BotFather
TELEGRAM_SUPERGROUP_ID=<chat_id>          # Chat ID du supergroup (négatif)
```

### Thread IDs des 5 topics (obligatoire)
Extraire via `scripts/extract_telegram_thread_ids.py` :
```bash
TOPIC_CHAT_PROACTIVE_ID=<thread_id>
TOPIC_EMAIL_ID=<thread_id>
TOPIC_ACTIONS_ID=<thread_id>
TOPIC_SYSTEM_ID=<thread_id>
TOPIC_METRICS_ID=<thread_id>
```

### User ID Mainteneur (obligatoire)
```bash
OWNER_USER_ID=<user_id>                 # Pour onboarding uniquement
```

### Database & Redis (obligatoire)
```bash
DATABASE_URL=postgresql://user:pass@host:5432/db
REDIS_URL=redis://user:pass@host:6379/0
```

### Config optionnelle
```bash
TELEGRAM_CONFIG_PATH=config/telegram.yaml  # Default: config/telegram.yaml
LOG_LEVEL=INFO                             # DEBUG, INFO, WARNING, ERROR
```

## Déploiement Docker

### Build
```bash
docker build -f Dockerfile.bot -t friday-bot .
```

### Run standalone
```bash
docker run -d \
  --name friday-bot \
  --env-file .env \
  --network friday-network \
  friday-bot
```

### Docker Compose (recommandé)
```bash
docker compose up -d friday-bot
```

## Fonctionnalités

### AC1: Connexion bot stable
- Retry automatique 3x avec backoff exponentiel
- Heartbeat toutes les 60s pour vérifier connexion
- Alerte System si bot down >5min
- Graceful shutdown (SIGTERM/SIGINT)

### AC2: 5 Topics spécialisés
1. **💬 Chat & Proactive** (DEFAULT) - Conversation bidirectionnelle
2. **📬 Email & Communications** - Notifications email
3. **🤖 Actions & Validations** - Actions nécessitant validation
4. **🚨 System & Alerts** - Santé système
5. **📊 Metrics & Logs** - Métriques non-critiques

### AC3: Messages texte
- Handler messages texte dans Chat & Proactive
- Stockage DB (`ingestion.telegram_messages`)
- Echo response Day 1 (intégration agent Friday = Story future)
- Split automatique messages >4096 chars

### AC4: Routing automatique
Algorithme séquentiel (ordre prioritaire):
1. Source=heartbeat/proactive → Chat & Proactive
2. Module=email/desktop_search → Email & Communications
3. Type=action.* → Actions & Validations
4. Priority=critical/warning → System & Alerts
5. Default → Metrics & Logs

### AC5: Commandes
- `/help` - Liste complète des commandes
- `/start` - Alias de /help
- `/status`, `/journal`, `/receipt`, `/confiance`, `/stats`, `/budget` - Voir Story 1.11 ci-dessous

### AC6: Onboarding
- Message d'accueil envoyé au propriétaire la première fois
- Idempotent (flag `core.user_settings.onboarding_sent`)
- Présente les 5 topics + commandes de base

### AC7: 3 modes utilisateur
Documentation uniquement (muting géré nativement par Telegram):
- **Mode Normal**: Tous topics actifs (5/5)
- **Mode Focus**: Chat + Actions + System (3/5)
- **Mode Deep Work**: System uniquement (1/5)

## Story 1.10 : Inline Buttons & Validation

### AC1-AC6 : Flow de validation Approve/Reject/Correct

Quand une action trust=`propose` est créée, le bot envoie un message dans le topic **Actions & Validations** avec des inline buttons :

```
[Approve] [Reject] [Correct]
```

**Sécurité** :
- Seul `OWNER_USER_ID` peut interagir avec les boutons (BUG-1.10.4)
- `SELECT FOR UPDATE` empêche les race conditions sur le receipt (BUG-1.10.2)
- Double-click prevention : vérifie `status='pending'` avant update
- Rate limiting logs pour tentatives non autorisées (BUG-1.10.16)

**Action Executor** :
- Whitelist de modules autorisés (`bot/action_executor.py`)
- Exécute uniquement les actions approuvées avec `status='approved'`
- Erreurs capturées → `status='error'` avec message dans payload

**Timeout** :
- Configurable via `config/telegram.yaml` → `validation_timeout_hours`
- `null` = pas de timeout (défaut Day 1)
- Cron `services/metrics/expire_validations.py` pour expirer les pending

**Migration DB** :
- `017_action_receipts_extended_status.sql` ajoute statuts `expired` et `error`

## Story 1.11 : Commandes Telegram Trust & Budget

### AC1-AC7 : 6 commandes de consultation

Toutes les commandes supportent le flag `-v` (verbose) pour afficher des détails supplémentaires.

**`/confiance`** - Tableau accuracy par module/action (AC1)
- Affiche accuracy, total actions, confiance moyenne, trust level
- `-v` : ajoute colonnes `recommended_trust_level` et alertes rétrogradation

**`/receipt <id>`** - Détail complet d'une action (AC2)
- Accepte UUID complet ou préfixe (>=8 chars hex)
- Affiche input/output summary, confidence, reasoning, timestamps
- `-v` : détail des sous-étapes (steps)

**`/journal`** - 20 dernières actions (AC3)
- Liste chronologique inversée avec status emoji, module, action, confidence
- `-v` : ajoute input_summary et reasoning

**`/status`** - Dashboard temps réel (AC4)
- Health checks : PostgreSQL (ping), Redis (PING), Bot (uptime)
- Dernières 5 actions, alertes trust pending
- `-v` : détail uptime + compteurs actions

**`/budget`** - Consommation API Claude du mois (AC5)
- Tokens input/output, coût estimé EUR, % budget mensuel (45 EUR)
- Taux USD/EUR configurable via `USD_EUR_RATE` envvar (défaut: 0.92)
- `-v` : détail coût par catégorie (input vs output)

**`/stats`** - Métriques globales agrégées (AC6)
- Total actions, accuracy moyenne, répartition par trust level
- Top 3 modules par volume, corrections récentes
- `-v` : détail par module

**Helpers formatage** (`bot/handlers/formatters.py`) :
- `format_confidence()` - Barre emoji + pourcentage
- `format_status_emoji()` - Mapping 8 statuts → emoji
- `format_timestamp()` - Format relatif (il y a Xmin/Xh/Xj)
- `format_eur()` - Montant EUR avec séparateur décimal
- `truncate_text()` - Tronque avec ellipsis
- `parse_verbose_flag()` - Détecte `-v`/`--verbose` dans args

**Migration DB** :
- `018_trust_metrics_missing_columns.sql` ajoute `avg_confidence`, `last_trust_change_at`, `recommended_trust_level` à `core.trust_metrics`

## Tests

### Unitaires
```bash
pytest tests/unit/bot/ -v
```

**Coverage minimale** : 80% sur bot/ directory

**Tests critiques** :
- `test_routing.py` - 6 tests routing (1 par topic + 1 edge case)
- `test_config.py` - 4 tests config loading + validation
- `test_commands.py` - 3 tests /help, /start, vérification stubs supprimés
- `test_callbacks.py` - 13 tests approve/reject/sécurité (Story 1.10)
- `test_action_executor.py` - 5 tests exécution actions (Story 1.10)
- `test_expire_validations.py` - 6 tests timeout (Story 1.10)
- `test_validation_flow.py` - 4 tests flow end-to-end (Story 1.10)
- `test_trust_budget_commands.py` - 18 tests 6 commandes consultation (Story 1.11)
- `test_formatters.py` - 21 tests helpers formatage (Story 1.11)

### Intégration
```bash
pytest tests/integration/bot/ -v
```

**Tests** :
- `test_message_flow.py` - Message reçu → stocké DB → loggé
- `test_reconnection.py` - Reconnexion automatique après déconnexion

### E2E
```bash
./tests/e2e/test_telegram_bot_e2e.sh
```

**Checklist manuelle** :
1. Envoyer "Hello Friday" dans Chat & Proactive
2. Vérifier réponse "Echo: Hello Friday"
3. /help affiche liste commandes
4. Onboarding message reçu (si premier join)

## Troubleshooting

### Bot ne démarre pas
- Vérifier toutes les envvars requises présentes
- Vérifier token Telegram valide
- Vérifier bot est admin dans supergroup avec droits `can_post_messages` + `can_manage_topics`

### Bot crash au démarrage
- Vérifier PostgreSQL accessible
- Vérifier Redis accessible
- Vérifier migrations DB appliquées (tables `core.user_settings`, `ingestion.telegram_messages`)

### Messages pas stockés en DB
- Vérifier `DATABASE_URL` correcte
- Vérifier table `ingestion.telegram_messages` existe
- Vérifier logs bot pour erreurs PostgreSQL

### Onboarding pas envoyé
- Vérifier `OWNER_USER_ID` est défini
- Vérifier handler `handle_new_member` enregistré (check logs "Handlers enregistrés")
- Vérifier user_id correspond bien au propriétaire

### Heartbeat échoue
- Vérifier connexion Internet VPS
- Vérifier token Telegram toujours valide
- Vérifier logs pour "Heartbeat échec"

## Bugs connus fixés

### Story 1.9
Voir story 1.9 pour liste complète des 15 bugs identifiés et corrigés.

**Priorités P0 (bloquants)** :
- BUG-1.9.1: Token invalide détecté au démarrage
- BUG-1.9.2: Retry connexion implémenté
- BUG-1.9.6: Validation config complète
- BUG-1.9.8: Rate limiting (TODO Story future)

### Story 1.10
Voir story 1.10 pour liste complète des 16 bugs identifiés et corrigés.

**Bugs corrigés** :
- BUG-1.10.1: Validation callback_data <64 bytes
- BUG-1.10.2: SELECT FOR UPDATE (race conditions)
- BUG-1.10.4: Vérification OWNER_USER_ID obligatoire
- BUG-1.10.6: Truncate reasoning >500 chars
- BUG-1.10.7: Validation confidence 0.0-1.0
- BUG-1.10.8: Escape markdown special chars
- BUG-1.10.9: Whitelist modules dans ActionExecutor
- BUG-1.10.10: Lock receipt avant exécution
- BUG-1.10.11/12: Status='error' avec message payload
- BUG-1.10.13: Timeout null = pas d'expiration
- BUG-1.10.16: Rate limiting logs unauthorized

### Story 1.11
Voir story 1.11 pour liste complète des 5 bugs identifiés et corrigés.

**Bugs corrigés** :
- BUG-1.11.1: avg_confidence absent de trust_metrics (migration 018)
- BUG-1.11.2: last_trust_change_at absent de trust_metrics (migration 018)
- BUG-1.11.3: Pas de tracking tokens API (message graceful)
- BUG-1.11.4: confidence non bornée (validée 0.0-1.0 par Pydantic)
- BUG-1.11.5: Taux USD/EUR hardcodé (configurable via envvar)

## Références

- [Architecture addendum §11](_docs/architecture-addendum-20260205.md) - Stratégie Topics
- [Telegram User Guide](../docs/telegram-user-guide.md) - Guide utilisateur
- [Telegram Topics Setup](../docs/telegram-topics-setup.md) - Setup manuel
- [Story 1.9](../_bmad-output/implementation-artifacts/1-9-bot-telegram-core-topics.md) - Requirements bot core
- [Story 1.10](../_bmad-output/implementation-artifacts/1-10-bot-telegram-inline-buttons-validation.md) - Requirements inline buttons
- [Story 1.11](../_bmad-output/implementation-artifacts/1-11-commandes-telegram-trust-budget.md) - Requirements commandes trust & budget
