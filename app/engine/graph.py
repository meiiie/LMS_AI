"""
Agent Orchestrator using LangGraph.

This module implements the agent orchestration layer that routes
user messages to appropriate specialized agents based on intent.

**Feature: maritime-ai-tutor**
**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Types of agents in the system."""
    CHAT = "chat"      # General conversation
    RAG = "rag"        # Knowledge retrieval
    TUTOR = "tutor"    # Teaching and assessment


class IntentType(str, Enum):
    """Types of user intents."""
    GENERAL = "GENERAL"      # General conversation
    KNOWLEDGE = "KNOWLEDGE"  # Maritime knowledge queries
    TEACHING = "TEACHING"    # Learning/teaching requests
    UNCLEAR = "UNCLEAR"      # Intent not clear


class Entity(BaseModel):
    """Extracted entity from user message."""
    name: str = Field(..., min_length=1)
    entity_type: str = Field(..., min_length=1)
    value: str = Field(default="")


class Intent(BaseModel):
    """
    Classified intent from user message.
    
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    type: IntentType = Field(..., description="Classified intent type")
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0,
        description="Classification confidence"
    )
    entities: List[Entity] = Field(
        default_factory=list,
        description="Extracted entities"
    )
    
    def is_confident(self, threshold: float = 0.7) -> bool:
        """Check if confidence meets threshold."""
        return self.confidence >= threshold
    
    def requires_clarification(self) -> bool:
        """Check if clarification is needed."""
        return self.confidence < 0.7 or self.type == IntentType.UNCLEAR


class AgentState(TypedDict, total=False):
    """
    State maintained across agent interactions.
    
    Uses TypedDict for LangGraph compatibility.
    
    **Validates: Requirements 2.5**
    """
    user_id: str
    messages: List[Dict[str, Any]]
    current_agent: str
    memory_context: Optional[Dict[str, Any]]
    learning_profile: Optional[Dict[str, Any]]
    intent: Optional[Dict[str, Any]]
    confidence: float
    session_id: str
    turn_count: int


# Intent classification keywords
KNOWLEDGE_KEYWORDS = {
    "solas", "colregs", "marpol", "regulation", "rule", "chapter",
    "convention", "imo", "safety", "navigation", "collision",
    "fire", "lifesaving", "pollution", "certificate", "inspection"
}

TEACHING_KEYWORDS = {
    "teach", "learn", "explain", "understand", "quiz", "test",
    "assessment", "practice", "exercise", "study", "lesson",
    "course", "training", "help me understand", "what is"
}


class IntentClassifier:
    """
    Classifies user intent for agent routing.
    
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    
    CONFIDENCE_THRESHOLD = 0.7
    
    def classify(self, message: str) -> Intent:
        """
        Classify the intent of a user message.
        
        Args:
            message: User's message text
            
        Returns:
            Intent with type and confidence
            
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        message_lower = message.lower()
        words = set(message_lower.split())
        
        # Calculate keyword matches
        knowledge_score = len(words & KNOWLEDGE_KEYWORDS)
        teaching_score = len(words & TEACHING_KEYWORDS)
        
        # Check for teaching phrases
        teaching_phrases = ["teach me", "help me learn", "explain to me", "what is"]
        for phrase in teaching_phrases:
            if phrase in message_lower:
                teaching_score += 2
        
        # Determine intent - ensure confidence >= 0.7 when keywords match
        if teaching_score > knowledge_score and teaching_score > 0:
            # Base confidence 0.7, increase with more matches
            confidence = min(0.7 + (teaching_score * 0.1), 1.0)
            return Intent(
                type=IntentType.TEACHING,
                confidence=confidence,
                entities=self._extract_entities(message)
            )
        elif knowledge_score > 0:
            # Base confidence 0.7, increase with more matches
            confidence = min(0.7 + (knowledge_score * 0.1), 1.0)
            return Intent(
                type=IntentType.KNOWLEDGE,
                confidence=confidence,
                entities=self._extract_entities(message)
            )
        else:
            # Default to general conversation
            return Intent(
                type=IntentType.GENERAL,
                confidence=0.8,
                entities=[]
            )
    
    def _extract_entities(self, message: str) -> List[Entity]:
        """Extract entities from message."""
        entities = []
        message_lower = message.lower()
        
        # Extract regulation references
        for keyword in KNOWLEDGE_KEYWORDS:
            if keyword in message_lower:
                entities.append(Entity(
                    name=keyword,
                    entity_type="maritime_term",
                    value=keyword
                ))
        
        return entities[:5]  # Limit to 5 entities


class AgentRouter:
    """
    Routes messages to appropriate agents based on intent.
    
    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    
    INTENT_TO_AGENT = {
        IntentType.GENERAL: AgentType.CHAT,
        IntentType.KNOWLEDGE: AgentType.RAG,
        IntentType.TEACHING: AgentType.TUTOR,
        IntentType.UNCLEAR: None,  # Requires clarification
    }
    
    def route(self, intent: Intent) -> Optional[AgentType]:
        """
        Route to appropriate agent based on intent.
        
        Args:
            intent: Classified intent
            
        Returns:
            AgentType to route to, or None if clarification needed
            
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        if intent.requires_clarification():
            return None
        
        return self.INTENT_TO_AGENT.get(intent.type, AgentType.CHAT)
    
    def get_clarification_message(self) -> str:
        """Get message to request clarification from user."""
        return (
            "I'm not quite sure what you're looking for. Could you please clarify?\n\n"
            "Are you:\n"
            "- Looking for specific maritime regulations or information?\n"
            "- Wanting to learn about a maritime topic?\n"
            "- Just having a general conversation?"
        )


@dataclass
class OrchestratorResponse:
    """Response from the orchestrator."""
    content: str
    agent_type: AgentType
    intent: Intent
    requires_clarification: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentOrchestrator:
    """
    Main orchestrator that coordinates agent interactions.
    
    Uses LangGraph-style state management for conversation flow.
    
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
    """
    
    def __init__(self):
        """Initialize orchestrator with classifier and router."""
        self._classifier = IntentClassifier()
        self._router = AgentRouter()
        self._states: Dict[str, AgentState] = {}  # Session states
    
    def get_or_create_state(self, session_id: str, user_id: str) -> AgentState:
        """
        Get existing state or create new one.
        
        **Validates: Requirements 2.5**
        """
        if session_id not in self._states:
            self._states[session_id] = AgentState(
                user_id=user_id,
                messages=[],
                current_agent=AgentType.CHAT.value,
                memory_context=None,
                learning_profile=None,
                intent=None,
                confidence=0.0,
                session_id=session_id,
                turn_count=0
            )
        return self._states[session_id]
    
    def process_message(
        self, 
        message: str, 
        session_id: str,
        user_id: str
    ) -> OrchestratorResponse:
        """
        Process a user message and route to appropriate agent.
        
        Args:
            message: User's message
            session_id: Current session ID
            user_id: User's ID
            
        Returns:
            OrchestratorResponse with routing decision
            
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        # Get or create state
        state = self.get_or_create_state(session_id, user_id)
        
        # Classify intent
        intent = self._classifier.classify(message)
        
        # Update state
        state["messages"].append({"role": "user", "content": message})
        state["intent"] = intent.model_dump()
        state["confidence"] = intent.confidence
        state["turn_count"] = state.get("turn_count", 0) + 1
        
        # Route to agent
        agent_type = self._router.route(intent)
        
        if agent_type is None:
            # Clarification needed
            return OrchestratorResponse(
                content=self._router.get_clarification_message(),
                agent_type=AgentType.CHAT,
                intent=intent,
                requires_clarification=True
            )
        
        # Update current agent
        state["current_agent"] = agent_type.value
        
        # Generate placeholder response (actual agent would process)
        content = self._generate_placeholder_response(agent_type, message)
        
        return OrchestratorResponse(
            content=content,
            agent_type=agent_type,
            intent=intent,
            requires_clarification=False,
            metadata={"turn_count": state["turn_count"]}
        )
    
    def _generate_placeholder_response(
        self, 
        agent_type: AgentType, 
        message: str
    ) -> str:
        """Generate placeholder response for testing."""
        if agent_type == AgentType.RAG:
            return f"[RAG Agent] Searching knowledge base for: {message}"
        elif agent_type == AgentType.TUTOR:
            return f"[Tutor Agent] Starting teaching session about: {message}"
        else:
            return f"[Chat Agent] Processing: {message}"
    
    def clear_session(self, session_id: str) -> bool:
        """Clear a session state."""
        if session_id in self._states:
            del self._states[session_id]
            return True
        return False
