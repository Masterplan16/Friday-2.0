-- Migration 028: Urgency Keywords Table
-- Story 2.3: Detection VIP & Urgence
-- Date: 2026-02-11
-- Description: Table pour keywords urgence avec poids configurables.
--              Algorithme multi-facteurs : VIP (0.5) + keywords (0.3) + deadline (0.2).
--              Seed initial avec 6 keywords manuels français.

BEGIN;

-- Table urgency_keywords
CREATE TABLE IF NOT EXISTS core.urgency_keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keyword TEXT NOT NULL UNIQUE,
    weight DOUBLE PRECISION NOT NULL DEFAULT 0.3 CHECK (weight >= 0.0 AND weight <= 1.0),
    context_pattern TEXT,
    language VARCHAR(5) NOT NULL DEFAULT 'fr',
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'learned')),
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hit_count INT DEFAULT 0 CHECK (hit_count >= 0),
    last_hit_at TIMESTAMPTZ,
    active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour recherche rapide keywords actifs
CREATE INDEX IF NOT EXISTS idx_urgency_keywords_active
ON core.urgency_keywords(active, weight DESC)
WHERE active = TRUE;

-- Index pour filtrer par langue
CREATE INDEX IF NOT EXISTS idx_urgency_keywords_language
ON core.urgency_keywords(language)
WHERE active = TRUE;

-- Index pour stats par source
CREATE INDEX IF NOT EXISTS idx_urgency_keywords_source
ON core.urgency_keywords(source)
WHERE active = TRUE;

-- Commentaire table
COMMENT ON TABLE core.urgency_keywords IS
'Keywords pour détection urgence multi-facteurs. '
'Weight = poids dans calcul urgence_score (0.3 par défaut). '
'Algorithme: urgency_score = 0.5*VIP + 0.3*keywords + 0.2*deadline. '
'Seuil urgence: score >= 0.6.';

-- Commentaires colonnes
COMMENT ON COLUMN core.urgency_keywords.id IS 'Identifiant unique UUID';
COMMENT ON COLUMN core.urgency_keywords.keyword IS 'Mot-clé urgence (case-insensitive match)';
COMMENT ON COLUMN core.urgency_keywords.weight IS 'Poids dans calcul score (0.0-1.0, défaut 0.3)';
COMMENT ON COLUMN core.urgency_keywords.context_pattern IS 'Pattern regex optionnel pour affiner contexte';
COMMENT ON COLUMN core.urgency_keywords.language IS 'Langue du keyword (fr, en, etc.)';
COMMENT ON COLUMN core.urgency_keywords.source IS 'Source: manual (seed) ou learned (apprentissage)';
COMMENT ON COLUMN core.urgency_keywords.hit_count IS 'Nombre de détections avec ce keyword';
COMMENT ON COLUMN core.urgency_keywords.last_hit_at IS 'Date de dernière détection';
COMMENT ON COLUMN core.urgency_keywords.active IS 'Soft delete (FALSE = keyword désactivé)';

-- Trigger pour updated_at
CREATE OR REPLACE FUNCTION core.update_urgency_keywords_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_urgency_keywords_updated_at
BEFORE UPDATE ON core.urgency_keywords
FOR EACH ROW
EXECUTE FUNCTION core.update_urgency_keywords_updated_at();

-- Seed initial : 6 keywords manuels français
INSERT INTO core.urgency_keywords
    (keyword, weight, language, source)
VALUES
    ('URGENT', 0.4, 'fr', 'manual'),
    ('urgent', 0.3, 'fr', 'manual'),
    ('deadline', 0.3, 'fr', 'manual'),
    ('délai', 0.3, 'fr', 'manual'),
    ('échéance', 0.3, 'fr', 'manual'),
    ('avant demain', 0.4, 'fr', 'manual'),
    ('aujourd''hui', 0.2, 'fr', 'manual'),
    ('ce soir', 0.3, 'fr', 'manual'),
    ('immédiat', 0.4, 'fr', 'manual'),
    ('prioritaire', 0.3, 'fr', 'manual')
ON CONFLICT (keyword) DO NOTHING;

COMMIT;
