import importlib.util
import json
from pathlib import Path


def _load_seed_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "seed_maritime_text_kb.py"
    spec = importlib.util.spec_from_file_location("seed_maritime_text_kb", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_json_request_sets_user_agent_for_cloudflare_compat(monkeypatch):
    module = _load_seed_module()
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        return FakeResponse()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    status, payload = module._json_request("https://wiii.example/api/v1/knowledge/stats")

    assert status == 200
    assert payload == {"ok": True}
    assert captured["headers"]["User-agent"] == module.DEFAULT_USER_AGENT
