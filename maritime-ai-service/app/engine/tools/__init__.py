"""
Tool Registry Module - Centralized Tool Management.

This package intentionally keeps top-level imports light. Most tool functions
and submodules are loaded lazily so consumers do not eagerly import every tool
implementation just by importing ``app.engine.tools``.
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any

from app.engine.tools.registry import (
    ToolAccess,
    ToolCategory,
    ToolInfo,
    ToolRegistry,
    get_tool_registry,
    register_tool,
)


logger = logging.getLogger(__name__)

_CORE_TOOL_MODULES = (
    "app.engine.tools.rag_tools",
    "app.engine.tools.memory_tools",
    "app.engine.tools.tutor_tools",
    "app.engine.tools.utility_tools",
    "app.engine.tools.web_search_tools",
    "app.engine.tools.think_tool",
    "app.engine.tools.progress_tool",
)


def _prime_core_tool_modules() -> None:
    """Preserve legacy registration side effects without static eager imports."""
    for module_name in _CORE_TOOL_MODULES:
        import_module(module_name)


_LAZY_ATTR_MODULES = {
    "tool_knowledge_search": "app.engine.tools.rag_tools",
    "tool_maritime_search": "app.engine.tools.rag_tools",
    "init_rag_tools": "app.engine.tools.rag_tools",
    "get_last_retrieved_sources": "app.engine.tools.rag_tools",
    "clear_retrieved_sources": "app.engine.tools.rag_tools",
    "tool_save_user_info": "app.engine.tools.memory_tools",
    "tool_get_user_info": "app.engine.tools.memory_tools",
    "tool_remember": "app.engine.tools.memory_tools",
    "tool_forget": "app.engine.tools.memory_tools",
    "tool_list_memories": "app.engine.tools.memory_tools",
    "tool_clear_all_memories": "app.engine.tools.memory_tools",
    "init_memory_tools": "app.engine.tools.memory_tools",
    "set_current_user": "app.engine.tools.memory_tools",
    "get_user_cache": "app.engine.tools.memory_tools",
    "tool_start_lesson": "app.engine.tools.tutor_tools",
    "tool_continue_lesson": "app.engine.tools.tutor_tools",
    "tool_lesson_status": "app.engine.tools.tutor_tools",
    "tool_end_lesson": "app.engine.tools.tutor_tools",
    "init_tutor_tools": "app.engine.tools.tutor_tools",
    "set_tutor_user": "app.engine.tools.tutor_tools",
    "get_current_session_id": "app.engine.tools.tutor_tools",
    "tool_calculator": "app.engine.tools.utility_tools",
    "tool_current_datetime": "app.engine.tools.utility_tools",
    "tool_current_weather": "app.engine.tools.utility_tools",
    "init_utility_tools": "app.engine.tools.utility_tools",
    "tool_web_search": "app.engine.tools.web_search_tools",
    "tool_search_news": "app.engine.tools.web_search_tools",
    "tool_search_legal": "app.engine.tools.web_search_tools",
    "tool_search_maritime": "app.engine.tools.web_search_tools",
    "init_web_search_tools": "app.engine.tools.web_search_tools",
    "tool_fetch_url": "app.engine.tools.web_fetch_tool",
    "get_web_fetch_tools": "app.engine.tools.web_fetch_tool",
    "tool_think": "app.engine.tools.think_tool",
    "tool_report_progress": "app.engine.tools.progress_tool",
    "product_search_tools": "app.engine.tools.product_search_tools",
}


_prime_core_tool_modules()


def _load_attr(module_name: str, attr_name: str) -> Any:
    """Load an arbitrary attribute from a module without adding static edges."""
    return getattr(import_module(module_name), attr_name)


def _load_lazy_attr(name: str) -> Any:
    module_name = _LAZY_ATTR_MODULES.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = (
        import_module(module_name)
        if name == module_name.rsplit(".", 1)[-1]
        else _load_attr(module_name, name)
    )
    globals()[name] = value
    return value


def __getattr__(name: str) -> Any:
    return _load_lazy_attr(name)


def get_all_tools() -> list:
    """Get all registered tools."""
    return get_tool_registry().get_all()


def get_tools_for_role(role: str) -> list:
    """Get tools filtered by user role."""
    return get_tool_registry().get_for_role(role)


def _init_extended_tools() -> None:
    """
    Initialize Sprint 13 extended tools (config-gated).

    Only registers tools when explicitly enabled in config.
    Uses try/except fail-graceful pattern (warn, don't crash).
    """
    try:
        settings = _load_attr("app.core.config", "get_settings")()
    except Exception as e:
        logger.debug("Extended tools: config not available: %s", e)
        return

    registry = get_tool_registry()

    if settings.enable_filesystem_tools:
        try:
            get_filesystem_tools = _load_attr(
                "app.engine.tools.filesystem_tools",
                "get_filesystem_tools",
            )

            for tool_fn in get_filesystem_tools():
                registry.register(
                    tool_fn, ToolCategory.FILESYSTEM, ToolAccess.WRITE, roles=["admin"]
                )
            logger.info("Filesystem tools registered (sandboxed, admin-only)")
        except Exception as e:
            logger.warning("Filesystem tools init failed: %s", e)

    if settings.enable_code_execution:
        try:
            get_code_execution_tools = _load_attr(
                "app.engine.tools.code_execution_tools",
                "get_code_execution_tools",
            )

            for tool_fn in get_code_execution_tools():
                registry.register(
                    tool_fn, ToolCategory.EXECUTION, ToolAccess.WRITE, roles=["admin"]
                )
            logger.info("Code execution tools registered (sandboxed, admin-only)")
        except Exception as e:
            logger.warning("Code execution tools init failed: %s", e)

    if (
        settings.enable_browser_agent
        and settings.enable_privileged_sandbox
        and settings.sandbox_provider == "opensandbox"
        and settings.sandbox_allow_browser_workloads
    ):
        try:
            get_browser_sandbox_tools = _load_attr(
                "app.engine.tools.browser_sandbox_tools",
                "get_browser_sandbox_tools",
            )

            for tool_fn in get_browser_sandbox_tools():
                registry.register(
                    tool_fn, ToolCategory.EXECUTION, ToolAccess.WRITE, roles=["admin"]
                )
            logger.info("Browser sandbox tools registered (admin-only)")
        except Exception as e:
            logger.warning("Browser sandbox tools init failed: %s", e)

    if settings.enable_skill_creation:
        try:
            get_skill_tools = _load_attr(
                "app.engine.tools.skill_tools",
                "get_skill_tools",
            )

            for tool_fn in get_skill_tools():
                registry.register(
                    tool_fn,
                    ToolCategory.SKILL_MANAGEMENT,
                    ToolAccess.WRITE,
                    roles=["admin"],
                )
            logger.info("Skill management tools registered (admin-only)")
        except Exception as e:
            logger.warning("Skill management tools init failed: %s", e)

    if settings.enable_scheduler:
        try:
            get_scheduler_tools = _load_attr(
                "app.engine.tools.scheduler_tools",
                "get_scheduler_tools",
            )

            for tool_fn in get_scheduler_tools():
                registry.register(
                    tool_fn,
                    ToolCategory.SCHEDULER,
                    ToolAccess.WRITE,
                    roles=["teacher", "admin"],
                )
            logger.info("Scheduler tools registered (proactive agent, teacher/admin)")
        except Exception as e:
            logger.warning("Scheduler tools init failed: %s", e)

    if settings.enable_product_search:
        try:
            init_excel_report_tool = _load_attr(
                "app.engine.tools.excel_report_tool",
                "init_excel_report_tool",
            )
            get_product_page_scraper_tools = _load_attr(
                "app.engine.tools.product_page_scraper",
                "get_product_page_scraper_tools",
            )

            _load_lazy_attr("product_search_tools").init_product_search_tools()
            init_excel_report_tool()
            for scraper_tool in get_product_page_scraper_tools():
                registry.register(scraper_tool, ToolCategory.PRODUCT_SEARCH, ToolAccess.READ)
            logger.info("Product search + Excel report + page scraper tools registered")
        except Exception as e:
            logger.warning("Product search tools init failed: %s", e)

    if settings.enable_visual_product_search:
        try:
            get_visual_product_search_tool = _load_attr(
                "app.engine.tools.visual_product_search",
                "get_visual_product_search_tool",
            )

            registry.register(
                get_visual_product_search_tool(),
                ToolCategory.PRODUCT_SEARCH,
                ToolAccess.READ,
            )
            logger.info("Visual product search tool registered")
        except Exception as e:
            logger.warning("Visual product search tool init failed: %s", e)

    if settings.enable_lms_integration:
        try:
            tool_approve_course_outline = _load_attr(
                "app.engine.tools.course_generation_tool",
                "tool_approve_course_outline",
            )
            tool_generate_course_outline = _load_attr(
                "app.engine.tools.course_generation_tool",
                "tool_generate_course_outline",
            )
            register_lms_tools = _load_attr(
                "app.engine.tools.lms_tools",
                "register_lms_tools",
            )

            register_lms_tools()
            registry.register(
                tool_generate_course_outline,
                ToolCategory.LMS,
                ToolAccess.WRITE,
                description="Generate course outline from uploaded document",
                roles=["teacher", "admin"],
            )
            registry.register(
                tool_approve_course_outline,
                ToolCategory.LMS,
                ToolAccess.WRITE,
                description="Approve outline and start content generation",
                roles=["teacher", "admin"],
            )
            logger.info(
                "LMS tools registered (gate: enable_lms_integration) + course generation tools"
            )
        except Exception as e:
            logger.warning("LMS tools init failed: %s", e)

    if settings.enable_character_tools:
        try:
            get_character_tools = _load_attr(
                "app.engine.character.character_tools",
                "get_character_tools",
            )

            character_tools = get_character_tools()
            for tool_fn in character_tools:
                registry.register(
                    tool_fn,
                    ToolCategory.CHARACTER,
                    ToolAccess.WRITE,
                )
            logger.info("Character tools registered (%d tools)", len(character_tools))
        except Exception as e:
            logger.warning("Character tools init failed: %s", e)


_tools_initialized = False


def init_all_tools(
    rag_agent=None,
    semantic_memory=None,
    user_id: str = None,
    domain_id: str = None,
) -> None:
    """Initialize all tools with required dependencies."""
    global _tools_initialized
    if _tools_initialized:
        logger.debug("init_all_tools already called, updating user context only")

    if rag_agent:
        _load_lazy_attr("init_rag_tools")(rag_agent)

    if semantic_memory:
        _load_lazy_attr("init_memory_tools")(semantic_memory, user_id)

    if user_id:
        _load_lazy_attr("init_tutor_tools")(user_id)

    if user_id:
        try:
            _load_attr("app.engine.character.character_tools", "set_character_user")(
                user_id
            )
        except Exception as e:
            logger.debug("Character user init skipped: %s", e)

    _load_lazy_attr("init_utility_tools")()

    try:
        _load_attr(
            "app.engine.tools.output_generation_tools",
            "init_output_generation_tools",
        )()
    except Exception as e:
        logger.warning("Output generation tools init failed: %s", e)

    registry = get_tool_registry()
    if "tool_think" not in registry.get_all_names():
        registry.register(
            _load_lazy_attr("tool_think"),
            ToolCategory.UTILITY,
            ToolAccess.READ,
            description="Think step-by-step about complex problems (private scratchpad)",
        )

    if "tool_report_progress" not in registry.get_all_names():
        registry.register(
            _load_lazy_attr("tool_report_progress"),
            ToolCategory.UTILITY,
            ToolAccess.READ,
            description="Report progress and start a new analysis phase (multi-phase thinking)",
        )

    _load_lazy_attr("init_web_search_tools")()
    _init_extended_tools()

    if domain_id:
        try:
            domain_registry = _load_attr("app.domains.registry", "get_domain_registry")()
            domain_plugin = domain_registry.get(domain_id)
            if domain_plugin:
                domain_tools = domain_plugin.get_tools()
                for tool_fn in domain_tools:
                    registry.register(tool_fn, ToolCategory.RAG)
                if domain_tools:
                    logger.info(
                        "Registered %d domain tools for '%s'",
                        len(domain_tools),
                        domain_id,
                    )
        except Exception as e:
            logger.debug("Domain tool registration skipped: %s", e)

    logger.info("Tool Registry initialized: %s", registry.summary())
    _tools_initialized = True


TOOLS = get_all_tools


__all__ = [
    "ToolRegistry",
    "ToolCategory",
    "ToolAccess",
    "ToolInfo",
    "get_tool_registry",
    "register_tool",
    "tool_knowledge_search",
    "tool_maritime_search",
    "init_rag_tools",
    "get_last_retrieved_sources",
    "clear_retrieved_sources",
    "tool_save_user_info",
    "tool_get_user_info",
    "tool_remember",
    "tool_forget",
    "tool_list_memories",
    "tool_clear_all_memories",
    "init_memory_tools",
    "set_current_user",
    "get_user_cache",
    "tool_start_lesson",
    "tool_continue_lesson",
    "tool_lesson_status",
    "tool_end_lesson",
    "init_tutor_tools",
    "set_tutor_user",
    "get_current_session_id",
    "tool_calculator",
    "tool_current_datetime",
    "tool_current_weather",
    "init_utility_tools",
    "tool_web_search",
    "tool_search_news",
    "tool_search_legal",
    "tool_search_maritime",
    "init_web_search_tools",
    "tool_fetch_url",
    "get_web_fetch_tools",
    "_init_extended_tools",
    "tool_think",
    "tool_report_progress",
    "get_all_tools",
    "get_tools_for_role",
    "init_all_tools",
    "TOOLS",
]
