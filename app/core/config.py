"""
Configuration Management using Pydantic Settings
Loads configuration from environment variables with validation
Requirements: 9.1
"""
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Application
    app_name: str = Field(default="Maritime AI Tutor", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="development", description="Environment: development, staging, production")
    
    # API Settings
    api_v1_prefix: str = Field(default="/api/v1", description="API version 1 prefix")
    api_key: Optional[str] = Field(default=None, description="API Key for authentication")
    jwt_secret_key: str = Field(default="change-me-in-production", description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expire_minutes: int = Field(default=30, description="JWT token expiration in minutes")
    
    # Rate Limiting
    rate_limit_requests: int = Field(default=100, description="Max requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window in seconds")
    
    # Database - PostgreSQL (Local Docker)
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_user: str = Field(default="maritime", description="PostgreSQL user")
    postgres_password: str = Field(default="maritime_secret", description="PostgreSQL password")
    postgres_db: str = Field(default="maritime_ai", description="PostgreSQL database name")
    
    # Database - Supabase/Cloud (Production)
    database_url: Optional[str] = Field(default=None, description="Full database URL (Supabase/Cloud)")
    supabase_url: Optional[str] = Field(default=None, description="Supabase project URL")
    supabase_key: Optional[str] = Field(default=None, description="Supabase anon key")
    
    # LMS API Key (for authentication from LMS)
    lms_api_key: Optional[str] = Field(default=None, description="API Key for LMS integration")

    
    @property
    def postgres_url(self) -> str:
        """
        Construct PostgreSQL connection URL.
        Prioritizes DATABASE_URL (cloud) over individual settings (local).
        """
        # Use DATABASE_URL if provided (Supabase/Cloud)
        if self.database_url:
            # Convert to asyncpg format if needed
            url = self.database_url
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            return url
        
        # Fallback to local Docker settings
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    @property
    def postgres_url_sync(self) -> str:
        """
        Construct synchronous PostgreSQL connection URL (for Alembic migrations).
        """
        if self.database_url:
            url = self.database_url
            # Ensure it's standard postgresql:// format
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            return url.replace("postgresql+asyncpg://", "postgresql://")
        
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    # Database - Neo4j (Local Docker)
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j connection URI (local or Aura)")
    neo4j_user: str = Field(default="neo4j", description="Neo4j user")
    neo4j_username: Optional[str] = Field(default=None, description="Neo4j username (Aura format)")
    neo4j_password: str = Field(default="neo4j_secret", description="Neo4j password")
    
    @property
    def neo4j_username_resolved(self) -> str:
        """Get Neo4j username (supports both neo4j_user and neo4j_username)"""
        return self.neo4j_username or self.neo4j_user
    
    # LLM Settings - OpenAI/OpenRouter (legacy)
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    openai_base_url: Optional[str] = Field(default=None, description="OpenAI-compatible API base URL (e.g., OpenRouter)")
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model for general tasks")
    openai_model_advanced: str = Field(default="gpt-4o", description="OpenAI model for complex tasks")
    
    # LLM Settings - Google Gemini (primary)
    google_api_key: Optional[str] = Field(default=None, description="Google Gemini API key")
    google_model: str = Field(default="gemini-pro", description="Google Gemini model")
    llm_provider: str = Field(default="google", description="LLM provider: google, openai, openrouter")
    
    # Memori Settings
    memori_enabled: bool = Field(default=True, description="Enable Memori long-term memory")
    memori_namespace_prefix: str = Field(default="user_", description="Memori namespace prefix")
    memori_namespace_suffix: str = Field(default="_maritime", description="Memori namespace suffix")
    memori_summarize_threshold: int = Field(default=10, description="Turns before summarization")
    
    # Vector Store
    chroma_host: str = Field(default="localhost", description="ChromaDB host")
    chroma_port: int = Field(default=8000, description="ChromaDB port")
    
    # Security
    cors_origins: list[str] = Field(default=["*"], description="CORS allowed origins")
    encryption_key: Optional[str] = Field(default=None, description="Encryption key for sensitive data")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or text")
    mask_pii: bool = Field(default=True, description="Mask PII in logs")
    
    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}")
        return v
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.upper()


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Export settings instance for convenience
settings = get_settings()
