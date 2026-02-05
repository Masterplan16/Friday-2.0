-- Migration 006: Ingestion media (audio, photos)
-- Date: 2026-02-05
-- Description: Notes Plaud, photos BeeStation

BEGIN;

-- Table audio notes (Plaud Note)
CREATE TABLE ingestion.audio_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename VARCHAR(500) NOT NULL,
    storage_path TEXT NOT NULL,
    duration_seconds INTEGER,
    file_size_bytes BIGINT,
    transcription TEXT,
    transcription_confidence FLOAT,
    language VARCHAR(10) DEFAULT 'fr-FR',
    detected_actions JSONB DEFAULT '[]',
    detected_events JSONB DEFAULT '[]',
    detected_thesis_notes JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    recorded_at TIMESTAMPTZ,
    transcribed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audio_recorded_at ON ingestion.audio_notes(recorded_at DESC);
CREATE INDEX idx_audio_transcribed_at ON ingestion.audio_notes(transcribed_at) WHERE transcribed_at IS NOT NULL;

COMMENT ON TABLE ingestion.audio_notes IS 'Notes audio Plaud (transcription + extraction actions)';

-- Table photos (BeeStation via PC)
CREATE TABLE ingestion.photos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename VARCHAR(500) NOT NULL,
    storage_path TEXT NOT NULL,
    storage_location VARCHAR(20) NOT NULL DEFAULT 'pc' CHECK (storage_location IN ('vps', 'pc', 'beestation')),
    file_size_bytes BIGINT,
    mime_type VARCHAR(100),
    checksum VARCHAR(64) UNIQUE,
    width_px INTEGER,
    height_px INTEGER,
    exif_data JSONB,
    detected_objects JSONB DEFAULT '[]',
    detected_faces INTEGER DEFAULT 0,
    tags TEXT[],
    caption TEXT,
    taken_at TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_photos_checksum ON ingestion.photos(checksum);
CREATE INDEX idx_photos_taken_at ON ingestion.photos(taken_at DESC) WHERE taken_at IS NOT NULL;
CREATE INDEX idx_photos_tags ON ingestion.photos USING GIN(tags);

COMMENT ON TABLE ingestion.photos IS 'Photos BeeStation (indexation, recherche sémantique)';

COMMIT;
