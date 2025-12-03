-- =============================================================================
-- SEMANTIC MEMORY SCHEMA v0.3
-- Maritime AI Tutor - CHỈ THỊ KỸ THUẬT SỐ 06
-- =============================================================================
-- Run this script in Supabase SQL Editor
-- Prerequisites: pgvector extension must be available in your Supabase project
-- =============================================================================

-- Enable pgvector extension (required for vector operations)
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- SEMANTIC MEMORIES TABLE
-- Stores conversation memories with vector embeddings for semantic search
-- Uses Gemini embedding-001 with MRL 768 dimensions
-- =============================================================================

CREATE TABLE IF NOT EXISTS semantic_memories (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- User identification (from LMS)
    user_id VARCHAR(255) NOT NULL,
    
    -- Memory content
    content TEXT NOT NULL,
    
    -- Vector embedding (Gemini MRL 768 dimensions)
    -- IMPORTANT: Must match EMBEDDING_DIMENSIONS in config
    embedding vector(768) NOT NULL,
    
    -- Memory classification
    memory_type VARCHAR(50) NOT NULL DEFAULT 'message',
    -- Types: 'message', 'summary', 'user_fact'
    
    -- Importance score for retrieval ranking (0.0 - 1.0)
    importance FLOAT DEFAULT 0.5,
    
    -- Additional metadata (JSON)
    metadata JSONB DEFAULT '{}',
    
    -- Session reference (optional, for grouping)
    session_id VARCHAR(255),
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Index on user_id for filtering by user
CREATE INDEX IF NOT EXISTS idx_semantic_memories_user_id 
ON semantic_memories(user_id);

-- Index on memory_type for filtering by type
CREATE INDEX IF NOT EXISTS idx_semantic_memories_type 
ON semantic_memories(memory_type);

-- Index on session_id for session-based queries
CREATE INDEX IF NOT EXISTS idx_semantic_memories_session_id 
ON semantic_memories(session_id);

-- Index on created_at for time-based queries
CREATE INDEX IF NOT EXISTS idx_semantic_memories_created_at 
ON semantic_memories(created_at DESC);

-- Composite index for common query pattern
CREATE INDEX IF NOT EXISTS idx_semantic_memories_user_type 
ON semantic_memories(user_id, memory_type);

-- =============================================================================
-- HNSW INDEX FOR VECTOR SIMILARITY SEARCH
-- Uses cosine similarity (vector_cosine_ops)
-- HNSW provides fast approximate nearest neighbor search
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_semantic_memories_embedding 
ON semantic_memories 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- =============================================================================
-- ROW LEVEL SECURITY (RLS)
-- Ensures users can only access their own memories
-- =============================================================================

-- Enable RLS on the table
ALTER TABLE semantic_memories ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only SELECT their own memories
CREATE POLICY "Users can view own memories"
ON semantic_memories FOR SELECT
USING (
    user_id = current_setting('app.current_user_id', true)
    OR current_setting('app.current_user_id', true) IS NULL
);

-- Policy: Users can only INSERT their own memories
CREATE POLICY "Users can insert own memories"
ON semantic_memories FOR INSERT
WITH CHECK (
    user_id = current_setting('app.current_user_id', true)
    OR current_setting('app.current_user_id', true) IS NULL
);

-- Policy: Users can only UPDATE their own memories
CREATE POLICY "Users can update own memories"
ON semantic_memories FOR UPDATE
USING (
    user_id = current_setting('app.current_user_id', true)
    OR current_setting('app.current_user_id', true) IS NULL
);

-- Policy: Users can only DELETE their own memories
CREATE POLICY "Users can delete own memories"
ON semantic_memories FOR DELETE
USING (
    user_id = current_setting('app.current_user_id', true)
    OR current_setting('app.current_user_id', true) IS NULL
);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to search similar memories using cosine similarity
CREATE OR REPLACE FUNCTION search_semantic_memories(
    p_user_id VARCHAR(255),
    p_query_embedding vector(768),
    p_limit INT DEFAULT 5,
    p_threshold FLOAT DEFAULT 0.7
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    memory_type VARCHAR(50),
    importance FLOAT,
    similarity FLOAT,
    created_at TIMESTAMP WITH TIME ZONE
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        sm.id,
        sm.content,
        sm.memory_type,
        sm.importance,
        1 - (sm.embedding <=> p_query_embedding) AS similarity,
        sm.created_at
    FROM semantic_memories sm
    WHERE sm.user_id = p_user_id
      AND 1 - (sm.embedding <=> p_query_embedding) >= p_threshold
    ORDER BY sm.embedding <=> p_query_embedding
    LIMIT p_limit;
END;
$$;

-- Function to get user facts
CREATE OR REPLACE FUNCTION get_user_facts(
    p_user_id VARCHAR(255)
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    importance FLOAT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        sm.id,
        sm.content,
        sm.importance,
        sm.metadata,
        sm.created_at
    FROM semantic_memories sm
    WHERE sm.user_id = p_user_id
      AND sm.memory_type = 'user_fact'
    ORDER BY sm.importance DESC, sm.created_at DESC;
END;
$$;

-- Function to update timestamp on update
CREATE OR REPLACE FUNCTION update_semantic_memory_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update timestamp
DROP TRIGGER IF EXISTS trigger_update_semantic_memory_timestamp ON semantic_memories;
CREATE TRIGGER trigger_update_semantic_memory_timestamp
    BEFORE UPDATE ON semantic_memories
    FOR EACH ROW
    EXECUTE FUNCTION update_semantic_memory_timestamp();

-- =============================================================================
-- VERIFICATION QUERIES
-- Run these to verify the setup
-- =============================================================================

-- Check if pgvector extension is enabled
-- SELECT * FROM pg_extension WHERE extname = 'vector';

-- Check table structure
-- \d semantic_memories

-- Check indexes
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'semantic_memories';

-- Check RLS policies
-- SELECT * FROM pg_policies WHERE tablename = 'semantic_memories';

-- =============================================================================
-- SAMPLE DATA (for testing - remove in production)
-- =============================================================================

-- INSERT INTO semantic_memories (user_id, content, embedding, memory_type, importance)
-- VALUES (
--     'test_user_001',
--     'User mentioned they are studying for COLREGs exam',
--     '[0.1, 0.2, ...]'::vector(768),  -- Replace with actual embedding
--     'user_fact',
--     0.8
-- );

COMMENT ON TABLE semantic_memories IS 'Semantic memory storage for Maritime AI Tutor v0.3 - Uses Gemini embeddings with MRL 768 dimensions';
