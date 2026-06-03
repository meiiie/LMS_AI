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
import validate_runtime_evidence_registry as registry


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sample_registry() -> dict:
    return {
        "registry": registry.REGISTRY_NAME,
        "version": 1,
        "description": "Test runtime evidence registry",
        "requirements": [
            {
                "id": "sample-runtime-evidence",
                "title": "Sample runtime evidence",
                "layer": "Wiii Core",
                "workflow": ".github/workflows/sample-evidence.yml",
                "artifact": "sample-evidence.json",
                "schema_version": "wiii.sample_evidence.v1",
                "freshness": {
                    "timestamp_path": "generated_at",
                    "max_age_hours": 72,
                },
                "payload_schema_field": "schema_version",
                "forbidden_payload_tokens": [
                    "api_key",
                    "access_token",
                    "authorization",
                    "raw sample evidence leaked",
                ],
                "forbidden_payload_regexes": [],
                "payload_checks": [
                    {
                        "path": "status",
                        "equals": "pass",
                    },
                    {
                        "path": "privacy.raw_content_included",
                        "equals": False,
                    },
                    {
                        "path": "privacy.identifier_strategy",
                        "equals": "hash_or_count_only",
                    }
                ],
                "probe": "scripts/probe_sample.py",
                "contract_tests": ["tests/test_probe_sample.py"],
                "live_env_flags": ["WIII_LIVE_SAMPLE_PROBE"],
                "live_guard_tokens": ["--allow-run"],
                "dispatch_or_schedule_gate_tokens": [
                    "allow_live_sample",
                    "WIII_SAMPLE_EVIDENCE_ENABLED",
                ],
                "artifact_tokens": [
                    "sample-evidence-${{ github.run_id }}"
                ],
            }
        ],
    }


def _write_sample_repo(repo_root: Path, *, workflow_extra: str = "") -> None:
    workflow = """
name: Sample Evidence
on:
  pull_request:
    paths:
      - ".github/workflows/sample-evidence.yml"
      - "tools/wiii_self_harness/**"
      - "scripts/probe_sample.py"
      - "scripts/runtime_evidence_output.py"
      - "tests/test_probe_sample.py"
      - "tests/test_runtime_evidence_output.py"
  push:
    paths:
      - ".github/workflows/sample-evidence.yml"
      - "tools/wiii_self_harness/**"
      - "scripts/probe_sample.py"
      - "scripts/runtime_evidence_output.py"
      - "tests/test_probe_sample.py"
      - "tests/test_runtime_evidence_output.py"
  schedule:
    - cron: "15 3 * * *"
  workflow_dispatch:
    inputs:
      allow_live_sample:
        description: "Run the sample live evidence probe."
        required: true
        type: boolean
        default: false
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  contract:
    name: Sample Contract
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          persist-credentials: false
      - run: python -m pytest tests/test_probe_sample.py -q --tb=short
      - run: python -m pytest tests/test_runtime_evidence_output.py -q --tb=short
  sample:
    needs: contract
    environment: wiii-runtime-evidence
    if: >-
      ${{
        (github.event_name == 'workflow_dispatch' && inputs.allow_live_sample == true) ||
        (github.event_name == 'schedule' && vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1')
      }}
    env:
      WIII_LIVE_SAMPLE_PROBE: "1"
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          persist-credentials: false
      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json
      - run: |
          echo wiii.sample_evidence.v1
          echo WIII_LIVE_SAMPLE_PROBE
          echo allow_live_sample
          echo sample-runtime-evidence
      - run: |
          python tools/wiii_self_harness/validate_runtime_evidence_artifact.py \
            sample-evidence.json \
            --requirement-id sample-runtime-evidence
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: always()
        with:
          name: sample-evidence-${{ github.run_id }}
          path: sample-evidence.json
          if-no-files-found: error
          retention-days: 30
""" + workflow_extra
    probe = """
import argparse
SCHEMA_VERSION = "wiii.sample_evidence.v1"
ENV_FLAG = "WIII_LIVE_SAMPLE_PROBE"
ALLOW_FLAG = "--allow-run"
from runtime_evidence_output import emit_json_payload
OUT_FLAG = "--out"
def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-run", action="store_true")
    parser.add_argument("--out")
    return parser
def emit_sample(args):
    emit_json_payload({"status": "pass"}, args.out)
"""
    test = """
def test_sample_probe_contract():
    assert "wiii.sample_evidence.v1"
    assert "WIII_LIVE_SAMPLE_PROBE"
"""
    output_helper_test = """
def test_runtime_evidence_output_helper_contract():
    assert "runtime evidence output helper"
"""
    output_helper = """
import os
import tempfile

def validate_output_path(out_path):
    return None

def emit_json_payload(payload, out_path=None):
    if out_path is None:
        return None
    validate_output_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    validate_output_path(out_path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=out_path.parent,
            prefix=f".{out_path.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_path = temp_file.name
            temp_file.write("{}")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        validate_output_path(out_path)
        os.replace(temp_path, out_path)
        temp_path = None
    finally:
        if temp_path is not None:
            os.unlink(temp_path)
"""
    _write(repo_root / ".github/workflows/sample-evidence.yml", workflow)
    _write(repo_root / "scripts/probe_sample.py", probe)
    _write(repo_root / "scripts/runtime_evidence_output.py", output_helper)
    _write(repo_root / "tests/test_probe_sample.py", test)
    _write(repo_root / "tests/test_runtime_evidence_output.py", output_helper_test)


_SAMPLE_PRIMARY_UPLOAD_STEP_HEAD = (
    "      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a\n"
    "        if: always()\n"
)


def _sample_registry_with_diagnostic_upload() -> dict:
    data = _sample_registry()
    data["requirements"][0]["diagnostic_uploads"] = [
        {
            "artifact": "sample-preflight.json",
            "path": "sample-preflight.json",
            "artifact_tokens": ["sample-preflight-${{ github.run_id }}"],
            "if_no_files_found": "warn",
            "retention_days": 14,
        }
    ]
    return data


def _sample_preflight_validation_step(*, include_cleanup: bool = True) -> str:
    cleanup_line = "            rm -f sample-preflight.json\n" if include_cleanup else ""
    return (
        "      - run: |\n"
        "          preflight_validation_status=0\n"
        "          python tools/wiii_self_harness/validate_runtime_evidence_preflight.py \\\n"
        "            sample-preflight.json \\\n"
        "            --requirement-id sample-runtime-evidence \\\n"
        "            || preflight_validation_status=$?\n"
        "          if [[ \"${preflight_validation_status}\" -ne 0 ]]; then\n"
        f"{cleanup_line}"
        "            exit \"${preflight_validation_status}\"\n"
        "          fi\n"
    )


def _sample_preflight_upload_step() -> str:
    return (
        "      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a\n"
        "        if: always()\n"
        "        with:\n"
        "          name: sample-preflight-${{ github.run_id }}\n"
        "          path: sample-preflight.json\n"
        "          if-no-files-found: warn\n"
        "          retention-days: 14\n"
    )


def _insert_sample_diagnostic_upload(
    workflow: Path,
    *,
    validation_before_upload: bool = True,
    include_cleanup: bool = True,
) -> None:
    validation_step = _sample_preflight_validation_step(include_cleanup=include_cleanup)
    upload_step = _sample_preflight_upload_step()
    diagnostic_steps = (
        validation_step + upload_step
        if validation_before_upload
        else upload_step + validation_step
    )
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            _SAMPLE_PRIMARY_UPLOAD_STEP_HEAD,
            diagnostic_steps + _SAMPLE_PRIMARY_UPLOAD_STEP_HEAD,
            1,
        ),
        encoding="utf-8",
    )


def _sample_mjs_registry() -> dict:
    data = _sample_registry()
    data["requirements"][0]["probe"] = "scripts/probe_sample.mjs"
    return data


def _write_sample_mjs_repo(repo_root: Path) -> None:
    _write_sample_repo(repo_root)
    workflow = repo_root / ".github/workflows/sample-evidence.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8")
        .replace("scripts/probe_sample.py", "scripts/probe_sample.mjs")
        .replace(
            '      - "scripts/runtime_evidence_output.py"\n',
            '      - "scripts/runtime_evidence_output.py"\n'
            '      - "scripts/runtime-evidence-output.mjs"\n'
            '      - "scripts/test-runtime-evidence-output.mjs"\n',
        )
        .replace(
            "python scripts/probe_sample.mjs --allow-run --out sample-evidence.json",
            "node scripts/probe_sample.mjs --allow-run --out sample-evidence.json",
        )
        .replace(
            "      - run: python -m pytest tests/test_runtime_evidence_output.py -q --tb=short\n",
            "      - run: python -m pytest tests/test_runtime_evidence_output.py -q --tb=short\n"
            "      - run: node scripts/test-runtime-evidence-output.mjs\n",
        ),
        encoding="utf-8",
    )
    _write(
        repo_root / "scripts/probe_sample.mjs",
        """
import { spawnSync } from "node:child_process";
import process from "node:process";

const SCHEMA_VERSION = "wiii.sample_evidence.v1";
const ENV_FLAG = "WIII_LIVE_SAMPLE_PROBE";
const ALLOW_FLAG = "--allow-run";
const SUMMARY_ENV = "WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON";
const runner = "scripts/run-sample-evidence.mjs";
const forwarded = [];

function parseArgs(argv) {
  let outPath = "";
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === "--out") {
      outPath = argv[index + 1] || "";
      index += 1;
      continue;
    }
    if (item.startsWith("--out=")) {
      outPath = item.slice("--out=".length);
      continue;
    }
  }
  return { outPath };
}

function fail(message) {
  console.error(message);
  process.exit(2);
}

if (process.env[ENV_FLAG] !== "1") {
  fail(`${ENV_FLAG}=1 is required.`);
}
if (!process.argv.includes(ALLOW_FLAG)) {
  fail(`${ALLOW_FLAG} is required.`);
}
const { outPath } = parseArgs(process.argv.slice(2));
if (!outPath) {
  fail("--out is required.");
}
spawnSync(process.execPath, [runner, ...forwarded], {
  env: {
    ...process.env,
    [SUMMARY_ENV]: outPath,
  },
});
""",
    )
    _write(
        repo_root / "scripts/runtime-evidence-output.mjs",
        """
import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";

export function validateOutputPath(outputPath) {
  return outputPath;
}

export function writeJsonFile(outputPath, payload) {
  const resolved = path.resolve(outputPath);
  validateOutputPath(resolved);
  mkdirSync(path.dirname(resolved), { recursive: true });
  const tempPath = path.join(path.dirname(resolved), `.${path.basename(resolved)}.${randomUUID()}.tmp`);
  const fd = openSync(tempPath, "wx", 0o600);
  try {
    writeFileSync(fd, `${JSON.stringify(payload, null, 2)}\\n`, "utf8");
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  validateOutputPath(resolved);
  renameSync(tempPath, resolved);
  if (existsSync(tempPath)) {
    rmSync(tempPath, { force: true });
  }
}
""",
    )
    _write(
        repo_root / "scripts/test-runtime-evidence-output.mjs",
        """
import assert from "node:assert/strict";

assert.ok("runtime-evidence-output helper contract");
""",
    )


def _add_safe_production_override(workflow: Path) -> None:
    workflow.write_text(
        workflow.read_text(encoding="utf-8")
        .replace(
            "      allow_live_sample:\n"
            "        description: \"Run the sample live evidence probe.\"\n"
            "        required: true\n"
            "        type: boolean\n"
            "        default: false\n",
            "      allow_live_sample:\n"
            "        description: \"Run the sample live evidence probe.\"\n"
            "        required: true\n"
            "        type: boolean\n"
            "        default: false\n"
            "      allow_production:\n"
            "        description: \"Permit production settings.environment.\"\n"
            "        required: true\n"
            "        type: boolean\n"
            "        default: false\n",
        )
        .replace(
            "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
            "      - name: Generate sample evidence\n"
            "        env:\n"
            "          ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}\n"
            "        run: |\n"
            "          set -euo pipefail\n"
            "\n"
            "          args=()\n"
            "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
            "            args+=(--allow-production)\n"
            "          fi\n"
            "\n"
            "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n"
            "            --out sample-evidence.json\n",
        ),
        encoding="utf-8",
    )


def _add_probe_production_override_support(probe: Path) -> None:
    probe.write_text(
        probe.read_text(encoding="utf-8")
        + "\nPRODUCTION_OVERRIDE_FLAG = \"--allow-production\"\n"
        "def _requires_production_override(args):\n"
        "    return bool(args.allow_production)\n",
        encoding="utf-8",
    )


class RuntimeEvidenceRegistryTests(unittest.TestCase):
    def test_default_registry_validates_against_repository(self) -> None:
        data = registry.load_registry(registry.DEFAULT_REGISTRY)

        result = registry.validate_registry(data)

        self.assertEqual([], result.errors)
        self.assertGreaterEqual(result.requirement_count, 5)

    def test_registry_validation_result_exposes_validation_schema_version(self) -> None:
        data = registry.load_registry(registry.DEFAULT_REGISTRY)

        result = registry.validate_registry(data)
        payload = result.to_dict()

        self.assertEqual(
            registry.REGISTRY_VALIDATION_SCHEMA_VERSION,
            result.validation_schema_version,
        )
        self.assertEqual(
            registry.REGISTRY_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual({}, payload["error_code_counts"])
        self.assertIn(
            "validation_schema: wiii.runtime_evidence_registry_validation.v1",
            registry.format_summary(result),
        )

    def test_registry_validation_result_exposes_registry_contract_fingerprint(self) -> None:
        data = registry.load_registry(registry.DEFAULT_REGISTRY)

        result = registry.validate_registry(data)
        payload = result.to_dict()
        changed = copy.deepcopy(data)
        changed["version"] = data["version"] + 1
        changed_result = registry.validate_registry(changed)

        self.assertEqual(data["version"], result.registry_version)
        self.assertEqual(data["version"], payload["registry_version"])
        self.assertRegex(result.registry_fingerprint_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            result.registry_fingerprint_sha256,
            payload["registry_fingerprint_sha256"],
        )
        self.assertNotEqual(
            result.registry_fingerprint_sha256,
            changed_result.registry_fingerprint_sha256,
        )
        self.assertIn("registry_version:", registry.format_summary(result))
        self.assertIn("registry_fingerprint_sha256:", registry.format_summary(result))

    def test_registry_validation_result_exposes_normalized_error_codes(self) -> None:
        data = {
            "registry": registry.REGISTRY_NAME,
            "version": 0,
            "description": "broken registry",
            "requirements": [],
        }

        result = registry.validate_registry(data)
        payload = result.to_dict()
        rendered = registry.format_summary(result)

        self.assertFalse(result.ok)
        self.assertIn("registry_version_invalid", payload["error_codes"])
        self.assertIn("registry_requirements_empty", payload["error_codes"])
        self.assertEqual(
            {
                "registry_requirements_empty": 1,
                "registry_version_invalid": 1,
            },
            payload["error_code_counts"],
        )
        self.assertEqual(
            "registry_version_invalid",
            registry.normalize_registry_error_code("registry: `version` must be an integer >= 1"),
        )
        self.assertIn("Error codes:", rendered)
        self.assertIn("Error code counts:", rendered)
        self.assertIn("registry_version_invalid", rendered)

    def test_registry_version_rejects_boolean(self) -> None:
        data = _sample_registry()
        data["version"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertIsNone(result.registry_version)
        self.assertIn("registry_version_invalid", result.to_dict()["error_codes"])

    def test_registry_rejects_unknown_root_fields(self) -> None:
        data = _sample_registry()
        data["decorative_config"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registry: unknown field(s): decorative_config" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_unknown_field", result.to_dict()["error_codes"])

    def test_requirement_rejects_unknown_fields(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["artifact_token"] = "sample-evidence-${{ github.run_id }}"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("requirements[0]: unknown field(s): artifact_token" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_requirement_unknown_field", result.to_dict()["error_codes"])

    def test_freshness_rejects_unknown_fields(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["freshness"]["grace_period_hours"] = 1

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                ".freshness: unknown field(s): grace_period_hours" in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn("registry_freshness_unknown_field", result.to_dict()["error_codes"])

    def test_freshness_max_age_rejects_boolean(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["freshness"]["max_age_hours"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "registry_freshness_max_age_invalid",
            result.to_dict()["error_codes"],
        )

    def test_payload_check_rejects_unknown_fields(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0]["comment"] = "looks plausible"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                ".payload_checks[0]: unknown field(s): comment" in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn("registry_payload_check_unknown_field", result.to_dict()["error_codes"])

    def test_payload_check_when_rejects_unknown_fields(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0]["when"] = {
            "path": "mode",
            "equals": "live",
            "comment": "looks plausible",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                ".payload_checks[0].when: unknown field(s): comment" in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn("registry_payload_check_unknown_field", result.to_dict()["error_codes"])

    def test_freshness_timestamp_path_rejects_wildcard(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["freshness"]["timestamp_path"] = "events.*.generated_at"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("`timestamp_path` must be dot-path syntax" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_freshness_path_invalid", result.to_dict()["error_codes"])

    def test_registry_validation_json_error_exposes_validation_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            missing_registry = Path(temp_dir) / "missing-registry.json"
            with contextlib.redirect_stdout(stdout):
                exit_code = registry.main(["--registry", str(missing_registry), "--json"])

        data = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(data["ok"])
        self.assertEqual(
            registry.REGISTRY_VALIDATION_SCHEMA_VERSION,
            data["validation_schema_version"],
        )
        self.assertEqual(["registry_load_failed"], data["error_codes"])
        self.assertEqual({"registry_load_failed": 1}, data["error_code_counts"])

    def test_registry_validation_json_rejects_non_finite_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "registry.json"
            registry_path.write_text('{"registry": NaN}', encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = registry.main(
                    ["--registry", str(registry_path), "--json"]
                )

        data = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(data["ok"])
        self.assertEqual(["registry_load_failed"], data["error_codes"])
        self.assertEqual({"registry_load_failed": 1}, data["error_code_counts"])
        self.assertTrue(
            any("non-finite JSON number" in error for error in data["errors"]),
            data["errors"],
        )

    def test_registry_validation_json_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "registry.json"
            registry_path.write_text(
                '{"registry": "A", "registry": "B"}',
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = registry.main(
                    ["--registry", str(registry_path), "--json"]
                )

        data = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(data["ok"])
        self.assertEqual(["registry_load_failed"], data["error_codes"])
        self.assertEqual({"registry_load_failed": 1}, data["error_code_counts"])
        self.assertTrue(
            any("duplicate JSON object key" in error for error in data["errors"]),
            data["errors"],
        )

    def test_registry_validation_json_out_writes_utf8_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "runtime-evidence-registry-validation.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = registry.main(["--json", "--out", str(out_path)])
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(
            registry.REGISTRY_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )

    def test_registry_validation_out_rejects_registry_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "registry.json"
            registry_path.write_text(
                json.dumps(_sample_registry(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = registry.main(
                    [
                        "--registry",
                        str(registry_path),
                        "--json",
                        "--out",
                        str(registry_path),
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["registry_output_path_overwrites_registry"],
            payload["error_codes"],
        )

    def test_registry_validation_out_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "registry-report"
            out_path.mkdir()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = registry.main(["--json", "--out", str(out_path)])

            payload = json.loads(stdout.getvalue())
            out_entries = list(out_path.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["registry_output_path_directory"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"registry_output_path_directory": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], out_entries)

    def test_registry_validation_out_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "target.json"
            target_path.write_text("keep", encoding="utf-8")
            out_path = Path(temp_dir) / "runtime-evidence-registry-validation.json"
            try:
                os.symlink(target_path, out_path)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = registry.main(["--json", "--out", str(out_path)])

            payload = json.loads(stdout.getvalue())
            target_text = target_path.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["registry_output_path_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"registry_output_path_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual("keep", target_text)

    def test_registry_validation_out_rejects_parent_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir) / "target-dir"
            target_dir.mkdir()
            symlink_parent = Path(temp_dir) / "linked-parent"
            try:
                os.symlink(target_dir, symlink_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            out_path = symlink_parent / "runtime-evidence-registry-validation.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = registry.main(["--json", "--out", str(out_path)])

            payload = json.loads(stdout.getvalue())
            target_entries = list(target_dir.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["registry_output_path_parent_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"registry_output_path_parent_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], target_entries)

    def test_valid_registry_passes_with_temp_repo_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_pull_request_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root, workflow_extra="\npull_request_target:\n")

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("pull_request_target" in error for error in result.errors), result.errors)

    def test_workflow_must_live_under_github_workflows(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["workflow"] = "tools/sample-evidence.yml"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow_text = (repo_root / ".github/workflows/sample-evidence.yml").read_text(
                encoding="utf-8"
            )
            _write(repo_root / "tools/sample-evidence.yml", workflow_text)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(".github/workflows" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_file_location_invalid", result.to_dict()["error_codes"])

    def test_probe_must_be_python_or_mjs_script(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["probe"] = "scripts/probe_sample.txt"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe_text = (repo_root / "scripts/probe_sample.py").read_text(encoding="utf-8")
            _write(repo_root / "scripts/probe_sample.txt", probe_text)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "scripts/probe_sample.py",
                    "scripts/probe_sample.txt",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("probe must be a script file" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_probe_suffix_invalid", result.to_dict()["error_codes"])

    def test_contract_tests_must_be_python_or_typescript_test_files(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["contract_tests"] = ["tests/test_probe_sample.md"]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            test_text = (repo_root / "tests/test_probe_sample.py").read_text(encoding="utf-8")
            _write(repo_root / "tests/test_probe_sample.md", test_text)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "tests/test_probe_sample.py",
                    "tests/test_probe_sample.md",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("contract_tests entries must be Python" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_contract_test_path_invalid", result.to_dict()["error_codes"])

    def test_contract_tests_must_not_point_to_non_test_python_modules(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["contract_tests"] = ["tests/probe_sample_helper.py"]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            test_text = (repo_root / "tests/test_probe_sample.py").read_text(encoding="utf-8")
            _write(repo_root / "tests/probe_sample_helper.py", test_text)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "tests/test_probe_sample.py",
                    "tests/probe_sample_helper.py",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("contract_tests entries must be Python" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_contract_test_path_invalid", result.to_dict()["error_codes"])

    def test_contract_tests_must_not_duplicate_normalized_paths(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["contract_tests"].append("./tests//test_probe_sample.py")

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                .replace(
                    '      - "tests/test_probe_sample.py"\n',
                    '      - "tests/test_probe_sample.py"\n'
                    '      - "./tests//test_probe_sample.py"\n',
                )
                .replace(
                    "      - run: python -m pytest tests/test_probe_sample.py -q --tb=short\n",
                    "      - run: python -m pytest tests/test_probe_sample.py -q --tb=short\n"
                    "      - run: python -m pytest ./tests//test_probe_sample.py -q --tb=short\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate normalized paths" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_contract_test_duplicate", result.to_dict()["error_codes"])

    def test_payload_check_accepts_length_equals_path_operation(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"] = [
            {
                "path": "cases",
                "length_equals_path": "case_count",
            },
            {
                "path": "privacy.raw_content_included",
                "equals": False,
            },
            {
                "path": "privacy.identifier_strategy",
                "equals": "hash_or_count_only",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_payload_check_accepts_wildcard_path_segments(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"] = [
            {
                "path": "cases.*.status",
                "equals": "pass",
            },
            {
                "path": "privacy.raw_content_included",
                "equals": False,
            },
            {
                "path": "privacy.identifier_strategy",
                "equals": "hash_or_count_only",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_payload_check_path_rejects_empty_segments(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0]["path"] = "privacy..raw_content_included"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("`path` must be dot-path syntax" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_payload_check_path_invalid", result.to_dict()["error_codes"])

    def test_payload_check_rejects_missing_length_equals_path_target(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"] = [
            {
                "path": "cases",
                "length_equals_path": "",
            },
            {
                "path": "privacy.raw_content_included",
                "equals": False,
            },
            {
                "path": "privacy.identifier_strategy",
                "equals": "hash_or_count_only",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("length_equals_path" in error for error in result.errors), result.errors)

    def test_payload_check_length_equals_path_rejects_wildcard(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"] = [
            {
                "path": "cases",
                "length_equals_path": "case_counts.*.total",
            },
            {
                "path": "privacy.raw_content_included",
                "equals": False,
            },
            {
                "path": "privacy.identifier_strategy",
                "equals": "hash_or_count_only",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("`length_equals_path` must be dot-path syntax" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_payload_check_path_invalid", result.to_dict()["error_codes"])

    def test_payload_check_when_path_rejects_wildcard(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0]["when"] = {
            "path": "cases.*.mode",
            "equals": "live",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(".when: `path` must be dot-path syntax" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_payload_check_path_invalid", result.to_dict()["error_codes"])

    def test_payload_check_min_must_be_json_number(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0] = {
            "path": "metrics.count",
            "min": "1",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("min must be a JSON number" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_payload_check_value_invalid", result.to_dict()["error_codes"])

    def test_payload_check_equals_must_be_non_null_scalar(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0] = {
            "path": "status",
            "equals": None,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("equals must be a non-null JSON scalar" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_payload_check_value_invalid", result.to_dict()["error_codes"])

    def test_payload_check_sorted_equals_must_be_list(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0] = {
            "path": "events.names",
            "sorted_equals": "ready",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("sorted_equals must be a list" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_payload_check_value_invalid", result.to_dict()["error_codes"])

    def test_payload_check_sorted_equals_items_must_be_non_null_scalars(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0] = {
            "path": "events.names",
            "sorted_equals": ["ready", {"phase": "done"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "sorted_equals[1] must be a non-null JSON scalar" in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn("registry_payload_check_value_invalid", result.to_dict()["error_codes"])

    def test_payload_check_when_requires_explicit_operation(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0]["when"] = {
            "path": "mode",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("exactly one of equals or not_equals is required" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_payload_check_when_operation_invalid",
            result.to_dict()["error_codes"],
        )

    def test_payload_check_when_rejects_multiple_operations(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0]["when"] = {
            "path": "mode",
            "equals": "live",
            "not_equals": "dry-run",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("exactly one of equals or not_equals is required" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_payload_check_when_operation_invalid",
            result.to_dict()["error_codes"],
        )

    def test_payload_check_when_value_must_be_non_null_scalar(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"][0]["when"] = {
            "path": "mode",
            "equals": ["live"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(".when: equals must be a non-null JSON scalar" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_payload_check_when_value_invalid",
            result.to_dict()["error_codes"],
        )

    def test_payload_checks_must_prove_raw_content_absence(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"] = [
            check
            for check in data["requirements"][0]["payload_checks"]
            if check.get("path") != "privacy.raw_content_included"
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("raw content absence" in error for error in result.errors), result.errors)

    def test_payload_checks_must_prove_identifier_strategy(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"] = [
            check
            for check in data["requirements"][0]["payload_checks"]
            if check.get("path") != "privacy.identifier_strategy"
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("identifier_strategy" in error for error in result.errors), result.errors)

    def test_forbidden_payload_tokens_must_include_baseline_secret_tokens(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["forbidden_payload_tokens"] = [
            "raw sample evidence leaked",
            "access_token",
            "authorization",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("baseline secret token" in error for error in result.errors), result.errors)

    def test_forbidden_payload_tokens_must_not_duplicate_values(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["forbidden_payload_tokens"].append("api_key")

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("`forbidden_payload_tokens` must not contain duplicate values" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_string_list_duplicate", result.to_dict()["error_codes"])

    def test_forbidden_payload_tokens_must_not_duplicate_case_insensitively(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["forbidden_payload_tokens"].append("API_KEY")

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("case-insensitive duplicate values" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_forbidden_payload_token_duplicate",
            result.to_dict()["error_codes"],
        )

    def test_forbidden_payload_regexes_must_compile(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["forbidden_payload_regexes"] = ["("]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("forbidden_payload_regexes pattern must compile" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_forbidden_payload_regex_invalid",
            result.to_dict()["error_codes"],
        )

    def test_forbidden_payload_regexes_must_not_duplicate(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["forbidden_payload_regexes"] = [
            r"secret\s+value",
            r"secret\s+value",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate forbidden_payload_regexes pattern" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_forbidden_payload_regex_duplicate",
            result.to_dict()["error_codes"],
        )

    def test_live_guard_tokens_must_not_duplicate_values(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["live_guard_tokens"].append("--allow-run")

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("`live_guard_tokens` must not contain duplicate values" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_string_list_duplicate", result.to_dict()["error_codes"])

    def test_python_probe_live_guard_token_must_be_argparse_store_true_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.py"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    '    parser.add_argument("--allow-run", action="store_true")',
                    '    parser.add_argument("--other-flag", action="store_true")\n'
                    '    "--allow-run only appears in text"',
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("argparse store_true CLI flag" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_guard_token_invalid", result.to_dict()["error_codes"])

    def test_python_probe_live_guard_token_rejects_non_store_true_argparse_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.py"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    '    parser.add_argument("--allow-run", action="store_true")',
                    '    parser.add_argument("--allow-run", action="store_false")',
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("argparse store_true CLI flag" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_guard_token_invalid", result.to_dict()["error_codes"])

    def test_mjs_probe_live_guard_token_allows_fail_closed_process_argv_guard(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_mjs_probe_live_guard_token_must_fail_closed_on_missing_arg(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "if (!process.argv.includes(ALLOW_FLAG)) {\n"
                    "  fail(`${ALLOW_FLAG} is required.`);\n"
                    "}\n",
                    "if (process.argv.includes(ALLOW_FLAG)) {\n"
                    "  console.log(`${ALLOW_FLAG} acknowledged.`);\n"
                    "}\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("fail-closed process.argv.includes" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_guard_token_invalid", result.to_dict()["error_codes"])

    def test_mjs_probe_live_guard_token_must_be_top_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "if (!process.argv.includes(ALLOW_FLAG)) {\n"
                    "  fail(`${ALLOW_FLAG} is required.`);\n"
                    "}\n",
                    "function unusedGuard() {\n"
                    "  if (!process.argv.includes(ALLOW_FLAG)) {\n"
                    "    fail(`${ALLOW_FLAG} is required.`);\n"
                    "  }\n"
                    "}\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("fail-closed process.argv.includes" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_guard_token_invalid", result.to_dict()["error_codes"])

    def test_mjs_probe_fail_function_must_exit_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "  process.exit(2);",
                    "  console.log(message);",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("MJS probe fail() must call process.exit" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_guard_token_invalid", result.to_dict()["error_codes"])

    def test_mjs_probe_fail_function_rejects_zero_exit_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "  process.exit(2);",
                    "  process.exit(0);",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("MJS probe fail() must call process.exit" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_guard_token_invalid", result.to_dict()["error_codes"])

    def test_mjs_probe_live_guard_token_ignores_template_literal_spoof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            _write(
                repo_root / "scripts/probe_sample.mjs",
                """
const SCHEMA_VERSION = "wiii.sample_evidence.v1";
const ENV_FLAG = "WIII_LIVE_SAMPLE_PROBE";
const ALLOW_FLAG = "--allow-run";
console.log(`fake guard: if (!process.argv.includes(ALLOW_FLAG)) { fail("${ALLOW_FLAG}"); }`);
""",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("fail-closed process.argv.includes" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_guard_token_invalid", result.to_dict()["error_codes"])

    def test_mjs_probe_workflow_requires_out_artifact_on_probe_command_line(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    " --out sample-evidence.json",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "registered probe invocation must write `--out sample-evidence.json`"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn("workflow_probe_binding_invalid", result.to_dict()["error_codes"])

    def test_mjs_probe_output_argument_must_be_parsed_from_process_argv(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    'if (item === "--out") {',
                    'if (item === "--artifact") {',
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "registered MJS probe must parse `--out` from process.argv"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_output_argument_must_assign_separate_out_arg_to_returned_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "      outPath = argv[index + 1] || \"\";",
                    "      const parsedOutPath = argv[index + 1] || \"\";",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "registered MJS probe must parse `--out` from process.argv"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_output_argument_must_assign_equals_out_arg_to_returned_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "      outPath = item.slice(\"--out=\".length);",
                    "      const parsedOutPath = item.slice(\"--out=\".length);",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "registered MJS probe must parse `--out` from process.argv"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_output_argument_must_return_parsed_out_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "  return { outPath };",
                    "  return { otherPath: outPath };",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "must forward parsed `--out` path to WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_output_argument_ignores_template_literal_spoof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            _write(
                repo_root / "scripts/probe_sample.mjs",
                """
const SCHEMA_VERSION = "wiii.sample_evidence.v1";
const ENV_FLAG = "WIII_LIVE_SAMPLE_PROBE";
const ALLOW_FLAG = "--allow-run";

function fail(message) {
  console.error(message);
  process.exit(2);
}

if (process.env[ENV_FLAG] !== "1") {
  fail(`${ENV_FLAG}=1 is required.`);
}
if (!process.argv.includes(ALLOW_FLAG)) {
  fail(`${ALLOW_FLAG} is required.`);
}
console.log(`fake output parser: if (item === "--out") { item.startsWith("--out="); }`);
""",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "registered MJS probe must parse `--out` from process.argv"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_output_argument_must_flow_to_summary_env(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "[SUMMARY_ENV]: outPath",
                    "[SUMMARY_ENV]: \"sample-evidence.json\"",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "must forward parsed `--out` path to WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_output_env_forward_ignores_template_literal_spoof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "[SUMMARY_ENV]: outPath",
                    "OTHER_ENV: outPath",
                )
                + "\nconsole.log(`fake env forward: [SUMMARY_ENV]: outPath`);\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "must forward parsed `--out` path to WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_output_env_forward_must_be_on_spawn_sync_runner(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "[SUMMARY_ENV]: outPath",
                    "[SUMMARY_ENV]: \"sample-evidence.json\"",
                )
                + "\nconst unusedOptions = { env: { [SUMMARY_ENV]: outPath } };\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "must forward parsed `--out` path to WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_output_env_forward_requires_runner_spawn(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8").replace(
                    "spawnSync(process.execPath, [runner, ...forwarded], {",
                    "spawnSync(process.execPath, [], {",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "must forward parsed `--out` path to WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON"
                in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_runtime_evidence_output_helper_must_use_atomic_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            helper_path = repo_root / "scripts/runtime-evidence-output.mjs"
            helper_path.write_text(
                helper_path.read_text(encoding="utf-8").replace("    fsyncSync(fd);\n", ""),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("runtime evidence output helper" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_output_helper_atomic_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport { writeFileSync } from \"node:fs\";\n"
                + "writeFileSync(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport fs from \"node:fs\";\n"
                + "fs.writeFileSync(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport { writeFile as writeEvidenceFile } from \"node:fs/promises\";\n"
                + "await writeEvidenceFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_named_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport { promises as fsPromises } from \"node:fs\";\n"
                + "await fsPromises.writeFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_fs_promises_namespace_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport fsPromises from \"node:fs/promises\";\n"
                + "await fsPromises.writeFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fsPromises = await import(\"node:fs/promises\");\n"
                + "await fsPromises.writeFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_fs_destructured_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { promises: fsPromises } = await import(\"node:fs\");\n"
                + "await fsPromises.writeFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_fs_destructured_promises_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { promises: fsPromises } = await import(\"node:fs\");\n"
                + "const writer = \"writeFile\";\n"
                + "await fsPromises[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_static_namespace_fs_default_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport * as fs from \"node:fs\";\n"
                + "fs.default.writeFileSync(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_static_named_fs_default_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport { default as fsDefault } from \"node:fs\";\n"
                + "const writer = \"writeFileSync\";\n"
                + "fsDefault[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_fs_default_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fs = await import(\"node:fs\");\n"
                + "fs.default.writeFileSync(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_fs_default_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fs = await import(\"node:fs\");\n"
                + "const writer = \"writeFileSync\";\n"
                + "fs.default[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_named_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { writeFileSync: writeEvidenceFile } = await import(\"node:fs\");\n"
                + "writeEvidenceFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_named_fs_default_initializer_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { writeFileSync: writeEvidenceFile = null } = await import(\"node:fs\");\n"
                + "writeEvidenceFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_named_fs_default_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { default: fsDefault } = await import(\"node:fs\");\n"
                + "fsDefault.writeFileSync(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_named_fs_default_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { default: fsDefault } = await import(\"node:fs\");\n"
                + "const writer = \"writeFileSync\";\n"
                + "fsDefault[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_require_named_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { writeFileSync: writeEvidenceFile } = require(\"node:fs\");\n"
                + "writeEvidenceFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_require_named_fs_default_initializer_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { writeFileSync: writeEvidenceFile = null } = require(\"node:fs\");\n"
                + "writeEvidenceFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_require_named_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { writeFile: writeEvidenceFile } = require(\"node:fs/promises\");\n"
                + "await writeEvidenceFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_require_fs_destructured_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { promises: fsPromises } = require(\"node:fs\");\n"
                + "await fsPromises.writeFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_require_fs_destructured_promises_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst { promises: fsPromises } = require(\"node:fs\");\n"
                + "const writer = \"writeFile\";\n"
                + "await fsPromises[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_inline_require_fs_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst writer = \"writeFileSync\";\n"
                + "require(\"node:fs\")[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_inline_dynamic_fs_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst writer = \"writeFileSync\";\n"
                + "(await import(\"node:fs\"))[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_inline_require_fs_promises_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst writer = \"writeFile\";\n"
                + "await require(\"node:fs\").promises[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_inline_dynamic_fs_promises_computed_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst writer = \"writeFile\";\n"
                + "(await import(\"node:fs/promises\"))[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_static_fs_bracket_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport fs from \"node:fs\";\n"
                + "fs[\"writeFileSync\"](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_optional_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport fs from \"node:fs\";\n"
                + "fs?.writeFileSync(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_optional_computed_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport fs from \"node:fs\";\n"
                + "const writer = \"writeFileSync\";\n"
                + "fs?.[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_dynamic_fs_bracket_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fs = await import(\"node:fs\");\n"
                + "fs[\"writeFileSync\"](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_require_fs_promises_bracket_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fs = require(\"node:fs\");\n"
                + "await fs[\"promises\"][\"writeFile\"](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_optional_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fs = require(\"node:fs\");\n"
                + "await fs.promises?.writeFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_optional_computed_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fs = require(\"node:fs\");\n"
                + "const bucket = \"promises\";\n"
                + "const writer = \"writeFile\";\n"
                + "await fs?.[bucket]?.[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_computed_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nimport fs from \"node:fs\";\n"
                + "const writer = \"writeFileSync\";\n"
                + "fs[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_computed_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fs = require(\"node:fs\");\n"
                + "const bucket = \"promises\";\n"
                + "const writer = \"writeFile\";\n"
                + "await fs[bucket][writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_module_constant_require_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fsModule = \"node:fs\";\n"
                + "const fs = require(fsModule);\n"
                + "const writer = \"writeFileSync\";\n"
                + "fs[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_module_constant_dynamic_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fsModule = \"node:fs\";\n"
                + "const { writeFileSync: writeEvidenceFile } = await import(fsModule);\n"
                + "writeEvidenceFile(outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_module_constant_dynamic_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fsModule = \"node:fs/promises\";\n"
                + "const fsPromises = await import(fsModule);\n"
                + "const writer = \"writeFile\";\n"
                + "await fsPromises[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_concatenated_module_constant_fs_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst modulePrefix = \"node:\";\n"
                + "const fsModule = modulePrefix + \"fs\";\n"
                + "const fs = require(fsModule);\n"
                + "const writer = \"write\" + \"FileSync\";\n"
                + "fs[writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_must_not_concatenated_module_constant_fs_promises_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconst fsModule = \"node:\" + \"fs\";\n"
                + "const fs = require(fsModule);\n"
                + "const bucket = \"prom\" + \"ises\";\n"
                + "const writer = \"write\" + \"File\";\n"
                + "await fs[bucket][writer](outPath, JSON.stringify({ status: \"pass\" }));\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("outside runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_raw_write_detector_ignores_template_literal_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            probe_path = repo_root / "scripts/probe_sample.mjs"
            probe_path.write_text(
                probe_path.read_text(encoding="utf-8")
                + "\nconsole.log(`fake writeFileSync(outPath, JSON.stringify({ status: \"pass\" }))`);\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_payload_checks_must_not_duplicate_path_operation_and_condition(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["payload_checks"].append(
            {
                "path": "status",
                "equals": "pass",
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("duplicate payload check" in error for error in result.errors), result.errors)

    def test_missing_workflow_artifact_validator_token_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace("validate_runtime_evidence_artifact.py", "missing_validator.py"),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("validate_runtime_evidence_artifact.py" in error for error in result.errors), result.errors)

    def test_workflow_must_reference_registered_contract_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                .replace(
                    "      - run: python -m pytest tests/test_probe_sample.py -q --tb=short\n",
                    "      - run: python -m pytest -q --tb=short\n",
                )
                .replace('      - "tests/test_probe_sample.py"\n', ""),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.contract_tests" in error for error in result.errors),
            result.errors,
        )

    def test_registry_rejects_symlink_workflow_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            target = repo_root / ".github/workflows/sample-target.yml"
            target.write_text(workflow.read_text(encoding="utf-8"), encoding="utf-8")
            workflow.unlink()
            try:
                workflow.symlink_to(target)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("path must not contain symlinks" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("repo_path_symlink", result.to_dict()["error_codes"])

    def test_workflow_must_execute_registered_contract_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python -m pytest tests/test_probe_sample.py -q --tb=short",
                    "echo tests/test_probe_sample.py",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must be executed by pytest or vitest" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_contract_test_execution_requires_bounded_path_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python -m pytest tests/test_probe_sample.py -q --tb=short",
                    "python -m pytest tests/test_probe_sample.py.disabled -q --tb=short",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must be executed by pytest or vitest" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_contract_test_invalid", result.to_dict()["error_codes"])

    def test_workflow_contract_test_execution_ignores_commented_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python -m pytest tests/test_probe_sample.py -q --tb=short\n",
                    "      - run: # python -m pytest tests/test_probe_sample.py -q --tb=short\n"
                    "      - run: echo skipped\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must be executed by pytest or vitest" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_contract_test_invalid", result.to_dict()["error_codes"])

    def test_workflow_contract_test_execution_rejects_echoed_runner_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python -m pytest tests/test_probe_sample.py -q --tb=short\n",
                    "      - run: echo python -m pytest tests/test_probe_sample.py -q --tb=short\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must be executed by pytest or vitest" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_contract_test_invalid", result.to_dict()["error_codes"])

    def test_workflow_must_validate_registered_artifact_with_requirement_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "--requirement-id sample-runtime-evidence",
                    "--requirement-id other-runtime-evidence",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.validation" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_validation_artifact_requires_bounded_path_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "validate_runtime_evidence_artifact.py             sample-evidence.json",
                    "validate_runtime_evidence_artifact.py             sample-evidence.json.disabled",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.validation" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_validation_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_validation_artifact_requires_exact_registered_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "validate_runtime_evidence_artifact.py             sample-evidence.json",
                    "validate_runtime_evidence_artifact.py             tmp/sample-evidence.json",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.validation" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_validation_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_validation_must_execute_artifact_validator_not_echo_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python tools/wiii_self_harness/validate_runtime_evidence_artifact.py",
                    "echo python tools/wiii_self_harness/validate_runtime_evidence_artifact.py",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.validation" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_validation_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_validation_must_use_canonical_artifact_validator_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python tools/wiii_self_harness/validate_runtime_evidence_artifact.py",
                    "python scripts/validate_runtime_evidence_artifact.py",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.validation" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_validation_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_validation_artifact_and_requirement_must_be_validator_args(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "validate_runtime_evidence_artifact.py             "
                    "sample-evidence.json             "
                    "--requirement-id sample-runtime-evidence",
                    "validate_runtime_evidence_artifact.py             "
                    "other-evidence.json             "
                    "--requirement-id other-runtime-evidence             "
                    "sample-evidence.json --requirement-id sample-runtime-evidence",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.validation" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_validation_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_must_upload_registered_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          path: sample-evidence.json",
                    "          path: other-evidence.json",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.upload" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_upload_path_must_match_validation_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          path: sample-evidence.json",
                    "          path: tmp/sample-evidence.json",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("probe-validation-upload order" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_upload_artifact_token_requires_exact_name_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          name: sample-evidence-${{ github.run_id }}",
                    "          name: sample-evidence-${{ github.run_id }}.disabled",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.upload" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_artifact_token_ignores_path_scalar_name_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          name: sample-evidence-${{ github.run_id }}\n"
                    "          path: sample-evidence.json\n",
                    "          path: |\n"
                    "            sample-evidence.json\n"
                    "            name: sample-evidence-${{ github.run_id }}\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.upload" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_must_preserve_failed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "        if: always()\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("if: always()" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_preserve_failed_evidence_ignores_commented_if(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "        if: always()\n",
                    "        if: success()\n        # if: always()\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("if: always()" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_preserve_failed_evidence_ignores_path_scalar_if_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "        if: always()\n"
                    "        with:\n"
                    "          name: sample-evidence-${{ github.run_id }}\n"
                    "          path: sample-evidence.json\n",
                    "        if: success()\n"
                    "        with:\n"
                    "          name: sample-evidence-${{ github.run_id }}\n"
                    "          path: |\n"
                    "            sample-evidence.json\n"
                    "            if: always()\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("if: always()" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_rejects_duplicate_step_if(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "        if: always()\n",
                    "        if: always()\n"
                    "        if: success()\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate step field(s): if" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_must_set_bounded_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          retention-days: 30",
                    "          retention-days: 120",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("retention-days" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_upload_must_error_when_artifact_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if-no-files-found: error\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("if-no-files-found: error" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_upload_missing_file_policy_ignores_commented_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if-no-files-found: error\n",
                    "          if-no-files-found: warn\n"
                    "          # if-no-files-found: error\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("if-no-files-found: error" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_rejects_duplicate_missing_file_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if-no-files-found: error\n",
                    "          if-no-files-found: error\n"
                    "          if-no-files-found: warn\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate with field(s): if-no-files-found" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_must_use_narrow_json_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          path: sample-evidence.json\n",
                    "          path: |\n"
                    "            sample-evidence.json\n"
                    "            test-results/**/*.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("exactly one explicit JSON evidence file" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_upload_rejects_environment_variable_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "path: sample-evidence.json",
                    "path: $ARTIFACT_DIR/sample-evidence.json",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("exactly one explicit JSON evidence file" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_rejects_extra_json_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          path: sample-evidence.json\n",
                    "          path: |\n"
                    "            sample-evidence.json\n"
                    "            raw-output.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("exactly one explicit JSON evidence file" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_upload_rejects_duplicate_path_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          path: sample-evidence.json\n",
                    "          path: sample-evidence.json\n"
                    "          path: other-evidence.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate with field(s): path" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_upload_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_rejects_unregistered_upload_artifact_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + """
  extra_upload:
    timeout-minutes: 15
    steps:
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: always()
        with:
          name: raw-logs-${{ github.run_id }}
          path: logs/raw-output.json
          if-no-files-found: error
          retention-days: 30
""",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unregistered upload-artifact step" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_allows_registered_diagnostic_upload_artifact_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _insert_sample_diagnostic_upload(workflow)

            result = registry.validate_registry(
                _sample_registry_with_diagnostic_upload(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_workflow_rejects_diagnostic_upload_before_preflight_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _insert_sample_diagnostic_upload(workflow, validation_before_upload=False)

            result = registry.validate_registry(
                _sample_registry_with_diagnostic_upload(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "before upload in the same job" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_workflow_rejects_diagnostic_preflight_without_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _insert_sample_diagnostic_upload(workflow, include_cleanup=False)

            result = registry.validate_registry(
                _sample_registry_with_diagnostic_upload(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "before upload in the same job" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_workflow_rejects_same_token_wrong_path_upload_artifact_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + """
  sidecar_upload:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: always()
        with:
          name: sample-evidence-${{ github.run_id }}
          path: tmp/sample-evidence.json
          if-no-files-found: error
          retention-days: 30
""",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unregistered upload-artifact step" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_checkout_must_not_persist_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "        with:\n          persist-credentials: false\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.checkout" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_checkout_hardening_ignores_commented_persist_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          persist-credentials: false\n",
                    "          persist-credentials: true\n"
                    "          # persist-credentials: false\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.checkout" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_checkout_invalid", result.to_dict()["error_codes"])

    def test_workflow_checkout_hardening_ignores_run_block_uses_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n"
                    "        with:\n"
                    "          persist-credentials: false\n",
                    "      - run: |\n"
                    "          echo fake-checkout\n"
                    "          uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n"
                    "          persist-credentials: false\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.checkout" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_checkout_invalid", result.to_dict()["error_codes"])

    def test_workflow_checkout_hardening_ignores_run_block_list_item_uses_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n"
                    "        with:\n"
                    "          persist-credentials: false\n",
                    "      - run: |\n"
                    "          echo fake-checkout\n"
                    "          - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n"
                    "            with:\n"
                    "              persist-credentials: false\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.checkout" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_checkout_invalid", result.to_dict()["error_codes"])

    def test_workflow_jobs_must_have_timeout_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "    timeout-minutes: 15\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.jobs" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_rejects_duplicate_contract_job_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + """
  contract:
    name: Overridden Contract
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - run: echo skipped registered contract tests
""",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate workflow job id(s): contract" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_job_name_duplicate", result.to_dict()["error_codes"])

    def test_workflow_rejects_duplicate_live_job_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + """
  sample:
    name: Overridden Live Job
    runs-on: ubuntu-latest
    needs: []
    if: github.event_name == 'push'
    env:
      WIII_LIVE_SAMPLE_PROBE: "1"
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          persist-credentials: false
      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json
      - run: python tools/wiii_self_harness/validate_runtime_evidence_artifact.py sample-evidence.json --requirement-id sample-runtime-evidence
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: always()
        with:
          name: sample-evidence-${{ github.run_id }}
          path: sample-evidence.json
          if-no-files-found: error
          retention-days: 30
""",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate workflow job id(s): sample" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_job_name_duplicate", result.to_dict()["error_codes"])

    def test_workflow_rejects_duplicate_job_if_gate_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "    env:\n      WIII_LIVE_SAMPLE_PROBE: \"1\"\n",
                    "    if: github.event_name == 'push'\n"
                    "    env:\n"
                    "      WIII_LIVE_SAMPLE_PROBE: \"1\"\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate job-level field(s): if" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_job_control_duplicate", result.to_dict()["error_codes"])

    def test_workflow_rejects_duplicate_job_needs_contract_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "    if: >-\n",
                    "    needs: []\n"
                    "    if: >-\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate job-level field(s): needs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_job_control_duplicate", result.to_dict()["error_codes"])

    def test_workflow_must_not_enable_continue_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n"
                    "        continue-on-error: true\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.fail_closed" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_must_not_enable_shell_xtrace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                    "      - run: |\n"
                    "          set -euxo pipefail\n"
                    "          python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("shell xtrace" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_shell_xtrace_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_workflow_must_not_enable_bash_xtrace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                    "      - run: bash -x scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("shell xtrace" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_shell_xtrace_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_workflow_permissions_must_stay_contents_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "  contents: read",
                    "  contents: write",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.permissions" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_permissions_reject_extra_scope_and_job_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                .replace(
                    "  contents: read",
                    "  contents: read\n  issues: write",
                )
                .replace(
                    "    timeout-minutes: 15",
                    "    timeout-minutes: 15\n    permissions:\n      contents: read",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("job-level permissions" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_rejects_duplicate_top_level_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + "\npermissions:\n  contents: write\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate top-level `permissions` key" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_top_level_duplicate", result.to_dict()["error_codes"])

    def test_workflow_rejects_duplicate_top_level_permissions_scalar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8") + "\npermissions: write-all\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate top-level `permissions` key" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_top_level_duplicate", result.to_dict()["error_codes"])

    def test_workflow_must_have_concurrency_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    """concurrency:
  group: ${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
""",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.concurrency" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_concurrency_only_cancels_pull_request_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
                    "cancel-in-progress: true",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.concurrency" in error for error in result.errors),
            result.errors,
        )

    def test_live_evidence_job_requires_runtime_evidence_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "    environment: wiii-runtime-evidence\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.environment" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_environment_invalid", result.to_dict()["error_codes"])

    def test_live_evidence_job_rejects_wrong_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "environment: wiii-runtime-evidence",
                    "environment: production",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("wiii-runtime-evidence" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_environment_invalid", result.to_dict()["error_codes"])

    def test_workflow_allows_secrets_in_gated_live_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '      WIII_LIVE_SAMPLE_PROBE: "1"',
                    '      WIII_LIVE_SAMPLE_PROBE: "1"\n'
                    "      SAMPLE_TOKEN: ${{ secrets.SAMPLE_TOKEN }}",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_workflow_rejects_top_level_secret_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "jobs:\n",
                    "env:\n"
                    "  SAMPLE_TOKEN: ${{ secrets.SAMPLE_TOKEN }}\n\n"
                    "jobs:\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("top-level secret references" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_secret_scope_invalid", result.to_dict()["error_codes"])

    def test_workflow_rejects_top_level_bracket_secret_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "jobs:\n",
                    "env:\n"
                    "  SAMPLE_TOKEN: ${{ secrets['SAMPLE_TOKEN'] }}\n\n"
                    "jobs:\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("top-level secret references" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_secret_scope_invalid", result.to_dict()["error_codes"])

    def test_workflow_rejects_secrets_in_ungated_contract_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "    timeout-minutes: 15\n    steps:",
                    "    timeout-minutes: 15\n"
                    "    env:\n"
                    "      SAMPLE_TOKEN: ${{ secrets.SAMPLE_TOKEN }}\n"
                    "    steps:",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow_secrets" in error and ".contract:" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_secret_scope_invalid", result.to_dict()["error_codes"])

    def test_workflow_rejects_secret_live_job_without_contract_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                .replace(
                    '      WIII_LIVE_SAMPLE_PROBE: "1"',
                    '      WIII_LIVE_SAMPLE_PROBE: "1"\n'
                    "      SAMPLE_TOKEN: ${{ secrets.SAMPLE_TOKEN }}",
                )
                .replace("    needs: contract\n", ""),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("secret-bearing evidence job" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_secret_scope_invalid", result.to_dict()["error_codes"])

    def test_workflow_rejects_secret_sidecar_job_outside_evidence_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + """
  secret_sidecar:
    needs: contract
    if: >-
      ${{
        (github.event_name == 'workflow_dispatch' && inputs.allow_live_sample == true) ||
        (github.event_name == 'schedule' && vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1')
      }}
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      SAMPLE_TOKEN: ${{ secrets.SAMPLE_TOKEN }}
    steps:
      - run: echo secret-sidecar
""",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registered live evidence job" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_secret_scope_invalid", result.to_dict()["error_codes"])

    def test_workflow_allows_manual_production_override_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            _add_probe_production_override_support(repo_root / "scripts/probe_sample.py")
            _add_safe_production_override(repo_root / ".github/workflows/sample-evidence.yml")

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_probe_production_override_requires_workflow_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            _add_probe_production_override_support(repo_root / "scripts/probe_sample.py")

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registered probe supports --allow-production" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_must_cover_each_registered_probe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            validator = registry.RegistryValidator(
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

            validator.require_workflow_production_override_guard(
                workflow.read_text(encoding="utf-8"),
                context="workflow_production_override[sample]",
                registered_probe_paths=[
                    "scripts/probe_sample.py",
                    "scripts/probe_second.py",
                ],
                production_override_probe_paths=[
                    "scripts/probe_sample.py",
                    "scripts/probe_second.py",
                ],
            )

        self.assertTrue(
            any("each registered probe" in error for error in validator.errors),
            validator.errors,
        )

    def test_workflow_production_override_input_must_default_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      allow_production:\n"
                    "        description: \"Permit production settings.environment.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: false\n",
                    "      allow_production:\n"
                    "        description: \"Permit production settings.environment.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: true\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("allow_production input" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_input_rejects_duplicate_schema_fields(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      allow_production:\n"
                    "        description: \"Permit production settings.environment.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: false\n",
                    "      allow_production:\n"
                    "        description: \"Permit production settings.environment.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: false\n"
                    "        default: false\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("allow_production input" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_input_rejects_duplicate_input_name(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      allow_production:\n"
                    "        description: \"Permit production settings.environment.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: false\n",
                    "      allow_production:\n"
                    "        description: \"Permit production settings.environment.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: false\n"
                    "      allow_production:\n"
                    "        description: \"Permit production settings.environment.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: false\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("allow_production input" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_env_must_be_manual_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}",
                    "ALLOW_PRODUCTION_INPUT: true",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("ALLOW_PRODUCTION_INPUT" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_env_rejects_duplicate_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}\n",
                    "          ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}\n"
                    "          ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("ALLOW_PRODUCTION_INPUT" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_env_must_bind_flag_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - name: Generate sample evidence\n"
                    "        env:\n"
                    "          ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}\n"
                    "        run: |\n",
                    "      - name: Bind production override input\n"
                    "        env:\n"
                    "          ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}\n"
                    "        run: echo bound\n"
                    "      - name: Generate sample evidence\n"
                    "        run: |\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("ALLOW_PRODUCTION_INPUT" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_flag_must_run_registered_probe_step(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - name: Generate sample evidence\n"
                    "        env:\n"
                    "          ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}\n"
                    "        run: |\n"
                    "          set -euo pipefail\n"
                    "\n"
                    "          args=()\n"
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n"
                    "            --out sample-evidence.json\n",
                    "      - name: Prepare production override args\n"
                    "        env:\n"
                    "          ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}\n"
                    "        run: |\n"
                    "          set -euo pipefail\n"
                    "\n"
                    "          args=()\n"
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "      - name: Generate sample evidence\n"
                    "        run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registered live probe step" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_flag_must_pass_args_to_probe_command(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '          python scripts/probe_sample.py --allow-run "${args[@]}" \\\n'
                    "            --out sample-evidence.json\n",
                    "          python scripts/probe_sample.py --allow-run \\\n"
                    "            --out sample-evidence.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registered live probe command" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_allows_here_string_after_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '          python scripts/probe_sample.py --allow-run "${args[@]}" \\\n',
                    "          read -r note <<< \"safe\"\n"
                    '          python scripts/probe_sample.py --allow-run "${args[@]}" \\\n',
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_workflow_production_override_flag_rejects_args_reset_before_probe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n",
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          args=()\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registered live probe command" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_flag_rejects_args_unset_before_probe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n",
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          unset 'args[0]'\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registered live probe command" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_flag_rejects_args_redeclare_before_probe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n",
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          declare -a args=()\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registered live probe command" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_flag_rejects_args_read_before_probe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n",
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "\n"
                    "          read -a args <<< \"\"\n"
                    "          python scripts/probe_sample.py --allow-run \"${args[@]}\" \\\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("registered live probe command" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_env_ignores_commented_binding_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}",
                    "ALLOW_PRODUCTION_INPUT: true\n"
                    "          # ALLOW_PRODUCTION_INPUT: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("ALLOW_PRODUCTION_INPUT" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_flag_must_be_conditionally_appended(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python scripts/probe_sample.py --allow-run \"${args[@]}\" \\",
                    "python scripts/probe_sample.py --allow-run --allow-production \\",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("--allow-production" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_ignores_heredoc_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n",
                    "          cat <<'EOF'\n"
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "          EOF\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("--allow-production" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_production_override_ignores_numeric_heredoc_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            _add_safe_production_override(workflow)
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n",
                    "          cat <<'123EOF'\n"
                    "          if [[ \"${ALLOW_PRODUCTION_INPUT}\" == \"true\" ]]; then\n"
                    "            args+=(--allow-production)\n"
                    "          fi\n"
                    "          123EOF\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("--allow-production" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_production_override_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_rejects_duplicate_top_level_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + "\nconcurrency:\n"
                "  group: unsafe-${{ github.run_id }}\n"
                "  cancel-in-progress: true\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate top-level `concurrency` key" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_top_level_duplicate", result.to_dict()["error_codes"])

    def test_workflow_rejects_duplicate_top_level_jobs_scalar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8") + "\njobs: disabled\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate top-level `jobs` key" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_top_level_duplicate", result.to_dict()["error_codes"])

    def test_gate_tokens_must_pair_dispatch_and_schedule_gates(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["dispatch_or_schedule_gate_tokens"] = [
            "allow_live_sample",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("scheduled vars gate token" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_gate_token_pair_invalid", result.to_dict()["error_codes"])

    def test_gate_tokens_reject_unsupported_tokens(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["dispatch_or_schedule_gate_tokens"] = [
            "allow_live_sample",
            "WIII_SAMPLE_EVIDENCE_ENABLED",
            "sample_evidence_enabled",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unsupported gate token" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_gate_token_unsupported", result.to_dict()["error_codes"])

    def test_gate_tokens_reject_malformed_dispatch_gate_shape(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["dispatch_or_schedule_gate_tokens"] = [
            "allow-live-sample",
            "WIII_SAMPLE_EVIDENCE_ENABLED",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unsupported gate token" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_gate_token_unsupported", result.to_dict()["error_codes"])
        self.assertIn("registry_gate_token_pair_invalid", result.to_dict()["error_codes"])

    def test_gate_tokens_reject_malformed_schedule_gate_shape(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["dispatch_or_schedule_gate_tokens"] = [
            "allow_live_sample",
            "WIII_sample_evidence_enabled",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unsupported gate token" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_gate_token_unsupported", result.to_dict()["error_codes"])
        self.assertIn("registry_gate_token_pair_invalid", result.to_dict()["error_codes"])

    def test_workflow_dispatch_gate_must_be_boolean_default_false_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "        type: boolean\n        default: false",
                    "        type: string\n        default: true",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.gates.allow_live_sample" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_dispatch_input_rejects_duplicate_gate_name_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      allow_live_sample:\n"
                    "        description: \"Run the sample live evidence probe.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: false\n",
                    "      allow_live_sample:\n"
                    "        description: \"Run the sample live evidence probe.\"\n"
                    "        required: true\n"
                    "        type: boolean\n"
                    "        default: false\n"
                    "      allow_live_sample:\n"
                    "        description: \"Overridden unsafe default.\"\n"
                    "        required: false\n"
                    "        type: boolean\n"
                    "        default: true\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate workflow_dispatch input name" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_dispatch_input_duplicate", result.to_dict()["error_codes"])

    def test_workflow_dispatch_input_rejects_duplicate_schema_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "        type: boolean\n        default: false",
                    "        type: boolean\n"
                    "        default: false\n"
                    "        default: false",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate workflow_dispatch input field(s): default" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_dispatch_input_duplicate", result.to_dict()["error_codes"])

    def test_workflow_dispatch_input_schema_ignores_commented_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "        type: boolean\n        default: false",
                    "        type: string\n"
                    "        default: true\n"
                    "        # type: boolean\n"
                    "        # default: false",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.gates.allow_live_sample" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_gate_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_dispatch_input_ignores_fake_event_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    """  workflow_dispatch:
    inputs:
      allow_live_sample:
        description: "Run the sample live evidence probe."
        required: true
        type: boolean
        default: false
""",
                    "",
                )
                + """
fake_events:
  workflow_dispatch:
    inputs:
      allow_live_sample:
        description: "Run the sample live evidence probe."
        required: true
        type: boolean
        default: false
""",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.gates.allow_live_sample" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_gate_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_rejects_duplicate_workflow_dispatch_event_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "permissions:\n",
                    "  workflow_dispatch:\n"
                    "    inputs:\n"
                    "      allow_live_sample:\n"
                    "        description: \"Overridden unsafe default.\"\n"
                    "        required: false\n"
                    "        type: boolean\n"
                    "        default: true\n"
                    "permissions:\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate workflow event name(s): workflow_dispatch" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_event_duplicate", result.to_dict()["error_codes"])

    def test_workflow_dispatch_gate_must_guard_manual_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "inputs.allow_live_sample == true",
                    "inputs.allow_live_sample != false",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.gates.allow_live_sample" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_dispatch_gate_guard_ignores_workflow_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "inputs.allow_live_sample == true",
                    "inputs.allow_live_sample != false",
                    1,
                )
                + "\n# spoofed manual guard: inputs.allow_live_sample == true\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.gates.allow_live_sample" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_gate_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_schedule_gate_must_use_registered_vars_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1'",
                    "env.WIII_SAMPLE_EVIDENCE_ENABLED == '1'",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "workflow.gates.WIII_SAMPLE_EVIDENCE_ENABLED" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_workflow_schedule_gate_guard_ignores_workflow_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1'",
                    "env.WIII_SAMPLE_EVIDENCE_ENABLED == '1'",
                    1,
                )
                + "\n# spoofed schedule guard: vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1'\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "workflow.gates.WIII_SAMPLE_EVIDENCE_ENABLED" in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn("workflow_gate_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_live_env_flag_must_be_enabled_in_job_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '      WIII_LIVE_SAMPLE_PROBE: "1"\n',
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_probe.WIII_LIVE_SAMPLE_PROBE" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_live_env_flag_rejects_duplicate_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '      WIII_LIVE_SAMPLE_PROBE: "1"\n',
                    '      WIII_LIVE_SAMPLE_PROBE: "1"\n'
                    '      WIII_LIVE_SAMPLE_PROBE: "0"\n',
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow env maps must not duplicate" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_env_flag_duplicate", result.to_dict()["error_codes"])

    def test_workflow_live_env_flag_ignores_run_block_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '    env:\n'
                    '      WIII_LIVE_SAMPLE_PROBE: "1"\n'
                    "    timeout-minutes: 15\n"
                    "    steps:\n",
                    "    timeout-minutes: 15\n"
                    "    steps:\n"
                    "      - run: |\n"
                    "          echo not-live\n"
                    '          WIII_LIVE_SAMPLE_PROBE: "1"\n',
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_probe.WIII_LIVE_SAMPLE_PROBE" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_probe_binding_invalid", result.to_dict()["error_codes"])

    def test_live_env_flags_must_use_wiii_uppercase_shape(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["live_env_flags"] = ["LIVE_SAMPLE_PROBE"]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("live_env_flags entries must be uppercase" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_env_flag_invalid", result.to_dict()["error_codes"])

    def test_live_env_flags_must_not_reuse_scheduled_gate_tokens(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["live_env_flags"] = ["WIII_SAMPLE_EVIDENCE_ENABLED"]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not reuse scheduled evidence gate tokens" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_env_flag_invalid", result.to_dict()["error_codes"])

    def test_workflow_guard_token_must_be_bound_to_probe_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python scripts/probe_sample.py --allow-run --out sample-evidence.json",
                    "python scripts/probe_sample.py --out sample-evidence.json",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_probe.--allow-run" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_live_probe_invocation_requires_bounded_path_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python scripts/probe_sample.py --allow-run --out sample-evidence.json",
                    "python scripts/probe_sample.py.disabled --allow-run --out sample-evidence.json",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("missing workflow step invoking" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_probe_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_live_probe_invocation_ignores_commented_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                    "      - run: # python scripts/probe_sample.py --allow-run --out sample-evidence.json\n"
                    "      - run: echo skipped\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("missing workflow step invoking" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_probe_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_live_probe_invocation_rejects_echoed_probe_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python scripts/probe_sample.py --allow-run --out sample-evidence.json",
                    "echo python scripts/probe_sample.py --allow-run --out sample-evidence.json",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("missing workflow step invoking" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_probe_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_live_probe_invocation_rejects_python_module_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python scripts/probe_sample.py --allow-run --out sample-evidence.json",
                    "python -m pip install scripts/probe_sample.py "
                    "--allow-run --out sample-evidence.json",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("missing workflow step invoking" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_probe_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_probe_guard_must_be_on_probe_command_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                    "      - run: |\n"
                    "          set -euo pipefail\n"
                    "          python scripts/probe_sample.py --out sample-evidence.json\n"
                    "          echo --allow-run\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_probe.--allow-run" in error for error in result.errors),
            result.errors,
        )

    def test_python_probe_out_artifact_must_be_on_probe_command_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                    "      - run: |\n"
                    "          set -euo pipefail\n"
                    "          python scripts/probe_sample.py --allow-run\n"
                    "          echo --out sample-evidence.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_probe.--out" in error for error in result.errors),
            result.errors,
        )

    def test_python_probe_out_artifact_must_be_probe_argument_not_shell_suffix(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "python scripts/probe_sample.py --allow-run --out sample-evidence.json",
                    "python scripts/probe_sample.py --allow-run; "
                    "echo --out sample-evidence.json",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("missing workflow step invoking" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_probe_binding_invalid", result.to_dict()["error_codes"])

    def test_live_guard_tokens_must_be_allow_cli_flags(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["live_guard_tokens"] = ["allow-run"]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("live_guard_tokens entries must be explicit" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("registry_live_guard_token_invalid", result.to_dict()["error_codes"])

    def test_live_probe_multiline_run_must_use_strict_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                    "      - run: |\n"
                    "          python scripts/probe_sample.py --allow-run "
                    "--out sample-evidence.json\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("set -euo pipefail" in error for error in result.errors),
            result.errors,
        )

    def test_python_probe_out_artifact_must_be_bound_to_probe_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "--out sample-evidence.json",
                    "--out other-evidence.json",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_probe.--out" in error for error in result.errors),
            result.errors,
        )

    def test_python_probe_out_artifact_requires_bounded_path_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "--out sample-evidence.json",
                    "--out sample-evidence.json.disabled",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_probe.--out" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_probe_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_requirement_must_bind_probe_validation_and_upload_in_one_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            upload_step = """      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: always()
        with:
          name: sample-evidence-${{ github.run_id }}
          path: sample-evidence.json
          if-no-files-found: error
          retention-days: 30
"""
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(upload_step, "")
                + """
  upload:
    timeout-minutes: 15
    steps:
"""
                + upload_step,
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.requirement_job" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_must_validate_artifact_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            validation_marker = (
                "      - run: |\n"
                "          python tools/wiii_self_harness/validate_runtime_evidence_artifact.py"
            )
            upload_step = """      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: always()
        with:
          name: sample-evidence-${{ github.run_id }}
          path: sample-evidence.json
          if-no-files-found: error
          retention-days: 30
"""
            workflow_text = workflow.read_text(encoding="utf-8").replace(upload_step, "")
            workflow.write_text(
                workflow_text.replace(validation_marker, upload_step + validation_marker),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("probe-validation-upload order" in error for error in result.errors),
            result.errors,
        )

    def test_live_evidence_job_must_checkout_before_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            checkout_step = """      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          persist-credentials: false
"""
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    checkout_step + "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n",
                    "      - run: python scripts/probe_sample.py --allow-run --out sample-evidence.json\n" + checkout_step,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("checkout before probe" in error for error in result.errors),
            result.errors,
        )

    def test_live_evidence_job_must_run_after_contract_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "    needs: contract\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_contract" in error for error in result.errors),
            result.errors,
        )

    def test_contract_dependency_must_run_registered_contract_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                .replace(
                    "      - run: python -m pytest tests/test_probe_sample.py -q --tb=short",
                    "      - run: python -m pytest tests/other_test.py -q --tb=short",
                    1,
                )
                + """
  unrelated_tests:
    timeout-minutes: 15
    steps:
      - run: python -m pytest tests/test_probe_sample.py -q --tb=short
""",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("needs: contract" in error for error in result.errors),
            result.errors,
        )

    def test_contract_dependency_must_checkout_before_registered_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            checkout_step = """      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          persist-credentials: false
"""
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "    steps:\n"
                    + checkout_step
                    + "      - run: python -m pytest tests/test_probe_sample.py -q --tb=short\n",
                    "    steps:\n"
                    "      - run: python -m pytest tests/test_probe_sample.py -q --tb=short\n"
                    + checkout_step,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("contract` job must checkout" in error for error in result.errors),
            result.errors,
        )

    def test_contract_dependency_must_not_be_conditionally_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "    runs-on: ubuntu-latest\n    timeout-minutes: 15",
                    "    runs-on: ubuntu-latest\n    if: ${{ github.event_name == 'workflow_dispatch' }}\n    timeout-minutes: 15",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("job-level if condition" in error for error in result.errors),
            result.errors,
        )

    def test_live_evidence_job_must_bind_registered_gate_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "inputs.allow_live_sample == true",
                    "inputs.other_gate == true",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_gates" in error for error in result.errors),
            result.errors,
        )

    def test_live_evidence_job_must_bind_gate_tokens_in_job_if(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "inputs.allow_live_sample == true) ||",
                    "inputs.other_gate == true) ||",
                )
                + "\n# workflow-wide mention is not enough: inputs.allow_live_sample == true\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_gates" in error for error in result.errors),
            result.errors,
        )

    def test_live_evidence_job_accepts_outer_parentheses_on_registered_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "(github.event_name == 'workflow_dispatch' && "
                    "inputs.allow_live_sample == true) ||\n"
                    "        (github.event_name == 'schedule' && "
                    "vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1')",
                    "((github.event_name == 'workflow_dispatch' && "
                    "inputs.allow_live_sample == true) ||\n"
                    "        (github.event_name == 'schedule' && "
                    "vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1'))",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_live_evidence_job_accepts_schedule_first_registered_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "(github.event_name == 'workflow_dispatch' && "
                    "inputs.allow_live_sample == true) ||\n"
                    "        (github.event_name == 'schedule' && "
                    "vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1')",
                    "(github.event_name == 'schedule' && "
                    "vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1') ||\n"
                    "        (github.event_name == 'workflow_dispatch' && "
                    "inputs.allow_live_sample == true)",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertTrue(result.ok, result.errors)

    def test_live_evidence_job_rejects_extra_push_gate_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "(github.event_name == 'schedule' && "
                    "vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1')",
                    "(github.event_name == 'schedule' && "
                    "vars.WIII_SAMPLE_EVIDENCE_ENABLED == '1') || "
                    "github.event_name == 'push'",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.live_gates" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_gate_binding_invalid", result.to_dict()["error_codes"])

    def test_workflow_action_refs_must_be_pinned_to_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                    "actions/checkout@v6",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.actions" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_action_refs_must_stay_on_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                    "actions/cache@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unsupported workflow uses action" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_uses_rejects_third_party_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                    "third-party/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unsupported workflow uses action" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_paths_must_cover_self_harness_probe_and_contract_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '      - "tools/wiii_self_harness/**"\n',
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.paths" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_paths_must_cover_runtime_evidence_output_helper_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '      - "tests/test_runtime_evidence_output.py"\n',
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("runtime_evidence_output.py" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_path_filter_missing",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_workflow_must_run_runtime_evidence_output_helper_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: python -m pytest tests/test_runtime_evidence_output.py -q --tb=short\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("runtime evidence output helper test" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_output_helper_contract_invalid",
            result.to_dict()["error_codes"],
        )

    def test_mjs_probe_workflow_must_run_runtime_evidence_output_helper_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_mjs_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "      - run: node scripts/test-runtime-evidence-output.mjs\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_mjs_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("test-runtime-evidence-output.mjs" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "workflow_output_helper_contract_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_paths_must_cover_push_and_pull_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    """  push:
    paths:
      - ".github/workflows/sample-evidence.yml"
      - "tools/wiii_self_harness/**"
      - "scripts/probe_sample.py"
      - "scripts/runtime_evidence_output.py"
      - "tests/test_probe_sample.py"
      - "tests/test_runtime_evidence_output.py"
""",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.paths.push" in error for error in result.errors),
            result.errors,
        )

    def test_workflow_paths_ignore_fake_event_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    """  push:
    paths:
      - ".github/workflows/sample-evidence.yml"
      - "tools/wiii_self_harness/**"
      - "scripts/probe_sample.py"
      - "scripts/runtime_evidence_output.py"
      - "tests/test_probe_sample.py"
      - "tests/test_runtime_evidence_output.py"
""",
                    "",
                )
                + """
fake_events:
  push:
    paths:
      - ".github/workflows/sample-evidence.yml"
      - "tools/wiii_self_harness/**"
      - "scripts/probe_sample.py"
      - "scripts/runtime_evidence_output.py"
      - "tests/test_probe_sample.py"
      - "tests/test_runtime_evidence_output.py"
""",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.paths.push" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_path_filter_missing", result.to_dict()["error_codes"])

    def test_workflow_paths_reject_duplicate_push_paths_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "  schedule:\n",
                    "    paths:\n"
                    "      - \"docs-only/**\"\n"
                    "  schedule:\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.paths.push" in error for error in result.errors),
            result.errors,
        )
        self.assertTrue(
            any("duplicate event filter field(s): paths" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_path_filter_duplicate", result.to_dict()["error_codes"])

    def test_workflow_paths_reject_duplicate_pull_request_paths_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "  push:\n",
                    "    paths:\n"
                    "      - \"docs-only/**\"\n"
                    "  push:\n",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("workflow.paths.pull_request" in error for error in result.errors),
            result.errors,
        )
        self.assertTrue(
            any("duplicate event filter field(s): paths" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_path_filter_duplicate", result.to_dict()["error_codes"])

    def test_workflow_paths_reject_paths_ignore_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "  push:\n"
                    "    paths:\n",
                    "  push:\n"
                    "    paths-ignore:\n"
                    "      - \"scripts/**\"\n"
                    "    paths:\n",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("unsupported event filter field(s): paths-ignore" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_path_filter_invalid", result.to_dict()["error_codes"])

    def test_workflow_paths_reject_branch_filter_without_main(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "  pull_request:\n"
                    "    paths:\n",
                    "  pull_request:\n"
                    "    branches: [release]\n"
                    "    paths:\n",
                    1,
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("branches filter must include 'main'" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_path_filter_invalid", result.to_dict()["error_codes"])

    def test_workflow_rejects_duplicate_push_event_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "permissions:\n",
                    "  push:\n"
                    "    branches:\n"
                    "      - main\n"
                    "permissions:\n",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate workflow event name(s): push" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("workflow_event_duplicate", result.to_dict()["error_codes"])

    def test_python_probe_workflow_requires_out_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(" --out sample-evidence.json", ""),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("--out" in error for error in result.errors), result.errors)

    def test_python_probe_out_must_be_argparse_cli_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8").replace(
                    '    parser.add_argument("--out")',
                    '    # parser.add_argument("--out")',
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must define `--out` as an argparse CLI flag" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_argument_invalid",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_requires_utf8_output_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8").replace("emit_json_payload", "json_print"),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("emit_json_payload" in error for error in result.errors), result.errors)

    def test_python_probe_must_import_shared_utf8_output_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8").replace(
                    "from runtime_evidence_output import emit_json_payload",
                    "def emit_json_payload(payload, out_path=None):\n    pass",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must import emit_json_payload from runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_helper_invalid",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_call_output_helper_with_out_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8").replace(
                    'emit_json_payload({"status": "pass"}, args.out)',
                    'emit_json_payload({"status": "pass"})',
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must call emit_json_payload with an output path argument" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_output_helper_invalid",
            result.to_dict()["error_codes"],
        )

    def test_python_runtime_evidence_output_helper_must_use_atomic_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            helper_path = repo_root / "scripts/runtime_evidence_output.py"
            helper_path.write_text(
                helper_path.read_text(encoding="utf-8").replace(
                    "        os.replace(temp_path, out_path)\n",
                    "",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("runtime evidence output helper" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_output_helper_atomic_invalid",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_side_channel(path):\n"
                + "    path.write_text('{\"status\":\"pass\"}', encoding='utf-8')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_json_dump_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_json_dump(handle):\n"
                + "    import json\n"
                + "    json.dump({'status': 'pass'}, handle)\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_json_dump_alias_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_json_dump_alias(handle):\n"
                + "    import json as json_module\n"
                + "    json_module.dump({'status': 'pass'}, handle)\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_json_dump_from_import_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_json_dump_from_import(handle):\n"
                + "    from json import dump as dump_json\n"
                + "    dump_json({'status': 'pass'}, handle)\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_open_side_channel_evidence_file_for_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_open(path):\n"
                + "    with open(path, 'w', encoding='utf-8') as handle:\n"
                + "        handle.write('{\"status\":\"pass\"}')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_open_side_channel_with_constant_write_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_open_constant_mode(path):\n"
                + "    mode = 'w'\n"
                + "    with open(path, mode, encoding='utf-8') as handle:\n"
                + "        handle.write('{\"status\":\"pass\"}')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_io_open_alias_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_io_open(path):\n"
                + "    from io import open as io_open\n"
                + "    mode = 'w'\n"
                + "    with io_open(path, mode, encoding='utf-8') as handle:\n"
                + "        handle.write('{\"status\":\"pass\"}')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_codecs_open_alias_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_codecs_open(path):\n"
                + "    from codecs import open as codecs_open\n"
                + "    mode = 'a'\n"
                + "    with codecs_open(path, mode, encoding='utf-8') as handle:\n"
                + "        handle.write('{\"status\":\"pass\"}')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_builtins_open_alias_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_builtins_open(path):\n"
                + "    from builtins import open as builtin_open\n"
                + "    mode = 'w'\n"
                + "    with builtin_open(path, mode, encoding='utf-8') as handle:\n"
                + "        handle.write('{\"status\":\"pass\"}')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_path_open_side_channel_with_constant_write_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_path_open_constant_mode(path):\n"
                + "    mode = 'a'\n"
                + "    with path.open(mode=mode, encoding='utf-8') as handle:\n"
                + "        handle.write('{\"status\":\"pass\"}')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_os_write_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_os_write(path):\n"
                + "    import os as operating_system\n"
                + "    fd = operating_system.open(path, operating_system.O_WRONLY | operating_system.O_CREAT)\n"
                + "    operating_system.write(fd, b'{\"status\":\"pass\"}')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_python_probe_must_not_os_write_from_import_side_channel_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            probe = repo_root / "scripts/probe_sample.py"
            probe.write_text(
                probe.read_text(encoding="utf-8")
                + "\ndef leak_os_write_from_import(path):\n"
                + "    from os import O_CREAT, O_WRONLY, open as os_open, write as os_write\n"
                + "    fd = os_open(path, O_WRONLY | O_CREAT)\n"
                + "    os_write(fd, b'{\"status\":\"pass\"}')\n",
                encoding="utf-8",
            )

            result = registry.validate_registry(
                _sample_registry(),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not write evidence files outside runtime_evidence_output" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_probe_raw_file_write_forbidden",
            result.to_dict()["error_codes"],
        )

    def test_repo_escaping_path_fails(self) -> None:
        data = copy.deepcopy(_sample_registry())
        data["requirements"][0]["workflow"] = "../outside.yml"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                json.loads(json.dumps(data)),
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("repo-relative" in error for error in result.errors), result.errors)

    def test_duplicate_artifact_name_fails(self) -> None:
        data = _sample_registry()
        duplicate = copy.deepcopy(data["requirements"][0])
        duplicate["id"] = "sample-runtime-evidence-copy"
        data["requirements"].append(duplicate)

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("duplicate artifact name" in error for error in result.errors), result.errors)

    def test_artifact_token_must_include_run_id_suffix(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["artifact_tokens"] = ["sample-evidence-latest"]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("artifact token must be lowercase kebab-case" in error for error in result.errors),
            result.errors,
        )

    def test_artifact_token_must_identify_requirement_or_artifact(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["artifact_tokens"] = [
            "opaque-evidence-${{ github.run_id }}"
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)
            workflow = repo_root / ".github/workflows/sample-evidence.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "sample-evidence-${{ github.run_id }}",
                    "opaque-evidence-${{ github.run_id }}",
                ),
                encoding="utf-8",
            )

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("artifact token must include requirement id" in error for error in result.errors),
            result.errors,
        )
        self.assertIn(
            "registry_artifact_token_identity_invalid",
            result.to_dict()["error_codes"],
        )

    def test_duplicate_artifact_token_fails(self) -> None:
        data = _sample_registry()
        duplicate = copy.deepcopy(data["requirements"][0])
        duplicate["id"] = "sample-runtime-evidence-copy"
        duplicate["artifact"] = "sample-copy-evidence.json"
        data["requirements"].append(duplicate)

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("duplicate artifact token" in error for error in result.errors), result.errors)

    def test_non_json_artifact_name_fails(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["artifact"] = "sample-evidence.txt"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("JSON file" in error for error in result.errors), result.errors)

    def test_artifact_name_must_not_be_glob_pattern(self) -> None:
        data = _sample_registry()
        data["requirements"][0]["artifact"] = "sample-*.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_sample_repo(repo_root)

            result = registry.validate_registry(
                data,
                repo_root=repo_root,
                registry_path=repo_root / "registry.json",
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("safe lowercase kebab-case JSON file name" in error for error in result.errors),
            result.errors,
        )


if __name__ == "__main__":
    unittest.main()
