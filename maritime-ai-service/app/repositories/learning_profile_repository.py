"""
Learning Profile Repository.

This module provides the repository pattern implementation for
Learning Profile persistence operations.

**Feature: wiii**
**Validates: Requirements 6.1, 6.3, 6.4**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 04 - Memory & Personalization**
"""

import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol
from uuid import UUID

from sqlalchemy import text

from app.models.learning_profile import (
    Assessment,
    LearnerLevel,
    LearningProfile,
    LearningStyle,
    create_default_profile,
)

logger = logging.getLogger(__name__)
_LEARNING_PROFILE_MISSING_ORG_WARNING = "learning_profile_blocked_missing_org_context"
_LEARNING_PROFILE_ORG_FILTER = " AND organization_id = :org_id"


@dataclass(frozen=True)
class LearningProfileOrgScope:
    org_id: Optional[str]
    state: str
    warnings: list[str]
    write_allowed: bool


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
        logger.info("Created learning profile for user %s", profile.user_id)
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
        logger.debug("Updated learning profile for user %s", profile.user_id)
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
            logger.info("Deleted learning profile for user %s", user_id)
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
            logger.info("Created default profile for new user %s", user_id)
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


class LearningProfileRepository:
    """
    PostgreSQL implementation of Learning Profile repository.
    
    Uses the learning_profile table created by CHỈ THỊ SỐ 04 SQL script.
    
    **Spec: CHỈ THỊ KỸ THUẬT SỐ 04**
    **Validates: Requirements 6.1, 6.3, 6.4**
    """
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize with SHARED database connection."""
        self._engine = None
        self._session_factory = None
        self._available = False
        self._init_connection()
    
    def _init_connection(self):
        """Initialize database connection using SHARED engine."""
        try:
            # Use SHARED engine to minimize connections
            from app.core.database import get_shared_engine, get_shared_session_factory
            
            self._engine = get_shared_engine()
            self._session_factory = get_shared_session_factory()
            
            # Test connection
            with self._session_factory() as session:
                session.execute(text("SELECT 1"))
            
            self._available = True
            logger.info("Learning profile repository using SHARED database engine")
        except Exception as e:
            logger.warning("Learning profile repository connection failed: %s", e)
            self._available = False
    
    def is_available(self) -> bool:
        """Check if repository is available."""
        return self._available

    def _org_scope(
        self,
        organization_id: Optional[str] = None,
        *,
        write: bool = False,
    ) -> tuple[LearningProfileOrgScope, Optional[str], dict[str, object]]:
        scope = self._resolve_learning_profile_org_scope(
            organization_id=organization_id,
            write=write,
        )
        if not scope.write_allowed or not scope.org_id:
            return scope, None, {}
        return scope, _LEARNING_PROFILE_ORG_FILTER, {"org_id": scope.org_id}

    def _resolve_learning_profile_org_scope(
        self,
        *,
        organization_id: Optional[str] = None,
        write: bool = False,
    ) -> LearningProfileOrgScope:
        if isinstance(organization_id, str) and organization_id.strip():
            return LearningProfileOrgScope(
                org_id=organization_id.strip(),
                state="explicit",
                warnings=[],
                write_allowed=True,
            )

        from app.engine.semantic_memory.write_audit import (
            resolve_memory_read_scope,
            resolve_memory_write_scope,
        )

        scope = resolve_memory_write_scope() if write else resolve_memory_read_scope()
        return LearningProfileOrgScope(
            org_id=scope.org_id,
            state=scope.state,
            warnings=list(scope.warnings),
            write_allowed=scope.write_allowed,
        )

    def _log_learning_profile_scope_blocked(
        self,
        operation: str,
        scope: LearningProfileOrgScope,
        *,
        user_id: Optional[str] = None,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_LEARNING_PROFILE_MISSING_ORG_WARNING)
        logger.warning(
            "[LEARNING_PROFILE] %s blocked user_hash=%s org_hash=%s "
            "org_scope=%s warnings=%s",
            operation,
            _hash_memory_identifier(user_id),
            _hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )
    
    async def get(
        self,
        user_id: str,
        *,
        organization_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Get a learning profile by user ID.

        Args:
            user_id: The user's unique identifier (string from LMS)

        Returns:
            Profile dict if found, None otherwise
        """
        if not self._available:
            return None

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=False,
        )
        if org_filter is None:
            self._log_learning_profile_scope_blocked(
                "get",
                scope,
                user_id=user_id,
            )
            return None

        try:
            user_id_param = str(self._convert_user_id(user_id))
            params: dict = {"user_id": user_id_param, **org_params}

            with self._session_factory() as session:
                result = session.execute(
                    text(f"""
                        SELECT user_id, attributes, weak_areas, strong_areas,
                               total_sessions, total_messages, updated_at,
                               organization_id
                        FROM learning_profile
                        WHERE user_id = :user_id{org_filter}
                    """),
                    params,
                )
                row = result.fetchone()

                if row:
                    return {
                        "user_id": str(row[0]),
                        "attributes": row[1] or {},
                        "weak_areas": row[2] or [],
                        "strong_areas": row[3] or [],
                        "total_sessions": row[4] or 0,
                        "total_messages": row[5] or 0,
                        "updated_at": row[6],
                        "organization_id": row[7],
                    }
                return None
        except Exception as e:
            logger.error("Failed to get learning profile: %s", e)
            return None
    
    def _convert_user_id(self, user_id: str):
        """
        Convert user_id to UUID if it's a valid UUID string.
        Otherwise return as-is for TEXT column compatibility.
        """
        try:
            # Try to parse as UUID
            return UUID(user_id)
        except (ValueError, TypeError):
            # Not a valid UUID, return as string
            # This handles cases like "test-user"
            return user_id
    
    async def create(
        self,
        user_id: str,
        attributes: dict = None,
        *,
        organization_id: Optional[str] = None,
    ) -> Optional[dict]:
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

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_learning_profile_scope_blocked(
                "create",
                scope,
                user_id=user_id,
            )
            return None

        try:
            user_id_param = str(self._convert_user_id(user_id))
            params: dict = {
                "user_id": user_id_param,
                "attributes": json.dumps(attributes or {"level": "beginner"}),
                **org_params,
            }

            with self._session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO learning_profile
                            (organization_id, user_id, attributes)
                        VALUES (:org_id, :user_id, :attributes)
                        ON CONFLICT (organization_id, user_id) DO NOTHING
                    """),
                    params,
                )
                session.commit()
            logger.info(
                "Created learning profile for user_hash=%s org_hash=%s",
                _hash_memory_identifier(user_id),
                _hash_memory_identifier(scope.org_id),
            )
            return await self.get(user_id, organization_id=scope.org_id)
        except Exception as e:
            if "there is no unique or exclusion constraint" in str(e):
                logger.error(
                    "Failed to create learning profile: migration 054 is required "
                    "for ON CONFLICT (organization_id, user_id)"
                )
            else:
                logger.error("Failed to create learning profile: %s", e)
            return None
    
    async def get_or_create(
        self,
        user_id: str,
        *,
        organization_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Get existing profile or create default one.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            Existing or newly created profile dict
        """
        profile = await self.get(user_id, organization_id=organization_id)
        if profile is None:
            profile = await self.create(user_id, organization_id=organization_id)
        return profile
    
    async def update_weak_areas(
        self,
        user_id: str,
        weak_areas: List[str],
        *,
        organization_id: Optional[str] = None,
    ) -> bool:
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

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_learning_profile_scope_blocked(
                "update_weak_areas",
                scope,
                user_id=user_id,
            )
            return False

        try:
            user_id_param = str(self._convert_user_id(user_id))
            params: dict = {
                "user_id": user_id_param,
                "weak_areas": json.dumps(weak_areas),
                **org_params,
            }

            with self._session_factory() as session:
                session.execute(
                    text(f"""
                        UPDATE learning_profile
                        SET weak_areas = :weak_areas, updated_at = NOW()
                        WHERE user_id = :user_id{org_filter}
                    """),
                    params,
                )
                session.commit()
                logger.info(
                    "Updated weak areas for user_hash=%s org_hash=%s",
                    _hash_memory_identifier(user_id),
                    _hash_memory_identifier(scope.org_id),
                )
                return True
        except Exception as e:
            logger.error("Failed to update weak areas: %s", e)
            return False
    
    async def update_strong_areas(
        self,
        user_id: str,
        strong_areas: List[str],
        *,
        organization_id: Optional[str] = None,
    ) -> bool:
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

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_learning_profile_scope_blocked(
                "update_strong_areas",
                scope,
                user_id=user_id,
            )
            return False

        try:
            user_id_param = str(self._convert_user_id(user_id))
            params: dict = {
                "user_id": user_id_param,
                "strong_areas": json.dumps(strong_areas),
                **org_params,
            }

            with self._session_factory() as session:
                session.execute(
                    text(f"""
                        UPDATE learning_profile
                        SET strong_areas = :strong_areas, updated_at = NOW()
                        WHERE user_id = :user_id{org_filter}
                    """),
                    params,
                )
                session.commit()
                logger.info(
                    "Updated strong areas for user_hash=%s org_hash=%s",
                    _hash_memory_identifier(user_id),
                    _hash_memory_identifier(scope.org_id),
                )
                return True
        except Exception as e:
            logger.error("Failed to update strong areas: %s", e)
            return False
    
    async def increment_stats(
        self,
        user_id: str,
        messages: int = 1,
        *,
        organization_id: Optional[str] = None,
    ) -> bool:
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

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_learning_profile_scope_blocked(
                "increment_stats",
                scope,
                user_id=user_id,
            )
            return False

        try:
            profile = await self.get_or_create(user_id, organization_id=scope.org_id)
            if profile is None:
                return False
            user_id_param = str(self._convert_user_id(user_id))
            params: dict = {"user_id": user_id_param, "messages": messages, **org_params}

            with self._session_factory() as session:
                session.execute(
                    text(f"""
                        UPDATE learning_profile
                        SET total_messages = total_messages + :messages,
                            updated_at = NOW()
                        WHERE user_id = :user_id{org_filter}
                    """),
                    params,
                )
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to increment stats: %s", e)
            return False

# Singleton instance
_pg_profile_repo: Optional[LearningProfileRepository] = None


def get_learning_profile_repository() -> LearningProfileRepository:
    """Get or create PostgreSQL LearningProfileRepository singleton."""
    global _pg_profile_repo
    if _pg_profile_repo is None:
        _pg_profile_repo = LearningProfileRepository()
    return _pg_profile_repo


def _hash_memory_identifier(value) -> str | None:
    try:
        from app.engine.semantic_memory.privacy import hash_memory_identifier

        return hash_memory_identifier(value)
    except Exception:
        return None
