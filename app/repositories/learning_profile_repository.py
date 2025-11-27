"""
Learning Profile Repository.

This module provides the repository pattern implementation for
Learning Profile persistence operations.

**Feature: maritime-ai-tutor**
**Validates: Requirements 6.1, 6.3, 6.4**
"""

import logging
from typing import Dict, Optional, Protocol
from uuid import UUID

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
