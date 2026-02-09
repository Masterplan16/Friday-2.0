# Bot Telegram Friday 2.0

**Story 1.9** - Interface utilisateur via Telegram avec support topics.

## Architecture

```
bot/
├── main.py              # Point d'entrée, connexion bot, heartbeat, graceful shutdown
├── config.py            # Chargement config telegram.yaml + envvars
├── routing.py           # Algorithme routage événements → topics
├── models.py            # Pydantic models (TelegramEvent, BotConfig, TopicConfig)
├── handlers/
│   ├── commands.py      # /help, /start, stubs Story 1.11
│   ├── messages.py      # Messages texte + onboarding nouveaux membres
│   └── callbacks.py     # Inline buttons (Story 1.10)
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

### User ID Antonio (obligatoire)
```bash
ANTONIO_USER_ID=<user_id>                 # Pour onboarding uniquement Antonio
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
- Stubs Story 1.11: `/status`, `/journal`, `/receipt`, `/confiance`, `/stats`, `/budget`

### AC6: Onboarding
- Message d'accueil envoyé à Antonio la première fois
- Idempotent (flag `core.user_settings.onboarding_sent`)
- Présente les 5 topics + commandes de base

### AC7: 3 modes utilisateur
Documentation uniquement (muting géré nativement par Telegram):
- **Mode Normal**: Tous topics actifs (5/5)
- **Mode Focus**: Chat + Actions + System (3/5)
- **Mode Deep Work**: System uniquement (1/5)

## Tests

### Unitaires
```bash
pytest tests/unit/bot/ -v
```

**Coverage minimale** : 80% sur bot/ directory

**Tests critiques** :
- `test_routing.py` - 6 tests routing (1 par topic + 1 edge case)
- `test_config.py` - 4 tests config loading + validation
- `test_commands.py` - 3 tests /help, /start, stubs

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
- Vérifier `ANTONIO_USER_ID` est défini
- Vérifier handler `handle_new_member` enregistré (check logs "Handlers enregistrés")
- Vérifier user_id correspond bien à Antonio

### Heartbeat échoue
- Vérifier connexion Internet VPS
- Vérifier token Telegram toujours valide
- Vérifier logs pour "Heartbeat échec"

## Bugs connus fixés

Voir story 1.9 pour liste complète des 15 bugs identifiés et corrigés.

**Priorités P0 (bloquants)** :
- BUG-1.9.1: Token invalide détecté au démarrage ✅
- BUG-1.9.2: Retry connexion implémenté ✅
- BUG-1.9.6: Validation config complète ✅
- BUG-1.9.8: Rate limiting (TODO Story future)

## Références

- [Architecture addendum §11](_docs/architecture-addendum-20260205.md) - Stratégie Topics
- [Telegram User Guide](../docs/telegram-user-guide.md) - Guide utilisateur Antonio
- [Telegram Topics Setup](../docs/telegram-topics-setup.md) - Setup manuel
- [Story 1.9](../_bmad-output/implementation-artifacts/1-9-bot-telegram-core-topics.md) - Requirements complets
