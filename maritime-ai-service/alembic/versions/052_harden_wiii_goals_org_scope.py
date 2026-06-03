"""052: harden dynamic goals with required organization scope.

Dynamic goals drive autonomous planning. Legacy rows are backfilled to the
default organization, then organization_id becomes NOT NULL and indexed for
all runtime read/update filters.
"""

from alembic import op
import sqlalchemy as sa


revision = "052"
down_revision = "051"
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


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "wiii_goals"):
        return

    if not _column_exists(conn, "wiii_goals", "organization_id"):
        op.add_column(
            "wiii_goals",
            sa.Column(
                "organization_id",
                sa.Text(),
                nullable=True,
                server_default=sa.text("'default'"),
            ),
        )

    op.execute(
        sa.text(
            "UPDATE wiii_goals "
            "SET organization_id = 'default' "
            "WHERE organization_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE wiii_goals "
            "ALTER COLUMN organization_id SET DEFAULT 'default'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE wiii_goals "
            "ALTER COLUMN organization_id SET NOT NULL"
        )
    )

    if not _index_exists(conn, "ix_wiii_goals_org_status_updated"):
        op.create_index(
            "ix_wiii_goals_org_status_updated",
            "wiii_goals",
            ["organization_id", "status", "updated_at"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "wiii_goals"):
        return

    if _index_exists(conn, "ix_wiii_goals_org_status_updated"):
        op.drop_index(
            "ix_wiii_goals_org_status_updated",
            table_name="wiii_goals",
        )
    if _column_exists(conn, "wiii_goals", "organization_id"):
        op.execute(
            sa.text(
                "ALTER TABLE wiii_goals "
                "ALTER COLUMN organization_id DROP NOT NULL"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE wiii_goals "
                "ALTER COLUMN organization_id DROP DEFAULT"
            )
        )
