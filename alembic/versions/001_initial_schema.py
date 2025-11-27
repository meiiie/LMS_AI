"""Initial database schema

Revision ID: 001
Revises: 
Create Date: 2024-01-15

Creates the initial database tables:
- memori_store: User memory storage
- learning_profile: User learning profiles
- conversation_session: Conversation tracking

**Feature: maritime-ai-tutor**
**Validates: Requirements 3.5, 6.4**
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create memori_store table
    op.create_table(
        'memori_store',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('namespace', sa.String(255), nullable=False),
        sa.Column('memory_type', sa.String(50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('entities', postgresql.JSONB(), server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_memori_namespace', 'memori_store', ['namespace'])
    
    # Create learning_profile table
    op.create_table(
        'learning_profile',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('current_level', sa.String(20), server_default='CADET', nullable=False),
        sa.Column('learning_style', sa.String(20), nullable=True),
        sa.Column('weak_topics', postgresql.JSONB(), server_default='[]'),
        sa.Column('completed_topics', postgresql.JSONB(), server_default='[]'),
        sa.Column('assessment_history', postgresql.JSONB(), server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('user_id')
    )
    
    # Create conversation_session table
    op.create_table(
        'conversation_session',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('turn_count', sa.Integer(), server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['learning_profile.user_id'])
    )
    op.create_index('idx_session_user_id', 'conversation_session', ['user_id'])


def downgrade() -> None:
    op.drop_index('idx_session_user_id', table_name='conversation_session')
    op.drop_table('conversation_session')
    op.drop_table('learning_profile')
    op.drop_index('idx_memori_namespace', table_name='memori_store')
    op.drop_table('memori_store')
