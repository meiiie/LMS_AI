import copy
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_runtime_evidence_coverage as coverage
import validate_runtime_evidence_registry as registry_validator


def _registry_with_synthetic_lms_gap() -> dict:
    registry = copy.deepcopy(
        registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
    )
    requirement = next(
        item for item in registry["requirements"] if item["id"] == "lms-test-course-replay"
    )
    for check in requirement["payload_checks"]:
        if check.get("path") == "evidence_contract.synthetic_host_side_replay":
            check["equals"] = True
        if check.get("path") == "evidence_contract.external_lms_write_disabled":
            check["equals"] = True
        if check.get("path") == "evidence_contract.requires_live_channel_credentials":
            check["equals"] = False
    return registry


def _registry_with_weak_credentialed_external_contract() -> dict:
    registry = copy.deepcopy(
        registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
    )
    requirement = next(
        item
        for item in registry["requirements"]
        if item["id"] == "provider-runtime-tool-loop"
    )
    requirement["live_env_flags"] = []
    requirement["live_guard_tokens"] = []
    requirement["dispatch_or_schedule_gate_tokens"] = ["allow_live_call"]
    return registry


class RuntimeEvidenceCoverageReportTests(unittest.TestCase):
    def test_default_registry_renders_operator_markdown(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

        report = coverage.build_report(registry)
        rendered = coverage.format_markdown(report)

        self.assertTrue(report.ok, report.to_dict())
        self.assertFalse(report.coverage_errors)
        self.assertIn("# Wiii Runtime Evidence Coverage", rendered)
        self.assertIn("payload_checks >= freshness_hours", rendered)
        self.assertIn("provider-runtime-tool-loop", rendered)
        self.assertIn("provider-runtime-evidence-${{ github.run_id }}", rendered)
        self.assertIn("autonomy-proactive-channel", rendered)
        self.assertIn("autonomy-proactive-channel-preflight.json", rendered)
        self.assertIn("lms-test-course-replay", rendered)
        self.assertIn("lms-test-course-preflight.json", rendered)
        self.assertIn("semantic-memory-write-doctor", rendered)
        self.assertIn("wiii-connect-action-replay", rendered)
        self.assertIn("wiii-connect-facebook-post-replay", rendered)
        self.assertIn("wiii-connect-composio-acceptance", rendered)
        self.assertIn("runtime-ledger-browser-replay", rendered)
        self.assertIn("WIII_LIVE_PROVIDER_RUNTIME_PROBE", rendered)
        self.assertIn("WIII_LMS_TEST_COURSE_EVIDENCE_ENABLED", rendered)
        self.assertIn("WIII_SEMANTIC_MEMORY_WRITE_EVIDENCE_ENABLED", rendered)
        self.assertIn("WIII_CONNECT_ACTION_EVIDENCE_ENABLED", rendered)
        self.assertIn("WIII_CONNECT_FACEBOOK_POST_REPLAY_EVIDENCE_ENABLED", rendered)
        self.assertIn("WIII_CONNECT_COMPOSIO_ACCEPTANCE_EVIDENCE_ENABLED", rendered)
        self.assertIn("WIII_RUNTIME_LEDGER_BROWSER_REPLAY_EVIDENCE_ENABLED", rendered)
        self.assertIn("validate_runtime_evidence_artifact.py", rendered)
        self.assertIn("Privacy/Provenance", rendered)
        self.assertIn("hash_or_count_only", rendered)
        self.assertIn("status_only", rendered)

    def test_coverage_report_exposes_report_schema_version(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

        report = coverage.build_report(registry)
        payload = json.loads(json.dumps(report.to_dict()))
        rendered = coverage.format_markdown(report)

        self.assertEqual(
            coverage.COVERAGE_REPORT_SCHEMA_VERSION,
            report.schema_version,
        )
        self.assertEqual(
            coverage.COVERAGE_REPORT_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertEqual([], report.error_codes)
        self.assertEqual([], payload["error_codes"])
        self.assertEqual({}, report.error_code_counts)
        self.assertEqual({}, payload["error_code_counts"])
        self.assertEqual([], payload["validation_error_codes"])
        self.assertEqual([], payload["coverage_error_codes"])
        self.assertIn("- Error codes: `-`", rendered)
        self.assertIn("- Error code counts: `-`", rendered)
        self.assertIn(
            "Report schema: `wiii.runtime_evidence_coverage_report.v1`",
            rendered,
        )

    def test_coverage_report_exposes_registry_contract_identity(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

        report = coverage.build_report(registry)
        payload = json.loads(json.dumps(report.to_dict()))
        changed = copy.deepcopy(registry)
        changed["version"] = registry["version"] + 1
        changed_report = coverage.build_report(changed)
        rendered = coverage.format_markdown(report)

        self.assertEqual(registry_validator.REGISTRY_NAME, report.registry_name)
        self.assertEqual(registry_validator.REGISTRY_NAME, payload["registry_name"])
        self.assertEqual(registry["version"], report.registry_version)
        self.assertEqual(registry["version"], payload["registry_version"])
        self.assertRegex(report.registry_fingerprint_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            report.registry_fingerprint_sha256,
            payload["registry_fingerprint_sha256"],
        )
        self.assertNotEqual(
            report.registry_fingerprint_sha256,
            changed_report.registry_fingerprint_sha256,
        )
        self.assertIn("Registry name: `Wiii Runtime Evidence Registry`", rendered)
        self.assertIn("Registry version:", rendered)
        self.assertIn("Registry fingerprint SHA-256:", rendered)

    def test_json_report_has_rows_and_layers(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

        report = coverage.build_report(registry)
        payload = json.loads(json.dumps(report.to_dict()))

        self.assertTrue(payload["ok"])
        self.assertEqual([], payload["coverage_errors"])
        self.assertGreaterEqual(payload["requirement_count"], 9)
        self.assertIn("Wiii Core", payload["layers"])
        self.assertIn("Wiii Living", payload["layers"])
        self.assertIn("Wiii Host", payload["layers"])
        self.assertEqual(payload["requirement_count"], len(payload["rows"]))
        for row in payload["rows"]:
            self.assertTrue(row["coverage_target_met"], row)
            self.assertTrue(row["artifact_tokens"], row)
            self.assertGreater(row["raw_content_absence_checks"], 0, row)
            self.assertGreater(row["identifier_strategy_checks"], 0, row)
            self.assertTrue(row["identifier_strategies"], row)

    def test_report_surfaces_upload_contracts(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

        report = coverage.build_report(registry)
        payload = json.loads(json.dumps(report.to_dict()))
        rows = {row["requirement_id"]: row for row in payload["rows"]}
        rendered = coverage.format_markdown(report)

        provider = rows["provider-runtime-tool-loop"]
        proactive = rows["autonomy-proactive-channel"]

        self.assertEqual(
            ["provider-runtime-evidence-${{ github.run_id }}"],
            provider["artifact_tokens"],
        )
        self.assertEqual(0, provider["diagnostic_upload_count"])
        self.assertEqual([], provider["diagnostic_upload_artifacts"])
        self.assertEqual([], provider["diagnostic_upload_paths"])
        self.assertEqual(
            ["autonomy-proactive-channel-preflight.json"],
            proactive["diagnostic_upload_artifacts"],
        )
        self.assertEqual(
            ["maritime-ai-service/autonomy-proactive-channel-preflight.json"],
            proactive["diagnostic_upload_paths"],
        )
        self.assertEqual(1, proactive["diagnostic_upload_count"])
        self.assertIn("Uploads", rendered)
        self.assertIn("diagnostic:1 autonomy-proactive-channel-preflight.json", rendered)

    def test_coverage_json_error_exposes_report_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            missing_registry = Path(temp_dir) / "missing-registry.json"
            with contextlib.redirect_stdout(stdout):
                exit_code = coverage.main(
                    [
                        "--registry",
                        str(missing_registry),
                        "--format",
                        "json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            coverage.COVERAGE_REPORT_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertEqual(["registry_load_failed"], payload["error_codes"])
        self.assertEqual({"registry_load_failed": 1}, payload["error_code_counts"])

    def test_report_surfaces_privacy_and_provenance_counts(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

        report = coverage.build_report(registry)
        rows = {row.requirement_id: row for row in report.rows}

        provider = rows["provider-runtime-tool-loop"]
        self.assertGreaterEqual(provider.raw_content_absence_checks, 1)
        self.assertEqual(["hashes_and_counts"], provider.identifier_strategies)

        browser_replay = rows["runtime-ledger-browser-replay"]
        self.assertGreaterEqual(browser_replay.raw_content_absence_checks, 1)
        self.assertIn("status_only", browser_replay.identifier_strategies)
        self.assertIn("hash_or_count_only", browser_replay.identifier_strategies)

    def test_report_surfaces_external_evidence_modes(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

        report = coverage.build_report(registry)
        payload = json.loads(json.dumps(report.to_dict()))
        rendered = coverage.format_markdown(report)
        rows = {row.requirement_id: row for row in report.rows}
        payload_rows = {row["requirement_id"]: row for row in payload["rows"]}

        provider = rows["provider-runtime-tool-loop"]
        lms = rows["lms-test-course-replay"]
        composio = rows["wiii-connect-composio-acceptance"]

        self.assertEqual("credentialed_external", provider.external_evidence_mode)
        self.assertIn(
            "credentialed_provider_call_required",
            provider.credentialed_external_flags,
        )
        self.assertEqual([], provider.synthetic_gap_flags)
        self.assertEqual("credentialed_external", lms.external_evidence_mode)
        self.assertEqual([], lms.synthetic_gap_flags)
        self.assertIn("requires_live_channel_credentials", lms.credentialed_external_flags)
        self.assertEqual("credentialed_external", composio.external_evidence_mode)
        self.assertIn("external_provider_execution", composio.credentialed_external_flags)
        self.assertIn("requires_connected_account", composio.credentialed_external_flags)
        self.assertEqual("credentialed_external", payload_rows["lms-test-course-replay"]["external_evidence_mode"])
        self.assertEqual(0, report.synthetic_external_gap_count)
        self.assertEqual(0, payload["synthetic_external_gap_count"])
        self.assertEqual(
            report.requirement_count,
            report.synthetic_external_gap_count
            + report.credentialed_external_count
            + report.local_or_backend_count,
        )
        self.assertEqual(
            payload["requirement_count"],
            payload["synthetic_external_gap_count"]
            + payload["credentialed_external_count"]
            + payload["local_or_backend_count"],
        )
        self.assertIn("External Mode", rendered)
        self.assertIn("External evidence:", rendered)
        self.assertIn("synthetic_external_gap", rendered)
        self.assertIn("credentialed_external", rendered)

    def test_report_can_fail_on_synthetic_external_gaps(self) -> None:
        registry = _registry_with_synthetic_lms_gap()

        report = coverage.build_report(registry, require_no_synthetic_gaps=True)
        payload = json.loads(json.dumps(report.to_dict()))
        rendered = coverage.format_markdown(report)

        self.assertFalse(report.ok)
        self.assertEqual(1, report.synthetic_external_gap_count)
        self.assertIn("coverage_synthetic_external_gap_present", report.error_codes)
        self.assertIn(
            "coverage_synthetic_external_gap_present",
            payload["coverage_error_codes"],
        )
        self.assertEqual(
            {"coverage_synthetic_external_gap_present": 1},
            payload["error_code_counts"],
        )
        self.assertIn("Coverage Gate Errors", rendered)
        self.assertIn("lms-test-course-replay", rendered)
        self.assertIn("synthetic external gap", rendered)

    def test_cli_can_require_no_synthetic_external_gaps(self) -> None:
        registry = _registry_with_synthetic_lms_gap()
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "runtime_evidence_registry.json"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(stdout):
                exit_code = coverage.main(
                    [
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--require-no-synthetic-gaps",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(1, payload["synthetic_external_gap_count"])
        self.assertIn("coverage_synthetic_external_gap_present", payload["error_codes"])

    def test_report_can_require_credentialed_external_contracts(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

        report = coverage.build_report(
            registry,
            require_credentialed_external_contracts=True,
        )
        payload = json.loads(json.dumps(report.to_dict()))

        self.assertTrue(report.ok, payload)
        self.assertEqual([], report.coverage_errors)
        self.assertGreaterEqual(report.credentialed_external_count, 1)
        self.assertEqual(0, payload["synthetic_external_gap_count"])

    def test_report_fails_when_credentialed_external_contract_is_weak(self) -> None:
        registry = _registry_with_weak_credentialed_external_contract()

        report = coverage.build_report(
            registry,
            require_credentialed_external_contracts=True,
        )
        payload = json.loads(json.dumps(report.to_dict()))
        rendered = coverage.format_markdown(report)

        self.assertFalse(report.ok)
        self.assertIn(
            "coverage_credentialed_external_contract_incomplete",
            report.coverage_error_codes,
        )
        self.assertIn(
            "coverage_credentialed_external_contract_incomplete",
            payload["error_codes"],
        )
        self.assertIn("provider-runtime-tool-loop", report.coverage_errors[0])
        self.assertIn("live_env_flags", report.coverage_errors[0])
        self.assertIn("live_guard_tokens", report.coverage_errors[0])
        self.assertIn("manual_and_scheduled_gates", report.coverage_errors[0])
        self.assertIn("Coverage Gate Errors", rendered)

    def test_cli_can_require_credentialed_external_contracts(self) -> None:
        registry = _registry_with_weak_credentialed_external_contract()
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "runtime_evidence_registry.json"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(stdout):
                exit_code = coverage.main(
                    [
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--require-credentialed-external-contracts",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "coverage_credentialed_external_contract_incomplete",
            payload["error_codes"],
        )

    def test_browser_replay_registry_uses_list_wide_case_checks(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
        requirement = next(
            item
            for item in registry["requirements"]
            if item["id"] == "runtime-ledger-browser-replay"
        )
        paths = [check["path"] for check in requirement["payload_checks"]]

        self.assertNotIn("doctor.status", paths)
        self.assertNotIn("browser_replay.cases.*.approval_token_present", paths)
        self.assertIn("doctor.ready_paths", paths)
        self.assertIn("checks.sync_parity_passed", paths)
        self.assertIn("browser_replay.cases.*.ledger_schema_version", paths)
        self.assertIn("browser_replay.cases.*.trace_version", paths)
        self.assertIn("browser_replay.cases.*.route_reason_hash_present", paths)
        self.assertIn("browser_replay.route_path_counts.lms_document_preview", paths)
        self.assertIn("browser_replay.route_path_counts.external_connection_status", paths)
        self.assertIn("browser_replay.route_path_counts.external_app_action", paths)
        self.assertIn("browser_replay.route_path_counts.visual_generation", paths)
        self.assertIn("browser_replay.validated_case_id_hashes", paths)
        self.assertIn("browser_replay.visual_lifecycle_case_count", paths)
        self.assertIn("browser_replay.code_studio_lifecycle_case_count", paths)
        self.assertIn("browser_replay.finalization_status_counts.saved", paths)
        self.assertIn("browser_replay.finalization_saved_case_count", paths)
        self.assertIn("browser_replay.finalization_error_case_count", paths)
        self.assertIn("browser_replay.finalized_case_id_hashes", paths)
        self.assertIn("browser_replay.cases.*.finalization_saved", paths)
        self.assertIn("browser_replay.post_turn_lifecycle_case_id_hashes", paths)
        self.assertIn("browser_replay.post_turn_lifecycle_case_count", paths)
        self.assertIn("browser_replay.cases.*.post_turn_lifecycle_schema_version", paths)
        self.assertIn(
            "browser_replay.cases.*.post_turn_lifecycle_raw_content_included",
            paths,
        )
        self.assertIn(
            "browser_replay.cases.*.post_turn_lifecycle_raw_scope_keys_present",
            paths,
        )
        self.assertIn("wiii_connect_capability.snapshot_version", paths)
        self.assertIn("wiii_connect_capability.path_readiness_count", paths)
        self.assertIn("wiii_connect_capability.paths.*.reason_hash_present", paths)
        self.assertTrue(
            any(check.get("length_equals_path") == "evidence.case_count" for check in requirement["payload_checks"])
        )

    def test_report_surfaces_registry_validation_errors(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
        registry["requirements"][0]["workflow"] = "../outside.yml"

        report = coverage.build_report(registry)
        payload = json.loads(json.dumps(report.to_dict()))
        rendered = coverage.format_markdown(report)

        self.assertFalse(report.ok)
        self.assertTrue(report.validation_errors)
        self.assertIn("repo_path_not_relative", report.error_codes)
        self.assertIn("repo_path_not_relative", payload["error_codes"])
        self.assertEqual(report.error_code_counts, payload["error_code_counts"])
        self.assertGreaterEqual(
            payload["error_code_counts"]["repo_path_not_relative"],
            1,
        )
        self.assertIn("repo_path_not_relative", report.validation_error_codes)
        self.assertIn("repo_path_not_relative", payload["validation_error_codes"])
        self.assertIn("Validation Errors", rendered)
        self.assertIn("Error codes:", rendered)
        self.assertIn("repo_path_not_relative", rendered)
        self.assertIn("repo-relative", rendered)

    def test_report_fails_when_payload_checks_fall_below_freshness_hours(self) -> None:
        registry = copy.deepcopy(
            registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
        )
        requirement = registry["requirements"][0]
        requirement["payload_checks"] = requirement["payload_checks"][:71]

        report = coverage.build_report(registry)
        payload = json.loads(json.dumps(report.to_dict()))
        rendered = coverage.format_markdown(report)

        self.assertFalse(report.ok)
        self.assertTrue(report.coverage_errors)
        self.assertEqual(
            ["coverage_payload_checks_below_freshness"],
            report.error_codes,
        )
        self.assertEqual(
            ["coverage_payload_checks_below_freshness"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"coverage_payload_checks_below_freshness": 1},
            payload["error_code_counts"],
        )
        self.assertEqual(
            ["coverage_payload_checks_below_freshness"],
            report.coverage_error_codes,
        )
        self.assertEqual(
            ["coverage_payload_checks_below_freshness"],
            payload["coverage_error_codes"],
        )
        self.assertFalse(
            next(
                row
                for row in report.rows
                if row.requirement_id == "provider-runtime-tool-loop"
            ).coverage_target_met
        )
        self.assertIn("Coverage Gate Errors", rendered)
        self.assertIn("Error codes: `coverage_payload_checks_below_freshness`", rendered)
        self.assertIn("provider-runtime-tool-loop", report.coverage_errors[0])
        self.assertIn("payload_checks=71", report.coverage_errors[0])

    def test_boolean_freshness_hours_does_not_satisfy_coverage_gate(self) -> None:
        registry = copy.deepcopy(
            registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
        )
        requirement = registry["requirements"][0]
        requirement["freshness"]["max_age_hours"] = True

        report = coverage.build_report(registry)
        row = next(
            row
            for row in report.rows
            if row.requirement_id == requirement["id"]
        )
        payload = json.loads(json.dumps(report.to_dict()))

        self.assertFalse(report.ok)
        self.assertIsNone(row.freshness_hours)
        self.assertFalse(row.coverage_target_met)
        self.assertIn("registry_freshness_max_age_invalid", payload["error_codes"])
        self.assertIn(
            "coverage_payload_checks_below_freshness",
            payload["error_codes"],
        )

    def test_coverage_report_exposes_error_code_counts(self) -> None:
        registry = copy.deepcopy(
            registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
        )
        for requirement in registry["requirements"][:2]:
            requirement["payload_checks"] = requirement["payload_checks"][:1]

        report = coverage.build_report(registry)
        payload = json.loads(json.dumps(report.to_dict()))
        rendered = coverage.format_markdown(report)

        self.assertFalse(report.ok)
        self.assertEqual(
            {
                "coverage_payload_checks_below_freshness": 2,
                "registry_payload_privacy_check_missing": 4,
            },
            report.error_code_counts,
        )
        self.assertEqual(report.error_code_counts, payload["error_code_counts"])
        self.assertEqual(
            [
                "coverage_payload_checks_below_freshness",
                "registry_payload_privacy_check_missing",
            ],
            payload["error_codes"],
        )
        self.assertIn(
            "- Error code counts: `coverage_payload_checks_below_freshness=2, "
            "registry_payload_privacy_check_missing=4`",
            rendered,
        )

    def test_markdown_table_cells_collapse_layout_breaks(self) -> None:
        row = coverage.CoverageRow(
            requirement_id="sample\nrequirement|id",
            title="Sample",
            layer="Wiii\nCore",
            artifact="sample-artifact.json",
            artifact_tokens=["sample-artifact-${{ github.run_id }}"],
            diagnostic_upload_count=1,
            diagnostic_upload_artifacts=["sample-preflight.json"],
            diagnostic_upload_paths=["sample/preflight.json"],
            schema_version="wiii.sample.v1",
            workflow=".github/workflows/sample.yml",
            probe="scripts/probe_sample.py",
            contract_tests=1,
            payload_checks=72,
            raw_content_absence_checks=1,
            identifier_strategy_checks=1,
            identifier_strategies=["hash_or_count_only"],
            external_evidence_mode="local_or_backend",
            synthetic_gap_flags=[],
            credentialed_external_flags=[],
            freshness_hours=72,
            forbidden_tokens=3,
            forbidden_regexes=0,
            live_env_flags=["WIII_SAMPLE\nFLAG"],
            live_guard_tokens=["--allow-sample"],
            dispatch_or_schedule_gates=["allow_sample\tgate"],
            coverage_target_met=True,
        )
        report = coverage.CoverageReport(
            schema_version=coverage.COVERAGE_REPORT_SCHEMA_VERSION,
            registry_name=registry_validator.REGISTRY_NAME,
            registry_version=1,
            registry_path="registry.json",
            registry_fingerprint_sha256="0" * 64,
            ok=True,
            error_codes=[],
            error_code_counts={},
            validation_errors=[],
            validation_error_codes=[],
            coverage_errors=[],
            coverage_error_codes=[],
            requirement_count=1,
            synthetic_external_gap_count=0,
            credentialed_external_count=0,
            local_or_backend_count=1,
            layers=["Wiii Core"],
            rows=[row],
        )

        rendered = coverage.format_markdown(report)
        data_rows = [
            line
            for line in rendered.splitlines()
            if line.startswith("| sample requirement\\|id |")
        ]

        self.assertEqual(1, len(data_rows), rendered)
        self.assertIn("Wiii Core", data_rows[0])
        self.assertIn("WIII_SAMPLE FLAG", data_rows[0])
        self.assertIn("allow_sample gate", data_rows[0])

    def test_cli_can_write_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "coverage.md"

            exit_code = coverage.main(["--out", str(out_path)])

            self.assertEqual(0, exit_code)
            self.assertIn("Wiii Runtime Evidence Coverage", out_path.read_text(encoding="utf-8"))

    def test_cli_rejects_report_output_over_registry_path(self) -> None:
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "runtime_evidence_registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = coverage.main(
                    [
                        "--registry",
                        str(registry_path),
                        "--out",
                        str(registry_path),
                        "--format",
                        "json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["coverage_report_output_path_overwrites_registry"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"coverage_report_output_path_overwrites_registry": 1},
            payload["error_code_counts"],
        )
        self.assertIn("must not overwrite registry", payload["errors"][0])

    def test_cli_rejects_report_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "coverage-report"
            out_path.mkdir()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = coverage.main(
                    [
                        "--out",
                        str(out_path),
                        "--format",
                        "json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            out_entries = list(out_path.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["coverage_report_output_path_directory"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"coverage_report_output_path_directory": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], out_entries)

    def test_cli_rejects_report_output_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "coverage-target.md"
            target_path.write_text("keep", encoding="utf-8")
            out_path = Path(temp_dir) / "coverage.md"
            try:
                os.symlink(target_path, out_path)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = coverage.main(
                    [
                        "--out",
                        str(out_path),
                        "--format",
                        "json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            target_text = target_path.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["coverage_report_output_path_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"coverage_report_output_path_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual("keep", target_text)

    def test_cli_rejects_report_output_parent_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir) / "target-dir"
            target_dir.mkdir()
            symlink_parent = Path(temp_dir) / "linked-parent"
            try:
                os.symlink(target_dir, symlink_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            out_path = symlink_parent / "coverage.md"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = coverage.main(
                    [
                        "--out",
                        str(out_path),
                        "--format",
                        "json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            target_entries = list(target_dir.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["coverage_report_output_path_parent_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"coverage_report_output_path_parent_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], target_entries)


if __name__ == "__main__":
    unittest.main()
