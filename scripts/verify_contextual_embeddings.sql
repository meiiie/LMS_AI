-- ============================================================
-- CORRECTED: VERIFY CONTEXTUAL EMBEDDINGS STATUS
-- Run this query on Neon production database
-- ============================================================

-- ISSUE: Previous query checked 'content' column, but contextual_content
-- is stored in a SEPARATE column called 'contextual_content'

-- 1. Check contextual_content column (CORRECT)
SELECT 
    COUNT(*) as total_chunks,
    COUNT(CASE WHEN contextual_content IS NOT NULL AND contextual_content != '' THEN 1 END) as with_context,
    COUNT(CASE WHEN contextual_content IS NULL OR contextual_content = '' THEN 1 END) as without_context,
    ROUND(
        100.0 * COUNT(CASE WHEN contextual_content IS NOT NULL AND contextual_content != '' THEN 1 END) / NULLIF(COUNT(*), 0), 
        2
    ) as context_percentage
FROM knowledge_embeddings;

-- 2. Sample of chunks WITH contextual_content (first 200 chars)
SELECT 
    id,
    LEFT(contextual_content, 200) as contextual_content_preview,
    document_id,
    page_number
FROM knowledge_embeddings
WHERE contextual_content IS NOT NULL AND contextual_content != ''
LIMIT 5;

-- 3. Check if contextual_content starts with context pattern
SELECT 
    COUNT(*) as total,
    COUNT(CASE WHEN contextual_content LIKE '[Context:%' THEN 1 END) as with_context_prefix
FROM knowledge_embeddings
WHERE contextual_content IS NOT NULL;

-- 4. Also check if content already has context (alternative storage)
SELECT 
    COUNT(*) as total,
    COUNT(CASE WHEN content LIKE '[Context:%' THEN 1 END) as content_with_context
FROM knowledge_embeddings;

-- ============================================================
-- EXPECTED RESULTS:
-- If contextual_content column has data: Context enrichment worked
-- If both are empty: Re-ingestion with context_enricher needed
-- ============================================================
