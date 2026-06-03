import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_dispatch_gate as dispatch_gate_generator
import generate_completion_audit_launch_pack as launch_pack_generator
import generate_completion_audit_recovery_checkpoint as recovery_checkpoint_generator
import generate_completion_audit_recovery_dispatch_authorization as recovery_authorization_generator
import generate_completion_audit_recovery_queue_progress as recovery_progress_generator
import generate_completion_audit_recovery_work_order as recovery_work_order_generator
import generate_completion_audit_run_plan as run_plan_generator
import generate_completion_audit_setup_attestation_template as setup_attestation_template_generator
import generate_completion_audit_setup_handle_plan as setup_handle_plan_generator
import generate_completion_audit_setup_state as setup_state_generator
from test_generate_completion_audit_recovery_plan import (
    _sample_handoff_payload as _sample_recovery_handoff_payload,
)
from test_generate_completion_audit_recovery_work_order import (
    _write_sources as _write_recovery_sources,
)
from test_generate_completion_audit_run_plan import _sample_readiness_payload, _write_json
from test_validate_completion_audit_setup_state import _load_json
import report_completion_audit_setup_gaps as setup_gap_reporter
import report_completion_audit_recovery_work_order_status as recovery_status_reporter
import run_completion_audit_dispatch_diagnostics as diagnostics_runner
import run_completion_audit_dispatch_gate as dispatch_runner
import run_completion_audit_recovery_dispatch_authorization as recovery_dispatch_runner
import smoke_completion_audit_setup_attestation as setup_attestation_smoke_runner
import validate_completion_audit_control_chain as validator
import validate_completion_audit_recovery_control_chain as recovery_control_chain_validator


def _write_recovery_control_chain(root: Path, *, setup_state_path: Path) -> Path:
    recovery_root = root / "recovery"
    recovery_root.mkdir()
    handoff_path, plan_path, queue_path = _write_recovery_sources(
        recovery_root,
        _sample_recovery_handoff_payload(),
    )
    work_order_path = recovery_root / "work-order.json"
    status_path = recovery_root / "work-order-status.json"
    progress_path = recovery_root / "queue-progress.json"
    authorization_path = recovery_root / "authorization.json"
    run_path = recovery_root / "run.json"
    control_chain_path = root / "recovery-control-chain.json"

    work_order = recovery_work_order_generator.generate_completion_audit_recovery_work_order(
        queue_path,
        recovery_plan_path=plan_path,
        handoff_json_path=handoff_path,
    )
    _write_json(work_order_path, work_order.to_dict())
    status = recovery_status_reporter.report_completion_audit_recovery_work_order_status(
        work_order_path,
        recovery_queue_path=queue_path,
        recovery_plan_path=plan_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
    )
    _write_json(status_path, status.to_dict())
    progress = recovery_progress_generator.generate_completion_audit_recovery_queue_progress(
        queue_path,
        recovery_plan_path=plan_path,
        work_order_status_path=status_path,
        recovery_work_order_path=work_order_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
    )
    _write_json(progress_path, progress.to_dict())
    authorization = (
        recovery_authorization_generator.generate_completion_audit_recovery_dispatch_authorization(
            progress_path,
            recovery_plan_path=plan_path,
            source_recovery_queue_path=queue_path,
            work_order_status_path=status_path,
            recovery_work_order_path=work_order_path,
            handoff_json_path=handoff_path,
            setup_state_path=setup_state_path,
        )
    )
    _write_json(authorization_path, authorization.to_dict())
    run = recovery_dispatch_runner.run_completion_audit_recovery_dispatch_authorization(
        authorization_path,
        recovery_queue_progress_path=progress_path,
        recovery_plan_path=plan_path,
        source_recovery_queue_path=queue_path,
        work_order_status_path=status_path,
        recovery_work_order_path=work_order_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
        repo_root=Path.cwd(),
    )
    _write_json(run_path, run.to_dict())
    control_chain = recovery_control_chain_validator.validate_recovery_control_chain(
        recovery_plan_path=plan_path,
        recovery_queue_path=queue_path,
        recovery_work_order_path=work_order_path,
        recovery_work_order_status_path=status_path,
        recovery_queue_progress_path=progress_path,
        recovery_dispatch_authorization_path=authorization_path,
        recovery_dispatch_run_path=run_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
        repo_root=Path.cwd(),
    )
    _write_json(control_chain_path, control_chain.to_dict())
    return control_chain_path


def _write_control_chain(root: Path) -> dict[str, Path]:
    readiness_path = root / "readiness.json"
    run_plan_path = root / "run-plan.json"
    launch_pack_path = root / "launch-pack.json"
    setup_state_path = root / "setup-state.json"
    setup_handle_plan_path = root / "setup-handle-plan.json"
    setup_gap_report_path = root / "setup-gaps.json"
    setup_gap_markdown_report_path = root / "setup-gaps.md"
    setup_attestation_template_path = root / "setup-attestation-template.json"
    setup_attestation_smoke_path = root / "setup-attestation-smoke.json"
    setup_attestation_smoke_out_dir = root / "setup-attestation-smoke"
    dispatch_gate_path = root / "dispatch-gate.json"
    dispatch_run_path = root / "dispatch-run.json"
    dispatch_diagnostics_path = root / "dispatch-diagnostics.json"

    _write_json(readiness_path, _sample_readiness_payload())
    run_plan = run_plan_generator.generate_completion_audit_run_plan(readiness_path)
    _write_json(run_plan_path, run_plan.to_dict())
    launch_pack = launch_pack_generator.generate_completion_audit_launch_pack(
        run_plan_path,
        readiness_report_path=readiness_path,
    )
    _write_json(launch_pack_path, launch_pack.to_dict())
    setup_state = setup_state_generator.generate_completion_audit_setup_state(
        launch_pack_path
    )
    _write_json(setup_state_path, setup_state.to_dict())
    setup_handle_plan = (
        setup_handle_plan_generator.generate_completion_audit_setup_handle_plan(
            setup_state_path,
            launch_pack_path=launch_pack_path,
        )
    )
    _write_json(setup_handle_plan_path, setup_handle_plan.to_dict())
    setup_gap_report = setup_gap_reporter.report_completion_audit_setup_gaps(
        setup_handle_plan_path
    )
    _write_json(setup_gap_report_path, setup_gap_report.to_dict())
    setup_gap_markdown_report_path.write_text(
        setup_gap_reporter.render_markdown(setup_gap_report),
        encoding="utf-8",
    )
    setup_attestation_template = (
        setup_attestation_template_generator.generate_completion_audit_setup_attestation_template(
            setup_handle_plan_path,
            setup_state_path=setup_state_path,
            launch_pack_path=launch_pack_path,
        )
    )
    _write_json(setup_attestation_template_path, setup_attestation_template.to_dict())
    setup_attestation_smoke_runner.run_completion_audit_setup_attestation_smoke(
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        setup_handle_plan_path=setup_handle_plan_path,
        template_path=setup_attestation_template_path,
        out_dir=setup_attestation_smoke_out_dir,
        json_out=setup_attestation_smoke_path,
        repo_root=Path.cwd(),
    )
    dispatch_gate = dispatch_gate_generator.generate_completion_audit_dispatch_gate(
        launch_pack_path,
        setup_state_path,
    )
    _write_json(dispatch_gate_path, dispatch_gate.to_dict())
    dispatch_run = dispatch_runner.run_completion_audit_dispatch_gate(
        dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        repo_root=Path.cwd(),
    )
    _write_json(dispatch_run_path, dispatch_run.to_dict())
    dispatch_diagnostics = diagnostics_runner.run_completion_audit_dispatch_diagnostics(
        dispatch_run_path,
        dispatch_gate_path=dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        repo_root=Path.cwd(),
    )
    _write_json(dispatch_diagnostics_path, dispatch_diagnostics.to_dict())
    recovery_control_chain_path = _write_recovery_control_chain(
        root,
        setup_state_path=setup_state_path,
    )
    recovery_checkpoint_path = root / "recovery-checkpoint.json"
    recovery_checkpoint = (
        recovery_checkpoint_generator.generate_completion_audit_recovery_checkpoint(
            recovery_control_chain_path,
            repo_root=Path.cwd(),
        )
    )
    _write_json(recovery_checkpoint_path, recovery_checkpoint.to_dict())
    return {
        "readiness": readiness_path,
        "run_plan": run_plan_path,
        "launch_pack": launch_pack_path,
        "setup_state": setup_state_path,
        "setup_handle_plan": setup_handle_plan_path,
        "setup_gap_report": setup_gap_report_path,
        "setup_gap_markdown_report": setup_gap_markdown_report_path,
        "setup_attestation_template": setup_attestation_template_path,
        "setup_attestation_smoke": setup_attestation_smoke_path,
        "setup_attestation_smoke_out_dir": setup_attestation_smoke_out_dir,
        "setup_attestation": setup_attestation_smoke_out_dir / "setup-attestation.json",
        "setup_attestation_patch": setup_attestation_smoke_out_dir / "setup-handle-patch.json",
        "attested_setup_state": setup_attestation_smoke_out_dir / "setup-state-attested.json",
        "attested_dispatch_gate": setup_attestation_smoke_out_dir / "dispatch-gate-attested.json",
        "attested_dispatch_run": setup_attestation_smoke_out_dir / "dispatch-run-dry.json",
        "dispatch_gate": dispatch_gate_path,
        "dispatch_run": dispatch_run_path,
        "dispatch_diagnostics": dispatch_diagnostics_path,
        "recovery_control_chain": recovery_control_chain_path,
        "recovery_checkpoint": recovery_checkpoint_path,
    }


def _validate(paths: dict[str, Path]) -> validator.ControlChainValidationResult:
    return validator.validate_control_chain(
        readiness_report_path=paths["readiness"],
        run_plan_path=paths["run_plan"],
        launch_pack_path=paths["launch_pack"],
        setup_state_path=paths["setup_state"],
        setup_handle_plan_path=paths["setup_handle_plan"],
        setup_gap_report_path=paths.get("setup_gap_report"),
        setup_gap_markdown_report_path=paths.get("setup_gap_markdown_report"),
        setup_attestation_template_path=paths.get("setup_attestation_template"),
        setup_attestation_smoke_path=paths.get("setup_attestation_smoke"),
        setup_attestation_smoke_out_dir=paths.get("setup_attestation_smoke_out_dir"),
        setup_attestation_path=paths.get("setup_attestation"),
        setup_attestation_patch_path=paths.get("setup_attestation_patch"),
        attested_setup_state_path=paths.get("attested_setup_state"),
        attested_dispatch_gate_path=paths.get("attested_dispatch_gate"),
        attested_dispatch_run_path=paths.get("attested_dispatch_run"),
        dispatch_gate_path=paths["dispatch_gate"],
        dispatch_run_path=paths["dispatch_run"],
        dispatch_diagnostics_path=paths.get("dispatch_diagnostics"),
        recovery_control_chain_path=paths.get("recovery_control_chain"),
        recovery_checkpoint_path=paths.get("recovery_checkpoint"),
        repo_root=Path.cwd(),
    )


class ValidateCompletionAuditControlChainTests(unittest.TestCase):
    def test_valid_pending_control_chain_passes_but_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            dispatch_run_payload = _load_json(paths["dispatch_run"])

            result = _validate(paths)

        payload = result.to_dict()
        self.assertTrue(result.ok, payload)
        self.assertFalse(payload["control_chain_ready"])
        self.assertFalse(payload["dispatch_ready"])
        self.assertEqual(str(paths["dispatch_diagnostics"]), payload["dispatch_diagnostics_path"])
        self.assertEqual(
            str(paths["setup_gap_report"]),
            payload["setup_gap_report_path"],
        )
        self.assertEqual(
            str(paths["setup_gap_markdown_report"]),
            payload["setup_gap_markdown_report_path"],
        )
        self.assertEqual(
            str(paths["setup_attestation_template"]),
            payload["setup_attestation_template_path"],
        )
        self.assertEqual(
            str(paths["setup_attestation_smoke"]),
            payload["setup_attestation_smoke_path"],
        )
        self.assertEqual(
            str(paths["recovery_control_chain"]),
            payload["recovery_control_chain_path"],
        )
        self.assertEqual(
            str(paths["recovery_checkpoint"]),
            payload["recovery_checkpoint_path"],
        )
        self.assertFalse(payload["recovery_chain_ready"])
        self.assertFalse(payload["recovery_release_gate_ready"])
        self.assertTrue(payload["recovery_operator_setup_required"])
        self.assertEqual("collect_operator_setup", payload["recovery_resume_state"])
        self.assertEqual(
            [
                "setup_attestation",
                "attested_setup_state",
                "attested_dispatch_gate",
                "recovery_control_chain_replay",
            ],
            payload["recovery_required_resume_inputs"],
        )
        self.assertEqual(
            str(paths["setup_attestation"]),
            payload["setup_attestation_path"],
        )
        self.assertEqual(
            str(paths["attested_dispatch_run"]),
            payload["attested_dispatch_run_path"],
        )
        self.assertEqual([], payload["error_codes"])
        self.assertIn(
            "completion_audit_dispatch_run_gate_not_ready",
            dispatch_run_payload["error_codes"],
        )

    def test_stale_dispatch_diagnostics_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["dispatch_diagnostics"])
            payload["dispatch_run_sha256"] = "0" * 64
            _write_json(paths["dispatch_diagnostics"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_stale_recovery_control_chain_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["recovery_control_chain"])
            payload["chain_fingerprint_sha256"] = "0" * 64
            _write_json(paths["recovery_control_chain"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_recovery_control_chain_source_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            control_payload = _load_json(paths["recovery_control_chain"])
            plan_path = Path(control_payload["recovery_plan_path"])
            plan_payload = _load_json(plan_path)
            plan_payload["action_items_fingerprint_sha256"] = "0" * 64
            _write_json(plan_path, plan_payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_stale_recovery_checkpoint_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["recovery_checkpoint"])
            payload["resume_checkpoint_fingerprint_sha256"] = "0" * 64
            _write_json(paths["recovery_checkpoint"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_recovery_checkpoint_source_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["recovery_control_chain"])
            payload["chain_state"] = "release_ready"
            _write_json(paths["recovery_control_chain"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_stale_setup_gap_report_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["setup_gap_report"])
            payload["setup_handle_plan_sha256"] = "0" * 64
            _write_json(paths["setup_gap_report"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_stale_setup_gap_markdown_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            text = paths["setup_gap_markdown_report"].read_text(encoding="utf-8")
            paths["setup_gap_markdown_report"].write_text(
                text.replace("- blocked_requirement_count: 2", "- blocked_requirement_count: 0"),
                encoding="utf-8",
            )

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_stale_setup_attestation_smoke_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["setup_attestation_smoke"])
            payload["source_paths"]["launch_pack"] = "stale-launch-pack.json"
            _write_json(paths["setup_attestation_smoke"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_stale_attested_dispatch_run_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["attested_dispatch_run"])
            payload["dispatch_gate_sha256"] = "0" * 64
            _write_json(paths["attested_dispatch_run"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_stale_dispatch_run_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["dispatch_run"])
            payload["dispatch_gate_sha256"] = "0" * 64
            _write_json(paths["dispatch_run"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_pending_dispatch_run_must_keep_live_commands_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            payload = _load_json(paths["dispatch_run"])
            payload["commands"] = [
                {
                    "requirement_id": "autonomy-proactive-channel",
                    "command_name": "workflow_dispatch",
                    "working_directory": ".",
                    "argv": ["gh", "workflow", "run", "x.yml"],
                    "uses_shell": False,
                    "executed": False,
                    "returncode": -1,
                    "stdout_included": False,
                    "stderr_included": False,
                }
            ]
            payload["command_count"] = 1
            payload["dispatch_run_fingerprint_sha256"] = (
                dispatch_runner._dispatch_run_fingerprint(
                    payload["commands"],
                    payload["errors"],
                    payload["diagnostic_commands"],
                )
            )
            _write_json(paths["dispatch_run"], payload)

            result = _validate(paths)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_control_chain(Path(temp_dir))
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        "--readiness-report",
                        str(paths["readiness"]),
                        "--run-plan",
                        str(paths["run_plan"]),
                        "--launch-pack",
                        str(paths["launch_pack"]),
                        "--setup-state",
                        str(paths["setup_state"]),
                        "--setup-handle-plan",
                        str(paths["setup_handle_plan"]),
                        "--setup-gap-report",
                        str(paths["setup_gap_report"]),
                        "--setup-gap-markdown-report",
                        str(paths["setup_gap_markdown_report"]),
                        "--setup-attestation-template",
                        str(paths["setup_attestation_template"]),
                        "--setup-attestation-smoke",
                        str(paths["setup_attestation_smoke"]),
                        "--setup-attestation-smoke-out-dir",
                        str(paths["setup_attestation_smoke_out_dir"]),
                        "--setup-attestation",
                        str(paths["setup_attestation"]),
                        "--setup-attestation-patch",
                        str(paths["setup_attestation_patch"]),
                        "--attested-setup-state",
                        str(paths["attested_setup_state"]),
                        "--attested-dispatch-gate",
                        str(paths["attested_dispatch_gate"]),
                        "--attested-dispatch-run",
                        str(paths["attested_dispatch_run"]),
                        "--dispatch-gate",
                        str(paths["dispatch_gate"]),
                        "--dispatch-run",
                        str(paths["dispatch_run"]),
                        "--dispatch-diagnostics",
                        str(paths["dispatch_diagnostics"]),
                        "--recovery-control-chain",
                        str(paths["recovery_control_chain"]),
                        "--recovery-checkpoint",
                        str(paths["recovery_checkpoint"]),
                        "--repo-root",
                        str(Path.cwd()),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(
            str(paths["dispatch_diagnostics"]),
            payload["dispatch_diagnostics_path"],
        )
        self.assertEqual(
            str(paths["setup_gap_report"]),
            payload["setup_gap_report_path"],
        )
        self.assertEqual(
            str(paths["setup_gap_markdown_report"]),
            payload["setup_gap_markdown_report_path"],
        )
        self.assertEqual(
            str(paths["setup_attestation_smoke"]),
            payload["setup_attestation_smoke_path"],
        )
        self.assertEqual(
            str(paths["recovery_control_chain"]),
            payload["recovery_control_chain_path"],
        )
        self.assertEqual(
            str(paths["recovery_checkpoint"]),
            payload["recovery_checkpoint_path"],
        )
        self.assertFalse(payload["recovery_chain_ready"])
        self.assertFalse(payload["recovery_release_gate_ready"])
        self.assertTrue(payload["recovery_operator_setup_required"])
        self.assertEqual("collect_operator_setup", payload["recovery_resume_state"])
        self.assertEqual(
            str(paths["attested_dispatch_run"]),
            payload["attested_dispatch_run_path"],
        )
        self.assertFalse(payload["control_chain_ready"])

    def test_cli_out_writes_control_chain_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_control_chain(root)
            out_path = root / "control-chain.json"

            exit_code = validator.main(
                [
                    "--readiness-report",
                    str(paths["readiness"]),
                    "--run-plan",
                    str(paths["run_plan"]),
                    "--launch-pack",
                    str(paths["launch_pack"]),
                    "--setup-state",
                    str(paths["setup_state"]),
                    "--setup-handle-plan",
                    str(paths["setup_handle_plan"]),
                    "--dispatch-gate",
                    str(paths["dispatch_gate"]),
                    "--dispatch-run",
                    str(paths["dispatch_run"]),
                    "--recovery-control-chain",
                    str(paths["recovery_control_chain"]),
                    "--recovery-checkpoint",
                    str(paths["recovery_checkpoint"]),
                    "--repo-root",
                    str(Path.cwd()),
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual("collect_operator_setup", payload["recovery_resume_state"])

    def test_cli_out_rejects_directory_without_writing_inside_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_control_chain(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        "--readiness-report",
                        str(paths["readiness"]),
                        "--run-plan",
                        str(paths["run_plan"]),
                        "--launch-pack",
                        str(paths["launch_pack"]),
                        "--setup-state",
                        str(paths["setup_state"]),
                        "--setup-handle-plan",
                        str(paths["setup_handle_plan"]),
                        "--dispatch-gate",
                        str(paths["dispatch_gate"]),
                        "--dispatch-run",
                        str(paths["dispatch_run"]),
                        "--out",
                        str(root),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "completion_audit_control_chain_output_path_directory",
            payload["error_codes"],
        )

    def test_cli_out_rejects_symlink_without_writing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_control_chain(root)
            target_path = root / "target.json"
            out_path = root / "linked.json"
            try:
                os.symlink(target_path, out_path)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        "--readiness-report",
                        str(paths["readiness"]),
                        "--run-plan",
                        str(paths["run_plan"]),
                        "--launch-pack",
                        str(paths["launch_pack"]),
                        "--setup-state",
                        str(paths["setup_state"]),
                        "--setup-handle-plan",
                        str(paths["setup_handle_plan"]),
                        "--dispatch-gate",
                        str(paths["dispatch_gate"]),
                        "--dispatch-run",
                        str(paths["dispatch_run"]),
                        "--out",
                        str(out_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(target_path.exists())
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_control_chain_output_path_symlink"],
            payload["error_codes"],
        )

    def test_cli_out_rejects_parent_symlink_without_writing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_control_chain(root)
            target_dir = root / "target"
            target_dir.mkdir()
            symlink_parent = root / "linked-parent"
            try:
                os.symlink(target_dir, symlink_parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")
            out_path = symlink_parent / "control-chain.json"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        "--readiness-report",
                        str(paths["readiness"]),
                        "--run-plan",
                        str(paths["run_plan"]),
                        "--launch-pack",
                        str(paths["launch_pack"]),
                        "--setup-state",
                        str(paths["setup_state"]),
                        "--setup-handle-plan",
                        str(paths["setup_handle_plan"]),
                        "--dispatch-gate",
                        str(paths["dispatch_gate"]),
                        "--dispatch-run",
                        str(paths["dispatch_run"]),
                        "--out",
                        str(out_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse((target_dir / "control-chain.json").exists())
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_control_chain_output_path_parent_symlink"],
            payload["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
