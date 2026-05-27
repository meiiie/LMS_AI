"""
API Version 1 package.

The public `router` is now built lazily so importing a single submodule such as
`app.api.v1.living_agent` no longer eagerly imports every other router in the
package. This reduces coupling and keeps package import side-effects smaller.
"""

from __future__ import annotations

import importlib
import logging
from typing import Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

_router: Optional[APIRouter] = None


def _register_router(router: APIRouter, import_path: str, label: str) -> None:
    parts = import_path.rsplit(".", 1)
    module = importlib.import_module(parts[0])
    sub_router = getattr(module, parts[1])
    router.include_router(sub_router)
    logger.debug("[OK] %s router registered", label)


def _register_optional_router(
    router: APIRouter,
    flag_name: str,
    import_path: str,
    label: str,
) -> None:
    from app.core.config import settings

    if not getattr(settings, flag_name, False):
        return
    try:
        _register_router(router, import_path, label)
        logger.info("[OK] %s router registered", label)
    except Exception as exc:
        logger.error("[FAIL] %s router registration failed: %s", label, exc)


def _build_router() -> APIRouter:
    router = APIRouter(tags=["v1"])

    core_router_specs = [
        ("app.api.v1.chat.router", "Chat"),
        ("app.api.v1.chat_stream.router", "Chat Stream"),
        ("app.api.v1.health.router", "Health"),
        ("app.api.v1.insights.router", "Insights"),
        ("app.api.v1.knowledge.router", "Knowledge"),
        ("app.api.v1.memories.router", "Memories"),
        ("app.api.v1.sources.router", "Sources"),
        ("app.api.v1.admin.router", "Admin"),
        ("app.api.v1.webhook.router", "Webhook"),
        ("app.api.v1.threads.router", "Threads"),
        ("app.api.v1.organizations.router", "Organizations"),
        ("app.api.v1.feedback.router", "Feedback"),
        ("app.api.v1.character.router", "Character"),
        ("app.api.v1.mood.router", "Mood"),
        ("app.api.v1.generated_files.router", "Generated Files"),
        ("app.api.v1.llm_status.router", "LLM Status"),
        ("app.api.v1.document_context.router", "Document Context"),
        ("app.api.v1.host_actions.router", "Host Action Audit"),
        ("app.api.v1.wiii_connect.router", "Wiii Connect"),
        ("app.api.v1.voice.router", "Voice"),
        ("app.api.v1.soul_bridge.router", "Soul Bridge"),
        ("app.api.v1.living_agent.router", "Living Agent"),
        ("app.auth.user_router.router", "User"),
        ("app.auth.token_router.router", "Auth Tokens"),
    ]
    for import_path, label in core_router_specs:
        _register_router(router, import_path, label)

    optional_router_specs = [
        ("enable_websocket", "app.api.v1.websocket.router", "WebSocket"),
        ("enable_google_oauth", "app.auth.google_oauth.router", "Google OAuth"),
        ("enable_lms_token_exchange", "app.auth.lms_auth_router.router", "LMS Token Exchange"),
        ("enable_messenger_webhook", "app.api.v1.messenger_webhook.router", "Messenger Webhook"),
        ("enable_zalo_webhook", "app.api.v1.zalo_webhook.router", "Zalo Webhook"),
        ("enable_org_knowledge", "app.api.v1.org_knowledge.router", "Org Knowledge"),
        (
            "enable_knowledge_visualization",
            "app.api.v1.knowledge_visualization.router",
            "Knowledge Visualization",
        ),
        ("enable_magic_link_auth", "app.auth.magic_link_router.router", "Magic Link Auth"),
        ("enable_dev_login", "app.auth.dev_login_router.router", "Dev Login"),
    ]
    for flag_name, import_path, label in optional_router_specs:
        _register_optional_router(router, flag_name, import_path, label)

    try:
        from app.core.config import settings

        if getattr(settings, "enable_lms_integration", False):
            for import_path, label in [
                ("app.api.v1.lms_webhook.router", "LMS Webhook"),
                ("app.api.v1.lms_data.router", "LMS Data"),
                ("app.api.v1.lms_dashboard.router", "LMS Dashboard"),
                ("app.api.v1.course_generation.router", "Course Generation"),
            ]:
                _register_router(router, import_path, label)
            logger.info("[OK] LMS Integration routers registered")
    except Exception as exc:
        logger.error("[FAIL] LMS Integration router registration failed: %s", exc)

    try:
        from app.core.config import settings

        if getattr(settings, "enable_admin_module", False):
            for import_path, label in [
                ("app.api.v1.admin_dashboard.router", "Admin Dashboard"),
                ("app.api.v1.admin_feature_flags.router", "Admin Feature Flags"),
                ("app.api.v1.admin_analytics.router", "Admin Analytics"),
                ("app.api.v1.admin_audit.router", "Admin Audit"),
                ("app.api.v1.admin_gdpr.router", "Admin GDPR"),
            ]:
                _register_router(router, import_path, label)
            logger.info("[OK] Admin Module routers registered")
    except Exception as exc:
        logger.error("[FAIL] Admin Module router registration failed: %s", exc)

    @router.get("/")
    async def api_v1_root():
        return {"api": "v1", "status": "active"}

    return router


def __getattr__(name: str):
    if name == "router":
        global _router
        if _router is None:
            _router = _build_router()
        return _router
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"{__name__}.{name}":
            raise
    raise AttributeError(name)


__all__ = ["router"]
