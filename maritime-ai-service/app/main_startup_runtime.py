"""Startup runtime helpers for the FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import os
from importlib import import_module
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.main_runtime_contracts import AppRuntimeResources


def _load_attr(module_name: str, attr_name: str):
    """Resolve a startup dependency lazily at the application boundary."""
    return getattr(import_module(module_name), attr_name)


def _log_startup_banner(logger_: logging.Logger) -> None:
    logger_.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger_.info("Environment: %s", settings.environment)
    logger_.info("Debug mode: %s", settings.debug)


def _init_observability(logger_: logging.Logger) -> None:
    init_telemetry = _load_attr("app.core.observability", "init_telemetry")
    init_sentry = _load_attr("app.core.sentry_config", "init_sentry")

    init_telemetry(service_name=settings.app_name.lower())
    init_sentry(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )

    if settings.enable_langsmith:
        configure_langsmith = _load_attr("app.core.langsmith", "configure_langsmith")

        configure_langsmith(settings)


def _register_runtime_lifecycle_hooks(logger_: logging.Logger) -> None:
    registration_count = 0
    try:
        register_default_lifecycle_hooks = _load_attr(
            "app.engine.runtime.lifecycle",
            "register_default_lifecycle_hooks",
        )

        registrations = register_default_lifecycle_hooks()
        registration_count += len(registrations)
        logger_.info(
            "[OK] Runtime lifecycle hooks registered: %d",
            len(registrations),
        )
    except Exception as exc:  # pragma: no cover - startup log
        logger_.warning(
            "[WARN] Runtime lifecycle hook registration failed: %s "
            "(service will continue)",
            exc,
        )
    try:
        register_semantic_memory_lifecycle_hooks = _load_attr(
            "app.engine.semantic_memory.lifecycle_hooks",
            "register_semantic_memory_lifecycle_hooks",
        )

        registrations = register_semantic_memory_lifecycle_hooks()
        registration_count += len(registrations)
        logger_.info(
            "[OK] Semantic memory lifecycle hooks registered: %d",
            len(registrations),
        )
    except Exception as exc:  # pragma: no cover - startup log
        logger_.warning(
            "[WARN] Semantic memory lifecycle hook registration failed: %s "
            "(service will continue)",
            exc,
        )

    if registration_count:
        logger_.info("[OK] Lifecycle hooks ready: %d", registration_count)


def _validate_postgresql(logger_: logging.Logger) -> None:
    try:
        get_chat_history_repository = _load_attr(
            "app.repositories.chat_history_repository",
            "get_chat_history_repository",
        )

        chat_repo = get_chat_history_repository()
        if chat_repo.is_available():
            logger_.info("[OK] PostgreSQL connection: Available")
        else:
            logger_.warning(
                "[WARN] PostgreSQL connection: Unavailable (service will continue)"
            )
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning(
            "[WARN] PostgreSQL validation failed: %s (service will continue)", exc
        )


def _validate_neo4j(logger_: logging.Logger) -> Any:
    neo4j_repo = None
    try:
        Neo4jKnowledgeRepository = _load_attr(
            "app.repositories.neo4j_knowledge_repository",
            "Neo4jKnowledgeRepository",
        )

        neo4j_repo = Neo4jKnowledgeRepository()
        if neo4j_repo.is_available():
            logger_.info("[OK] Neo4j connection: Available")
        elif not settings.enable_neo4j and settings.environment == "development":
            logger_.info("[SKIP] Neo4j connection: Disabled in local development")
        else:
            logger_.warning("[WARN] Neo4j connection: Unavailable (service will continue)")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning(
            "[WARN] Neo4j validation failed: %s (service will continue)", exc
        )
    return neo4j_repo


def _validate_pgvector(logger_: logging.Logger) -> None:
    try:
        get_semantic_memory_repository = _load_attr(
            "app.repositories.semantic_memory_repository",
            "get_semantic_memory_repository",
        )

        semantic_repo = get_semantic_memory_repository()
        if semantic_repo.is_available():
            logger_.info("[OK] pgvector connection: Available")
        else:
            logger_.warning("[WARN] pgvector connection: Unavailable (service will continue)")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] pgvector validation failed: %s (service will continue)", exc)


def _validate_prompt_loader(logger_: logging.Logger) -> None:
    try:
        get_prompt_loader = _load_attr("app.prompts.prompt_loader", "get_prompt_loader")

        get_prompt_loader()
        logger_.info("[OK] PromptLoader initialized (persona YAML files checked)")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] PromptLoader initialization failed: %s (using defaults)", exc)


def _discover_domain_plugins(logger_: logging.Logger) -> None:
    try:
        DomainLoader = _load_attr("app.domains.loader", "DomainLoader")
        get_domain_registry = _load_attr("app.domains.registry", "get_domain_registry")

        domains_dir = Path(__file__).parent / "domains"
        loader = DomainLoader(domains_dir)
        registry = get_domain_registry()

        discovered = loader.discover()
        for domain in discovered:
            domain_cfg = domain.get_config()
            if domain_cfg.id in settings.active_domains:
                registry.register(domain)
                logger_.info("Domain plugin loaded: %s (%s)", domain_cfg.id, domain_cfg.name)
            else:
                logger_.debug(
                    "Domain plugin skipped (not in active_domains): %s", domain_cfg.id
                )

        if settings.default_domain:
            registry.set_default(settings.default_domain)

        logger_.info("Domain registry: %d active domain(s)", len(registry.list_all()))
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Domain plugin discovery failed: %s (service will continue)", exc)


def _maybe_run_migrations(logger_: logging.Logger) -> None:
    if os.environ.get("RUN_MIGRATIONS", "false").lower() != "true":
        logger_.info("Skipping auto-migration (set RUN_MIGRATIONS=true to enable)")
        return

    try:
        from alembic import command as alembic_command
        from alembic.config import Config as AlembicConfig

        alembic_ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
        if os.path.exists(alembic_ini_path):
            alembic_cfg = AlembicConfig(alembic_ini_path)
            alembic_cfg.set_main_option(
                "script_location",
                os.path.join(os.path.dirname(__file__), "..", "alembic"),
            )
            alembic_command.upgrade(alembic_cfg, "head")
            logger_.info("Database migrations applied (Alembic upgrade head)")
        else:
            logger_.info("alembic.ini not found - skipping migrations")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Database migration failed: %s (service will continue)", exc)


def _restore_runtime_policy(logger_: logging.Logger) -> None:
    try:
        apply_persisted_llm_runtime_policy = _load_attr(
            "app.services.llm_runtime_policy_service",
            "apply_persisted_llm_runtime_policy",
        )

        persisted_runtime = apply_persisted_llm_runtime_policy()
        if persisted_runtime and persisted_runtime.payload:
            logger_.info(
                "Persisted LLM runtime policy restored from DB%s",
                (
                    f" (updated_at={persisted_runtime.updated_at.isoformat()})"
                    if persisted_runtime.updated_at
                    else ""
                ),
            )
        else:
            logger_.info("No persisted LLM runtime policy override found")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Persisted LLM runtime policy restore failed: %s", exc)


def _bootstrap_lms_connectors() -> None:
    if settings.enable_lms_integration:
        try:
            bootstrap_lms_connectors = _load_attr(
                "app.integrations.lms.loader",
                "bootstrap_lms_connectors",
            )

            lms_count = bootstrap_lms_connectors(settings)
            print(f"[OK] LMS integration: {lms_count} connector(s) registered", flush=True)
        except Exception as exc:  # pragma: no cover - startup log
            print(f"[WARN] LMS connector bootstrap failed: {exc}", flush=True)
    else:
        print("[SKIP] LMS integration disabled", flush=True)


def _initialize_llm_pool(logger_: logging.Logger) -> None:
    try:
        LLMPool = _load_attr("app.engine.llm_pool", "LLMPool")

        LLMPool.initialize()
        logger_.info("[OK] LLM Singleton Pool initialized (3 shared instances, ~120MB)")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] LLM Pool initialization failed: %s", exc)


def _initialize_agent_registry(logger_: logging.Logger) -> None:
    try:
        AgentConfigRegistry = _load_attr(
            "app.engine.multi_agent.agent_config",
            "AgentConfigRegistry",
        )

        AgentConfigRegistry.initialize(
            settings.agent_provider_configs,
            getattr(settings, "agent_runtime_profiles", "{}"),
        )
        logger_.info("[OK] AgentConfigRegistry initialized (per-node LLM config)")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] AgentConfigRegistry initialization failed: %s", exc)


async def _schedule_runtime_audit(
    logger_: logging.Logger,
) -> tuple[asyncio.Task | None, asyncio.Task | None]:
    runtime_audit_task = None
    runtime_audit_loop_task = None
    try:
        background_refresh_request_selectable_runtime_audit = _load_attr(
            "app.services.llm_runtime_audit_service",
            "background_refresh_request_selectable_runtime_audit",
        )

        runtime_audit_task = asyncio.create_task(
            background_refresh_request_selectable_runtime_audit(run_live_probe=False)
        )
        logger_.info("[OK] Scheduled background LLM runtime audit (discovery only, no live probes)")

        audit_interval = float(
            getattr(settings, "llm_runtime_audit_refresh_interval_seconds", 0.0)
            or 0.0
        )
        if audit_interval > 0:
            audit_interval = max(audit_interval, 3600.0)

            async def _runtime_audit_loop() -> None:
                while True:
                    await asyncio.sleep(audit_interval)
                    await background_refresh_request_selectable_runtime_audit(
                        run_live_probe=False
                    )

            runtime_audit_loop_task = asyncio.create_task(_runtime_audit_loop())
            logger_.info(
                "[OK] Scheduled periodic LLM runtime audit every %ss (discovery only)",
                int(audit_interval),
            )
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] Could not schedule LLM runtime audit refresh: %s", exc)
    return runtime_audit_task, runtime_audit_loop_task


async def _schedule_model_health_probes(
    logger_: logging.Logger,
) -> tuple[asyncio.Task | None, asyncio.Task | None]:
    """Schedule lightweight model probes so routing can skip degraded models."""
    if not settings.enable_llm_model_health_probes:
        return None, None

    try:
        run_probe_once = _load_attr(
            "app.services.llm_model_health_probe_service",
            "run_nvidia_model_health_probe_once",
        )
        run_probe_loop = _load_attr(
            "app.services.llm_model_health_probe_service",
            "run_nvidia_model_health_probe_loop",
        )

        probe_task = asyncio.create_task(run_probe_once(logger_obj=logger_))
        interval = float(settings.llm_model_health_probe_interval_seconds or 0.0)
        probe_loop_task = (
            asyncio.create_task(run_probe_loop(logger_obj=logger_))
            if interval > 0
            else None
        )
        logger_.info("[OK] Scheduled NVIDIA model health probe (interval=%ss)", int(interval))
        return probe_task, probe_loop_task
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] Could not schedule model health probes: %s", exc)
        return None, None


def _initialize_unified_client(logger_: logging.Logger) -> None:
    if not settings.enable_unified_client:
        return
    try:
        UnifiedLLMClient = _load_attr(
            "app.engine.llm_providers.unified_client",
            "UnifiedLLMClient",
        )

        UnifiedLLMClient.initialize()
        logger_.info("[OK] UnifiedLLMClient initialized (AsyncOpenAI SDK)")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] UnifiedLLMClient initialization failed: %s", exc)


def _validate_embedding_dimensions(logger_: logging.Logger) -> None:
    try:
        get_embedding_dimensions = _load_attr(
            "app.engine.model_catalog",
            "get_embedding_dimensions",
        )

        expected_dimensions = get_embedding_dimensions(settings.embedding_model)
        if settings.embedding_dimensions != expected_dimensions:
            logger_.error(
                "Embedding dimension mismatch: config=%d, expected=%d. "
                "This may cause pgvector index errors.",
                settings.embedding_dimensions,
                expected_dimensions,
            )
        else:
            logger_.info("Embedding dimension validated: %dd", settings.embedding_dimensions)
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Embedding dimension validation skipped: %s", exc)


def _prewarm_rag_agent(logger_: logging.Logger) -> None:
    try:
        get_rag_agent = _load_attr("app.engine.agentic_rag", "get_rag_agent")
        is_rag_agent_initialized = _load_attr(
            "app.engine.agentic_rag",
            "is_rag_agent_initialized",
        )

        get_rag_agent()
        if is_rag_agent_initialized():
            logger_.info("[OK] RAGAgent singleton pre-warmed (using shared LLM)")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] RAGAgent pre-warm failed: %s", exc)


def _prewarm_corrective_rag(logger_: logging.Logger) -> None:
    try:
        get_corrective_rag = _load_attr(
            "app.engine.agentic_rag",
            "get_corrective_rag",
        )

        get_corrective_rag()
        logger_.info("[OK] CorrectiveRAG pre-warmed (using shared LLMs)")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] CorrectiveRAG pre-warm failed: %s", exc)


def _prewarm_multi_agent_runner(logger_: logging.Logger) -> None:
    try:
        get_wiii_runner = _load_attr(
            "app.engine.multi_agent.runner",
            "get_wiii_runner",
        )
        get_wiii_runner()
        logger_.info("Multi-Agent runner pre-warmed")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Multi-Agent runner pre-warm failed: %s", exc)


async def _run_startup_health_check(logger_: logging.Logger) -> None:
    try:
        check_api_health = _load_attr("app.api.v1.health", "check_api_health")

        health = await check_api_health()
        logger_.info("Startup health check: %s", health.status.value)
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Startup health check skipped: %s", exc)


async def _recover_course_generation_jobs(logger_: logging.Logger) -> None:
    if not settings.enable_lms_integration:
        return
    try:
        recover_course_generation_jobs = _load_attr(
            "app.api.v1.course_generation",
            "recover_course_generation_jobs",
        )

        recovered_jobs = await recover_course_generation_jobs()
        if recovered_jobs:
            logger_.info("Recovered %d course generation job(s) on startup", recovered_jobs)
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Course generation recovery skipped: %s", exc)


async def _initialize_mcp_client(logger_: logging.Logger) -> None:
    if not settings.enable_mcp_client:
        return
    try:
        MCPToolManager = _load_attr("app.mcp.client", "MCPToolManager")

        configs = MCPToolManager.resolve_configs(settings)
        await MCPToolManager.initialize(configs)
        logger_.info("[OK] MCP Client initialized")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] MCP Client initialization failed: %s", exc)


async def _start_scheduled_executor(logger_: logging.Logger) -> Any:
    if not settings.enable_scheduler:
        return None
    try:
        get_scheduled_task_executor = _load_attr(
            "app.services.scheduled_task_executor",
            "get_scheduled_task_executor",
        )

        executor = get_scheduled_task_executor()
        await executor.start()
        logger_.info(
            "Scheduled task executor started (poll every %ds)",
            settings.scheduler_poll_interval,
        )
        return executor
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Scheduled task executor startup failed: %s", exc)
        return None


async def _start_living_agent(logger_: logging.Logger) -> Any:
    if not settings.enable_living_agent:
        return None

    try:
        get_emotion_engine = _load_attr(
            "app.engine.living_agent.emotion_engine",
            "get_emotion_engine",
        )

        emotion_engine = get_emotion_engine()
        loaded = await emotion_engine.load_from_db_if_needed()
        if loaded:
            logger_.info("[OK] Emotion state restored from DB: mood=%s", emotion_engine.mood.value)
        else:
            logger_.info("[OK] Emotion engine initialized with defaults")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] Emotion state restore failed: %s", exc)

    try:
        get_heartbeat_scheduler = _load_attr(
            "app.engine.living_agent.heartbeat",
            "get_heartbeat_scheduler",
        )

        heartbeat = get_heartbeat_scheduler()
        await heartbeat.start()
        logger_.info(
            "[OK] Living Agent heartbeat started (interval=%ds, active %d:00-%d:00 UTC+7)",
            settings.living_agent_heartbeat_interval,
            settings.living_agent_active_hours_start,
            settings.living_agent_active_hours_end,
        )
        return heartbeat
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] Living Agent heartbeat startup failed: %s", exc)
        return None


async def _start_magic_link_maintenance(
    logger_: logging.Logger,
) -> tuple[asyncio.Task | None, asyncio.Task | None]:
    """Start the magic-link cleanup + WS-session reaper background tasks.

    Both run only when ``enable_magic_link_auth`` is on. They are gated together
    since they are two halves of the same feature's hygiene loop. Also picks
    the session store (in-memory vs Valkey) for cross-worker handoff support.
    """
    if not settings.enable_magic_link_auth:
        return None, None

    # Pick the session store (in-memory by default; Valkey if flag+reachable)
    try:
        initialize_session_store = _load_attr(
            "app.auth.magic_link_session_store", "initialize_session_store"
        )
        await initialize_session_store(settings)
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] Magic link session store initialization failed: %s", exc)

    cleanup_task: asyncio.Task | None = None
    reaper_task: asyncio.Task | None = None
    try:
        magic_link_cleanup_loop = _load_attr(
            "app.auth.magic_link_service", "magic_link_cleanup_loop"
        )
        magic_link_session_reaper_loop = _load_attr(
            "app.auth.magic_link_service", "magic_link_session_reaper_loop"
        )

        cleanup_task = asyncio.create_task(
            magic_link_cleanup_loop(
                interval_seconds=settings.magic_link_cleanup_interval_seconds,
                grace_period_hours=settings.magic_link_cleanup_grace_hours,
            )
        )
        logger_.info(
            "[OK] Magic link cleanup loop started (every %ds, grace %dh)",
            settings.magic_link_cleanup_interval_seconds,
            settings.magic_link_cleanup_grace_hours,
        )

        # Reaper drops stale sessions older than 2x the WS timeout
        reaper_max_age = float(settings.magic_link_ws_timeout_seconds) * 2.0
        reaper_task = asyncio.create_task(
            magic_link_session_reaper_loop(
                interval_seconds=settings.magic_link_session_reaper_interval_seconds,
                max_age_seconds=reaper_max_age,
            )
        )
        logger_.info(
            "[OK] Magic link WS session reaper started (every %ds, max age %.0fs)",
            settings.magic_link_session_reaper_interval_seconds,
            reaper_max_age,
        )
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] Magic link maintenance startup failed: %s", exc)
    return cleanup_task, reaper_task


async def _start_soul_bridge(logger_: logging.Logger) -> Any:
    if not settings.enable_soul_bridge:
        return None
    try:
        get_soul_bridge = _load_attr("app.engine.soul_bridge", "get_soul_bridge")

        soul_bridge = get_soul_bridge()
        await soul_bridge.initialize(settings)
        connect_results = await soul_bridge.connect_to_peers()
        connected = sum(1 for value in connect_results.values() if value)
        logger_.info(
            "[OK] SoulBridge initialized: %d/%d peers connected",
            connected,
            len(connect_results),
        )
        return soul_bridge
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("[WARN] SoulBridge startup failed: %s", exc)
        return None


async def startup_application(logger_: logging.Logger) -> AppRuntimeResources:
    """Run startup sequence and collect resources for shutdown."""

    resources = AppRuntimeResources()
    _log_startup_banner(logger_)
    _init_observability(logger_)
    _register_runtime_lifecycle_hooks(logger_)
    _validate_postgresql(logger_)
    resources.neo4j_repo = _validate_neo4j(logger_)
    _validate_pgvector(logger_)
    _validate_prompt_loader(logger_)
    _discover_domain_plugins(logger_)
    _maybe_run_migrations(logger_)
    _restore_runtime_policy(logger_)
    _bootstrap_lms_connectors()
    _initialize_llm_pool(logger_)
    _initialize_agent_registry(logger_)
    (
        resources.runtime_audit_task,
        resources.runtime_audit_loop_task,
    ) = await _schedule_runtime_audit(logger_)
    (
        resources.model_health_probe_task,
        resources.model_health_probe_loop_task,
    ) = await _schedule_model_health_probes(logger_)
    _initialize_unified_client(logger_)
    _validate_embedding_dimensions(logger_)
    _prewarm_rag_agent(logger_)
    _prewarm_corrective_rag(logger_)
    _prewarm_multi_agent_runner(logger_)
    logger_.info("ChatService will initialize on first request (memory optimized)")
    await _run_startup_health_check(logger_)
    await _recover_course_generation_jobs(logger_)
    await _initialize_mcp_client(logger_)
    resources.scheduled_executor = await _start_scheduled_executor(logger_)
    resources.heartbeat = await _start_living_agent(logger_)
    resources.soul_bridge = await _start_soul_bridge(logger_)
    (
        resources.magic_link_cleanup_task,
        resources.magic_link_reaper_task,
    ) = await _start_magic_link_maintenance(logger_)
    return resources
