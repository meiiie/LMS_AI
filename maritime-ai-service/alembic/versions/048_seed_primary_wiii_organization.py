"""048: seed primary wiii organization.

Production traffic for wiii.holilihu.online resolves to organization id
``wiii``. Seed it in Alembic so rebuilt environments do not fail thread and
memory writes against the thread_views organization foreign key.
"""

from alembic import op
import sqlalchemy as sa


revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = :table_name"
        ),
        {"table_name": table_name},
    )
    return result.fetchone() is not None


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, "organizations"):
        return

    conn.execute(
        sa.text(
            """
            INSERT INTO organizations (
                id,
                name,
                display_name,
                description,
                allowed_domains,
                default_domain,
                settings,
                is_active
            )
            VALUES (
                'wiii',
                'Wiii',
                'Wiii Production',
                'Primary Wiii production organization for wiii.holilihu.online',
                ARRAY['maritime', 'traffic_law'],
                'maritime',
                '{"source": "alembic-048", "domain": "wiii.holilihu.online"}'::jsonb,
                true
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                allowed_domains = EXCLUDED.allowed_domains,
                default_domain = EXCLUDED.default_domain,
                settings = organizations.settings || EXCLUDED.settings,
                is_active = true,
                updated_at = NOW()
            """
        )
    )


def downgrade():
    # Do not delete `wiii`: production thread/history rows may already
    # reference it. Operators can remove or remap data explicitly if needed.
    return
