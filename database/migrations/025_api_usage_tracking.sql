-- Migration 025: API Usage Tracking (Story 6.2 - AC6)
-- Tracking pour coûts embeddings Voyage AI + autres APIs externes
-- Date: 2026-02-11

BEGIN;

-- Table: core.api_usage
-- Suivi granulaire des appels API externes (Voyage AI, Claude, etc.)
CREATE TABLE IF NOT EXISTS core.api_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identification
    service VARCHAR(50) NOT NULL,  -- 'voyage-ai', 'anthropic', 'openai', etc.
    operation VARCHAR(100) NOT NULL,  -- 'embed', 'complete', 'chat', etc.

    -- Métriques
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    tokens_total INTEGER GENERATED ALWAYS AS (tokens_input + tokens_output) STORED,

    -- Coûts (en centimes EUR)
    cost_input_cents DECIMAL(10,4) DEFAULT 0,
    cost_output_cents DECIMAL(10,4) DEFAULT 0,
    cost_total_cents DECIMAL(10,4) GENERATED ALWAYS AS (cost_input_cents + cost_output_cents) STORED,

    -- Contexte
    module VARCHAR(50),  -- 'email', 'archiviste', 'heartbeat', etc.
    story_id VARCHAR(20),  -- '6.2', '2.1', etc. (traçabilité dev)

    -- Métadonnées
    metadata JSONB DEFAULT '{}',  -- {model: 'voyage-4-large', batch: true, ...}

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour queries fréquentes
CREATE INDEX idx_api_usage_service_date ON core.api_usage(service, created_at DESC);
CREATE INDEX idx_api_usage_module ON core.api_usage(module);
CREATE INDEX idx_api_usage_created_at ON core.api_usage(created_at DESC);

-- Table: core.api_budget_limits
-- Limites mensuelles par service
CREATE TABLE IF NOT EXISTS core.api_budget_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    service VARCHAR(50) NOT NULL UNIQUE,  -- 'voyage-ai', 'anthropic', etc.

    -- Limites (en centimes EUR)
    monthly_limit_cents INTEGER NOT NULL,  -- Ex: 1500 = 15 EUR
    warning_threshold_pct INTEGER DEFAULT 80,  -- Alerte à 80%

    -- Status
    active BOOLEAN DEFAULT true,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Insertion limites initiales (Story 6.2)
INSERT INTO core.api_budget_limits (service, monthly_limit_cents, warning_threshold_pct)
VALUES
    ('voyage-ai', 1500, 80),  -- 15 EUR/mois, alerte à 12 EUR (80%)
    ('anthropic', 4500, 85)   -- 45 EUR/mois, alerte à 38.25 EUR (85%)
ON CONFLICT (service) DO NOTHING;

-- Vue agrégée: usage mensuel par service
CREATE OR REPLACE VIEW core.api_usage_monthly AS
SELECT
    service,
    DATE_TRUNC('month', created_at) AS month,
    COUNT(*) AS total_calls,
    SUM(tokens_total) AS total_tokens,
    ROUND(SUM(cost_total_cents)::NUMERIC, 2) AS total_cost_cents,
    ROUND((SUM(cost_total_cents) / 100.0)::NUMERIC, 2) AS total_cost_eur
FROM core.api_usage
GROUP BY service, DATE_TRUNC('month', created_at)
ORDER BY month DESC, service;

-- Vue: budget status actuel
CREATE OR REPLACE VIEW core.api_budget_status AS
WITH current_month AS (
    SELECT
        service,
        COALESCE(SUM(cost_total_cents), 0) AS spent_cents
    FROM core.api_usage
    WHERE created_at >= DATE_TRUNC('month', NOW())
    GROUP BY service
)
SELECT
    l.service,
    l.monthly_limit_cents,
    l.warning_threshold_pct,
    COALESCE(cm.spent_cents, 0) AS spent_cents,
    ROUND((COALESCE(cm.spent_cents, 0)::NUMERIC / l.monthly_limit_cents * 100), 1) AS usage_pct,
    (l.monthly_limit_cents - COALESCE(cm.spent_cents, 0)) AS remaining_cents,
    CASE
        WHEN COALESCE(cm.spent_cents, 0) >= l.monthly_limit_cents THEN 'EXCEEDED'
        WHEN COALESCE(cm.spent_cents, 0) >= (l.monthly_limit_cents * l.warning_threshold_pct / 100) THEN 'WARNING'
        ELSE 'OK'
    END AS status
FROM core.api_budget_limits l
LEFT JOIN current_month cm ON l.service = cm.service
WHERE l.active = true
ORDER BY usage_pct DESC;

-- Fonction: enregistrer usage API
CREATE OR REPLACE FUNCTION core.log_api_usage(
    p_service VARCHAR,
    p_operation VARCHAR,
    p_tokens_input INTEGER DEFAULT 0,
    p_tokens_output INTEGER DEFAULT 0,
    p_cost_input_cents DECIMAL DEFAULT 0,
    p_cost_output_cents DECIMAL DEFAULT 0,
    p_module VARCHAR DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'
) RETURNS UUID AS $$
DECLARE
    v_usage_id UUID;
BEGIN
    INSERT INTO core.api_usage (
        service,
        operation,
        tokens_input,
        tokens_output,
        cost_input_cents,
        cost_output_cents,
        module,
        metadata
    ) VALUES (
        p_service,
        p_operation,
        p_tokens_input,
        p_tokens_output,
        p_cost_input_cents,
        p_cost_output_cents,
        p_module,
        p_metadata
    )
    RETURNING id INTO v_usage_id;

    RETURN v_usage_id;
END;
$$ LANGUAGE plpgsql;

-- Trigger: update timestamp api_budget_limits
CREATE OR REPLACE FUNCTION core.update_api_budget_limits_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_api_budget_limits_updated_at
    BEFORE UPDATE ON core.api_budget_limits
    FOR EACH ROW
    EXECUTE FUNCTION core.update_api_budget_limits_timestamp();

COMMIT;

-- Migration 025 completed successfully
-- Prochaines étapes:
--   → Subtask 6.2: Intégrer tracking dans vectorstore.py
--   → Subtask 6.3: Budget monitor + alertes Telegram
--   → Subtask 6.4: Commande Telegram /budget
