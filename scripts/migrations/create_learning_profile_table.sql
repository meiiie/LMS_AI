-- Create learning_profile table for CHỈ THỊ KỸ THUẬT SỐ 04
-- Run this script on Neon PostgreSQL to create the table

-- Drop existing table if exists (careful in production!)
-- DROP TABLE IF EXISTS learning_profile;

CREATE TABLE IF NOT EXISTS learning_profile (
    user_id VARCHAR(255) PRIMARY KEY,
    attributes JSONB DEFAULT '{"level": "beginner"}'::jsonb,
    weak_areas JSONB DEFAULT '[]'::jsonb,
    strong_areas JSONB DEFAULT '[]'::jsonb,
    total_sessions INTEGER DEFAULT 0,
    total_messages INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_learning_profile_user_id ON learning_profile(user_id);

-- Add comment
COMMENT ON TABLE learning_profile IS 'User learning profiles for personalization (CHỈ THỊ SỐ 04)';
