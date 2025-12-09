"""Add sparse search support with tsvector

Revision ID: 004
Revises: 003
Create Date: 2024-12-09 03:00:00.000000

Feature: sparse-search-migration
Requirements: 2.1, 2.2, 2.3, 2.4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    """Add sparse search support with tsvector column and trigger."""
    
    # Add tsvector column for full-text search
    op.add_column('knowledge_embeddings', 
                  sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True))
    
    # Create GIN index for fast full-text search
    op.create_index('idx_knowledge_search_vector', 
                    'knowledge_embeddings', 
                    ['search_vector'], 
                    postgresql_using='gin')
    
    # Create trigger function to auto-generate search_vector
    op.execute("""
        CREATE OR REPLACE FUNCTION update_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Create trigger on INSERT and UPDATE
    op.execute("""
        CREATE TRIGGER trg_update_search_vector
        BEFORE INSERT OR UPDATE ON knowledge_embeddings
        FOR EACH ROW EXECUTE FUNCTION update_search_vector();
    """)
    
    # Populate existing rows with search_vector
    op.execute("""
        UPDATE knowledge_embeddings 
        SET search_vector = to_tsvector('simple', COALESCE(content, ''))
        WHERE search_vector IS NULL;
    """)


def downgrade():
    """Remove sparse search support."""
    
    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS trg_update_search_vector ON knowledge_embeddings;")
    
    # Drop trigger function
    op.execute("DROP FUNCTION IF EXISTS update_search_vector();")
    
    # Drop index
    op.drop_index('idx_knowledge_search_vector', table_name='knowledge_embeddings')
    
    # Drop column
    op.drop_column('knowledge_embeddings', 'search_vector')
