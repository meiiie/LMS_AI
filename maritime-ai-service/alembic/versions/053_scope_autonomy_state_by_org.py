"""Scope Wiii autonomy state by organization.

Revision ID: 053
Revises: 052
Create Date: 2026-05-31

Existing legacy rows are backfilled to the default organization. Downgrade
collapses per-org autonomy keys back to one row per key; back up the table
first if per-org graduation state must be preserved.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    inspector = inspect(conn)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "wiii_autonomy_state"):
        return

    if not _column_exists(conn, "wiii_autonomy_state", "organization_id"):
        op.add_column(
            "wiii_autonomy_state",
            sa.Column("organization_id", sa.Text(), nullable=True),
        )

    conn.execute(
        text(
            "UPDATE wiii_autonomy_state "
            "SET organization_id = 'default' "
            "WHERE organization_id IS NULL"
        )
    )

    op.alter_column(
        "wiii_autonomy_state",
        "organization_id",
        server_default="default",
        nullable=False,
    )

    conn.execute(text("ALTER TABLE wiii_autonomy_state DROP CONSTRAINT IF EXISTS wiii_autonomy_state_pkey"))
    conn.execute(
        text(
            "ALTER TABLE wiii_autonomy_state "
            "ADD CONSTRAINT pk_wiii_autonomy_state_org_key "
            "PRIMARY KEY (organization_id, key)"
        )
    )
    op.create_index(
        "ix_wiii_autonomy_state_org_updated",
        "wiii_autonomy_state",
        ["organization_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "wiii_autonomy_state"):
        return

    if _column_exists(conn, "wiii_autonomy_state", "organization_id"):
        op.drop_index(
            "ix_wiii_autonomy_state_org_updated",
            table_name="wiii_autonomy_state",
        )
        conn.execute(
            text(
                "DELETE FROM wiii_autonomy_state s "
                "USING wiii_autonomy_state d "
                "WHERE s.key = d.key "
                "AND s.organization_id <> 'default' "
                "AND d.organization_id = 'default'"
            )
        )
        conn.execute(
            text(
                "UPDATE wiii_autonomy_state "
                "SET organization_id = 'default' "
                "WHERE organization_id <> 'default'"
            )
        )
        conn.execute(
            text(
                "DELETE FROM wiii_autonomy_state a "
                "USING wiii_autonomy_state b "
                "WHERE a.key = b.key "
                "AND a.ctid < b.ctid"
            )
        )
        conn.execute(text("ALTER TABLE wiii_autonomy_state DROP CONSTRAINT IF EXISTS pk_wiii_autonomy_state_org_key"))
        conn.execute(
            text(
                "ALTER TABLE wiii_autonomy_state "
                "ADD CONSTRAINT wiii_autonomy_state_pkey PRIMARY KEY (key)"
            )
        )
        op.drop_column("wiii_autonomy_state", "organization_id")
