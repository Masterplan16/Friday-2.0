-- Migration 003: Core configuration tables
-- Date: 2026-02-05
-- Description: Configuration système, jobs, audit

BEGIN;

-- Table configuration clé/valeur
CREATE TABLE core.config (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER config_updated_at
    BEFORE UPDATE ON core.config
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE core.config IS 'Configuration système clé/valeur (JSON)';

-- Table jobs/tasks (pour n8n et workflows)
CREATE TABLE core.tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}',
    result JSONB,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tasks_status ON core.tasks(status);
CREATE INDEX idx_tasks_type ON core.tasks(type);
CREATE INDEX idx_tasks_scheduled_at ON core.tasks(scheduled_at) WHERE scheduled_at IS NOT NULL;
CREATE INDEX idx_tasks_created_at ON core.tasks(created_at DESC);

CREATE TRIGGER tasks_updated_at
    BEFORE UPDATE ON core.tasks
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE core.tasks IS 'Jobs/tasks (workflows n8n, agents, pipelines)';

-- Table events (Redis Streams persistence backup)
CREATE TABLE core.events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    source VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_type ON core.events(event_type);
CREATE INDEX idx_events_created_at ON core.events(created_at DESC);
CREATE INDEX idx_events_source ON core.events(source);

COMMENT ON TABLE core.events IS 'Events log (backup persistence Redis Streams)';

-- Table audit log
CREATE TABLE core.audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES core.users(id),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100),
    entity_id VARCHAR(255),
    changes JSONB,
    metadata JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_user_id ON core.audit_log(user_id);
CREATE INDEX idx_audit_action ON core.audit_log(action);
CREATE INDEX idx_audit_created_at ON core.audit_log(created_at DESC);

COMMENT ON TABLE core.audit_log IS 'Audit trail (actions utilisateurs, modifications système)';

COMMIT;
