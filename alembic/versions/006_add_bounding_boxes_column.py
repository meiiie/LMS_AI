"""Add bounding_boxes column to knowledge_embeddings

Revision ID: 006
Revises: 005
Create Date: 2025-12-10

Feature: source-highlight-citation
Adds bounding_boxes JSONB column for PDF text highlighting support.

**Feature: source-highlight-citation**
**Validates: Requirements 3.1, 3.2, 3.3**
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
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
    Add bounding_boxes column to knowledge_embeddings table.
    
    - bounding_boxes: JSONB array of normalized coordinates for PDF highlighting
      Format: [{"x0": 10.5, "y0": 5.2, "x1": 90.3, "y1": 8.7}, ...]
      Coordinates are normalized to percentage (0-100) for responsive display
    
    Also creates GIN index for efficient JSONB querying.
    
    **Feature: source-highlight-citation**
    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    # Add bounding_boxes column if not exists
    if not column_exists('knowledge_embeddings', 'bounding_boxes'):
        op.add_column(
            'knowledge_embeddings',
            sa.Column('bounding_boxes', JSONB, nullable=True, server_default=None)
        )
    
    # Create GIN index for JSONB querying (optional, for future filtering)
    if not index_exists('idx_knowledge_bounding_boxes'):
        op.create_index(
            'idx_knowledge_bounding_boxes',
            'knowledge_embeddings',
            ['bounding_boxes'],
            postgresql_using='gin'
        )


def downgrade() -> None:
    """Remove bounding_boxes column and index."""
    # Drop index first
    if index_exists('idx_knowledge_bounding_boxes'):
        op.drop_index('idx_knowledge_bounding_boxes', table_name='knowledge_embeddings')
    
    # Drop column
    if column_exists('knowledge_embeddings', 'bounding_boxes'):
        op.drop_column('knowledge_embeddings', 'bounding_boxes')
