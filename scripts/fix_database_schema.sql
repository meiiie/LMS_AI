-- ============================================================================
-- FIX DATABASE SCHEMA - Maritime AI Service
-- Run this script on Neon PostgreSQL to fix schema issues
-- Date: 2025-12-10
-- ============================================================================

-- ============================================================================
-- 1. Create chat_sessions table (if not exists)
-- ============================================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id UUID PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    user_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);

-- ============================================================================
-- 2. Create chat_messages table (if not exists)
-- ============================================================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_blocked BOOLEAN DEFAULT FALSE,
    block_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_is_blocked ON chat_messages(is_blocked);

-- ============================================================================
-- 3. Add missing columns to chat_messages (if table already exists)
-- ============================================================================
DO $$
BEGIN
    -- Add is_blocked column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'chat_messages' AND column_name = 'is_blocked'
    ) THEN
        ALTER TABLE chat_messages ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS idx_chat_messages_is_blocked ON chat_messages(is_blocked);
    END IF;
    
    -- Add block_reason column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'chat_messages' AND column_name = 'block_reason'
    ) THEN
        ALTER TABLE chat_messages ADD COLUMN block_reason TEXT;
    END IF;
END $$;

-- ============================================================================
-- 4. Add missing columns to learning_profile
-- ============================================================================
DO $$
BEGIN
    -- Add attributes column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'learning_profile' AND column_name = 'attributes'
    ) THEN
        ALTER TABLE learning_profile ADD COLUMN attributes JSONB DEFAULT '{}';
    END IF;
    
    -- Add weak_areas column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'learning_profile' AND column_name = 'weak_areas'
    ) THEN
        ALTER TABLE learning_profile ADD COLUMN weak_areas JSONB DEFAULT '[]';
    END IF;
    
    -- Add strong_areas column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'learning_profile' AND column_name = 'strong_areas'
    ) THEN
        ALTER TABLE learning_profile ADD COLUMN strong_areas JSONB DEFAULT '[]';
    END IF;
    
    -- Add total_sessions column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'learning_profile' AND column_name = 'total_sessions'
    ) THEN
        ALTER TABLE learning_profile ADD COLUMN total_sessions INTEGER DEFAULT 0;
    END IF;
    
    -- Add total_messages column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'learning_profile' AND column_name = 'total_messages'
    ) THEN
        ALTER TABLE learning_profile ADD COLUMN total_messages INTEGER DEFAULT 0;
    END IF;
END $$;

-- ============================================================================
-- 5. Fix learning_profile.user_id type (UUID -> TEXT for LMS compatibility)
-- ============================================================================
-- Check if user_id is UUID type and convert to TEXT
DO $$
DECLARE
    col_type TEXT;
BEGIN
    SELECT data_type INTO col_type
    FROM information_schema.columns 
    WHERE table_name = 'learning_profile' AND column_name = 'user_id';
    
    IF col_type = 'uuid' THEN
        -- Drop foreign key constraints first (if any)
        -- Note: This may fail if there are FK constraints - handle manually if needed
        
        -- Create backup of data
        CREATE TEMP TABLE learning_profile_backup AS SELECT * FROM learning_profile;
        
        -- Drop and recreate table with TEXT user_id
        DROP TABLE IF EXISTS learning_profile CASCADE;
        
        CREATE TABLE learning_profile (
            user_id TEXT PRIMARY KEY,
            current_level VARCHAR(20) DEFAULT 'CADET' NOT NULL,
            learning_style VARCHAR(20),
            weak_topics JSONB DEFAULT '[]',
            completed_topics JSONB DEFAULT '[]',
            assessment_history JSONB DEFAULT '[]',
            attributes JSONB DEFAULT '{}',
            weak_areas JSONB DEFAULT '[]',
            strong_areas JSONB DEFAULT '[]',
            total_sessions INTEGER DEFAULT 0,
            total_messages INTEGER DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        -- Restore data (convert UUID to TEXT)
        INSERT INTO learning_profile (user_id, current_level, learning_style, weak_topics, completed_topics, assessment_history, created_at, updated_at)
        SELECT user_id::TEXT, current_level, learning_style, weak_topics, completed_topics, assessment_history, created_at, updated_at
        FROM learning_profile_backup;
        
        DROP TABLE learning_profile_backup;
        
        RAISE NOTICE 'Converted learning_profile.user_id from UUID to TEXT';
    END IF;
END $$;

-- ============================================================================
-- 6. Verify schema
-- ============================================================================
SELECT 'chat_sessions' as table_name, column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'chat_sessions'
UNION ALL
SELECT 'chat_messages' as table_name, column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'chat_messages'
UNION ALL
SELECT 'learning_profile' as table_name, column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'learning_profile'
ORDER BY table_name, column_name;
