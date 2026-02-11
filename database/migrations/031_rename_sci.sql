-- Migration 031: Rename SCI account types to explicit names
-- Date: 2026-02-11
-- Description: Rename sci_1 → sci_ravas, sci_2 → sci_malbosc

BEGIN;

-- Drop existing CHECK constraint
ALTER TABLE knowledge.financial_accounts DROP CONSTRAINT IF EXISTS financial_accounts_account_type_check;

-- Update existing data (if any)
UPDATE knowledge.financial_accounts SET account_type = 'sci_ravas' WHERE account_type = 'sci_1';
UPDATE knowledge.financial_accounts SET account_type = 'sci_malbosc' WHERE account_type = 'sci_2';

-- Recreate CHECK constraint with new values
ALTER TABLE knowledge.financial_accounts
ADD CONSTRAINT financial_accounts_account_type_check
CHECK (account_type IN ('selarl', 'scm', 'sci_ravas', 'sci_malbosc', 'personal'));

-- Update comment
COMMENT ON TABLE knowledge.financial_accounts IS 'Comptes financiers (5 périmètres: SELARL, SCM, SCI Ravas, SCI Malbosc, Perso)';

COMMIT;
