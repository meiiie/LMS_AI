import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from test_generate_completion_audit_run_plan import _write_json
from test_run_completion_audit_dispatch_diagnostics import (
    _write_source_bound_dispatch_run,
)
from test_validate_completion_audit_dispatch_run import _write_dispatch_run
from test_validate_completion_audit_setup_state import _load_json
import run_completion_audit_dispatch_diagnostics as runner
import validate_completion_audit_dispatch_diagnostics as validator


def _write_diagnostics_report(
    root: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    launch_pack_path, setup_state_path, gate_path, run_path = _write_dispatch_run(root)
    diagnostics_path = root / "dispatch-diagnostics.json"
    report = runner.run_completion_audit_dispatch_diagnostics(
        run_path,
        dispatch_gate_path=gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        repo_root=root,
    )
    _write_json(diagnostics_path, report.to_dict())
    return launch_pack_path, setup_state_path, gate_path, run_path, diagnostics_path


def _refresh_diagnostic_fingerprint(payload: dict) -> None:
    payload["diagnostic_run_fingerprint_sha256"] = runner._diagnostic_run_fingerprint(
        payload["commands"],
        payload["errors"],
        payload["dispatch_run_fingerprint_sha256"],
        preflight_stages=payload.get("preflight_stages", []),
    )


class ValidateCompletionAuditDispatchDiagnosticsTests(unittest.TestCase):
    def test_valid_diagnostics_report_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path, diagnostics_path = (
                _write_diagnostics_report(root)
            )

            result = validator.validate_dispatch_diagnostics(
                diagnostics_path,
                dispatch_run_path=run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            )
            payload = _load_json(diagnostics_path)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])
        self.assertFalse(payload["privacy"]["raw_output_included"])
        self.assertEqual(
            {"local_failure_from_preflight"},
            {command["command_name"] for command in payload["commands"]},
        )
        command = payload["commands"][0]
        self.assertIn("argv_rebound", command)
        self.assertIn("unresolved_placeholder_count", command)
        self.assertIn("output_artifact_validated", command)
        self.assertIn("execution_ok", command)

    def test_valid_source_bound_preflight_diagnostics_pass_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path, source_dir = (
                _write_source_bound_dispatch_run(root)
            )
            diagnostics_path = root / "dispatch-diagnostics.json"
            report = runner.run_completion_audit_dispatch_diagnostics(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                preflight_source_dirs=[source_dir],
            )
            _write_json(diagnostics_path, report.to_dict())

            result = validator.validate_dispatch_diagnostics(
                diagnostics_path,
                dispatch_run_path=run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                preflight_source_dirs=[source_dir],
                repo_root=root,
            )
            payload = _load_json(diagnostics_path)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(2, payload["preflight_stage_count"])
        self.assertEqual(0, payload["staged_preflight_count"])
        self.assertTrue(
            all(stage["validation_ok"] for stage in payload["preflight_stages"])
        )

    def test_source_parity_rejects_stale_diagnostics_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path, diagnostics_path = (
                _write_diagnostics_report(root)
            )
            payload = _load_json(diagnostics_path)
            payload["dispatch_run_sha256"] = "0" * 64
            _refresh_diagnostic_fingerprint(payload)
            _write_json(diagnostics_path, payload)

            result = validator.validate_dispatch_diagnostics(
                diagnostics_path,
                dispatch_run_path=run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_diagnostics_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_dry_run_diagnostics_must_not_execute_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, _gate_path, _run_path, diagnostics_path = (
                _write_diagnostics_report(root)
            )
            payload = _load_json(diagnostics_path)
            payload["commands"][0]["executed"] = True
            payload["commands"][0]["returncode"] = 0
            payload["executed_diagnostic_command_count"] = 1
            _refresh_diagnostic_fingerprint(payload)
            _write_json(diagnostics_path, payload)

            result = validator.validate_dispatch_diagnostics(diagnostics_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_diagnostics_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_live_dispatch_command_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, _gate_path, _run_path, diagnostics_path = (
                _write_diagnostics_report(root)
            )
            payload = _load_json(diagnostics_path)
            payload["commands"][0]["command_name"] = "workflow_dispatch"
            payload["commands"][0]["argv"] = ["gh", "workflow", "run", "x.yml"]
            _refresh_diagnostic_fingerprint(payload)
            _write_json(diagnostics_path, payload)

            result = validator.validate_dispatch_diagnostics(diagnostics_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_diagnostics_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path, diagnostics_path = (
                _write_diagnostics_report(root)
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(diagnostics_path),
                        "--dispatch-run",
                        str(run_path),
                        "--dispatch-gate",
                        str(gate_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--repo-root",
                        str(root),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.DIAGNOSTICS_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertIn("--preflight-source-dir", validator.build_parser().format_help())


if __name__ == "__main__":
    unittest.main()
