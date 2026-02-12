-- Migration 034: LLM Usage Tracking
-- Story: Epic 2 - Pipeline Email
-- Date: 2026-02-12
-- Description: Table core.llm_usage pour tracking couts LLM par appel.
--              Remplace ancienne migration 034 (ALTER TABLE core.api_usage inexistante).
--              Supporte: classification, extraction entites, embeddings, filtrage.

BEGIN;

CREATE TABLE IF NOT EXISTS core.llm_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    provider TEXT NOT NULL,       -- 'anthropic', 'voyage'
    model TEXT NOT NULL,           -- 'claude-sonnet-4-5', 'voyage-2'
    input_tokens INT,
    output_tokens INT,
    cost_usd DECIMAL(10,6),
    context TEXT,                  -- 'email_classification', 'entity_extraction', 'embeddings', 'benchmark', etc.
    email_id UUID,                 -- Reference optionnelle vers ingestion.emails(id)
    tokens_saved_by_filters INT DEFAULT 0  -- Tokens economises via filtrage sender
);

CREATE INDEX idx_llm_usage_timestamp ON core.llm_usage(timestamp);
CREATE INDEX idx_llm_usage_provider ON core.llm_usage(provider, model);
CREATE INDEX idx_llm_usage_daily ON core.llm_usage((timestamp::date));
CREATE INDEX idx_llm_usage_context ON core.llm_usage(context);

COMMENT ON TABLE core.llm_usage IS 'Tracking couts LLM par appel (classification, extraction entites, embeddings). Budget quotidien et mensuel.';

COMMIT;
