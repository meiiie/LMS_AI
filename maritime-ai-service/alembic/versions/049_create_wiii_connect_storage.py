"""049: create Wiii Connect durable storage.

Adds per-org connection records and an append-only audit ledger for future
external provider adapters. The tables store sanitized control-plane metadata;
raw OAuth tokens and provider secrets must remain in vault/provider-managed
storage.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() "
            "AND table_name = :table_name"
        ),
        {"table_name": table_name},
    )
    return result.fetchone() is not None


def upgrade():
    conn = op.get_bind()

    if not _table_exists(conn, "wiii_connect_connections"):
        op.create_table(
            "wiii_connect_connections",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("organization_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("provider_slug", sa.Text(), nullable=False),
            sa.Column("provider_kind", sa.Text(), nullable=False),
            sa.Column(
                "state",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'disconnected'"),
            ),
            sa.Column(
                "scopes",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "vault_ref",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("account_label", sa.Text(), nullable=True),
            sa.Column("external_account_ref", sa.Text(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column(
                "warnings",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_wiii_connect_connections_org_user_provider",
            "wiii_connect_connections",
            ["organization_id", "user_id", "provider_slug"],
        )
        op.create_index(
            "ix_wiii_connect_connections_provider_state",
            "wiii_connect_connections",
            ["provider_slug", "state"],
        )
        op.create_index(
            "ix_wiii_connect_connections_org_updated",
            "wiii_connect_connections",
            ["organization_id", "updated_at"],
        )

    if not _table_exists(conn, "wiii_connect_audit_ledger"):
        op.create_table(
            "wiii_connect_audit_ledger",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("organization_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("provider_slug", sa.Text(), nullable=False),
            sa.Column("event_kind", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column(
                "surface",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'backend'"),
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_wiii_connect_audit_org_created",
            "wiii_connect_audit_ledger",
            ["organization_id", "created_at"],
        )
        op.create_index(
            "ix_wiii_connect_audit_provider_created",
            "wiii_connect_audit_ledger",
            ["provider_slug", "created_at"],
        )
        op.create_index(
            "ix_wiii_connect_audit_kind_created",
            "wiii_connect_audit_ledger",
            ["event_kind", "created_at"],
        )


def downgrade():
    conn = op.get_bind()

    if _table_exists(conn, "wiii_connect_audit_ledger"):
        op.drop_index(
            "ix_wiii_connect_audit_kind_created",
            table_name="wiii_connect_audit_ledger",
        )
        op.drop_index(
            "ix_wiii_connect_audit_provider_created",
            table_name="wiii_connect_audit_ledger",
        )
        op.drop_index(
            "ix_wiii_connect_audit_org_created",
            table_name="wiii_connect_audit_ledger",
        )
        op.drop_table("wiii_connect_audit_ledger")

    if _table_exists(conn, "wiii_connect_connections"):
        op.drop_index(
            "ix_wiii_connect_connections_org_updated",
            table_name="wiii_connect_connections",
        )
        op.drop_index(
            "ix_wiii_connect_connections_provider_state",
            table_name="wiii_connect_connections",
        )
        op.drop_index(
            "ix_wiii_connect_connections_org_user_provider",
            table_name="wiii_connect_connections",
        )
        op.drop_table("wiii_connect_connections")
