-- ============================================================================
-- CHỈ THỊ KỸ THUẬT SỐ 04: MEMORY & PERSONALIZATION
-- Script tạo bảng cho Supabase
-- ============================================================================

-- Bảng lưu lịch sử hội thoại
CREATE TABLE IF NOT EXISTS chat_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,    -- Link với LMS
    session_id VARCHAR(255),          -- Phiên làm việc
    role VARCHAR(50) NOT NULL,        -- 'user' | 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- Index để query nhanh theo user_id
CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_history(user_id, created_at DESC);

-- Index để query theo session_id
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id, created_at DESC);

-- Bảng lưu hồ sơ học tập (Dùng cho cá nhân hóa)
CREATE TABLE IF NOT EXISTS learning_profile (
    user_id VARCHAR(255) PRIMARY KEY,
    attributes JSONB DEFAULT '{}'::jsonb,  -- VD: {"level": "beginner", "style": "visual"}
    weak_areas JSONB DEFAULT '[]'::jsonb,  -- VD: ["Rule 19", "Lights"]
    strong_areas JSONB DEFAULT '[]'::jsonb, -- VD: ["Rule 5", "Navigation"]
    total_sessions INT DEFAULT 0,
    total_messages INT DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- Bảng lưu session (optional - để track sessions)
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    user_name VARCHAR(255),
    context JSONB DEFAULT '{}'::jsonb,  -- course_id, lesson_id, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_session_user ON chat_sessions(user_id, created_at DESC);

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Function để tự động update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger cho learning_profile
DROP TRIGGER IF EXISTS update_learning_profile_updated_at ON learning_profile;
CREATE TRIGGER update_learning_profile_updated_at
    BEFORE UPDATE ON learning_profile
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger cho chat_sessions
DROP TRIGGER IF EXISTS update_chat_sessions_updated_at ON chat_sessions;
CREATE TRIGGER update_chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- SAMPLE DATA (Optional - for testing)
-- ============================================================================

-- INSERT INTO learning_profile (user_id, attributes, weak_areas)
-- VALUES (
--     'test_user_001',
--     '{"level": "intermediate", "style": "visual", "language": "vi"}'::jsonb,
--     '["Rule 19 - Conduct in restricted visibility", "Lights and shapes"]'::jsonb
-- );
