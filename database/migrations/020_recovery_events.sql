-- Migration 020: Tables pour Self-Healing (Story 1.13 - AC3, AC5, AC6)
-- Created: 2026-02-10
-- Description: Tracking recovery events et system metrics historiques

BEGIN;

-- Table core.recovery_events : Événements de recovery automatique
CREATE TABLE IF NOT EXISTS core.recovery_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,  -- 'auto_recovery_ram', 'crash_loop_detected', 'os_reboot', 'docker_restart'
    services_affected TEXT,  -- Comma-separated list ou JSON
    ram_before INTEGER,  -- RAM% avant recovery (nullable si non applicable)
    ram_after INTEGER,  -- RAM% après recovery (nullable si non applicable)
    success BOOLEAN NOT NULL DEFAULT false,  -- Recovery réussi ou échoué
    recovery_duration_seconds INTEGER,  -- Durée de la recovery (NFR13)
    notification_sent BOOLEAN DEFAULT false,  -- Notification Telegram envoyée
    error_message TEXT,  -- Message d'erreur si échec
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index sur created_at pour queries temporelles rapides
CREATE INDEX idx_recovery_events_created_at ON core.recovery_events(created_at DESC);

-- Index sur event_type pour filtrage par type
CREATE INDEX idx_recovery_events_event_type ON core.recovery_events(event_type);

-- Index sur success pour statistiques
CREATE INDEX idx_recovery_events_success ON core.recovery_events(success);

-- Table core.system_metrics : Métriques système historiques
CREATE TABLE IF NOT EXISTS core.system_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_type VARCHAR(50) NOT NULL,  -- 'ram_usage_pct', 'cpu_usage_pct', 'disk_usage_pct'
    value NUMERIC(10, 2) NOT NULL,  -- Valeur métrique (ex: 87.5)
    threshold NUMERIC(10, 2),  -- Seuil alerte (ex: 85.0)
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index sur timestamp pour queries temporelles rapides
CREATE INDEX idx_system_metrics_timestamp ON core.system_metrics(timestamp DESC);

-- Index sur metric_type pour filtrage par type
CREATE INDEX idx_system_metrics_metric_type ON core.system_metrics(metric_type);

-- Index composite pour queries par type + période
CREATE INDEX idx_system_metrics_type_timestamp ON core.system_metrics(metric_type, timestamp DESC);

-- Commentaires sur les tables
COMMENT ON TABLE core.recovery_events IS 'Événements de recovery automatique (auto-recovery RAM, crash loop, OS reboot) - Story 1.13';
COMMENT ON TABLE core.system_metrics IS 'Métriques système historiques (RAM, CPU, Disk) pour monitoring - Story 1.13';

-- Commentaires sur colonnes recovery_events
COMMENT ON COLUMN core.recovery_events.event_type IS 'Type: auto_recovery_ram, crash_loop_detected, os_reboot, docker_restart';
COMMENT ON COLUMN core.recovery_events.services_affected IS 'Liste services affectés (comma-separated ou JSON)';
COMMENT ON COLUMN core.recovery_events.ram_before IS 'RAM% avant recovery (nullable si non applicable)';
COMMENT ON COLUMN core.recovery_events.ram_after IS 'RAM% après recovery (nullable si non applicable)';
COMMENT ON COLUMN core.recovery_events.recovery_duration_seconds IS 'Durée recovery en secondes (NFR13: <120s pour RAM)';
COMMENT ON COLUMN core.recovery_events.notification_sent IS 'Notification Telegram envoyée (AC5)';

-- Commentaires sur colonnes system_metrics
COMMENT ON COLUMN core.system_metrics.metric_type IS 'Type métrique: ram_usage_pct, cpu_usage_pct, disk_usage_pct';
COMMENT ON COLUMN core.system_metrics.value IS 'Valeur métrique (pourcentage ou valeur absolue)';
COMMENT ON COLUMN core.system_metrics.threshold IS 'Seuil alerte configuré pour cette métrique';

-- Vérification : Tables créées
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='core' AND table_name='recovery_events') THEN
        RAISE EXCEPTION 'Table core.recovery_events not created';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='core' AND table_name='system_metrics') THEN
        RAISE EXCEPTION 'Table core.system_metrics not created';
    END IF;

    RAISE NOTICE 'Migration 020: Tables recovery_events et system_metrics créées avec succès';
END $$;

COMMIT;
