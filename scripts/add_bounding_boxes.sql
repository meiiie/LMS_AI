-- Migration 006: Add bounding_boxes column to knowledge_embeddings
-- Feature: source-highlight-citation
-- Validates: Requirements 3.1, 3.2, 3.3

-- Add bounding_boxes column (JSONB for array of coordinates)
-- Format: [{"x0": 10.5, "y0": 5.2, "x1": 90.3, "y1": 8.7}, ...]
-- Coordinates are normalized to percentage (0-100) for responsive display

ALTER TABLE knowledge_embeddings 
ADD COLUMN IF NOT EXISTS bounding_boxes JSONB DEFAULT NULL;

-- Create GIN index for efficient JSONB querying
CREATE INDEX IF NOT EXISTS idx_knowledge_bounding_boxes 
ON knowledge_embeddings USING GIN(bounding_boxes);

-- Verify column was added
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'knowledge_embeddings' 
AND column_name = 'bounding_boxes';
