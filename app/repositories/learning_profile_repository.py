"""
Learning Profile Repository.

This module provides the repository pattern implementation for
Learning Profile persistence operations.

**Feature: maritime-ai-tutor**
**Validates: Requirements 6.1, 6.3, 6.4**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 04 - Memory & Personalization**
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.learning_profile import (
    Assessment,
    LearnerLevel,
    LearningProfile,
    LearningStyle,
    create_default_profile,
)

logger = logging.getLogger(__name__)


class ILearningProfileRepository(Protocol):
    """
    Interface for Learning Profile repository operations.
    
    Defines the contract for CRUD operations on learning profiles.
    """
    
    async def get(self, user_id: UUID) -> Optional[LearningProfile]:
        """Get a learning profile by user ID."""
        ...
    
    async def create(self, profile: LearningProfile) -> LearningProfile:
        """Create a new learning profile."""
        ...
    
    async def update(self, profile: LearningProfile) -> LearningProfile:
        """Update an existing learning profile."""
        ...
    
    async def delete(self, user_id: UUID) -> bool:
        """Delete a learning profile."""
        ...
    
    async def get_or_create(self, user_id: UUID) -> LearningProfile:
        """Get existing profile or create default one."""
        ...


class InMemoryLearningProfileRepository:
    """
    In-memory implementation of Learning Profile repository.
    
    Used for development and testing. Production should use
    PostgreSQL-backed implementation.
    
    **Validates: Requirements 6.1, 6.3, 6.4**
    """
    
    def __init__(self):
        """Initialize with empty storage."""
        self._profiles: Dict[UUID, LearningProfile] = {}
    
    async def get(self, user_id: UUID) -> Optional[LearningProfile]:
        """
        Get a learning profile by user ID.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            LearningProfile if found, None otherwise
            
        **Validates: Requirements 6.3**
        """
        return self._profiles.get(user_id)

    
    async def create(self, profile: LearningProfile) -> LearningProfile:
        """
        Create a new learning profile.
        
        Args:
            profile: The profile to create
            
        Returns:
            The created profile
            
        Raises:
            ValueError: If profile already exists
        """
        if profile.user_id in self._profiles:
            raise ValueError(f"Profile already exists for user {profile.user_id}")
        
        self._profiles[profile.user_id] = profile
        logger.info(f"Created learning profile for user {profile.user_id}")
        return profile
    
    async def update(self, profile: LearningProfile) -> LearningProfile:
        """
        Update an existing learning profile.
        
        Args:
            profile: The profile with updated data
            
        Returns:
            The updated profile
            
        **Validates: Requirements 6.4**
        """
        self._profiles[profile.user_id] = profile
        logger.debug(f"Updated learning profile for user {profile.user_id}")
        return profile
    
    async def delete(self, user_id: UUID) -> bool:
        """
        Delete a learning profile.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            True if deleted, False if not found
        """
        if user_id in self._profiles:
            del self._profiles[user_id]
            logger.info(f"Deleted learning profile for user {user_id}")
            return True
        return False
    
    async def get_or_create(self, user_id: UUID) -> LearningProfile:
        """
        Get existing profile or create default one.
        
        This is the primary method for ensuring a user has a profile.
        Creates with default values if not exists.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            Existing or newly created LearningProfile
            
        **Validates: Requirements 6.1**
        """
        profile = await self.get(user_id)
        if profile is None:
            profile = create_default_profile(user_id)
            await self.create(profile)
            logger.info(f"Created default profile for new user {user_id}")
        return profile
    
    async def add_assessment(
        self, 
        user_id: UUID, 
        assessment: Assessment
    ) -> LearningProfile:
        """
        Add an assessment to a user's profile.
        
        Automatically updates weak_topics and completed_topics.
        
        Args:
            user_id: The user's unique identifier
            assessment: The assessment to add
            
        Returns:
            Updated LearningProfile
            
        **Validates: Requirements 6.2**
        """
        profile = await self.get_or_create(user_id)
        profile.add_assessment(assessment)
        return await self.update(profile)
    
    async def update_level(
        self, 
        user_id: UUID, 
        level: LearnerLevel
    ) -> LearningProfile:
        """
        Update a user's proficiency level.
        
        Args:
            user_id: The user's unique identifier
            level: The new level
            
        Returns:
            Updated LearningProfile
        """
        profile = await self.get_or_create(user_id)
        profile.current_level = level
        return await self.update(profile)
    
    async def update_learning_style(
        self, 
        user_id: UUID, 
        style: LearningStyle
    ) -> LearningProfile:
        """
        Update a user's learning style preference.
        
        Args:
            user_id: The user's unique identifier
            style: The preferred learning style
            
        Returns:
            Updated LearningProfile
        """
        profile = await self.get_or_create(user_id)
        profile.learning_style = style
        return await self.update(profile)
    
    def count(self) -> int:
        """Get total number of profiles."""
        return len(self._profiles)
    
    def clear(self) -> None:
        """Clear all profiles (for testing)."""
        self._profiles.clear()


class SupabaseLearningProfileRepository:
    """
    Supabase PostgreSQL implementation of Learning Profile repository.
    
    Uses the learning_profile table created by CHỈ THỊ SỐ 04 SQL script.
    
    **Spec: CHỈ THỊ KỸ THUẬT SỐ 04**
    **Validates: Requirements 6.1, 6.3, 6.4**
    """
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize with database connection."""
        self._database_url = database_url or settings.postgres_url_sync
        self._engine = None
        self._session_factory = None
        self._available = False
        self._init_connection()
    
    def _init_connection(self):
        """Initialize database connection."""
        try:
            self._engine = create_engine(
                self._database_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=3,        # Limit connections for Supabase Free Tier
                max_overflow=0,     # No extra connections
                pool_timeout=30,    # Wait 30s for connection
                pool_recycle=1800   # Recycle connections after 30 minutes
            )
            self._session_factory = sessionmaker(bind=self._engine)
            
            # Test connection
            with self._session_factory() as session:
                session.execute(text("SELECT 1"))
            
            self._available = True
            logger.info("Learning profile repository connected to Supabase")
        except Exception as e:
            logger.warning(f"Learning profile repository connection failed: {e}")
            self._available = False
    
    def is_available(self) -> bool:
        """Check if repository is available."""
        return self._available
    
    async def get(self, user_id: str) -> Optional[dict]:
        """
        Get a learning profile by user ID.
        
        Args:
            user_id: The user's unique identifier (string from LMS)
            
        Returns:
            Profile dict if found, None otherwise
        """
        if not self._available:
            return None
        
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text("""
                        SELECT user_id, attributes, weak_areas, strong_areas, 
                               total_sessions, total_messages, updated_at
                        FROM learning_profile
                        WHERE user_id = :user_id
                    """),
                    {"user_id": user_id}
                )
                row = result.fetchone()
                
                if row:
                    return {
                        "user_id": row[0],
                        "attributes": row[1] or {},
                        "weak_areas": row[2] or [],
                        "strong_areas": row[3] or [],
                        "total_sessions": row[4] or 0,
                        "total_messages": row[5] or 0,
                        "updated_at": row[6]
                    }
                return None
        except Exception as e:
            logger.error(f"Failed to get learning profile: {e}")
            return None
    
    async def create(self, user_id: str, attributes: dict = None) -> Optional[dict]:
        """
        Create a new learning profile.
        
        Args:
            user_id: The user's unique identifier
            attributes: Initial attributes (level, style, language)
            
        Returns:
            The created profile dict
        """
        if not self._available:
            return None
        
        try:
            with self._session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO learning_profile (user_id, attributes)
                        VALUES (:user_id, :attributes)
                        ON CONFLICT (user_id) DO NOTHING
                    """),
                    {
                        "user_id": user_id,
                        "attributes": json.dumps(attributes or {"level": "beginner"})
                    }
                )
                session.commit()
                logger.info(f"Created learning profile for user {user_id}")
                return await self.get(user_id)
        except Exception as e:
            logger.error(f"Failed to create learning profile: {e}")
            return None
    
    async def get_or_create(self, user_id: str) -> Optional[dict]:
        """
        Get existing profile or create default one.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            Existing or newly created profile dict
        """
        profile = await self.get(user_id)
        if profile is None:
            profile = await self.create(user_id)
        return profile
    
    async def update_weak_areas(self, user_id: str, weak_areas: List[str]) -> bool:
        """
        Update user's weak areas.
        
        Args:
            user_id: The user's unique identifier
            weak_areas: List of weak topic names
            
        Returns:
            True if successful
        """
        if not self._available:
            return False
        
        try:
            with self._session_factory() as session:
                session.execute(
                    text("""
                        UPDATE learning_profile
                        SET weak_areas = :weak_areas, updated_at = NOW()
                        WHERE user_id = :user_id
                    """),
                    {
                        "user_id": user_id,
                        "weak_areas": json.dumps(weak_areas)
                    }
                )
                session.commit()
                logger.info(f"Updated weak areas for user {user_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to update weak areas: {e}")
            return False
    
    async def update_strong_areas(self, user_id: str, strong_areas: List[str]) -> bool:
        """
        Update user's strong areas.
        
        Args:
            user_id: The user's unique identifier
            strong_areas: List of strong topic names
            
        Returns:
            True if successful
        """
        if not self._available:
            return False
        
        try:
            with self._session_factory() as session:
                session.execute(
                    text("""
                        UPDATE learning_profile
                        SET strong_areas = :strong_areas, updated_at = NOW()
                        WHERE user_id = :user_id
                    """),
                    {
                        "user_id": user_id,
                        "strong_areas": json.dumps(strong_areas)
                    }
                )
                session.commit()
                logger.info(f"Updated strong areas for user {user_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to update strong areas: {e}")
            return False
    
    async def increment_stats(self, user_id: str, messages: int = 1) -> bool:
        """
        Increment user's message count.
        
        Args:
            user_id: The user's unique identifier
            messages: Number of messages to add
            
        Returns:
            True if successful
        """
        if not self._available:
            return False
        
        try:
            # Ensure profile exists
            await self.get_or_create(user_id)
            
            with self._session_factory() as session:
                session.execute(
                    text("""
                        UPDATE learning_profile
                        SET total_messages = total_messages + :messages,
                            updated_at = NOW()
                        WHERE user_id = :user_id
                    """),
                    {"user_id": user_id, "messages": messages}
                )
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to increment stats: {e}")
            return False


# Singleton instance
_supabase_profile_repo: Optional[SupabaseLearningProfileRepository] = None


def get_learning_profile_repository() -> SupabaseLearningProfileRepository:
    """Get or create SupabaseLearningProfileRepository singleton."""
    global _supabase_profile_repo
    if _supabase_profile_repo is None:
        _supabase_profile_repo = SupabaseLearningProfileRepository()
    return _supabase_profile_repo
