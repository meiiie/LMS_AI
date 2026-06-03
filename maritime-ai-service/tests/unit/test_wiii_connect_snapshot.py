from __future__ import annotations

import json
from dataclasses import replace


def test_wiii_connect_snapshot_serializes_privacy_safe_metadata(monkeypatch):
    from app.engine.wiii_connect.snapshot import (
        WIII_CONNECT_SNAPSHOT_VERSION,
        build_wiii_connect_snapshot,
        settings,
    )

    monkeypatch.setattr(settings, "living_agent_enable_weather", True, raising=False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "weather-secret", raising=False)
    monkeypatch.setattr(settings, "living_agent_weather_city", "Ha Noi", raising=False)

    state = {
        "context": {
            "host_context": {
                "host_type": "lms",
                "connector_id": "lms-connector-1",
                "host_user_id": "private-user-id",
                "metadata": {
                    "pointyTargets": [{"id": "send", "label": "Gui"}],
                },
            },
            "host_capabilities": {
                "host_type": "lms",
                "tools": [
                    {"name": "authoring.preview_lesson_patch"},
                    {"name": "pointy.highlight"},
                ],
            },
            "document_context": {
                "attachments": [
                    {
                        "file_name": "private.docx",
                        "markdown": "RAW DOCUMENT TEXT MUST NOT LEAK",
                    }
                ],
                "source_refs": [{"id": "src-1"}],
                "approval_token": "approval-secret",
            },
        },
        "approval_token": "top-level-approval-secret",
    }

    snapshot = build_wiii_connect_snapshot(state=state, query="tao bai hoc")
    metadata = snapshot.to_metadata()
    serialized = str(metadata)

    assert metadata["version"] == WIII_CONNECT_SNAPSHOT_VERSION
    assert "RAW DOCUMENT TEXT MUST NOT LEAK" not in serialized
    assert "approval-secret" not in serialized
    assert "top-level-approval-secret" not in serialized
    assert "weather-secret" not in serialized
    assert "private.docx" not in serialized
    assert "private-user-id" not in serialized

    status = snapshot.connection_status_map()
    assert status["lms_authoring"]["active"] is True
    assert status["lms_authoring"]["host_user_id_present"] is True
    assert status["host_actions"]["tool_count"] == 2
    assert status["document_corpus"]["attachment_count"] == 1
    assert status["document_corpus"]["source_ref_count"] == 1
    assert status["pointy"]["target_count"] == 1
    assert status["weather"]["active"] is True

    summary = metadata["capability_summary"]
    assert "document_corpus" in summary["active_connection_slugs"]
    assert "document_corpus" in summary["agent_ready_connection_slugs"]
    assert summary["connected_provider_slugs"] == []
    assert "pointy" in summary["suppressed_tool_groups"]
    by_summary_path = {item["path"]: item for item in summary["path_readiness"]}
    assert by_summary_path["document_grounded_answer"]["status"] == "ready"
    assert by_summary_path["lms_document_apply"]["status"] == "guarded"
    assert by_summary_path["lms_document_apply"]["reason"] == (
        "runtime_approval_gate_required"
    )
    assert by_summary_path["external_app_action"]["status"] == "blocked"
    assert by_summary_path["external_app_action"]["reason"] == (
        "no_agent_ready_external_provider"
    )


def test_wiii_connect_snapshot_fails_closed_without_host_or_provider(monkeypatch):
    from app.engine.wiii_connect.snapshot import build_wiii_connect_snapshot, settings

    monkeypatch.setattr(settings, "living_agent_enable_weather", False, raising=False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "", raising=False)

    snapshot = build_wiii_connect_snapshot(state={"context": {}}, query="")
    status = snapshot.connection_status_map()

    assert status["server"]["active"] is True
    assert status["lms_authoring"]["active"] is False
    assert status["lms_authoring"]["reason"] == "missing_lms_host"
    assert status["host_actions"]["active"] is False
    assert status["host_actions"]["reason"] == "missing_host_tools"
    assert status["weather"]["active"] is True
    assert status["weather"]["reason"] == "tool_runtime_available"
    assert status["weather"]["tool_runtime_available"] is True
    assert status["query"]["active"] is False

    doctor = snapshot.doctor_report().to_metadata()
    by_path = {item["path"]: item for item in doctor["path_diagnostics"]}

    assert doctor["version"] == "wiii_connect_doctor.v0"
    assert doctor["status"] == "degraded"
    assert doctor["summary"]["blocked_paths"] > 0
    assert by_path["casual_chat"]["status"] == "ready"
    assert by_path["weather_lookup"]["status"] == "ready"
    assert by_path["external_app_action"]["status"] == "blocked"
    assert by_path["external_app_action"]["reason"] == (
        "no_agent_ready_external_provider"
    )
    summary = snapshot.to_metadata()["capability_summary"]
    by_summary_path = {item["path"]: item for item in summary["path_readiness"]}
    assert summary["connected_provider_slugs"] == []
    assert summary["agent_ready_provider_slugs"] == []
    assert by_summary_path["external_app_action"]["status"] == "blocked"
    assert by_summary_path["external_app_action"]["reason"] == (
        "no_agent_ready_external_provider"
    )
    providers = {item["provider_slug"]: item for item in doctor["provider_diagnostics"]}
    facebook = providers["facebook"]
    facebook_stages = {stage["key"]: stage for stage in facebook["stages"]}
    assert facebook["status"] == "blocked"
    assert facebook["reason"] == "connection_storage_unavailable"
    assert facebook["connection_status"] == "not_connected"
    assert facebook["agent_ready"] is False
    assert facebook["required_next"] == ["configure_wiii_connect_storage"]
    assert facebook["connection_lifecycle"]["version"] == (
        "wiii_connect_connection_lifecycle.v1"
    )
    assert facebook["connection_lifecycle"]["status"] == "disconnected"
    assert facebook["connection_lifecycle"]["reason"] == (
        "connection_storage_unavailable"
    )
    assert facebook["connection_lifecycle"]["required_next"] == [
        "configure_wiii_connect_storage"
    ]
    assert facebook_stages["registry"]["status"] == "ready"
    assert facebook_stages["adapter"]["status"] == "blocked"
    assert facebook_stages["adapter"]["reason"] == "provider_adapter_not_bound"
    assert facebook_stages["account"]["status"] == "blocked"
    assert facebook_stages["agent_policy"]["status"] == "pending"
    assert facebook_stages["gateway"]["status"] == "blocked"
    assert "path:external_app_action:no_agent_ready_external_provider" in doctor[
        "top_blockers"
    ]


def test_wiii_connect_snapshot_distinguishes_connected_account_from_agent_ready(
    monkeypatch,
):
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
    )
    from app.engine.wiii_connect import snapshot as snapshot_module

    class FakeStorage:
        def list_connection_records(self, **kwargs):
            if kwargs["provider_slug"] != "facebook":
                return ()
            return (
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_local_active",
                    provider_slug="facebook",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True),
                    reason="provider_connection_list",
                ),
            )

    monkeypatch.setattr(
        snapshot_module,
        "storage_status_metadata",
        lambda: {
            "persistent": True,
            "connection_table_ready": True,
            "audit_ledger_ready": True,
        },
    )
    monkeypatch.setattr(
        snapshot_module,
        "get_wiii_connect_persistent_storage",
        lambda: FakeStorage(),
    )

    snapshot = snapshot_module.build_wiii_connect_snapshot(
        state={"user_id": "user-1", "organization_id": "org-1", "context": {}},
        query="facebook connected?",
    )
    status = snapshot.connection_status_map()["facebook"]
    doctor = snapshot.doctor_report().to_metadata()
    facebook_doctor = {
        item["provider_slug"]: item for item in doctor["provider_diagnostics"]
    }["facebook"]
    facebook_stages = {stage["key"]: stage for stage in facebook_doctor["stages"]}

    assert status["status"] == "connected"
    assert status["active"] is True
    assert status["agent_ready"] is False
    assert status["reason"] == "provider_adapter_not_bound"
    assert status["connection_count"] == 1
    assert status["active_connection_count"] == 1
    assert status["adapter_bound"] is False
    assert status["connection_lifecycle"]["status"] == "connected"
    assert status["connection_lifecycle"]["connection_present"] is True
    assert status["connection_lifecycle"]["agent_ready"] is False
    assert "wiii_connect.facebook.connected" in status["capabilities"]
    assert "wiii_connect.facebook.agent_ready" not in status["capabilities"]
    assert facebook_doctor["status"] == "guarded"
    assert facebook_doctor["reason"] == "provider_adapter_not_bound"
    assert facebook_doctor["required_next"] == ["bind_provider_adapter"]
    assert facebook_doctor["connection_lifecycle"]["status"] == "connected"
    assert facebook_stages["registry"]["status"] == "ready"
    assert facebook_stages["adapter"]["status"] == "blocked"
    assert facebook_stages["account"]["status"] == "ready"
    assert facebook_stages["agent_policy"]["status"] == "blocked"
    assert facebook_stages["gateway"]["status"] == "blocked"
    assert snapshot.agent_ready_external_provider_slugs() == ()
    summary = snapshot.to_metadata()["capability_summary"]
    assert summary["connected_provider_slugs"] == ["facebook"]
    assert summary["agent_ready_provider_slugs"] == []
    assert summary["connected_scope_names"] == ["read"]


def test_wiii_connect_snapshot_projects_backend_provider_connection(monkeypatch):
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
    )
    from app.engine.wiii_connect import snapshot as snapshot_module

    def enable_provider(entry, config):
        return replace(
            entry,
            enabled=True,
            agent_ready=True,
            action_allowlist=("FACEBOOK_CREATE_PAGE_POST",),
            default_scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
            requirements=(),
            connect_requirements=(),
            agent_ready_requirements=(),
            warnings=(),
        )

    class FakeStorage:
        def list_connection_records(self, **kwargs):
            assert kwargs["organization_id"] == "org-1"
            assert kwargs["user_id"] == "user-1"
            if kwargs["provider_slug"] != "facebook":
                return ()
            return (
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_secret_active",
                    provider_slug="facebook",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
                    account_label="Private Facebook Page",
                    external_account_ref="external-secret-ref",
                    reason="provider_connection_list",
                ),
            )

    monkeypatch.setattr(
        snapshot_module,
        "build_composio_execution_enabled_entry",
        enable_provider,
    )
    monkeypatch.setattr(
        snapshot_module,
        "storage_status_metadata",
        lambda: {
            "persistent": True,
            "connection_table_ready": True,
            "audit_ledger_ready": True,
        },
    )
    monkeypatch.setattr(
        snapshot_module,
        "get_wiii_connect_persistent_storage",
        lambda: FakeStorage(),
    )

    snapshot = snapshot_module.build_wiii_connect_snapshot(
        state={"user_id": "user-1", "organization_id": "org-1", "context": {}},
        query="đăng một bài lên facebook",
    )
    metadata = snapshot.to_metadata()
    serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    facebook = {
        connection["slug"]: connection for connection in metadata["connections"]
    }["facebook"]

    assert facebook["status"] == "connected"
    assert facebook["active"] is True
    assert facebook["agent_ready"] is True
    assert facebook["source"] == "wiii_connect_persistent_storage"
    assert facebook["reason"] == "connected"
    assert facebook["connection_count"] == 1
    assert facebook["active_connection_count"] == 1
    assert facebook["connection_ref_present"] is True
    assert facebook["connection_state"] == "connected"
    assert facebook["scope_count"] == 3
    assert facebook["connection_lifecycle"]["status"] == "connected"
    assert facebook["connection_lifecycle"]["ready_to_execute_action"] is True
    assert "wiii_connect.facebook.agent_ready" in facebook["capabilities"]
    summary = metadata["capability_summary"]
    by_summary_path = {item["path"]: item for item in summary["path_readiness"]}
    assert summary["connected_provider_slugs"] == ["facebook"]
    assert summary["agent_ready_provider_slugs"] == ["facebook"]
    assert summary["connected_scope_names"] == ["apply", "preview", "read"]
    assert "pointy" in summary["suppressed_tool_groups"]
    assert by_summary_path["external_app_action"]["status"] == "guarded"
    assert by_summary_path["external_app_action"]["reason"] == (
        "provider_worker_gateway_required"
    )
    assert by_summary_path["external_app_action"]["agent_ready_connection_slugs"] == [
        "facebook"
    ]
    assert snapshot.agent_ready_external_provider_slugs() == ("facebook",)
    doctor = snapshot.doctor_report().to_metadata()
    by_path = {item["path"]: item for item in doctor["path_diagnostics"]}

    assert doctor["summary"]["external_agent_ready_connections"] == 1
    assert by_path["external_app_action"]["status"] == "guarded"
    assert by_path["external_app_action"]["reason"] == (
        "provider_worker_gateway_required"
    )
    assert by_path["external_app_action"]["agent_ready_connection_slugs"] == [
        "facebook"
    ]
    providers = {item["provider_slug"]: item for item in doctor["provider_diagnostics"]}
    facebook_doctor = providers["facebook"]
    facebook_stages = {stage["key"]: stage for stage in facebook_doctor["stages"]}
    assert facebook_doctor["status"] == "guarded"
    assert facebook_doctor["reason"] == "agent_ready_gateway_required"
    assert facebook_doctor["connection_status"] == "connected"
    assert facebook_doctor["agent_ready"] is True
    assert facebook_doctor["connection_count"] == 1
    assert facebook_doctor["active_connection_count"] == 1
    assert facebook_doctor["scope_count"] == 3
    assert facebook_doctor["required_next"] == ["select_action_and_evaluate_gateway"]
    assert facebook_doctor["connection_lifecycle"]["status"] == "connected"
    assert facebook_doctor["connection_lifecycle"]["agent_ready"] is True
    assert facebook_stages["registry"]["status"] == "ready"
    assert facebook_stages["account"]["status"] == "ready"
    assert facebook_stages["agent_policy"]["status"] == "ready"
    assert facebook_stages["gateway"]["status"] == "pending"

    assert "ca_secret_active" not in serialized
    assert "wcn_" not in serialized
    assert "Private Facebook Page" not in serialized
    assert "external-secret-ref" not in serialized


def test_wiii_connect_snapshot_connected_provider_without_scope_is_not_agent_ready(
    monkeypatch,
):
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
    )
    from app.engine.wiii_connect import snapshot as snapshot_module

    def enable_provider(entry, config):
        return replace(
            entry,
            enabled=True,
            agent_ready=True,
            action_allowlist=("FACEBOOK_CREATE_PAGE_POST",),
            default_scopes=WiiiConnectScopeGrant(),
            requirements=(),
            connect_requirements=(),
            agent_ready_requirements=(),
            warnings=(),
        )

    class FakeStorage:
        def list_connection_records(self, **kwargs):
            if kwargs["provider_slug"] != "facebook":
                return ()
            return (
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_scope_missing",
                    provider_slug="facebook",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(),
                    reason="provider_connection_list",
                ),
            )

    monkeypatch.setattr(
        snapshot_module,
        "build_composio_execution_enabled_entry",
        enable_provider,
    )
    monkeypatch.setattr(
        snapshot_module,
        "storage_status_metadata",
        lambda: {
            "persistent": True,
            "connection_table_ready": True,
            "audit_ledger_ready": True,
        },
    )
    monkeypatch.setattr(
        snapshot_module,
        "get_wiii_connect_persistent_storage",
        lambda: FakeStorage(),
    )

    status = snapshot_module.build_wiii_connect_snapshot(
        state={"user_id": "user-1", "organization_id": "org-1", "context": {}},
    ).connection_status_map()["facebook"]

    assert status["status"] == "connected"
    assert status["active"] is True
    assert status["agent_ready"] is False
    assert status["reason"] == "connected_missing_scope_grant"
