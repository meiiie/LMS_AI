import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import apply_completion_audit_setup_state as setup_applier
import generate_completion_audit_dispatch_gate as gate_generator
import generate_completion_audit_setup_attestation_from_handles as generator
import generate_completion_audit_setup_handle_plan as plan_generator
from test_apply_completion_audit_setup_state import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import validate_completion_audit_setup_attestation as attestation_validator


def _handle_evidence_from_plan(plan_path: Path, plan_payload: dict) -> dict:
    handles = []
    for item in plan_payload["plan_items"]:
        for check in item["setup_checks"]:
            if check["present"]:
                continue
            source_handle = check["binding_tokens"][0]
            evidence_kind = check["recommended_evidence_kinds"][0]
            handles.append(
                {
                    "requirement_id": item["requirement_id"],
                    "category": check["category"],
                    "key": check["key"],
                    "source_handle": source_handle,
                    "evidence_kind": evidence_kind,
                    "evidence_ref": f"{evidence_kind}:{source_handle}",
                }
            )
    return {
        "schema_version": generator.SETUP_HANDLE_EVIDENCE_SCHEMA_VERSION,
        "ok": True,
        "setup_handle_plan_sha256": generator.attestation_generator._sha256_file(
            plan_path
        ),
        "setup_handle_plan_schema_version": plan_payload["schema_version"],
        "setup_handle_plan_fingerprint_sha256": plan_payload[
            "setup_handle_plan_fingerprint_sha256"
        ],
        "setup_state_sha256": plan_payload["setup_state_sha256"],
        "setup_state_schema_version": plan_payload["setup_state_schema_version"],
        "setup_state_fingerprint_sha256": plan_payload[
            "setup_state_fingerprint_sha256"
        ],
        "handle_count": len(handles),
        "handles": handles,
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        },
        "errors": [],
        "error_codes": [],
        "error_code_counts": {},
    }


def _write_plan(root: Path) -> tuple[Path, Path, Path]:
    launch_pack_path, setup_state_path = _write_setup_state(root)
    plan_path = root / "setup-handle-plan.json"
    plan = plan_generator.generate_completion_audit_setup_handle_plan(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    _write_json(plan_path, plan.to_dict())
    return launch_pack_path, setup_state_path, plan_path


class GenerateCompletionAuditSetupAttestationFromHandlesTests(unittest.TestCase):
    def test_handle_evidence_generates_attestation_patch_and_unlocks_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            plan_payload = _load_json(plan_path)
            evidence_path = root / "setup-handle-evidence.json"
            attestation_path = root / "setup-attestation.json"
            patch_path = root / "setup-handle-patch.json"
            applied_path = root / "setup-state-applied.json"
            _write_json(evidence_path, _handle_evidence_from_plan(plan_path, plan_payload))

            attestation = generator.generate_completion_audit_setup_attestation_from_handles(
                plan_path,
                evidence_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )
            _write_json(attestation_path, attestation)
            patch = generator.setup_handle_patch_from_attestation(attestation)
            _write_json(patch_path, patch)
            validation = attestation_validator.validate_setup_attestation(
                attestation_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
                patch_path=patch_path,
            )
            applied = setup_applier.apply_completion_audit_setup_state(
                setup_state_path,
                patch_path,
                launch_pack_path=launch_pack_path,
            )
            _write_json(applied_path, applied)
            gate = gate_generator.generate_completion_audit_dispatch_gate(
                launch_pack_path,
                applied_path,
            ).to_dict()

        self.assertTrue(validation.ok, validation.to_dict())
        self.assertEqual(plan_payload["pending_setup_check_count"], attestation["attestation_count"])
        self.assertTrue(applied["dispatch_ready"], applied)
        self.assertTrue(gate["dispatch_ready"], gate)
        rendered = json.dumps(attestation, sort_keys=True)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_cli_writes_attestation_and_patch_from_handle_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            evidence_path = root / "setup-handle-evidence.json"
            attestation_path = root / "setup-attestation.json"
            patch_path = root / "setup-handle-patch.json"
            _write_json(
                evidence_path,
                _handle_evidence_from_plan(plan_path, _load_json(plan_path)),
            )

            exit_code = generator.main(
                [
                    str(plan_path),
                    str(evidence_path),
                    "--setup-state",
                    str(setup_state_path),
                    "--launch-pack",
                    str(launch_pack_path),
                    "--out",
                    str(attestation_path),
                    "--patch-out",
                    str(patch_path),
                ]
            )
            attestation = _load_json(attestation_path)
            patch = _load_json(patch_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(attestation["attestation_count"], len(patch["checks"]))

    def test_cli_rejects_stale_handle_evidence_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            evidence = _handle_evidence_from_plan(plan_path, _load_json(plan_path))
            evidence["setup_handle_plan_sha256"] = "0" * 64
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(evidence_path, evidence)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        str(plan_path),
                        str(evidence_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--launch-pack",
                        str(launch_pack_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_handle_evidence_source_mismatch"],
            payload["error_codes"],
        )

    def test_cli_rejects_raw_evidence_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            evidence = _handle_evidence_from_plan(plan_path, _load_json(plan_path))
            evidence["handles"][0]["evidence_ref"] = "<raw-recipient-id>"
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(evidence_path, evidence)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        str(plan_path),
                        str(evidence_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--launch-pack",
                        str(launch_pack_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_handle_evidence_unsafe_token"],
            payload["error_codes"],
        )

    def test_cli_rejects_unbound_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            evidence = _handle_evidence_from_plan(plan_path, _load_json(plan_path))
            evidence["handles"][0]["source_handle"] = "UNBOUND_HANDLE"
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(evidence_path, evidence)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        str(plan_path),
                        str(evidence_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--launch-pack",
                        str(launch_pack_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_handle_evidence_unbound_handle"],
            payload["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
