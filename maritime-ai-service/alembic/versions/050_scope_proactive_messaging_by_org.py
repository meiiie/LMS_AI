"""050: scope proactive messaging tables by organization.

Proactive outreach is an autonomous-action surface. The message log and
opt-out preference rows must carry tenant scope before runtime code can safely
send, suppress, or audit messages in multi-tenant deployments.

Existing legacy rows are backfilled to the default organization. Downgrading
from the per-org preference key back to the legacy per-user key keeps one row
per user and can discard non-default duplicate preference rows; take a table
backup first if per-org opt-out history must be preserved.
"""

from alembic import op
import sqlalchemy as sa


revision = "050"
down_revision = "049"
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


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = :table_name "
            "AND column_name = :column_name"
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return result.fetchone() is not None


def _index_exists(conn, index_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND indexname = :index_name"
        ),
        {"index_name": index_name},
    )
    return result.fetchone() is not None


def _primary_key_names(conn, table_name: str) -> list[str]:
    result = conn.execute(
        sa.text(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_schema = current_schema() "
            "AND table_name = :table_name "
            "AND constraint_type = 'PRIMARY KEY'"
        ),
        {"table_name": table_name},
    )
    return [row[0] for row in result.fetchall()]


def _add_org_column(conn, table_name: str) -> None:
    if not _column_exists(conn, table_name, "organization_id"):
        op.add_column(
            table_name,
            sa.Column(
                "organization_id",
                sa.Text(),
                nullable=True,
                server_default=sa.text("'default'"),
            ),
        )

    op.execute(
        sa.text(
            f"UPDATE {table_name} "
            "SET organization_id = 'default' "
            "WHERE organization_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            f"ALTER TABLE {table_name} "
            "ALTER COLUMN organization_id SET DEFAULT 'default'"
        )
    )
    op.execute(
        sa.text(
            f"ALTER TABLE {table_name} "
            "ALTER COLUMN organization_id SET NOT NULL"
        )
    )


def upgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "wiii_proactive_messages"):
        _add_org_column(conn, "wiii_proactive_messages")
        if not _index_exists(conn, "ix_proactive_messages_org_user_created"):
            op.create_index(
                "ix_proactive_messages_org_user_created",
                "wiii_proactive_messages",
                ["organization_id", "user_id", "created_at"],
            )

    if _table_exists(conn, "wiii_proactive_preferences"):
        _add_org_column(conn, "wiii_proactive_preferences")
        for pk_name in _primary_key_names(conn, "wiii_proactive_preferences"):
            if pk_name != "pk_wiii_proactive_preferences_org_user":
                op.drop_constraint(
                    pk_name,
                    "wiii_proactive_preferences",
                    type_="primary",
                )
        if "pk_wiii_proactive_preferences_org_user" not in _primary_key_names(
            conn,
            "wiii_proactive_preferences",
        ):
            op.create_primary_key(
                "pk_wiii_proactive_preferences_org_user",
                "wiii_proactive_preferences",
                ["organization_id", "user_id"],
            )


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "wiii_proactive_preferences"):
        for pk_name in _primary_key_names(conn, "wiii_proactive_preferences"):
            op.drop_constraint(
                pk_name,
                "wiii_proactive_preferences",
                type_="primary",
            )
        if _column_exists(conn, "wiii_proactive_preferences", "organization_id"):
            op.execute(
                sa.text(
                    "DELETE FROM wiii_proactive_preferences p "
                    "WHERE p.organization_id <> 'default' "
                    "AND EXISTS ("
                    "  SELECT 1 FROM wiii_proactive_preferences d "
                    "  WHERE d.user_id = p.user_id "
                    "  AND d.organization_id = 'default'"
                    ")"
                )
            )
            op.execute(
                sa.text(
                    "DELETE FROM wiii_proactive_preferences p "
                    "USING wiii_proactive_preferences q "
                    "WHERE p.ctid < q.ctid "
                    "AND p.user_id = q.user_id"
                )
            )
            op.create_primary_key(
                "wiii_proactive_preferences_pkey",
                "wiii_proactive_preferences",
                ["user_id"],
            )
            op.drop_column("wiii_proactive_preferences", "organization_id")

    if _table_exists(conn, "wiii_proactive_messages"):
        if _index_exists(conn, "ix_proactive_messages_org_user_created"):
            op.drop_index(
                "ix_proactive_messages_org_user_created",
                table_name="wiii_proactive_messages",
            )
        if _column_exists(conn, "wiii_proactive_messages", "organization_id"):
            op.drop_column("wiii_proactive_messages", "organization_id")
