-- ============================================================
-- Migration 039: Heartbeat Metrics Table
-- ============================================================
-- Story: 4.1 - Task 8
-- Date: 2026-02-16
-- Description: Table pour metrics cycles Heartbeat Engine
--              Permet calcul silence_rate (AC4) et monitoring
-- ============================================================

BEGIN;

-- 1. Créer table core.heartbeat_metrics
CREATE TABLE IF NOT EXISTS core.heartbeat_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Timestamp cycle
    cycle_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Checks sélectionnés par LLM
    checks_selected TEXT[] NOT NULL DEFAULT '{}',

    -- Metrics exécution
    checks_executed INT NOT NULL DEFAULT 0,
    checks_notified INT NOT NULL DEFAULT 0,

    -- LLM decision reasoning
    llm_decision_reasoning TEXT,

    -- Performance
    duration_ms INT NOT NULL DEFAULT 0,

    -- Erreur si cycle crash
    error TEXT,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Index pour queries fréquentes
CREATE INDEX idx_heartbeat_metrics_timestamp
ON core.heartbeat_metrics(cycle_timestamp DESC);

-- 3. Index pour calcul silence_rate (AC4)
-- Filter index : cycles avec notifications (pour calcul rapide)
CREATE INDEX idx_heartbeat_metrics_notified
ON core.heartbeat_metrics(checks_notified)
WHERE checks_notified > 0;

-- 4. Commentaires
COMMENT ON TABLE core.heartbeat_metrics IS
'Metrics cycles Heartbeat Engine (Story 4.1). Permet calcul silence_rate (target >=80%) et monitoring performance.';

COMMENT ON COLUMN core.heartbeat_metrics.checks_selected IS
'IDs checks sélectionnés par LLM décideur ce cycle.';

COMMENT ON COLUMN core.heartbeat_metrics.checks_executed IS
'Nombre checks réellement exécutés (peut être < checks_selected si erreurs).';

COMMENT ON COLUMN core.heartbeat_metrics.checks_notified IS
'Nombre notifications Telegram envoyées (silence_rate = cycles avec 0 notification).';

COMMENT ON COLUMN core.heartbeat_metrics.llm_decision_reasoning IS
'Reasoning du LLM décideur pour sélection checks (ou "Fallback mode" si LLM crash).';

COMMENT ON COLUMN core.heartbeat_metrics.duration_ms IS
'Durée cycle en millisecondes (performance monitoring).';

COMMENT ON COLUMN core.heartbeat_metrics.error IS
'Message erreur si cycle crash (NULL si succès).';

-- 5. Fonction helper : calcul silence_rate sur N jours
CREATE OR REPLACE FUNCTION core.calculate_silence_rate(days INT DEFAULT 7)
RETURNS NUMERIC AS $$
BEGIN
    RETURN (
        SELECT
            ROUND(
                (COUNT(*) FILTER (WHERE checks_notified = 0)::NUMERIC / NULLIF(COUNT(*), 0)) * 100,
                2
            )
        FROM core.heartbeat_metrics
        WHERE cycle_timestamp > NOW() - (days || ' days')::INTERVAL
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION core.calculate_silence_rate(INT) IS
'Calcule silence_rate (%) sur N derniers jours. Target >=80% (AC4). Usage: SELECT core.calculate_silence_rate(7);';

-- 6. Alerte si silence_rate < 50%
-- Note: Alerte implémentée dans nightly job (services/metrics/nightly.py)
-- Pas de trigger DB pour éviter overhead

COMMIT;

-- ============================================================
-- Rollback (si nécessaire)
-- ============================================================
-- BEGIN;
-- DROP FUNCTION IF EXISTS core.calculate_silence_rate(INT);
-- DROP TABLE IF EXISTS core.heartbeat_metrics;
-- COMMIT;
