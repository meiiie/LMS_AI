"""048: seed primary wiii organization.

Production traffic for wiii.holilihu.online resolves to organization id
``wiii``. Seed it in Alembic so rebuilt environments do not fail thread and
memory writes against the thread_views organization foreign key.

If a production operator has already customized or disabled the organization,
the conflict path preserves those existing choices and only fills missing
metadata.
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
            "WHERE table_schema = current_schema() "
            "AND table_name = :table_name"
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
                name = COALESCE(organizations.name, EXCLUDED.name),
                display_name = COALESCE(
                    organizations.display_name,
                    EXCLUDED.display_name
                ),
                description = COALESCE(
                    organizations.description,
                    EXCLUDED.description
                ),
                allowed_domains = COALESCE(
                    organizations.allowed_domains,
                    EXCLUDED.allowed_domains
                ),
                default_domain = COALESCE(
                    organizations.default_domain,
                    EXCLUDED.default_domain
                ),
                settings = COALESCE(EXCLUDED.settings, '{}'::jsonb)
                    || COALESCE(organizations.settings, '{}'::jsonb),
                is_active = COALESCE(organizations.is_active, EXCLUDED.is_active),
                updated_at = NOW()
            """
        )
    )


def downgrade():
    # Do not delete `wiii`: production thread/history rows may already
    # reference it. Operators can remove or remap data explicitly if needed.
    return
