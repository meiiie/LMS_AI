"""056: create Wiii Connect operation approval ledger.

Adds a durable replay ledger for preview/apply connector mutations. The table
stores only control-plane identifiers, request fingerprints, status, and safe
metadata. Raw post text, page IDs, connection refs, provider payloads, media,
and approval tokens must not be written here.

Downgrade drops only this ledger. Existing connection and audit rows remain
intact; previews issued before downgrade fall back to stateless token checks.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def _constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = current_schema() "
            "AND table_name = :table_name "
            "AND constraint_name = :constraint_name"
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    )
    return result.fetchone() is not None


def _index_exists(conn, index_name: str) -> bool:
    result = conn.execute(
        text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND indexname = :index_name"
        ),
        {"index_name": index_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "wiii_connect_operation_approvals"):
        op.create_table(
            "wiii_connect_operation_approvals",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("organization_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("provider_slug", sa.Text(), nullable=False),
            sa.Column("action_slug", sa.Text(), nullable=False),
            sa.Column("preview_evidence_id", sa.Text(), nullable=False),
            sa.Column("request_fingerprint", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column(
                "reason",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'preview_recorded'"),
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.PrimaryKeyConstraint("id"),
        )

    if not _constraint_exists(
        conn,
        "wiii_connect_operation_approvals",
        "uq_wiii_connect_operation_approval_preview",
    ):
        op.create_unique_constraint(
            "uq_wiii_connect_operation_approval_preview",
            "wiii_connect_operation_approvals",
            ["organization_id", "user_id", "provider_slug", "preview_evidence_id"],
        )

    if not _index_exists(conn, "ix_wiii_connect_operation_approval_status_expiry"):
        op.create_index(
            "ix_wiii_connect_operation_approval_status_expiry",
            "wiii_connect_operation_approvals",
            ["organization_id", "status", "expires_at"],
        )
    if not _index_exists(conn, "ix_wiii_connect_operation_approval_action_status"):
        op.create_index(
            "ix_wiii_connect_operation_approval_action_status",
            "wiii_connect_operation_approvals",
            ["provider_slug", "action_slug", "status"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    table_name = "wiii_connect_operation_approvals"
    if not _table_exists(conn, table_name):
        return

    if _index_exists(conn, "ix_wiii_connect_operation_approval_action_status"):
        op.drop_index(
            "ix_wiii_connect_operation_approval_action_status",
            table_name=table_name,
        )
    if _index_exists(conn, "ix_wiii_connect_operation_approval_status_expiry"):
        op.drop_index(
            "ix_wiii_connect_operation_approval_status_expiry",
            table_name=table_name,
        )
    if _constraint_exists(
        conn,
        table_name,
        "uq_wiii_connect_operation_approval_preview",
    ):
        op.drop_constraint(
            "uq_wiii_connect_operation_approval_preview",
            table_name,
            type_="unique",
        )
    op.drop_table(table_name)
