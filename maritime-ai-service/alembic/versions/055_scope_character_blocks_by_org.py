"""055: scope character blocks by organization.

Character blocks and experience logs carry Wiii's living/persona state. Legacy
blocks were unique only by (user_id, label), which made the same user identifier
share one character state across tenants. This migration backfills the default
organization, makes organization_id required, and moves block uniqueness to
(organization_id, user_id, label).

Downgrading collapses per-org character blocks back to one row per user/label,
preferring the default organization and then the most recently updated row.
Back up the table first if per-org living state must be preserved.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    inspector = inspect(conn)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


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


def _ensure_org_column(conn, table_name: str) -> None:
    if not _table_exists(conn, table_name):
        return

    if not _column_exists(conn, table_name, "organization_id"):
        op.add_column(
            table_name,
            sa.Column(
                "organization_id",
                sa.Text(),
                nullable=True,
                server_default="default",
            ),
        )

    conn.execute(
        text(
            f"UPDATE {table_name} "
            "SET organization_id = 'default' "
            "WHERE organization_id IS NULL"
        )
    )
    op.alter_column(
        table_name,
        "organization_id",
        existing_type=sa.Text(),
        server_default="default",
        nullable=False,
    )


def _drop_constraint_if_exists(conn, table_name: str, constraint_name: str) -> None:
    if not _constraint_exists(conn, table_name, constraint_name):
        return
    quoted_name = conn.dialect.identifier_preparer.quote(constraint_name)
    conn.execute(text(f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {quoted_name}"))


def upgrade() -> None:
    conn = op.get_bind()

    _ensure_org_column(conn, "wiii_character_blocks")
    _ensure_org_column(conn, "wiii_experiences")

    if _table_exists(conn, "wiii_character_blocks"):
        conn.execute(
            text(
                """
                DELETE FROM wiii_character_blocks cb
                USING (
                    SELECT
                        ctid,
                        ROW_NUMBER() OVER (
                            PARTITION BY organization_id, user_id, label
                            ORDER BY
                                updated_at DESC NULLS LAST,
                                created_at DESC NULLS LAST,
                                ctid DESC
                        ) AS rn
                    FROM wiii_character_blocks
                ) ranked
                WHERE cb.ctid = ranked.ctid
                AND ranked.rn > 1
                """
            )
        )

        _drop_constraint_if_exists(
            conn,
            "wiii_character_blocks",
            "uq_character_blocks_user_label",
        )
        if not _constraint_exists(
            conn,
            "wiii_character_blocks",
            "uq_character_blocks_org_user_label",
        ):
            op.create_unique_constraint(
                "uq_character_blocks_org_user_label",
                "wiii_character_blocks",
                ["organization_id", "user_id", "label"],
            )

        if not _index_exists(conn, "idx_character_blocks_org_user_label"):
            op.create_index(
                "idx_character_blocks_org_user_label",
                "wiii_character_blocks",
                ["organization_id", "user_id", "label"],
                unique=False,
            )

    if _table_exists(conn, "wiii_experiences"):
        if not _index_exists(conn, "idx_experiences_org_user_created"):
            op.create_index(
                "idx_experiences_org_user_created",
                "wiii_experiences",
                ["organization_id", "user_id", "created_at"],
                unique=False,
            )


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "wiii_experiences"):
        if _index_exists(conn, "idx_experiences_org_user_created"):
            op.drop_index(
                "idx_experiences_org_user_created",
                table_name="wiii_experiences",
            )

    if not _table_exists(conn, "wiii_character_blocks"):
        return

    if _index_exists(conn, "idx_character_blocks_org_user_label"):
        op.drop_index(
            "idx_character_blocks_org_user_label",
            table_name="wiii_character_blocks",
        )

    _drop_constraint_if_exists(
        conn,
        "wiii_character_blocks",
        "uq_character_blocks_org_user_label",
    )

    if _column_exists(conn, "wiii_character_blocks", "organization_id"):
        conn.execute(
            text(
                """
                DELETE FROM wiii_character_blocks cb
                USING (
                    SELECT
                        ctid,
                        ROW_NUMBER() OVER (
                            PARTITION BY user_id, label
                            ORDER BY
                                (organization_id = 'default') DESC,
                                updated_at DESC NULLS LAST,
                                created_at DESC NULLS LAST,
                                ctid DESC
                        ) AS rn
                    FROM wiii_character_blocks
                ) ranked
                WHERE cb.ctid = ranked.ctid
                AND ranked.rn > 1
                """
            )
        )

    if not _constraint_exists(
        conn,
        "wiii_character_blocks",
        "uq_character_blocks_user_label",
    ):
        op.create_unique_constraint(
            "uq_character_blocks_user_label",
            "wiii_character_blocks",
            ["user_id", "label"],
        )
