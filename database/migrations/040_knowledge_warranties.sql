-- Migration 040: knowledge.warranties + knowledge.warranty_alerts
-- Story 3.4 - Suivi Garanties
-- Date: 2026-02-16
--
-- Tables:
--   knowledge.warranties - Garanties actives/expirées avec lien document
--   knowledge.warranty_alerts - Tracking alertes envoyées (anti-spam)
--
-- Rollback:
--   DROP TABLE IF EXISTS knowledge.warranty_alerts CASCADE;
--   DROP TABLE IF EXISTS knowledge.warranties CASCADE;

BEGIN;

-- Table warranties principale
CREATE TABLE knowledge.warranties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_name VARCHAR(500) NOT NULL,
    item_category VARCHAR(100) NOT NULL,
    vendor VARCHAR(255),
    purchase_date DATE NOT NULL,
    warranty_duration_months INT NOT NULL CHECK (warranty_duration_months BETWEEN 1 AND 120),
    expiration_date DATE NOT NULL,
    purchase_amount DECIMAL(10, 2),
    document_id UUID REFERENCES ingestion.document_metadata(id) ON DELETE SET NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'claimed')),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT purchase_before_expiry CHECK (purchase_date < expiration_date)
);

-- Index performants pour queries fréquentes
CREATE INDEX idx_warranty_status ON knowledge.warranties(status);
CREATE INDEX idx_warranty_expiry ON knowledge.warranties(expiration_date);
CREATE INDEX idx_warranty_document ON knowledge.warranties(document_id);
CREATE INDEX idx_warranty_category ON knowledge.warranties(item_category);

-- Trigger auto-update timestamp (réutilise fonction existante migration 001)
CREATE TRIGGER update_warranty_timestamp
BEFORE UPDATE ON knowledge.warranties
FOR EACH ROW
EXECUTE FUNCTION core.update_updated_at();

-- Table tracking alertes envoyées (éviter spam)
CREATE TABLE knowledge.warranty_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    warranty_id UUID NOT NULL REFERENCES knowledge.warranties(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL CHECK (alert_type IN ('60_days', '30_days', '7_days', 'expired')),
    notified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (warranty_id, alert_type)
);

COMMIT;
