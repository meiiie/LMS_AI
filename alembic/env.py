"""
Alembic migration environment configuration.

This module configures Alembic to work with the Maritime AI Service database models.
"""

import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

# Load .env file
load_dotenv()

# Add the app directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the database models
from app.models.database import Base

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = Base.metadata

# Get database URL from environment or config
def get_url():
    """
    Get database URL from environment variables.
    
    CHỈ THỊ KỸ THUẬT SỐ 19: Ưu tiên DATABASE_URL (Neon/Cloud)
    """
    # Ưu tiên DATABASE_URL (Neon/Cloud)
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Convert to sync driver (psycopg2) for Alembic
        url = database_url
        if "+asyncpg" in url:
            url = url.replace("+asyncpg", "")
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        # Convert ssl=require to sslmode=require for psycopg2
        if "ssl=require" in url:
            url = url.replace("ssl=require", "sslmode=require")
        return url
    
    # Fallback to individual env vars (local Docker)
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5433")
    user = os.getenv("POSTGRES_USER", "maritime")
    password = os.getenv("POSTGRES_PASSWORD", "maritime_secret")
    db = os.getenv("POSTGRES_DB", "maritime_ai")
    
    # Use psycopg2 driver (sync) for alembic
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
