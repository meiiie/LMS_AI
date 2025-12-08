"""Add multimodal columns to knowledge_embeddings

Revision ID: 002
Revises: 001
Create Date: 2025-12-08

CHỈ THỊ KỸ THUẬT SỐ 26: Multimodal RAG Vision
Creates knowledge_embeddings table and adds multimodal columns.

**Feature: multimodal-rag-vision**
**Validates: Requirements 5.1, 5.2**
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if table exists in database"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """
    Create knowledge_embeddings table with multimodal columns.
    
    - image_url: URL to the page image stored in Supabase Storage
    - page_number: Page number in the original PDF document
    - document_id: Identifier for the source document
    """
    # Create knowledge_embeddings table if not exists
    if not table_exists('knowledge_embeddings'):
        op.create_table(
            'knowledge_embeddings',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=True),
            sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
            sa.Column('source', sa.String(255), nullable=True),
            sa.Column('chunk_index', sa.Integer(), nullable=True),
            sa.Column('image_url', sa.Text(), nullable=True),
            sa.Column('page_number', sa.Integer(), nullable=True),
            sa.Column('document_id', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id')
        )
        
        # Create indexes
        op.create_index('idx_knowledge_embeddings_source', 'knowledge_embeddings', ['source'])
        op.create_index('idx_knowledge_embeddings_page', 'knowledge_embeddings', ['page_number'])
        op.create_index('idx_knowledge_embeddings_document', 'knowledge_embeddings', ['document_id', 'page_number'])
        op.create_index(
            'idx_knowledge_embeddings_image_url',
            'knowledge_embeddings',
            ['image_url'],
            postgresql_where=sa.text('image_url IS NOT NULL')
        )
    else:
        # Table exists, just add new columns
        # Add image_url column
        op.add_column(
            'knowledge_embeddings',
            sa.Column('image_url', sa.Text(), nullable=True)
        )
        
        # Add page_number column
        op.add_column(
            'knowledge_embeddings',
            sa.Column('page_number', sa.Integer(), nullable=True)
        )
        
        # Add document_id column (for grouping pages by document)
        op.add_column(
            'knowledge_embeddings',
            sa.Column('document_id', sa.String(255), nullable=True)
        )
        
        # Create index for page lookup
        op.create_index(
            'idx_knowledge_embeddings_page',
            'knowledge_embeddings',
            ['page_number']
        )
        
        # Create index for document grouping
        op.create_index(
            'idx_knowledge_embeddings_document',
            'knowledge_embeddings',
            ['document_id', 'page_number']
        )
        
        # Create index for image_url (for checking existence)
        op.create_index(
            'idx_knowledge_embeddings_image_url',
            'knowledge_embeddings',
            ['image_url'],
            postgresql_where=sa.text('image_url IS NOT NULL')
        )


def downgrade() -> None:
    """Remove multimodal columns from knowledge_embeddings table."""
    # Drop indexes first
    op.drop_index('idx_knowledge_embeddings_image_url', table_name='knowledge_embeddings')
    op.drop_index('idx_knowledge_embeddings_document', table_name='knowledge_embeddings')
    op.drop_index('idx_knowledge_embeddings_page', table_name='knowledge_embeddings')
    
    # Drop columns
    op.drop_column('knowledge_embeddings', 'document_id')
    op.drop_column('knowledge_embeddings', 'page_number')
    op.drop_column('knowledge_embeddings', 'image_url')
