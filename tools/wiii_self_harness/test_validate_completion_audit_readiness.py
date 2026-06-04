import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from report_completion_audit_readiness import READINESS_REPORT_SCHEMA_VERSION
import validate_completion_audit_readiness as validator
from validate_self_harness_report_bundle import REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_markdown(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        validator.format_markdown(validator._report_from_payload(payload)).rstrip("\n")
        + "\n",
        encoding="utf-8",
    )


def _report_bundle_result(
    *,
    ok: bool = True,
    fingerprint: str = "4" * 64,
    schema: str = REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
    error_codes: list[str] | None = None,
):
    return mock.Mock(
        ok=ok,
        bundle_fingerprint_sha256=fingerprint,
        validation_schema_version=schema,
        to_dict=mock.Mock(return_value={"error_codes": error_codes or []}),
    )


def _empty_action_preflight_fields() -> dict:
    return {
        "preflight_status": "",
        "preflight_schema_version": "",
        "preflight_generated_at": "",
        "preflight_required_next": [],
        "preflight_source_file": "",
    }


def _proactive_preflight_summary() -> dict:
    required_next = ["provide_recipient_id"]
    return {
        "requirement_id": "autonomy-proactive-channel",
        "schema_version": "wiii.proactive_channel_preflight.v1",
        "status": "fail",
        "generated_at": "2026-06-02T12:00:00+00:00",
        "required_next": required_next,
        "source_file": "proactive-channel-preflight.json",
        "source_file_sha256": "5" * 64,
        "source_validation_schema_version": (
            "wiii.runtime_evidence_preflight_validation.v1"
        ),
        "source_validation_ok": True,
        "source_validation_error_codes": [],
        "raw_payload_included": False,
        "setup_contract": {
            "version": "wiii.live_evidence_setup_contract.v1",
            "requirement_id": "autonomy-proactive-channel",
            "required_next": required_next,
            "workflow_inputs_required": [
                "channel",
                "recipient_id",
                "allow_send",
                "allow_production",
            ],
            "environment_flags_required": ["live_proactive_channel_probe_flag"],
            "credential_slots_required": ["selected_channel_credential"],
            "external_setup_required": [
                "approved_recipient",
                "selected_channel_enabled",
            ],
            "dispatch_ready": False,
        },
    }


def _proactive_preflight_source() -> dict:
    return {
        "schema_version": "wiii.proactive_channel_preflight.v1",
        "generated_at": "2026-06-02T12:00:00+00:00",
        "status": "fail",
        "requested_channel": "telegram",
        "allow_send_acknowledged": True,
        "live_env_flag_set": True,
        "recipient_id_present": False,
        "production_environment": False,
        "allow_production_acknowledged": False,
        "live_send_attempted": False,
        "channel_config": {
            "supported": True,
            "enabled": True,
            "credential_present": True,
            "credential_value_included": False,
            "credential_name_included": False,
        },
        "required_next": ["provide_recipient_id"],
        "setup_contract": {
            "version": "wiii.live_evidence_setup_contract.v1",
            "requirement_id": "autonomy-proactive-channel",
            "required_next": ["provide_recipient_id"],
            "workflow_inputs_required": [
                "channel",
                "recipient_id",
                "allow_send",
                "allow_production",
            ],
            "environment_flags_required": ["live_proactive_channel_probe_flag"],
            "credential_slots_required": ["selected_channel_credential"],
            "external_setup_required": [
                "approved_recipient",
                "selected_channel_enabled",
            ],
            "dispatch_ready": False,
        },
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "raw_recipient_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_message_included": False,
            "raw_delivery_payload_included": False,
            "raw_channel_credentials_included": False,
        },
    }


def _write_matching_proactive_preflight(preflight_dir: Path) -> None:
    source_path = preflight_dir / "proactive-channel-preflight.json"
    _write_json(source_path, _proactive_preflight_source())


def _write_matching_embedded_proactive_preflight(preflight_dir: Path) -> Path:
    source_path = preflight_dir / "autonomy-proactive-channel-evidence.json"
    _write_json(source_path, {"preflight": _proactive_preflight_source()})
    return source_path


def _source_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_payload() -> dict:
    return {
        "schema_version": READINESS_REPORT_SCHEMA_VERSION,
        "registry_name": "Wiii Runtime Evidence Registry",
        "registry_version": 1,
        "registry_fingerprint_sha256": "1" * 64,
        "bundle_root": "artifacts/runtime-evidence-empty",
        "bundle_fingerprint_sha256": "2" * 64,
        "completion_audit_fingerprint_sha256": "3" * 64,
        "self_harness_report_bundle_root": "artifacts/wiii-self-harness",
        "self_harness_report_bundle_fingerprint_sha256": "4" * 64,
        "self_harness_report_bundle_validation_schema_version": (
            REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION
        ),
        "full_completion_audit_ready": False,
        "scoped_completion_audit_ready": True,
        "full_requirement_count": 2,
        "full_passed_count": 1,
        "full_missing_count": 1,
        "full_failed_count": 0,
        "scoped_requirement_count": 1,
        "scoped_passed_count": 1,
        "scoped_missing_count": 0,
        "scoped_failed_count": 0,
        "excluded_requirement_ids": ["lms-test-course-replay"],
        "unknown_excluded_requirement_ids": [],
        "full_missing_requirement_ids": ["lms-test-course-replay"],
        "full_failed_requirement_ids": [],
        "scoped_missing_requirement_ids": [],
        "scoped_failed_requirement_ids": [],
        "full_live_setup_blocked_count": 0,
        "full_live_setup_blocked_requirement_ids": [],
        "scoped_live_setup_blocked_count": 0,
        "scoped_live_setup_blocked_requirement_ids": [],
        "readiness_blockers": ["missing:lms-test-course-replay"],
        "scoped_readiness_blockers": ["-"],
        "scoped_next_action_count": 0,
        "scoped_next_actions_fingerprint_sha256": validator._next_actions_fingerprint(
            []
        ),
        "scoped_next_actions": [],
        "preflight_summary_count": 0,
        "preflight_summaries": [],
        "rows": [
            {
                "requirement_id": "core-runtime-replay",
                "artifact": "core-runtime-evidence.json",
                "status": "passed",
                "included_in_scope": True,
                "error_codes": [],
            },
            {
                "requirement_id": "lms-test-course-replay",
                "artifact": "lms-test-course-evidence.json",
                "status": "missing",
                "included_in_scope": False,
                "error_codes": ["missing_artifact"],
            },
        ],
        "errors": [],
        "ok": True,
        "error_codes": [],
        "error_code_counts": {},
    }


def _payload_with_unknown_exclusion() -> dict:
    payload = _valid_payload()
    error = "unknown excluded completion audit requirement id(s): unknown-lane"
    payload["excluded_requirement_ids"] = ["unknown-lane"]
    payload["unknown_excluded_requirement_ids"] = ["unknown-lane"]
    payload["rows"][0]["included_in_scope"] = True
    payload["rows"][1]["included_in_scope"] = True
    payload["scoped_completion_audit_ready"] = False
    payload["scoped_requirement_count"] = 2
    payload["scoped_passed_count"] = 1
    payload["scoped_missing_count"] = 1
    payload["scoped_missing_requirement_ids"] = ["lms-test-course-replay"]
    payload["scoped_readiness_blockers"] = ["missing:lms-test-course-replay"]
    payload["scoped_next_actions"] = [
        {
            "requirement_id": "lms-test-course-replay",
            "title": "LMS test course replay",
            "layer": "Wiii Host",
            "artifact": "lms-test-course-evidence.json",
            "schema_version": "wiii.lms_test_course_replay.v1",
            "status": "missing",
            "workflow": ".github/workflows/lms-test-course-evidence.yml",
            "probe": "maritime-ai-service/scripts/probe_live_lms_test_course_replay.py",
            "live_env_flags": ["WIII_LIVE_LMS_TEST_COURSE_REPLAY"],
            "live_guard_tokens": ["--allow-run"],
            "dispatch_or_schedule_gate_tokens": ["run_lms_test_course_replay"],
            "artifact_tokens": ["lms-test-course-evidence-${{ github.run_id }}"],
            "error_codes": ["missing_artifact"],
            "blocked_by_live_setup": False,
            **_empty_action_preflight_fields(),
        }
    ]
    payload["scoped_next_action_count"] = len(payload["scoped_next_actions"])
    payload["scoped_next_actions_fingerprint_sha256"] = (
        validator._next_actions_fingerprint(payload["scoped_next_actions"])
    )
    payload["errors"] = [error]
    payload["ok"] = False
    payload["error_codes"] = [
        "completion_audit_unknown_excluded_requirement",
    ]
    payload["error_code_counts"] = {
        "completion_audit_unknown_excluded_requirement": 1,
    }
    return payload


def _payload_with_preflight_next_action() -> dict:
    payload = _valid_payload()
    summary = _proactive_preflight_summary()
    payload["excluded_requirement_ids"] = []
    payload["full_completion_audit_ready"] = False
    payload["scoped_completion_audit_ready"] = False
    payload["full_passed_count"] = 1
    payload["full_missing_count"] = 1
    payload["scoped_requirement_count"] = 2
    payload["scoped_passed_count"] = 1
    payload["scoped_missing_count"] = 1
    payload["full_missing_requirement_ids"] = ["autonomy-proactive-channel"]
    payload["scoped_missing_requirement_ids"] = ["autonomy-proactive-channel"]
    payload["full_live_setup_blocked_count"] = 1
    payload["full_live_setup_blocked_requirement_ids"] = [
        "autonomy-proactive-channel"
    ]
    payload["scoped_live_setup_blocked_count"] = 1
    payload["scoped_live_setup_blocked_requirement_ids"] = [
        "autonomy-proactive-channel"
    ]
    payload["readiness_blockers"] = ["missing:autonomy-proactive-channel"]
    payload["scoped_readiness_blockers"] = ["missing:autonomy-proactive-channel"]
    payload["rows"][1] = {
        "requirement_id": "autonomy-proactive-channel",
        "artifact": "autonomy-proactive-channel-evidence.json",
        "status": "missing",
        "included_in_scope": True,
        "error_codes": ["missing_artifact"],
    }
    payload["scoped_next_actions"] = [
        {
            "requirement_id": "autonomy-proactive-channel",
            "title": "Proactive channel evidence",
            "layer": "Wiii Autonomy",
            "artifact": "autonomy-proactive-channel-evidence.json",
            "schema_version": "wiii.live_proactive_channel_probe.v1",
            "status": "missing",
            "workflow": ".github/workflows/autonomy-runtime-evidence.yml",
            "probe": "maritime-ai-service/scripts/probe_live_proactive_channel.py",
            "live_env_flags": ["WIII_LIVE_PROACTIVE_CHANNEL_PROBE"],
            "live_guard_tokens": ["--allow-send"],
            "dispatch_or_schedule_gate_tokens": ["run_proactive_channel"],
            "artifact_tokens": ["autonomy-proactive-channel-${{ github.run_id }}"],
            "error_codes": ["missing_artifact"],
            "blocked_by_live_setup": True,
            "preflight_status": summary["status"],
            "preflight_schema_version": summary["schema_version"],
            "preflight_generated_at": summary["generated_at"],
            "preflight_required_next": summary["required_next"],
            "preflight_source_file": summary["source_file"],
        }
    ]
    payload["scoped_next_action_count"] = len(payload["scoped_next_actions"])
    payload["scoped_next_actions_fingerprint_sha256"] = (
        validator._next_actions_fingerprint(payload["scoped_next_actions"])
    )
    payload["preflight_summary_count"] = 1
    payload["preflight_summaries"] = [summary]
    return payload


class ValidateCompletionAuditReadinessTests(unittest.TestCase):
    def test_valid_non_lms_scoped_ready_report_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, _valid_payload())

            result = validator.validate_readiness_report(report_path)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.errors)
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_scoped_counts_must_match_rows(self) -> None:
        payload = _valid_payload()
        payload["scoped_missing_count"] = 1
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_consistency_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_row_scope_flag_must_match_excluded_requirements(self) -> None:
        payload = _valid_payload()
        payload["rows"][1]["included_in_scope"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertTrue(
            any("included_in_scope" in error for error in result.errors),
            result.to_dict(),
        )

    def test_full_readiness_must_match_missing_rows(self) -> None:
        payload = _valid_payload()
        payload["full_completion_audit_ready"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_consistency_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_scoped_next_actions_must_match_scoped_blockers(self) -> None:
        payload = _payload_with_unknown_exclusion()
        payload["scoped_next_actions"] = []
        payload["scoped_next_action_count"] = 0
        payload["scoped_next_actions_fingerprint_sha256"] = (
            validator._next_actions_fingerprint([])
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_next_actions_invalid",
            result.to_dict()["error_codes"],
        )

    def test_scoped_next_actions_fingerprint_must_match_actions(self) -> None:
        payload = _payload_with_unknown_exclusion()
        payload["scoped_next_actions_fingerprint_sha256"] = "f" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_next_actions_invalid",
            result.to_dict()["error_codes"],
        )

    def test_next_actions_fingerprint_binds_readiness_schema_version(self) -> None:
        actions = _payload_with_unknown_exclusion()["scoped_next_actions"]

        first_fingerprint = validator._next_actions_fingerprint(
            actions,
            schema_version=READINESS_REPORT_SCHEMA_VERSION,
        )
        second_fingerprint = validator._next_actions_fingerprint(
            actions,
            schema_version="wiii.completion_audit_readiness_report.v2",
        )

        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_preflight_summary_can_support_next_action_diagnostics(self) -> None:
        payload = _payload_with_preflight_next_action()
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertTrue(result.ok, result.to_dict())
        summary = payload["preflight_summaries"][0]
        self.assertEqual(
            "wiii.live_evidence_setup_contract.v1",
            summary["setup_contract"]["version"],
        )
        self.assertEqual(
            ["selected_channel_credential"],
            summary["setup_contract"]["credential_slots_required"],
        )

    def test_preflight_summary_count_must_match_summaries(self) -> None:
        payload = _payload_with_preflight_next_action()
        payload["preflight_summary_count"] = 2
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_preflight_invalid",
            result.to_dict()["error_codes"],
        )

    def test_preflight_summary_requires_valid_source_attestation(self) -> None:
        payload = _payload_with_preflight_next_action()
        payload["preflight_summaries"][0]["source_validation_ok"] = False
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_preflight_invalid",
            result.to_dict()["error_codes"],
        )

    def test_preflight_dir_validates_source_hash_and_payload(self) -> None:
        payload = _payload_with_preflight_next_action()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preflight_dir = root / "preflight"
            _write_matching_proactive_preflight(preflight_dir)
            source_path = preflight_dir / "proactive-channel-preflight.json"
            payload["preflight_summaries"][0]["source_file_sha256"] = _source_sha(
                source_path
            )
            report_path = root / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(
                report_path,
                preflight_dir=preflight_dir,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_preflight_dirs_validate_source_from_later_directory(self) -> None:
        payload = _payload_with_preflight_next_action()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            empty_dir = root / "empty"
            empty_dir.mkdir()
            preflight_dir = root / "preflight"
            _write_matching_proactive_preflight(preflight_dir)
            source_path = preflight_dir / "proactive-channel-preflight.json"
            payload["preflight_summaries"][0]["source_file_sha256"] = _source_sha(
                source_path
            )
            report_path = root / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(
                report_path,
                preflight_dirs=[empty_dir, preflight_dir],
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_preflight_dir_allows_embedded_preflight_source(self) -> None:
        payload = _payload_with_preflight_next_action()
        payload["preflight_summaries"][0]["source_file"] = (
            "autonomy-proactive-channel-evidence.json#preflight"
        )
        payload["scoped_next_actions"][0]["preflight_source_file"] = (
            "autonomy-proactive-channel-evidence.json#preflight"
        )
        payload["scoped_next_actions_fingerprint_sha256"] = (
            validator._next_actions_fingerprint(payload["scoped_next_actions"])
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preflight_dir = root / "preflight"
            source_path = _write_matching_embedded_proactive_preflight(preflight_dir)
            payload["preflight_summaries"][0]["source_file_sha256"] = _source_sha(
                source_path
            )
            report_path = root / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(
                report_path,
                preflight_dir=preflight_dir,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_preflight_dir_rejects_source_hash_mismatch(self) -> None:
        payload = _payload_with_preflight_next_action()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preflight_dir = root / "preflight"
            _write_matching_proactive_preflight(preflight_dir)
            payload["preflight_summaries"][0]["source_file_sha256"] = "6" * 64
            report_path = root / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(
                report_path,
                preflight_dir=preflight_dir,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_preflight_invalid",
            result.to_dict()["error_codes"],
        )
        self.assertTrue(
            any(
                "source_file_sha256 must match source file" in error
                for error in result.errors
            ),
            result.to_dict(),
        )

    def test_preflight_summary_setup_contract_must_match_source(self) -> None:
        payload = _payload_with_preflight_next_action()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preflight_dir = root / "preflight"
            _write_matching_proactive_preflight(preflight_dir)
            source_path = preflight_dir / "proactive-channel-preflight.json"
            payload["preflight_summaries"][0]["source_file_sha256"] = _source_sha(
                source_path
            )
            payload["preflight_summaries"][0]["setup_contract"][
                "credential_slots_required"
            ] = ["different_credential_slot"]
            report_path = root / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(
                report_path,
                preflight_dir=preflight_dir,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_preflight_invalid",
            result.to_dict()["error_codes"],
        )
        self.assertTrue(
            any("setup_contract must match source" in error for error in result.errors),
            result.to_dict(),
        )

    def test_next_action_preflight_fields_must_match_summary(self) -> None:
        payload = _payload_with_preflight_next_action()
        payload["scoped_next_actions"][0]["preflight_required_next"] = [
            "different_hint"
        ]
        payload["scoped_next_actions_fingerprint_sha256"] = (
            validator._next_actions_fingerprint(payload["scoped_next_actions"])
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_next_actions_invalid",
            result.to_dict()["error_codes"],
        )

    def test_next_action_live_setup_block_must_match_summary(self) -> None:
        payload = _payload_with_preflight_next_action()
        payload["scoped_next_actions"][0]["blocked_by_live_setup"] = False
        payload["scoped_next_actions_fingerprint_sha256"] = (
            validator._next_actions_fingerprint(payload["scoped_next_actions"])
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_next_actions_invalid",
            result.to_dict()["error_codes"],
        )

    def test_unknown_excluded_requirement_error_provenance_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, _payload_with_unknown_exclusion())

            result = validator.validate_readiness_report(report_path)

        self.assertTrue(result.ok, result.to_dict())

    def test_unknown_excluded_requirement_requires_matching_errors(self) -> None:
        payload = _payload_with_unknown_exclusion()
        payload["errors"] = []
        payload["ok"] = True
        payload["error_codes"] = []
        payload["error_code_counts"] = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            _write_json(report_path, payload)

            result = validator.validate_readiness_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_consistency_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_outputs_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "readiness.json"
            markdown_path = Path(temp_dir) / "readiness.md"
            bundle_path = Path(temp_dir) / "self-harness"
            payload_data = _valid_payload()
            _write_json(report_path, payload_data)
            _write_markdown(markdown_path, payload_data)
            stdout = io.StringIO()

            with (
                mock.patch.object(
                    validator,
                    "validate_report_bundle",
                    return_value=_report_bundle_result(),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = validator.main(
                    [
                        str(report_path),
                        "--markdown-report",
                        str(markdown_path),
                        "--self-harness-report-bundle",
                        str(bundle_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertEqual([], payload["error_codes"])
        self.assertEqual(str(markdown_path), payload["markdown_report_path"])
        self.assertEqual(
            str(bundle_path),
            payload["self_harness_report_bundle_path"],
        )

    def test_self_harness_report_bundle_source_must_match_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "readiness.json"
            bundle_path = root / "self-harness"
            _write_json(report_path, _valid_payload())

            with mock.patch.object(
                validator,
                "validate_report_bundle",
                return_value=_report_bundle_result(),
            ):
                result = validator.validate_readiness_report(
                    report_path,
                    self_harness_report_bundle_path=bundle_path,
                )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_self_harness_report_bundle_source_rejects_stale_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "readiness.json"
            bundle_path = root / "self-harness"
            _write_json(report_path, _valid_payload())

            with mock.patch.object(
                validator,
                "validate_report_bundle",
                return_value=_report_bundle_result(fingerprint="9" * 64),
            ):
                result = validator.validate_readiness_report(
                    report_path,
                    self_harness_report_bundle_path=bundle_path,
                )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_self_harness_bundle_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_self_harness_report_bundle_source_must_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "readiness.json"
            bundle_path = root / "self-harness"
            _write_json(report_path, _valid_payload())

            with mock.patch.object(
                validator,
                "validate_report_bundle",
                return_value=_report_bundle_result(
                    ok=False,
                    error_codes=["report_bundle_fingerprint_mismatch"],
                ),
            ):
                result = validator.validate_readiness_report(
                    report_path,
                    self_harness_report_bundle_path=bundle_path,
                )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_self_harness_bundle_invalid",
            result.to_dict()["error_codes"],
        )

    def test_markdown_report_must_match_readiness_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "readiness.json"
            markdown_path = root / "readiness.md"
            payload = _valid_payload()
            _write_json(report_path, payload)
            _write_markdown(markdown_path, payload)

            result = validator.validate_readiness_report(
                report_path,
                markdown_report_path=markdown_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_markdown_report_rejects_stale_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "readiness.json"
            markdown_path = root / "readiness.md"
            payload = _valid_payload()
            _write_json(report_path, payload)
            _write_markdown(markdown_path, payload)
            markdown_path.write_text(
                markdown_path.read_text(encoding="utf-8").replace(
                    "Scoped completion audit ready",
                    "Stale scoped completion audit ready",
                    1,
                ),
                encoding="utf-8",
            )

            result = validator.validate_readiness_report(
                report_path,
                markdown_report_path=markdown_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_readiness_markdown_invalid",
            result.to_dict()["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
