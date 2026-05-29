from __future__ import annotations

import json

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


class _FakeStorage:
    def __init__(self, records=()):
        self.records = tuple(records)
        self.audit_records = []

    def status(self, *, probe_database: bool = True):
        return _storage_status()

    def list_connection_records(self, **_kwargs):
        return self.records

    def append_audit_record(self, record, *, organization_id: str, user_id: str):
        self.audit_records.append((record, organization_id, user_id))
        return True


@pytest.mark.asyncio
async def test_wiii_connect_facebook_direct_tool_executes_backend_gateway(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
        WiiiConnectFacebookPageListResult,
        WiiiConnectFacebookPageOption,
    )

    fake_storage = _FakeStorage(records=(_connected_facebook_record(),))
    executed = {}

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)
    monkeypatch.setattr(module, "get_wiii_connect_persistent_storage", lambda: fake_storage)

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

    monkeypatch.setattr(module, "verify_composio_tool_schema", fake_verify_schema)

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
    monkeypatch.setattr(module, "execute_composio_tool", fake_execute)

    result = await module.execute_wiii_connect_facebook_post_direct_apply(
        state={
            "user_id": "dev-user",
            "organization_id": "org-1",
            "session_id": "session-1",
            "context": {"user_role": "student"},
        },
        message="Wiii Connect test",
    )

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "action_completed"
    assert result["success"] is True
    assert result["action_slug"] == "FACEBOOK_CREATE_POST"
    assert executed["connected_account_id"] == "ca_fb_1"
    assert executed["arguments"] == {
        "page_id": "page_1",
        "message": "Wiii Connect test",
        "published": True,
    }
    assert fake_storage.audit_records
    assert "test-key" not in serialized
    assert "wiii-connect:apply" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_facebook_direct_tool_fails_closed_without_connection(monkeypatch):
    from app.engine.tools import wiii_connect_tools as module

    monkeypatch.setattr(module, "build_composio_adapter_config", _facebook_composio_config)
    monkeypatch.setattr(
        module,
        "get_wiii_connect_persistent_storage",
        lambda: _FakeStorage(records=()),
    )

    result = await module.execute_wiii_connect_facebook_post_direct_apply(
        state={"user_id": "dev-user", "organization_id": "org-1"},
        message="Wiii Connect test",
    )

    assert result["status"] == "action_failed"
    assert result["success"] is False
    assert result["error"] in {"connection_missing", "connection_selection_required"}
    assert result["gateway"]["status"] == "blocked"
