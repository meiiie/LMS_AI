from pathlib import Path
import re
import tempfile
import unittest

import strict_json


SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_JSON_READER_MODULES = (
    "run_wiii_self_harness.py",
    "validate_runtime_evidence_registry.py",
    "validate_runtime_evidence_artifact.py",
    "validate_runtime_evidence_bundle.py",
    "validate_self_harness_report_bundle.py",
    "report_runtime_evidence_coverage.py",
)


class StrictJsonTests(unittest.TestCase):
    def test_loads_strict_json_rejects_non_finite_numbers(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-finite JSON number"):
            strict_json.loads_strict_json('{"value": NaN}')

    def test_loads_strict_json_rejects_duplicate_object_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
            strict_json.loads_strict_json('{"value": 1, "value": 2}')

    def test_load_strict_json_file_returns_regular_json_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "payload.json"
            path.write_text('{"value": 1, "items": ["a", "b"]}', encoding="utf-8")

            payload = strict_json.load_strict_json_file(path)

        self.assertEqual({"value": 1, "items": ["a", "b"]}, payload)

    def test_runtime_json_readers_do_not_bypass_strict_json(self) -> None:
        direct_json_parse = re.compile(r"\bjson\.loads?\s*\(")

        for file_name in RUNTIME_JSON_READER_MODULES:
            with self.subTest(file_name=file_name):
                text = (SCRIPT_DIR / file_name).read_text(encoding="utf-8")
                self.assertIsNone(direct_json_parse.search(text), file_name)


if __name__ == "__main__":
    unittest.main()
