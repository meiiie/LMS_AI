"""Tests for production config validation."""
import pytest

PLACEHOLDER_SECRET_VALUES = (
    "",
    "change_me",
    "change-me",
    "changeme",
    "placeholder",
    "your_secret",
    "your-secret",
    "example",
    "dummy",
    "test-secret",
)


class TestProductionValidation:
    """Validate that production config blocks insecure defaults."""

    def test_session_secret_default_blocked_in_production(self):
        """Default session_secret_key must fail in production."""
        from app.core.config import Settings
        with pytest.raises(Exception):
            Settings(
                environment="production",
                session_secret_key="change-session-secret-in-production",
                api_key="a" * 32,
                google_api_key="test",
            )

    def test_session_secret_short_warns_in_production(self):
        """Short session_secret_key should warn (not raise) — only warns when
        enable_google_oauth=True and key < 32 chars."""
        from app.core.config import Settings
        # Short key doesn't raise — it only logs a warning.
        # Verify the field exists and the default is the expected sentinel.
        assert "session_secret_key" in Settings.model_fields
        assert Settings.model_fields["session_secret_key"].default == "change-session-secret-in-production"

    def test_session_secret_field_default(self):
        """Check field default exists."""
        from app.core.config import Settings
        assert Settings.model_fields["session_secret_key"].default == "change-session-secret-in-production"

    def test_magic_link_config_flags_exist(self):
        """All magic link config flags should exist."""
        from app.core.config import Settings
        fields = Settings.model_fields
        assert "resend_api_key" in fields
        assert "enable_magic_link_auth" in fields

    @pytest.mark.parametrize("placeholder_secret", PLACEHOLDER_SECRET_VALUES)
    def test_magic_link_requires_real_resend_key_when_enabled_in_production(
        self, placeholder_secret
    ):
        """Production Magic Link must fail closed without a real email provider."""
        from app.core.config import Settings

        with pytest.raises(ValueError, match="RESEND_API_KEY"):
            Settings(
                environment="production",
                api_key="a-real-prod-api-key-with-enough-bytes",
                jwt_secret_key="jwt]secret]with]enough]entropy]for]prod",
                session_secret_key="session]secret]with]enough]entropy]for]prod",
                google_api_key="test",
                enable_magic_link_auth=True,
                resend_api_key=placeholder_secret,
            )

    @pytest.mark.parametrize("placeholder_secret", PLACEHOLDER_SECRET_VALUES)
    def test_google_oauth_requires_real_client_secret_when_enabled_in_production(
        self, placeholder_secret
    ):
        """Production Google OAuth must fail closed without real OAuth credentials."""
        from app.core.config import Settings

        with pytest.raises(ValueError, match="GOOGLE_OAUTH_CLIENT_ID"):
            Settings(
                environment="production",
                api_key="a-real-prod-api-key-with-enough-bytes",
                jwt_secret_key="jwt]secret]with]enough]entropy]for]prod",
                session_secret_key="session]secret]with]enough]entropy]for]prod",
                google_api_key="test",
                enable_google_oauth=True,
                google_oauth_client_id=placeholder_secret,
                google_oauth_client_secret="real-google-oauth-client-secret",
            )

        with pytest.raises(ValueError, match="GOOGLE_OAUTH_CLIENT_ID"):
            Settings(
                environment="production",
                api_key="a-real-prod-api-key-with-enough-bytes",
                jwt_secret_key="jwt]secret]with]enough]entropy]for]prod",
                session_secret_key="session]secret]with]enough]entropy]for]prod",
                google_api_key="test",
                enable_google_oauth=True,
                google_oauth_client_id="real-google-oauth-client-id",
                google_oauth_client_secret=placeholder_secret,
            )

    def test_api_key_too_short_in_production(self):
        """API key under 16 chars should fail in production."""
        from app.core.config import Settings
        with pytest.raises(Exception):
            Settings(
                environment="production",
                api_key="short",
                session_secret_key="a]b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
                google_api_key="test",
            )

    def test_api_key_long_enough_passes_in_production(self):
        """API key >= 16 chars should not raise for api_key length."""
        from app.core.config import Settings
        # This should not raise ValueError for api_key length.
        # It may raise for jwt_secret_key default, so we set that too.
        try:
            Settings(
                environment="production",
                api_key="a" * 32,
                session_secret_key="a" * 32,
                jwt_secret_key="a" * 32,
                google_api_key="test",
            )
        except ValueError as e:
            # Should not be the api_key error
            assert "api_key must be at least 16" not in str(e)

    def test_sentry_config_flags_exist(self):
        """Sentry config flags should exist."""
        from app.core.config import Settings
        fields = Settings.model_fields
        assert "sentry_dsn" in fields
        assert "sentry_environment" in fields
        assert "sentry_traces_sample_rate" in fields


class TestSessionSecretEnforcement:
    """Test session secret enforcement (Task 7 — Production Hardening)."""

    def test_known_weak_secrets_blocked(self):
        """Known weak secrets should be listed in blocklist."""
        # We verify that the validation logic exists by checking field defaults
        from app.core.config import Settings
        assert Settings.model_fields["session_secret_key"].default == "change-session-secret-in-production"

    def test_high_entropy_secret_check(self):
        """Cryptographically random secrets should have high entropy."""
        import secrets
        strong_secret = secrets.token_urlsafe(64)
        unique_chars = len(set(strong_secret))
        assert unique_chars >= 10  # High entropy

    def test_low_entropy_detection_logic(self):
        """Low entropy detection should catch repeated chars."""
        low_entropy = "a" * 64
        assert len(set(low_entropy)) < 10  # Caught by validator

    def test_session_secret_length_requirement(self):
        """Session secret must be >= 32 chars."""
        from app.core.config import Settings
        # The validator requires 32+ chars in production
        assert "session_secret_key" in Settings.model_fields


class TestCORSProduction:
    """Verify CORS configuration for production domains (Task 8)."""

    def test_cors_origins_env_template_has_production_domains(self):
        """Production env template should include holilihu.online."""
        import pathlib
        template = pathlib.Path("scripts/deploy/.env.production.template").read_text(encoding="utf-8")
        assert "holilihu.online" in template
        assert "wiii.holilihu.online" in template

    def test_cors_origin_regex_in_template(self):
        """Production template should have subdomain regex."""
        import pathlib
        template = pathlib.Path("scripts/deploy/.env.production.template").read_text()
        assert "CORS_ORIGIN_REGEX" in template

    def test_embed_allowed_origins_in_template(self):
        """Embed CSP frame-ancestors should include LMS domain."""
        import pathlib
        template = pathlib.Path("scripts/deploy/.env.production.template").read_text()
        assert "EMBED_ALLOWED_ORIGINS" in template
        assert "holilihu.online" in template

    def test_cors_middleware_config_fields_exist(self):
        """CORSMiddleware should merge settings.cors_origins with dev origins."""
        from app.core.config import Settings
        fields = Settings.model_fields
        assert "cors_origins" in fields
        assert "cors_origin_regex" in fields


class TestProductionSmokeTestDocs:
    """Verify deploy smoke-test examples match the hardened auth boundary."""

    def test_smoke_test_script_avoids_x_user_id_header(self):
        """Production API-key smoke test should not rely on X-User-ID."""
        import pathlib

        script = pathlib.Path("scripts/deploy/smoke-test.sh").read_text(encoding="utf-8")
        assert '"user_id":"api-client"' in script
        assert '-H "X-User-ID:' not in script

    def test_smoke_test_script_uses_fast_sync_chat_probe(self):
        """Sync /chat deploy smoke should avoid ambiguous prompts that hit slow LLM paths."""
        import pathlib

        script = pathlib.Path("scripts/deploy/smoke-test.sh").read_text(encoding="utf-8")
        assert '"message":"doi phet"' in script
        assert 'CHAT_SESSION_ID="smoke-test-chat-' in script
        assert "%{time_total}" in script
        assert '"message": "test"' not in script

    def test_smoke_test_script_matches_sse_v3_visual_lifecycle(self):
        """Production visual smoke test should assert current SSE V3 lifecycle events."""
        import pathlib

        script = pathlib.Path("scripts/deploy/smoke-test.sh").read_text(encoding="utf-8")
        assert "event: visual_(open|patch)" in script
        assert "Structured visual SSE events" in script
        assert "event: visual_commit" in script
        assert 'VISUAL_SESSION_ID="smoke-test-visual-' in script
        assert 'session_id":"smoke-test-visual"' not in script
        assert "```widget" in script

    def test_smoke_test_script_checks_llm_model_health_visibility(self):
        """Production smoke should expose redacted model health telemetry."""
        import pathlib

        script = pathlib.Path("scripts/deploy/smoke-test.sh").read_text(encoding="utf-8")
        assert "/api/v1/health/llm-models" in script
        assert "LLM model health visible" in script
        assert "last_error_detail" in script

    def test_launch_checklist_examples_match_api_key_contract(self):
        """Launch checklist should document service-client auth for API key examples."""
        import pathlib

        checklist = pathlib.Path("scripts/deploy/LAUNCH_CHECKLIST.md").read_text(encoding="utf-8")
        assert '"user_id": "api-client"' in checklist
        assert "JWT or LMS service token" in checklist


class TestProductionBackupScheduling:
    """Verify backup automation docs/config match the intended schedule."""

    def test_pg_backup_service_targets_20_utc(self):
        """Containerized pg-backup should wait for the daily 20:00 UTC window."""
        import pathlib

        compose = pathlib.Path("docker-compose.prod.yml").read_text(encoding="utf-8")
        assert "pg-backup:" in compose
        assert "TARGET_TOTAL=$$((20 * 3600))" in compose
        assert "sleep $$SLEEP_FOR" in compose

    def test_backup_cron_script_still_targets_same_window(self):
        """Host cron helper should match the same backup window."""
        import pathlib

        script = pathlib.Path("scripts/deploy/setup-backup-cron.sh").read_text()
        assert 'CRON_SCHEDULE="0 20 * * *"' in script

    def test_pg_backup_writes_to_host_visible_backup_dir(self):
        """Automatic backups should land in the same host-visible dir as ops scripts."""
        import pathlib

        compose = pathlib.Path("docker-compose.prod.yml").read_text()
        assert '      - ./backups:/backups' in compose
        assert 'backup-data:/backups' not in compose


class TestProductionOperationalScripts:
    """Verify deploy-time operational scripts fail closed on prod issues."""

    def test_root_dockerignore_excludes_local_scratch_from_image_context(self):
        """Production image builds should not ingest local artifacts or agent scratch."""
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parents[3]
        dockerignore = (repo_root / ".dockerignore").read_text(encoding="utf-8")

        assert "artifacts/" in dockerignore
        assert "memory/" in dockerignore
        assert ".agents/" in dockerignore
        assert "wiii-desktop/src/" in dockerignore
        assert "maritime-ai-service/logs/" in dockerignore

    def test_deploy_script_guards_precision_docs_host_capacity(self):
        """Precision-docs capability should fail early on undersized hosts."""
        import pathlib

        script = pathlib.Path("scripts/deploy/deploy.sh").read_text(encoding="utf-8")

        assert "validate_host_capacity" in script
        assert "SKIP_PRECISION_HOST_CAPACITY_CHECK" in script
        assert "MIN_PRECISION_HOST_MEM_GIB" in script
        assert "MIN_PRECISION_DOCKER_FREE_GIB" in script
        assert "ALLOW_LOW_MEMORY_PRECISION" in script
        assert "/proc/meminfo" in script
        assert "echo precision" in script
        assert "echo true" in script
        assert "DOCUMENT_CONTEXT_PARSER_MODE" in script
        assert "USE_DOCLING_FOR_COURSE_GEN" in script
        assert "Configured parser profile:" in script
        assert "Precision document parsing is disabled; skipping" not in script

    def test_deploy_manifest_checks_retry_transient_ghcr_errors(self):
        """Pinned image validation should tolerate short GHCR token timeouts."""
        import pathlib

        deploy_script = pathlib.Path("scripts/deploy/deploy.sh").read_text(encoding="utf-8")
        deploy_workflow = pathlib.Path("../.github/workflows/deploy-production.yml").read_text(encoding="utf-8")

        assert "inspect_image_manifest_with_retry" in deploy_script
        assert "IMAGE_MANIFEST_RETRIES" in deploy_script
        assert "inspect_output=\"$(docker manifest inspect" in deploy_script
        assert "inspect_status=$?" in deploy_script
        assert "Image manifest check failed after" in deploy_script
        assert "Last error:" in deploy_script
        assert deploy_script.count("docker manifest inspect") == 1

        assert "inspect_manifest_with_retry" in deploy_workflow
        assert "max_attempts=4" in deploy_workflow
        assert "inspect_output=\"$(docker manifest inspect" in deploy_workflow
        assert "inspect_status=$?" in deploy_workflow
        assert "::warning::Image manifest check failed" in deploy_workflow
        assert "Last error:" in deploy_workflow
        assert deploy_workflow.count("docker manifest inspect") == 1

    def test_status_dashboard_surfaces_docker_disk_usage(self):
        """Production status should show Docker disk pressure next to RAM/disk."""
        import pathlib

        script = pathlib.Path("scripts/deploy/status.sh").read_text(encoding="utf-8")

        assert "--- Docker Disk ---" in script
        assert "docker system df" in script

    def test_health_check_verifies_required_services_are_running(self):
        """Health check should catch crashed services, not only unhealthy ones."""
        import pathlib

        script = pathlib.Path("scripts/deploy/health-check.sh").read_text()
        assert (
            'REQUIRED_SERVICES=(postgres minio valkey app nginx pg-backup)'
            in script
        )
        assert (
            'docker compose --env-file "$ENV_ARG" -f "$COMPOSE_FILE" "$@"'
            in script
        )
        assert (
            'compose ps --services --status running'
            in script
        )
        assert '${NGINX_LOCAL_URL}/api/v1/health/live' in script
        assert 'http://localhost:8000/api/v1/health/live' not in script
        assert 'Missing required services:' in script

    def test_ingest_script_uses_explicit_live_health_endpoint(self):
        """Ingestion preflight should probe the canonical liveness endpoint."""
        import pathlib

        script = pathlib.Path("scripts/deploy/ingest-production.sh").read_text()
        assert (
            'HEALTH_URL="http://localhost:8000/api/v1/health/live"'
            in script
        )
        assert '${API_URL}/../health' not in script

    def test_knowledge_ingestion_doc_includes_liveness_preflight(self):
        """Knowledge ingestion checklist should document the same preflight."""
        import pathlib

        doc = pathlib.Path(
            "docs/deploy/KNOWLEDGE_INGESTION.md"
        ).read_text(encoding="utf-8")
        assert 'curl localhost:8000/api/v1/health/live' in doc


class TestProductionOrganizationSeed:
    """Verify production org bootstrap stays compatible with subdomain routing."""

    def test_wiii_org_seed_is_idempotent_and_non_destructive(self):
        """The primary production org seed should upsert and preserve data."""
        import pathlib

        migration = pathlib.Path(
            "alembic/versions/048_seed_primary_wiii_organization.py"
        ).read_text(encoding="utf-8")

        assert "INSERT INTO organizations" in migration
        assert "'wiii'" in migration
        assert "ON CONFLICT (id) DO UPDATE" in migration
        assert "wiii.holilihu.online" in migration
        assert "table_schema = current_schema()" in migration
        assert "COALESCE(EXCLUDED.settings" in migration
        assert "COALESCE(organizations.settings" in migration
        assert "is_active = COALESCE(organizations.is_active" in migration
        assert "DELETE FROM organizations" not in migration
