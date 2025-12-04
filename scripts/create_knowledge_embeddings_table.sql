-- Knowledge Embeddings Table for Dense Search (Hybrid Search v0.5)
-- Feature: hybrid-search
-- Requirements: 2.1, 6.1

-- Enable pgvector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- Create knowledge_embeddings table
CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id VARCHAR(255) UNIQUE NOT NULL,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create IVFFlat index for fast cosine similarity search
-- lists = 100 is optimal for ~10k-100k vectors
CREATE INDEX IF NOT EXISTS knowledge_embeddings_vector_idx 
ON knowledge_embeddings 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Create index on node_id for fast lookups
CREATE INDEX IF NOT EXISTS knowledge_embeddings_node_id_idx 
ON knowledge_embeddings (node_id);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_knowledge_embeddings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at
DROP TRIGGER IF EXISTS knowledge_embeddings_updated_at_trigger ON knowledge_embeddings;
CREATE TRIGGER knowledge_embeddings_updated_at_trigger
    BEFORE UPDATE ON knowledge_embeddings
    FOR EACH ROW
    EXECUTE FUNCTION update_knowledge_embeddings_updated_at();

-- Comments for documentation
COMMENT ON TABLE knowledge_embeddings IS 'Stores 768-dim Gemini embeddings for Knowledge nodes (Dense Search)';
COMMENT ON COLUMN knowledge_embeddings.node_id IS 'Reference to Knowledge node ID in Neo4j';
COMMENT ON COLUMN knowledge_embeddings.embedding IS '768-dimensional L2-normalized Gemini embedding vector';
