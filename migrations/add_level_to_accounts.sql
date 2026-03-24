-- Migration: add level column to accounts table
-- Run once against your production database.
-- Safe to run multiple times — checks for column existence first (PostgreSQL syntax).

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'accounts' AND column_name = 'level'
    ) THEN
        ALTER TABLE accounts ADD COLUMN level VARCHAR(20) DEFAULT NULL;
        RAISE NOTICE 'Column "level" added to accounts table.';
    ELSE
        RAISE NOTICE 'Column "level" already exists — skipping.';
    END IF;
END
$$;

-- Valid values: 'jhs', 'shs', 'university'
-- NULL means level was not provided (acceptable — field is optional).
