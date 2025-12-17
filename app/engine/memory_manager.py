"""
Memory Manager - Intelligent Memory Deduplication & Reconciliation

CHỈ THỊ KỸ THUẬT SỐ 24: MEMORY MANAGER & DEDUPLICATION

Implements "Check before Write" logic:
1. Search existing memories (Semantic Search)
2. Use LLM Judge to compare and decide action
3. Execute: IGNORE (Exit 0), UPDATE, or INSERT

This is the "brain" of the memory system that prevents:
- Duplicate memories
- Conflicting information
- Memory bloat
"""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from app.core.config import settings

logger = logging.getLogger(__name__)


class MemoryAction(Enum):
    """Actions the Memory Manager can take."""
    IGNORE = "ignore"  # Exit 0 - Already exists
    UPDATE = "update"  # Conflict - Update existing
    INSERT = "insert"  # New information


@dataclass
class MemoryDecision:
    """Result of memory deduplication check."""
    action: MemoryAction
    reason: str
    target_id: Optional[str] = None  # ID of memory to update (for UPDATE action)
    similarity_score: float = 0.0


class MemoryManager:
    """
    Intelligent Memory Manager with Deduplication.
    
    CHỈ THỊ SỐ 24: Implements "Check before Write" logic
    to prevent duplicate and conflicting memories.
    """
    
    def __init__(self, semantic_memory=None):
        """
        Initialize Memory Manager.
        
        Args:
            semantic_memory: SemanticMemoryEngine instance
        """
        # Thresholds from config - CHỈ THỊ SỐ 24
        self.DUPLICATE_THRESHOLD = settings.memory_duplicate_threshold  # Default 0.90
        self.RELATED_THRESHOLD = settings.memory_related_threshold      # Default 0.75
        
        self._semantic_memory = semantic_memory
        self._llm = None
        
    def _ensure_llm(self):
        """Lazy initialization of LLM for judging."""
        if self._llm is None:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                self._llm = ChatGoogleGenerativeAI(
                    model=settings.google_model,
                    google_api_key=settings.google_api_key,
                    temperature=0.1  # Low temperature for consistent decisions
                )
                logger.info(f"Memory Manager LLM Judge initialized with {settings.google_model}")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM Judge: {e}")
    
    async def check_and_save(
        self,
        user_id: str,
        new_fact: str,
        fact_type: str = "preference",
        session_id: Optional[str] = None
    ) -> MemoryDecision:
        """
        Check if memory should be saved, updated, or ignored.
        
        CHỈ THỊ SỐ 24: "Check before Write" logic
        
        Args:
            user_id: User ID
            new_fact: New fact to potentially save
            fact_type: Type of fact (name, goal, preference, etc.)
            session_id: Optional session ID
            
        Returns:
            MemoryDecision with action and reason
        """
        if not self._semantic_memory:
            # Fallback: Just insert if no semantic memory
            return MemoryDecision(
                action=MemoryAction.INSERT,
                reason="Semantic memory not available, inserting directly"
            )
        
        try:
            # Step 1: Search for existing similar memories
            existing_memories = await self._search_similar_memories(
                user_id=user_id,
                query=new_fact,
                limit=3
            )
            
            if not existing_memories:
                # No similar memories found - INSERT
                await self._do_insert(user_id, new_fact, fact_type, session_id)
                return MemoryDecision(
                    action=MemoryAction.INSERT,
                    reason="Thông tin hoàn toàn mới, đã lưu."
                )
            
            # Step 2: Check for exact duplicates OR conflicts (same fact type)
            new_fact_lower = new_fact.lower()
            new_fact_type = new_fact.split(":")[0].strip().lower() if ":" in new_fact else ""
            new_fact_value = new_fact.split(":", 1)[1].strip().lower() if ":" in new_fact else new_fact_lower
            
            for mem in existing_memories:
                mem_content_lower = mem.get("content", "").lower()
                similarity = mem.get("similarity", 0)
                
                # Check if same fact type (e.g., both are "name:" or both are "goal:")
                mem_fact_type = mem_content_lower.split(":")[0].strip() if ":" in mem_content_lower else ""
                mem_fact_value = mem_content_lower.split(":", 1)[1].strip() if ":" in mem_content_lower else mem_content_lower
                
                # Only process if same fact type
                if new_fact_type and mem_fact_type and new_fact_type == mem_fact_type:
                    # Check if values are the same (duplicate) or different (conflict)
                    if new_fact_value == mem_fact_value:
                        # Exact duplicate - IGNORE (Exit 0)
                        logger.info(f"[MEMORY MANAGER] Exact duplicate detected (type={new_fact_type}), ignoring")
                        return MemoryDecision(
                            action=MemoryAction.IGNORE,
                            reason=f"Thông tin đã tồn tại: '{mem['content'][:50]}...' (Exit 0)",
                            similarity_score=similarity
                        )
                    else:
                        # Same type but different value - CONFLICT -> UPDATE
                        logger.info(f"[MEMORY MANAGER] Conflict detected: '{mem_fact_value}' vs '{new_fact_value}', updating")
                        await self._do_update(mem.get("id"), new_fact, fact_type)
                        return MemoryDecision(
                            action=MemoryAction.UPDATE,
                            reason=f"Đã cập nhật: '{mem_fact_value}' -> '{new_fact_value}'",
                            target_id=mem.get("id"),
                            similarity_score=similarity
                        )
            
            # Step 3: Use LLM Judge for related memories
            decision = await self._llm_judge(new_fact, existing_memories)
            
            # Step 4: Execute decision
            if decision.action == MemoryAction.IGNORE:
                logger.info(f"[MEMORY MANAGER] LLM Judge: IGNORE - {decision.reason}")
                
            elif decision.action == MemoryAction.UPDATE:
                logger.info(f"[MEMORY MANAGER] LLM Judge: UPDATE - {decision.reason}")
                await self._do_update(decision.target_id, new_fact, fact_type)
                
            elif decision.action == MemoryAction.INSERT:
                logger.info(f"[MEMORY MANAGER] LLM Judge: INSERT - {decision.reason}")
                await self._do_insert(user_id, new_fact, fact_type, session_id)
            
            return decision
            
        except Exception as e:
            logger.error(f"Memory check failed: {e}")
            # Fallback: Insert on error
            await self._do_insert(user_id, new_fact, fact_type, session_id)
            return MemoryDecision(
                action=MemoryAction.INSERT,
                reason=f"Error during check, inserted anyway: {e}"
            )
    
    async def _search_similar_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Search for similar existing memories."""
        try:
            context = await self._semantic_memory.retrieve_context(
                user_id=user_id,
                query=query,
                search_limit=limit,
                similarity_threshold=self.RELATED_THRESHOLD,
                include_user_facts=True
            )
            
            results = []
            
            # Include user facts
            for fact in context.user_facts:
                results.append({
                    "id": getattr(fact, "id", None),
                    "content": fact.content if hasattr(fact, "content") else str(fact),
                    "similarity": getattr(fact, "similarity", 0.7),
                    "type": "user_fact"
                })
            
            # Include relevant memories
            for mem in context.relevant_memories:
                results.append({
                    "id": mem.id,
                    "content": mem.content,
                    "similarity": mem.similarity,
                    "type": "memory"
                })
            
            return results[:limit]
            
        except Exception as e:
            logger.warning(f"Similar memory search failed: {e}")
            return []
    
    async def _llm_judge(
        self,
        new_fact: str,
        existing_memories: List[Dict[str, Any]]
    ) -> MemoryDecision:
        """
        Use LLM to judge whether to IGNORE, UPDATE, or INSERT.
        
        CHỈ THỊ SỐ 24: "The Judge" - LLM-based decision making
        """
        self._ensure_llm()
        
        if not self._llm:
            # Fallback: Insert if no LLM
            return MemoryDecision(
                action=MemoryAction.INSERT,
                reason="LLM Judge not available, inserting"
            )
        
        try:
            # Format existing memories for prompt
            memories_text = "\n".join([
                f"- ID: {m.get('id', 'N/A')}, Content: \"{m['content'][:100]}\" (Similarity: {m.get('similarity', 0):.2f})"
                for m in existing_memories
            ])
            
            prompt = f"""Bạn là Memory Judge. Quyết định xem thông tin mới có nên được lưu không.

THÔNG TIN MỚI: "{new_fact}"

KÝ ỨC HIỆN CÓ:
{memories_text}

QUY TẮC:
1. IGNORE: Nếu thông tin mới ĐÃ CÓ trong ký ức (trùng lặp về nghĩa, dù từ ngữ khác)
2. UPDATE: Nếu thông tin mới MÂU THUẪN hoặc CẬP NHẬT cho ký ức cũ (ví dụ: tên cũ là A, nay là B)
3. INSERT: Nếu là thông tin HOÀN TOÀN MỚI, không liên quan đến ký ức hiện có

Trả lời theo format:
ACTION: [IGNORE/UPDATE/INSERT]
TARGET_ID: [ID của ký ức cần update, nếu UPDATE]
REASON: [Giải thích ngắn gọn]
"""
            
            response = await self._llm.ainvoke(prompt)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            content = text_content.strip()
            
            # Parse response
            action = MemoryAction.INSERT  # Default
            target_id = None
            reason = "LLM decision"
            
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("ACTION:"):
                    action_str = line.replace("ACTION:", "").strip().upper()
                    if action_str == "IGNORE":
                        action = MemoryAction.IGNORE
                    elif action_str == "UPDATE":
                        action = MemoryAction.UPDATE
                    else:
                        action = MemoryAction.INSERT
                        
                elif line.startswith("TARGET_ID:"):
                    target_id = line.replace("TARGET_ID:", "").strip()
                    if target_id.lower() in ["none", "n/a", ""]:
                        target_id = None
                        
                elif line.startswith("REASON:"):
                    reason = line.replace("REASON:", "").strip()
            
            return MemoryDecision(
                action=action,
                reason=reason,
                target_id=target_id
            )
            
        except Exception as e:
            logger.error(f"LLM Judge failed: {e}")
            return MemoryDecision(
                action=MemoryAction.INSERT,
                reason=f"LLM Judge error: {e}"
            )
    
    async def _do_insert(
        self,
        user_id: str,
        fact_content: str,
        fact_type: str,
        session_id: Optional[str] = None
    ) -> bool:
        """Insert new memory."""
        try:
            return await self._semantic_memory.store_user_fact_upsert(
                user_id=user_id,
                fact_content=fact_content,
                fact_type=fact_type,
                confidence=0.95,
                session_id=session_id
            )
        except Exception as e:
            logger.error(f"Memory insert failed: {e}")
            return False
    
    async def _do_update(
        self,
        target_id: str,
        new_content: str,
        fact_type: str
    ) -> bool:
        """Update existing memory."""
        try:
            if not target_id:
                return False
            
            # Generate new embedding
            embedding = self._semantic_memory._embeddings.embed_documents([new_content])[0]
            
            # Update via repository
            return self._semantic_memory._repository.update_fact(
                fact_id=target_id,
                content=new_content,
                embedding=embedding,
                metadata={
                    "fact_type": fact_type,
                    "updated_by": "memory_manager",
                    "confidence": 0.95
                }
            )
        except Exception as e:
            logger.error(f"Memory update failed: {e}")
            return False


# Singleton instance
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager(semantic_memory=None) -> MemoryManager:
    """Get or create MemoryManager singleton."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(semantic_memory)
    elif semantic_memory and _memory_manager._semantic_memory is None:
        _memory_manager._semantic_memory = semantic_memory
    return _memory_manager
