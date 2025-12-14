-- Migration: Add contextual_content column to knowledge_embeddings
-- Feature: contextual-rag (Anthropic-style Context Enrichment)
-- Date: 2024-12-14
-- 
-- This column stores LLM-generated context for each chunk.
-- The context is prepended to the original content for better embeddings.
-- This provides ~49% improvement in retrieval accuracy (per Anthropic research).

-- Add contextual_content column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'knowledge_embeddings' 
        AND column_name = 'contextual_content'
    ) THEN
        ALTER TABLE knowledge_embeddings 
        ADD COLUMN contextual_content TEXT DEFAULT NULL;
        
        -- Add comment for documentation
        COMMENT ON COLUMN knowledge_embeddings.contextual_content IS 
            'LLM-generated context prepended to chunk for better retrieval (Contextual RAG)';
        
        RAISE NOTICE 'Added contextual_content column to knowledge_embeddings';
    ELSE
        RAISE NOTICE 'Column contextual_content already exists';
    END IF;
END $$;

-- Verify the column was added
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns 
WHERE table_name = 'knowledge_embeddings' 
AND column_name = 'contextual_content';
