import contextlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

import run_wiii_self_harness as harness


SELF_HARNESS_WORKFLOW_PATH = harness.REPO_ROOT / ".github" / "workflows" / "wiii-self-harness.yml"
PINNED_ACTION_REF_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_SELF_HARNESS_ACTIONS = {
    "actions/checkout",
    "actions/setup-python",
    "actions/upload-artifact",
}
EXPECTED_SELF_HARNESS_CONCURRENCY_GROUP = (
    "${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}"
)
EXPECTED_SELF_HARNESS_CANCEL_IN_PROGRESS = (
    "${{ github.event_name == 'pull_request' }}"
)
SELF_HARNESS_RUNTIME_EVIDENCE_OUTPUT_PATHS = (
    "maritime-ai-service/scripts/runtime_evidence_output.py",
    "maritime-ai-service/tests/unit/test_runtime_evidence_output.py",
    "wiii-desktop/scripts/runtime-evidence-output.mjs",
    "wiii-desktop/scripts/test-runtime-evidence-output.mjs",
)


def _workflow_event_paths(workflow_text: str, event_name: str) -> set[str]:
    match = re.search(
        rf"(?ms)^  {re.escape(event_name)}:\n(?P<block>.*?)(?=^  [A-Za-z_][A-Za-z0-9_]*:\n|^permissions:\n)",
        workflow_text,
    )
    block = match.group("block") if match else ""
    return set(re.findall(r"(?m)^\s+-\s+['\"]([^'\"]+)['\"]\s*$", block))


def _sample_manifest() -> dict:
    return {
        "harness": harness.HARNESS_NAME,
        "version": 1,
        "description": "Test manifest",
        "required_scenarios": ["sample-scenario"],
        "scenarios": [
            {
                "id": "sample-scenario",
                "title": "Sample scenario",
                "status": "active",
                "layer": "Wiii Core",
                "risk": "low",
                "owner": "Tests",
                "active_product_path": True,
                "contract": "Sample contract",
                "invariants": ["A sample invariant exists."],
                "evidence": [
                    {
                        "kind": "runtime",
                        "path": "src/contract.txt",
                        "must_contain": ["needle"],
                    },
                    {
                        "kind": "test",
                        "path": "tests/test_contract.py",
                        "must_contain": ["test_sample_contract"],
                    }
                ],
                "verification": [
                    {
                        "command": "python -m unittest",
                        "purpose": "Exercise the sample contract.",
                    }
                ],
            }
        ],
    }


def _write_sample_evidence(repo_root: Path, text: str = "needle") -> None:
    evidence_file = repo_root / "src" / "contract.txt"
    evidence_file.parent.mkdir(parents=True)
    evidence_file.write_text(text, encoding="utf-8")
    test_file = repo_root / "tests" / "test_contract.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_sample_contract():\n    assert True\n"
        if text == "needle"
        else text,
        encoding="utf-8",
    )


class WiiiSelfHarnessTests(unittest.TestCase):
    def test_default_manifest_validates_against_repository(self) -> None:
        data = harness.load_manifest(harness.DEFAULT_MANIFEST)

        result = harness.validate_manifest(data)

        self.assertEqual([], result.errors)
        self.assertGreaterEqual(result.scenario_count, 5)
        self.assertGreater(result.evidence_count, 0)
        self.assertEqual(
            harness.HARNESS_VALIDATION_SCHEMA_VERSION,
            result.validation_schema_version,
        )
        self.assertEqual(1, result.manifest_version)
        self.assertRegex(result.manifest_fingerprint_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual([], result.to_dict()["error_codes"])
        self.assertEqual({}, result.to_dict()["error_code_counts"])

    def test_self_harness_workflow_has_bounded_timeout(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^  self-harness:\n(?P<block>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
            workflow_text,
        )

        self.assertIsNotNone(match)
        job_block = match.group("block") if match else ""
        timeout_match = re.search(
            r"(?m)^    timeout-minutes:\s*([0-9]+)\s*$",
            job_block,
        )

        self.assertIsNotNone(timeout_match)
        timeout_minutes = int(timeout_match.group(1)) if timeout_match else 0
        self.assertGreaterEqual(timeout_minutes, 1)
        self.assertLessEqual(timeout_minutes, 120)

    def test_self_harness_workflow_uses_only_pinned_allowed_actions(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")
        uses_specs = re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*([^#\s]+)\s*$", workflow_text)

        self.assertGreater(len(uses_specs), 0)
        for spec in uses_specs:
            with self.subTest(spec=spec):
                self.assertIn("@", spec)
                action, ref = spec.rsplit("@", 1)
                self.assertIn(action, ALLOWED_SELF_HARNESS_ACTIONS)
                self.assertRegex(ref, PINNED_ACTION_REF_RE)

    def test_self_harness_workflow_permissions_stay_read_only(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertEqual(1, len(re.findall(r"(?m)^permissions:\s*$", workflow_text)))
        self.assertIsNone(re.search(r"(?m)^[ \t]+permissions:\s*$", workflow_text))
        self.assertRegex(
            workflow_text,
            r"(?m)^permissions:\s*\n  contents:\s*read\s*$",
        )
        self.assertNotRegex(workflow_text, r"(?m)^\s+[A-Za-z-]+:\s*write\s*$")
        self.assertNotIn("read-all", workflow_text)
        self.assertNotIn("write-all", workflow_text)

    def test_self_harness_workflow_concurrency_stays_pull_request_scoped(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertEqual(1, len(re.findall(r"(?m)^concurrency:\s*$", workflow_text)))
        self.assertIsNone(re.search(r"(?m)^[ \t]+concurrency:\s*$", workflow_text))
        self.assertIn(
            f"  group: {EXPECTED_SELF_HARNESS_CONCURRENCY_GROUP}",
            workflow_text,
        )
        self.assertIn(
            f"  cancel-in-progress: {EXPECTED_SELF_HARNESS_CANCEL_IN_PROGRESS}",
            workflow_text,
        )

    def test_self_harness_workflow_paths_cover_runtime_evidence_output_helpers(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")

        for event_name in ("push", "pull_request"):
            paths = _workflow_event_paths(workflow_text, event_name)
            with self.subTest(event=event_name):
                self.assertTrue(paths)
            for path in SELF_HARNESS_RUNTIME_EVIDENCE_OUTPUT_PATHS:
                with self.subTest(event=event_name, path=path):
                    self.assertIn(path, paths)

    def test_self_harness_workflow_generates_json_reports_without_shell_redirect(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "python tools/wiii_self_harness/generate_self_harness_report_bundle.py "
            "--out-dir artifacts/wiii-self-harness",
            workflow_text,
        )
        self.assertIn(
            "python tools/wiii_self_harness/run_wiii_self_harness.py --json "
            "--out artifacts/wiii-self-harness-validation.json",
            workflow_text,
        )
        self.assertIn(
            "python tools/wiii_self_harness/validate_runtime_evidence_registry.py --json "
            "--out artifacts/wiii-runtime-evidence-registry-validation.json",
            workflow_text,
        )
        self.assertIn(
            "python tools/wiii_self_harness/validate_self_harness_sidecar_parity.py "
            "--bundle-root artifacts/wiii-self-harness "
            "--self-harness-sidecar artifacts/wiii-self-harness-validation.json "
            "--registry-sidecar artifacts/wiii-runtime-evidence-registry-validation.json "
            "--json --out artifacts/wiii-self-harness-sidecar-parity-validation.json",
            workflow_text,
        )
        self.assertNotIn("set +e", workflow_text)
        self.assertNotIn("|| true", workflow_text)
        self.assertNotIn("mv artifacts/self-harness-report-bundle-validation.json", workflow_text)
        self.assertNotRegex(
            workflow_text,
            r"run_wiii_self_harness\.py\s+--json\s*>",
        )
        self.assertNotRegex(
            workflow_text,
            r"validate_runtime_evidence_registry\.py\s+--json\s*>",
        )

    def test_self_harness_workflow_writes_contract_sidecars_before_completion_audit(
        self,
    ) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")

        bundle_validation_index = workflow_text.index("Validate self-harness report bundle")
        manifest_sidecar_index = workflow_text.index("Validate scenario manifest")
        registry_sidecar_index = workflow_text.index("Validate runtime evidence registry")
        parity_index = workflow_text.index("Validate self-harness sidecar parity")
        smoke_index = workflow_text.index("Smoke completion audit handoff")

        self.assertLess(bundle_validation_index, manifest_sidecar_index)
        self.assertLess(manifest_sidecar_index, smoke_index)
        self.assertLess(registry_sidecar_index, smoke_index)
        self.assertLess(registry_sidecar_index, parity_index)
        self.assertLess(parity_index, smoke_index)

    def test_self_harness_workflow_smokes_completion_audit_handoff(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("Validate self-harness report bundle", workflow_text)
        self.assertIn("validate_self_harness_report_bundle.py", workflow_text)
        self.assertIn("--require-self-validation", workflow_text)
        self.assertIn("--require-no-synthetic-gaps", workflow_text)
        self.assertIn("--require-credentialed-external-contracts", workflow_text)
        self.assertIn(
            "artifacts/wiii-self-harness-report-bundle-validation.json",
            workflow_text,
        )
        self.assertIn("Smoke completion audit handoff", workflow_text)
        self.assertIn("smoke_completion_audit_handoff.py", workflow_text)
        self.assertIn("artifacts/runtime-evidence-empty", workflow_text)
        self.assertIn("artifacts/wiii-completion-audit-smoke", workflow_text)
        self.assertIn("artifacts/wiii-completion-audit-smoke.json", workflow_text)
        self.assertIn("--self-harness-report-bundle", workflow_text)
        self.assertIn("artifacts/wiii-self-harness", workflow_text)
        self.assertIn("--artifact-bundle-root", workflow_text)
        self.assertIn("--json-out", workflow_text)
        self.assertIn("Validate completion audit handoff smoke bundle", workflow_text)
        self.assertIn("validate_completion_audit_handoff.py", workflow_text)
        self.assertIn(
            "artifacts/wiii-completion-audit-smoke-validation.json",
            workflow_text,
        )
        self.assertIn("Validate completion audit smoke sidecars", workflow_text)
        self.assertIn("validate_completion_audit_smoke.py", workflow_text)
        self.assertIn("--release-gate-json", workflow_text)
        self.assertIn("--structural-validation-json", workflow_text)
        self.assertIn("Report non-LMS completion audit readiness", workflow_text)
        self.assertIn("report_completion_audit_readiness.py", workflow_text)
        self.assertIn("--exclude-requirement-id lms-test-course-replay", workflow_text)
        self.assertIn("READINESS_AS_OF=", workflow_text)
        self.assertIn('--as-of "$READINESS_AS_OF" --format json', workflow_text)
        self.assertIn('--as-of "$READINESS_AS_OF" --format markdown', workflow_text)
        self.assertIn(
            "artifacts/wiii-completion-audit-readiness-non-lms.json",
            workflow_text,
        )
        self.assertIn("Validate non-LMS completion audit readiness report", workflow_text)
        self.assertIn("validate_completion_audit_readiness.py", workflow_text)
        self.assertIn("Generate non-LMS completion audit setup state", workflow_text)
        self.assertIn("generate_completion_audit_setup_state.py", workflow_text)
        self.assertIn(
            "artifacts/wiii-completion-audit-setup-state-non-lms.json",
            workflow_text,
        )
        self.assertIn("Validate non-LMS completion audit setup state", workflow_text)
        self.assertIn("validate_completion_audit_setup_state.py", workflow_text)
        self.assertIn("--launch-pack", workflow_text)
        self.assertIn(
            "Generate non-LMS completion audit setup attestation template",
            workflow_text,
        )
        self.assertIn(
            "generate_completion_audit_setup_attestation_template.py",
            workflow_text,
        )
        self.assertIn(
            "artifacts/wiii-completion-audit-setup-attestation-template-non-lms.json",
            workflow_text,
        )
        self.assertIn(
            "Validate non-LMS completion audit setup attestation template",
            workflow_text,
        )
        self.assertIn(
            "validate_completion_audit_setup_attestation_template.py",
            workflow_text,
        )
        self.assertIn(
            "Smoke non-LMS completion audit setup attestation path",
            workflow_text,
        )
        self.assertIn("smoke_completion_audit_setup_attestation.py", workflow_text)
        self.assertIn(
            "artifacts/wiii-completion-audit-setup-attestation-smoke",
            workflow_text,
        )
        self.assertIn(
            "artifacts/wiii-completion-audit-setup-attestation-smoke.json",
            workflow_text,
        )
        self.assertIn("--template", workflow_text)
        self.assertIn(
            "Validate non-LMS completion audit setup attestation smoke",
            workflow_text,
        )
        self.assertIn(
            "validate_completion_audit_setup_attestation_smoke.py",
            workflow_text,
        )
        self.assertIn("Generate non-LMS completion audit dispatch gate", workflow_text)
        self.assertIn("generate_completion_audit_dispatch_gate.py", workflow_text)
        self.assertIn(
            "artifacts/wiii-completion-audit-dispatch-gate-non-lms.json",
            workflow_text,
        )
        self.assertIn("Validate non-LMS completion audit dispatch gate", workflow_text)
        self.assertIn("validate_completion_audit_dispatch_gate.py", workflow_text)
        self.assertIn("--setup-state", workflow_text)
        for token in (
            "--json --out artifacts/wiii-completion-audit-smoke-sidecars-validation.json",
            "--json --out artifacts/wiii-completion-audit-readiness-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-run-plan-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-launch-pack-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-setup-state-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-setup-handle-plan-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-setup-gaps-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-setup-attestation-template-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-setup-attestation-smoke-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-dispatch-gate-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-dispatch-run-validation-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-dispatch-diagnostics-validation-non-lms.json",
        ):
            with self.subTest(token=token):
                self.assertIn(token, workflow_text)
        for token in (
            "Generate non-LMS completion audit handoff for recovery",
            "generate_completion_audit_handoff.py",
            "--out-dir artifacts/wiii-completion-audit-handoff-non-lms --allow-not-ready",
            "Validate non-LMS completion audit handoff for recovery",
            "--json --out artifacts/wiii-completion-audit-handoff-validation-non-lms.json",
            "Generate non-LMS completion audit recovery plan",
            "generate_completion_audit_recovery_plan.py",
            "artifacts/wiii-completion-audit-recovery-plan-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-plan-non-lms.md",
            "--json --out artifacts/wiii-completion-audit-recovery-plan-validation-non-lms.json",
            "Materialize non-LMS completion audit recovery queue",
            "run_completion_audit_recovery_queue.py",
            "--json --out artifacts/wiii-completion-audit-recovery-queue-validation-non-lms.json",
            "Generate non-LMS completion audit recovery work order",
            "generate_completion_audit_recovery_work_order.py",
            "--json --out artifacts/wiii-completion-audit-recovery-work-order-validation-non-lms.json",
            "Report non-LMS completion audit recovery work-order status",
            "report_completion_audit_recovery_work_order_status.py",
            "--json --out artifacts/wiii-completion-audit-recovery-work-order-status-validation-non-lms.json",
            "Generate non-LMS completion audit recovery queue progress",
            "generate_completion_audit_recovery_queue_progress.py",
            "--json --out artifacts/wiii-completion-audit-recovery-queue-progress-validation-non-lms.json",
            "Generate non-LMS completion audit recovery dispatch authorization",
            "generate_completion_audit_recovery_dispatch_authorization.py",
            "--json --out artifacts/wiii-completion-audit-recovery-dispatch-authorization-validation-non-lms.json",
            "Materialize non-LMS completion audit recovery dispatch run",
            "run_completion_audit_recovery_dispatch_authorization.py",
            "--allow-blocked-report",
            "--json --out artifacts/wiii-completion-audit-recovery-dispatch-run-validation-non-lms.json",
            "Validate non-LMS completion audit recovery control chain",
            "validate_completion_audit_recovery_control_chain.py",
            "Generate non-LMS completion audit recovery checkpoint",
            "generate_completion_audit_recovery_checkpoint.py",
            "artifacts/wiii-completion-audit-recovery-checkpoint-non-lms.json",
            "Validate non-LMS completion audit recovery checkpoint",
            "validate_completion_audit_recovery_checkpoint.py",
            "artifacts/wiii-completion-audit-recovery-checkpoint-validation-non-lms.json",
            "--recovery-control-chain artifacts/wiii-completion-audit-recovery-control-chain-non-lms.json",
            "--recovery-checkpoint artifacts/wiii-completion-audit-recovery-checkpoint-non-lms.json",
            "--json --out artifacts/wiii-completion-audit-control-chain-non-lms.json",
        ):
            with self.subTest(token=token):
                self.assertIn(token, workflow_text)

    def test_self_harness_workflow_renders_strict_runtime_evidence_coverage(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("Render runtime evidence coverage", workflow_text)
        self.assertIn(
            "python tools/wiii_self_harness/report_runtime_evidence_coverage.py "
            "--format markdown --require-no-synthetic-gaps "
            "--require-credentialed-external-contracts",
            workflow_text,
        )

    def test_self_harness_workflow_uploads_artifacts_after_all_gates(self) -> None:
        workflow_text = SELF_HARNESS_WORKFLOW_PATH.read_text(encoding="utf-8")
        upload_index = workflow_text.index("Upload self-harness report artifacts")

        for earlier_step in (
            "Generate self-harness report artifacts",
            "Validate self-harness report bundle",
            "Validate scenario manifest",
            "Validate runtime evidence registry",
            "Validate self-harness sidecar parity",
            "Smoke completion audit handoff",
            "Validate completion audit handoff smoke bundle",
            "Validate completion audit smoke sidecars",
            "Report non-LMS completion audit readiness",
            "Validate non-LMS completion audit readiness report",
            "Generate non-LMS completion audit run plan",
            "Validate non-LMS completion audit run plan",
            "Generate non-LMS completion audit launch pack",
            "Validate non-LMS completion audit launch pack",
            "Generate non-LMS completion audit setup state",
            "Validate non-LMS completion audit setup state",
            "Generate non-LMS completion audit setup handle plan",
            "Validate non-LMS completion audit setup handle plan",
            "Report non-LMS completion audit setup gaps",
            "Validate non-LMS completion audit setup gaps",
            "Generate non-LMS completion audit setup attestation template",
            "Validate non-LMS completion audit setup attestation template",
            "Smoke non-LMS completion audit setup attestation path",
            "Validate non-LMS completion audit setup attestation smoke",
            "Generate non-LMS completion audit dispatch gate",
            "Validate non-LMS completion audit dispatch gate",
            "Materialize non-LMS completion audit dispatch run",
            "Validate non-LMS completion audit dispatch run",
            "Materialize non-LMS completion audit dispatch diagnostics",
            "Validate non-LMS completion audit dispatch diagnostics",
            "Generate non-LMS completion audit handoff for recovery",
            "Validate non-LMS completion audit handoff for recovery",
            "Generate non-LMS completion audit recovery plan",
            "Validate non-LMS completion audit recovery plan",
            "Materialize non-LMS completion audit recovery queue",
            "Validate non-LMS completion audit recovery queue",
            "Generate non-LMS completion audit recovery work order",
            "Validate non-LMS completion audit recovery work order",
            "Report non-LMS completion audit recovery work-order status",
            "Validate non-LMS completion audit recovery work-order status",
            "Generate non-LMS completion audit recovery queue progress",
            "Validate non-LMS completion audit recovery queue progress",
            "Generate non-LMS completion audit recovery dispatch authorization",
            "Validate non-LMS completion audit recovery dispatch authorization",
            "Materialize non-LMS completion audit recovery dispatch run",
            "Validate non-LMS completion audit recovery dispatch run",
            "Validate non-LMS completion audit recovery control chain",
            "Generate non-LMS completion audit recovery checkpoint",
            "Validate non-LMS completion audit recovery checkpoint",
            "Render runtime evidence coverage",
            "Run harness unit tests",
            "Run Understand-Anything wrapper unit tests",
        ):
            with self.subTest(earlier_step=earlier_step):
                self.assertLess(workflow_text.index(earlier_step), upload_index)
        upload_block = workflow_text[upload_index:]
        self.assertIn("if: always()", upload_block)
        self.assertIn("if-no-files-found: error", upload_block)
        self.assertIn(
            "artifacts/wiii-completion-audit-readiness-non-lms.json",
            upload_block,
        )
        self.assertIn(
            "artifacts/wiii-completion-audit-setup-state-non-lms.json",
            upload_block,
        )
        self.assertIn(
            "artifacts/wiii-completion-audit-setup-attestation-template-non-lms.json",
            upload_block,
        )
        self.assertIn(
            "artifacts/wiii-completion-audit-setup-attestation-smoke/",
            upload_block,
        )
        self.assertIn(
            "artifacts/wiii-completion-audit-setup-attestation-smoke.json",
            upload_block,
        )
        self.assertIn(
            "artifacts/wiii-completion-audit-dispatch-gate-non-lms.json",
            upload_block,
        )
        for artifact_path in (
            "artifacts/wiii-self-harness-validation.json",
            "artifacts/wiii-runtime-evidence-registry-validation.json",
            "artifacts/wiii-self-harness-sidecar-parity-validation.json",
            "artifacts/wiii-completion-audit-smoke-sidecars-validation.json",
            "artifacts/wiii-completion-audit-readiness-validation-non-lms.json",
            "artifacts/wiii-completion-audit-run-plan-validation-non-lms.json",
            "artifacts/wiii-completion-audit-launch-pack-validation-non-lms.json",
            "artifacts/wiii-completion-audit-setup-state-validation-non-lms.json",
            "artifacts/wiii-completion-audit-setup-handle-plan-validation-non-lms.json",
            "artifacts/wiii-completion-audit-setup-gaps-validation-non-lms.json",
            "artifacts/wiii-completion-audit-setup-attestation-template-validation-non-lms.json",
            "artifacts/wiii-completion-audit-setup-attestation-smoke-validation-non-lms.json",
            "artifacts/wiii-completion-audit-dispatch-gate-validation-non-lms.json",
            "artifacts/wiii-completion-audit-dispatch-run-validation-non-lms.json",
            "artifacts/wiii-completion-audit-dispatch-diagnostics-validation-non-lms.json",
            "artifacts/wiii-completion-audit-handoff-non-lms/",
            "artifacts/wiii-completion-audit-handoff-validation-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-plan-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-plan-non-lms.md",
            "artifacts/wiii-completion-audit-recovery-plan-validation-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-queue-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-queue-validation-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-work-order-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-work-order-validation-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-work-order-status-validation-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-queue-progress-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-queue-progress-validation-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-dispatch-authorization-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-dispatch-authorization-validation-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-dispatch-run-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-dispatch-run-validation-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-control-chain-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-checkpoint-non-lms.json",
            "artifacts/wiii-completion-audit-recovery-checkpoint-validation-non-lms.json",
            "artifacts/wiii-completion-audit-control-chain-non-lms.json",
        ):
            with self.subTest(artifact_path=artifact_path):
                self.assertIn(artifact_path, upload_block)

    def test_completion_audit_validators_support_safe_json_out_sidecars(self) -> None:
        validator_paths = sorted(
            (harness.REPO_ROOT / "tools" / "wiii_self_harness").glob(
                "validate_completion_audit_*.py"
            )
        )

        self.assertGreater(len(validator_paths), 10)
        for validator_path in validator_paths:
            source = validator_path.read_text(encoding="utf-8")
            with self.subTest(validator=validator_path.name):
                self.assertIn('parser.add_argument("--out"', source)
                self.assertIn("safe_write_report_text", source)
                self.assertNotIn("args.out.write_text", source)

    def test_core_report_clis_use_safe_report_output(self) -> None:
        cli_paths = [
            harness.REPO_ROOT / "tools" / "wiii_self_harness" / file_name
            for file_name in (
                "run_wiii_self_harness.py",
                "validate_runtime_evidence_registry.py",
                "validate_self_harness_sidecar_parity.py",
                "validate_runtime_evidence_bundle.py",
                "validate_self_harness_report_bundle.py",
                "report_runtime_evidence_coverage.py",
            )
        ]

        for cli_path in cli_paths:
            source = cli_path.read_text(encoding="utf-8")
            with self.subTest(cli=cli_path.name):
                self.assertIn("safe_write_report_text", source)
                self.assertNotIn("args.out.write_text", source)

    def test_completion_audit_artifact_clis_use_safe_report_output(self) -> None:
        cli_paths = sorted(
            path
            for path in (harness.REPO_ROOT / "tools" / "wiii_self_harness").glob("*.py")
            if path.name.startswith(
                (
                    "apply_completion_audit_",
                    "generate_completion_audit_",
                    "probe_completion_audit_",
                    "promote_completion_audit_",
                    "report_completion_audit_",
                    "run_completion_audit_",
                )
            )
        )

        self.assertGreater(len(cli_paths), 20)
        for cli_path in cli_paths:
            source = cli_path.read_text(encoding="utf-8")
            with self.subTest(cli=cli_path.name):
                if 'parser.add_argument("--out"' in source:
                    self.assertIn("safe_write_report_text", source)
                    self.assertNotIn("args.out.write_text", source)
                if 'parser.add_argument("--patch-out"' in source:
                    self.assertIn("safe_write_report_text", source)
                    self.assertNotIn("args.patch_out.write_text", source)
                self.assertNotIn("path.write_text(text", source)

    def test_non_test_self_harness_writes_are_centralized(self) -> None:
        source_paths = sorted(
            path
            for path in (harness.REPO_ROOT / "tools" / "wiii_self_harness").glob("*.py")
            if not path.name.startswith("test_")
            and path.name != "safe_report_output.py"
        )

        self.assertGreater(len(source_paths), 20)
        for source_path in source_paths:
            source = source_path.read_text(encoding="utf-8")
            with self.subTest(source=source_path.name):
                self.assertNotIn(".write_text(", source)

    def test_valid_manifest_passes_with_temp_repo_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                _sample_manifest(),
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertTrue(result.ok)
        self.assertEqual([], result.errors)

    def test_manifest_version_rejects_boolean(self) -> None:
        manifest = _sample_manifest()
        manifest["version"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertIsNone(result.manifest_version)
        self.assertIn("manifest_version_invalid", result.to_dict()["error_codes"])

    def test_manifest_rejects_unknown_root_fields(self) -> None:
        manifest = _sample_manifest()
        manifest["decorative_config"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("manifest: unknown field(s): decorative_config" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("manifest_unknown_field", result.to_dict()["error_codes"])

    def test_scenario_rejects_unknown_fields(self) -> None:
        manifest = _sample_manifest()
        manifest["scenarios"][0]["comment"] = "looks plausible"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unknown field(s): comment" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("scenario_unknown_field", result.to_dict()["error_codes"])

    def test_evidence_rejects_unknown_fields(self) -> None:
        manifest = _sample_manifest()
        manifest["scenarios"][0]["evidence"][0]["note"] = "operator-only"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(".evidence[0]: unknown field(s): note" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("evidence_unknown_field", result.to_dict()["error_codes"])

    def test_verification_rejects_unknown_fields(self) -> None:
        manifest = _sample_manifest()
        manifest["scenarios"][0]["verification"][0]["notes"] = "operator-only"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(".verification[0]: unknown field(s): notes" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("verification_unknown_field", result.to_dict()["error_codes"])

    def test_manifest_string_lists_must_not_duplicate_values(self) -> None:
        manifest = _sample_manifest()
        manifest["required_scenarios"].append("sample-scenario")
        manifest["scenarios"][0]["invariants"].append("A sample invariant exists.")
        manifest["scenarios"][0]["evidence"][0]["must_contain"].append("needle")
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not contain duplicate values" in error for error in result.errors),
            result.errors,
        )
        self.assertEqual(
            ["manifest_string_list_duplicate"],
            result.to_dict()["error_codes"],
        )
        self.assertEqual(
            {"manifest_string_list_duplicate": 3},
            result.to_dict()["error_code_counts"],
        )

    def test_required_scenario_ids_must_be_lowercase_kebab_case(self) -> None:
        manifest = _sample_manifest()
        manifest["required_scenarios"] = ["Sample Scenario"]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("required_scenarios id must be lowercase kebab-case" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "manifest_required_scenario_id_invalid",
            result.to_dict()["error_codes"],
        )

    def test_active_scenarios_must_be_required(self) -> None:
        manifest = _sample_manifest()
        manifest["required_scenarios"] = ["other-scenario"]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("active scenario 'sample-scenario' is missing" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "manifest_active_scenario_not_required",
            result.to_dict()["error_codes"],
        )

    def test_required_scenarios_must_be_active(self) -> None:
        manifest = _sample_manifest()
        manifest["scenarios"][0]["status"] = "deferred"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("required scenario 'sample-scenario' must be active" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "manifest_required_scenario_not_active",
            result.to_dict()["error_codes"],
        )

    def test_deferred_scenarios_do_not_have_to_be_required(self) -> None:
        manifest = _sample_manifest()
        manifest["required_scenarios"] = ["sample-scenario"]
        deferred = json.loads(json.dumps(manifest["scenarios"][0]))
        deferred["id"] = "deferred-scenario"
        deferred["status"] = "deferred"
        manifest["scenarios"].append(deferred)
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertTrue(result.ok, result.errors)

    def test_active_scenarios_require_runtime_evidence(self) -> None:
        manifest = _sample_manifest()
        manifest["scenarios"][0]["evidence"][0]["kind"] = "test"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("active scenario must include runtime evidence" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "scenario_runtime_evidence_missing",
            result.to_dict()["error_codes"],
        )

    def test_active_scenarios_require_test_evidence(self) -> None:
        manifest = _sample_manifest()
        manifest["scenarios"][0]["evidence"][1]["kind"] = "runtime"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("active scenario must include test evidence" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "scenario_test_evidence_missing",
            result.to_dict()["error_codes"],
        )

    def test_scenario_evidence_entries_must_not_duplicate_kind_and_path(self) -> None:
        manifest = _sample_manifest()
        manifest["scenarios"][0]["evidence"].append(
            json.loads(json.dumps(manifest["scenarios"][0]["evidence"][0]))
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate evidence entry for kind/path" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("scenario_evidence_duplicate", result.to_dict()["error_codes"])

    def test_scenario_evidence_entries_must_not_duplicate_normalized_paths(self) -> None:
        manifest = _sample_manifest()
        duplicate = json.loads(json.dumps(manifest["scenarios"][0]["evidence"][0]))
        duplicate["path"] = "./src//contract.txt"
        manifest["scenarios"][0]["evidence"].append(duplicate)
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root)

            result = harness.validate_manifest(
                manifest,
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate evidence entry for kind/path" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("scenario_evidence_duplicate", result.to_dict()["error_codes"])

    def test_missing_evidence_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)

            result = harness.validate_manifest(
                _sample_manifest(),
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("evidence file does not exist" in error for error in result.errors),
            result.errors,
        )

    def test_missing_evidence_token_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_evidence(repo_root, text="wrong content")

            result = harness.validate_manifest(
                _sample_manifest(),
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("token 'needle' missing" in error for error in result.errors), result.errors)
        self.assertEqual(["evidence_token_missing"], result.to_dict()["error_codes"])

    def test_manifest_fingerprint_changes_when_contract_changes(self) -> None:
        first_manifest = _sample_manifest()
        second_manifest = json.loads(json.dumps(first_manifest))
        second_manifest["scenarios"][0]["invariants"].append("A second invariant exists.")

        first_result = harness.validate_manifest(
            first_manifest,
            enforce_default_scenarios=False,
        )
        second_result = harness.validate_manifest(
            second_manifest,
            enforce_default_scenarios=False,
        )

        self.assertNotEqual(
            first_result.manifest_fingerprint_sha256,
            second_result.manifest_fingerprint_sha256,
        )

    def test_cli_json_shape_uses_result_contract(self) -> None:
        data = json.loads(
            json.dumps(
                harness.validate_manifest(
                    _sample_manifest(),
                    enforce_default_scenarios=False,
                ).to_dict()
            )
        )

        self.assertIn("ok", data)
        self.assertIn("errors", data)
        self.assertIn("error_codes", data)
        self.assertIn("error_code_counts", data)
        self.assertIn("manifest_fingerprint_sha256", data)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", data["manifest_fingerprint_sha256"]))
        self.assertEqual(harness.HARNESS_NAME, data["harness"])

    def test_cli_json_out_writes_utf8_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "self-harness-validation.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = harness.main(["--json", "--out", str(out_path)])
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(
            harness.HARNESS_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )

    def test_cli_out_rejects_manifest_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(_sample_manifest(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = harness.main(
                    [
                        "--manifest",
                        str(manifest_path),
                        "--json",
                        "--out",
                        str(manifest_path),
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["self_harness_output_path_overwrites_manifest"],
            payload["error_codes"],
        )

    def test_cli_out_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "self-harness-validation"
            out_path.mkdir()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = harness.main(["--json", "--out", str(out_path)])

            payload = json.loads(stdout.getvalue())
            out_entries = list(out_path.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["self_harness_output_path_directory"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"self_harness_output_path_directory": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], out_entries)

    def test_cli_out_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "target.json"
            target_path.write_text("keep", encoding="utf-8")
            out_path = Path(temp_dir) / "self-harness-validation.json"
            try:
                os.symlink(target_path, out_path)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = harness.main(["--json", "--out", str(out_path)])

            payload = json.loads(stdout.getvalue())
            target_text = target_path.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["self_harness_output_path_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"self_harness_output_path_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual("keep", target_text)

    def test_cli_out_rejects_parent_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir) / "target-dir"
            target_dir.mkdir()
            symlink_parent = Path(temp_dir) / "linked-parent"
            try:
                os.symlink(target_dir, symlink_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            out_path = symlink_parent / "self-harness-validation.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = harness.main(["--json", "--out", str(out_path)])

            payload = json.loads(stdout.getvalue())
            target_entries = list(target_dir.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["self_harness_output_path_parent_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"self_harness_output_path_parent_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], target_entries)

    def test_cli_json_load_error_exposes_validation_schema_and_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            missing_manifest = Path(temp_dir) / "missing-manifest.json"
            with contextlib.redirect_stdout(stdout):
                exit_code = harness.main(
                    [
                        "--manifest",
                        str(missing_manifest),
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            harness.HARNESS_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(["manifest_load_failed"], payload["error_codes"])
        self.assertEqual({"manifest_load_failed": 1}, payload["error_code_counts"])

    def test_cli_json_rejects_non_finite_manifest_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text('{"harness": NaN}', encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = harness.main(
                    [
                        "--manifest",
                        str(manifest_path),
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(["manifest_load_failed"], payload["error_codes"])
        self.assertEqual({"manifest_load_failed": 1}, payload["error_code_counts"])
        self.assertTrue(
            any("non-finite JSON number" in error for error in payload["errors"]),
            payload["errors"],
        )

    def test_cli_json_rejects_duplicate_manifest_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text(
                '{"harness": "A", "harness": "B"}',
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = harness.main(
                    [
                        "--manifest",
                        str(manifest_path),
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(["manifest_load_failed"], payload["error_codes"])
        self.assertEqual({"manifest_load_failed": 1}, payload["error_code_counts"])
        self.assertTrue(
            any("duplicate JSON object key" in error for error in payload["errors"]),
            payload["errors"],
        )


if __name__ == "__main__":
    unittest.main()
