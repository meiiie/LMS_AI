// Neo4j Full-text Index for Sparse Search (Hybrid Search v0.5)
// Feature: hybrid-search
// Requirements: 3.1

// Create full-text index on Knowledge nodes
// Indexes both title and content fields for comprehensive search
CREATE FULLTEXT INDEX knowledge_fulltext IF NOT EXISTS
FOR (k:Knowledge) ON EACH [k.title, k.content]
OPTIONS {
  indexConfig: {
    `fulltext.analyzer`: 'standard-no-stop-words',
    `fulltext.eventually_consistent`: false
  }
};

// Verify index was created
SHOW INDEXES
WHERE name = 'knowledge_fulltext';

// Example usage:
// CALL db.index.fulltext.queryNodes('knowledge_fulltext', 'Rule 15') 
// YIELD node, score
// RETURN node.title, node.content, score
// ORDER BY score DESC
// LIMIT 10;
