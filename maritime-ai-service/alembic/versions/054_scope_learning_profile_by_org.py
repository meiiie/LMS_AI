"""054: scope learning profiles by organization.

Learning profiles drive personalization and adaptive tutoring. Legacy rows are
backfilled to the default organization, then the primary key becomes
(organization_id, user_id) so the same LMS/user identifier can keep separate
learning state in different tenants.

Downgrading collapses per-org profiles back to one row per user, preferring the
default organization row and then the most recently updated row. Back up the
table first if per-org learning history must be preserved.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    inspector = inspect(conn)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _primary_key(conn, table_name: str) -> tuple[str | None, list[str]]:
    inspector = inspect(conn)
    pk = inspector.get_pk_constraint(table_name) or {}
    return pk.get("name"), list(pk.get("constrained_columns") or [])


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
    if not _table_exists(conn, "learning_profile"):
        return

    if not _column_exists(conn, "learning_profile", "organization_id"):
        op.add_column(
            "learning_profile",
            sa.Column(
                "organization_id",
                sa.Text(),
                nullable=True,
                server_default="default",
            ),
        )

    conn.execute(
        text(
            "UPDATE learning_profile "
            "SET organization_id = 'default' "
            "WHERE organization_id IS NULL"
        )
    )

    op.alter_column(
        "learning_profile",
        "organization_id",
        server_default="default",
        nullable=False,
    )

    pk_name, pk_columns = _primary_key(conn, "learning_profile")
    if pk_columns != ["organization_id", "user_id"]:
        if pk_name:
            quoted_pk = conn.dialect.identifier_preparer.quote(pk_name)
            conn.execute(
                text(f"ALTER TABLE learning_profile DROP CONSTRAINT IF EXISTS {quoted_pk}")
            )
        if not _constraint_exists(
            conn,
            "learning_profile",
            "pk_learning_profile_org_user",
        ):
            op.create_primary_key(
                "pk_learning_profile_org_user",
                "learning_profile",
                ["organization_id", "user_id"],
            )

    if not _index_exists(conn, "ix_learning_profile_user_org"):
        op.create_index(
            "ix_learning_profile_user_org",
            "learning_profile",
            ["user_id", "organization_id"],
            unique=False,
        )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "learning_profile"):
        return

    if _index_exists(conn, "ix_learning_profile_user_org"):
        op.drop_index("ix_learning_profile_user_org", table_name="learning_profile")

    if _column_exists(conn, "learning_profile", "organization_id"):
        conn.execute(
            text(
                """
                DELETE FROM learning_profile lp
                USING (
                    SELECT
                        ctid,
                        ROW_NUMBER() OVER (
                            PARTITION BY user_id
                            ORDER BY
                                (organization_id = 'default') DESC,
                                updated_at DESC NULLS LAST,
                                ctid DESC
                        ) AS rn
                    FROM learning_profile
                ) ranked
                WHERE lp.ctid = ranked.ctid
                AND ranked.rn > 1
                """
            )
        )

    pk_name, pk_columns = _primary_key(conn, "learning_profile")
    if pk_columns != ["user_id"]:
        if pk_name:
            quoted_pk = conn.dialect.identifier_preparer.quote(pk_name)
            conn.execute(
                text(f"ALTER TABLE learning_profile DROP CONSTRAINT IF EXISTS {quoted_pk}")
            )
        if not _constraint_exists(conn, "learning_profile", "learning_profile_pkey"):
            op.create_primary_key(
                "learning_profile_pkey",
                "learning_profile",
                ["user_id"],
            )
