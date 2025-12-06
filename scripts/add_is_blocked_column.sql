-- Migration: Add is_blocked column to chat_history and chat_messages tables
-- CHỈ THỊ KỸ THUẬT SỐ 22: Memory Isolation & Context Protection
-- 
-- Purpose: Allow blocked messages to be saved for admin review
-- while filtering them from AI context window

-- ============================================================================
-- 1. Update chat_history table (CHỈ THỊ SỐ 04 schema)
-- ============================================================================

-- Add is_blocked column (default FALSE for existing records)
ALTER TABLE chat_history 
ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE;

-- Add block_reason column (nullable)
ALTER TABLE chat_history 
ADD COLUMN IF NOT EXISTS block_reason TEXT;

-- Create index for efficient filtering
CREATE INDEX IF NOT EXISTS idx_chat_history_is_blocked 
ON chat_history(is_blocked);

-- ============================================================================
-- 2. Update chat_messages table (Legacy schema)
-- ============================================================================

-- Add is_blocked column (default FALSE for existing records)
ALTER TABLE chat_messages 
ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE;

-- Add block_reason column (nullable)
ALTER TABLE chat_messages 
ADD COLUMN IF NOT EXISTS block_reason TEXT;

-- Create index for efficient filtering
CREATE INDEX IF NOT EXISTS idx_chat_messages_is_blocked 
ON chat_messages(is_blocked);

-- ============================================================================
-- 3. Verify migration
-- ============================================================================

-- Check chat_history columns
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'chat_history' 
AND column_name IN ('is_blocked', 'block_reason');

-- Check chat_messages columns
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'chat_messages' 
AND column_name IN ('is_blocked', 'block_reason');
