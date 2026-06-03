from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


def _facebook_composio_config():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )

    return WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="test-key",
        api_key_present=True,
        auth_config_by_provider={"facebook": "authcfg_fb"},
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={
            "facebook": ("FACEBOOK_LIST_MANAGED_PAGES",),
        },
        apply_execute_enabled=True,
        apply_action_allowlist_by_provider={
            "facebook": ("FACEBOOK_CREATE_POST", "FACEBOOK_CREATE_PHOTO_POST"),
        },
    )


def _facebook_readonly_composio_config():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )

    return WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="test-key",
        api_key_present=True,
        auth_config_by_provider={"facebook": "authcfg_fb"},
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={
            "facebook": ("FACEBOOK_LIST_MANAGED_PAGES",),
        },
        apply_execute_enabled=False,
    )


def _gmail_composio_config():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )

    return WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="test-key",
        api_key_present=True,
        auth_config_by_provider={"gmail": "authcfg_gmail"},
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={
            "gmail": ("GMAIL_FETCH_EMAILS",),
        },
    )


def _storage_status():
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    return WiiiConnectPersistentStorageStatus(
        enabled=True,
        persistent=True,
        connection_table_ready=True,
        audit_ledger_ready=True,
        reason="ready",
    )


def _connected_facebook_record():
    from app.engine.wiii_connect import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        WiiiConnectVaultSecretRef,
    )

    return WiiiConnectConnectionRecordV1(
        connection_id="ca_fb_1",
        provider_slug="facebook",
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug="facebook",
            connection_id="ca_fb_1",
            vault_key_id="provider-managed://composio/ca_fb_1",
        ),
    )


def _connected_gmail_record():
    from app.engine.wiii_connect import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        WiiiConnectVaultSecretRef,
    )

    return WiiiConnectConnectionRecordV1(
        connection_id="ca_gmail_1",
        provider_slug="gmail",
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug="gmail",
            connection_id="ca_gmail_1",
            vault_key_id="provider-managed://composio/ca_gmail_1",
        ),
    )


def _state_with_facebook_direct_plan():
    from app.engine.multi_agent.external_app_action_runtime import (
        record_external_app_action_plan,
        resolve_external_app_action_plan,
    )
    from app.engine.multi_agent.external_app_integration_lane import (
        external_app_integration_lane_from_plan,
        record_external_app_integration_lane,
    )

    state = {
        "user_id": "dev-user",
        "organization_id": "org-1",
        "session_id": "session-1",
        "context": {"user_role": "student"},
    }
    plan = resolve_external_app_action_plan(
        query="Wiii dang mot bai viet len Facebook giup toi",
        state=state,
        ready_provider_slugs=("facebook",),
        action_allowlists_by_provider={
            "facebook": ("FACEBOOK_CREATE_POST", "FACEBOOK_CREATE_PHOTO_POST"),
        },
    )
    record_external_app_action_plan(state, plan)
    record_external_app_integration_lane(
        state,
        external_app_integration_lane_from_plan(plan),
    )
    return state


def _state_with_gmail_provider_plan():
    from app.engine.multi_agent.external_app_action_runtime import (
        record_external_app_action_plan,
        resolve_external_app_action_plan,
    )
    from app.engine.multi_agent.external_app_integration_lane import (
        external_app_integration_lane_from_plan,
        record_external_app_integration_lane,
    )

    state = {
        "user_id": "dev-user",
        "organization_id": "org-1",
        "session_id": "session-1",
        "context": {"user_role": "student"},
        "query": "Wiii doc Gmail moi nhat tu giao vien",
    }
    plan = resolve_external_app_action_plan(
        query=str(state["query"]),
        state=state,
        ready_provider_slugs=("gmail",),
        action_allowlists_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )
    record_external_app_action_plan(state, plan)
    record_external_app_integration_lane(
        state,
        external_app_integration_lane_from_plan(plan),
    )
    return state


def _state_with_facebook_provider_plan(
    *,
    action_allowlist: tuple[str, ...] = ("FACEBOOK_LIST_MANAGED_PAGES",),
):
    from app.engine.multi_agent.external_app_action_runtime import (
        record_external_app_action_plan,
        resolve_external_app_action_plan,
    )
    from app.engine.multi_agent.external_app_integration_lane import (
        external_app_integration_lane_from_plan,
        record_external_app_integration_lane,
    )

    state = {
        "user_id": "dev-user",
        "organization_id": "org-1",
        "session_id": "session-1",
        "context": {"user_role": "student"},
        "query": "Wiii read Facebook page list",
    }
    plan = resolve_external_app_action_plan(
        query=str(state["query"]),
        state=state,
        ready_provider_slugs=("facebook",),
        action_allowlists_by_provider={"facebook": action_allowlist},
    )
    record_external_app_action_plan(state, plan)
    record_external_app_integration_lane(
        state,
        external_app_integration_lane_from_plan(plan),
    )
    return state


class _FakeStorage:
    def __init__(self, records=()):
        self.records = tuple(records)
        self.audit_records = []
        self.list_calls = []

    def status(self, *, probe_database: bool = True):
        return _storage_status()

    def list_connection_records(self, **kwargs):
        self.list_calls.append(dict(kwargs))
        return self.records

    def append_audit_record(self, record, *, organization_id: str, user_id: str):
        self.audit_records.append((record, organization_id, user_id))
        return True


def test_wiii_connect_connection_selection_filters_requested_provider(monkeypatch):
    from app.core.security_models import AuthenticatedUser
    from app.engine.wiii_connect import backend_action_executor as module
    from app.engine.wiii_connect.adapter_v1 import public_connection_ref

    fake_storage = _FakeStorage(records=(_connected_facebook_record(),))
    monkeypatch.setattr(
        module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    selected = module.select_wiii_connect_connection(
        "gmail",
        current_user=AuthenticatedUser(
            user_id="dev-user",
            auth_method="test",
            organization_id="org-1",
        ),
        storage=_storage_status().to_public_metadata(),
        connection_ref=public_connection_ref("facebook", "ca_fb_1"),
    )

    assert selected is None
    assert fake_storage.list_calls == [
        {
            "organization_id": "org-1",
            "user_id": "dev-user",
            "provider_slug": "gmail",
        }
    ]


@pytest.mark.asyncio
async def test_wiii_connect_facebook_direct_tool_executes_backend_gateway(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
        WiiiConnectFacebookPageListResult,
        WiiiConnectFacebookPageOption,
    )

    fake_storage = _FakeStorage(records=(_connected_facebook_record(),))
    executed = {}

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_verify_schema(**kwargs):
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            schema_present=True,
            argument_keys=("page_id", "message", "published"),
            required_argument_keys=("page_id", "message", "published"),
        )

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_verify_schema)

    async def fake_list_pages(**_kwargs):
        return WiiiConnectFacebookPageListResult(
            ready=True,
            reason="ready",
            pages=(WiiiConnectFacebookPageOption(page_id="page_1", name="Wiii"),),
        )

    async def fake_execute(**kwargs):
        executed.update(kwargs)
        return WiiiConnectComposioExecuteResult(
            ready=True,
            successful=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            status_code=200,
            data_keys=("id",),
            log_id_present=True,
        )

    monkeypatch.setattr(module, "list_composio_facebook_pages", fake_list_pages)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)

    result = await module.execute_wiii_connect_facebook_post_direct_apply(
        state=_state_with_facebook_direct_plan(),
        message="Wiii Connect test",
    )

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "action_completed"
    assert result["success"] is True
    assert result["action_slug"] == "FACEBOOK_CREATE_POST"
    assert result["page_id_present"] is True
    assert executed["connected_account_id"] == "ca_fb_1"
    assert executed["arguments"] == {
        "page_id": "page_1",
        "message": "Wiii Connect test",
        "published": True,
    }
    assert fake_storage.audit_records
    assert "page_1" not in serialized
    assert "test-key" not in serialized
    assert "wiii-connect:apply" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_facebook_direct_tool_requires_turn_plan(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)

    result = await module.execute_wiii_connect_facebook_post_direct_apply(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        message="Wiii Connect test",
    )

    assert result["status"] == "action_failed"
    assert result["success"] is False
    assert result["error"] == "missing_external_app_action_plan"
    assert result["data"]["execution_gate"]["plan"] is None


@pytest.mark.asyncio
async def test_wiii_connect_facebook_direct_tool_fails_closed_without_connection(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: _FakeStorage(records=()),
    )

    result = await module.execute_wiii_connect_facebook_post_direct_apply(
        state=_state_with_facebook_direct_plan(),
        message="Wiii Connect test",
    )

    assert result["status"] == "action_failed"
    assert result["success"] is False
    assert result["error"] in {"connection_missing", "connection_selection_required"}
    assert result["gateway"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_wiii_connect_generic_tool_executes_curated_readonly_action(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
    )

    fake_storage = _FakeStorage(records=(_connected_gmail_record(),))
    executed = {}

    monkeypatch.setattr(module, "build_composio_adapter_config", _gmail_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_verify_schema(**kwargs):
        assert kwargs["request_id"] == "req-wiii-connect-tool-1"
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            request_id=kwargs["request_id"],
            schema_present=True,
            argument_keys=("query", "max_results"),
            required_argument_keys=("query",),
        )

    async def fake_execute(**kwargs):
        assert kwargs["request_id"] == "req-wiii-connect-tool-1"
        executed.update(kwargs)
        return WiiiConnectComposioExecuteResult(
            ready=True,
            successful=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            request_id=kwargs["request_id"],
            status_code=200,
            data_keys=("messages",),
            log_id_present=True,
        )

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_verify_schema)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)

    result = await module.execute_wiii_connect_provider_action(
        state={
            "user_id": "dev-user",
            "organization_id": "org-1",
            "request_id": "req-wiii-connect-tool-1",
        },
        provider_slug="gmail",
        action_slug="GMAIL_FETCH_EMAILS",
        arguments={
            "query": "from:teacher",
            "max_results": 3,
            "access_token": "client-secret",
        },
    )

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "action_completed"
    assert result["success"] is True
    assert result["provider_slug"] == "gmail"
    assert result["action_slug"] == "GMAIL_FETCH_EMAILS"
    assert executed["connected_account_id"] == "ca_gmail_1"
    assert executed["arguments"] == {"query": "from:teacher", "max_results": 3}
    assert result["data"]["argument_policy"]["accepted_argument_keys"] == [
        "max_results",
        "query",
    ]
    assert result["data"]["argument_policy"]["hidden_argument_count"] == 1
    assert result["data"]["operation_policy"]["status"] == "not_required"
    assert fake_storage.audit_records
    audit_request_ids = {
        record.to_public_metadata()["metadata"]["request"].get("request_id")
        for record, _organization_id, _user_id in fake_storage.audit_records
    }
    assert audit_request_ids == {"req-wiii-connect-tool-1"}
    assert "test-key" not in serialized
    assert "client-secret" not in serialized
    assert "provider-managed://" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_generic_tool_scopes_provider_to_agent_ready_allowlist(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _gmail_composio_config)
    tool = module.make_wiii_connect_execute_action_tool(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        allowed_provider_slugs=("gmail",),
    )

    provider_schema = tool.args["provider_slug"]
    assert provider_schema.get("enum") == ["gmail"] or provider_schema.get("const") == "gmail"
    action_schema = tool.args["action_slug"]
    assert (
        action_schema.get("enum") == ["GMAIL_FETCH_EMAILS"]
        or action_schema.get("const") == "GMAIL_FETCH_EMAILS"
    )

    result = await module.execute_wiii_connect_provider_action(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        provider_slug="facebook",
        action_slug="FACEBOOK_CREATE_POST",
        allowed_provider_slugs=("gmail",),
    )

    assert result["status"] == "action_failed"
    assert result["error"] == "provider_not_agent_ready"
    assert result["data"]["allowed_provider_slugs"] == ["gmail"]


@pytest.mark.asyncio
async def test_wiii_connect_generic_execute_tool_requires_provider_lane(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _gmail_composio_config)

    result = await module.execute_wiii_connect_provider_action(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        provider_slug="gmail",
        action_slug="GMAIL_FETCH_EMAILS",
        arguments={"query": "from:teacher"},
        allowed_provider_slugs=("gmail",),
    )

    assert result["status"] == "action_failed"
    assert result["success"] is False
    assert result["error"] == "missing_external_app_action_plan"
    assert result["data"]["execution_gate"]["plan"] is None


def test_wiii_connect_generic_tool_schema_can_use_plan_action_inventory(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    def fail_if_recomputed():
        raise AssertionError("schema should use ExternalAppActionPlan inventory")

    monkeypatch.setattr(module, "build_composio_adapter_config", fail_if_recomputed)
    tool = module.make_wiii_connect_execute_action_tool(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    provider_schema = tool.args["provider_slug"]
    assert provider_schema.get("enum") == ["gmail"] or provider_schema.get("const") == "gmail"
    action_schema = tool.args["action_slug"]
    assert (
        action_schema.get("enum") == ["GMAIL_FETCH_EMAILS"]
        or action_schema.get("const") == "GMAIL_FETCH_EMAILS"
    )
    assert "connection_ref" not in tool.args
    assert "preview_evidence_id" not in tool.args
    assert "approval_token_present" not in tool.args


def test_wiii_connect_delegate_tool_schema_uses_plan_action_inventory(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    def fail_if_recomputed():
        raise AssertionError("delegate schema should use ExternalAppActionPlan inventory")

    monkeypatch.setattr(module, "build_composio_adapter_config", fail_if_recomputed)
    tool = module.make_wiii_connect_delegate_to_integration_tool(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    provider_schema = tool.args["provider_slug"]
    assert provider_schema.get("enum") == ["gmail"] or provider_schema.get("const") == "gmail"
    action_schema = tool.args["action_slug"]
    assert (
        action_schema.get("enum") == ["GMAIL_FETCH_EMAILS"]
        or action_schema.get("const") == "GMAIL_FETCH_EMAILS"
    )
    assert "connection_ref" not in tool.args
    assert "arguments" not in tool.args
    assert "mutation" not in tool.args
    assert "preview_evidence_id" not in tool.args
    assert "approval_token_present" not in tool.args


def test_wiii_connect_facebook_direct_tool_schema_hides_connection_ref():
    from app.engine.tools import wiii_connect_tools as module

    tool = module.make_wiii_connect_facebook_post_direct_apply_tool(
        state=_state_with_facebook_direct_plan(),
    )

    assert "connection_ref" not in tool.args
    assert "provider_slug" not in tool.args
    assert "page_id" not in tool.args
    assert "image_base64" not in tool.args
    assert "image_media_type" not in tool.args
    assert "image_filename" not in tool.args
    assert "image_url" not in tool.args
    assert set(tool.args) == {"message", "image_policy"}


@pytest.mark.asyncio
async def test_wiii_connect_generic_tool_ignores_injected_connection_ref(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    captured = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return {
            "version": module.WIII_CONNECT_GENERIC_DIRECT_TOOL_VERSION,
            "status": "action_failed",
            "success": False,
            "provider_slug": kwargs["provider_slug"],
            "action_slug": kwargs["action_slug"],
            "data": {},
        }

    monkeypatch.setattr(module, "execute_wiii_connect_provider_action", fake_execute)
    tool = module.make_wiii_connect_execute_action_tool(
        state=_state_with_gmail_provider_plan(),
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    payload = json.loads(
        await tool.ainvoke(
            {
                "provider_slug": "gmail",
                "action_slug": "GMAIL_FETCH_EMAILS",
                "connection_ref": "wcn_injected",
            }
        )
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "connection_ref" not in tool.args
    assert captured["connection_ref"] == ""
    assert "wcn_injected" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_delegate_tool_ignores_injected_connection_ref(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    captured = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return {
            "version": module.WIII_CONNECT_INTEGRATION_DELEGATE_TOOL_VERSION,
            "status": "action_failed",
            "success": False,
            "provider_slug": kwargs["provider_slug"],
            "action_slug": kwargs["action_slug"],
            "data": {},
        }

    monkeypatch.setattr(module, "execute_wiii_connect_delegate_to_integration", fake_execute)
    tool = module.make_wiii_connect_delegate_to_integration_tool(
        state=_state_with_gmail_provider_plan(),
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    payload = json.loads(
        await tool.ainvoke(
            {
                "provider_slug": "gmail",
                "prompt": "doc email moi nhat tu giao vien",
                "action_slug": "GMAIL_FETCH_EMAILS",
                "connection_ref": "wcn_injected",
                "arguments": {"query": "from:attacker"},
                "mutation": "apply",
                "preview_evidence_id": "preview_injected",
                "approval_token_present": True,
            }
        )
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "connection_ref" not in tool.args
    assert captured["connection_ref"] == ""
    assert captured["arguments"] == {}
    assert captured["mutation"] == "read"
    assert captured["preview_evidence_id"] == ""
    assert captured["approval_token_present"] is False
    assert "wcn_injected" not in serialized
    assert "from:attacker" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_delegate_tool_executes_prompt_mapped_read_action(
    monkeypatch,
):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
    )

    fake_storage = _FakeStorage(records=(_connected_gmail_record(),))
    executed = {}

    monkeypatch.setattr(module, "build_composio_adapter_config", _gmail_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_verify_schema(**kwargs):
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            schema_present=True,
            argument_keys=("query", "max_results"),
            required_argument_keys=("query",),
        )

    async def fake_execute(**kwargs):
        executed.update(kwargs)
        return WiiiConnectComposioExecuteResult(
            ready=True,
            successful=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            status_code=200,
            data_keys=("messages",),
            log_id_present=True,
        )

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_verify_schema)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)
    tool = module.make_wiii_connect_delegate_to_integration_tool(
        state=_state_with_gmail_provider_plan(),
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    result = json.loads(
        await tool.ainvoke(
            {
                "provider_slug": "gmail",
                "prompt": "doc 2 email moi nhat tu giao vien",
            }
        )
    )

    worker = result["data"]["integration_worker"]
    argument_plan = worker["argument_plan"]
    serialized_worker = json.dumps(worker, ensure_ascii=False)
    assert result["status"] == "action_completed"
    assert result["success"] is True
    assert executed["arguments"] == {"query": "from:teacher", "max_results": 2}
    assert argument_plan["source"] == "backend_prompt_mapper"
    assert argument_plan["argument_keys"] == ["max_results", "query"]
    assert "doc 2 email" not in serialized_worker
    assert "from:teacher" not in serialized_worker


@pytest.mark.asyncio
async def test_wiii_connect_delegate_execution_feeds_runtime_flow_ledger(
    monkeypatch,
):
    from app.engine.multi_agent.runtime_flow_ledger import (
        RuntimeFlowLedger,
        build_runtime_flow_trace_from_state,
    )
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
    )

    fake_storage = _FakeStorage(records=(_connected_gmail_record(),))

    monkeypatch.setattr(module, "build_composio_adapter_config", _gmail_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_verify_schema(**kwargs):
        assert kwargs["request_id"] == "req-live-provider-ledger"
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            request_id=kwargs["request_id"],
            schema_present=True,
            argument_keys=("query", "max_results"),
            required_argument_keys=("query",),
        )

    async def fake_execute(**kwargs):
        assert kwargs["request_id"] == "req-live-provider-ledger"
        return WiiiConnectComposioExecuteResult(
            ready=True,
            successful=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            request_id=kwargs["request_id"],
            status_code=200,
            data_keys=("messages",),
            log_id_present=True,
        )

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_verify_schema)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)

    state = _state_with_gmail_provider_plan()
    state["request_id"] = "req-live-provider-ledger"
    state["_turn_path_decision"] = {
        "version": "turn_path_decision.v1",
        "path": "external_app_action",
        "reason": "external_app_action_request",
        "bind_tools": True,
        "force_tools": True,
    }
    state["_tool_policy_session"] = {
        "version": "tool_policy_session.v1",
        "path": "external_app_action",
        "reason": "external_app_action_request",
        "bind_tools": True,
        "force_tools": True,
        "visible_tool_names": [module.WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL],
    }
    tool = module.make_wiii_connect_delegate_to_integration_tool(
        state=state,
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    result_json = await tool.ainvoke(
        {
            "provider_slug": "gmail",
            "prompt": "doc 2 email moi nhat tu giao vien",
        }
    )
    result = json.loads(result_json)
    state["tool_call_events"] = [
        {
            "type": "call",
            "name": module.WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
            "args": {"provider_slug": "gmail"},
        },
        {
            "type": "result",
            "name": module.WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
            "result": result_json,
        },
    ]

    trace = build_runtime_flow_trace_from_state(state)
    ledger = RuntimeFlowLedger(request_id="req-live-provider-ledger")
    ledger.observe_metadata(
        {
            "provider": "backend-acceptance",
            "model": "wiii-connect-live-delegate",
            "runtime_authoritative": True,
            "agent_type": "direct",
            "runtime_flow_trace": trace,
        }
    )
    ledger.record_event(
        SimpleNamespace(
            type="tool_call",
            content={"name": module.WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL},
        )
    )
    ledger.record_event(
        SimpleNamespace(
            type="tool_result",
            content={
                "name": module.WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
                "result": result_json,
            },
        )
    )
    ledger.record_event(SimpleNamespace(type="metadata", content={}))
    ledger.record_event(SimpleNamespace(type="done", content={}))
    ledger.mark_finalization("saved")
    payload = ledger.to_payload()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert result["status"] == "action_completed"
    assert trace["external_action_trace"]["observed_action_result"] is True
    assert trace["external_action_trace"]["provider_slug"] == "gmail"
    assert trace["external_action_trace"]["action_slug"] == "GMAIL_FETCH_EMAILS"
    assert trace["external_action_trace"]["worker_outcome"] == "completed"
    assert payload["runtime"]["provider"] == "backend-acceptance"
    assert payload["runtime"]["model"] == "wiii-connect-live-delegate"
    assert payload["tools"]["observed"] == [
        module.WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL
    ]
    assert payload["tools"]["policy_session"]["visible_tool_names"] == [
        module.WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL
    ]
    assert payload["stream"]["event_counts"]["tool_call"] == 1
    assert payload["stream"]["event_counts"]["tool_result"] == 1
    assert payload["stream"]["done_seen"] is True
    assert payload["external_app"]["action_trace"]["worker_outcome"] == "completed"
    assert payload["host_actions"]["result_received"] is True
    assert payload["host_actions"]["result_success"] is True
    assert payload["finalization"]["status"] == "saved"
    assert fake_storage.audit_records
    assert "ca_gmail_1" not in serialized
    assert "provider-managed://" not in serialized
    assert "test-key" not in serialized
    assert "doc 2 email" not in serialized
    assert "from:teacher" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_facebook_direct_tool_ignores_injected_connection_ref(
    monkeypatch,
):
    from app.engine.tools import wiii_connect_tools as module

    captured = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return {
            "version": module.WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION,
            "status": "action_failed",
            "success": False,
            "provider_slug": kwargs["provider_slug"],
            "data": {},
        }

    monkeypatch.setattr(
        module,
        "execute_wiii_connect_facebook_post_direct_apply",
        fake_execute,
    )
    tool = module.make_wiii_connect_facebook_post_direct_apply_tool(
        state=_state_with_facebook_direct_plan(),
    )

    payload = json.loads(
        await tool.ainvoke(
            {
                "provider_slug": "gmail",
                "page_id": "page_private",
                "message": "No injected account binding",
                "connection_ref": "wcn_injected",
                "image_base64": "raw_image_payload",
                "image_media_type": "image/png",
                "image_filename": "private.png",
                "image_url": "https://example.invalid/private.png",
            }
        )
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "connection_ref" not in tool.args
    assert "page_id" not in tool.args
    assert "image_url" not in tool.args
    assert captured["provider_slug"] == "facebook"
    assert captured["connection_ref"] == ""
    assert captured["page_id"] == ""
    assert captured["image_base64"] is None
    assert captured["image_media_type"] is None
    assert captured["image_filename"] is None
    assert captured["image_url"] is None
    assert "wcn_injected" not in serialized
    assert "page_private" not in serialized
    assert "raw_image_payload" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_delegate_tool_executes_single_read_worker_action(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
    )

    fake_storage = _FakeStorage(records=(_connected_gmail_record(),))
    executed = {}

    monkeypatch.setattr(module, "build_composio_adapter_config", _gmail_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_verify_schema(**kwargs):
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            schema_present=True,
            argument_keys=("query", "max_results"),
            required_argument_keys=("query",),
        )

    async def fake_execute(**kwargs):
        executed.update(kwargs)
        return WiiiConnectComposioExecuteResult(
            ready=True,
            successful=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            status_code=200,
            data_keys=("messages",),
            log_id_present=True,
        )

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_verify_schema)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)

    result = await module.execute_wiii_connect_delegate_to_integration(
        state=_state_with_gmail_provider_plan(),
        provider_slug="gmail",
        prompt="doc email moi nhat tu giao vien",
        arguments={"query": "from:teacher", "max_results": 3},
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["version"] == module.WIII_CONNECT_INTEGRATION_DELEGATE_TOOL_VERSION
    assert result["status"] == "action_completed"
    assert result["success"] is True
    assert result["provider_slug"] == "gmail"
    assert result["action_slug"] == "GMAIL_FETCH_EMAILS"
    assert result["data"]["integration_worker"]["executor"] == "provider_worker"
    assert result["data"]["integration_worker"]["action_policy"]["reason"] == (
        "selected_single_read_action"
    )
    assert result["data"]["integration_worker"]["result_classification"]["outcome"] == (
        "completed"
    )
    assert result["data"]["integration_worker"]["stage_sequence"] == [
        "provider_gate",
        "action_policy",
        "ready",
    ]
    assert executed["connected_account_id"] == "ca_gmail_1"
    assert executed["arguments"]["query"] == "from:teacher"
    assert "doc email moi nhat" not in serialized
    assert "test-key" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_delegate_tool_requires_provider_lane(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _gmail_composio_config)

    result = await module.execute_wiii_connect_delegate_to_integration(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        provider_slug="gmail",
        prompt="doc email moi nhat tu giao vien",
        arguments={"query": "from:teacher", "max_results": 3},
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    assert result["version"] == module.WIII_CONNECT_INTEGRATION_DELEGATE_TOOL_VERSION
    assert result["status"] == "action_failed"
    assert result["success"] is False
    assert result["error"] == "missing_external_app_action_plan"
    assert result["data"]["execution_gate"]["plan"] is None


def test_wiii_connect_list_actions_ranks_candidates_from_intent(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)

    result = module.execute_wiii_connect_list_actions(
        provider_slug="facebook",
        intent_prompt="dang mot bai len facebook",
    )

    assert result["status"] == "action_completed"
    catalog = result["data"]["action_catalog"]
    ranking = catalog["ranking"]
    assert ranking["prompt_present"] is True
    assert ranking["candidate_count"] >= 1
    assert ranking["candidates"][0]["slug"] in {
        "FACEBOOK_CREATE_POST",
        "FACEBOOK_CREATE_PHOTO_POST",
    }
    assert "verb_match" in ranking["candidates"][0]["rank_reasons"]


@pytest.mark.asyncio
async def test_wiii_connect_list_actions_tool_hides_disabled_actions_for_agent_scope(
    monkeypatch,
):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(
        module,
        "build_composio_adapter_config",
        _facebook_readonly_composio_config,
    )

    tool = module.make_wiii_connect_list_actions_tool(
        state={"query": "dang mot bai len facebook"},
        allowed_provider_slugs=("facebook",),
    )

    assert "include_disabled" not in tool.args
    payload = json.loads(
        await tool.ainvoke(
            {
                "provider_slug": "facebook",
                "include_disabled": True,
                "intent_prompt": "dang mot bai len facebook",
            }
        )
    )

    catalog = payload["data"]["action_catalog"]
    serialized = json.dumps(catalog, ensure_ascii=False)
    assert payload["status"] == "action_completed"
    assert catalog["action_count"] == 1
    assert catalog["enabled_action_count"] == 1
    assert [action["slug"] for action in catalog["actions"]] == [
        "FACEBOOK_LIST_MANAGED_PAGES"
    ]
    assert "FACEBOOK_CREATE_POST" not in serialized
    assert "FACEBOOK_CREATE_PHOTO_POST" not in serialized


def test_wiii_connect_list_actions_tool_keeps_diagnostic_disabled_toggle():
    from app.engine.tools import wiii_connect_tools as module

    tool = module.make_wiii_connect_list_actions_tool()

    assert tool.args["include_disabled"].get("default") is False


@pytest.mark.asyncio
async def test_wiii_connect_list_actions_tool_uses_plan_action_inventory(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)

    tool = module.make_wiii_connect_list_actions_tool(
        state={"query": "dang mot bai len facebook"},
        allowed_provider_slugs=("facebook",),
        allowed_action_slugs_by_provider={
            "facebook": ("FACEBOOK_LIST_MANAGED_PAGES",),
        },
    )

    payload = json.loads(
        await tool.ainvoke(
            {
                "provider_slug": "facebook",
                "include_disabled": True,
                "intent_prompt": "dang mot bai len facebook",
            }
        )
    )

    catalog = payload["data"]["action_catalog"]
    serialized = json.dumps(catalog, ensure_ascii=False)
    assert payload["status"] == "action_completed"
    assert [action["slug"] for action in catalog["actions"]] == [
        "FACEBOOK_LIST_MANAGED_PAGES"
    ]
    assert "FACEBOOK_CREATE_POST" not in serialized
    assert "FACEBOOK_CREATE_PHOTO_POST" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_list_actions_tool_hides_backend_owned_argument_keys(
    monkeypatch,
):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)

    tool = module.make_wiii_connect_list_actions_tool(
        state={"query": "dang mot bai len facebook"},
        allowed_provider_slugs=("facebook",),
        allowed_action_slugs_by_provider={
            "facebook": ("FACEBOOK_CREATE_POST",),
        },
    )

    payload = json.loads(
        await tool.ainvoke(
            {
                "provider_slug": "facebook",
                "intent_prompt": "dang mot bai len facebook",
            }
        )
    )

    catalog = payload["data"]["action_catalog"]
    action = catalog["actions"][0]
    serialized = json.dumps(catalog, ensure_ascii=False)
    assert [item["slug"] for item in catalog["actions"]] == ["FACEBOOK_CREATE_POST"]
    assert action["argument_keys"] == ["message", "link"]
    assert action["model_argument_keys"] == ["message", "link"]
    assert action["hidden_argument_count"] == 3
    assert "page_id" not in serialized
    assert "published" not in serialized
    assert "scheduled_publish_time" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_generic_tool_blocks_implicit_apply_action(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)

    result = await module.execute_wiii_connect_provider_action(
        state={
            "user_id": "dev-user",
            "organization_id": "org-1",
            "query": "dang mot bai len facebook",
        },
        provider_slug="facebook",
        mutation="apply",
        arguments={"page_id": "page_1", "message": "No implicit action"},
    )

    assert result["status"] == "action_failed"
    assert result["success"] is False
    assert result["error"] == "explicit_action_required_for_mutation"
    assert result["gateway"] is None
    assert result["execution"] is None
    policy = result["data"]["action_policy"]
    assert policy["reason"] == "explicit_action_required_for_mutation"
    assert policy["candidates"][0]["slug"] in {
        "FACEBOOK_CREATE_POST",
        "FACEBOOK_CREATE_PHOTO_POST",
    }


@pytest.mark.asyncio
async def test_wiii_connect_generic_tool_reports_preview_required_for_apply_without_preview(
    monkeypatch,
):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module

    fake_storage = _FakeStorage(records=(_connected_facebook_record(),))

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    result = await module.execute_wiii_connect_provider_action(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        provider_slug="facebook",
        action_slug="FACEBOOK_CREATE_POST",
        arguments={"page_id": "page_1", "message": "No approval", "published": True},
    )

    assert result["status"] == "preview_required"
    assert result["success"] is False
    assert result["gateway"]["status"] == "blocked"
    assert result["error"] == "missing_preview_evidence"
    assert result["execution"] is None
    assert result["data"]["argument_policy"]["accepted_argument_keys"] == ["message"]
    assert result["data"]["argument_policy"]["hidden_argument_count"] == 2
    assert result["data"]["operation_policy"]["status"] == "required"


@pytest.mark.asyncio
async def test_wiii_connect_generic_tool_ignores_unverified_preview_authorization(
    monkeypatch,
):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module

    fake_storage = _FakeStorage(records=(_connected_facebook_record(),))

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    result = await module.execute_wiii_connect_provider_action(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        provider_slug="facebook",
        action_slug="FACEBOOK_CREATE_POST",
        arguments={"page_id": "page_1", "message": "No approval", "published": True},
        preview_evidence_id="preview_ok",
        approval_token_present=True,
    )

    assert result["status"] == "preview_required"
    assert result["success"] is False
    assert result["gateway"]["status"] == "blocked"
    assert result["error"] == "missing_preview_evidence"
    assert result["execution"] is None
    assert result["data"]["operation_policy"]["status"] == "required"
    assert (
        result["data"]["operation_policy"]["caller_claim_ignored"]
        is True
    )
    assert result["data"]["argument_policy"]["accepted_argument_keys"] == ["message"]


@pytest.mark.asyncio
async def test_wiii_connect_delegate_classifies_preview_required(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect import backend_action_executor as executor_module

    fake_storage = _FakeStorage(records=(_connected_facebook_record(),))
    state = _state_with_facebook_provider_plan(
        action_allowlist=("FACEBOOK_CREATE_POST",),
    )

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    result = await module.execute_wiii_connect_delegate_to_integration(
        state=state,
        provider_slug="facebook",
        prompt="dang mot bai len facebook",
        action_slug="FACEBOOK_CREATE_POST",
        mutation="apply",
        arguments={"page_id": "page_1", "message": "Needs preview", "published": True},
        allowed_provider_slugs=("facebook",),
        allowed_action_slugs_by_provider={
            "facebook": ("FACEBOOK_CREATE_POST",),
        },
    )

    worker = result["data"]["integration_worker"]
    classification = worker["result_classification"]
    assert result["version"] == module.WIII_CONNECT_INTEGRATION_DELEGATE_TOOL_VERSION
    assert result["status"] == "preview_required"
    assert result["success"] is False
    assert result["error"] == "missing_preview_evidence"
    assert classification["outcome"] == "preview_required"
    assert classification["failed_stage"] == "preview"
