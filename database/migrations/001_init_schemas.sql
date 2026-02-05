-- Migration 001: Init schemas (core, ingestion, knowledge)
-- Date: 2026-02-05
-- Description: Crée les 3 schemas principaux de Friday 2.0
-- JAMAIS de table dans public schema

BEGIN;

-- Créer les 3 schemas
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ingestion;
CREATE SCHEMA IF NOT EXISTS knowledge;

-- Activer extension pgcrypto (chiffrement colonnes sensibles)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Activer extension uuid-ossp (génération UUID)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Commentaires documentation
COMMENT ON SCHEMA core IS 'Configuration, jobs, audit, utilisateurs - Socle système';
COMMENT ON SCHEMA ingestion IS 'Emails, documents, fichiers, métadonnées - Zone entrée données brutes';
COMMENT ON SCHEMA knowledge IS 'Entités, relations, métadonnées embeddings - Zone sortie post-traitement IA';

COMMIT;
