-- Migration: Remove embedding column from entity_search table
ALTER TABLE entity_search DROP COLUMN IF EXISTS embedding;
