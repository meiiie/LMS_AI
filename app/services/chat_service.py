"""
Chat Service - Integration layer for all components.

This service wires together:
- Agent Orchestrator (LangGraph)
- Chat Agent, RAG Agent, Tutor Agent
- Memory Engine (Memori)
- Knowledge Graph (GraphRAG)
- Guardrails
- Learning Profile
- Chat History (Memory Lite - Week 2)

**Feature: maritime-ai-tutor**
**Validates: Requirements 1.1, 2.1, 2.2, 2.3**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 04 - Memory & Personalization**
"""

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional
from uuid import UUID, uuid4

from app.engine.agents.chat_agent import ChatAgent
from app.engine.graph import AgentOrchestrator, AgentType, IntentType
from app.engine.guardrails import Guardrails, ValidationStatus
from app.engine.memory import MemoriEngine
from app.engine.tools.rag_tool import RAGAgent, get_knowledge_repository
from app.engine.tools.tutor_agent import TutorAgent
from app.models.learning_profile import LearningProfile
from app.models.schemas import ChatRequest, InternalChatResponse, Source, UserRole
from app.repositories.learning_profile_repository import InMemoryLearningProfileRepository
from app.repositories.chat_history_repository import (
    ChatHistoryRepository, 
    get_chat_history_repository
)

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a chat request."""
    message: str
    agent_type: AgentType
    sources: Optional[List[Source]] = None
    blocked: bool = False
    metadata: dict = None


class ChatService:
    """
    Main service that integrates all components.
    
    **Validates: Requirements 1.1, 2.1, 2.2, 2.3**
    """
    
    def __init__(self):
        """Initialize all components."""
        # Core components
        self._memory = MemoriEngine()
        self._knowledge_graph = get_knowledge_repository()  # Use Neo4j if available
        self._profile_repo = InMemoryLearningProfileRepository()
        self._guardrails = Guardrails()
        
        # Memory Lite - Chat History (Week 2)
        self._chat_history = get_chat_history_repository()
        if self._chat_history.is_available():
            self._chat_history.ensure_tables()
            logger.info("Memory Lite (Chat History) initialized")
        
        # Agents
        self._orchestrator = AgentOrchestrator()
        self._chat_agent = ChatAgent(memory_engine=self._memory)
        self._rag_agent = RAGAgent(knowledge_graph=self._knowledge_graph)
        self._tutor_agent = TutorAgent()
        
        logger.info(f"Knowledge graph available: {self._knowledge_graph.is_available()}")
        logger.info(f"Chat history available: {self._chat_history.is_available()}")
        
        # Session tracking (in-memory fallback)
        self._sessions: dict[str, UUID] = {}  # user_id -> session_id
        
        logger.info("ChatService initialized with all components")
    
    async def process_message(
        self,
        request: ChatRequest,
        background_save: Optional[Callable] = None
    ) -> InternalChatResponse:
        """
        Process a chat message through the full pipeline.
        
        Pipeline:
        1. Input validation (Guardrails)
        2. Get/create session and retrieve history (Memory Lite)
        3. Save user message to history
        4. Intent classification (Orchestrator)
        5. Role-Based Prompting (student=Tutor, teacher/admin=Assistant)
        6. Agent routing and processing (with history context)
        7. Save AI response to history
        8. Output validation (Guardrails)
        9. Response generation
        
        **Validates: Requirements 1.1, 2.1, 2.2, 2.3, 7.1, 7.2**
        **Feature: Week 2 - Memory Lite**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03 - Role-Based Prompting**
        """
        user_id = str(request.user_id)
        message = request.message
        user_role = request.role  # student | teacher | admin
        
        # Step 1: Input validation
        input_result = await self._guardrails.validate_input(message)
        if not input_result.is_valid:
            logger.warning(f"Input blocked for user {user_id}: {input_result.issues}")
            return self._create_blocked_response(input_result.issues)
        
        # Log role for debugging
        logger.info(f"Processing request for user {user_id} with role: {user_role.value}")
        
        # Step 2: Get or create session (Memory Lite)
        session_id = self._get_or_create_session(user_id)
        
        # Step 3: Retrieve conversation history (Sliding Window)
        conversation_history = ""
        user_name = None
        if self._chat_history.is_available():
            # Get recent messages
            recent_messages = self._chat_history.get_recent_messages(session_id)
            conversation_history = self._chat_history.format_history_for_prompt(recent_messages)
            
            # Get user name if stored
            user_name = self._chat_history.get_user_name(session_id)
            
            # Save user message (use background task if provided)
            if background_save:
                background_save(self._save_message_async, session_id, "user", message)
            else:
                self._chat_history.save_message(session_id, "user", message)
            
            # Try to extract user name from message
            extracted_name = self._extract_user_name(message)
            if extracted_name and not user_name:
                self._chat_history.update_user_name(session_id, extracted_name)
                user_name = extracted_name
        
        # Step 4: Process through orchestrator
        orchestrator_response = self._orchestrator.process_message(
            message=message,
            session_id=str(session_id),
            user_id=user_id
        )
        
        # Step 5: Handle clarification request
        if orchestrator_response.requires_clarification:
            return self._create_clarification_response(orchestrator_response.content)
        
        # Step 6: Route to appropriate agent (with history context + role-based prompting)
        result = await self._route_to_agent(
            agent_type=orchestrator_response.agent_type,
            message=message,
            user_id=user_id,
            session_id=str(session_id),
            conversation_history=conversation_history,
            user_name=user_name,
            user_role=user_role  # Pass role for role-based prompting
        )
        
        # Step 7: Save AI response to history (use background task if provided)
        if self._chat_history.is_available():
            if background_save:
                # Use BackgroundTasks to save without blocking response
                background_save(self._save_message_async, session_id, "assistant", result.message)
            else:
                self._chat_history.save_message(session_id, "assistant", result.message)
        
        # Step 8: Output validation
        output_result = await self._guardrails.validate_output(result.message)
        if output_result.status == ValidationStatus.FLAGGED:
            result.message += "\n\n_Note: Please verify safety-critical information with official sources._"
        
        # Step 9: Create response (InternalChatResponse for API layer to convert)
        return InternalChatResponse(
            response_id=uuid4(),
            message=result.message,
            agent_type=result.agent_type,
            sources=result.sources,
            metadata={
                "session_id": str(session_id),
                "intent": orchestrator_response.intent.type.value,
                "confidence": orchestrator_response.intent.confidence,
                "user_name": user_name,
                "user_role": user_role.value,
                "history_available": self._chat_history.is_available(),
                **(result.metadata or {})
            }
        )

    
    async def _route_to_agent(
        self,
        agent_type: AgentType,
        message: str,
        user_id: str,
        session_id: str,
        conversation_history: str = "",
        user_name: Optional[str] = None,
        user_role: UserRole = UserRole.STUDENT
    ) -> ProcessingResult:
        """
        Route message to appropriate agent with conversation context.
        
        Role-Based Prompting (CHỈ THỊ KỸ THUẬT SỐ 03):
        - student: AI đóng vai Gia sư (Tutor) - giọng văn khuyến khích, giải thích cặn kẽ
        - teacher/admin: AI đóng vai Trợ lý (Assistant) - chuyên nghiệp, ngắn gọn
        """
        
        if agent_type == AgentType.RAG:
            return await self._process_with_rag(message, user_id, conversation_history, user_role)
        
        elif agent_type == AgentType.TUTOR:
            return await self._process_with_tutor(message, user_id, session_id)
        
        else:  # CHAT
            return await self._process_with_chat(message, user_id, conversation_history, user_name, user_role)
    
    async def _process_with_chat(
        self, 
        message: str, 
        user_id: str,
        conversation_history: str = "",
        user_name: Optional[str] = None,
        user_role: UserRole = UserRole.STUDENT
    ) -> ProcessingResult:
        """
        Process with Chat Agent with conversation context.
        
        Role-Based Prompting:
        - student: Gia sư - khuyến khích, giải thích cặn kẽ
        - teacher/admin: Trợ lý - chuyên nghiệp, ngắn gọn
        """
        # Build conversation history for chat agent
        history_list = []
        if conversation_history:
            for line in conversation_history.split("\n"):
                if line.startswith("User: "):
                    history_list.append({"role": "user", "content": line[6:]})
                elif line.startswith("AI: "):
                    history_list.append({"role": "assistant", "content": line[4:]})
        
        response = await self._chat_agent.process(
            message=message,
            user_id=user_id,
            conversation_history=history_list if history_list else None,
            user_role=user_role.value  # Pass role for role-based prompting
        )
        
        # Personalize response with user name
        content = response.content
        if user_name and not any(name in content.lower() for name in [user_name.lower()]):
            # Add personalization if not already present
            if "chào" in message.lower() or "hello" in message.lower():
                content = f"Chào {user_name}! " + content
        
        return ProcessingResult(
            message=content,
            agent_type=AgentType.CHAT,
            metadata={"memory_used": response.memory_used, "user_name": user_name, "user_role": user_role.value}
        )
    
    async def _process_with_rag(
        self, 
        message: str, 
        user_id: str,
        conversation_history: str = "",
        user_role: UserRole = UserRole.STUDENT
    ) -> ProcessingResult:
        """
        Process with RAG Agent with conversation context.
        
        Role-Based Prompting:
        - student: Gia sư - khuyến khích, giải thích cặn kẽ thuật ngữ
        - teacher/admin: Trợ lý - chuyên nghiệp, ngắn gọn, trích dẫn luật chính xác
        """
        logger.info(f"RAG query: {message} (role: {user_role.value})")
        logger.info(f"Knowledge graph available: {self._knowledge_graph.is_available()}")
        
        # Pass conversation history and role to RAG for context
        response = await self._rag_agent.query(
            message, 
            conversation_history=conversation_history,
            user_role=user_role.value  # Pass role for role-based prompting
        )
        logger.info(f"RAG response: {response.content[:100]}...")
        
        sources = None
        if response.citations:
            sources = [
                Source(
                    node_id=c.node_id,
                    title=c.title,
                    source_type="knowledge_graph",
                    content_snippet=c.source
                )
                for c in response.citations
            ]
        
        return ProcessingResult(
            message=response.content,
            agent_type=AgentType.RAG,
            sources=sources,
            metadata={
                "is_fallback": response.is_fallback,
                "citation_count": len(response.citations)
            }
        )
    
    async def _process_with_tutor(
        self, 
        message: str, 
        user_id: str,
        session_id: str
    ) -> ProcessingResult:
        """Process with Tutor Agent."""
        # Check for existing teaching session
        tutor_session_id = f"{user_id}_teaching"
        existing_session = self._tutor_agent.get_session(tutor_session_id)
        
        if existing_session:
            # Continue existing session
            response = self._tutor_agent.process_response(message, tutor_session_id)
        else:
            # Extract topic from message and start new session
            topic = self._extract_topic(message)
            response = self._tutor_agent.start_session(topic, user_id)
        
        # Update learning profile if assessment complete
        if response.assessment_complete:
            await self._update_learning_profile(user_id, response)
        
        return ProcessingResult(
            message=response.content,
            agent_type=AgentType.TUTOR,
            metadata={
                "phase": response.phase.value,
                "mastery_achieved": response.mastery_achieved
            }
        )
    
    def _extract_topic(self, message: str) -> str:
        """Extract topic from teaching request."""
        message_lower = message.lower()
        
        # Common maritime topics
        topics = {
            "solas": "solas",
            "colregs": "colregs",
            "fire": "fire_safety",
            "navigation": "navigation",
            "safety": "safety",
        }
        
        for keyword, topic in topics.items():
            if keyword in message_lower:
                return topic
        
        return "maritime_basics"
    
    async def _update_learning_profile(self, user_id: str, response) -> None:
        """Update learning profile after assessment."""
        try:
            profile = await self._profile_repo.get_or_create(UUID(user_id))
            assessment = self._tutor_agent.create_assessment_from_state(response.state)
            profile.add_assessment(assessment)
            await self._profile_repo.update(profile)
            logger.info(f"Updated learning profile for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to update learning profile: {e}")
    
    def _get_or_create_session(self, user_id: str) -> UUID:
        """Get or create a session for user (Memory Lite)."""
        # Try to get from chat history (persistent)
        if self._chat_history.is_available():
            chat_session = self._chat_history.get_or_create_session(user_id)
            if chat_session:
                self._sessions[user_id] = chat_session.session_id
                return chat_session.session_id
        
        # Fallback to in-memory session
        if user_id not in self._sessions:
            self._sessions[user_id] = uuid4()
        return self._sessions[user_id]
    
    def _extract_user_name(self, message: str) -> Optional[str]:
        """
        Extract user name from message.
        
        Patterns:
        - "tên là X", "tên tôi là X", "mình tên là X"
        - "I'm X", "my name is X", "call me X"
        """
        patterns = [
            r"tên (?:là|tôi là|mình là)\s+(\w+)",
            r"mình tên là\s+(\w+)",
            r"(?:i'm|i am|my name is|call me)\s+(\w+)",
            r"tên\s+(\w+)",
        ]
        
        message_lower = message.lower()
        for pattern in patterns:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                name = match.group(1).capitalize()
                # Filter out common words that aren't names
                if name.lower() not in ["là", "tôi", "mình", "the", "a", "an"]:
                    return name
        return None
    
    def _create_blocked_response(self, issues: List[str]) -> InternalChatResponse:
        """Create response for blocked content."""
        return InternalChatResponse(
            response_id=uuid4(),
            message=self._guardrails.get_refusal_message(),
            agent_type=AgentType.CHAT,
            metadata={"blocked": True, "issues": issues}
        )
    
    def _create_clarification_response(self, content: str) -> InternalChatResponse:
        """Create response requesting clarification."""
        return InternalChatResponse(
            response_id=uuid4(),
            message=content,
            agent_type=AgentType.CHAT,
            metadata={"requires_clarification": True}
        )
    
    def _save_message_async(self, session_id: UUID, role: str, content: str) -> None:
        """
        Save message to chat history (for BackgroundTasks).
        
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 04**
        """
        try:
            self._chat_history.save_message(session_id, role, content)
            logger.debug(f"Background saved {role} message to session {session_id}")
        except Exception as e:
            logger.error(f"Failed to save message in background: {e}")


# Singleton instance
_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get or create ChatService singleton."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
