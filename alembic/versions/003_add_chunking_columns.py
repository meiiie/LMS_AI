"""Add semantic chunking columns to knowledge_embeddings

Revision ID: 003
Revises: 002
Create Date: 2025-12-09

Feature: semantic-chunking
Adds content_type and confidence_score columns for semantic chunking support.

**Feature: semantic-chunking**
**Validates: Requirements 4.1, 4.2, 4.3**
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table"""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(index_name: str) -> bool:
    """Check if index exists"""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = inspector.get_indexes('knowledge_embeddings')
    return any(idx['name'] == index_name for idx in indexes)


def upgrade() -> None:
    """
    Add semantic chunking columns to knowledge_embeddings table.
    
    - content_type: Type of content (text, table, heading, diagram_reference, formula)
    - confidence_score: Confidence score for the chunk (0.0-1.0)
    
    Also creates indexes for efficient querying.
    """
    # Add content_type column if not exists
    if not column_exists('knowledge_embeddings', 'content_type'):
        op.add_column(
            'knowledge_embeddings',
            sa.Column('content_type', sa.String(50), nullable=True, server_default='text')
        )
    
    # Add confidence_score column if not exists
    if not column_exists('knowledge_embeddings', 'confidence_score'):
        op.add_column(
            'knowledge_embeddings',
            sa.Column('confidence_score', sa.Float(), nullable=True, server_default='1.0')
        )
    
    # Create composite index for chunk ordering (document_id, page_number, chunk_index)
    if not index_exists('idx_knowledge_chunks_ordering'):
        op.create_index(
            'idx_knowledge_chunks_ordering',
            'knowledge_embeddings',
            ['document_id', 'page_number', 'chunk_index']
        )
    
    # Create index for content type filtering
    if not index_exists('idx_knowledge_chunks_content_type'):
        op.create_index(
            'idx_knowledge_chunks_content_type',
            'knowledge_embeddings',
            ['content_type']
        )
    
    # Create index for confidence score filtering
    if not index_exists('idx_knowledge_chunks_confidence'):
        op.create_index(
            'idx_knowledge_chunks_confidence',
            'knowledge_embeddings',
            ['confidence_score']
        )


def downgrade() -> None:
    """Remove semantic chunking columns and indexes."""
    # Drop indexes first
    op.drop_index('idx_knowledge_chunks_confidence', table_name='knowledge_embeddings')
    op.drop_index('idx_knowledge_chunks_content_type', table_name='knowledge_embeddings')
    op.drop_index('idx_knowledge_chunks_ordering', table_name='knowledge_embeddings')
    
    # Drop columns
    op.drop_column('knowledge_embeddings', 'confidence_score')
    op.drop_column('knowledge_embeddings', 'content_type')
