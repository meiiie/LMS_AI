from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "probe_live_subagent_boundary_replay.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_subagent_boundary_replay",
    SCRIPT_PATH,
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


def _args(**overrides):
    values = {
        "allow_run": False,
        "allow_production": False,
        "request_id": "req-private-subagent-boundary",
        "session_id": "session-private-subagent-boundary",
        "organization_id": "org-private-subagent-boundary",
        "max_concurrent": 2,
        "worker_delay_seconds": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_live_subagent_probe_guard_requires_allow_run(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")
    assert probe.RAW_MARKER == "PRIVATE_SUBAGENT_BOUNDARY_RAW_MARKER"

    with pytest.raises(SystemExit, match="--allow-run"):
        probe._require_live_run(_args())


def test_live_subagent_probe_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_run(_args(allow_run=True))


def test_live_subagent_probe_guard_rejects_production_without_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_run(_args(allow_run=True))


def test_live_subagent_probe_guard_allows_production_with_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_run(_args(allow_run=True, allow_production=True))


async def test_parallel_subagent_boundary_replay_is_hash_count_only():
    summary = await probe._run_parallel_boundary_replay(_args())

    assert summary["schema"] == probe.SCHEMA_VERSION
    assert summary["status"] == "pass"
    assert summary["request"]["request_id_hash_present"] is True
    assert summary["request"]["session_id_hash_present"] is True
    assert summary["request"]["organization_id_hash_present"] is True
    assert summary["execution"]["parallel_task_count"] == 2
    assert summary["execution"]["result_count_matches_task_count"] is True
    assert summary["execution"]["parallel_execution_configured"] is True
    assert summary["runtime_ledger"]["schema_version"] == "wiii.runtime_flow_ledger.v1"
    assert summary["runtime_ledger"]["done_seen"] is True
    assert summary["runtime_ledger"]["subagent_report_count_matches_execution"] is True
    assert summary["subagents"]["report_count"] == 2
    assert summary["subagents"]["raw_content_included"] is False
    assert "state_top_level_keys_dropped" in summary["subagents"]["warning_codes"]
    assert "kwargs_top_level_keys_dropped" in summary["subagents"]["warning_codes"]
    assert "subagent_output_sanitized_or_truncated" in summary["subagents"]["warning_codes"]
    assert "subagent_thinking_dropped" in summary["subagents"]["warning_codes"]
    assert summary["subagents"]["counts"]["state_projected_key_count"] > 0
    assert summary["subagents"]["counts"]["thinking_dropped_count"] == 2
    assert summary["handoff_boundary"]["raw_content_included"] is False
    assert summary["handoff_boundary"]["state_dropped_key_count"] > 0
    assert summary["handoff_boundary"]["kwargs_dropped_key_count"] > 0
    assert summary["result_boundary"]["raw_content_included"] is False
    assert summary["result_boundary"]["output_sanitized_or_truncated"] is True
    assert summary["result_boundary"]["thinking_dropped_count"] == 2
    assert summary["result_boundary"]["evidence_image_count"] >= 1
    assert summary["doctor"]["subagents"]["report_count"] == 2
    assert summary["doctor"]["subagents"]["state_dropped_key_count"] > 0
    assert summary["privacy"]["raw_marker_absent"] is True
    assert summary["privacy"]["raw_request_identifiers_included"] is False
    assert summary["privacy"]["raw_secret_included"] is False

    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    assert probe.RAW_MARKER not in rendered
    assert probe.RAW_SECRET not in rendered
    assert "req-private-subagent-boundary" not in rendered
    assert "session-private-subagent-boundary" not in rendered
    assert "org-private-subagent-boundary" not in rendered


def test_parallel_subagent_boundary_probe_rejects_missing_hash_presence():
    summary = {
        "request": {
            "request_id_hash_present": False,
            "session_id_hash_present": True,
            "organization_id_hash_present": True,
        },
        "subagents": {
            "report_count": 2,
            "raw_content_included": False,
            "warning_codes": [
                "state_top_level_keys_dropped",
                "kwargs_top_level_keys_dropped",
                "subagent_output_sanitized_or_truncated",
                "subagent_thinking_dropped",
            ],
            "counts": {
                "source_count": 1,
                "tool_count": 1,
                "state_projected_key_count": 1,
                "state_dropped_key_count": 1,
                "thinking_dropped_count": 2,
            },
        },
        "doctor": {
            "subagents": {
                "report_count": 2,
                "raw_content_flag_count": 0,
            },
        },
        "privacy": {
            "raw_request_identifiers_included": False,
            "raw_secret_included": False,
        },
    }

    with pytest.raises(RuntimeError, match="request_id_hash_present"):
        probe._assert_probe_summary(summary)


def test_parallel_subagent_boundary_probe_rejects_raw_summary_leak():
    summary = {
        "subagents": {
            "report_count": 2,
            "raw_content_included": False,
            "warning_codes": [
                "state_top_level_keys_dropped",
                "kwargs_top_level_keys_dropped",
                "subagent_thinking_dropped",
            ],
        },
        "doctor": {"subagents": {"report_count": 2}},
        "leak": probe.RAW_MARKER,
    }

    with pytest.raises(RuntimeError, match="raw child"):
        probe._assert_probe_summary(summary)
    try:
        probe._assert_probe_summary(summary)
    except RuntimeError as exc:
        rendered = str(exc)
    assert probe.RAW_MARKER not in rendered
    assert probe.RAW_SECRET not in rendered
    assert "access_token" not in rendered
    assert "api_key" not in rendered
    assert "authorization" not in rendered


def test_failure_payload_redacts_raw_markers_secrets_and_identifiers():
    args = _args()
    payload = probe._failure_payload(
        RuntimeError(
            "failure "
            f"{probe.RAW_MARKER} {probe.RAW_SECRET} "
            "access_token api_key authorization "
            "req-private-subagent-boundary "
            "session-private-subagent-boundary "
            "org-private-subagent-boundary"
        ),
        args,
    )
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["error_code"] == "subagent_boundary_replay_failed"
    assert payload["privacy"]["failure_error_redacted"] is True
    assert payload["privacy"]["raw_marker_absent"] is True
    assert payload["privacy"]["raw_secret_included"] is False
    assert probe.RAW_MARKER not in rendered
    assert probe.RAW_SECRET not in rendered
    assert "access_token" not in rendered
    assert "api_key" not in rendered
    assert "authorization" not in rendered
    assert "req-private-subagent-boundary" not in rendered
    assert "session-private-subagent-boundary" not in rendered
    assert "org-private-subagent-boundary" not in rendered


def test_probe_main_out_writes_utf8_json(monkeypatch, tmp_path):
    monkeypatch.setenv(probe.ENV_FLAG, "1")
    out_path = tmp_path / "subagent-boundary-evidence.json"

    exit_code = probe.main(
        [
            "--allow-run",
            "--worker-delay-seconds",
            "0",
            "--out",
            str(out_path),
        ]
    )

    raw = out_path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))

    assert exit_code == 0
    assert not raw.startswith(b"\xff\xfe")
    assert payload["schema"] == probe.SCHEMA_VERSION
    assert payload["status"] == "pass"
