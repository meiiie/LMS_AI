import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import promote_completion_audit_runtime_evidence as promotion
import generate_completion_audit_setup_handle_plan as plan_generator
import generate_completion_audit_setup_state as setup_generator
from test_generate_completion_audit_run_plan import _write_json
from test_generate_completion_audit_setup_state import _write_launch_pack
from test_generate_completion_audit_setup_attestation_from_handles import _write_plan
from test_probe_completion_audit_setup_handle_evidence import (
    _bundle_report_for_artifacts,
    _composio_pass_payload,
    _env_for_pending_checks,
    _proactive_pass_payload,
)
from test_validate_completion_audit_setup_state import _load_json


def _write_repo_ready_plan(root: Path) -> tuple[Path, Path, Path]:
    launch_pack_path = _write_launch_pack(root)
    setup_state_path = root / "setup-state.json"
    setup_state = setup_generator.generate_completion_audit_setup_state(
        launch_pack_path,
        repo_root=Path("."),
    )
    _write_json(setup_state_path, setup_state.to_dict())
    plan_path = root / "setup-handle-plan.json"
    plan = plan_generator.generate_completion_audit_setup_handle_plan(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    _write_json(plan_path, plan.to_dict())
    return launch_pack_path, setup_state_path, plan_path


class PromoteCompletionAuditRuntimeEvidenceTests(unittest.TestCase):
    def test_promotion_promotes_validated_bundle_into_dispatch_ready_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_repo_ready_plan(root)
            plan_payload = _load_json(plan_path)
            runtime_dir = root / "runtime-evidence"
            runtime_dir.mkdir()
            proactive_path = runtime_dir / "autonomy-proactive-channel-evidence.json"
            composio_path = runtime_dir / "wiii-connect-composio-acceptance-evidence.json"
            bundle_report_path = root / "runtime-evidence-bundle-report.json"
            out_dir = root / "promotion"
            _write_json(proactive_path, _proactive_pass_payload())
            _write_json(composio_path, _composio_pass_payload())
            _write_json(
                bundle_report_path,
                _bundle_report_for_artifacts(
                    {
                        "autonomy-proactive-channel-evidence.json": proactive_path,
                        "wiii-connect-composio-acceptance-evidence.json": composio_path,
                    }
                ),
            )
            env = _env_for_pending_checks(plan_payload)

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(
                    promotion.handle_probe,
                    "_backend_health_check",
                    return_value=True,
                ),
            ):
                report = promotion.promote_completion_audit_runtime_evidence(
                    runtime_dir,
                    bundle_report_path,
                    plan_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                    out_dir=out_dir,
                    repo_root=root,
                    allow_env_read=True,
                    allow_network=True,
                )
            payload = report.to_dict()
            dispatch_run = _load_json(out_dir / "dispatch-run-attested.json")
            artifact_exists = {
                name: Path(path).is_file()
                for name, path in payload["artifacts"].items()
            }

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["promotion_ready"])
        self.assertEqual(10, payload["setup_handle_count"])
        self.assertEqual(10, payload["attestation_count"])
        self.assertEqual(0, payload["setup_state_pending_count"])
        self.assertTrue(payload["dispatch_ready"])
        self.assertTrue(payload["dispatch_run_ok"])
        self.assertEqual(0, payload["blocked_dispatch_item_count"])
        self.assertTrue(dispatch_run["ok"])
        self.assertTrue(dispatch_run["dry_run"])
        self.assertTrue(all(artifact_exists.values()), artifact_exists)

    def test_promotion_stops_before_handles_when_bundle_report_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            runtime_dir = root / "runtime-evidence"
            runtime_dir.mkdir()
            proactive_path = runtime_dir / "autonomy-proactive-channel-evidence.json"
            bundle_report_path = root / "runtime-evidence-bundle-report.json"
            out_dir = root / "promotion"
            _write_json(proactive_path, _proactive_pass_payload())
            report_payload = _bundle_report_for_artifacts(
                {"autonomy-proactive-channel-evidence.json": proactive_path},
                status_by_artifact={
                    "autonomy-proactive-channel-evidence.json": "failed",
                },
            )
            report_payload["completion_audit_ready"] = False
            _write_json(bundle_report_path, report_payload)

            report = promotion.promote_completion_audit_runtime_evidence(
                runtime_dir,
                bundle_report_path,
                plan_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
                out_dir=out_dir,
                repo_root=root,
            )
            payload = report.to_dict()
            copied_report_exists = Path(
                payload["artifacts"]["runtime_evidence_bundle_report"]
            ).is_file()
            handle_evidence_exists = Path(
                payload["artifacts"]["setup_handle_evidence"]
            ).exists()

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["promotion_ready"])
        self.assertEqual(0, payload["setup_handle_count"])
        self.assertEqual(
            {
                "completion_audit_runtime_evidence_promotion_bundle_not_ok",
                "completion_audit_runtime_evidence_promotion_bundle_not_ready",
            },
            set(payload["error_codes"]),
        )
        self.assertTrue(copied_report_exists)
        self.assertFalse(handle_evidence_exists)

    def test_cli_writes_promotion_report_for_pending_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            runtime_dir = root / "runtime-evidence"
            runtime_dir.mkdir()
            bundle_report_path = root / "runtime-evidence-bundle-report.json"
            out_dir = root / "promotion"
            out_path = root / "promotion-report.json"
            report_payload = _bundle_report_for_artifacts({})
            report_payload["ok"] = False
            report_payload["completion_audit_ready"] = False
            _write_json(bundle_report_path, report_payload)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = promotion.main(
                    [
                        str(runtime_dir),
                        "--runtime-evidence-bundle-report",
                        str(bundle_report_path),
                        "--setup-handle-plan",
                        str(plan_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--out-dir",
                        str(out_dir),
                        "--out",
                        str(out_path),
                    ]
                )
            payload = _load_json(out_path)

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["promotion_ready"])


if __name__ == "__main__":
    unittest.main()
