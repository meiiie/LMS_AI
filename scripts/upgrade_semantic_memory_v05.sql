-- Migration: Upgrade Semantic Memory to v0.5 - Insight Memory Engine
-- CHỈ THỊ KỸ THUẬT SỐ 23 CẢI TIẾN
-- Date: 2025-12-07

-- Add new columns for Insight Memory Engine
ALTER TABLE semantic_memories 
ADD COLUMN IF NOT EXISTS insight_category VARCHAR(50),
ADD COLUMN IF NOT EXISTS sub_topic VARCHAR(100),
ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMP DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS evolution_notes JSONB DEFAULT '[]';

-- Update existing records to have default values
UPDATE semantic_memories 
SET 
    last_accessed = COALESCE(last_accessed, created_at),
    evolution_notes = COALESCE(evolution_notes, '[]'::jsonb)
WHERE last_accessed IS NULL OR evolution_notes IS NULL;

-- Create index for last_accessed queries (for FIFO eviction)
CREATE INDEX IF NOT EXISTS idx_semantic_memories_last_accessed 
ON semantic_memories(user_id, last_accessed DESC);

-- Create index for category queries (for prioritized retrieval)
CREATE INDEX IF NOT EXISTS idx_semantic_memories_category 
ON semantic_memories(user_id, insight_category);

-- Create composite index for efficient category + last_accessed queries
CREATE INDEX IF NOT EXISTS idx_semantic_memories_category_accessed 
ON semantic_memories(user_id, insight_category, last_accessed DESC);

-- Add comment to track version
COMMENT ON TABLE semantic_memories IS 'Semantic Memory v0.5 - Insight Memory Engine (CHỈ THỊ 23 CẢI TIẾN)';
