from __future__ import annotations

import json


class _FakeResult:
    def __init__(self, row=None, *, rowcount: int = 0):
        self._row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def fetchone(self):
        return self._row


class _FakeSession:
    def __init__(self, row=None, *, rowcount: int = 0):
        self.row = row
        self.rowcount = rowcount
        self.executions = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.executions.append(
            {
                "statement": str(statement),
                "params": dict(params or {}),
            }
        )
        return _FakeResult(self.row, rowcount=self.rowcount)

    def commit(self):
        self.commits += 1


def test_persistent_storage_status_reports_ready_when_tables_exist():
    from app.engine.wiii_connect.persistent_storage import WiiiConnectPersistentStorage

    session = _FakeSession(
        row=("wiii_connect_connections", "wiii_connect_audit_ledger"),
    )
    storage = WiiiConnectPersistentStorage(session_factory=lambda: session)

    status = storage.status()
    metadata = status.to_public_metadata()

    assert metadata["version"] == "wiii_connect_persistent_storage.v1"
    assert metadata["persistent"] is True
    assert metadata["connection_table_ready"] is True
    assert metadata["audit_ledger_ready"] is True
    assert metadata["reason"] == "ready"


def test_persistent_audit_append_stores_redacted_metadata_only():
    from app.engine.wiii_connect.audit_ledger import build_audit_ledger_record
    from app.engine.wiii_connect.persistent_storage import WiiiConnectPersistentStorage

    session = _FakeSession()
    storage = WiiiConnectPersistentStorage(session_factory=lambda: session)
    record = build_audit_ledger_record(
        event_kind="provider",
        provider_slug="facebook",
        status="blocked",
        reason="provider_disabled",
        surface="desktop",
        metadata={
            "account_id": "page_1",
            "access_token": "secret-value",
            "nested": {"client_secret": "secret-value", "safe": "ok"},
        },
    )

    assert storage.append_audit_record(
        record,
        organization_id="org_1",
        user_id="user_1",
    )
    params = session.executions[-1]["params"]
    metadata = json.loads(params["metadata"])
    serialized = json.dumps(params, sort_keys=True, default=str)

    assert params["organization_id"] == "org_1"
    assert params["user_id"] == "user_1"
    assert params["provider_slug"] == "facebook"
    assert metadata["account_id"] == "page_1"
    assert metadata["nested"]["safe"] == "ok"
    assert "redacted_sensitive_field" in serialized
    assert "access_token" not in serialized
    assert "client_secret" not in serialized
    assert "secret-value" not in serialized
    assert session.commits == 1


def test_connection_upsert_stores_only_public_vault_ref_metadata():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        WiiiConnectVaultSecretRef,
    )
    from app.engine.wiii_connect.persistent_storage import WiiiConnectPersistentStorage

    session = _FakeSession()
    storage = WiiiConnectPersistentStorage(session_factory=lambda: session)
    connection = WiiiConnectConnectionRecordV1(
        connection_id="conn_1",
        provider_slug="facebook",
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True, write=True),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug="facebook",
            connection_id="conn_1",
            vault_key_id="vault://tenant/private/oauth-token-secret",
            secret_version="v1",
        ),
        account_label="Wiii Page",
        external_account_ref="page_1",
    )

    assert storage.upsert_connection_record(
        connection,
        organization_id="org_1",
        user_id="user_1",
        provider_kind="composio",
    )
    params = session.executions[-1]["params"]
    vault_ref = json.loads(params["vault_ref"])
    scopes = json.loads(params["scopes"])
    serialized = json.dumps(params, sort_keys=True, default=str)

    assert params["organization_id"] == "org_1"
    assert params["user_id"] == "user_1"
    assert params["provider_kind"] == "composio"
    assert params["state"] == "connected"
    assert scopes["read"] is True
    assert scopes["write"] is True
    assert vault_ref["vault_ref_present"] is True
    assert vault_ref["secret_version"] == "v1"
    assert "oauth-token-secret" not in serialized
    assert "vault://tenant/private" not in serialized
    assert session.commits == 1


def test_connection_fetch_rehydrates_sanitized_policy_record():
    from app.engine.wiii_connect.persistent_storage import WiiiConnectPersistentStorage

    session = _FakeSession(
        row={
            "id": "conn_1",
            "provider_slug": "facebook",
            "state": "ACTIVE",
            "scopes": json.dumps({"read": True, "write": True, "apply": False}),
            "vault_ref": json.dumps(
                {"vault_ref_present": True, "secret_version": "provider_managed"}
            ),
            "account_label": "Wiii Page",
            "external_account_ref": "page_1",
            "reason": "provider_connection_list",
            "warnings": json.dumps(["safe_warning"]),
            "last_checked_at": "2026-05-28T00:00:00+00:00",
        },
    )
    storage = WiiiConnectPersistentStorage(session_factory=lambda: session)

    record = storage.get_connection_record(
        organization_id="org_1",
        user_id="user_1",
        provider_slug="facebook",
        connection_id="conn_1",
    )
    assert record is not None
    serialized = json.dumps(record.to_public_metadata(), sort_keys=True)

    assert record.connection_id == "conn_1"
    assert record.state == "connected"
    assert record.scopes.read is True
    assert record.scopes.write is True
    assert record.vault_ref is not None
    assert record.to_public_metadata()["vault_ref_present"] is True
    assert "provider-managed://" not in serialized
    assert "oauth-token" not in serialized


def test_persistent_storage_rejects_missing_owner_boundary():
    from app.engine.wiii_connect.audit_ledger import build_audit_ledger_record
    from app.engine.wiii_connect.persistent_storage import WiiiConnectPersistentStorage

    session = _FakeSession()
    storage = WiiiConnectPersistentStorage(session_factory=lambda: session)
    record = build_audit_ledger_record(
        event_kind="provider",
        provider_slug="facebook",
        status="blocked",
        reason="provider_disabled",
    )

    assert (
        storage.append_audit_record(record, organization_id="", user_id="user_1")
        is False
    )
    assert session.executions == []


def test_expire_stale_pending_connections_is_org_user_provider_scoped():
    from app.engine.wiii_connect.persistent_storage import WiiiConnectPersistentStorage

    session = _FakeSession(rowcount=2)
    storage = WiiiConnectPersistentStorage(session_factory=lambda: session)

    expired = storage.expire_stale_pending_connections(
        organization_id="org_1",
        user_id="user_1",
        provider_slug="google-drive",
        ttl_seconds=120,
    )

    assert expired == 2
    sql = session.executions[-1]["statement"]
    params = session.executions[-1]["params"]
    assert "UPDATE wiii_connect_connections" in sql
    assert "state = 'expired'" in sql
    assert "state IN ('authorizing', 'waiting', 'error')" in sql
    assert "organization_id = :organization_id" in sql
    assert "user_id = :user_id" in sql
    assert "provider_slug = :provider_slug" in sql
    assert params["organization_id"] == "org_1"
    assert params["user_id"] == "user_1"
    assert params["provider_slug"] == "google_drive"
    assert "expired_by_wiii_connect_cleanup" in params["expiry_warning"]
    assert session.commits == 1


def test_expire_stale_pending_connections_rejects_missing_owner():
    from app.engine.wiii_connect.persistent_storage import WiiiConnectPersistentStorage

    session = _FakeSession()
    storage = WiiiConnectPersistentStorage(session_factory=lambda: session)

    assert (
        storage.expire_stale_pending_connections(
            organization_id="",
            user_id="user_1",
            provider_slug="gmail",
        )
        == 0
    )
    assert session.executions == []
