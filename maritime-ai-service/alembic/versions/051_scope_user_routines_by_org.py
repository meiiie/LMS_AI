"""051: scope user routine profiles by organization.

Routine profiles feed inactive-user detection and proactive timing. Legacy rows
are backfilled to the default organization, then the primary key becomes
(organization_id, user_id) so behavior learned in one tenant cannot influence
another tenant.

Downgrading restores the legacy per-user primary key by keeping one row per
user. Back up the table first if per-org routine history must be retained.
"""

from alembic import op
import sqlalchemy as sa


revision = "051"
down_revision = "050"
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


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "wiii_user_routines"):
        return

    if not _column_exists(conn, "wiii_user_routines", "organization_id"):
        op.add_column(
            "wiii_user_routines",
            sa.Column(
                "organization_id",
                sa.Text(),
                nullable=True,
                server_default=sa.text("'default'"),
            ),
        )

    op.execute(
        sa.text(
            "UPDATE wiii_user_routines "
            "SET organization_id = 'default' "
            "WHERE organization_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE wiii_user_routines "
            "ALTER COLUMN organization_id SET DEFAULT 'default'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE wiii_user_routines "
            "ALTER COLUMN organization_id SET NOT NULL"
        )
    )

    for pk_name in _primary_key_names(conn, "wiii_user_routines"):
        if pk_name != "pk_wiii_user_routines_org_user":
            op.drop_constraint(pk_name, "wiii_user_routines", type_="primary")
    if "pk_wiii_user_routines_org_user" not in _primary_key_names(
        conn,
        "wiii_user_routines",
    ):
        op.create_primary_key(
            "pk_wiii_user_routines_org_user",
            "wiii_user_routines",
            ["organization_id", "user_id"],
        )

    if not _index_exists(conn, "ix_user_routines_org_last_seen"):
        op.create_index(
            "ix_user_routines_org_last_seen",
            "wiii_user_routines",
            ["organization_id", "last_seen"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "wiii_user_routines"):
        return

    if _index_exists(conn, "ix_user_routines_org_last_seen"):
        op.drop_index(
            "ix_user_routines_org_last_seen",
            table_name="wiii_user_routines",
        )

    for pk_name in _primary_key_names(conn, "wiii_user_routines"):
        op.drop_constraint(pk_name, "wiii_user_routines", type_="primary")

    if _column_exists(conn, "wiii_user_routines", "organization_id"):
        op.execute(
            sa.text(
                "DELETE FROM wiii_user_routines r "
                "WHERE r.organization_id <> 'default' "
                "AND EXISTS ("
                "  SELECT 1 FROM wiii_user_routines d "
                "  WHERE d.user_id = r.user_id "
                "  AND d.organization_id = 'default'"
                ")"
            )
        )
        op.execute(
            sa.text(
                "DELETE FROM wiii_user_routines r "
                "USING wiii_user_routines q "
                "WHERE r.ctid < q.ctid "
                "AND r.user_id = q.user_id"
            )
        )
        op.create_primary_key(
            "wiii_user_routines_pkey",
            "wiii_user_routines",
            ["user_id"],
        )
        op.drop_column("wiii_user_routines", "organization_id")
