"""
Agentic RAG Module - Corrective RAG Implementation

Phase 7: Agentic RAG with self-correction capabilities.

Components:
- QueryAnalyzer: Analyze query complexity
- RetrievalGrader: Grade document relevance
- QueryRewriter: Rewrite queries for better retrieval
- AnswerVerifier: Check for hallucinations
- CorrectiveRAG: Main orchestrator
- RAGAgent: Knowledge retrieval with LLM
"""

from app.engine.agentic_rag.query_analyzer import QueryAnalyzer, QueryAnalysis
from app.engine.agentic_rag.retrieval_grader import RetrievalGrader, GradingResult
from app.engine.agentic_rag.query_rewriter import QueryRewriter
from app.engine.agentic_rag.answer_verifier import AnswerVerifier, VerificationResult
from app.engine.agentic_rag.corrective_rag import CorrectiveRAG, get_corrective_rag
from app.engine.agentic_rag.rag_agent import (
    RAGAgent, 
    get_rag_agent,
    is_rag_agent_initialized,
    reset_rag_agent
)

__all__ = [
    "QueryAnalyzer",
    "QueryAnalysis",
    "RetrievalGrader", 
    "GradingResult",
    "QueryRewriter",
    "AnswerVerifier",
    "VerificationResult",
    "CorrectiveRAG",
    "get_corrective_rag",
    "RAGAgent",
    "get_rag_agent",
    "is_rag_agent_initialized",
    "reset_rag_agent",
]

