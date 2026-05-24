import json
from pathlib import Path
import tempfile
import unittest

import run_wiii_self_harness as harness


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


class WiiiSelfHarnessTests(unittest.TestCase):
    def test_default_manifest_validates_against_repository(self) -> None:
        data = harness.load_manifest(harness.DEFAULT_MANIFEST)

        result = harness.validate_manifest(data)

        self.assertEqual([], result.errors)
        self.assertGreaterEqual(result.scenario_count, 5)
        self.assertGreater(result.evidence_count, 0)

    def test_valid_manifest_passes_with_temp_repo_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            evidence_file = repo_root / "src" / "contract.txt"
            evidence_file.parent.mkdir(parents=True)
            evidence_file.write_text("needle", encoding="utf-8")

            result = harness.validate_manifest(
                _sample_manifest(),
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertTrue(result.ok)
        self.assertEqual([], result.errors)

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
            evidence_file = repo_root / "src" / "contract.txt"
            evidence_file.parent.mkdir(parents=True)
            evidence_file.write_text("wrong content", encoding="utf-8")

            result = harness.validate_manifest(
                _sample_manifest(),
                repo_root=repo_root,
                manifest_path=repo_root / "manifest.json",
                enforce_default_scenarios=False,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("token 'needle' missing" in error for error in result.errors), result.errors)

    def test_cli_json_shape_uses_result_contract(self) -> None:
        data = json.loads(json.dumps(harness.validate_manifest(_sample_manifest(), enforce_default_scenarios=False).to_dict()))

        self.assertIn("ok", data)
        self.assertIn("errors", data)
        self.assertEqual(harness.HARNESS_NAME, data["harness"])


if __name__ == "__main__":
    unittest.main()
