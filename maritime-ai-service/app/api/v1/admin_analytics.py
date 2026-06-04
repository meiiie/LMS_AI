"""
Sprint 178: Admin Analytics API — Phase 2

Endpoints:
  GET /admin/analytics/overview    — DAU, chat volume, error rate
  GET /admin/analytics/llm-usage   — Token/cost breakdown
  GET /admin/analytics/users       — User growth, engagement
"""
import logging
from datetime import date, datetime, time, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.admin_security import check_admin_module as _check_admin_module
from app.api.deps import RequireAdmin
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])


def _parse_timestamptz_boundary(value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    """Convert query-string date boundaries into asyncpg-compatible datetimes."""
    if not value:
        return None

    raw = value.strip()
    try:
        if len(raw) == 10:
            parsed_date = date.fromisoformat(raw)
            boundary_time = time.max if end_of_day else time.min
            return datetime.combine(parsed_date, boundary_time, tzinfo=timezone.utc)

        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Date filters must use ISO format, for example 2026-04-09",
        ) from exc


async def _get_pool():
    from app.core.database import get_asyncpg_pool
    return await get_asyncpg_pool()


def _normalize_org_id(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _resolve_admin_analytics_org(
    auth: RequireAdmin,
    requested_org_id: Optional[str],
) -> Optional[str]:
    """Resolve the active organization boundary for analytics queries."""

    requested = _normalize_org_id(requested_org_id)
    if not settings.enable_multi_tenant:
        return requested

    active_org_id = _normalize_org_id(getattr(auth, "organization_id", None))
    if not active_org_id:
        raise HTTPException(
            status_code=403,
            detail="Active organization is required for admin analytics.",
        )
    if requested and requested != active_org_id:
        raise HTTPException(
            status_code=403,
            detail="Requested organization does not match active organization.",
        )
    return active_org_id


def _analytics_scope_metadata(org_id: Optional[str]) -> dict[str, object]:
    return {
        "org_scoped": org_id is not None,
        "org_filter_applied": org_id is not None,
        "identifier_strategy": "active_org_id_not_echoed",
    }


# =============================================================================
# GET /admin/analytics/overview
# =============================================================================

@router.get("/overview", dependencies=[Depends(_check_admin_module)])
async def analytics_overview(
    auth: RequireAdmin,
    from_date: Optional[str] = Query(None, alias="from", description="ISO date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, alias="to", description="ISO date YYYY-MM-DD"),
    org_id: Optional[str] = Query(None),
):
    """Overview analytics: daily active users, chat volume, error rate."""
    effective_org_id = _resolve_admin_analytics_org(auth, org_id)
    pool = await _get_pool()
    from_boundary = _parse_timestamptz_boundary(from_date)
    to_boundary = _parse_timestamptz_boundary(to_date, end_of_day=True)

    # Build safe date boundaries
    conditions_base = []
    params = []
    idx = 1

    if from_boundary:
        conditions_base.append(f"created_at >= ${idx}::timestamptz")
        params.append(from_boundary)
        idx += 1
    else:
        conditions_base.append("created_at >= NOW() - INTERVAL '30 days'")

    if to_boundary:
        conditions_base.append(f"created_at <= ${idx}::timestamptz")
        params.append(to_boundary)
        idx += 1

    org_cond = ""
    if effective_org_id:
        org_cond = f" AND organization_id = ${idx}"
        params.append(effective_org_id)
        idx += 1

    where = "WHERE " + " AND ".join(conditions_base)

    async with pool.acquire() as conn:
        # Daily active users (from chat_history)
        dau_rows = []
        try:
            dau_rows = await conn.fetch(
                f"""
                SELECT DATE(created_at) AS date, COUNT(DISTINCT user_id) AS count
                FROM chat_history
                {where} {org_cond}
                GROUP BY DATE(created_at)
                ORDER BY date
                """,
                *params,
            )
        except Exception as e:
            logger.debug("[ADMIN] DAU query failed: %s", e)

        # Chat volume
        chat_rows = []
        try:
            chat_rows = await conn.fetch(
                f"""
                SELECT DATE(created_at) AS date,
                       COUNT(*) AS messages,
                       COUNT(DISTINCT session_id) AS sessions
                FROM chat_history
                {where} {org_cond}
                GROUP BY DATE(created_at)
                ORDER BY date
                """,
                *params,
            )
        except Exception as e:
            logger.debug("[ADMIN] Chat volume query failed: %s", e)

        # Error rate from llm_usage_log
        error_rows = []
        try:
            error_rows = await conn.fetch(
                f"""
                SELECT DATE(created_at) AS date,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE duration_ms = 0 AND input_tokens = 0) AS errors
                FROM llm_usage_log
                {where} {org_cond}
                GROUP BY DATE(created_at)
                ORDER BY date
                """,
                *params,
            )
        except Exception as e:
            logger.debug("[ADMIN] Error rate query failed: %s", e)

    return {
        "period_start": from_date or "30 days ago",
        "period_end": to_date or "now",
        "daily_active_users": [
            {"date": str(r["date"]), "count": r["count"]} for r in dau_rows
        ],
        "chat_volume": [
            {"date": str(r["date"]), "messages": r["messages"], "sessions": r["sessions"]}
            for r in chat_rows
        ],
        "error_rate": [
            {
                "date": str(r["date"]),
                "total": r["total"],
                "errors": r["errors"],
                "rate": round(r["errors"] / max(r["total"], 1), 4),
            }
            for r in error_rows
        ],
        "scope": _analytics_scope_metadata(effective_org_id),
    }


# =============================================================================
# GET /admin/analytics/llm-usage
# =============================================================================

@router.get("/llm-usage", dependencies=[Depends(_check_admin_module)])
async def analytics_llm_usage(
    auth: RequireAdmin,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    org_id: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    group_by: str = Query("day", description="day, model, or org"),
):
    """LLM usage analytics: tokens, cost, breakdown."""
    effective_org_id = _resolve_admin_analytics_org(auth, org_id)
    pool = await _get_pool()
    from_boundary = _parse_timestamptz_boundary(from_date)
    to_boundary = _parse_timestamptz_boundary(to_date, end_of_day=True)

    conditions = ["created_at >= NOW() - INTERVAL '30 days'"]
    params = []
    idx = 1

    if from_boundary:
        conditions[0] = f"created_at >= ${idx}::timestamptz"
        params.append(from_boundary)
        idx += 1
    if to_boundary:
        conditions.append(f"created_at <= ${idx}::timestamptz")
        params.append(to_boundary)
        idx += 1
    if effective_org_id:
        conditions.append(f"organization_id = ${idx}")
        params.append(effective_org_id)
        idx += 1
    if model:
        conditions.append(f"model = ${idx}")
        params.append(model)
        idx += 1

    where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        # Totals
        try:
            totals = await conn.fetchrow(
                f"""
                SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) AS total_cost,
                       COUNT(*) AS total_requests
                FROM llm_usage_log {where}
                """,
                *params,
            )
        except Exception as e:
            logger.debug("[ADMIN] LLM totals query failed: %s", e)
            totals = {"total_tokens": 0, "total_cost": 0, "total_requests": 0}

        # Breakdown
        group_col_map = {
            "day": "DATE(created_at)",
            "model": "model",
            "org": "organization_id",
        }
        group_col = group_col_map.get(group_by, "DATE(created_at)")

        breakdown = []
        try:
            breakdown_rows = await conn.fetch(
                f"""
                SELECT {group_col} AS group_key,
                       SUM(input_tokens + output_tokens) AS tokens,
                       SUM(estimated_cost_usd) AS cost,
                       COUNT(*) AS requests
                FROM llm_usage_log {where}
                GROUP BY {group_col}
                ORDER BY {group_col}
                """,
                *params,
            )
            breakdown = [
                {
                    "group": str(r["group_key"]),
                    "tokens": r["tokens"] or 0,
                    "cost": float(r["cost"] or 0),
                    "requests": r["requests"],
                }
                for r in breakdown_rows
            ]
        except Exception as e:
            logger.debug("[ADMIN] LLM breakdown query failed: %s", e)

        # Top models
        top_models = []
        try:
            model_rows = await conn.fetch(
                f"""
                SELECT model, SUM(input_tokens + output_tokens) AS tokens, COUNT(*) AS requests
                FROM llm_usage_log {where}
                GROUP BY model ORDER BY tokens DESC LIMIT 10
                """,
                *params,
            )
            top_models = [
                {"model": r["model"], "tokens": r["tokens"] or 0, "requests": r["requests"]}
                for r in model_rows
            ]
        except Exception as e:
            logger.debug("[ADMIN] Top models query failed: %s", e)

        # Top users
        top_users = []
        try:
            user_rows = await conn.fetch(
                f"""
                SELECT user_id, SUM(input_tokens + output_tokens) AS tokens, COUNT(*) AS requests
                FROM llm_usage_log {where}
                GROUP BY user_id ORDER BY tokens DESC LIMIT 10
                """,
                *params,
            )
            top_users = [
                {"user_id": r["user_id"], "tokens": r["tokens"] or 0, "requests": r["requests"]}
                for r in user_rows
            ]
        except Exception as e:
            logger.debug("[ADMIN] Top users query failed: %s", e)

    return {
        "total_tokens": totals["total_tokens"],
        "total_cost_usd": float(totals["total_cost"]),
        "total_requests": totals["total_requests"],
        "breakdown": breakdown,
        "top_models": top_models,
        "top_users": top_users,
        "scope": _analytics_scope_metadata(effective_org_id),
    }


# =============================================================================
# GET /admin/analytics/users
# =============================================================================

@router.get("/users", dependencies=[Depends(_check_admin_module)])
async def analytics_users(
    auth: RequireAdmin,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    org_id: Optional[str] = Query(None),
):
    """User analytics: growth, engagement, account-type distribution."""
    effective_org_id = _resolve_admin_analytics_org(auth, org_id)
    pool = await _get_pool()
    from_boundary = _parse_timestamptz_boundary(from_date)
    to_boundary = _parse_timestamptz_boundary(to_date, end_of_day=True)

    date_conditions = []
    date_params = []
    idx = 1

    if from_boundary:
        date_conditions.append(f"created_at >= ${idx}::timestamptz")
        date_params.append(from_boundary)
        idx += 1
    else:
        date_conditions.append("created_at >= NOW() - INTERVAL '30 days'")

    if to_boundary:
        date_conditions.append(f"created_at <= ${idx}::timestamptz")
        date_params.append(to_boundary)
        idx += 1

    user_where = "WHERE " + " AND ".join(date_conditions)

    org_cond = ""
    org_membership_cond = ""
    org_params = list(date_params)
    if effective_org_id:
        org_cond = f" AND organization_id = ${idx}"
        org_membership_cond = f" AND uo.organization_id = ${idx}"
        org_params.append(effective_org_id)
        idx += 1

    async with pool.acquire() as conn:
        total_users = 0
        new_users = 0
        if effective_org_id:
            total_users = await conn.fetchval(
                """
                SELECT COUNT(DISTINCT u.id)
                FROM users u
                JOIN user_organizations uo ON uo.user_id = u.id
                WHERE uo.organization_id = $1
                """,
                effective_org_id,
            ) or 0
            new_users = await conn.fetchval(
                f"""
                SELECT COUNT(DISTINCT u.id)
                FROM users u
                JOIN user_organizations uo ON uo.user_id = u.id
                {user_where} {org_membership_cond}
                """,
                *org_params,
            ) or 0
        else:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
            new_users = await conn.fetchval(
                f"SELECT COUNT(*) FROM users {user_where}",
                *date_params,
            ) or 0

        # Active users in period (from chat_history)
        active_users = 0
        try:
            active_users = await conn.fetchval(
                f"""
                SELECT COUNT(DISTINCT user_id) FROM chat_history
                {user_where} {org_cond}
                """,
                *org_params,
            ) or 0
        except Exception as e:
            logger.debug("[ADMIN] Active users query failed: %s", e)

        # User growth curve
        growth = []
        try:
            if effective_org_id:
                growth_rows = await conn.fetch(
                    f"""
                    SELECT DATE(u.created_at) AS date, COUNT(DISTINCT u.id) AS new_users
                    FROM users u
                    JOIN user_organizations uo ON uo.user_id = u.id
                    {user_where} {org_membership_cond}
                    GROUP BY DATE(u.created_at)
                    ORDER BY date
                    """,
                    *org_params,
                )
            else:
                growth_rows = await conn.fetch(
                    f"""
                    SELECT DATE(created_at) AS date, COUNT(*) AS new_users
                    FROM users
                    {user_where}
                    GROUP BY DATE(created_at)
                    ORDER BY date
                    """,
                    *date_params,
                )
            growth = [{"date": str(r["date"]), "new_users": r["new_users"]} for r in growth_rows]
        except Exception as e:
            logger.debug("[ADMIN] User growth query failed: %s", e)

        # Compatibility role distribution
        legacy_role_dist = {}
        try:
            if effective_org_id:
                role_rows = await conn.fetch(
                    f"""
                    SELECT u.role, COUNT(DISTINCT u.id) AS count
                    FROM users u
                    JOIN user_organizations uo ON uo.user_id = u.id
                    WHERE uo.organization_id = $1
                    GROUP BY u.role
                    """,
                    effective_org_id,
                )
            else:
                role_rows = await conn.fetch(
                    "SELECT role, COUNT(*) AS count FROM users GROUP BY role"
                )
            legacy_role_dist = {r["role"]: r["count"] for r in role_rows}
        except Exception as e:
            logger.debug("[ADMIN] Role distribution query failed: %s", e)

        # Canonical Wiii account type distribution
        platform_role_dist = {}
        try:
            if effective_org_id:
                platform_rows = await conn.fetch(
                    f"""
                    SELECT
                        COALESCE(
                            u.platform_role,
                            CASE WHEN LOWER(COALESCE(u.role, 'student')) = 'admin'
                                THEN 'platform_admin'
                                ELSE 'user'
                            END
                        ) AS platform_role,
                        COUNT(DISTINCT u.id) AS count
                    FROM users u
                    JOIN user_organizations uo ON uo.user_id = u.id
                    WHERE uo.organization_id = $1
                    GROUP BY platform_role
                    """,
                    effective_org_id,
                )
            else:
                platform_rows = await conn.fetch(
                    """
                    SELECT
                        COALESCE(
                            platform_role,
                            CASE WHEN LOWER(COALESCE(role, 'student')) = 'admin'
                                THEN 'platform_admin'
                                ELSE 'user'
                            END
                        ) AS platform_role,
                        COUNT(*) AS count
                    FROM users
                    GROUP BY platform_role
                    """
                )
            platform_role_dist = {
                r["platform_role"]: r["count"] for r in platform_rows
            }
        except Exception as e:
            logger.debug("[ADMIN] Platform role distribution query failed: %s", e)
            if legacy_role_dist:
                platform_role_dist = {
                    "platform_admin": legacy_role_dist.get("admin", 0),
                    "user": sum(
                        count
                        for role, count in legacy_role_dist.items()
                        if str(role).lower() != "admin"
                    ),
                }

        # Wiii org membership roles only make sense within a specific org scope.
        organization_role_dist = {}
        if effective_org_id:
            try:
                membership_rows = await conn.fetch(
                    """
                    SELECT role, COUNT(*) AS count
                    FROM user_organizations
                    WHERE organization_id = $1
                    GROUP BY role
                    """,
                    effective_org_id,
                )
                organization_role_dist = {
                    r["role"]: r["count"] for r in membership_rows
                }
            except Exception as e:
                logger.debug("[ADMIN] Organization role distribution query failed: %s", e)

        # Top active users
        top_active = []
        try:
            active_rows = await conn.fetch(
                f"""
                SELECT user_id, COUNT(DISTINCT session_id) AS sessions
                FROM chat_history
                {user_where} {org_cond}
                GROUP BY user_id
                ORDER BY sessions DESC
                LIMIT 10
                """,
                *org_params,
            )
            top_active = [
                {"user_id": r["user_id"], "sessions": r["sessions"]}
                for r in active_rows
            ]
        except Exception as e:
            logger.debug("[ADMIN] Top active users query failed: %s", e)

    return {
        "total_users": total_users,
        "new_users_period": new_users,
        "active_users_period": active_users,
        "user_growth": growth,
        "role_distribution": legacy_role_dist,
        "legacy_role_distribution": legacy_role_dist,
        "platform_role_distribution": platform_role_dist,
        "organization_role_distribution": organization_role_dist,
        "top_active_users": top_active,
        "scope": _analytics_scope_metadata(effective_org_id),
    }
