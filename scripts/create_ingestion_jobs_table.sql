-- Knowledge Ingestion Jobs Table
-- Tracks PDF upload and processing jobs for Knowledge Graph ingestion
-- Feature: knowledge-ingestion
-- Requirements: 5.1, 5.2, 5.3

-- Create ingestion_jobs table
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    progress INT DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    nodes_created INT DEFAULT 0,
    error_message TEXT,
    file_path VARCHAR(500),
    content_hash VARCHAR(64),
    uploaded_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_uploaded_by ON ingestion_jobs(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_created_at ON ingestion_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_content_hash ON ingestion_jobs(content_hash);

-- Add comments for documentation
COMMENT ON TABLE ingestion_jobs IS 'Tracks PDF document ingestion jobs for Knowledge Graph';
COMMENT ON COLUMN ingestion_jobs.status IS 'Job status: pending, processing, completed, failed';
COMMENT ON COLUMN ingestion_jobs.progress IS 'Processing progress percentage (0-100)';
COMMENT ON COLUMN ingestion_jobs.nodes_created IS 'Number of Knowledge nodes created in Neo4j';
COMMENT ON COLUMN ingestion_jobs.content_hash IS 'SHA-256 hash of file content for duplicate detection';
