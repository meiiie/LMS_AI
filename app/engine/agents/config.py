"""
Agent Configuration - Data classes for agent metadata

SOTA 2025 Pattern: CrewAI-inspired agent configuration
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class AgentCategory(Enum):
    """Agent categories for organization."""
    RETRIEVAL = "retrieval"      # RAG, search agents
    TEACHING = "teaching"        # Tutor, explanation agents
    MEMORY = "memory"            # User context, history agents
    ROUTING = "routing"          # Supervisor, router agents
    GRADING = "grading"          # Quality control agents
    DIRECT = "direct"            # Simple response agents


class AccessLevel(Enum):
    """Agent access levels for safety."""
    READ = "read"                # Read-only operations
    WRITE = "write"              # Can modify data
    ADMIN = "admin"              # Full access


@dataclass
class AgentConfig:
    """
    Agent configuration following CrewAI conventions.
    
    SOTA 2025 Pattern:
    - Explicit role and goal
    - Tool mapping per agent
    - Memory and delegation settings
    """
    
    # Identity (Required)
    id: str                      # Unique identifier, e.g., "rag_agent"
    name: str                    # Display name, e.g., "Maritime RAG Agent"
    role: str                    # Role description
    goal: str                    # Primary objective
    
    # Classification
    category: AgentCategory = AgentCategory.RETRIEVAL
    access_level: AccessLevel = AccessLevel.READ
    
    # Capabilities
    tools: List[str] = field(default_factory=list)        # Tool IDs this agent can use
    persona_file: Optional[str] = None                     # Path to persona YAML
    
    # Behavior
    allow_delegation: bool = False    # Can delegate to other agents
    max_iterations: int = 5           # Safety limit for loops
    verbose: bool = True              # Detailed logging
    
    # Performance
    priority: int = 50                # 0-100, higher = more important
    timeout_seconds: int = 30         # Max execution time
    
    # Metadata
    description: str = ""             # Detailed description
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "goal": self.goal,
            "category": self.category.value,
            "access_level": self.access_level.value,
            "tools": self.tools,
            "persona_file": self.persona_file,
            "allow_delegation": self.allow_delegation,
            "max_iterations": self.max_iterations,
            "priority": self.priority,
            "description": self.description,
            "version": self.version,
            "tags": self.tags
        }


# =============================================================================
# Pre-defined Agent Configurations
# =============================================================================

RAG_AGENT_CONFIG = AgentConfig(
    id="rag_agent",
    name="Maritime RAG Agent",
    role="Knowledge Retrieval Specialist",
    goal="Find accurate maritime regulations and knowledge from the database",
    category=AgentCategory.RETRIEVAL,
    access_level=AccessLevel.READ,
    tools=["tool_maritime_search"],
    persona_file="prompts/agents/rag.yaml",
    allow_delegation=False,
    description="Retrieves and synthesizes maritime knowledge using RAG pipeline",
    tags=["rag", "knowledge", "colregs", "solas"]
)

TUTOR_AGENT_CONFIG = AgentConfig(
    id="tutor_agent",
    name="Maritime Tutor Agent",
    role="Senior Maritime Mentor",
    goal="Guide students in maritime knowledge with engaging, practical teaching",
    category=AgentCategory.TEACHING,
    access_level=AccessLevel.READ,
    tools=["tool_maritime_search", "tool_save_user_info"],
    persona_file="prompts/agents/tutor.yaml",
    allow_delegation=True,
    description="Teaches maritime concepts using real-world examples and Socratic method",
    tags=["tutor", "teaching", "student", "learning"]
)

MEMORY_AGENT_CONFIG = AgentConfig(
    id="memory_agent",
    name="Memory Context Agent",
    role="User Context Manager",
    goal="Retrieve and manage user preferences, history, and personalization",
    category=AgentCategory.MEMORY,
    access_level=AccessLevel.WRITE,
    tools=["tool_get_user_info", "tool_save_user_info", "tool_remember", "tool_forget"],
    persona_file="prompts/agents/memory.yaml",
    allow_delegation=False,
    description="Manages user context, preferences, and conversation history",
    tags=["memory", "context", "personalization", "user"]
)

GRADER_AGENT_CONFIG = AgentConfig(
    id="grader_agent",
    name="Quality Grader Agent",
    role="Response Quality Controller",
    goal="Evaluate and ensure response quality meets standards",
    category=AgentCategory.GRADING,
    access_level=AccessLevel.READ,
    tools=[],
    persona_file=None,
    allow_delegation=False,
    description="Grades agent responses for accuracy, relevance, and helpfulness",
    tags=["grading", "quality", "evaluation"]
)

SUPERVISOR_AGENT_CONFIG = AgentConfig(
    id="supervisor",
    name="Supervisor Agent",
    role="Multi-Agent Orchestrator",
    goal="Route queries to appropriate specialized agents and synthesize results",
    category=AgentCategory.ROUTING,
    access_level=AccessLevel.READ,
    tools=[],
    persona_file=None,
    allow_delegation=True,
    priority=100,  # Highest priority
    description="Coordinates the multi-agent system and manages workflow",
    tags=["supervisor", "routing", "orchestration"]
)

KG_BUILDER_AGENT_CONFIG = AgentConfig(
    id="kg_builder",
    name="KG Builder Agent",
    role="Knowledge Graph Construction Specialist",
    goal="Extract entities and relations from documents to build knowledge graphs",
    category=AgentCategory.RETRIEVAL,
    access_level=AccessLevel.WRITE,
    tools=[],
    persona_file=None,
    allow_delegation=False,
    description="Extracts entities and relations using LLM structured output for Neo4j",
    tags=["kg", "extraction", "neo4j", "document-kg"]
)


# Default configurations for easy access
DEFAULT_AGENT_CONFIGS = {
    "rag_agent": RAG_AGENT_CONFIG,
    "tutor_agent": TUTOR_AGENT_CONFIG,
    "memory_agent": MEMORY_AGENT_CONFIG,
    "grader_agent": GRADER_AGENT_CONFIG,
    "supervisor": SUPERVISOR_AGENT_CONFIG,
    "kg_builder": KG_BUILDER_AGENT_CONFIG
}
