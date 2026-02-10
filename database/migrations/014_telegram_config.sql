-- Migration 014: Telegram Configuration
-- Story 1.9 - Table configuration topics Telegram

BEGIN;

-- =====================================================================
-- Table: core.telegram_config
-- =====================================================================
-- Stocke le mapping entre les noms de topics et leurs thread IDs
-- dans le supergroup Telegram Friday 2.0 Control.

CREATE TABLE IF NOT EXISTS core.telegram_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    supergroup_id BIGINT NOT NULL,
    topic_name TEXT NOT NULL,
    topic_key TEXT NOT NULL,  -- Clé technique (ex: "chat_proactive")
    thread_id INTEGER NOT NULL CHECK (thread_id > 0),
    icon TEXT,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(topic_key),
    UNIQUE(thread_id)
);

-- Index pour recherche par topic_key (utilisé fréquemment par routing)
CREATE INDEX IF NOT EXISTS idx_telegram_config_topic_key
ON core.telegram_config(topic_key);

-- Index pour recherche par thread_id (lookup inverse)
CREATE INDEX IF NOT EXISTS idx_telegram_config_thread_id
ON core.telegram_config(thread_id);

-- Commentaires
COMMENT ON TABLE core.telegram_config IS 'Configuration des topics Telegram (mapping nom -> thread_id)';
COMMENT ON COLUMN core.telegram_config.supergroup_id IS 'Chat ID du supergroup Friday 2.0 Control (negatif)';
COMMENT ON COLUMN core.telegram_config.topic_name IS 'Nom affiche du topic (ex: "Chat & Proactive")';
COMMENT ON COLUMN core.telegram_config.topic_key IS 'Cle technique unique (ex: "chat_proactive")';
COMMENT ON COLUMN core.telegram_config.thread_id IS 'Thread ID du topic dans Telegram (>0)';
COMMENT ON COLUMN core.telegram_config.icon IS 'Emoji/icon du topic (ex: icon)';
COMMENT ON COLUMN core.telegram_config.description IS 'Description du role du topic';

-- =====================================================================
-- Données initiales (5 topics) - DÉSACTIVÉ
-- =====================================================================
-- CRIT-6 fix + HIGH-8 fix: Données invalides (thread_id fictifs 1-5, supergroup_id=0)
-- Les thread_id réels DOIVENT être extraits via script extract_telegram_thread_ids.py
-- et insérés depuis les variables d'environnement au démarrage du bot.
--
-- INSERT désactivé pour éviter pollution DB avec données invalides.
-- Le bot chargera les thread_id depuis les envvars (TOPIC_*_ID).
--
-- Exemple d'insertion manuelle après extraction:
-- INSERT INTO core.telegram_config (supergroup_id, topic_name, topic_key, thread_id, icon, description)
-- VALUES
--     (-1001234567890, 'Chat & Proactive', 'chat_proactive', 42, 'ICON', 'Conversation bidirectionnelle avec owner, heartbeat, reminders'),
--     (-1001234567890, 'Email & Communications', 'email', 43, 'ICON', 'Notifications email: classifications, PJ, emails urgents'),
--     (-1001234567890, 'Actions & Validations', 'actions', 44, 'ICON', 'Actions necessitant validation (trust=propose), inline buttons'),
--     (-1001234567890, 'System & Alerts', 'system', 45, 'ICON', 'Sante systeme: RAM >85%, services down, erreurs critiques'),
--     (-1001234567890, 'Metrics & Logs', 'metrics', 46, 'ICON', 'Metriques non-critiques: actions auto, stats, logs')
-- ON CONFLICT (topic_key) DO UPDATE SET thread_id = EXCLUDED.thread_id, updated_at = NOW();

-- =====================================================================
-- Table: ingestion.telegram_messages
-- =====================================================================
-- Stocke tous les messages reçus depuis Telegram pour historique et debugging.

CREATE TABLE IF NOT EXISTS ingestion.telegram_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    thread_id INTEGER,  -- NULL si message dans General topic
    message_id INTEGER NOT NULL,
    text TEXT,
    sent_at TIMESTAMPTZ NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour recherche par user_id + sent_at (queries fréquentes)
CREATE INDEX IF NOT EXISTS idx_telegram_messages_user_sent_at
ON ingestion.telegram_messages(user_id, sent_at DESC);

-- Index pour recherche par processed (queue processing)
CREATE INDEX IF NOT EXISTS idx_telegram_messages_processed
ON ingestion.telegram_messages(processed)
WHERE NOT processed;

-- Commentaires
COMMENT ON TABLE ingestion.telegram_messages IS 'Messages reçus depuis Telegram (historique complet)';
COMMENT ON COLUMN ingestion.telegram_messages.user_id IS 'User ID Telegram de l''expéditeur';
COMMENT ON COLUMN ingestion.telegram_messages.chat_id IS 'Chat ID (supergroup)';
COMMENT ON COLUMN ingestion.telegram_messages.thread_id IS 'Thread ID du topic (NULL si General)';
COMMENT ON COLUMN ingestion.telegram_messages.message_id IS 'Message ID unique Telegram';
COMMENT ON COLUMN ingestion.telegram_messages.text IS 'Contenu texte du message';
COMMENT ON COLUMN ingestion.telegram_messages.sent_at IS 'Horodatage du message (heure Telegram)';
COMMENT ON COLUMN ingestion.telegram_messages.processed IS 'Indique si le message a été traité par Friday';

COMMIT;
