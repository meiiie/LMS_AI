# -*- coding: utf-8 -*-
"""Sprint 194c - B6 HIGH: OrgContextMiddleware fail-closed on DB error."""
import asyncio

import httpx
import pytest
from unittest.mock import MagicMock, patch

_SP = "app.core.config.settings"
_RP = "app.repositories.organization_repository.get_organization_repository"


def _get(app, path="/test", headers=None, raise_server_exceptions=True):
    async def _request():
        transport = httpx.ASGITransport(
            app=app,
            raise_app_exceptions=raise_server_exceptions,
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path, headers=headers)

    return asyncio.run(_request())

def _app(captured_org, captured_domains=None):
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from app.core.middleware import OrgContextMiddleware
    async def endpoint(request: Request) -> Response:
        from app.core.org_context import current_org_id, current_org_allowed_domains
        captured_org.append(current_org_id.get())
        if captured_domains is not None:
            captured_domains.append(current_org_allowed_domains.get())
        return Response("ok")
    app = Starlette()
    app.add_route("/test", endpoint)
    app.add_middleware(OrgContextMiddleware)
    return app

class TestFailClosed:
    """DB error during org lookup → 503 response (request never reaches handler)."""

    def test_db_error_returns_503(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        repo = MagicMock(); repo.get_organization.side_effect = RuntimeError("refused")
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                resp = _get(
                    _app(captured),
                    headers={"X-Organization-ID": "org-boom"},
                    raise_server_exceptions=False,
                )
        assert resp.status_code == 503
        assert len(captured) == 0  # Handler never reached

    def test_timeout_returns_503(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        repo = MagicMock(); repo.get_organization.side_effect = TimeoutError("slow")
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                resp = _get(
                    _app(captured),
                    headers={"X-Organization-ID": "org-slow"},
                    raise_server_exceptions=False,
                )
        assert resp.status_code == 503
        assert len(captured) == 0

    def test_import_error_returns_503(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        with patch(_SP, ms):
            with patch(_RP, side_effect=ImportError("missing")):
                resp = _get(
                    _app(captured),
                    headers={"X-Organization-ID": "org-imp"},
                    raise_server_exceptions=False,
                )
        assert resp.status_code == 503
        assert len(captured) == 0

    def test_db_error_handler_not_reached(self):
        co = []; cd = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        repo = MagicMock(); repo.get_organization.side_effect = Exception("err")
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                resp = _get(
                    _app(co, cd),
                    headers={"X-Organization-ID": "org-x"},
                    raise_server_exceptions=False,
                )
        assert resp.status_code == 503
        assert len(co) == 0 and len(cd) == 0

class TestSuccess:
    def test_sets_org_id(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        org = MagicMock(); org.allowed_domains = ["maritime"]
        repo = MagicMock(); repo.get_organization.return_value = org
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                _get(_app(captured), headers={"X-Organization-ID": "org-good"})
        assert captured[0] == "org-good"

    def test_sets_allowed_domains(self):
        co = []; cd = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        org = MagicMock(); org.allowed_domains = ["maritime", "traffic_law"]
        repo = MagicMock(); repo.get_organization.return_value = org
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                _get(_app(co, cd), headers={"X-Organization-ID": "org-multi"})
        assert cd[0] == ["maritime", "traffic_law"]

    def test_org_not_found(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        repo = MagicMock(); repo.get_organization.return_value = None
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                _get(_app(captured), headers={"X-Organization-ID": "org-unknown"})
        assert captured[0] == "org-unknown"

class TestNoHeader:
    def test_no_org_header(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        with patch(_SP, ms):
            _get(_app(captured))
        assert captured[0] is None

class TestDisabled:
    def test_disabled_no_db(self):
        captured = []; calls = []
        ms = MagicMock(); ms.enable_multi_tenant = False
        with patch(_SP, ms):
            with patch(_RP) as mr:
                mr.side_effect = lambda: calls.append(1) or MagicMock()
                _get(_app(captured), headers={"X-Organization-ID": "org-x"})
        assert len(calls) == 0

class TestCleanup:
    def test_org_reset_after_request(self):
        from app.core.org_context import current_org_id
        assert current_org_id.get() is None
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = ""
        org = MagicMock(); org.allowed_domains = ["maritime"]
        repo = MagicMock(); repo.get_organization.return_value = org
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                _get(_app(captured), headers={"X-Organization-ID": "org-cleanup"})
        assert captured[0] == "org-cleanup"
        assert current_org_id.get() is None

class TestSubdomain:
    def test_subdomain_extraction(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = "holilihu.online"
        org = MagicMock(); org.allowed_domains = ["maritime"]
        repo = MagicMock(); repo.get_organization.return_value = org
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                _get(_app(captured), headers={"Host": "my-org.holilihu.online"})
        assert captured[0] == "my-org"

    def test_header_priority(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = "holilihu.online"
        org = MagicMock(); org.allowed_domains = ["maritime"]
        repo = MagicMock(); repo.get_organization.return_value = org
        with patch(_SP, ms):
            with patch(_RP, return_value=repo):
                _get(
                    _app(captured),
                    headers={
                        "X-Organization-ID": "header-org",
                        "Host": "sub.holilihu.online",
                    },
                )
        assert captured[0] == "header-org"

    def test_wiii_app_subdomain_is_reserved(self):
        captured = []
        ms = MagicMock(); ms.enable_multi_tenant = True; ms.subdomain_base_domain = "holilihu.online"
        with patch(_SP, ms):
            with patch(_RP) as repo_fn:
                _get(_app(captured), headers={"Host": "wiii.holilihu.online"})
        assert captured[0] is None
        repo_fn.assert_not_called()
