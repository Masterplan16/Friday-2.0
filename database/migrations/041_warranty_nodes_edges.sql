-- Migration 041: Helper function for warranty reminder nodes
-- Story 3.4 - Suivi Garanties (knowledge graph integration)
-- Date: 2026-02-16
--
-- Creates helper function for creating knowledge graph nodes
-- linked to warranty records.
--
-- Rollback:
--   DROP FUNCTION IF EXISTS knowledge.create_warranty_reminder_node(UUID, VARCHAR, DATE);

BEGIN;

-- Fonction helper création node garantie (knowledge graph)
CREATE OR REPLACE FUNCTION knowledge.create_warranty_reminder_node(
    p_warranty_id UUID,
    p_item_name VARCHAR,
    p_expiration_date DATE
) RETURNS UUID AS $$
DECLARE
    v_node_id UUID;
BEGIN
    INSERT INTO knowledge.nodes (type, name, metadata, source)
    VALUES (
        'reminder',
        'Garantie: ' || p_item_name || ' - expire ' || p_expiration_date::TEXT,
        jsonb_build_object(
            'warranty_id', p_warranty_id,
            'expiration_date', p_expiration_date
        ),
        'archiviste'
    )
    RETURNING id INTO v_node_id;

    RETURN v_node_id;
END;
$$ LANGUAGE plpgsql;

COMMIT;
