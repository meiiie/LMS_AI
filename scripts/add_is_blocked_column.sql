-- Migration: Add is_blocked column to chat tables
-- CHỈ THỊ KỸ THUẬT SỐ 22: Memory Isolation & Context Protection
-- 
-- Purpose: Allow blocked messages to be saved for admin review
-- while filtering them from AI context window
--
-- NOTE: This project has 2 schemas:
--   1. Legacy: chat_sessions + chat_messages (SQLAlchemy models)
--   2. CHỈ THỊ SỐ 04: chat_history (raw SQL)
-- 
-- Run the section that matches your database setup.

-- ============================================================================
-- OPTION A: Legacy Schema (chat_sessions + chat_messages)
-- Run this if you're using SQLAlchemy models
-- ============================================================================

-- Create chat_sessions table if not exists
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    user_name VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);

-- Create chat_messages table if not exists
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    is_blocked BOOLEAN DEFAULT FALSE,
    block_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_is_blocked ON chat_messages(is_blocked);

-- Add columns if table already exists (safe to run multiple times)
ALTER TABLE chat_messages 
ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE;

ALTER TABLE chat_messages 
ADD COLUMN IF NOT EXISTS block_reason TEXT;

-- ============================================================================
-- OPTION B: CHỈ THỊ SỐ 04 Schema (chat_history)
-- Run this if you want to use the new schema
-- ============================================================================

-- Create chat_history table if not exists
CREATE TABLE IF NOT EXISTS chat_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    session_id UUID NOT NULL,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    is_blocked BOOLEAN DEFAULT FALSE,
    block_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_history_user_id ON chat_history(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_session_id ON chat_history(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_created_at ON chat_history(created_at);
CREATE INDEX IF NOT EXISTS idx_chat_history_is_blocked ON chat_history(is_blocked);

-- Add columns if table already exists (safe to run multiple times)
ALTER TABLE chat_history 
ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE;

ALTER TABLE chat_history 
ADD COLUMN IF NOT EXISTS block_reason TEXT;

-- ============================================================================
-- 3. Verify migration
-- ============================================================================

-- Check chat_messages columns (Legacy)
SELECT 'chat_messages' as table_name, column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'chat_messages' 
AND column_name IN ('is_blocked', 'block_reason');

-- Check chat_history columns (CHỈ THỊ SỐ 04)
SELECT 'chat_history' as table_name, column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'chat_history' 
AND column_name IN ('is_blocked', 'block_reason');
