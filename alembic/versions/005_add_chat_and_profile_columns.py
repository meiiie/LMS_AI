"""Add chat tables and profile columns

Revision ID: 005
Revises: 004
Create Date: 2025-12-10

Adds:
- chat_sessions table (Memory Lite)
- chat_messages table with is_blocked, block_reason columns (CHỈ THỊ SỐ 22)
- learning_profile columns: weak_areas, strong_areas, total_sessions, total_messages, attributes

**Feature: maritime-ai-tutor**
**Spec: CHỈ THỊ SỐ 22 - Memory Isolation**
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    
    # =========================================================================
    # 0. Fix learning_profile.user_id type (UUID -> TEXT for LMS compatibility)
    # =========================================================================
    # Check current type of user_id
    result = conn.execute(sa.text("""
        SELECT data_type FROM information_schema.columns 
        WHERE table_name = 'learning_profile' AND column_name = 'user_id'
    """))
    row = result.fetchone()
    if row and row[0] == 'uuid':
        # Need to change from UUID to TEXT
        # This requires recreating the table or using ALTER TYPE
        # For safety, we'll create a new column and migrate data
        try:
            # Add new text column
            op.add_column('learning_profile', sa.Column('user_id_text', sa.Text(), nullable=True))
            # Copy data (convert UUID to text)
            conn.execute(sa.text("UPDATE learning_profile SET user_id_text = user_id::text"))
            # Drop old primary key
            conn.execute(sa.text("ALTER TABLE learning_profile DROP CONSTRAINT learning_profile_pkey"))
            # Drop old column
            op.drop_column('learning_profile', 'user_id')
            # Rename new column
            op.alter_column('learning_profile', 'user_id_text', new_column_name='user_id')
            # Add primary key back
            conn.execute(sa.text("ALTER TABLE learning_profile ADD PRIMARY KEY (user_id)"))
        except Exception as e:
            # If table is empty or doesn't exist, just continue
            print(f"Note: Could not migrate user_id type: {e}")
    
    # =========================================================================
    # 1. Create chat_sessions table (if not exists)
    # =========================================================================
    
    # Check if chat_sessions exists
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'chat_sessions')"
    ))
    chat_sessions_exists = result.scalar()
    
    if not chat_sessions_exists:
        op.create_table(
            'chat_sessions',
            sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('user_id', sa.String(255), nullable=False),
            sa.Column('user_name', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('session_id')
        )
        op.create_index('idx_chat_sessions_user_id', 'chat_sessions', ['user_id'])
    
    # =========================================================================
    # 2. Create chat_messages table (if not exists)
    # =========================================================================
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'chat_messages')"
    ))
    chat_messages_exists = result.scalar()
    
    if not chat_messages_exists:
        op.create_table(
            'chat_messages',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('role', sa.String(50), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('is_blocked', sa.Boolean(), server_default='false'),
            sa.Column('block_reason', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], ondelete='CASCADE')
        )
        op.create_index('idx_chat_messages_session_id', 'chat_messages', ['session_id'])
        op.create_index('idx_chat_messages_created_at', 'chat_messages', ['created_at'])
        op.create_index('idx_chat_messages_is_blocked', 'chat_messages', ['is_blocked'])
    else:
        # Table exists, add missing columns
        # Check and add is_blocked column
        result = conn.execute(sa.text(
            "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'chat_messages' AND column_name = 'is_blocked')"
        ))
        if not result.scalar():
            op.add_column('chat_messages', sa.Column('is_blocked', sa.Boolean(), server_default='false'))
            op.create_index('idx_chat_messages_is_blocked', 'chat_messages', ['is_blocked'])
        
        # Check and add block_reason column
        result = conn.execute(sa.text(
            "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'chat_messages' AND column_name = 'block_reason')"
        ))
        if not result.scalar():
            op.add_column('chat_messages', sa.Column('block_reason', sa.Text(), nullable=True))
    
    # =========================================================================
    # 3. Add missing columns to learning_profile
    # =========================================================================
    # Check and add attributes column (JSONB for flexible storage)
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'learning_profile' AND column_name = 'attributes')"
    ))
    if not result.scalar():
        op.add_column('learning_profile', sa.Column('attributes', postgresql.JSONB(), server_default='{}'))
    
    # Check and add weak_areas column
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'learning_profile' AND column_name = 'weak_areas')"
    ))
    if not result.scalar():
        op.add_column('learning_profile', sa.Column('weak_areas', postgresql.JSONB(), server_default='[]'))
    
    # Check and add strong_areas column
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'learning_profile' AND column_name = 'strong_areas')"
    ))
    if not result.scalar():
        op.add_column('learning_profile', sa.Column('strong_areas', postgresql.JSONB(), server_default='[]'))
    
    # Check and add total_sessions column
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'learning_profile' AND column_name = 'total_sessions')"
    ))
    if not result.scalar():
        op.add_column('learning_profile', sa.Column('total_sessions', sa.Integer(), server_default='0'))
    
    # Check and add total_messages column
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'learning_profile' AND column_name = 'total_messages')"
    ))
    if not result.scalar():
        op.add_column('learning_profile', sa.Column('total_messages', sa.Integer(), server_default='0'))


def downgrade() -> None:
    # Remove columns from learning_profile
    op.drop_column('learning_profile', 'total_messages')
    op.drop_column('learning_profile', 'total_sessions')
    op.drop_column('learning_profile', 'strong_areas')
    op.drop_column('learning_profile', 'weak_areas')
    op.drop_column('learning_profile', 'attributes')
    
    # Remove columns from chat_messages (if they exist)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'chat_messages' AND column_name = 'is_blocked')"
    ))
    if result.scalar():
        op.drop_index('idx_chat_messages_is_blocked', table_name='chat_messages')
        op.drop_column('chat_messages', 'block_reason')
        op.drop_column('chat_messages', 'is_blocked')
