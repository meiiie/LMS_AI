import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_handle_plan as plan_generator
import report_completion_audit_setup_gaps as reporter
from test_generate_completion_audit_dispatch_gate import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json


def _write_plan(root: Path, *, ready: bool = False) -> Path:
    launch_pack_path, setup_state_path = _write_setup_state(root, ready=ready)
    plan_path = root / "setup-handle-plan.json"
    plan = plan_generator.generate_completion_audit_setup_handle_plan(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    _write_json(plan_path, plan.to_dict())
    return plan_path


def _write_failed_diagnostics(root: Path) -> Path:
    evidence_dir = root / "runtime-evidence"
    evidence_dir.mkdir()
    _write_json(
        evidence_dir / reporter.PROACTIVE_ARTIFACT,
        {
            "schema_version": reporter.PROACTIVE_SCHEMA_VERSION,
            "status": "fail",
            "required_next": [
                "set_live_proactive_channel_probe_env_flag",
                "configure_selected_channel_credential",
            ],
            "preflight": {
                "schema_version": "wiii.proactive_channel_preflight.v1",
                "required_next": [
                    "set_live_proactive_channel_probe_env_flag",
                    "configure_selected_channel_credential",
                ],
                "setup_contract": {"dispatch_ready": False},
            },
        },
    )
    _write_json(
        evidence_dir / reporter.LMS_ARTIFACT,
        {
            "schema_version": reporter.LMS_SCHEMA_VERSION,
            "status": "fail",
            "required_next": [
                "pass_allow_external_lms_write",
                "set_live_lms_test_course_replay_flag",
                "configure_external_lms_apply_url",
                "configure_external_lms_apply_token",
            ],
            "preflight": {
                "schema_version": "wiii.lms_test_course_preflight.v1",
                "required_next": [
                    "pass_allow_external_lms_write",
                    "set_live_lms_test_course_replay_flag",
                    "configure_external_lms_apply_url",
                    "configure_external_lms_apply_token",
                ],
                "setup_contract": {"dispatch_ready": False},
            },
        },
    )
    _write_json(
        evidence_dir / reporter.COMPOSIO_ARTIFACT,
        {
            "schema_version": reporter.COMPOSIO_SCHEMA_VERSION,
            "schema": "wiii_connect_composio_acceptance_evidence.v1",
            "status": "fail",
            "required_next": [
                "set_live_composio_acceptance_flag",
                "configure_acceptance_bearer_token",
            ],
            "preflight_summary": {
                "schema_version": "wiii.connect_composio_acceptance_preflight.v1",
                "required_next": [
                    "set_live_composio_acceptance_flag",
                    "configure_acceptance_bearer_token",
                ],
                "setup_contract": {"dispatch_ready": False},
            },
        },
    )
    return evidence_dir


def _append_lms_plan_item(plan_path: Path, *, ready: bool) -> None:
    payload = _load_json(plan_path)
    checks = [
        _setup_check("workflow_inputs_required", "run_lms_replay", ["run_lms_replay"], ready=ready),
        _setup_check("workflow_inputs_required", "transport_mode", ["transport_mode", "--transport-mode"], ready=ready),
        _setup_check("workflow_inputs_required", "base_url", ["base_url", "--base-url"], ready=ready),
        _setup_check("workflow_inputs_required", "allow_write", ["run_lms_replay", "--allow-write"], ready=ready),
        _setup_check(
            "workflow_inputs_required",
            "allow_external_lms_write",
            ["run_lms_replay", "--allow-external-lms-write"],
            ready=ready,
        ),
        _setup_check("workflow_inputs_required", "allow_production", ["allow_production"], ready=ready),
        _setup_check(
            "environment_flags_required",
            "live_lms_test_course_replay_flag",
            ["WIII_LIVE_LMS_TEST_COURSE_REPLAY"],
            ready=ready,
        ),
        _setup_check(
            "credential_slots_required",
            "external_lms_apply_token",
            ["WIII_LMS_TEST_COURSE_APPLY_TOKEN"],
            ready=ready,
        ),
        _setup_check(
            "credential_slots_required",
            "lms_backend_bearer_token",
            ["WIII_LMS_TEST_COURSE_BEARER_TOKEN"],
            ready=ready,
        ),
        _setup_check(
            "external_setup_required",
            "external_lms_apply_endpoint",
            ["WIII_LMS_TEST_COURSE_APPLY_URL"],
            ready=ready,
        ),
        _setup_check(
            "external_setup_required",
            "staging_or_local_backend",
            ["base_url", "transport_mode"],
            ready=ready,
        ),
    ]
    payload["plan_items"].append(
        {
            "requirement_id": reporter.LMS_REQUIREMENT_ID,
            "title": "LMS test-course preview/apply replay evidence",
            "setup_status": "ready" if ready else "pending",
            "dispatch_ready": ready,
            "setup_checks": checks,
        }
    )
    _refresh_plan_summaries(payload)
    _write_json(plan_path, payload)


def _setup_check(
    category: str,
    key: str,
    tokens: list[str],
    *,
    ready: bool,
) -> dict:
    evidence_kind = plan_generator._recommended_evidence_kind(
        reporter.LMS_REQUIREMENT_ID,
        category,
        key,
    )
    return {
        "category": category,
        "key": key,
        "binding_tokens": tokens,
        "present": ready,
        "source_handle": tokens[0] if ready else "",
        "recommended_handle_specs": (
            []
            if ready
            else [
                f"{reporter.LMS_REQUIREMENT_ID}:{category}:{key}={token}"
                for token in tokens
            ]
        ),
        "recommended_evidence_kinds": [] if ready else [evidence_kind],
        "recommended_attestation_specs": (
            []
            if ready
            else [
                (
                    f"{reporter.LMS_REQUIREMENT_ID}:{category}:{key}={token}"
                    f"@{evidence_kind}:{token}"
                )
                for token in tokens
            ]
        ),
    }


def _refresh_plan_summaries(payload: dict) -> None:
    ready_items = 0
    ready_checks = 0
    pending_checks = 0
    for item in payload["plan_items"]:
        item_ready = item["dispatch_ready"] is True
        ready_items += int(item_ready)
        for check in item["setup_checks"]:
            if check["present"] is True:
                ready_checks += 1
            else:
                pending_checks += 1
    payload["requirement_count"] = len(payload["plan_items"])
    payload["ready_requirement_count"] = ready_items
    payload["blocked_requirement_count"] = payload["requirement_count"] - ready_items
    payload["ready_setup_check_count"] = ready_checks
    payload["pending_setup_check_count"] = pending_checks
    payload["setup_handle_plan_fingerprint_sha256"] = (
        plan_generator._setup_handle_plan_fingerprint(payload["plan_items"])
    )


class ReportCompletionAuditSetupGapsTests(unittest.TestCase):
    def test_report_lists_pending_setup_gaps_without_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = _write_plan(root)

            report = reporter.report_completion_audit_setup_gaps(plan_path).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertEqual(reporter.SETUP_GAP_REPORT_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual(2, report["blocked_requirement_count"])
        self.assertGreater(report["pending_setup_check_count"], 0)
        self.assertEqual(0, report["diagnostic_requirement_count"])
        self.assertTrue(report["setup_diagnostics_consistent"])
        self.assertFalse(report["privacy"]["secret_values_included"])

    def test_report_flags_preflight_required_next_that_setup_claims_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = _write_plan(root, ready=True)
            evidence_dir = _write_failed_diagnostics(root)

            report = reporter.report_completion_audit_setup_gaps(
                plan_path,
                runtime_evidence_dir=evidence_dir,
            ).to_dict()

        rendered = json.dumps(report, sort_keys=True)
        self.assertTrue(report["ok"], report)
        self.assertEqual(2, report["diagnostic_requirement_count"])
        self.assertFalse(report["setup_diagnostics_consistent"])
        self.assertGreaterEqual(report["diagnostic_present_setup_mismatch_count"], 2)
        proactive = next(
            item
            for item in report["requirements"]
            if item["requirement_id"] == reporter.PROACTIVE_REQUIREMENT_ID
        )
        self.assertIn(
            "set_live_proactive_channel_probe_env_flag",
            proactive["diagnostic_required_next"],
        )
        self.assertGreater(proactive["diagnostic_present_setup_mismatches"], [])
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_report_treats_required_next_as_consistent_when_setup_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = _write_plan(root)
            _append_lms_plan_item(plan_path, ready=False)
            evidence_dir = _write_failed_diagnostics(root)

            report = reporter.report_completion_audit_setup_gaps(
                plan_path,
                runtime_evidence_dir=evidence_dir,
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertTrue(report["setup_diagnostics_consistent"])
        self.assertEqual(0, report["diagnostic_present_setup_mismatch_count"])
        self.assertGreater(report["diagnostic_pending_setup_check_count"], 0)
        self.assertGreater(report["non_diagnostic_pending_setup_check_count"], 0)
        self.assertEqual(
            report["pending_setup_check_count"],
            report["diagnostic_pending_setup_check_count"]
            + report["non_diagnostic_pending_setup_check_count"],
        )
        mapped = [
            mapping
            for item in report["requirements"]
            for mapping in item["diagnostic_required_next_mapped_checks"]
        ]
        self.assertGreater(mapped, [])
        self.assertTrue(all(mapping["present"] is False for mapping in mapped))
        for item in report["requirements"]:
            self.assertEqual(
                item["pending_setup_check_count"],
                item["diagnostic_pending_setup_check_count"]
                + item["non_diagnostic_pending_setup_check_count"],
            )
            self.assertEqual(
                item["diagnostic_pending_setup_check_count"],
                len(item["diagnostic_pending_setup_keys"]),
            )
            self.assertEqual(
                item["non_diagnostic_pending_setup_check_count"],
                len(item["non_diagnostic_pending_setup_keys"]),
            )
        lms = next(
            item
            for item in report["requirements"]
            if item["requirement_id"] == reporter.LMS_REQUIREMENT_ID
        )
        self.assertIn(
            "credential_slots_required:external_lms_apply_token",
            lms["diagnostic_pending_setup_keys"],
        )
        self.assertIn(
            "credential_slots_required:lms_backend_bearer_token",
            lms["non_diagnostic_pending_setup_keys"],
        )

    def test_report_maps_lms_preflight_required_next_to_setup_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = _write_plan(root, ready=True)
            _append_lms_plan_item(plan_path, ready=True)
            evidence_dir = _write_failed_diagnostics(root)

            report = reporter.report_completion_audit_setup_gaps(
                plan_path,
                runtime_evidence_dir=evidence_dir,
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertEqual(3, report["diagnostic_requirement_count"])
        self.assertFalse(report["setup_diagnostics_consistent"])
        lms = next(
            item
            for item in report["requirements"]
            if item["requirement_id"] == reporter.LMS_REQUIREMENT_ID
        )
        self.assertIn(
            "configure_external_lms_apply_url",
            lms["diagnostic_required_next"],
        )
        mismatches = {
            (mapping["required_next"], mapping["category"], mapping["key"])
            for mapping in lms["diagnostic_present_setup_mismatches"]
        }
        self.assertIn(
            (
                "configure_external_lms_apply_url",
                "external_setup_required",
                "external_lms_apply_endpoint",
            ),
            mismatches,
        )
        self.assertIn(
            (
                "configure_external_lms_apply_token",
                "credential_slots_required",
                "external_lms_apply_token",
            ),
            mismatches,
        )

    def test_cli_writes_markdown_gap_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = _write_plan(root, ready=True)
            evidence_dir = _write_failed_diagnostics(root)
            out_path = root / "setup-gap-report.md"

            exit_code = reporter.main(
                [
                    str(plan_path),
                    "--runtime-evidence-dir",
                    str(evidence_dir),
                    "--format",
                    "markdown",
                    "--out",
                    str(out_path),
                ]
            )
            rendered = out_path.read_text(encoding="utf-8")

        self.assertEqual(0, exit_code)
        self.assertIn("Wiii Completion Audit Setup Gap Report", rendered)
        self.assertIn("setup_diagnostics_consistent: false", rendered)

    def test_cli_reports_invalid_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = _write_plan(root)
            payload = _load_json(plan_path)
            payload["privacy"]["secret_values_included"] = True
            _write_json(plan_path, payload)

            exit_code = reporter.main([str(plan_path)])

        self.assertEqual(1, exit_code)


if __name__ == "__main__":
    unittest.main()
