-- Migration 010: Knowledge finance tracking
-- Date: 2026-02-05
-- Description: Transactions, budgets, anomalies (5 périmètres)

BEGIN;

CREATE TABLE knowledge.financial_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_name VARCHAR(255) NOT NULL,
    account_type VARCHAR(50) NOT NULL CHECK (account_type IN ('bank', 'sas', 'eurl', 'sci', 'personal')),
    institution VARCHAR(255),
    account_number VARCHAR(100),
    currency VARCHAR(3) DEFAULT 'EUR',
    initial_balance DECIMAL(15, 2),
    current_balance DECIMAL(15, 2),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_accounts_type ON knowledge.financial_accounts(account_type);

CREATE TRIGGER accounts_updated_at
    BEFORE UPDATE ON knowledge.financial_accounts
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE knowledge.financial_accounts IS 'Comptes financiers (5 périmètres: perso, SAS, EURL, SCI, SCM)';

-- Table transactions
CREATE TABLE knowledge.financial_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES knowledge.financial_accounts(id) ON DELETE CASCADE,
    transaction_date DATE NOT NULL,
    amount DECIMAL(15, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'EUR',
    category VARCHAR(100),
    subcategory VARCHAR(100),
    description TEXT NOT NULL,
    counterparty VARCHAR(500),
    transaction_type VARCHAR(20) NOT NULL CHECK (transaction_type IN ('debit', 'credit', 'transfer')),
    payment_method VARCHAR(50),
    is_duplicate BOOLEAN DEFAULT false,
    duplicate_of_id UUID REFERENCES knowledge.financial_transactions(id),
    anomaly_detected BOOLEAN DEFAULT false,
    anomaly_type VARCHAR(100),
    confidence FLOAT,
    document_id UUID REFERENCES ingestion.documents(id),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_transactions_account ON knowledge.financial_transactions(account_id);
CREATE INDEX idx_transactions_date ON knowledge.financial_transactions(transaction_date DESC);
CREATE INDEX idx_transactions_category ON knowledge.financial_transactions(category);
CREATE INDEX idx_transactions_anomaly ON knowledge.financial_transactions(anomaly_detected) WHERE anomaly_detected = true;
CREATE INDEX idx_transactions_duplicate ON knowledge.financial_transactions(is_duplicate) WHERE is_duplicate = true;

CREATE TRIGGER transactions_updated_at
    BEFORE UPDATE ON knowledge.financial_transactions
    FOR EACH ROW
    EXECUTE FUNCTION core.update_updated_at();

COMMENT ON TABLE knowledge.financial_transactions IS 'Transactions financières (classification + détection anomalies)';
COMMENT ON COLUMN knowledge.financial_transactions.is_duplicate IS 'Transaction dupliquée (détection auto via montant/date/description)';
COMMENT ON COLUMN knowledge.financial_transactions.anomaly_detected IS 'Anomalie détectée (abonnement oublié, charge anormale, etc.)';

COMMIT;
