import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import report_completion_audit_readiness as readiness


def _sample_registry() -> dict:
    return {
        "registry": readiness.bundle_validator.REGISTRY_NAME,
        "version": 1,
        "requirements": [
            {
                "id": "core-runtime-replay",
                "title": "Core runtime replay",
                "layer": "Wiii Core",
                "workflow": ".github/workflows/core-runtime-evidence.yml",
                "artifact": "core-runtime-evidence.json",
                "schema_version": "wiii.core_runtime_replay.v1",
                "freshness": {"timestamp_path": "generated_at", "max_age_hours": 72},
                "payload_schema_field": "schema_version",
                "forbidden_payload_tokens": [],
                "forbidden_payload_regexes": [],
                "payload_checks": [{"path": "status", "equals": "pass"}],
                "probe": "maritime-ai-service/scripts/probe_live_core_runtime.py",
                "contract_tests": ["maritime-ai-service/tests/unit/test_core.py"],
                "live_env_flags": ["WIII_LIVE_CORE_RUNTIME"],
                "live_guard_tokens": ["--allow-run"],
                "dispatch_or_schedule_gate_tokens": ["run_core_runtime"],
                "artifact_tokens": ["core-runtime-evidence-${{ github.run_id }}"],
            },
            {
                "id": "lms-test-course-replay",
                "title": "LMS test course replay",
                "layer": "Wiii Host",
                "workflow": ".github/workflows/lms-test-course-evidence.yml",
                "artifact": "lms-test-course-evidence.json",
                "schema_version": "wiii.lms_test_course_replay.v1",
                "freshness": {"timestamp_path": "generated_at", "max_age_hours": 72},
                "payload_schema_field": "schema_version",
                "forbidden_payload_tokens": [],
                "forbidden_payload_regexes": [],
                "payload_checks": [{"path": "status", "equals": "pass"}],
                "probe": "maritime-ai-service/scripts/probe_live_lms_test_course_replay.py",
                "contract_tests": ["maritime-ai-service/tests/unit/test_lms.py"],
                "live_env_flags": ["WIII_LIVE_LMS_TEST_COURSE_REPLAY"],
                "live_guard_tokens": ["--allow-run"],
                "dispatch_or_schedule_gate_tokens": ["run_lms_test_course_replay"],
                "artifact_tokens": [
                    "lms-test-course-evidence-${{ github.run_id }}"
                ],
            },
        ],
    }


def _report_bundle_link() -> readiness.bundle_validator.ReportBundleLink:
    return readiness.bundle_validator.ReportBundleLink(
        bundle_root="artifacts/wiii-self-harness",
        bundle_fingerprint_sha256="a" * 64,
        validation_schema_version="wiii.self_harness_report_bundle_validation.v1",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_core_artifact(bundle_root: Path) -> None:
    _write_json(
        bundle_root / "core-runtime-evidence.json",
        {
            "schema_version": "wiii.core_runtime_replay.v1",
            "status": "pass",
            "generated_at": "2026-06-01T10:00:00+00:00",
        },
    )


def _provider_preflight_payload(
    *,
    generated_at: str,
    required_next: list[str],
    status: str = "fail",
) -> dict:
    return {
        "schema_version": "wiii.provider_runtime_preflight.v1",
        "generated_at": generated_at,
        "status": status,
        "requested_provider": "auto",
        "selected_provider": None,
        "tier": "premium",
        "allow_call_acknowledged": True,
        "live_env_flag_set": True,
        "include_stream_ledger": False,
        "allow_stream_write_acknowledged": False,
        "production_environment": False,
        "allow_production_acknowledged": False,
        "provider_status_counts": {
            "total": 1,
            "configured": 0,
            "request_selectable": 0,
        },
        "providers": [
            {
                "provider": "nvidia",
                "configured": False,
                "request_selectable": False,
            }
        ],
        "required_next": required_next,
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "raw_request_identifiers_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
        },
    }


def _proactive_preflight_payload(
    *,
    generated_at: str,
    required_next: list[str],
) -> dict:
    return {
        "schema_version": "wiii.proactive_channel_preflight.v1",
        "generated_at": generated_at,
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
            "enabled": False,
            "credential_present": False,
            "credential_value_included": False,
            "credential_name_included": False,
        },
        "required_next": required_next,
        "setup_contract": {
            "version": "wiii.live_evidence_setup_contract.v1",
            "requirement_id": "autonomy-proactive-channel",
            "required_next": required_next,
            "workflow_inputs_required": ["recipient_id"],
            "environment_flags_required": ["live_proactive_channel_probe"],
            "credential_slots_required": ["channel_credential"],
            "external_setup_required": ["approved_recipient"],
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


def _proactive_failure_artifact(
    *,
    generated_at: str = "2026-06-02T12:00:00+00:00",
    required_next: list[str] | None = None,
) -> dict:
    required = required_next or ["provide_recipient_id"]
    preflight = _proactive_preflight_payload(
        generated_at=generated_at,
        required_next=required,
    )
    return {
        "schema_version": "wiii.live_proactive_channel_probe.v1",
        "status": "fail",
        "generated_at": generated_at,
        "error_code": "proactive_channel_setup_blocked",
        "required_next": required,
        "setup_contract": preflight["setup_contract"],
        "preflight": preflight,
        "privacy": {
            "secret_values_included": False,
            "raw_recipient_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_message_included": False,
        },
    }


class CompletionAuditReadinessReportTests(unittest.TestCase):
    def test_scoped_readiness_can_exclude_lms_without_full_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            _write_core_artifact(bundle_root)

            report = readiness.build_readiness_report(
                registry=_sample_registry(),
                bundle_root=bundle_root,
                excluded_requirement_ids=["lms-test-course-replay"],
                as_of=readiness.bundle_validator._parse_timestamp(
                    "2026-06-01T12:00:00+00:00"
                ),
                report_bundle_link=_report_bundle_link(),
            )

        payload = report.to_dict()
        self.assertTrue(report.ok, payload)
        self.assertFalse(report.full_completion_audit_ready, payload)
        self.assertTrue(report.scoped_completion_audit_ready, payload)
        self.assertEqual(
            "a" * 64,
            report.self_harness_report_bundle_fingerprint_sha256,
        )
        self.assertEqual(
            "wiii.self_harness_report_bundle_validation.v1",
            report.self_harness_report_bundle_validation_schema_version,
        )
        self.assertEqual(["lms-test-course-replay"], report.excluded_requirement_ids)
        self.assertEqual(["lms-test-course-replay"], report.full_missing_requirement_ids)
        self.assertEqual([], report.scoped_missing_requirement_ids)
        self.assertEqual(2, report.full_requirement_count)
        self.assertEqual(1, report.scoped_requirement_count)
        self.assertIn("missing:lms-test-course-replay", report.readiness_blockers)
        self.assertEqual(["-"], report.scoped_readiness_blockers)
        self.assertEqual(0, report.scoped_next_action_count)
        self.assertRegex(
            report.scoped_next_actions_fingerprint_sha256,
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual([], report.scoped_next_actions)
        self.assertEqual([], payload["error_codes"])

    def test_scoped_readiness_stays_false_without_self_harness_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            _write_core_artifact(bundle_root)

            report = readiness.build_readiness_report(
                registry=_sample_registry(),
                bundle_root=bundle_root,
                excluded_requirement_ids=["lms-test-course-replay"],
                as_of=readiness.bundle_validator._parse_timestamp(
                    "2026-06-01T12:00:00+00:00"
                ),
            )

        self.assertFalse(report.scoped_completion_audit_ready, report.to_dict())
        self.assertIn(
            "self_harness_report_bundle_link_missing",
            report.scoped_readiness_blockers,
        )

    def test_unknown_excluded_requirement_id_fails_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            _write_core_artifact(bundle_root)

            report = readiness.build_readiness_report(
                registry=_sample_registry(),
                bundle_root=bundle_root,
                excluded_requirement_ids=["unknown-lane"],
                as_of=readiness.bundle_validator._parse_timestamp(
                    "2026-06-01T12:00:00+00:00"
                ),
                report_bundle_link=_report_bundle_link(),
            )

        payload = report.to_dict()
        self.assertFalse(report.ok)
        self.assertEqual(["unknown-lane"], report.unknown_excluded_requirement_ids)
        self.assertIn(
            "completion_audit_unknown_excluded_requirement",
            payload["error_codes"],
        )

    def test_empty_scope_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            _write_core_artifact(bundle_root)

            report = readiness.build_readiness_report(
                registry=_sample_registry(),
                bundle_root=bundle_root,
                excluded_requirement_ids=[
                    "core-runtime-replay",
                    "lms-test-course-replay",
                ],
                as_of=readiness.bundle_validator._parse_timestamp(
                    "2026-06-01T12:00:00+00:00"
                ),
                report_bundle_link=_report_bundle_link(),
            )

        self.assertFalse(report.ok)
        self.assertIn(
            "completion_audit_readiness_scope_empty",
            report.to_dict()["error_codes"],
        )

    def test_cli_can_require_scoped_ready_and_write_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir) / "bundle"
            bundle_root.mkdir()
            _write_core_artifact(bundle_root)
            out_path = Path(temp_dir) / "readiness.json"
            stdout = io.StringIO()

            with (
                mock.patch.object(readiness, "load_registry", return_value=_sample_registry()),
                mock.patch.object(readiness.bundle_validator, "require_valid_registry_contract"),
                mock.patch.object(
                    readiness.bundle_validator,
                    "require_registry_matches_report_bundle",
                    return_value=_report_bundle_link(),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = readiness.main(
                    [
                        str(bundle_root),
                        "--registry",
                        str(Path(temp_dir) / "registry.json"),
                        "--self-harness-report-bundle",
                        str(Path(temp_dir) / "reports"),
                        "--exclude-requirement-id",
                        "lms-test-course-replay",
                        "--require-scoped-ready",
                        "--format",
                        "json",
                        "--out",
                        str(out_path),
                        "--as-of",
                        "2026-06-01T12:00:00+00:00",
                    ]
                )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code, stdout.getvalue())
        self.assertFalse(payload["full_completion_audit_ready"], payload)
        self.assertTrue(payload["scoped_completion_audit_ready"], payload)
        self.assertEqual(
            "a" * 64,
            payload["self_harness_report_bundle_fingerprint_sha256"],
        )
        self.assertEqual(
            "wiii.self_harness_report_bundle_validation.v1",
            payload["self_harness_report_bundle_validation_schema_version"],
        )
        self.assertEqual("", stdout.getvalue())

    def test_cli_require_scoped_ready_returns_nonzero_when_scope_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir) / "bundle"
            bundle_root.mkdir()
            _write_core_artifact(bundle_root)
            stdout = io.StringIO()

            with (
                mock.patch.object(readiness, "load_registry", return_value=_sample_registry()),
                mock.patch.object(readiness.bundle_validator, "require_valid_registry_contract"),
                mock.patch.object(
                    readiness.bundle_validator,
                    "require_registry_matches_report_bundle",
                    return_value=_report_bundle_link(),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = readiness.main(
                    [
                        str(bundle_root),
                        "--registry",
                        str(Path(temp_dir) / "registry.json"),
                        "--self-harness-report-bundle",
                        str(Path(temp_dir) / "reports"),
                        "--require-scoped-ready",
                        "--format",
                        "json",
                        "--as-of",
                        "2026-06-01T12:00:00+00:00",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["scoped_completion_audit_ready"], payload)
        self.assertIn("lms-test-course-replay", payload["scoped_missing_requirement_ids"])
        self.assertEqual(1, payload["scoped_next_action_count"])
        self.assertRegex(
            payload["scoped_next_actions_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            ["lms-test-course-replay"],
            [action["requirement_id"] for action in payload["scoped_next_actions"]],
        )
        self.assertEqual(
            ".github/workflows/lms-test-course-evidence.yml",
            payload["scoped_next_actions"][0]["workflow"],
        )
        self.assertEqual(
            "maritime-ai-service/scripts/probe_live_lms_test_course_replay.py",
            payload["scoped_next_actions"][0]["probe"],
        )

    def test_next_actions_fingerprint_binds_readiness_schema_version(self) -> None:
        action = readiness.ReadinessNextAction(
            requirement_id="lms-test-course-replay",
            title="LMS test course replay",
            layer="Wiii Host",
            artifact="lms-test-course-evidence.json",
            schema_version="wiii.lms_test_course_replay.v1",
            status="missing",
            workflow=".github/workflows/lms-test-course-evidence.yml",
            probe="maritime-ai-service/scripts/probe_live_lms_test_course_replay.py",
            live_env_flags=["WIII_LIVE_LMS_TEST_COURSE_REPLAY"],
            live_guard_tokens=["--allow-run"],
            dispatch_or_schedule_gate_tokens=["run_lms_test_course_replay"],
            artifact_tokens=["lms-test-course-evidence-${{ github.run_id }}"],
            diagnostic_uploads=[],
            error_codes=["missing_artifact"],
            blocked_by_live_setup=False,
            preflight_status="",
            preflight_schema_version="",
            preflight_generated_at="",
            preflight_required_next=[],
            preflight_source_file="",
        )

        first_fingerprint = readiness._next_actions_fingerprint(
            [action],
            schema_version=readiness.READINESS_REPORT_SCHEMA_VERSION,
        )
        second_fingerprint = readiness._next_actions_fingerprint(
            [action],
            schema_version="wiii.completion_audit_readiness_report.v2",
        )

        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_readiness_report_attaches_preflight_summary_to_next_action(self) -> None:
        registry = _sample_registry()
        registry["requirements"][0].update(
            {
                "id": "provider-runtime-tool-loop",
                "title": "Provider runtime tool-loop evidence",
                "artifact": "provider-runtime-evidence.json",
                "schema_version": "wiii.live_provider_runtime_probe.v1",
                "workflow": ".github/workflows/provider-runtime-evidence.yml",
                "probe": "maritime-ai-service/scripts/probe_live_provider_runtime.py",
                "live_env_flags": ["WIII_LIVE_PROVIDER_RUNTIME_PROBE"],
                "live_guard_tokens": ["--allow-call"],
                "dispatch_or_schedule_gate_tokens": ["allow_live_call"],
                "artifact_tokens": [
                    "provider-runtime-evidence-${{ github.run_id }}"
                ],
                "diagnostic_uploads": [
                    {
                        "artifact": "provider-runtime-preflight.json",
                        "path": "maritime-ai-service/provider-runtime-preflight.json",
                        "artifact_tokens": [
                            "provider-runtime-preflight-${{ github.run_id }}"
                        ],
                        "if_no_files_found": "warn",
                        "retention_days": 14,
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            preflight_dir = root / "preflight"
            bundle_root.mkdir()
            _write_json(
                preflight_dir / "provider-runtime-preflight-old.json",
                _provider_preflight_payload(
                    generated_at="2026-06-02T11:00:00+00:00",
                    required_next=["old_setup_hint"],
                ),
            )
            _write_json(
                preflight_dir / "provider-runtime-preflight.json",
                _provider_preflight_payload(
                    generated_at="2026-06-02T12:00:00+00:00",
                    required_next=[
                        "configure_request_selectable_provider",
                        "raw token should not pass",
                    ],
                ),
            )

            preflights = readiness.load_preflight_summaries(preflight_dir)
            report = readiness.build_readiness_report(
                registry=registry,
                bundle_root=bundle_root,
                excluded_requirement_ids=["lms-test-course-replay"],
                as_of=readiness.bundle_validator._parse_timestamp(
                    "2026-06-02T13:00:00+00:00"
                ),
                report_bundle_link=_report_bundle_link(),
                preflight_summaries=preflights,
            )

        payload = report.to_dict()
        action = payload["scoped_next_actions"][0]
        rendered = json.dumps(payload, sort_keys=True)
        markdown = readiness.format_markdown(report)

        self.assertEqual(1, payload["preflight_summary_count"])
        self.assertEqual(1, payload["full_live_setup_blocked_count"])
        self.assertEqual(["provider-runtime-tool-loop"], payload["full_live_setup_blocked_requirement_ids"])
        self.assertEqual(1, payload["scoped_live_setup_blocked_count"])
        self.assertEqual(["provider-runtime-tool-loop"], payload["scoped_live_setup_blocked_requirement_ids"])
        summary = payload["preflight_summaries"][0]
        self.assertEqual("provider-runtime-tool-loop", action["requirement_id"])
        self.assertTrue(action["blocked_by_live_setup"])
        self.assertEqual("fail", action["preflight_status"])
        self.assertEqual(
            "wiii.provider_runtime_preflight.v1",
            action["preflight_schema_version"],
        )
        self.assertEqual(
            ["configure_request_selectable_provider", "raw_token_should_not_pass"],
            action["preflight_required_next"],
        )
        self.assertEqual(
            ["provider-runtime-preflight-${{ github.run_id }}"],
            action["diagnostic_uploads"][0]["artifact_tokens"],
        )
        self.assertRegex(summary["source_file_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            "wiii.runtime_evidence_preflight_validation.v1",
            summary["source_validation_schema_version"],
        )
        self.assertTrue(summary["source_validation_ok"])
        self.assertEqual([], summary["source_validation_error_codes"])
        self.assertIn("## Preflight Summaries", markdown)
        self.assertIn("configure_request_selectable_provider", markdown)
        self.assertNotIn("old_setup_hint", rendered)
        self.assertNotIn("secret_values_included", rendered)

    def test_readiness_report_rejects_invalid_raw_preflight_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            preflight_dir = Path(temp_dir) / "preflight"
            payload = _provider_preflight_payload(
                generated_at="2026-06-02T12:00:00+00:00",
                required_next=["configure_request_selectable_provider"],
            )
            payload["privacy"]["secret_values_included"] = True
            _write_json(preflight_dir / "provider-runtime-preflight.json", payload)

            with self.assertRaises(ValueError) as exc:
                readiness.load_preflight_summaries(preflight_dir)

        self.assertIn("preflight JSON failed validation", str(exc.exception))
        self.assertIn("privacy.secret_values_included", str(exc.exception))

    def test_readiness_report_uses_valid_embedded_failed_artifact_preflight(
        self,
    ) -> None:
        registry = _sample_registry()
        registry["requirements"][0].update(
            {
                "id": "autonomy-proactive-channel",
                "title": "Proactive channel evidence",
                "artifact": "autonomy-proactive-channel-evidence.json",
                "schema_version": "wiii.live_proactive_channel_probe.v1",
                "workflow": ".github/workflows/autonomy-runtime-evidence.yml",
                "probe": "maritime-ai-service/scripts/probe_live_proactive_channel.py",
                "live_env_flags": ["WIII_LIVE_PROACTIVE_CHANNEL_PROBE"],
                "live_guard_tokens": ["--allow-send"],
                "dispatch_or_schedule_gate_tokens": ["allow_live_send"],
                "artifact_tokens": [
                    "autonomy-proactive-channel-evidence-${{ github.run_id }}"
                ],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            _write_json(
                bundle_root / "autonomy-proactive-channel-evidence.json",
                _proactive_failure_artifact(
                    required_next=["provide_recipient_id", "enable_channel"]
                ),
            )

            preflights = readiness.load_embedded_preflight_summaries(
                bundle_root,
                registry,
            )
            report = readiness.build_readiness_report(
                registry=registry,
                bundle_root=bundle_root,
                excluded_requirement_ids=["lms-test-course-replay"],
                as_of=readiness.bundle_validator._parse_timestamp(
                    "2026-06-02T13:00:00+00:00"
                ),
                report_bundle_link=_report_bundle_link(),
                preflight_summaries=preflights,
            )

        payload = report.to_dict()
        action = payload["scoped_next_actions"][0]
        summary = payload["preflight_summaries"][0]

        self.assertEqual(1, payload["preflight_summary_count"])
        self.assertEqual("autonomy-proactive-channel", summary["requirement_id"])
        self.assertEqual(
            "autonomy-proactive-channel-evidence.json#preflight",
            summary["source_file"],
        )
        self.assertRegex(summary["source_file_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(summary["source_validation_ok"])
        self.assertEqual([], summary["source_validation_error_codes"])
        self.assertTrue(action["blocked_by_live_setup"])
        self.assertEqual(
            ["provide_recipient_id", "enable_channel"],
            action["preflight_required_next"],
        )

    def test_readiness_report_skips_invalid_embedded_preflight(self) -> None:
        registry = _sample_registry()
        registry["requirements"][0].update(
            {
                "id": "autonomy-proactive-channel",
                "artifact": "autonomy-proactive-channel-evidence.json",
                "schema_version": "wiii.live_proactive_channel_probe.v1",
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            artifact = _proactive_failure_artifact()
            artifact["preflight"]["privacy"]["secret_values_included"] = True
            _write_json(
                bundle_root / "autonomy-proactive-channel-evidence.json",
                artifact,
            )

            preflights = readiness.load_embedded_preflight_summaries(
                bundle_root,
                registry,
            )

        self.assertEqual({}, preflights)

    def test_cli_reads_preflight_dir_into_json_output(self) -> None:
        registry = _sample_registry()
        registry["requirements"][0].update(
            {
                "id": "provider-runtime-tool-loop",
                "artifact": "provider-runtime-evidence.json",
                "schema_version": "wiii.live_provider_runtime_probe.v1",
                "workflow": ".github/workflows/provider-runtime-evidence.yml",
                "probe": "maritime-ai-service/scripts/probe_live_provider_runtime.py",
                "live_env_flags": ["WIII_LIVE_PROVIDER_RUNTIME_PROBE"],
                "live_guard_tokens": ["--allow-call"],
                "dispatch_or_schedule_gate_tokens": ["allow_live_call"],
                "artifact_tokens": [
                    "provider-runtime-evidence-${{ github.run_id }}"
                ],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            preflight_dir = root / "preflight"
            bundle_root.mkdir()
            _write_json(
                preflight_dir / "provider-runtime-preflight.json",
                _provider_preflight_payload(
                    generated_at="2026-06-02T12:00:00+00:00",
                    required_next=["configure_request_selectable_provider"],
                ),
            )
            stdout = io.StringIO()

            with (
                mock.patch.object(readiness, "load_registry", return_value=registry),
                mock.patch.object(readiness.bundle_validator, "require_valid_registry_contract"),
                mock.patch.object(
                    readiness.bundle_validator,
                    "require_registry_matches_report_bundle",
                    return_value=_report_bundle_link(),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = readiness.main(
                    [
                        str(bundle_root),
                        "--registry",
                        str(root / "registry.json"),
                        "--self-harness-report-bundle",
                        str(root / "reports"),
                        "--exclude-requirement-id",
                        "lms-test-course-replay",
                        "--preflight-dir",
                        str(preflight_dir),
                        "--format",
                        "json",
                        "--as-of",
                        "2026-06-02T13:00:00+00:00",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertEqual(1, payload["preflight_summary_count"])
        self.assertTrue(payload["preflight_summaries"][0]["source_validation_ok"])
        self.assertEqual(
            ["configure_request_selectable_provider"],
            payload["scoped_next_actions"][0]["preflight_required_next"],
        )

    def test_cli_reads_embedded_preflight_when_preflight_dir_is_absent(self) -> None:
        registry = _sample_registry()
        registry["requirements"][0].update(
            {
                "id": "autonomy-proactive-channel",
                "title": "Proactive channel evidence",
                "artifact": "autonomy-proactive-channel-evidence.json",
                "schema_version": "wiii.live_proactive_channel_probe.v1",
                "workflow": ".github/workflows/autonomy-runtime-evidence.yml",
                "probe": "maritime-ai-service/scripts/probe_live_proactive_channel.py",
                "live_env_flags": ["WIII_LIVE_PROACTIVE_CHANNEL_PROBE"],
                "live_guard_tokens": ["--allow-send"],
                "dispatch_or_schedule_gate_tokens": ["allow_live_send"],
                "artifact_tokens": [
                    "autonomy-proactive-channel-evidence-${{ github.run_id }}"
                ],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            _write_json(
                bundle_root / "autonomy-proactive-channel-evidence.json",
                _proactive_failure_artifact(required_next=["provide_recipient_id"]),
            )
            stdout = io.StringIO()

            with (
                mock.patch.object(readiness, "load_registry", return_value=registry),
                mock.patch.object(
                    readiness.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    readiness.bundle_validator,
                    "require_registry_matches_report_bundle",
                    return_value=_report_bundle_link(),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = readiness.main(
                    [
                        str(bundle_root),
                        "--registry",
                        str(root / "registry.json"),
                        "--self-harness-report-bundle",
                        str(root / "reports"),
                        "--exclude-requirement-id",
                        "lms-test-course-replay",
                        "--format",
                        "json",
                        "--as-of",
                        "2026-06-02T13:00:00+00:00",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertEqual(1, payload["preflight_summary_count"])
        self.assertEqual(
            "autonomy-proactive-channel-evidence.json#preflight",
            payload["preflight_summaries"][0]["source_file"],
        )
        self.assertEqual(
            ["provide_recipient_id"],
            payload["scoped_next_actions"][0]["preflight_required_next"],
        )


if __name__ == "__main__":
    unittest.main()
