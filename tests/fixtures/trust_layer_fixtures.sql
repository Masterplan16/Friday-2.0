-- Fixtures SQL pour tests Trust Layer
-- Ces données sont chargées avant les tests d'intégration

-- S'assurer que l'extension pgcrypto est disponible pour gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Correction rules d'exemple pour tests
INSERT INTO core.correction_rules (
    id,
    module,
    action_type,
    scope,
    priority,
    conditions,
    output,
    source_receipts,
    hit_count,
    active,
    created_at,
    created_by
) VALUES
-- Règle 1 : Email urgent détecté
(
    gen_random_uuid(),
    'email',
    'classify',
    'classification',
    1,
    '{"sender_contains": "@urgent.com"}'::jsonb,
    '{"category": "urgent"}'::jsonb,
    ARRAY[]::text[],
    10,
    true,
    NOW(),
    'Mainteneur'
),
-- Règle 2 : Email finance détecté
(
    gen_random_uuid(),
    'email',
    'classify',
    'classification',
    2,
    '{"subject_contains": "facture"}'::jsonb,
    '{"category": "finance"}'::jsonb,
    ARRAY[]::text[],
    5,
    true,
    NOW(),
    'Mainteneur'
),
-- Règle 3 : Email médical (trust=blocked)
(
    gen_random_uuid(),
    'email',
    'classify',
    'classification',
    3,
    '{"subject_contains": "dossier médical"}'::jsonb,
    '{"category": "medical", "trust": "blocked"}'::jsonb,
    ARRAY[]::text[],
    0,
    true,
    NOW(),
    'Mainteneur'
),
-- Règle 4 : Archiviste OCR règle générique
(
    gen_random_uuid(),
    'archiviste',
    'ocr',
    'ocr-validation',
    1,
    '{"confidence_min": 0.90}'::jsonb,
    '{"validation": "auto"}'::jsonb,
    ARRAY[]::text[],
    20,
    true,
    NOW(),
    'Mainteneur'
);
