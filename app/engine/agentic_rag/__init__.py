"""
Agentic RAG Module - Corrective RAG Implementation

Phase 7: Agentic RAG with self-correction capabilities.

Components:
- RAGAgent: Base RAG agent with hybrid search (SINGLETON for memory optimization)
- QueryAnalyzer: Analyze query complexity
- RetrievalGrader: Grade document relevance
- QueryRewriter: Rewrite queries for better retrieval
- AnswerVerifier: Check for hallucinations
- CorrectiveRAG: Main orchestrator
"""

from app.engine.agentic_rag.rag_agent import (
    RAGAgent,
    get_rag_agent,  # CRITICAL: Use singleton to prevent memory overflow
    reset_rag_agent,  # For testing only
    is_rag_agent_initialized,  # For health checks
)
from app.engine.agentic_rag.query_analyzer import QueryAnalyzer, QueryAnalysis
from app.engine.agentic_rag.retrieval_grader import RetrievalGrader, GradingResult
from app.engine.agentic_rag.query_rewriter import QueryRewriter
from app.engine.agentic_rag.answer_verifier import AnswerVerifier, VerificationResult
from app.engine.agentic_rag.corrective_rag import (
    CorrectiveRAG,
    get_corrective_rag,  # CRITICAL: Use singleton
    reset_corrective_rag,  # For testing only
    is_corrective_rag_initialized,  # For health checks
)

__all__ = [
    # RAGAgent (use singleton!)
    "RAGAgent",
    "get_rag_agent",
    "reset_rag_agent",
    "is_rag_agent_initialized",
    # Query components
    "QueryAnalyzer",
    "QueryAnalysis",
    "RetrievalGrader", 
    "GradingResult",
    "QueryRewriter",
    "AnswerVerifier",
    "VerificationResult",
    # Main orchestrator (use singleton!)
    "CorrectiveRAG",
    "get_corrective_rag",
    "reset_corrective_rag",
    "is_corrective_rag_initialized",
]



