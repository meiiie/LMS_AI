import json
from pathlib import Path
import shutil
import tempfile
import unittest

from test_generate_completion_audit_recovery_checkpoint import _write_control_chain
from test_generate_completion_audit_recovery_plan import _write_json
import generate_completion_audit_recovery_checkpoint as generator
import validate_completion_audit_recovery_checkpoint as validator


def _write_checkpoint(
    root: Path,
    *,
    setup_ready: bool = False,
    dispatch_gate: bool = False,
) -> tuple[Path, Path]:
    control_chain_path, _paths = _write_control_chain(
        root,
        setup_ready=setup_ready,
        dispatch_gate=dispatch_gate,
    )
    checkpoint = generator.generate_completion_audit_recovery_checkpoint(
        control_chain_path,
        repo_root=root,
    )
    checkpoint_path = root / "checkpoint.json"
    _write_json(checkpoint_path, checkpoint.to_dict())
    return checkpoint_path, control_chain_path


class ValidateCompletionAuditRecoveryCheckpointTests(unittest.TestCase):
    def test_valid_checkpoint_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path, control_chain_path = _write_checkpoint(root)

            result = validator.validate_recovery_checkpoint(
                checkpoint_path,
                recovery_control_chain_path=control_chain_path,
                repo_root=root,
            )
            payload = result.to_dict()

        self.assertTrue(result.ok, payload)
        self.assertEqual(
            validator.RECOVERY_CHECKPOINT_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual("collect_operator_setup", payload["resume_state"])
        self.assertTrue(payload["operator_setup_required"])

    def test_ready_checkpoint_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path, control_chain_path = _write_checkpoint(
                root,
                setup_ready=True,
                dispatch_gate=True,
            )

            payload = validator.validate_recovery_checkpoint(
                checkpoint_path,
                recovery_control_chain_path=control_chain_path,
                repo_root=root,
            ).to_dict()

        self.assertTrue(payload["ok"], payload)
        self.assertEqual("dispatch_recovery", payload["resume_state"])
        self.assertFalse(payload["operator_setup_required"])

    def test_checkpoint_fingerprint_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path, control_chain_path = _write_checkpoint(root)
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            payload["required_resume_inputs"] = ["valid_recovery_control_chain"]
            _write_json(checkpoint_path, payload)

            result = validator.validate_recovery_checkpoint(
                checkpoint_path,
                recovery_control_chain_path=control_chain_path,
                repo_root=root,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_checkpoint_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_control_chain_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path, control_chain_path = _write_checkpoint(root)
            payload = json.loads(control_chain_path.read_text(encoding="utf-8"))
            payload["chain_state"] = "release_ready"
            _write_json(control_chain_path, payload)

            result = validator.validate_recovery_checkpoint(
                checkpoint_path,
                recovery_control_chain_path=control_chain_path,
                repo_root=root,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_checkpoint_source_invalid",
            result.to_dict()["error_codes"],
        )
        self.assertIn(
            "completion_audit_recovery_checkpoint_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_supplied_control_chain_path_must_match_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path, _control_chain_path = _write_checkpoint(root)
            other_control_chain_path, _paths = _write_control_chain(
                root / "other",
                setup_ready=False,
            )

            result = validator.validate_recovery_checkpoint(
                checkpoint_path,
                recovery_control_chain_path=other_control_chain_path,
                repo_root=root,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_checkpoint_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_supplied_relocated_control_chain_with_same_bytes_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path, control_chain_path = _write_checkpoint(root)
            relocated_path = root / "downloaded" / "recovery-control-chain.json"
            relocated_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(control_chain_path, relocated_path)

            result = validator.validate_recovery_checkpoint(
                checkpoint_path,
                recovery_control_chain_path=relocated_path,
                repo_root=root,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_cli_json_writes_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path, control_chain_path = _write_checkpoint(root)
            out_path = root / "checkpoint-validation.json"

            exit_code = validator.main(
                [
                    str(checkpoint_path),
                    "--recovery-control-chain",
                    str(control_chain_path),
                    "--repo-root",
                    str(root),
                    "--json",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual("collect_operator_setup", payload["resume_state"])


if __name__ == "__main__":
    unittest.main()
