#!/usr/bin/env python3
"""Validate Wiii runtime evidence registry obligations.

The validator is intentionally text-based and standard-library-only so it can
run in the lightweight Self-Harness workflow. It does not execute live probes;
it proves that each registered evidence artifact remains tied to a workflow,
probe, contract test, schema, upload step, and explicit live-run guard.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import hashlib
import json
import posixpath
from pathlib import Path, PurePosixPath
import re
import shlex
import sys
from typing import Any

from safe_report_output import safe_write_report_text
from strict_json import load_strict_json_file


REGISTRY_NAME = "Wiii Runtime Evidence Registry"
REGISTRY_VALIDATION_SCHEMA_VERSION = "wiii.runtime_evidence_registry_validation.v1"
REGISTRY_OUTPUT_PATH_DIRECTORY_ERROR = (
    "registry validation output path must not be a directory"
)
REGISTRY_OUTPUT_PATH_SYMLINK_ERROR = (
    "registry validation output path must not be a symlink"
)
REGISTRY_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "registry validation output path parent must not be a symlink"
)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = Path(__file__).with_name("runtime_evidence_registry.json")
CANONICAL_ARTIFACT_VALIDATOR_PATHS = {
    "tools/wiii_self_harness/validate_runtime_evidence_artifact.py",
    "../tools/wiii_self_harness/validate_runtime_evidence_artifact.py",
}
VALID_LAYERS = {"Wiii Core", "Wiii Living", "Wiii Host", "Wiii Org", "Wiii Data"}
ALLOWED_REGISTRY_KEYS = {"registry", "version", "description", "requirements"}
ALLOWED_REQUIREMENT_KEYS = {
    "id",
    "title",
    "layer",
    "workflow",
    "artifact",
    "schema_version",
    "freshness",
    "payload_schema_field",
    "forbidden_payload_tokens",
    "forbidden_payload_regexes",
    "payload_checks",
    "probe",
    "contract_tests",
    "live_env_flags",
    "live_guard_tokens",
    "dispatch_or_schedule_gate_tokens",
    "artifact_tokens",
    "diagnostic_uploads",
}
ALLOWED_DIAGNOSTIC_UPLOAD_KEYS = {
    "artifact",
    "path",
    "artifact_tokens",
    "if_no_files_found",
    "retention_days",
}
ALLOWED_FRESHNESS_KEYS = {"timestamp_path", "max_age_hours"}
ALLOWED_PAYLOAD_CHECK_KEYS = {
    "path",
    "equals",
    "min",
    "sorted_equals",
    "length_equals_path",
    "when",
}
ALLOWED_PAYLOAD_CHECK_WHEN_KEYS = {"path", "equals", "not_equals"}
DOT_PATH_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")
WILDCARD_DOT_PATH_RE = re.compile(r"^(?:[A-Za-z0-9_]+|\*)(?:\.(?:[A-Za-z0-9_]+|\*))*$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
ARTIFACT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.json$")
ARTIFACT_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*-\$\{\{ github\.run_id \}\}$")
LIVE_ENV_FLAG_RE = re.compile(r"^WIII_[A-Z0-9_]+$")
LIVE_GUARD_TOKEN_RE = re.compile(r"^--allow-[a-z0-9][a-z0-9-]*$")
DISPATCH_GATE_TOKEN_RE = re.compile(r"^(?:allow|run)_[a-z0-9]+(?:_[a-z0-9]+)*$")
SCHEDULE_GATE_TOKEN_RE = re.compile(
    r"^WIII_[A-Z0-9]+(?:_[A-Z0-9]+)*_EVIDENCE_ENABLED$"
)
SECRET_REFERENCE_RE = re.compile(r"\bsecrets\s*(?:\.|\[)")
SCHEMA_RE = re.compile(r"^wiii\.[a-z0-9_]+\.v[0-9]+$")
PINNED_ACTION_REF_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_ACTION_NAMES = {
    "actions/checkout",
    "actions/setup-node",
    "actions/setup-python",
    "actions/upload-artifact",
}
ALLOWED_PROBE_SUFFIXES = {".py", ".mjs"}
ALLOWED_TYPESCRIPT_TEST_SUFFIXES = (".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx")
ALLOWED_IDENTIFIER_STRATEGIES = {
    "aggregate_counts_only",
    "hash_only",
    "hash_or_count_only",
    "hashes_and_counts",
    "presence_hash_or_count_only",
    "status_only",
}
BASELINE_FORBIDDEN_PAYLOAD_TOKENS = {"api_key", "access_token", "authorization"}
EXPECTED_CONCURRENCY_GROUP = (
    "${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}"
)
EXPECTED_CONCURRENCY_CANCEL = "${{ github.event_name == 'pull_request' }}"
EXPECTED_LIVE_EVIDENCE_ENVIRONMENT = "wiii-runtime-evidence"
PRODUCTION_OVERRIDE_INPUT = "allow_production"
PRODUCTION_OVERRIDE_ENV = "ALLOW_PRODUCTION_INPUT"
PRODUCTION_OVERRIDE_FLAG = "--allow-production"
PRODUCTION_OVERRIDE_ENV_VALUE = (
    "${{ github.event_name == 'workflow_dispatch' && inputs.allow_production || false }}"
)
PRODUCTION_OVERRIDE_ENV_BINDING = (
    f"ALLOW_PRODUCTION_INPUT: {PRODUCTION_OVERRIDE_ENV_VALUE}"
)
PRODUCTION_OVERRIDE_GUARD_LINE = 'if [[ "${ALLOW_PRODUCTION_INPUT}" == "true" ]]; then'
PRODUCTION_OVERRIDE_APPEND_LINE = "args+=(--allow-production)"
PRODUCTION_OVERRIDE_ARGS_EXPANSION = "${args[@]}"
PRODUCTION_OVERRIDE_REQUIRED = "production_override_required"
PRODUCTION_OVERRIDE_DUPLICATE_INPUT_FIELD_MESSAGE = (
    "allow_production input must not duplicate workflow_dispatch input field(s)"
)
UNSUPPORTED_GATE_TOKEN_SUMMARY = "unsupported gate token(s)"
PYTHON_RUNTIME_EVIDENCE_HELPER_ATOMIC_TOKENS = [
    "emit_json_payload",
    "validate_output_path",
    "tempfile.NamedTemporaryFile",
    "delete=False",
    "dir=out_path.parent",
    "os.fsync",
    "os.replace",
    "suffix=\".tmp\"",
]
MJS_RUNTIME_EVIDENCE_HELPER_ATOMIC_TOKENS = [
    "writeJsonFile",
    "validateOutputPath",
    "openSync(tempPath, \"wx\", 0o600)",
    "writeFileSync(fd,",
    "fsyncSync(fd)",
    "renameSync(tempPath, resolved)",
    "rmSync",
    "randomUUID",
    ".tmp",
]
PYTHON_RUNTIME_EVIDENCE_HELPER_TEST_NAME = "test_runtime_evidence_output.py"
MJS_RUNTIME_EVIDENCE_HELPER_TEST_NAME = "test-runtime-evidence-output.mjs"


@dataclass(frozen=True)
class RegistryResult:
    validation_schema_version: str
    registry: str
    registry_version: int | None
    registry_path: str
    registry_fingerprint_sha256: str
    requirement_count: int
    passed_checks: int
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


@dataclass(frozen=True)
class DiagnosticUploadSpec:
    requirement_id: str
    artifact: str
    path: str
    artifact_tokens: tuple[str, ...]
    if_no_files_found: str
    retention_days: int


class RegistryValidator:
    def __init__(self, *, repo_root: Path, registry_path: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.registry_path = registry_path.resolve()
        self.errors: list[str] = []
        self.passed_checks = 0

    def pass_check(self) -> None:
        self.passed_checks += 1

    def error(self, message: str) -> None:
        self.errors.append(message)

    def resolve_repo_path(self, raw_path: Any, *, context: str) -> Path | None:
        if not isinstance(raw_path, str) or not raw_path.strip():
            self.error(f"{context}: path must be a non-empty string")
            return None
        normalized = raw_path.replace("\\", "/").strip()
        posix_path = PurePosixPath(normalized)
        parts = posix_path.parts
        if (
            Path(normalized).is_absolute()
            or posix_path.is_absolute()
            or ".." in parts
            or (parts and ":" in parts[0])
        ):
            self.error(f"{context}: path must be repo-relative: {raw_path!r}")
            return None

        relative_path = Path(*parts)
        raw_candidate = self.repo_root / relative_path
        candidate = raw_candidate.resolve()
        try:
            candidate.relative_to(self.repo_root)
        except ValueError:
            self.error(f"{context}: path escapes repo root: {raw_path!r}")
            return None
        if _repo_relative_path_contains_symlink(self.repo_root, relative_path):
            self.error(f"{context}: path must not contain symlinks: {raw_path!r}")
            return None
        self.pass_check()
        return candidate

    def require_string(self, value: Any, field: str, *, context: str) -> str:
        if not isinstance(value, str) or not value.strip():
            self.error(f"{context}: `{field}` must be a non-empty string")
            return ""
        self.pass_check()
        return value.strip()

    def require_string_list(self, value: Any, field: str, *, context: str) -> list[str]:
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            self.error(f"{context}: `{field}` must be a non-empty string list")
            return []
        self.pass_check()
        values = [item.strip() for item in value]
        self.require_unique_string_values(values, field=field, context=context)
        return values

    def require_string_list_allow_empty(self, value: Any, field: str, *, context: str) -> list[str]:
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            self.error(f"{context}: `{field}` must be a string list")
            return []
        self.pass_check()
        return [item.strip() for item in value]

    def require_dot_path(
        self,
        value: str,
        field: str,
        *,
        context: str,
        allow_wildcard: bool = False,
    ) -> None:
        pattern = WILDCARD_DOT_PATH_RE if allow_wildcard else DOT_PATH_RE
        if pattern.match(value):
            self.pass_check()
            return
        wildcard_hint = " with `*` wildcard segments" if allow_wildcard else ""
        self.error(f"{context}: `{field}` must be dot-path syntax{wildcard_hint}")

    def require_json_scalar(self, value: Any, field: str, *, context: str) -> None:
        if value is None or isinstance(value, (dict, list)):
            self.error(f"{context}: {field} must be a non-null JSON scalar")
            return
        self.pass_check()

    def reject_unknown_keys(
        self,
        item: dict[str, Any],
        *,
        allowed_keys: set[str],
        context: str,
    ) -> None:
        unknown_keys = sorted(set(item) - allowed_keys)
        if unknown_keys:
            self.error(f"{context}: unknown field(s): {', '.join(unknown_keys)}")
            return
        self.pass_check()

    def require_unique_string_values(
        self,
        values: list[str],
        *,
        field: str,
        context: str,
    ) -> None:
        seen_values: set[str] = set()
        duplicate_values: list[str] = []
        for value in values:
            if value in seen_values and value not in duplicate_values:
                duplicate_values.append(value)
            seen_values.add(value)
        if duplicate_values:
            rendered = ", ".join(repr(value) for value in duplicate_values)
            self.error(f"{context}: `{field}` must not contain duplicate values: {rendered}")
            return
        self.pass_check()

    def require_unique_repo_path_values(
        self,
        values: list[str],
        *,
        field: str,
        context: str,
    ) -> None:
        seen_paths: dict[str, str] = {}
        duplicate_paths: list[tuple[str, str]] = []
        for value in values:
            normalized = _normalized_registry_path_key(value)
            previous = seen_paths.get(normalized)
            if previous is not None and (previous, value) not in duplicate_paths:
                duplicate_paths.append((previous, value))
                continue
            seen_paths[normalized] = value
        if duplicate_paths:
            rendered = ", ".join(
                f"{first!r} and {second!r}" for first, second in duplicate_paths
            )
            self.error(
                f"{context}: `{field}` must not contain duplicate normalized paths: "
                f"{rendered}"
            )
            return
        self.pass_check()

    def require_file_text(self, raw_path: Any, *, context: str) -> tuple[Path | None, str]:
        path = self.resolve_repo_path(raw_path, context=context)
        if path is None:
            return None, ""
        if not path.exists():
            self.error(f"{context}: file does not exist: {raw_path}")
            return path, ""
        if not path.is_file():
            self.error(f"{context}: path must be a file: {raw_path}")
            return path, ""
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            self.error(f"{context}: file is not UTF-8: {raw_path} ({exc})")
            return path, ""
        self.pass_check()
        return path, text

    def require_tokens(self, text: str, tokens: list[str], *, context: str) -> None:
        for token in tokens:
            if token not in text:
                self.error(f"{context}: missing token {token!r}")
            else:
                self.pass_check()

    def require_workflow_validation_binding(
        self,
        workflow_text: str,
        *,
        artifact: str,
        requirement_id: str,
        context: str,
    ) -> None:
        commands = _workflow_validator_commands(workflow_text)
        if not commands:
            self.error(f"{context}: missing validate_runtime_evidence_artifact.py command")
            return
        for command in commands:
            if _workflow_validation_command_matches(
                command,
                artifact=artifact,
                requirement_id=requirement_id,
            ):
                self.pass_check()
                return
        self.error(
            f"{context}: validate_runtime_evidence_artifact.py must validate "
            f"{artifact!r} with --requirement-id {requirement_id!r}"
        )

    def require_workflow_top_level_key_uniqueness(
        self,
        workflow_text: str,
        *,
        keys: list[str],
        context: str,
    ) -> None:
        for key in keys:
            count = _workflow_top_level_key_count(workflow_text, key)
            if count > 1:
                self.error(f"{context}: duplicate top-level `{key}` key")
            else:
                self.pass_check()

    def require_workflow_job_name_uniqueness(
        self,
        workflow_text: str,
        *,
        context: str,
    ) -> None:
        duplicate_names = _workflow_duplicate_job_names(workflow_text)
        if duplicate_names:
            rendered = ", ".join(duplicate_names)
            self.error(f"{context}: duplicate workflow job id(s): {rendered}")
        else:
            self.pass_check()

    def require_workflow_event_name_uniqueness(
        self,
        workflow_text: str,
        *,
        context: str,
    ) -> None:
        duplicate_names = _workflow_duplicate_event_names(workflow_text)
        if duplicate_names:
            rendered = ", ".join(duplicate_names)
            self.error(f"{context}: duplicate workflow event name(s): {rendered}")
        else:
            self.pass_check()

    def require_workflow_upload_binding(
        self,
        workflow_text: str,
        *,
        artifact: str,
        artifact_tokens: list[str],
        context: str,
    ) -> None:
        upload_blocks = _workflow_upload_artifact_blocks(workflow_text)
        if not upload_blocks:
            self.error(f"{context}: missing actions/upload-artifact step")
            return
        for token in artifact_tokens:
            matching_blocks = [
                block
                for block in upload_blocks
                if _workflow_upload_block_has_artifact_token(block, token)
            ]
            if not matching_blocks:
                self.error(
                    f"{context}: upload-artifact step must bind artifact token "
                    f"{token!r} to uploaded path {artifact!r}"
                )
                continue
            self.pass_check()
            for block in matching_blocks:
                duplicate_step_fields = _workflow_block_duplicate_direct_fields(
                    block,
                    ["uses", "if", "with"],
                )
                if duplicate_step_fields:
                    rendered = ", ".join(duplicate_step_fields)
                    self.error(
                        f"{context}: upload-artifact step for {token!r} must not "
                        f"duplicate step field(s): {rendered}"
                    )
                duplicate_with_fields = _workflow_mapping_duplicate_direct_fields(
                    _workflow_upload_with_block(block),
                    ["name", "path", "if-no-files-found", "retention-days"],
                )
                if duplicate_with_fields:
                    rendered = ", ".join(duplicate_with_fields)
                    self.error(
                        f"{context}: upload-artifact step for {token!r} must not "
                        f"duplicate with field(s): {rendered}"
                    )
                if _workflow_step_scalar_field_equals(block, "if", "always()"):
                    self.pass_check()
                else:
                    self.error(
                        f"{context}: upload-artifact step for {token!r} must use "
                        "if: always()"
                    )
                if _workflow_upload_with_scalar_field_equals(
                    block,
                    "if-no-files-found",
                    "error",
                ):
                    self.pass_check()
                else:
                    self.error(
                        f"{context}: upload-artifact step for {token!r} must use "
                        "if-no-files-found: error"
                    )
                retention_days = _workflow_upload_artifact_retention_days(block)
                if retention_days is None:
                    self.error(
                        f"{context}: upload-artifact step for {token!r} must set "
                        "retention-days"
                    )
                    continue
                if retention_days <= 0 or retention_days > 90:
                    self.error(
                        f"{context}: upload-artifact retention-days for {token!r} "
                        "must be between 1 and 90"
                    )
                else:
                    self.pass_check()
                upload_paths = _workflow_upload_artifact_paths(block)
                if not upload_paths:
                    self.error(
                        f"{context}: upload-artifact step for {token!r} must set "
                        "explicit JSON path(s)"
                    )
                elif _workflow_upload_paths_are_narrow_json(upload_paths, artifact):
                    self.pass_check()
                else:
                    self.error(
                        f"{context}: upload-artifact step for {token!r} must "
                        "upload exactly one explicit JSON evidence file named "
                        f"{artifact!r}"
                    )

    def require_workflow_diagnostic_upload_bindings(
        self,
        workflow_text: str,
        *,
        specs: list[DiagnosticUploadSpec],
        context: str,
    ) -> None:
        if not specs:
            return
        upload_blocks = _workflow_upload_artifact_blocks(workflow_text)
        for spec in specs:
            spec_context = f"{context}[{spec.artifact}]"
            if any(
                _workflow_job_has_diagnostic_validation_upload_order(
                    job_block,
                    spec=spec,
                )
                for _job_name, job_block in _workflow_job_blocks(workflow_text)
            ):
                self.pass_check()
            else:
                self.error(
                    f"{spec_context}: diagnostic upload workflow must validate "
                    "and clean up preflight JSON before upload in the same job"
                )
            for token in spec.artifact_tokens:
                matching_blocks = [
                    block
                    for block in upload_blocks
                    if _workflow_upload_block_has_artifact_token(block, token)
                ]
                if not matching_blocks:
                    self.error(
                        f"{spec_context}: upload-artifact step must bind diagnostic "
                        f"artifact token {token!r} to uploaded path {spec.path!r}"
                    )
                    continue
                self.pass_check()
                for block in matching_blocks:
                    duplicate_step_fields = _workflow_block_duplicate_direct_fields(
                        block,
                        ["uses", "if", "with"],
                    )
                    if duplicate_step_fields:
                        rendered = ", ".join(duplicate_step_fields)
                        self.error(
                            f"{spec_context}: upload-artifact step for {token!r} "
                            f"must not duplicate step field(s): {rendered}"
                        )
                    duplicate_with_fields = _workflow_mapping_duplicate_direct_fields(
                        _workflow_upload_with_block(block),
                        ["name", "path", "if-no-files-found", "retention-days"],
                    )
                    if duplicate_with_fields:
                        rendered = ", ".join(duplicate_with_fields)
                        self.error(
                            f"{spec_context}: upload-artifact step for {token!r} "
                            f"must not duplicate with field(s): {rendered}"
                        )
                    if _workflow_step_scalar_field_equals(block, "if", "always()"):
                        self.pass_check()
                    else:
                        self.error(
                            f"{spec_context}: upload-artifact step for {token!r} "
                            "must use if: always()"
                        )
                    if _workflow_upload_with_scalar_field_equals(
                        block,
                        "if-no-files-found",
                        spec.if_no_files_found,
                    ):
                        self.pass_check()
                    else:
                        self.error(
                            f"{spec_context}: upload-artifact step for {token!r} "
                            f"must use if-no-files-found: {spec.if_no_files_found}"
                        )
                    retention_days = _workflow_upload_artifact_retention_days(block)
                    if retention_days == spec.retention_days:
                        self.pass_check()
                    else:
                        self.error(
                            f"{spec_context}: upload-artifact retention-days for "
                            f"{token!r} must be {spec.retention_days}"
                        )
                    upload_paths = _workflow_upload_artifact_paths(block)
                    if not upload_paths:
                        self.error(
                            f"{spec_context}: upload-artifact step for {token!r} "
                            "must set explicit JSON path(s)"
                        )
                    elif _workflow_upload_paths_match_expected(
                        upload_paths,
                        artifact=spec.artifact,
                        expected_path=spec.path,
                    ):
                        self.pass_check()
                    else:
                        self.error(
                            f"{spec_context}: upload-artifact step for {token!r} "
                            f"must upload exactly {spec.path!r}"
                        )

    def require_workflow_checkout_hardening(self, workflow_text: str, *, context: str) -> None:
        checkout_blocks = _workflow_checkout_blocks(workflow_text)
        if not checkout_blocks:
            self.error(f"{context}: missing actions/checkout step")
            return
        for block in checkout_blocks:
            if _workflow_checkout_block_disables_persisted_credentials(block):
                self.pass_check()
            else:
                self.error(
                    f"{context}: actions/checkout steps must set "
                    "persist-credentials: false"
                )

    def require_workflow_job_timeouts(self, workflow_text: str, *, context: str) -> None:
        job_blocks = _workflow_job_blocks(workflow_text)
        if not job_blocks:
            self.error(f"{context}: missing workflow jobs")
            return
        for job_name, block in job_blocks:
            match = re.search(r"(?m)^\s{4}timeout-minutes:\s*([0-9]+)\s*$", block)
            if not match:
                self.error(f"{context}.{job_name}: missing timeout-minutes")
                continue
            timeout_minutes = int(match.group(1))
            if timeout_minutes <= 0 or timeout_minutes > 120:
                self.error(
                    f"{context}.{job_name}: timeout-minutes must be between 1 and 120"
                )
            else:
                self.pass_check()

    def require_workflow_job_control_key_uniqueness(
        self,
        workflow_text: str,
        *,
        context: str,
    ) -> None:
        job_blocks = _workflow_job_blocks(workflow_text)
        if not job_blocks:
            self.error(f"{context}: missing workflow jobs")
            return

        control_fields = [
            "runs-on",
            "environment",
            "timeout-minutes",
            "needs",
            "if",
            "env",
            "steps",
        ]
        for job_name, block in job_blocks:
            duplicates = _workflow_job_duplicate_direct_fields(block, control_fields)
            if duplicates:
                rendered = ", ".join(duplicates)
                self.error(
                    f"{context}.{job_name}: duplicate job-level field(s): {rendered}"
                )
            else:
                self.pass_check()

    def require_workflow_fail_closed_execution(self, workflow_text: str, *, context: str) -> None:
        errors = 0
        for line_number, line in enumerate(workflow_text.splitlines(), start=1):
            match = re.match(r"^\s+continue-on-error:\s*(.+?)\s*$", line)
            if not match:
                continue
            value = match.group(1).split("#", 1)[0].strip().strip("\"'")
            if value.casefold() == "false":
                continue
            errors += 1
            self.error(
                f"{context}: continue-on-error must not be enabled "
                f"(line {line_number})"
            )
        if errors == 0:
            self.pass_check()

    def require_workflow_no_shell_xtrace(self, workflow_text: str, *, context: str) -> None:
        errors = 0
        for block in _workflow_step_blocks(workflow_text):
            for line in _workflow_run_command_lines(block):
                if _workflow_command_enables_shell_xtrace(line):
                    errors += 1
                    self.error(
                        f"{context}: shell xtrace must not be enabled in "
                        f"registered evidence workflows: {line!r}"
                    )
        if errors == 0:
            self.pass_check()

    def require_workflow_permissions_hardening(self, workflow_text: str, *, context: str) -> None:
        if re.search(r"(?m)^[ \t]+permissions:", workflow_text):
            self.error(f"{context}: job-level permissions overrides are not allowed")
            return
        permissions_block = _workflow_top_level_block(workflow_text, "permissions")
        if not permissions_block:
            self.error(f"{context}: missing top-level permissions block")
            return
        if permissions_block[0] != "permissions:":
            self.error(f"{context}: top-level permissions must be a mapping")
            return
        permissions: dict[str, str] = {}
        for line in permissions_block[1:]:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.match(r"^  ([A-Za-z-]+):\s*(read|write|none)\s*$", line)
            if not match:
                self.error(f"{context}: unsupported permissions entry {line.strip()!r}")
                continue
            permissions[match.group(1)] = match.group(2)
        if permissions != {"contents": "read"}:
            self.error(f"{context}: permissions must be exactly `contents: read`")
        else:
            self.pass_check()

    def require_workflow_concurrency_guard(self, workflow_text: str, *, context: str) -> None:
        concurrency_block = _workflow_top_level_block(workflow_text, "concurrency")
        if not concurrency_block:
            self.error(f"{context}: missing top-level concurrency block")
            return
        if concurrency_block[0] != "concurrency:":
            self.error(f"{context}: top-level concurrency must be a mapping")
            return

        entries: dict[str, str] = {}
        for line in concurrency_block[1:]:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.match(r"^  (group|cancel-in-progress):\s*(.+?)\s*$", line)
            if not match:
                self.error(f"{context}: unsupported concurrency entry {line.strip()!r}")
                continue
            entries[match.group(1)] = match.group(2)

        group = entries.get("group")
        if group != EXPECTED_CONCURRENCY_GROUP:
            self.error(
                f"{context}: group must be "
                f"`group: {EXPECTED_CONCURRENCY_GROUP}`"
            )
        else:
            self.pass_check()

        cancel_in_progress = entries.get("cancel-in-progress")
        if cancel_in_progress != EXPECTED_CONCURRENCY_CANCEL:
            self.error(
                f"{context}: cancel-in-progress must be "
                f"`cancel-in-progress: {EXPECTED_CONCURRENCY_CANCEL}`"
            )
        else:
            self.pass_check()

    def require_registered_workflow_secret_scope(self, requirements: list[Any]) -> None:
        specs_by_workflow: dict[str, list[tuple[str, str, list[str], str, list[str], list[str], list[str]]]] = {}
        for item in requirements:
            if not isinstance(item, dict):
                continue
            workflow = item.get("workflow")
            requirement_id = item.get("id")
            artifact = item.get("artifact")
            artifact_tokens = item.get("artifact_tokens")
            probe = item.get("probe")
            live_flags = item.get("live_env_flags")
            guard_tokens = item.get("live_guard_tokens")
            gate_tokens = item.get("dispatch_or_schedule_gate_tokens")
            if (
                not isinstance(workflow, str)
                or not workflow.strip()
                or not isinstance(requirement_id, str)
                or not requirement_id.strip()
                or not isinstance(artifact, str)
                or not artifact.strip()
                or not isinstance(artifact_tokens, list)
                or not isinstance(probe, str)
                or not probe.strip()
                or not isinstance(live_flags, list)
                or not isinstance(guard_tokens, list)
                or not isinstance(gate_tokens, list)
            ):
                continue
            clean_artifact_tokens = [
                token.strip()
                for token in artifact_tokens
                if isinstance(token, str) and token.strip()
            ]
            clean_live_flags = [
                token.strip()
                for token in live_flags
                if isinstance(token, str) and token.strip()
            ]
            clean_guard_tokens = [
                token.strip()
                for token in guard_tokens
                if isinstance(token, str) and token.strip()
            ]
            clean_gate_tokens = [
                token.strip()
                for token in gate_tokens
                if isinstance(token, str) and token.strip()
            ]
            if clean_artifact_tokens and clean_live_flags and clean_guard_tokens and clean_gate_tokens:
                specs_by_workflow.setdefault(workflow.strip(), []).append(
                    (
                        requirement_id.strip(),
                        artifact.strip(),
                        clean_artifact_tokens,
                        probe.strip(),
                        clean_live_flags,
                        clean_guard_tokens,
                        clean_gate_tokens,
                    )
                )

        for workflow, requirement_specs in specs_by_workflow.items():
            _, workflow_text = self.require_file_text(
                workflow,
                context=f"workflow_secrets[{workflow}]",
            )
            if not workflow_text:
                continue
            self.require_workflow_secret_scope_hardening(
                workflow_text,
                requirement_specs=requirement_specs,
                context=f"workflow_secrets[{workflow}]",
            )

    def require_workflow_secret_scope_hardening(
        self,
        workflow_text: str,
        *,
        requirement_specs: list[tuple[str, str, list[str], str, list[str], list[str], list[str]]],
        context: str,
    ) -> None:
        violation_count = 0
        gate_tokens = sorted(
            {
                token
                for *_, spec_gate_tokens in requirement_specs
                for token in spec_gate_tokens
            }
        )
        pre_jobs_text = _workflow_text_before_jobs(workflow_text)
        if _workflow_text_references_secrets(pre_jobs_text):
            violation_count += 1
            self.error(f"{context}: top-level secret references are not allowed")

        for job_name, block in _workflow_job_blocks(workflow_text):
            if not _workflow_text_references_secrets(block):
                continue
            if not _workflow_job_if_matches_any_dispatch_or_schedule_gate_pair(
                block,
                gate_tokens,
            ):
                violation_count += 1
                self.error(
                    f"{context}.{job_name}: secret references must stay behind "
                    "a registered workflow_dispatch or schedule evidence gate"
                )
            if not _workflow_job_needs_contract(block):
                violation_count += 1
                self.error(
                    f"{context}.{job_name}: secret-bearing evidence job must "
                    "declare `needs: contract`"
                )
            if not any(
                _workflow_secret_job_matches_registered_requirement(
                    block,
                    requirement_id=requirement_id,
                    artifact=artifact,
                    artifact_tokens=artifact_tokens,
                    probe_path=probe_path,
                    live_flags=live_flags,
                    guard_tokens=guard_tokens,
                    gate_tokens=requirement_gate_tokens,
                )
                for (
                    requirement_id,
                    artifact,
                    artifact_tokens,
                    probe_path,
                    live_flags,
                    guard_tokens,
                    requirement_gate_tokens,
                ) in requirement_specs
            ):
                violation_count += 1
                self.error(
                    f"{context}.{job_name}: secret references must stay inside "
                    "a registered live evidence job"
                )

        if violation_count == 0:
            self.pass_check()

    def require_registered_workflow_production_override_guard(
        self,
        requirements: list[Any],
    ) -> None:
        workflows: dict[str, set[str]] = {}
        production_override_workflows: dict[str, set[str]] = {}
        for item in requirements:
            if not isinstance(item, dict):
                continue
            workflow = item.get("workflow")
            if isinstance(workflow, str) and workflow.strip():
                workflow_key = workflow.strip()
                workflows.setdefault(workflow_key, set())
                probe = item.get("probe")
                if isinstance(probe, str) and probe.strip():
                    probe_path = probe.strip()
                    workflows[workflow_key].add(probe_path)
                    _, probe_text = self.require_file_text(
                        probe_path,
                        context=(
                            "workflow_production_override"
                            f"[{workflow_key}].probe[{probe_path}]"
                        ),
                    )
                    if _probe_supports_production_override(probe_text):
                        production_override_workflows.setdefault(
                            workflow_key,
                            set(),
                        ).add(probe_path)

        for workflow, probe_paths in sorted(workflows.items()):
            _, workflow_text = self.require_file_text(
                workflow,
                context=f"workflow_production_override[{workflow}]",
            )
            if not workflow_text:
                continue
            self.require_workflow_production_override_guard(
                workflow_text,
                context=f"workflow_production_override[{workflow}]",
                registered_probe_paths=sorted(probe_paths),
                production_override_probe_paths=sorted(
                    production_override_workflows.get(workflow, set())
                ),
            )

    def require_workflow_production_override_guard(
        self,
        workflow_text: str,
        *,
        context: str,
        registered_probe_paths: list[str],
        production_override_probe_paths: list[str],
    ) -> None:
        if (
            PRODUCTION_OVERRIDE_INPUT not in workflow_text
            and PRODUCTION_OVERRIDE_ENV not in workflow_text
            and PRODUCTION_OVERRIDE_FLAG not in workflow_text
        ):
            if production_override_probe_paths:
                self.error(
                    f"{context}: {PRODUCTION_OVERRIDE_REQUIRED}: "
                    "registered probe supports --allow-production; "
                    "workflow must expose manual allow_production input and pass "
                    "guarded args to the live probe command"
                )
            else:
                self.pass_check()
            return

        input_block = _workflow_dispatch_input_block(
            workflow_text,
            PRODUCTION_OVERRIDE_INPUT,
        )
        duplicate_input_names = _workflow_dispatch_duplicate_input_names(workflow_text)
        if PRODUCTION_OVERRIDE_INPUT in duplicate_input_names:
            self.error(
                f"{context}: allow_production input must not duplicate "
                f"workflow_dispatch input name {PRODUCTION_OVERRIDE_INPUT!r}"
            )
        elif not input_block:
            self.error(f"{context}: missing workflow_dispatch allow_production input")
        else:
            duplicate_input_fields = _workflow_dispatch_input_duplicate_fields(
                input_block,
                ["description", "required", "type", "default"],
            )
            if duplicate_input_fields:
                rendered = ", ".join(duplicate_input_fields)
                self.error(
                    f"{context}: {PRODUCTION_OVERRIDE_DUPLICATE_INPUT_FIELD_MESSAGE}: {rendered}"
                )
            elif _workflow_dispatch_input_is_boolean_default_false(input_block):
                self.pass_check()
            else:
                self.error(
                    f"{context}: allow_production input must be boolean with default false"
                )

        if _workflow_block_has_duplicate_env_flag(workflow_text, PRODUCTION_OVERRIDE_ENV):
            self.error(
                f"{context}: ALLOW_PRODUCTION_INPUT must not duplicate workflow env binding"
            )
        elif _workflow_production_override_env_is_manual_only(workflow_text):
            if not _workflow_production_override_flag_steps_bind_env(workflow_text):
                self.error(
                    f"{context}: ALLOW_PRODUCTION_INPUT must be bound on each "
                    "--allow-production guard step"
                )
            elif not _workflow_production_override_flag_steps_invoke_registered_probe(
                workflow_text,
                registered_probe_paths,
            ):
                self.error(
                    f"{context}: --allow-production must be appended in a "
                    "registered live probe step"
                )
            elif not _workflow_production_override_flag_steps_pass_args_to_probe(
                workflow_text,
                registered_probe_paths,
            ):
                self.error(
                    f"{context}: --allow-production args must be passed to the "
                    "registered live probe command"
                )
            elif not _workflow_production_override_registered_probe_steps_pass_args(
                workflow_text,
                production_override_probe_paths,
            ):
                self.error(
                    f"{context}: each registered probe that supports "
                    "--allow-production must receive guarded production override args"
                )
            else:
                self.pass_check()
        else:
            self.error(
                f"{context}: ALLOW_PRODUCTION_INPUT must be bound only from "
                "workflow_dispatch inputs.allow_production with fallback false"
            )

        if _workflow_production_override_flags_are_guarded(workflow_text):
            self.pass_check()
        else:
            self.error(
                f"{context}: --allow-production must be appended only inside "
                'the ALLOW_PRODUCTION_INPUT == "true" guard'
            )

    def require_workflow_live_job_environment(
        self,
        workflow_text: str,
        *,
        requirement_id: str,
        artifact: str,
        artifact_tokens: list[str],
        probe_path: str,
        live_flags: list[str],
        guard_tokens: list[str],
        gate_tokens: list[str],
        context: str,
    ) -> None:
        for job_name, block in _workflow_job_blocks(workflow_text):
            if not _workflow_secret_job_matches_registered_requirement(
                block,
                requirement_id=requirement_id,
                artifact=artifact,
                artifact_tokens=artifact_tokens,
                probe_path=probe_path,
                live_flags=live_flags,
                guard_tokens=guard_tokens,
                gate_tokens=gate_tokens,
            ):
                continue
            environments = _workflow_job_direct_scalar_values(block, "environment")
            if environments == [EXPECTED_LIVE_EVIDENCE_ENVIRONMENT]:
                self.pass_check()
            else:
                self.error(
                    f"{context}.{job_name}: live evidence job must declare "
                    f"`environment: {EXPECTED_LIVE_EVIDENCE_ENVIRONMENT}`"
                )
            return

    def require_workflow_gate_bindings(
        self,
        workflow_text: str,
        *,
        gate_tokens: list[str],
        context: str,
    ) -> None:
        duplicate_input_names = _workflow_dispatch_duplicate_input_names(workflow_text)
        for token in gate_tokens:
            if token.startswith(("allow_", "run_")):
                if token in duplicate_input_names:
                    self.error(
                        f"{context}.{token}: duplicate workflow_dispatch input "
                        f"name {token!r}"
                    )
                input_block = _workflow_dispatch_input_block(workflow_text, token)
                if not input_block:
                    self.error(f"{context}.{token}: missing workflow_dispatch input")
                else:
                    duplicate_input_fields = _workflow_dispatch_input_duplicate_fields(
                        input_block,
                        ["description", "required", "type", "default"],
                    )
                    if duplicate_input_fields:
                        rendered = ", ".join(duplicate_input_fields)
                        self.error(
                            f"{context}.{token}: duplicate workflow_dispatch "
                            f"input field(s): {rendered}"
                        )
                    if _workflow_dispatch_input_is_boolean_default_false(input_block):
                        self.pass_check()
                    else:
                        self.error(
                            f"{context}.{token}: workflow_dispatch input must be "
                            "boolean with default false"
                        )
                if _workflow_has_job_if_gate(workflow_text, token):
                    self.pass_check()
                else:
                    self.error(
                        f"{context}.{token}: workflow_dispatch runs must be guarded "
                        f"by `inputs.{token} == true`"
                    )
            if token.startswith("WIII_") and token.endswith("_EVIDENCE_ENABLED"):
                if _workflow_has_job_if_gate(workflow_text, token):
                    self.pass_check()
                else:
                    self.error(
                        f"{context}.{token}: scheduled runs must be guarded by "
                        f"`vars.{token} == '1'`"
                    )

    def require_workflow_live_probe_binding(
        self,
        workflow_text: str,
        *,
        probe_path: str,
        artifact: str,
        live_flags: list[str],
        guard_tokens: list[str],
        context: str,
    ) -> None:
        for flag in live_flags:
            if _workflow_block_has_duplicate_env_flag(workflow_text, flag):
                self.error(
                    f"{context}.{flag}: workflow env maps must not duplicate "
                    f"`{flag}`"
                )
            elif _workflow_block_sets_env_flag(workflow_text, flag):
                self.pass_check()
            else:
                self.error(f"{context}.{flag}: workflow must set `{flag}: \"1\"`")

        probe_blocks = _workflow_probe_invocation_blocks(workflow_text, probe_path)
        if not probe_blocks:
            self.error(f"{context}: missing workflow step invoking {probe_path!r}")
            return
        self.pass_check()
        for guard_token in guard_tokens:
            if any(
                _workflow_probe_block_has_guard(block, probe_path, guard_token)
                for block in probe_blocks
            ):
                self.pass_check()
            else:
                self.error(
                    f"{context}.{guard_token}: guard token must appear in the "
                    "workflow command line that invokes the registered probe"
                )
        guarded_probe_blocks = [
            block
            for block in probe_blocks
            if any(
                _workflow_probe_block_has_guard(block, probe_path, guard_token)
                for guard_token in guard_tokens
            )
        ]
        strict_shell_missing = [
            block
            for block in guarded_probe_blocks
            if not _workflow_run_block_starts_with_strict_shell(block)
        ]
        if strict_shell_missing:
            self.error(
                f"{context}: registered live probe multiline run steps must "
                "start with `set -euo pipefail`"
            )
        elif guarded_probe_blocks:
            self.pass_check()
        probe_suffix = PurePosixPath(probe_path.replace("\\", "/")).suffix
        if probe_suffix in {".py", ".mjs"}:
            if any(
                _workflow_probe_block_writes_artifact(
                    block,
                    probe_path=probe_path,
                    artifact=artifact,
                )
                for block in probe_blocks
            ):
                self.pass_check()
            else:
                self.error(
                    f"{context}.--out: registered probe invocation must "
                    f"write `--out {artifact}`"
                )

    def require_workflow_requirement_job_binding(
        self,
        workflow_text: str,
        *,
        artifact: str,
        artifact_tokens: list[str],
        requirement_id: str,
        probe_path: str,
        live_flags: list[str],
        guard_tokens: list[str],
        context: str,
    ) -> None:
        job_blocks = _workflow_job_blocks(workflow_text)
        if not job_blocks:
            self.error(f"{context}: missing workflow jobs")
            return
        candidate_notes: list[str] = []
        for job_name, block in job_blocks:
            missing: list[str] = []
            live_flags_ok = all(
                _workflow_block_sets_unique_env_flag(block, flag)
                for flag in live_flags
            )
            if not live_flags_ok:
                missing.append("live env")

            probe_blocks = _workflow_probe_invocation_blocks(block, probe_path)
            probe_ok = bool(probe_blocks) and _workflow_probe_blocks_have_guards(
                probe_blocks,
                probe_path=probe_path,
                guard_tokens=guard_tokens,
            )
            if not probe_ok:
                missing.append("probe guard")
            if not _workflow_job_checks_out_before_probe(block, probe_path):
                missing.append("checkout before probe")

            expected_upload_paths = _workflow_job_validation_expected_upload_paths(
                block,
                artifact=artifact,
                requirement_id=requirement_id,
            )
            validation_ok = bool(expected_upload_paths)
            if not validation_ok:
                missing.append("artifact validation")

            upload_ok = any(
                _workflow_job_has_expected_uploads(
                    block,
                    artifact=artifact,
                    artifact_tokens=artifact_tokens,
                    expected_path=expected_path,
                )
                for expected_path in expected_upload_paths
            )
            if not upload_ok:
                missing.append("artifact upload")

            if (
                probe_ok
                and validation_ok
                and upload_ok
                and not _workflow_job_has_probe_validation_upload_order(
                    block,
                    probe_path=probe_path,
                    artifact=artifact,
                    artifact_tokens=artifact_tokens,
                    requirement_id=requirement_id,
                    guard_tokens=guard_tokens,
                )
            ):
                missing.append("probe-validation-upload order")

            if not missing:
                self.pass_check()
                return
            if artifact in block or probe_blocks or any(token in block for token in artifact_tokens):
                candidate_notes.append(f"{job_name} missing {', '.join(missing)}")

        details = "; ".join(candidate_notes[:3]) if candidate_notes else "no candidate jobs"
        self.error(
            f"{context}: no single workflow job binds live env, probe guard, "
            "artifact validation, upload, and probe-validation-upload order "
            f"for {artifact!r} ({details})"
        )

    def require_workflow_live_job_contract_dependency(
        self,
        workflow_text: str,
        *,
        artifact: str,
        artifact_tokens: list[str],
        requirement_id: str,
        probe_path: str,
        live_flags: list[str],
        guard_tokens: list[str],
        test_paths: list[str],
        context: str,
    ) -> None:
        for job_name, block in _workflow_job_blocks(workflow_text):
            if not all(_workflow_block_sets_env_flag(block, flag) for flag in live_flags):
                continue
            probe_blocks = _workflow_probe_invocation_blocks(block, probe_path)
            if not probe_blocks:
                continue
            if not _workflow_probe_blocks_have_guards(
                probe_blocks,
                probe_path=probe_path,
                guard_tokens=guard_tokens,
            ):
                continue
            validation_ok = _workflow_job_has_bound_validation_upload(
                block,
                artifact=artifact,
                artifact_tokens=artifact_tokens,
                requirement_id=requirement_id,
            )
            if not validation_ok:
                continue

            if all(_workflow_runs_contract_test(block, test_path) for test_path in test_paths):
                self.pass_check()
                return
            if _workflow_job_needs_contract(block):
                if not _workflow_contract_job_is_unconditional(workflow_text):
                    self.error(
                        f"{context}.{job_name}: `needs: contract` job must not "
                        "have a job-level if condition"
                    )
                    return
                missing_tests = [
                    test_path
                    for test_path in test_paths
                    if not _workflow_contract_job_runs_test(workflow_text, test_path)
                ]
                if missing_tests:
                    self.error(
                        f"{context}.{job_name}: `needs: contract` job must execute "
                        f"registered contract test(s): {', '.join(missing_tests)}"
                    )
                    return
                missing_checkout_tests = [
                    test_path
                    for test_path in test_paths
                    if not _workflow_contract_job_checks_out_before_test(
                        workflow_text,
                        test_path,
                    )
                ]
                if missing_checkout_tests:
                    self.error(
                        f"{context}.{job_name}: `needs: contract` job must checkout "
                        "with persist-credentials false before registered contract "
                        f"test(s): {', '.join(missing_checkout_tests)}"
                    )
                else:
                    self.pass_check()
                return
            self.error(
                f"{context}.{job_name}: live evidence job must either execute all "
                "registered contract tests or declare `needs: contract`"
            )
            return

    def require_workflow_live_job_gate_binding(
        self,
        workflow_text: str,
        *,
        artifact: str,
        artifact_tokens: list[str],
        requirement_id: str,
        probe_path: str,
        live_flags: list[str],
        guard_tokens: list[str],
        gate_tokens: list[str],
        context: str,
    ) -> None:
        for job_name, block in _workflow_job_blocks(workflow_text):
            if not all(_workflow_block_sets_env_flag(block, flag) for flag in live_flags):
                continue
            probe_blocks = _workflow_probe_invocation_blocks(block, probe_path)
            if not probe_blocks:
                continue
            if not _workflow_probe_blocks_have_guards(
                probe_blocks,
                probe_path=probe_path,
                guard_tokens=guard_tokens,
            ):
                continue
            validation_ok = _workflow_job_has_bound_validation_upload(
                block,
                artifact=artifact,
                artifact_tokens=artifact_tokens,
                requirement_id=requirement_id,
            )
            if not validation_ok:
                continue

            if not _workflow_job_if_matches_dispatch_or_schedule_gates(block, gate_tokens):
                self.error(
                    f"{context}.{job_name}: live evidence job-level if must be "
                    "guarded by exactly the registered workflow_dispatch input "
                    "or scheduled vars gate"
                )
            else:
                self.pass_check()
            return

    def require_workflow_action_pinning(self, workflow_text: str, *, context: str) -> None:
        action_refs = _workflow_uses_refs(workflow_text)
        if not action_refs:
            self.error(f"{context}: missing workflow uses steps")
            return
        for action, ref in action_refs:
            if action not in ALLOWED_ACTION_NAMES:
                self.error(f"{context}: unsupported workflow uses action {action!r}")
                continue
            if PINNED_ACTION_REF_RE.match(ref):
                self.pass_check()
            else:
                self.error(
                    f"{context}: {action} must be pinned to a 40-character commit SHA"
                )

    def require_workflow_path_filters(
        self,
        workflow_text: str,
        *,
        workflow_path: str,
        probe_path: str,
        test_paths: list[str],
        context: str,
    ) -> None:
        required_paths = [
            workflow_path.replace("\\", "/"),
            "tools/wiii_self_harness/**",
            probe_path.replace("\\", "/"),
            *[test_path.replace("\\", "/") for test_path in test_paths],
        ]
        for event_name in ("pull_request", "push"):
            duplicate_filter_fields = _workflow_event_duplicate_direct_fields(
                workflow_text,
                event_name,
                ["paths", "paths-ignore", "branches", "branches-ignore"],
            )
            if duplicate_filter_fields:
                rendered = ", ".join(duplicate_filter_fields)
                self.error(
                    f"{context}.{event_name}: duplicate event filter field(s): "
                    f"{rendered}"
                )
            unsupported_filter_fields = [
                field
                for field in ("paths-ignore", "branches-ignore")
                if _workflow_event_has_direct_field(workflow_text, event_name, field)
            ]
            if unsupported_filter_fields:
                rendered = ", ".join(unsupported_filter_fields)
                self.error(
                    f"{context}.{event_name}: unsupported event filter field(s): "
                    f"{rendered}"
                )
            else:
                self.pass_check()
            branches = _workflow_event_filter_values(workflow_text, event_name, "branches")
            if branches and "main" not in branches:
                self.error(
                    f"{context}.{event_name}: branches filter must include 'main'"
                )
            else:
                self.pass_check()
            paths = _workflow_event_paths(workflow_text, event_name)
            if not paths:
                self.error(f"{context}.{event_name}: missing paths filter")
                continue
            for required_path in required_paths:
                if required_path in paths:
                    self.pass_check()
                else:
                    self.error(
                        f"{context}.{event_name}: missing paths filter {required_path!r}"
                    )

    def require_workflow_contract_test_execution(
        self,
        workflow_text: str,
        *,
        test_paths: list[str],
        context: str,
    ) -> None:
        for test_path in test_paths:
            if _workflow_runs_contract_test(workflow_text, test_path):
                self.pass_check()
            else:
                self.error(
                    f"{context}: registered contract test {test_path!r} "
                    "must be executed by pytest or vitest in a run step"
                )

    def require_registered_workflow_upload_steps(self, requirements: list[Any]) -> None:
        specs_by_workflow: dict[str, list[tuple[str, str, list[str]]]] = {}
        diagnostic_specs_by_workflow: dict[str, list[DiagnosticUploadSpec]] = {}
        for item in requirements:
            if not isinstance(item, dict):
                continue
            workflow = item.get("workflow")
            artifact = item.get("artifact")
            requirement_id = item.get("id")
            artifact_tokens = item.get("artifact_tokens")
            if (
                not isinstance(workflow, str)
                or not workflow.strip()
                or not isinstance(requirement_id, str)
                or not requirement_id.strip()
                or not isinstance(artifact, str)
                or not artifact.strip()
                or not isinstance(artifact_tokens, list)
            ):
                continue
            tokens = [
                token.strip()
                for token in artifact_tokens
                if isinstance(token, str) and token.strip()
            ]
            if tokens:
                specs_by_workflow.setdefault(workflow.strip(), []).append(
                    (requirement_id.strip(), artifact.strip(), tokens)
                )
            diagnostic_uploads = item.get("diagnostic_uploads")
            if isinstance(diagnostic_uploads, list):
                for diagnostic_upload in diagnostic_uploads:
                    if not isinstance(diagnostic_upload, dict):
                        continue
                    diagnostic_artifact = diagnostic_upload.get("artifact")
                    diagnostic_path = diagnostic_upload.get("path")
                    diagnostic_tokens = diagnostic_upload.get("artifact_tokens")
                    diagnostic_if_no_files_found = diagnostic_upload.get("if_no_files_found")
                    diagnostic_retention_days = diagnostic_upload.get("retention_days")
                    if (
                        isinstance(diagnostic_artifact, str)
                        and diagnostic_artifact.strip()
                        and isinstance(diagnostic_path, str)
                        and diagnostic_path.strip()
                        and isinstance(diagnostic_tokens, list)
                        and diagnostic_tokens
                        and all(isinstance(token, str) and token.strip() for token in diagnostic_tokens)
                        and isinstance(diagnostic_if_no_files_found, str)
                        and diagnostic_if_no_files_found.strip()
                        and _is_positive_int(diagnostic_retention_days)
                    ):
                        diagnostic_specs_by_workflow.setdefault(workflow.strip(), []).append(
                            DiagnosticUploadSpec(
                                requirement_id=requirement_id.strip(),
                                artifact=diagnostic_artifact.strip(),
                                path=diagnostic_path.replace("\\", "/").strip(),
                                artifact_tokens=tuple(token.strip() for token in diagnostic_tokens),
                                if_no_files_found=diagnostic_if_no_files_found.strip(),
                                retention_days=diagnostic_retention_days,
                            )
                        )

        for workflow in sorted(set(specs_by_workflow) | set(diagnostic_specs_by_workflow)):
            specs = specs_by_workflow.get(workflow, [])
            diagnostic_specs = diagnostic_specs_by_workflow.get(workflow, [])
            _, workflow_text = self.require_file_text(
                workflow,
                context=f"workflow_uploads[{workflow}]",
            )
            if not workflow_text:
                continue
            upload_index = 0
            for _, job_block in _workflow_job_blocks(workflow_text):
                expected_paths_by_artifact: dict[tuple[str, str], list[str]] = {}
                for requirement_id, artifact, _tokens in specs:
                    expected_paths_by_artifact[(requirement_id, artifact)] = (
                        _workflow_job_validation_expected_upload_paths(
                            job_block,
                            artifact=artifact,
                            requirement_id=requirement_id,
                        )
                    )
                for block in _workflow_upload_artifact_blocks(job_block):
                    if any(
                        any(
                            _workflow_upload_block_binds_artifact_path(
                                block,
                                artifact=artifact,
                                artifact_token=token,
                                expected_path=expected_path,
                            )
                            for token in tokens
                            for expected_path in expected_paths_by_artifact[
                                (requirement_id, artifact)
                            ]
                        )
                        for requirement_id, artifact, tokens in specs
                    ):
                        self.pass_check()
                    elif any(
                        any(
                            _workflow_upload_block_binds_artifact_path(
                                block,
                                artifact=diagnostic_spec.artifact,
                                artifact_token=token,
                                expected_path=diagnostic_spec.path,
                            )
                            for token in diagnostic_spec.artifact_tokens
                        )
                        for diagnostic_spec in diagnostic_specs
                    ):
                        self.pass_check()
                    else:
                        self.error(
                            f"workflow_uploads[{workflow}].upload[{upload_index}]: "
                            "unregistered upload-artifact step"
                        )
                    upload_index += 1

    def validate(self, data: dict[str, Any]) -> RegistryResult:
        self.reject_unknown_keys(
            data,
            allowed_keys=ALLOWED_REGISTRY_KEYS,
            context="registry",
        )
        if data.get("registry") != REGISTRY_NAME:
            self.error(f"registry: `registry` must be {REGISTRY_NAME!r}")
        else:
            self.pass_check()

        version = data.get("version")
        if not _is_positive_int(version):
            self.error("registry: `version` must be an integer >= 1")
        else:
            self.pass_check()

        self.require_string(data.get("description"), "description", context="registry")
        requirements = data.get("requirements")
        if not isinstance(requirements, list) or not requirements:
            self.error("registry: `requirements` must be a non-empty list")
            requirements = []
        else:
            self.pass_check()

        seen_ids: set[str] = set()
        seen_artifacts: set[str] = set()
        seen_artifact_tokens: set[str] = set()
        for index, item in enumerate(requirements):
            self.validate_requirement(
                item,
                index=index,
                seen_ids=seen_ids,
                seen_artifacts=seen_artifacts,
                seen_artifact_tokens=seen_artifact_tokens,
            )
        self.require_registered_workflow_upload_steps(requirements)
        self.require_registered_workflow_secret_scope(requirements)
        self.require_registered_workflow_production_override_guard(requirements)

        return RegistryResult(
            validation_schema_version=REGISTRY_VALIDATION_SCHEMA_VERSION,
            registry=REGISTRY_NAME,
            registry_version=version if _is_positive_int(version) else None,
            registry_path=str(self.registry_path),
            registry_fingerprint_sha256=_registry_fingerprint(data),
            requirement_count=len(requirements),
            passed_checks=self.passed_checks,
            errors=self.errors,
        )

    def validate_requirement(
        self,
        item: Any,
        *,
        index: int,
        seen_ids: set[str],
        seen_artifacts: set[str],
        seen_artifact_tokens: set[str],
    ) -> None:
        context = f"requirements[{index}]"
        if not isinstance(item, dict):
            self.error(f"{context}: requirement must be an object")
            return
        self.reject_unknown_keys(
            item,
            allowed_keys=ALLOWED_REQUIREMENT_KEYS,
            context=context,
        )

        requirement_id = self.require_string(item.get("id"), "id", context=context)
        if requirement_id:
            context = f"requirements[{requirement_id}]"
            if not ID_RE.match(requirement_id):
                self.error(f"{context}: `id` must be lowercase kebab-case")
            elif requirement_id in seen_ids:
                self.error(f"{context}: duplicate requirement id")
            else:
                seen_ids.add(requirement_id)
                self.pass_check()

        self.require_string(item.get("title"), "title", context=context)
        layer = self.require_string(item.get("layer"), "layer", context=context)
        if layer and layer not in VALID_LAYERS:
            self.error(f"{context}: unsupported layer {layer!r}")
        elif layer:
            self.pass_check()

        artifact = self.require_string(item.get("artifact"), "artifact", context=context)
        if artifact:
            if "/" in artifact or "\\" in artifact:
                self.error(f"{context}: `artifact` must be a file name, not a path")
            elif not artifact.endswith(".json"):
                self.error(f"{context}: `artifact` must be a JSON file")
            elif not ARTIFACT_NAME_RE.match(artifact):
                self.error(
                    f"{context}: `artifact` must be a safe lowercase kebab-case JSON file name"
                )
            elif artifact in seen_artifacts:
                self.error(f"{context}: duplicate artifact name {artifact!r}")
            else:
                seen_artifacts.add(artifact)
                self.pass_check()
        schema = self.require_string(item.get("schema_version"), "schema_version", context=context)
        if schema and not SCHEMA_RE.match(schema):
            self.error(f"{context}: invalid schema_version {schema!r}")
        elif schema:
            self.pass_check()

        self.validate_freshness(item.get("freshness"), context=context)

        payload_schema_field = self.require_string(
            item.get("payload_schema_field"),
            "payload_schema_field",
            context=context,
        )
        if payload_schema_field and payload_schema_field not in {"schema", "schema_version"}:
            self.error(f"{context}: unsupported payload_schema_field {payload_schema_field!r}")
        elif payload_schema_field:
            self.pass_check()

        forbidden_payload_tokens = self.require_string_list(
            item.get("forbidden_payload_tokens"),
            "forbidden_payload_tokens",
            context=context,
        )
        self.require_baseline_forbidden_payload_tokens(
            forbidden_payload_tokens,
            context=context,
        )
        self.require_casefold_unique_forbidden_payload_tokens(
            forbidden_payload_tokens,
            context=context,
        )
        forbidden_payload_regexes = self.require_string_list_allow_empty(
            item.get("forbidden_payload_regexes"),
            "forbidden_payload_regexes",
            context=context,
        )
        self.validate_forbidden_payload_regexes(
            forbidden_payload_regexes,
            context=context,
        )
        self.validate_payload_checks(item.get("payload_checks"), context=context)
        self.require_privacy_payload_checks(item.get("payload_checks"), context=context)

        live_flags = self.require_string_list(item.get("live_env_flags"), "live_env_flags", context=context)
        self.validate_live_env_flags(live_flags, context=context)
        guard_tokens = self.require_string_list(item.get("live_guard_tokens"), "live_guard_tokens", context=context)
        self.validate_live_guard_tokens(guard_tokens, context=context)
        gate_tokens = self.require_string_list(
            item.get("dispatch_or_schedule_gate_tokens"),
            "dispatch_or_schedule_gate_tokens",
            context=context,
        )
        self.validate_dispatch_or_schedule_gate_tokens(
            gate_tokens,
            context=context,
        )
        artifact_tokens = self.require_string_list(item.get("artifact_tokens"), "artifact_tokens", context=context)
        self.validate_artifact_tokens(
            artifact_tokens,
            context=context,
            seen_artifact_tokens=seen_artifact_tokens,
            requirement_id=requirement_id,
            artifact=artifact,
        )
        diagnostic_uploads = self.validate_diagnostic_uploads(
            item.get("diagnostic_uploads"),
            context=context,
            requirement_id=requirement_id,
            seen_artifacts=seen_artifacts,
            seen_artifact_tokens=seen_artifact_tokens,
        )

        workflow_path, workflow_text = self.require_file_text(item.get("workflow"), context=f"{context}.workflow")
        probe_path, probe_text = self.require_file_text(item.get("probe"), context=f"{context}.probe")
        self.validate_probe_script_path(probe_path, context=f"{context}.probe")
        test_paths = self.require_string_list(item.get("contract_tests"), "contract_tests", context=context)
        self.require_unique_repo_path_values(
            test_paths,
            field="contract_tests",
            context=context,
        )
        for test_index, test_path in enumerate(test_paths):
            contract_test_path, _ = self.require_file_text(
                test_path,
                context=f"{context}.contract_tests[{test_index}]",
            )
            self.validate_contract_test_path(
                contract_test_path,
                context=f"{context}.contract_tests[{test_index}]",
            )

        if workflow_path and workflow_path.suffix not in {".yml", ".yaml"}:
            self.error(f"{context}.workflow: workflow must be a YAML file")
        elif workflow_path:
            self.pass_check()
        self.validate_workflow_path_location(workflow_path, context=f"{context}.workflow")

        if "pull_request_target:" in workflow_text:
            self.error(f"{context}.workflow: pull_request_target is not allowed for evidence workflows")
        elif workflow_text:
            self.pass_check()

        workflow_required = [
            "permissions:",
            "contents: read",
            "pull_request:",
            "workflow_dispatch:",
            "schedule:",
            "actions/upload-artifact@",
            "validate_runtime_evidence_artifact.py",
            str(item.get("id") or ""),
            artifact,
            *live_flags,
            *guard_tokens,
            *gate_tokens,
            *artifact_tokens,
            *[
                token
                for diagnostic_upload in diagnostic_uploads
                for token in diagnostic_upload.artifact_tokens
            ],
            *[diagnostic_upload.path for diagnostic_upload in diagnostic_uploads],
        ]
        self.require_tokens(workflow_text, workflow_required, context=f"{context}.workflow")
        self.require_workflow_top_level_key_uniqueness(
            workflow_text,
            keys=["on", "permissions", "concurrency", "jobs"],
            context=f"{context}.workflow.top_level",
        )
        self.require_workflow_event_name_uniqueness(
            workflow_text,
            context=f"{context}.workflow.events",
        )
        self.require_workflow_job_name_uniqueness(
            workflow_text,
            context=f"{context}.workflow.job_names",
        )
        self.require_tokens(
            workflow_text,
            test_paths,
            context=f"{context}.workflow.contract_tests",
        )
        self.require_workflow_contract_test_execution(
            workflow_text,
            test_paths=test_paths,
            context=f"{context}.workflow.contract_tests",
        )
        self.require_workflow_validation_binding(
            workflow_text,
            artifact=artifact,
            requirement_id=requirement_id,
            context=f"{context}.workflow.validation",
        )
        self.require_workflow_upload_binding(
            workflow_text,
            artifact=artifact,
            artifact_tokens=artifact_tokens,
            context=f"{context}.workflow.upload",
        )
        self.require_workflow_diagnostic_upload_bindings(
            workflow_text,
            specs=diagnostic_uploads,
            context=f"{context}.workflow.diagnostic_uploads",
        )
        self.require_workflow_checkout_hardening(
            workflow_text,
            context=f"{context}.workflow.checkout",
        )
        self.require_workflow_job_timeouts(
            workflow_text,
            context=f"{context}.workflow.jobs",
        )
        self.require_workflow_job_control_key_uniqueness(
            workflow_text,
            context=f"{context}.workflow.job_controls",
        )
        self.require_workflow_fail_closed_execution(
            workflow_text,
            context=f"{context}.workflow.fail_closed",
        )
        self.require_workflow_no_shell_xtrace(
            workflow_text,
            context=f"{context}.workflow.shell",
        )
        self.require_workflow_permissions_hardening(
            workflow_text,
            context=f"{context}.workflow.permissions",
        )
        self.require_workflow_concurrency_guard(
            workflow_text,
            context=f"{context}.workflow.concurrency",
        )
        self.require_workflow_gate_bindings(
            workflow_text,
            gate_tokens=gate_tokens,
            context=f"{context}.workflow.gates",
        )
        self.require_workflow_live_probe_binding(
            workflow_text,
            probe_path=str(item.get("probe") or ""),
            artifact=artifact,
            live_flags=live_flags,
            guard_tokens=guard_tokens,
            context=f"{context}.workflow.live_probe",
        )
        self.require_workflow_requirement_job_binding(
            workflow_text,
            artifact=artifact,
            artifact_tokens=artifact_tokens,
            requirement_id=requirement_id,
            probe_path=str(item.get("probe") or ""),
            live_flags=live_flags,
            guard_tokens=guard_tokens,
            context=f"{context}.workflow.requirement_job",
        )
        self.require_workflow_live_job_contract_dependency(
            workflow_text,
            artifact=artifact,
            artifact_tokens=artifact_tokens,
            requirement_id=requirement_id,
            probe_path=str(item.get("probe") or ""),
            live_flags=live_flags,
            guard_tokens=guard_tokens,
            test_paths=test_paths,
            context=f"{context}.workflow.live_contract",
        )
        self.require_workflow_live_job_gate_binding(
            workflow_text,
            artifact=artifact,
            artifact_tokens=artifact_tokens,
            requirement_id=requirement_id,
            probe_path=str(item.get("probe") or ""),
            live_flags=live_flags,
            guard_tokens=guard_tokens,
            gate_tokens=gate_tokens,
            context=f"{context}.workflow.live_gates",
        )
        self.require_workflow_live_job_environment(
            workflow_text,
            artifact=artifact,
            artifact_tokens=artifact_tokens,
            requirement_id=requirement_id,
            probe_path=str(item.get("probe") or ""),
            live_flags=live_flags,
            guard_tokens=guard_tokens,
            gate_tokens=gate_tokens,
            context=f"{context}.workflow.environment",
        )
        self.require_workflow_action_pinning(
            workflow_text,
            context=f"{context}.workflow.actions",
        )
        self.require_workflow_path_filters(
            workflow_text,
            workflow_path=str(item.get("workflow") or ""),
            probe_path=str(item.get("probe") or ""),
            test_paths=test_paths,
            context=f"{context}.workflow.paths",
        )
        self.require_workflow_runtime_evidence_output_helper_contract(
            workflow_text,
            probe_path=probe_path,
            context=f"{context}.workflow.output_helper_contract",
        )

        probe_required = [schema, *live_flags, *guard_tokens]
        self.require_tokens(probe_text, probe_required, context=f"{context}.probe")
        if probe_path and probe_path.suffix == ".py":
            self.require_python_probe_cli_guard_tokens(
                probe_text,
                guard_tokens=guard_tokens,
                context=f"{context}.probe",
            )
            self.require_python_probe_output_argument(
                probe_text,
                context=f"{context}.probe",
            )
            self.require_python_probe_output_helper_import(
                probe_text,
                context=f"{context}.probe",
            )
            self.require_python_probe_output_helper_call(
                probe_text,
                context=f"{context}.probe",
            )
            self.require_python_probe_no_raw_file_writes(
                probe_text,
                context=f"{context}.probe",
            )
            self.require_python_runtime_evidence_output_helper(
                probe_path,
                context=f"{context}.probe.output_helper",
            )
            self.require_tokens(
                workflow_text,
                ["--out"],
                context=f"{context}.workflow",
            )
        if probe_path and probe_path.suffix == ".mjs":
            self.require_mjs_probe_cli_guard_tokens(
                probe_text,
                guard_tokens=guard_tokens,
                context=f"{context}.probe",
            )
            self.require_mjs_probe_output_argument(
                probe_text,
                context=f"{context}.probe",
            )
            self.require_mjs_probe_no_raw_file_writes(
                probe_text,
                context=f"{context}.probe",
            )
            self.require_mjs_runtime_evidence_output_helper(
                probe_path,
                context=f"{context}.probe.output_helper",
            )

    def validate_diagnostic_uploads(
        self,
        value: Any,
        *,
        context: str,
        requirement_id: str,
        seen_artifacts: set[str],
        seen_artifact_tokens: set[str],
    ) -> list[DiagnosticUploadSpec]:
        if value is None:
            return []
        if not isinstance(value, list) or not value:
            self.error(f"{context}: `diagnostic_uploads` must be a non-empty list")
            return []
        self.pass_check()

        specs: list[DiagnosticUploadSpec] = []
        for index, item in enumerate(value):
            upload_context = f"{context}.diagnostic_uploads[{index}]"
            if not isinstance(item, dict):
                self.error(f"{upload_context}: diagnostic upload must be an object")
                continue
            self.reject_unknown_keys(
                item,
                allowed_keys=ALLOWED_DIAGNOSTIC_UPLOAD_KEYS,
                context=upload_context,
            )

            artifact = self.require_string(item.get("artifact"), "artifact", context=upload_context)
            artifact_valid = False
            if artifact:
                if "/" in artifact or "\\" in artifact:
                    self.error(f"{upload_context}: `artifact` must be a file name, not a path")
                elif not artifact.endswith(".json"):
                    self.error(f"{upload_context}: `artifact` must be a JSON file")
                elif not ARTIFACT_NAME_RE.match(artifact):
                    self.error(
                        f"{upload_context}: `artifact` must be a safe lowercase kebab-case JSON file name"
                    )
                elif artifact in seen_artifacts:
                    self.error(f"{upload_context}: duplicate artifact name {artifact!r}")
                else:
                    seen_artifacts.add(artifact)
                    self.pass_check()
                    artifact_valid = True

            upload_path = self.require_string(item.get("path"), "path", context=upload_context)
            normalized_path = upload_path.replace("\\", "/").strip() if upload_path else ""
            path_valid = False
            if normalized_path:
                posix_path = PurePosixPath(normalized_path)
                parts = posix_path.parts
                if (
                    Path(normalized_path).is_absolute()
                    or posix_path.is_absolute()
                    or ".." in parts
                    or not parts
                    or (parts and ":" in parts[0])
                    or any(token in normalized_path for token in ("*", "?", "[", "]", "{", "}", "$", "%"))
                ):
                    self.error(f"{upload_context}: `path` must be an explicit repo-relative JSON path")
                elif posix_path.name != artifact:
                    self.error(
                        f"{upload_context}: `path` file name must match artifact {artifact!r}"
                    )
                elif posix_path.suffix != ".json":
                    self.error(f"{upload_context}: `path` must point to a JSON file")
                else:
                    self.pass_check()
                    path_valid = True

            artifact_tokens = self.require_string_list(
                item.get("artifact_tokens"),
                "artifact_tokens",
                context=upload_context,
            )
            self.validate_artifact_tokens(
                artifact_tokens,
                context=upload_context,
                seen_artifact_tokens=seen_artifact_tokens,
                requirement_id=requirement_id,
                artifact=artifact,
            )

            if_no_files_found = self.require_string(
                item.get("if_no_files_found"),
                "if_no_files_found",
                context=upload_context,
            )
            if if_no_files_found and if_no_files_found != "warn":
                self.error(
                    f"{upload_context}: `if_no_files_found` must be 'warn' for diagnostic uploads"
                )
            elif if_no_files_found:
                self.pass_check()

            retention_days = item.get("retention_days")
            if not _is_positive_int(retention_days):
                self.error(f"{upload_context}: `retention_days` must be an integer >= 1")
            elif retention_days > 30:
                self.error(f"{upload_context}: `retention_days` must be <= 30")
            else:
                self.pass_check()

            if (
                artifact_valid
                and path_valid
                and artifact_tokens
                and if_no_files_found == "warn"
                and _is_positive_int(retention_days)
                and retention_days <= 30
            ):
                specs.append(
                    DiagnosticUploadSpec(
                        requirement_id=requirement_id,
                        artifact=artifact,
                        path=normalized_path,
                        artifact_tokens=tuple(artifact_tokens),
                        if_no_files_found=if_no_files_found,
                        retention_days=retention_days,
                    )
                )
        return specs

    def validate_artifact_tokens(
        self,
        artifact_tokens: list[str],
        *,
        context: str,
        seen_artifact_tokens: set[str],
        requirement_id: str,
        artifact: str,
    ) -> None:
        artifact_stem = artifact.removesuffix(".json")
        for token in artifact_tokens:
            if not ARTIFACT_TOKEN_RE.match(token):
                self.error(
                    f"{context}: artifact token must be lowercase kebab-case "
                    "ending with `${{ github.run_id }}`: "
                    f"{token!r}"
                )
                continue
            if token in seen_artifact_tokens:
                self.error(f"{context}: duplicate artifact token {token!r}")
                continue
            token_stem = token.removesuffix("-${{ github.run_id }}")
            if requirement_id not in token_stem and artifact_stem not in token_stem:
                self.error(
                    f"{context}: artifact token must include requirement id "
                    f"{requirement_id!r} or artifact stem {artifact_stem!r}: {token!r}"
                )
                continue
            seen_artifact_tokens.add(token)
            self.pass_check()

    def validate_workflow_path_location(self, workflow_path: Path | None, *, context: str) -> None:
        if workflow_path is None:
            return
        expected_parent = (self.repo_root / ".github" / "workflows").resolve()
        if workflow_path.parent != expected_parent:
            self.error(f"{context}: workflow must live directly under .github/workflows/")
            return
        self.pass_check()

    def validate_probe_script_path(self, probe_path: Path | None, *, context: str) -> None:
        if probe_path is None:
            return
        if probe_path.suffix not in ALLOWED_PROBE_SUFFIXES:
            suffixes = ", ".join(sorted(ALLOWED_PROBE_SUFFIXES))
            self.error(f"{context}: probe must be a script file ending in {suffixes}")
            return
        self.pass_check()

    def validate_contract_test_path(
        self,
        contract_test_path: Path | None,
        *,
        context: str,
    ) -> None:
        if contract_test_path is None:
            return
        name = contract_test_path.name
        if contract_test_path.suffix == ".py" and name.startswith("test_"):
            self.pass_check()
            return
        if name.endswith(ALLOWED_TYPESCRIPT_TEST_SUFFIXES):
            self.pass_check()
            return
        self.error(
            f"{context}: contract_tests entries must be Python `test_*.py` "
            "or TypeScript `*.test.ts`/`*.spec.ts` files"
        )

    def validate_live_env_flags(self, live_flags: list[str], *, context: str) -> None:
        for flag in live_flags:
            if not LIVE_ENV_FLAG_RE.match(flag):
                self.error(
                    f"{context}: live_env_flags entries must be uppercase "
                    f"`WIII_*` environment variables: {flag!r}"
                )
                continue
            if flag.endswith("_EVIDENCE_ENABLED"):
                self.error(
                    f"{context}: live_env_flags entries must not reuse scheduled "
                    f"evidence gate tokens: {flag!r}"
                )
                continue
            self.pass_check()

    def validate_live_guard_tokens(self, guard_tokens: list[str], *, context: str) -> None:
        for token in guard_tokens:
            if not LIVE_GUARD_TOKEN_RE.match(token):
                self.error(
                    f"{context}: live_guard_tokens entries must be explicit "
                    f"`--allow-*` lowercase kebab-case CLI flags: {token!r}"
                )
                continue
            self.pass_check()

    def require_python_probe_cli_guard_tokens(
        self,
        probe_text: str,
        *,
        guard_tokens: list[str],
        context: str,
    ) -> None:
        parser_flags = _python_probe_argparse_store_true_flags(probe_text)
        for token in guard_tokens:
            if token in parser_flags:
                self.pass_check()
            else:
                self.error(
                    f"{context}: live guard token {token!r} must be an argparse "
                    "store_true CLI flag in the registered Python probe"
                )

    def require_python_probe_output_argument(
        self,
        probe_text: str,
        *,
        context: str,
    ) -> None:
        parser_flags = _python_probe_argparse_flags(probe_text)
        if "--out" in parser_flags:
            self.pass_check()
            return
        self.error(
            f"{context}: registered Python probe must define `--out` as an "
            "argparse CLI flag"
        )

    def require_python_probe_output_helper_import(
        self,
        probe_text: str,
        *,
        context: str,
    ) -> None:
        if _python_probe_imports_runtime_evidence_output_helper(probe_text):
            self.pass_check()
            return
        self.error(
            f"{context}: registered Python probe must import emit_json_payload "
            "from runtime_evidence_output"
        )

    def require_python_probe_output_helper_call(
        self,
        probe_text: str,
        *,
        context: str,
    ) -> None:
        if _python_probe_calls_output_helper_with_output_path(probe_text):
            self.pass_check()
            return
        self.error(
            f"{context}: registered Python probe must call emit_json_payload "
            "with an output path argument"
        )

    def require_python_probe_no_raw_file_writes(
        self,
        probe_text: str,
        *,
        context: str,
    ) -> None:
        raw_write_calls = _python_probe_raw_file_write_calls(probe_text)
        if not raw_write_calls:
            self.pass_check()
            return
        rendered = ", ".join(raw_write_calls)
        self.error(
            f"{context}: registered Python probe must not write evidence files "
            f"outside runtime_evidence_output: {rendered}"
        )

    def require_python_runtime_evidence_output_helper(
        self,
        probe_path: Path,
        *,
        context: str,
    ) -> None:
        helper_path = probe_path.with_name("runtime_evidence_output.py")
        self.require_runtime_evidence_output_helper_atomic_tokens(
            helper_path,
            tokens=PYTHON_RUNTIME_EVIDENCE_HELPER_ATOMIC_TOKENS,
            context=context,
        )

    def require_mjs_probe_cli_guard_tokens(
        self,
        probe_text: str,
        *,
        guard_tokens: list[str],
        context: str,
    ) -> None:
        if _mjs_probe_fail_function_exits_nonzero(probe_text):
            self.pass_check()
        else:
            self.error(
                f"{context}: registered MJS probe fail() must call "
                "process.exit with a non-zero literal status"
            )
        guarded_flags = _mjs_probe_fail_closed_guard_tokens(probe_text)
        for token in guard_tokens:
            if token in guarded_flags:
                self.pass_check()
            else:
                self.error(
                    f"{context}: live guard token {token!r} must be checked by "
                    "a fail-closed process.argv.includes(...) guard in the "
                    "registered MJS probe"
                )

    def require_mjs_probe_output_argument(
        self,
        probe_text: str,
        *,
        context: str,
    ) -> None:
        if _mjs_probe_handles_output_argument(probe_text):
            self.pass_check()
        else:
            self.error(
                f"{context}: registered MJS probe must parse `--out` from "
                "process.argv"
            )
        if _mjs_probe_forwards_output_to_summary_env(probe_text):
            self.pass_check()
        else:
            self.error(
                f"{context}: registered MJS probe must forward parsed `--out` "
                "path to WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON"
            )

    def require_mjs_probe_no_raw_file_writes(
        self,
        probe_text: str,
        *,
        context: str,
    ) -> None:
        raw_write_calls = _mjs_probe_raw_file_write_calls(probe_text)
        if not raw_write_calls:
            self.pass_check()
            return
        rendered = ", ".join(raw_write_calls)
        self.error(
            f"{context}: registered MJS probe must not write evidence files "
            f"outside runtime-evidence-output.mjs: {rendered}"
        )

    def require_mjs_runtime_evidence_output_helper(
        self,
        probe_path: Path,
        *,
        context: str,
    ) -> None:
        helper_path = probe_path.with_name("runtime-evidence-output.mjs")
        self.require_runtime_evidence_output_helper_atomic_tokens(
            helper_path,
            tokens=MJS_RUNTIME_EVIDENCE_HELPER_ATOMIC_TOKENS,
            context=context,
        )

    def require_runtime_evidence_output_helper_atomic_tokens(
        self,
        helper_path: Path,
        *,
        tokens: list[str],
        context: str,
    ) -> None:
        relative_path = helper_path.relative_to(self.repo_root).as_posix()
        _, helper_text = self.require_file_text(relative_path, context=context)
        if not helper_text:
            return
        missing = [token for token in tokens if token not in helper_text]
        if not missing:
            self.passed_checks += len(tokens)
            return
        rendered = ", ".join(repr(token) for token in missing)
        self.error(
            f"{context}: runtime evidence output helper {relative_path!r} must "
            f"use atomic temp-file writes; missing token(s): {rendered}"
        )

    def require_workflow_runtime_evidence_output_helper_contract(
        self,
        workflow_text: str,
        *,
        probe_path: Path | None,
        context: str,
    ) -> None:
        helper_paths = _runtime_evidence_output_helper_paths_for_probe(
            probe_path,
            repo_root=self.repo_root,
        )
        if helper_paths is None:
            return
        helper_path, helper_test_path = helper_paths
        for event_name in ("pull_request", "push"):
            paths = _workflow_event_paths(workflow_text, event_name)
            for required_path in (helper_path, helper_test_path):
                if required_path in paths:
                    self.pass_check()
                else:
                    self.error(
                        f"{context}.{event_name}: missing paths filter "
                        f"{required_path!r}"
                    )
        if helper_test_path.endswith(".py"):
            helper_test_runs = _workflow_contract_job_runs_test(
                workflow_text,
                helper_test_path,
            )
        else:
            helper_test_runs = _workflow_contract_job_runs_node_script(
                workflow_text,
                helper_test_path,
            )
        if helper_test_runs:
            self.pass_check()
            return
        self.error(
            f"{context}: contract job must execute runtime evidence output "
            f"helper test {helper_test_path!r}"
        )

    def validate_dispatch_or_schedule_gate_tokens(
        self,
        gate_tokens: list[str],
        *,
        context: str,
    ) -> None:
        dispatch_tokens = [
            token for token in gate_tokens if DISPATCH_GATE_TOKEN_RE.match(token)
        ]
        schedule_tokens = [
            token for token in gate_tokens if SCHEDULE_GATE_TOKEN_RE.match(token)
        ]
        recognized_tokens = set(dispatch_tokens) | set(schedule_tokens)
        unsupported_tokens = [
            token for token in gate_tokens if token not in recognized_tokens
        ]
        if unsupported_tokens:
            self.error(
                f"{context}: dispatch_or_schedule_gate_tokens contains "
                f"{UNSUPPORTED_GATE_TOKEN_SUMMARY}: {', '.join(unsupported_tokens)}"
            )
        else:
            self.pass_check()

        if len(dispatch_tokens) != 1:
            self.error(
                f"{context}: dispatch_or_schedule_gate_tokens must include exactly "
                "one workflow_dispatch input gate token starting with `allow_` or `run_`"
            )
        else:
            self.pass_check()

        if len(schedule_tokens) != 1:
            self.error(
                f"{context}: dispatch_or_schedule_gate_tokens must include exactly "
                "one scheduled vars gate token matching `WIII_*_EVIDENCE_ENABLED`"
            )
        else:
            self.pass_check()

    def require_baseline_forbidden_payload_tokens(
        self,
        forbidden_payload_tokens: list[str],
        *,
        context: str,
    ) -> None:
        missing = sorted(BASELINE_FORBIDDEN_PAYLOAD_TOKENS - set(forbidden_payload_tokens))
        if missing:
            self.error(
                f"{context}: forbidden_payload_tokens must include baseline "
                f"secret token(s): {', '.join(missing)}"
            )
        else:
            self.pass_check()

    def require_casefold_unique_forbidden_payload_tokens(
        self,
        forbidden_payload_tokens: list[str],
        *,
        context: str,
    ) -> None:
        first_seen_by_casefold: dict[str, str] = {}
        for token in forbidden_payload_tokens:
            normalized = token.casefold()
            previous = first_seen_by_casefold.get(normalized)
            if previous is not None and previous != token:
                self.error(
                    f"{context}: forbidden_payload_tokens must not contain "
                    f"case-insensitive duplicate values: {previous!r}, {token!r}"
                )
                return
            first_seen_by_casefold[normalized] = token
        self.pass_check()

    def validate_forbidden_payload_regexes(
        self,
        forbidden_payload_regexes: list[str],
        *,
        context: str,
    ) -> None:
        seen_patterns: set[str] = set()
        for pattern in forbidden_payload_regexes:
            if pattern in seen_patterns:
                self.error(f"{context}: duplicate forbidden_payload_regexes pattern {pattern!r}")
                continue
            seen_patterns.add(pattern)
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                self.error(
                    f"{context}: forbidden_payload_regexes pattern must compile: "
                    f"{pattern!r} ({exc})"
                )
                continue
            self.pass_check()

    def validate_payload_checks(self, checks: Any, *, context: str) -> None:
        if not isinstance(checks, list) or not checks:
            self.error(f"{context}: `payload_checks` must be a non-empty list")
            return
        self.pass_check()
        seen_check_keys: set[tuple[str, str, str]] = set()
        for index, check in enumerate(checks):
            check_context = f"{context}.payload_checks[{index}]"
            if not isinstance(check, dict):
                self.error(f"{check_context}: check must be an object")
                continue
            self.reject_unknown_keys(
                check,
                allowed_keys=ALLOWED_PAYLOAD_CHECK_KEYS,
                context=check_context,
            )
            path = self.require_string(check.get("path"), "path", context=check_context)
            if path:
                self.require_dot_path(
                    path,
                    "path",
                    context=check_context,
                    allow_wildcard="length_equals_path" not in check,
                )
            operation_count = sum(
                key in check for key in ("equals", "min", "sorted_equals", "length_equals_path")
            )
            if operation_count != 1:
                self.error(
                    f"{check_context}: exactly one of equals, min, sorted_equals, "
                    "or length_equals_path is required"
                )
            else:
                self.pass_check()
            if "equals" in check:
                self.require_json_scalar(
                    check.get("equals"),
                    "equals",
                    context=check_context,
                )
            if "min" in check:
                min_value = check.get("min")
                if isinstance(min_value, bool) or not isinstance(min_value, (int, float)):
                    self.error(f"{check_context}: min must be a JSON number")
                else:
                    self.pass_check()
            if "sorted_equals" in check:
                sorted_equals = check.get("sorted_equals")
                if not isinstance(sorted_equals, list):
                    self.error(f"{check_context}: sorted_equals must be a list")
                else:
                    self.pass_check()
                    for item_index, item in enumerate(sorted_equals):
                        self.require_json_scalar(
                            item,
                            f"sorted_equals[{item_index}]",
                            context=check_context,
                        )
            if "length_equals_path" in check:
                length_equals_path = self.require_string(
                    check.get("length_equals_path"),
                    "length_equals_path",
                    context=check_context,
                )
                if length_equals_path:
                    self.require_dot_path(
                        length_equals_path,
                        "length_equals_path",
                        context=check_context,
                    )
            when = check.get("when")
            operation = next(
                (
                    key
                    for key in ("equals", "min", "sorted_equals", "length_equals_path")
                    if key in check
                ),
                "",
            )
            if path and operation:
                when_key = _payload_check_when_key(when)
                check_key = (path, operation, when_key)
                if check_key in seen_check_keys:
                    self.error(
                        f"{check_context}: duplicate payload check for "
                        f"{path!r} with operation {operation!r}"
                    )
                else:
                    seen_check_keys.add(check_key)
                    self.pass_check()
            if when is None:
                continue
            if not isinstance(when, dict):
                self.error(f"{check_context}: `when` must be an object when present")
                continue
            self.reject_unknown_keys(
                when,
                allowed_keys=ALLOWED_PAYLOAD_CHECK_WHEN_KEYS,
                context=f"{check_context}.when",
            )
            when_path = self.require_string(
                when.get("path"),
                "path",
                context=f"{check_context}.when",
            )
            if when_path:
                self.require_dot_path(
                    when_path,
                    "path",
                    context=f"{check_context}.when",
                )
            when_operation_count = sum(key in when for key in ("equals", "not_equals"))
            if when_operation_count != 1:
                self.error(
                    f"{check_context}.when: exactly one of equals or not_equals is required"
                )
            else:
                self.pass_check()
                when_operation = "equals" if "equals" in when else "not_equals"
                self.require_json_scalar(
                    when.get(when_operation),
                    when_operation,
                    context=f"{check_context}.when",
                )

    def require_privacy_payload_checks(self, checks: Any, *, context: str) -> None:
        if not isinstance(checks, list):
            return
        raw_content_check_present = False
        identifier_strategy_check_present = False
        for check in checks:
            if not isinstance(check, dict):
                continue
            path = check.get("path")
            if not isinstance(path, str):
                continue
            if "raw_content_included" in path and check.get("equals") is False:
                raw_content_check_present = True
            if (
                "identifier_strategy" in path
                and check.get("equals") in ALLOWED_IDENTIFIER_STRATEGIES
            ):
                identifier_strategy_check_present = True

        if raw_content_check_present:
            self.pass_check()
        else:
            self.error(
                f"{context}: payload_checks must prove raw content absence with "
                "`raw_content_included == false`"
            )
        if identifier_strategy_check_present:
            self.pass_check()
        else:
            self.error(
                f"{context}: payload_checks must prove an allowed "
                "identifier_strategy"
            )

    def validate_freshness(self, value: Any, *, context: str) -> None:
        if not isinstance(value, dict):
            self.error(f"{context}: `freshness` must be an object")
            return
        self.pass_check()
        self.reject_unknown_keys(
            value,
            allowed_keys=ALLOWED_FRESHNESS_KEYS,
            context=f"{context}.freshness",
        )
        timestamp_path = self.require_string(
            value.get("timestamp_path"),
            "timestamp_path",
            context=f"{context}.freshness",
        )
        if timestamp_path:
            self.require_dot_path(
                timestamp_path,
                "timestamp_path",
                context=f"{context}.freshness",
            )
        max_age_hours = value.get("max_age_hours")
        if not _is_positive_int(max_age_hours):
            self.error(f"{context}.freshness: max_age_hours must be a positive integer")
        else:
            self.pass_check()


def _normalize_shell_continuations(text: str) -> str:
    return re.sub(r"\\\r?\n\s*", " ", text)


def _strip_unquoted_shell_comments(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        in_single_quote = False
        in_double_quote = False
        escaped = False
        comment_index: int | None = None
        for index, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\" and not in_single_quote:
                escaped = True
                continue
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                continue
            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                continue
            if (
                char == "#"
                and not in_single_quote
                and not in_double_quote
                and (index == 0 or line[index - 1].isspace())
            ):
                comment_index = index
                break
        cleaned_lines.append(line if comment_index is None else line[:comment_index].rstrip())
    return "\n".join(cleaned_lines)


def _workflow_run_command_text(block: str) -> str:
    normalized_block = _normalize_shell_continuations(block).replace("\\", "/")
    return _strip_unquoted_shell_comments(normalized_block)


def _text_mentions_bounded_token(text: str, token: str) -> bool:
    normalized_text = text.replace("\\", "/")
    normalized_token = token.replace("\\", "/")
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_./-]){re.escape(normalized_token)}(?![A-Za-z0-9_./-])",
            normalized_text,
        )
    )


def _normalized_registry_path_key(raw_path: str) -> str:
    return str(PurePosixPath(raw_path.replace("\\", "/").strip()))


def _repo_relative_path_contains_symlink(repo_root: Path, relative_path: Path) -> bool:
    current = repo_root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _payload_check_when_key(when: Any) -> str:
    if not isinstance(when, dict):
        return ""
    operation = next((key for key in ("equals", "not_equals") if key in when), "")
    value = when.get(operation) if operation else None
    return json.dumps(
        {
            "path": when.get("path"),
            "operation": operation,
            "value": value,
        },
        sort_keys=True,
        ensure_ascii=True,
    )


def _workflow_validator_commands(workflow_text: str) -> list[str]:
    commands: list[str] = []
    for block in _workflow_step_blocks(workflow_text):
        if "run:" not in block:
            continue
        command_text = _workflow_run_command_text(block)
        commands.extend(
            line.strip()
            for line in command_text.splitlines()
            if "validate_runtime_evidence_artifact.py" in line
        )
    return commands


def _workflow_step_blocks(workflow_text: str) -> list[str]:
    lines = workflow_text.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    if re.match(r"^\s{6}-\s+(?:name:|uses:|run:|id:)", first_line):
        return [workflow_text]

    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if not re.match(r"^\s{4}steps:\s*(?:#.*)?$", lines[index]):
            index += 1
            continue

        steps_indent = 4
        step_indent = steps_indent + 2
        steps_end = len(lines)
        for end_index in range(index + 1, len(lines)):
            line = lines[end_index]
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= steps_indent:
                steps_end = end_index
                break

        step_starts = [
            step_index
            for step_index in range(index + 1, steps_end)
            if re.match(rf"^\s{{{step_indent}}}-\s+(?:name:|uses:|run:|id:)", lines[step_index])
        ]
        for position, start in enumerate(step_starts):
            end = step_starts[position + 1] if position + 1 < len(step_starts) else steps_end
            blocks.append("\n".join(lines[start:end]))
        index = steps_end
    return blocks


def _workflow_text_before_jobs(workflow_text: str) -> str:
    lines = workflow_text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^jobs:\s*(?:#.*)?$", line):
            return "\n".join(lines[:index])
    return workflow_text


def _workflow_text_references_secrets(text: str) -> bool:
    return bool(SECRET_REFERENCE_RE.search(text))


def _workflow_upload_artifact_blocks(workflow_text: str) -> list[str]:
    return [
        block
        for block in _workflow_step_blocks(workflow_text)
        if _workflow_step_uses_action(block, "actions/upload-artifact")
    ]


def _workflow_upload_artifact_names(upload_block: str) -> list[str]:
    return _workflow_mapping_direct_scalar_values(
        _workflow_upload_with_block(upload_block),
        "name",
    )


def _workflow_block_scalar_field_equals(block: str, field: str, expected: str) -> bool:
    values = [
        match.group(1).strip().strip("\"'")
        for match in re.finditer(
            rf"(?m)^\s+{re.escape(field)}:\s*([^#\r\n]+?)\s*(?:#.*)?$",
            block,
        )
    ]
    return expected in values


def _workflow_step_scalar_field_equals(block: str, field: str, expected: str) -> bool:
    return expected in _workflow_block_direct_scalar_values(block, field)


def _workflow_block_direct_scalar_values(block: str, field: str) -> list[str]:
    lines = block.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    if not first_line:
        return []

    first_indent = len(first_line) - len(first_line.lstrip(" "))
    direct_indent = first_indent + 2 if first_line.lstrip().startswith("- ") else first_indent
    values: list[str] = []
    first_match = re.match(
        rf"^\s*-\s+{re.escape(field)}:\s*([^#\r\n]+?)\s*(?:#.*)?$",
        first_line,
    )
    if first_match:
        values.append(first_match.group(1).strip().strip("\"'"))
    values.extend(
        match.group(1).strip().strip("\"'")
        for line in lines[1:]
        if (
            match := re.match(
                rf"^\s{{{direct_indent}}}{re.escape(field)}:"
                r"\s*([^#\r\n]+?)\s*(?:#.*)?$",
                line,
            )
        )
    )
    return values


def _workflow_block_duplicate_direct_fields(block: str, fields: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    allowed = set(fields)
    for field in _workflow_block_direct_field_names(block):
        if field in allowed:
            counts[field] = counts.get(field, 0) + 1
    return [field for field in fields if counts.get(field, 0) > 1]


def _workflow_block_direct_field_names(block: str) -> list[str]:
    lines = block.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    if not first_line:
        return []

    first_indent = len(first_line) - len(first_line.lstrip(" "))
    direct_indent = first_indent + 2 if first_line.lstrip().startswith("- ") else first_indent
    fields: list[str] = []
    if first_match := re.match(r"^\s*-\s+([A-Za-z0-9_-]+):(?:\s|$)", first_line):
        fields.append(first_match.group(1))
    for line in lines[1:]:
        if match := re.match(rf"^\s{{{direct_indent}}}([A-Za-z0-9_-]+):(?:\s|$)", line):
            fields.append(match.group(1))
    return fields


def _workflow_job_duplicate_direct_fields(job_block: str, fields: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    allowed = set(fields)
    for field in _workflow_job_direct_field_names(job_block):
        if field in allowed:
            counts[field] = counts.get(field, 0) + 1
    return [field for field in fields if counts.get(field, 0) > 1]


def _workflow_job_direct_field_names(job_block: str) -> list[str]:
    lines = job_block.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    if not first_line:
        return []

    job_indent = len(first_line) - len(first_line.lstrip(" "))
    field_indent = job_indent + 2
    fields: list[str] = []
    for line in lines[1:]:
        if match := re.match(rf"^\s{{{field_indent}}}([A-Za-z-]+):(?:\s|$)", line):
            fields.append(match.group(1))
    return fields


def _workflow_job_direct_scalar_values(job_block: str, field: str) -> list[str]:
    lines = job_block.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    if not first_line:
        return []

    job_indent = len(first_line) - len(first_line.lstrip(" "))
    field_indent = job_indent + 2
    return [
        match.group(1).strip().strip("\"'")
        for line in lines[1:]
        if (
            match := re.match(
                rf"^\s{{{field_indent}}}{re.escape(field)}:"
                r"\s*([^#\r\n]+?)\s*(?:#.*)?$",
                line,
            )
        )
    ]


def _workflow_mapping_block(block: str, field: str) -> str:
    lines = block.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    if not first_line:
        return ""
    first_indent = len(first_line) - len(first_line.lstrip(" "))
    direct_indent = first_indent + 2 if first_line.lstrip().startswith("- ") else first_indent
    for index, line in enumerate(lines):
        match = re.match(
            rf"^\s{{{direct_indent}}}{re.escape(field)}:\s*(?:#.*)?$",
            line,
        )
        if not match:
            continue
        end = len(lines)
        for next_index in range(index + 1, len(lines)):
            next_line = lines[next_index]
            if not next_line.strip():
                continue
            next_indent = len(next_line) - len(next_line.lstrip(" "))
            if next_indent <= direct_indent:
                end = next_index
                break
        return "\n".join(lines[index:end])
    return ""


def _workflow_mapping_direct_scalar_values(mapping_block: str, field: str) -> list[str]:
    lines = mapping_block.splitlines()
    if len(lines) < 2:
        return []

    parent_indent = len(lines[0]) - len(lines[0].lstrip(" "))
    child_indent = next(
        (
            len(line) - len(line.lstrip(" "))
            for line in lines[1:]
            if line.strip()
            and not line.strip().startswith("#")
            and len(line) - len(line.lstrip(" ")) > parent_indent
        ),
        None,
    )
    if child_indent is None:
        return []

    return [
        match.group(1).strip().strip("\"'")
        for line in lines[1:]
        if (
            match := re.match(
                rf"^\s{{{child_indent}}}{re.escape(field)}:"
                r"\s*([^#\r\n]+?)\s*(?:#.*)?$",
                line,
            )
        )
    ]


def _workflow_mapping_duplicate_direct_fields(
    mapping_block: str,
    fields: list[str],
) -> list[str]:
    counts: dict[str, int] = {}
    allowed = set(fields)
    for field in _workflow_mapping_direct_field_names(mapping_block):
        if field in allowed:
            counts[field] = counts.get(field, 0) + 1
    return [field for field in fields if counts.get(field, 0) > 1]


def _workflow_mapping_direct_field_names(mapping_block: str) -> list[str]:
    lines = mapping_block.splitlines()
    if len(lines) < 2:
        return []

    parent_indent = len(lines[0]) - len(lines[0].lstrip(" "))
    child_indent = next(
        (
            len(line) - len(line.lstrip(" "))
            for line in lines[1:]
            if line.strip()
            and not line.strip().startswith("#")
            and len(line) - len(line.lstrip(" ")) > parent_indent
        ),
        None,
    )
    if child_indent is None:
        return []

    return [
        match.group(1)
        for line in lines[1:]
        if (
            match := re.match(
                rf"^\s{{{child_indent}}}([A-Za-z0-9_-]+):(?:\s|$)",
                line,
            )
        )
    ]


def _workflow_upload_with_block(upload_block: str) -> str:
    return _workflow_mapping_block(upload_block, "with")


def _workflow_upload_with_scalar_field_equals(
    upload_block: str,
    field: str,
    expected: str,
) -> bool:
    return expected in _workflow_mapping_direct_scalar_values(
        _workflow_upload_with_block(upload_block),
        field,
    )


def _workflow_upload_artifact_retention_days(upload_block: str) -> int | None:
    values = _workflow_mapping_direct_scalar_values(
        _workflow_upload_with_block(upload_block),
        "retention-days",
    )
    if not values or not values[0].isdigit():
        return None
    return int(values[0])


def _workflow_upload_artifact_paths(upload_block: str) -> list[str]:
    with_block = _workflow_upload_with_block(upload_block)
    lines = with_block.splitlines()
    if not lines:
        return []
    parent_indent = len(lines[0]) - len(lines[0].lstrip(" "))
    child_indent = next(
        (
            len(line) - len(line.lstrip(" "))
            for line in lines[1:]
            if line.strip()
            and not line.strip().startswith("#")
            and len(line) - len(line.lstrip(" ")) > parent_indent
        ),
        None,
    )
    if child_indent is None:
        return []
    path_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(rf"^\s{{{child_indent}}}path:\s*", line)
        ),
        None,
    )
    if path_index is None:
        return []
    path_line = lines[path_index]
    path_indent = len(path_line) - len(path_line.lstrip(" "))
    value = path_line.split(":", 1)[1].strip()
    if value and value not in {"|", "|-", ">", ">-"}:
        return [value.strip("\"'")]

    paths: list[str] = []
    for line in lines[path_index + 1:]:
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= path_indent:
            break
        stripped = line.strip()
        if re.match(r"^[A-Za-z-]+:\s*", stripped):
            break
        paths.append(stripped.strip("\"'"))
    return paths


def _workflow_upload_paths_are_narrow_json(paths: list[str], artifact: str) -> bool:
    if len(paths) != 1:
        return False
    for raw_path in paths:
        normalized = _workflow_normalized_relative_literal(raw_path)
        if not normalized:
            return False
        if any(token in normalized for token in ("*", "?", "[", "]", "{", "}", "$", "%")):
            return False
        if normalized.startswith("~"):
            return False
        posix_path = PurePosixPath(normalized)
        parts = posix_path.parts
        if posix_path.is_absolute() or ".." in parts or not parts:
            return False
        if posix_path.suffix != ".json":
            return False
        return posix_path.name == artifact
    return False


def _workflow_upload_paths_match_expected(
    paths: list[str],
    *,
    artifact: str,
    expected_path: str,
) -> bool:
    return (
        _workflow_upload_paths_are_narrow_json(paths, artifact)
        and _workflow_normalized_relative_literal(paths[0]) == expected_path
    )


def _workflow_upload_block_binds_artifact(
    upload_block: str,
    *,
    artifact: str,
    artifact_token: str,
) -> bool:
    if not _workflow_upload_block_has_artifact_token(upload_block, artifact_token):
        return False
    return _workflow_upload_paths_are_narrow_json(
        _workflow_upload_artifact_paths(upload_block),
        artifact,
    )


def _workflow_upload_block_binds_artifact_path(
    upload_block: str,
    *,
    artifact: str,
    artifact_token: str,
    expected_path: str,
) -> bool:
    if not _workflow_upload_block_has_artifact_token(upload_block, artifact_token):
        return False
    return _workflow_upload_paths_match_expected(
        _workflow_upload_artifact_paths(upload_block),
        artifact=artifact,
        expected_path=expected_path,
    )


def _workflow_upload_block_has_artifact_token(upload_block: str, artifact_token: str) -> bool:
    return artifact_token in _workflow_upload_artifact_names(upload_block)


def _workflow_validation_command_matches(
    command: str,
    *,
    artifact: str,
    requirement_id: str,
) -> bool:
    command_line = re.sub(r"^(?:-\s*)?run:\s*", "", command.strip())
    arguments = _workflow_command_arguments(command_line)
    return _workflow_artifact_validator_arguments_match(
        arguments,
        artifact=artifact,
        requirement_id=requirement_id,
    )


def _workflow_block_validates_artifact(
    block: str,
    *,
    artifact: str,
    requirement_id: str,
) -> bool:
    return any(
        _workflow_validation_command_matches(
            command,
            artifact=artifact,
            requirement_id=requirement_id,
        )
        for command in _workflow_validator_commands(block)
    )


def _workflow_validation_block_expected_upload_path(
    block: str,
    *,
    artifact: str,
    requirement_id: str,
) -> str | None:
    if not _workflow_block_validates_artifact(
        block,
        artifact=artifact,
        requirement_id=requirement_id,
    ):
        return None
    return _workflow_expected_upload_path_for_validation_block(block, artifact)


def _workflow_job_validation_expected_upload_paths(
    job_block: str,
    *,
    artifact: str,
    requirement_id: str,
) -> list[str]:
    paths: list[str] = []
    for block in _workflow_step_blocks(job_block):
        expected_path = _workflow_validation_block_expected_upload_path(
            block,
            artifact=artifact,
            requirement_id=requirement_id,
        )
        if expected_path is not None:
            paths.append(expected_path)
    return paths


def _workflow_job_has_expected_uploads(
    job_block: str,
    *,
    artifact: str,
    artifact_tokens: list[str],
    expected_path: str,
) -> bool:
    upload_blocks = _workflow_upload_artifact_blocks(job_block)
    return all(
        any(
            _workflow_upload_block_binds_artifact_path(
                upload_block,
                artifact=artifact,
                artifact_token=artifact_token,
                expected_path=expected_path,
            )
            for upload_block in upload_blocks
        )
        for artifact_token in artifact_tokens
    )


def _workflow_job_has_bound_validation_upload(
    job_block: str,
    *,
    artifact: str,
    artifact_tokens: list[str],
    requirement_id: str,
) -> bool:
    return any(
        _workflow_job_has_expected_uploads(
            job_block,
            artifact=artifact,
            artifact_tokens=artifact_tokens,
            expected_path=expected_path,
        )
        for expected_path in _workflow_job_validation_expected_upload_paths(
            job_block,
            artifact=artifact,
            requirement_id=requirement_id,
        )
    )


def _workflow_secret_job_matches_registered_requirement(
    job_block: str,
    *,
    requirement_id: str,
    artifact: str,
    artifact_tokens: list[str],
    probe_path: str,
    live_flags: list[str],
    guard_tokens: list[str],
    gate_tokens: list[str],
) -> bool:
    probe_blocks = _workflow_probe_invocation_blocks(job_block, probe_path)
    return (
        all(_workflow_block_sets_unique_env_flag(job_block, flag) for flag in live_flags)
        and bool(probe_blocks)
        and _workflow_probe_blocks_have_guards(
            probe_blocks,
            probe_path=probe_path,
            guard_tokens=guard_tokens,
        )
        and _workflow_job_if_matches_dispatch_or_schedule_gates(job_block, gate_tokens)
        and _workflow_job_needs_contract(job_block)
        and _workflow_job_has_bound_validation_upload(
            job_block,
            artifact=artifact,
            artifact_tokens=artifact_tokens,
            requirement_id=requirement_id,
        )
    )


def _workflow_command_invokes_artifact_validator(command: str) -> bool:
    command_line = re.sub(r"^(?:-\s*)?run:\s*", "", command.strip())
    arguments = _workflow_command_arguments(command_line)
    return _workflow_command_arguments_invoke_artifact_validator(arguments)


def _workflow_command_arguments_invoke_artifact_validator(arguments: list[str]) -> bool:
    return (
        len(arguments) >= 2
        and bool(re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", arguments[0]))
        and _workflow_command_argument_is_canonical_artifact_validator(arguments[1])
    )


def _workflow_artifact_validator_arguments_match(
    arguments: list[str],
    *,
    artifact: str,
    requirement_id: str,
) -> bool:
    if not _workflow_command_arguments_invoke_artifact_validator(arguments):
        return False
    positionals: list[str] = []
    requirement_ids: list[str] = []
    index = 2
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--requirement-id":
            if index + 1 >= len(arguments):
                return False
            requirement_ids.append(arguments[index + 1])
            index += 2
            continue
        if argument.startswith("--requirement-id="):
            requirement_ids.append(argument.split("=", 1)[1])
            index += 1
            continue
        if argument in {"--registry", "--as-of"}:
            if index + 1 >= len(arguments):
                return False
            index += 2
            continue
        if argument.startswith("--registry=") or argument.startswith("--as-of="):
            index += 1
            continue
        if argument == "--json":
            index += 1
            continue
        if argument.startswith("-"):
            return False
        positionals.append(argument)
        index += 1
    return (
        len(positionals) == 1
        and _workflow_artifact_validator_positional_matches(positionals[0], artifact)
        and requirement_ids == [requirement_id]
    )


def _workflow_artifact_validator_positional_matches(argument: str, artifact: str) -> bool:
    return _workflow_normalized_relative_literal(argument) == artifact


def _workflow_expected_upload_path_for_validation_block(block: str, artifact: str) -> str | None:
    values = _workflow_block_direct_scalar_values(block, "working-directory")
    if len(values) > 1:
        return None
    if not values:
        return artifact

    working_directory = _workflow_safe_working_directory(values[0])
    if working_directory is None:
        return None
    return artifact if not working_directory else f"{working_directory}/{artifact}"


def _workflow_safe_working_directory(value: str) -> str | None:
    normalized = _workflow_normalized_relative_literal(value)
    if normalized in {"", "."}:
        return ""
    if any(token in normalized for token in ("*", "?", "[", "]", "{", "}", "$", "%")):
        return None
    if normalized.startswith("~"):
        return None
    posix_path = PurePosixPath(normalized)
    parts = posix_path.parts
    if posix_path.is_absolute() or ".." in parts or not parts:
        return None
    return posix_path.as_posix()


def _workflow_normalized_relative_literal(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _workflow_command_argument_is_canonical_artifact_validator(argument: str) -> bool:
    normalized_argument = posixpath.normpath(argument.replace("\\", "/"))
    return normalized_argument in CANONICAL_ARTIFACT_VALIDATOR_PATHS


def _workflow_uses_refs(workflow_text: str) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for block in _workflow_step_blocks(workflow_text):
        for value in _workflow_block_direct_scalar_values(block, "uses"):
            refs.append(_workflow_split_uses_ref(value))
    return refs


def _workflow_split_uses_ref(value: str) -> tuple[str, str]:
    if "@" not in value:
        return value, ""
    action, ref = value.rsplit("@", 1)
    return action, ref


def _workflow_step_uses_action(block: str, expected_action: str) -> bool:
    for value in _workflow_block_direct_scalar_values(block, "uses"):
        if "@" not in value:
            continue
        action, _ = _workflow_split_uses_ref(value)
        if action == expected_action:
            return True
    return False


def _workflow_checkout_blocks(workflow_text: str) -> list[str]:
    return [
        block
        for block in _workflow_step_blocks(workflow_text)
        if _workflow_step_uses_action(block, "actions/checkout")
    ]


def _workflow_checkout_block_disables_persisted_credentials(checkout_block: str) -> bool:
    return _workflow_mapping_direct_scalar_values(
        _workflow_mapping_block(checkout_block, "with"),
        "persist-credentials",
    ) == ["false"]


def _workflow_block_sets_env_flag(workflow_text: str, flag: str) -> bool:
    for block in _workflow_env_blocks(workflow_text):
        if _workflow_env_block_sets_flag(block, flag):
            return True
    return False


def _workflow_block_sets_unique_env_flag(workflow_text: str, flag: str) -> bool:
    return (
        not _workflow_block_has_duplicate_env_flag(workflow_text, flag)
        and _workflow_block_sets_env_flag(workflow_text, flag)
    )


def _workflow_block_has_duplicate_env_flag(workflow_text: str, flag: str) -> bool:
    return any(
        _workflow_mapping_duplicate_direct_fields(block, [flag])
        for block in _workflow_env_blocks(workflow_text)
    )


def _workflow_env_blocks(workflow_text: str) -> list[str]:
    lines = workflow_text.splitlines()
    blocks: list[str] = []
    active_scalar_indent: int | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if active_scalar_indent is not None:
            if stripped and indent <= active_scalar_indent:
                active_scalar_indent = None
            else:
                index += 1
                continue

        if re.match(r"^\s*(?:[A-Za-z0-9_-]+:|-\s+run:)\s*(?:\||\|-\s*|>|>-\s*)$", line):
            active_scalar_indent = indent
            index += 1
            continue

        if not re.match(r"^\s*env:\s*(?:#.*)?$", line):
            index += 1
            continue

        start = index
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_stripped = next_line.strip()
            next_indent = len(next_line) - len(next_line.lstrip(" "))
            if next_stripped and next_indent <= indent:
                break
            index += 1
        blocks.append("\n".join(lines[start:index]))
    return blocks


def _workflow_env_block_sets_flag(env_block: str, flag: str) -> bool:
    lines = env_block.splitlines()
    if len(lines) < 2:
        return False

    child_indent = next(
        (
            len(line) - len(line.lstrip(" "))
            for line in lines[1:]
            if line.strip() and not line.strip().startswith("#")
        ),
        None,
    )
    if child_indent is None:
        return False

    return any(
        re.match(
            rf"^\s{{{child_indent}}}{re.escape(flag)}:\s*[\"']?1[\"']?\s*(?:#.*)?$",
            line,
        )
        for line in lines[1:]
    )


def _workflow_probe_invocation_blocks(workflow_text: str, probe_path: str) -> list[str]:
    return [
        block
        for block in _workflow_step_blocks(workflow_text)
        if "run:" in block and _workflow_run_block_invokes_probe(block, probe_path)
    ]


def _workflow_probe_blocks_have_guards(
    probe_blocks: list[str],
    *,
    probe_path: str,
    guard_tokens: list[str],
) -> bool:
    return all(
        any(
            _workflow_probe_block_has_guard(probe_block, probe_path, guard_token)
            for probe_block in probe_blocks
        )
        for guard_token in guard_tokens
    )


def _workflow_probe_block_has_guard(
    block: str,
    probe_path: str,
    guard_token: str,
) -> bool:
    return any(
        guard_token in arguments[2:]
        for arguments in _workflow_probe_command_argument_lists(block, probe_path)
    )


def _workflow_probe_block_writes_artifact(
    block: str,
    *,
    probe_path: str,
    artifact: str,
) -> bool:
    for arguments in _workflow_probe_command_argument_lists(block, probe_path):
        for index, argument in enumerate(arguments[2:]):
            if argument == "--out":
                out_index = index + 3
                if out_index < len(arguments) and arguments[out_index] == artifact:
                    return True
            if argument.startswith("--out=") and argument.split("=", 1)[1] == artifact:
                return True
    return False


def _workflow_run_block_invokes_probe(block: str, probe_path: str) -> bool:
    return bool(_workflow_probe_command_lines(block, probe_path))


def _workflow_probe_command_lines(block: str, probe_path: str) -> list[str]:
    normalized_probe_path = probe_path.replace("\\", "/")
    suffix = PurePosixPath(normalized_probe_path).suffix
    path_tokens = _workflow_probe_path_tokens(normalized_probe_path)
    return [
        line
        for line in _workflow_run_command_lines(block)
        if _workflow_command_line_invokes_probe(
            line,
            suffix=suffix,
            path_tokens=path_tokens,
        )
    ]


def _workflow_probe_command_argument_lists(block: str, probe_path: str) -> list[list[str]]:
    normalized_probe_path = probe_path.replace("\\", "/")
    suffix = PurePosixPath(normalized_probe_path).suffix
    path_tokens = _workflow_probe_path_tokens(normalized_probe_path)
    return [
        arguments
        for line in _workflow_run_command_lines(block)
        if _workflow_command_arguments_invoke_probe(
            arguments := _workflow_command_arguments(line),
            suffix=suffix,
            path_tokens=path_tokens,
        )
    ]


def _workflow_command_line_invokes_probe(
    command_line: str,
    *,
    suffix: str,
    path_tokens: set[str],
) -> bool:
    arguments = _workflow_command_arguments(command_line)
    return _workflow_command_arguments_invoke_probe(
        arguments,
        suffix=suffix,
        path_tokens=path_tokens,
    )


def _workflow_command_arguments_invoke_probe(
    arguments: list[str],
    *,
    suffix: str,
    path_tokens: set[str],
) -> bool:
    if len(arguments) < 2:
        return False
    if _workflow_command_arguments_have_shell_control(arguments):
        return False
    runner = arguments[0]
    if suffix == ".py":
        if not re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", runner):
            return False
    elif suffix == ".mjs":
        if runner != "node":
            return False
    else:
        return False
    return _workflow_command_argument_matches_path(arguments[1], path_tokens)


def _workflow_command_arguments_have_shell_control(arguments: list[str]) -> bool:
    shell_tokens = (";", "&&", "||", "|", "&")
    return any(any(token in argument for token in shell_tokens) for argument in arguments)


def _workflow_command_arguments(command_line: str) -> list[str]:
    try:
        return [argument.replace("\\", "/") for argument in shlex.split(command_line)]
    except ValueError:
        return []


def _workflow_command_argument_matches_path(
    argument: str,
    path_tokens: set[str],
) -> bool:
    normalized_argument = argument.replace("\\", "/")
    normalized_candidates = {
        normalized_argument,
        normalized_argument.removeprefix("./"),
        str(PurePosixPath(normalized_argument)),
    }
    return any(candidate in path_tokens for candidate in normalized_candidates)


def _workflow_job_has_probe_validation_upload_order(
    job_block: str,
    *,
    probe_path: str,
    artifact: str,
    artifact_tokens: list[str],
    requirement_id: str,
    guard_tokens: list[str],
) -> bool:
    probe_seen = False
    validation_seen = False
    expected_upload_path: str | None = None
    for block in _workflow_step_blocks(job_block):
        if not probe_seen:
            if (
                "run:" in block
                and _workflow_run_block_invokes_probe(block, probe_path)
                and all(
                    _workflow_probe_block_has_guard(block, probe_path, guard_token)
                    for guard_token in guard_tokens
                )
            ):
                probe_seen = True
            continue

        if not validation_seen:
            expected_path = _workflow_validation_block_expected_upload_path(
                block,
                artifact=artifact,
                requirement_id=requirement_id,
            )
            if expected_path is not None:
                validation_seen = True
                expected_upload_path = expected_path
            continue

        if (
            expected_upload_path is not None
            and _workflow_step_uses_action(block, "actions/upload-artifact")
            and all(
                _workflow_upload_block_binds_artifact_path(
                    block,
                    artifact=artifact,
                    artifact_token=artifact_token,
                    expected_path=expected_upload_path,
                )
                for artifact_token in artifact_tokens
            )
        ):
            return True
    return False


def _workflow_job_has_diagnostic_validation_upload_order(
    job_block: str,
    *,
    spec: DiagnosticUploadSpec,
) -> bool:
    validation_seen = False
    for block in _workflow_step_blocks(job_block):
        if not validation_seen:
            if _workflow_block_validates_preflight(
                block,
                artifact=spec.artifact,
                requirement_id=spec.requirement_id,
            ) and _workflow_run_block_removes_preflight_on_validation_failure(
                block,
                spec.artifact,
            ):
                validation_seen = True
            continue

        if (
            _workflow_step_uses_action(block, "actions/upload-artifact")
            and all(
                _workflow_upload_block_binds_artifact_path(
                    block,
                    artifact=spec.artifact,
                    artifact_token=token,
                    expected_path=spec.path,
                )
                for token in spec.artifact_tokens
            )
        ):
            return True
    return False


def _workflow_block_validates_preflight(
    block: str,
    *,
    artifact: str,
    requirement_id: str,
) -> bool:
    if "run:" not in block:
        return False
    command_text = _workflow_run_command_text(block)
    return (
        "validate_runtime_evidence_preflight.py" in command_text
        and _text_mentions_bounded_token(command_text, artifact)
        and _text_mentions_bounded_token(command_text, "--requirement-id")
        and _text_mentions_bounded_token(command_text, requirement_id)
    )


def _workflow_run_block_removes_preflight_on_validation_failure(
    block: str,
    artifact: str,
) -> bool:
    if "run:" not in block:
        return False
    command_text = _workflow_run_command_text(block)
    return (
        _text_mentions_bounded_token(command_text, "preflight_validation_status")
        and _text_mentions_bounded_token(command_text, f"rm -f {artifact}")
        and _text_mentions_bounded_token(command_text, 'exit "${preflight_validation_status}"')
    )


def _workflow_run_block_starts_with_strict_shell(block: str) -> bool:
    if "run: |" not in block:
        return True
    lines = block.splitlines()
    run_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^\s*(?:-\s*)?run:\s*\|\s*$", line)
        ),
        None,
    )
    if run_index is None:
        return True
    for line in lines[run_index + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        return stripped == "set -euo pipefail"
    return False


def _workflow_job_checks_out_before_probe(job_block: str, probe_path: str) -> bool:
    checkout_seen = False
    for block in _workflow_step_blocks(job_block):
        if _workflow_step_uses_action(block, "actions/checkout"):
            if _workflow_checkout_block_disables_persisted_credentials(block):
                checkout_seen = True
            continue
        if "run:" in block and _workflow_run_block_invokes_probe(block, probe_path):
            return checkout_seen
    return False


def _workflow_repo_path_tokens(repo_path: str) -> set[str]:
    normalized_path = repo_path.replace("\\", "/")
    tokens = {normalized_path}
    for prefix in ("maritime-ai-service/", "wiii-desktop/"):
        if normalized_path.startswith(prefix):
            tokens.add(normalized_path[len(prefix):])
    return {token for token in tokens if token}


def _workflow_probe_path_tokens(probe_path: str) -> set[str]:
    return _workflow_repo_path_tokens(probe_path)


def _workflow_contract_test_path_tokens(test_path: str) -> set[str]:
    return _workflow_repo_path_tokens(test_path)


def _workflow_run_block_mentions_path_token(block: str, path_tokens: set[str]) -> bool:
    command_text = _workflow_run_command_text(block)
    return any(
        _text_mentions_bounded_token(command_text, token)
        for token in path_tokens
    )


def _workflow_runs_contract_test(workflow_text: str, test_path: str) -> bool:
    normalized_test_path = test_path.replace("\\", "/")
    path_tokens = _workflow_contract_test_path_tokens(normalized_test_path)
    suffix = PurePosixPath(normalized_test_path).suffix
    for block in _workflow_step_blocks(workflow_text):
        if "run:" not in block:
            continue
        if not _workflow_run_block_mentions_path_token(block, path_tokens):
            continue
        if any(
            _workflow_command_line_runs_contract_test(
                line,
                suffix=suffix,
                path_tokens=path_tokens,
            )
            for line in _workflow_run_command_lines(block)
        ):
            return True
    return False


def _workflow_contract_job_runs_test(workflow_text: str, test_path: str) -> bool:
    contract_block = next(
        (block for job_name, block in _workflow_job_blocks(workflow_text) if job_name == "contract"),
        "",
    )
    if not contract_block:
        return False
    return _workflow_runs_contract_test(contract_block, test_path)


def _workflow_contract_job_runs_node_script(workflow_text: str, script_path: str) -> bool:
    contract_block = next(
        (block for job_name, block in _workflow_job_blocks(workflow_text) if job_name == "contract"),
        "",
    )
    if not contract_block:
        return False
    path_tokens = _workflow_contract_test_path_tokens(script_path)
    for block in _workflow_step_blocks(contract_block):
        if "run:" not in block:
            continue
        if not _workflow_run_block_mentions_path_token(block, path_tokens):
            continue
        if any(
            _workflow_command_line_runs_node_script(line, path_tokens=path_tokens)
            for line in _workflow_run_command_lines(block)
        ):
            return True
    return False


def _workflow_contract_job_checks_out_before_test(
    workflow_text: str,
    test_path: str,
) -> bool:
    contract_block = next(
        (block for job_name, block in _workflow_job_blocks(workflow_text) if job_name == "contract"),
        "",
    )
    if not contract_block:
        return False
    return _workflow_job_checks_out_before_contract_test(contract_block, test_path)


def _workflow_job_checks_out_before_contract_test(job_block: str, test_path: str) -> bool:
    path_tokens = _workflow_contract_test_path_tokens(test_path)
    suffix = PurePosixPath(test_path.replace("\\", "/")).suffix
    checkout_seen = False
    for block in _workflow_step_blocks(job_block):
        if _workflow_step_uses_action(block, "actions/checkout"):
            if _workflow_checkout_block_disables_persisted_credentials(block):
                checkout_seen = True
            continue
        if "run:" not in block:
            continue
        if not _workflow_run_block_mentions_path_token(block, path_tokens):
            continue
        if any(
            _workflow_command_line_runs_contract_test(
                line,
                suffix=suffix,
                path_tokens=path_tokens,
            )
            for line in _workflow_run_command_lines(block)
        ):
            return checkout_seen
    return False


def _workflow_run_command_lines(block: str) -> list[str]:
    lines: list[str] = []
    for raw_line in _workflow_run_command_text(block).splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        match = re.match(r"^(?:-\s*)?run:\s*(.*?)\s*$", stripped)
        if match:
            inline_command = match.group(1).strip()
            if inline_command and inline_command not in {"|", "|-", ">", ">-"}:
                lines.append(inline_command)
            continue
        lines.append(stripped)
    return lines


def _workflow_command_line_runs_contract_test(
    command_line: str,
    *,
    suffix: str,
    path_tokens: set[str],
) -> bool:
    if not any(_text_mentions_bounded_token(command_line, token) for token in path_tokens):
        return False
    runner_pattern = (
        re.compile(r"^(?:python\s+-m\s+)?pytest(?:\s|$)")
        if suffix == ".py"
        else re.compile(r"^(?:npx\s+)?vitest(?:\s|$)")
    )
    return bool(runner_pattern.search(command_line))


def _workflow_command_line_runs_node_script(
    command_line: str,
    *,
    path_tokens: set[str],
) -> bool:
    arguments = _workflow_command_arguments(command_line)
    if len(arguments) < 2:
        return False
    if _workflow_command_arguments_have_shell_control(arguments):
        return False
    return arguments[0] == "node" and _workflow_command_argument_matches_path(
        arguments[1],
        path_tokens,
    )


def _runtime_evidence_output_helper_paths_for_probe(
    probe_path: Path | None,
    *,
    repo_root: Path,
) -> tuple[str, str] | None:
    if probe_path is None:
        return None
    try:
        relative_probe = probe_path.relative_to(repo_root)
    except ValueError:
        return None
    if probe_path.suffix == ".py":
        helper_path = relative_probe.with_name("runtime_evidence_output.py")
        if relative_probe.parts and relative_probe.parts[0] == "maritime-ai-service":
            helper_test_path = Path(
                "maritime-ai-service",
                "tests",
                "unit",
                PYTHON_RUNTIME_EVIDENCE_HELPER_TEST_NAME,
            )
        else:
            helper_test_path = Path("tests", PYTHON_RUNTIME_EVIDENCE_HELPER_TEST_NAME)
        return helper_path.as_posix(), helper_test_path.as_posix()
    if probe_path.suffix == ".mjs":
        return (
            relative_probe.with_name("runtime-evidence-output.mjs").as_posix(),
            relative_probe.with_name(MJS_RUNTIME_EVIDENCE_HELPER_TEST_NAME).as_posix(),
        )
    return None


def _workflow_command_enables_shell_xtrace(command_line: str) -> bool:
    try:
        arguments = shlex.split(command_line, posix=True)
    except ValueError:
        return False
    if not arguments:
        return False
    command = arguments[0]
    if command == "set":
        return any(
            argument.startswith("-")
            and not argument.startswith("--")
            and "x" in argument[1:]
            for argument in arguments[1:]
        ) or ("-o" in arguments[1:] and "xtrace" in arguments[1:])
    if command in {"bash", "sh"}:
        return any(
            argument.startswith("-")
            and not argument.startswith("--")
            and "x" in argument[1:]
            for argument in arguments[1:]
        )
    return False


def _workflow_contract_job_is_unconditional(workflow_text: str) -> bool:
    contract_block = next(
        (block for job_name, block in _workflow_job_blocks(workflow_text) if job_name == "contract"),
        "",
    )
    return bool(contract_block) and re.search(r"(?m)^\s{4}if:\s*", contract_block) is None


def _workflow_job_needs_contract(job_block: str) -> bool:
    if re.search(r"(?m)^\s{4}needs:\s*contract\s*$", job_block):
        return True
    if re.search(r"(?m)^\s{4}needs:\s*\[[^\]]*\bcontract\b[^\]]*\]\s*$", job_block):
        return True

    lines = job_block.splitlines()
    needs_index = next(
        (index for index, line in enumerate(lines) if re.match(r"^\s{4}needs:\s*$", line)),
        None,
    )
    if needs_index is None:
        return False
    for line in lines[needs_index + 1:]:
        if line.startswith("    ") and not line.startswith("      "):
            break
        if re.match(r"^\s{6}-\s*contract\s*$", line):
            return True
    return False


def _workflow_job_block_has_gate(job_block: str, token: str) -> bool:
    if_text = _workflow_job_if_text(job_block)
    if token.startswith(("allow_", "run_")):
        return (
            "github.event_name == 'workflow_dispatch'" in if_text
            and f"inputs.{token} == true" in if_text
        )
    if token.startswith("WIII_") and token.endswith("_EVIDENCE_ENABLED"):
        return (
            "github.event_name == 'schedule'" in if_text
            and f"vars.{token} == '1'" in if_text
        )
    return token in if_text


def _workflow_job_if_matches_dispatch_or_schedule_gates(
    job_block: str,
    gate_tokens: list[str],
) -> bool:
    dispatch_tokens = [
        token
        for token in gate_tokens
        if token.startswith(("allow_", "run_"))
    ]
    schedule_tokens = [
        token
        for token in gate_tokens
        if token.startswith("WIII_") and token.endswith("_EVIDENCE_ENABLED")
    ]
    if len(dispatch_tokens) != 1 or len(schedule_tokens) != 1:
        return False

    dispatch_token = dispatch_tokens[0]
    schedule_token = schedule_tokens[0]
    normalized_if = _normalize_workflow_if_expression(_workflow_job_if_text(job_block))
    dispatch_gate = (
        "(github.event_name=='workflow_dispatch'"
        f"&&inputs.{dispatch_token}==true)"
    )
    schedule_gate = (
        "(github.event_name=='schedule'"
        f"&&vars.{schedule_token}=='1')"
    )
    expected_orders = {
        dispatch_gate + "||" + schedule_gate,
        schedule_gate + "||" + dispatch_gate,
    }
    return normalized_if in expected_orders | {
        f"({expected})" for expected in expected_orders
    }


def _workflow_job_if_matches_any_dispatch_or_schedule_gate_pair(
    job_block: str,
    gate_tokens: list[str],
) -> bool:
    dispatch_tokens = sorted(
        {
            token
            for token in gate_tokens
            if token.startswith(("allow_", "run_"))
        }
    )
    schedule_tokens = sorted(
        {
            token
            for token in gate_tokens
            if token.startswith("WIII_") and token.endswith("_EVIDENCE_ENABLED")
        }
    )
    return any(
        _workflow_job_if_matches_dispatch_or_schedule_gates(
            job_block,
            [dispatch_token, schedule_token],
        )
        for dispatch_token in dispatch_tokens
        for schedule_token in schedule_tokens
    )


def _workflow_production_override_flags_are_guarded(workflow_text: str) -> bool:
    found_flag = False
    for block in _workflow_step_blocks(workflow_text):
        in_production_guard = False
        heredoc_delimiter: str | None = None
        for raw_line in _workflow_run_command_text(block).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if heredoc_delimiter is not None:
                if line == heredoc_delimiter:
                    heredoc_delimiter = None
                continue
            heredoc_delimiter = _workflow_shell_heredoc_delimiter(line)
            if line == PRODUCTION_OVERRIDE_GUARD_LINE:
                in_production_guard = True
                continue
            if line == "fi" and in_production_guard:
                in_production_guard = False
                continue
            if PRODUCTION_OVERRIDE_FLAG not in line:
                continue
            found_flag = True
            if not in_production_guard or line != PRODUCTION_OVERRIDE_APPEND_LINE:
                return False
    return found_flag


def _probe_supports_production_override(probe_text: str) -> bool:
    return (
        PRODUCTION_OVERRIDE_FLAG in probe_text
        and re.search(r"\ballow_production\b", probe_text) is not None
    )


def _python_probe_argparse_store_true_flags(probe_text: str) -> set[str]:
    try:
        tree = ast.parse(probe_text)
    except SyntaxError:
        return set()

    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        has_store_true = any(
            keyword.arg == "action"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "store_true"
            for keyword in node.keywords
        )
        if not has_store_true:
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                flags.add(argument.value)
    return flags


def _python_probe_argparse_flags(probe_text: str) -> set[str]:
    try:
        tree = ast.parse(probe_text)
    except SyntaxError:
        return set()

    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                flags.add(argument.value)
    return flags


def _python_probe_imports_runtime_evidence_output_helper(probe_text: str) -> bool:
    try:
        tree = ast.parse(probe_text)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "runtime_evidence_output":
            continue
        if any(alias.name == "emit_json_payload" for alias in node.names):
            return True
    return False


def _python_probe_calls_output_helper_with_output_path(probe_text: str) -> bool:
    try:
        tree = ast.parse(probe_text)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "emit_json_payload":
            continue
        if len(node.args) >= 2 and not _ast_value_is_none(node.args[1]):
            return True
        for keyword in node.keywords:
            if keyword.arg == "out_path" and not _ast_value_is_none(keyword.value):
                return True
    return False


def _ast_value_is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _python_probe_raw_file_write_calls(probe_text: str) -> list[str]:
    try:
        tree = ast.parse(probe_text)
    except SyntaxError:
        return []

    json_aliases = _python_imported_module_aliases(tree, "json")
    json_dump_names = _python_imported_member_aliases(tree, "json", {"dump"})
    os_aliases = _python_imported_module_aliases(tree, "os")
    os_write_names = _python_imported_member_aliases(tree, "os", {"open", "write"})
    file_open_names = {"open"}
    file_open_names.update(_python_imported_member_aliases(tree, "io", {"open"}))
    file_open_names.update(_python_imported_member_aliases(tree, "codecs", {"open"}))
    file_open_names.update(_python_imported_member_aliases(tree, "builtins", {"open"}))
    string_constants = _python_string_constants(tree)

    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _ast_call_is_json_dump(
            node,
            json_aliases=json_aliases,
            json_dump_names=json_dump_names,
        ):
            calls.add("json.dump")
        if raw_os_call := _ast_os_raw_file_write_call(
            node,
            os_aliases=os_aliases,
            os_write_names=os_write_names,
        ):
            calls.add(raw_os_call)
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in {"write_text", "write_bytes"}:
                calls.add(node.func.attr)
            elif node.func.attr == "open" and _python_open_call_can_write(
                node,
                string_constants=string_constants,
            ):
                calls.add("open")
        elif isinstance(node.func, ast.Name) and node.func.id in file_open_names:
            if _python_open_call_can_write(
                node,
                string_constants=string_constants,
            ):
                calls.add("open")
    return sorted(calls)


def _python_imported_module_aliases(tree: ast.AST, module_name: str) -> set[str]:
    aliases = {module_name}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.name == module_name:
                aliases.add(alias.asname or alias.name)
    return aliases


def _python_imported_member_aliases(
    tree: ast.AST,
    module_name: str,
    member_names: set[str],
) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != module_name:
            continue
        for alias in node.names:
            if alias.name in member_names:
                aliases.add(alias.asname or alias.name)
    return aliases


def _python_string_constants(tree: ast.AST) -> dict[str, str]:
    constants: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            value: ast.AST
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
                if value is None:
                    continue
            else:
                continue
            resolved = _python_resolve_string_expression(
                value,
                string_constants=constants,
            )
            if resolved is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in constants:
                    constants[target.id] = resolved
                    changed = True
    return constants


def _python_resolve_string_expression(
    node: ast.AST,
    *,
    string_constants: dict[str, str],
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return string_constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _python_resolve_string_expression(
            node.left,
            string_constants=string_constants,
        )
        right = _python_resolve_string_expression(
            node.right,
            string_constants=string_constants,
        )
        if left is not None and right is not None:
            return left + right
    return None


def _python_open_call_can_write(
    node: ast.Call,
    *,
    string_constants: dict[str, str],
) -> bool:
    if len(node.args) >= 2:
        return _python_file_mode_can_write(
            node.args[1],
            string_constants=string_constants,
        )
    for keyword in node.keywords:
        if keyword.arg == "mode":
            return _python_file_mode_can_write(
                keyword.value,
                string_constants=string_constants,
            )
    return False


def _python_file_mode_can_write(
    node: ast.AST,
    *,
    string_constants: dict[str, str],
) -> bool:
    mode = _python_resolve_string_expression(
        node,
        string_constants=string_constants,
    )
    if mode is None:
        return False
    return any(marker in mode for marker in ("w", "a", "x", "+"))


def _ast_call_is_json_dump(
    node: ast.Call,
    *,
    json_aliases: set[str],
    json_dump_names: set[str],
) -> bool:
    if isinstance(node.func, ast.Name) and node.func.id in json_dump_names:
        return True
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "dump"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in json_aliases
    )


def _ast_os_raw_file_write_call(
    node: ast.Call,
    *,
    os_aliases: set[str],
    os_write_names: set[str],
) -> str | None:
    if isinstance(node.func, ast.Name) and node.func.id in os_write_names:
        return f"os.{node.func.id}"
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in {"open", "write"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in os_aliases
    ):
        return f"os.{node.func.attr}"
    return None


def _mjs_probe_fail_closed_guard_tokens(probe_text: str) -> set[str]:
    code, string_values = _javascript_code_with_string_markers(probe_text)
    marker_pattern = r"__JS_STRING_([0-9]+)__"
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    constants = _javascript_const_string_values(code, string_values)

    flags: set[str] = set()
    expression_pattern = rf"(?:{marker_pattern}|{name_pattern})"
    condition_pattern = re.compile(
        rf"^\s*!\s*process\.argv\.includes\(\s*"
        rf"({expression_pattern})\s*\)\s*$",
        re.DOTALL,
    )
    for condition, body in _javascript_top_level_if_blocks(code):
        match = condition_pattern.fullmatch(condition)
        if not match or re.search(r"\bfail\s*\(", body) is None:
            continue
        token = _javascript_resolve_string_expression(
            match.group(1),
            constants=constants,
            string_values=string_values,
        )
        if token:
            flags.add(token)
    return flags


def _javascript_const_string_values(
    code: str,
    string_values: list[str],
) -> dict[str, str]:
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    declaration_pattern = re.compile(
        rf"(?m)^\s*const\s+({name_pattern})\s*=\s*(?P<expression>[^;\n]+)\s*;",
    )
    declarations = [
        (match.group(1), match.group("expression").strip())
        for match in declaration_pattern.finditer(code)
    ]
    constants: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for name, expression in declarations:
            if name in constants:
                continue
            value = _javascript_resolve_const_string_expression(
                expression,
                constants=constants,
                string_values=string_values,
            )
            if value is None:
                continue
            constants[name] = value
            changed = True
    return constants


def _javascript_resolve_const_string_expression(
    expression: str,
    *,
    constants: dict[str, str],
    string_values: list[str],
) -> str | None:
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    marker_pattern = r"__JS_STRING_[0-9]+__"
    value_parts: list[str] = []
    for part in expression.split("+"):
        cleaned = part.strip()
        if not cleaned:
            return None
        marker_match = re.fullmatch(marker_pattern, cleaned)
        if marker_match:
            value_parts.append(_javascript_resolve_string_marker(cleaned, string_values))
            continue
        if re.fullmatch(name_pattern, cleaned) and cleaned in constants:
            value_parts.append(constants[cleaned])
            continue
        return None
    return "".join(value_parts)


def _javascript_resolve_string_marker(
    marker: str,
    string_values: list[str],
) -> str:
    marker_match = re.fullmatch(r"__JS_STRING_([0-9]+)__", marker)
    if not marker_match:
        return ""
    return string_values[int(marker_match.group(1))]


def _mjs_probe_fail_function_exits_nonzero(probe_text: str) -> bool:
    code, _ = _javascript_code_with_string_markers(probe_text)
    body = _javascript_function_body(code, "fail")
    return bool(body) and _javascript_body_calls_process_exit_nonzero(body)


def _mjs_probe_handles_output_argument(probe_text: str) -> bool:
    code, string_values = _javascript_code_with_string_markers(probe_text)
    return bool(_mjs_probe_output_arg_return_properties(code, string_values))


def _mjs_probe_forwards_output_to_summary_env(probe_text: str) -> bool:
    code, string_values = _javascript_code_with_string_markers(probe_text)
    constants = _javascript_const_string_values(code, string_values)
    output_properties = _mjs_probe_output_arg_return_properties(code, string_values)
    output_vars = _javascript_parse_args_destructured_variables(
        code,
        returned_properties=output_properties,
    )
    if not output_vars:
        return False

    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    env_expressions = [
        re.escape(f"__JS_STRING_{index}__")
        for index, value in enumerate(string_values)
        if value == "WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON"
    ]
    env_expressions.extend(
        re.escape(name)
        for name, value in constants.items()
        if value == "WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON"
    )
    if not env_expressions:
        return False

    env_expression = "|".join(env_expressions)
    assignment_pattern = rf"(?:\[\s*(?:{env_expression})\s*\]|(?:{env_expression}))\s*:\s*({name_pattern})"
    return any(
        _javascript_spawn_sync_forwards_summary_env(
            arguments,
            assignment_pattern=assignment_pattern,
            output_vars=output_vars,
        )
        for arguments in _javascript_call_argument_lists(code, "spawnSync")
    )


def _javascript_spawn_sync_forwards_summary_env(
    arguments: list[str],
    *,
    assignment_pattern: str,
    output_vars: set[str],
) -> bool:
    if len(arguments) < 3:
        return False
    if arguments[0].strip() != "process.execPath":
        return False
    if "runner" not in arguments[1] or "forwarded" not in arguments[1]:
        return False
    match = re.search(assignment_pattern, arguments[2])
    return bool(match) and match.group(1) in output_vars


MJS_RAW_FILE_WRITE_FUNCTIONS = {
    "appendFile",
    "appendFileSync",
    "createWriteStream",
    "writeFile",
    "writeFileSync",
}
MJS_RAW_PROMISE_FILE_WRITE_FUNCTIONS = {"appendFile", "writeFile"}
MJS_RAW_FS_MODULES = {"fs", "node:fs"}
MJS_RAW_FS_PROMISE_MODULES = {"fs/promises", "node:fs/promises"}


def _mjs_probe_raw_file_write_calls(probe_text: str) -> list[str]:
    code, string_values = _javascript_code_with_string_markers(probe_text)
    constants = _javascript_const_string_values(code, string_values)
    direct_names = set(MJS_RAW_FILE_WRITE_FUNCTIONS)
    direct_names.update(_javascript_named_fs_write_imports(code, string_values))
    direct_names.update(
        _javascript_named_fs_promises_write_imports(code, string_values)
    )
    direct_names.update(_javascript_dynamic_fs_write_imports(code, string_values, constants))
    direct_names.update(
        _javascript_dynamic_fs_promises_write_imports(code, string_values, constants)
    )
    direct_names.update(_javascript_require_fs_write_imports(code, string_values, constants))
    direct_names.update(
        _javascript_require_fs_promises_write_imports(code, string_values, constants)
    )
    namespace_names = _javascript_fs_namespace_imports(code, string_values)
    namespace_names.update(
        _javascript_dynamic_fs_namespace_imports(code, string_values, constants)
    )
    namespace_names.update(
        _javascript_require_fs_namespace_imports(code, string_values, constants)
    )
    promise_namespace_names = _javascript_fs_promises_namespace_imports(
        code,
        string_values,
    )
    promise_namespace_names.update(
        _javascript_dynamic_fs_promises_namespace_imports(code, string_values, constants)
    )
    promise_namespace_names.update(
        _javascript_require_fs_promises_namespace_imports(code, string_values, constants)
    )
    promise_namespace_names.update(
        _javascript_dynamic_fs_promises_member_imports(code, string_values, constants)
    )
    promise_namespace_names.update(
        _javascript_require_fs_promises_member_imports(code, string_values, constants)
    )

    calls: set[str] = set()
    for name in direct_names:
        if re.search(rf"\b{re.escape(name)}\s*\(", code):
            calls.add(name)

    for function_name in MJS_RAW_FILE_WRITE_FUNCTIONS:
        if _javascript_inline_module_function_call(
            code,
            string_values,
            constants,
            module_values=MJS_RAW_FS_MODULES,
            function_name=function_name,
        ):
            calls.add(f"inline.{function_name}")
    for function_name in MJS_RAW_PROMISE_FILE_WRITE_FUNCTIONS:
        if _javascript_inline_module_function_call(
            code,
            string_values,
            constants,
            module_values=MJS_RAW_FS_PROMISE_MODULES,
            function_name=function_name,
        ):
            calls.add(f"inline.{function_name}")
        if _javascript_inline_module_promises_function_call(
            code,
            string_values,
            constants,
            module_values=MJS_RAW_FS_MODULES,
            function_name=function_name,
        ):
            calls.add(f"inline.promises.{function_name}")

    for namespace in namespace_names:
        for function_name in MJS_RAW_FILE_WRITE_FUNCTIONS:
            if _javascript_namespace_function_call(
                code,
                namespace=namespace,
                function_name=function_name,
                string_values=string_values,
                constants=constants,
            ):
                calls.add(f"{namespace}.{function_name}")
        for function_name in ("appendFile", "writeFile"):
            if _javascript_namespace_promises_function_call(
                code,
                namespace=namespace,
                function_name=function_name,
                string_values=string_values,
                constants=constants,
            ):
                calls.add(f"{namespace}.promises.{function_name}")
    for namespace in promise_namespace_names:
        for function_name in MJS_RAW_PROMISE_FILE_WRITE_FUNCTIONS:
            if _javascript_namespace_function_call(
                code,
                namespace=namespace,
                function_name=function_name,
                string_values=string_values,
                constants=constants,
            ):
                calls.add(f"{namespace}.{function_name}")
    return sorted(calls)


def _javascript_named_fs_write_imports(
    code: str,
    string_values: list[str],
) -> set[str]:
    names: set[str] = set()
    module_pattern = _javascript_string_module_pattern(string_values, MJS_RAW_FS_MODULES)
    if not module_pattern:
        return names
    import_pattern = re.compile(
        rf"\bimport\s+(?:[A-Za-z_$][A-Za-z0-9_$]*\s*,\s*)?"
        rf"\{{(?P<body>[^}}]+)\}}\s*from\s*(?:{module_pattern})\s*;",
    )
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    for match in import_pattern.finditer(code):
        for part in match.group("body").split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            import_match = re.match(
                rf"^(?P<imported>{name_pattern})"
                rf"(?:\s+as\s+(?P<local>{name_pattern}))?$",
                cleaned,
            )
            if not import_match:
                continue
            imported = import_match.group("imported")
            if imported not in MJS_RAW_FILE_WRITE_FUNCTIONS:
                continue
            names.add(import_match.group("local") or imported)
    return names


def _javascript_named_fs_promises_write_imports(
    code: str,
    string_values: list[str],
) -> set[str]:
    names: set[str] = set()
    module_pattern = _javascript_string_module_pattern(
        string_values,
        MJS_RAW_FS_PROMISE_MODULES,
    )
    if not module_pattern:
        return names
    import_pattern = re.compile(
        rf"\bimport\s+(?:[A-Za-z_$][A-Za-z0-9_$]*\s*,\s*)?"
        rf"\{{(?P<body>[^}}]+)\}}\s*from\s*(?:{module_pattern})\s*;",
    )
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    for match in import_pattern.finditer(code):
        for part in match.group("body").split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            import_match = re.match(
                rf"^(?P<imported>{name_pattern})"
                rf"(?:\s+as\s+(?P<local>{name_pattern}))?$",
                cleaned,
            )
            if not import_match:
                continue
            imported = import_match.group("imported")
            if imported not in MJS_RAW_PROMISE_FILE_WRITE_FUNCTIONS:
                continue
            names.add(import_match.group("local") or imported)
    return names


def _javascript_dynamic_fs_write_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_MODULES,
    )
    return _javascript_dynamic_named_imports(
        code,
        module_pattern=module_pattern,
        imported_names=MJS_RAW_FILE_WRITE_FUNCTIONS,
    )


def _javascript_dynamic_fs_promises_write_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_PROMISE_MODULES,
    )
    return _javascript_dynamic_named_imports(
        code,
        module_pattern=module_pattern,
        imported_names=MJS_RAW_PROMISE_FILE_WRITE_FUNCTIONS,
    )


def _javascript_require_fs_write_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_MODULES,
    )
    return _javascript_require_named_imports(
        code,
        module_pattern=module_pattern,
        imported_names=MJS_RAW_FILE_WRITE_FUNCTIONS,
    )


def _javascript_require_fs_promises_write_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_PROMISE_MODULES,
    )
    return _javascript_require_named_imports(
        code,
        module_pattern=module_pattern,
        imported_names=MJS_RAW_PROMISE_FILE_WRITE_FUNCTIONS,
    )


def _javascript_dynamic_fs_promises_member_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_MODULES,
    )
    return _javascript_dynamic_named_imports(
        code,
        module_pattern=module_pattern,
        imported_names={"promises"},
    )


def _javascript_require_fs_promises_member_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_MODULES,
    )
    return _javascript_require_named_imports(
        code,
        module_pattern=module_pattern,
        imported_names={"promises"},
    )


def _javascript_dynamic_named_imports(
    code: str,
    *,
    module_pattern: str,
    imported_names: set[str],
) -> set[str]:
    if not module_pattern:
        return set()
    import_pattern = re.compile(
        rf"\b(?:const|let|var)\s*\{{(?P<body>[^}}]+)\}}\s*=\s*"
        rf"(?:await\s+)?import\s*\(\s*(?:{module_pattern})\s*\)\s*;",
    )
    names: set[str] = set()
    for match in import_pattern.finditer(code):
        names.update(
            _javascript_destructured_binding_names(
                match.group("body"),
                imported_names=imported_names,
            )
        )
    return names


def _javascript_require_named_imports(
    code: str,
    *,
    module_pattern: str,
    imported_names: set[str],
) -> set[str]:
    if not module_pattern:
        return set()
    import_pattern = re.compile(
        rf"\b(?:const|let|var)\s*\{{(?P<body>[^}}]+)\}}\s*=\s*"
        rf"require\s*\(\s*(?:{module_pattern})\s*\)\s*;",
    )
    names: set[str] = set()
    for match in import_pattern.finditer(code):
        names.update(
            _javascript_destructured_binding_names(
                match.group("body"),
                imported_names=imported_names,
            )
        )
    return names


def _javascript_destructured_binding_names(
    body: str,
    *,
    imported_names: set[str],
) -> set[str]:
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    names: set[str] = set()
    for part in body.split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        cleaned = _javascript_binding_without_default_initializer(cleaned)
        import_match = re.match(
            rf"^(?P<imported>{name_pattern})"
            rf"(?:\s*:\s*(?P<local>{name_pattern}))?$",
            cleaned,
        )
        if not import_match:
            continue
        imported = import_match.group("imported")
        if imported not in imported_names:
            continue
        names.add(import_match.group("local") or imported)
    return names


def _javascript_fs_namespace_imports(
    code: str,
    string_values: list[str],
) -> set[str]:
    names: set[str] = set()
    module_pattern = _javascript_string_module_pattern(string_values, MJS_RAW_FS_MODULES)
    if not module_pattern:
        return names
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    namespace_pattern = re.compile(
        rf"\bimport\s+\*\s+as\s+({name_pattern})\s+from\s*"
        rf"(?:{module_pattern})\s*;",
    )
    default_pattern = re.compile(
        rf"\bimport\s+({name_pattern})\s+from\s*(?:{module_pattern})\s*;",
    )
    for match in namespace_pattern.finditer(code):
        names.add(match.group(1))
    for match in default_pattern.finditer(code):
        names.add(match.group(1))
    named_default_pattern = re.compile(
        rf"\bimport\s*\{{(?P<body>[^}}]+)\}}\s*from\s*"
        rf"(?:{module_pattern})\s*;",
    )
    for match in named_default_pattern.finditer(code):
        names.update(_javascript_default_binding_names(match.group("body")))
    return names


def _javascript_dynamic_fs_namespace_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_MODULES,
    )
    names = _javascript_dynamic_namespace_imports(code, module_pattern=module_pattern)
    names.update(
        _javascript_dynamic_default_namespace_imports(
            code,
            module_pattern=module_pattern,
        )
    )
    return names


def _javascript_require_fs_namespace_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_MODULES,
    )
    return _javascript_require_namespace_imports(code, module_pattern=module_pattern)


def _javascript_fs_promises_namespace_imports(
    code: str,
    string_values: list[str],
) -> set[str]:
    names: set[str] = set()
    raw_module_pattern = _javascript_string_module_pattern(
        string_values,
        MJS_RAW_FS_MODULES,
    )
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    if raw_module_pattern:
        import_pattern = re.compile(
            rf"\bimport\s+(?:{name_pattern}\s*,\s*)?"
            rf"\{{(?P<body>[^}}]+)\}}\s*from\s*(?:{raw_module_pattern})\s*;",
        )
        for match in import_pattern.finditer(code):
            for part in match.group("body").split(","):
                cleaned = part.strip()
                if not cleaned:
                    continue
                import_match = re.match(
                    rf"^(?P<imported>{name_pattern})"
                    rf"(?:\s+as\s+(?P<local>{name_pattern}))?$",
                    cleaned,
                )
                if not import_match or import_match.group("imported") != "promises":
                    continue
                names.add(import_match.group("local") or "promises")

    promise_module_pattern = _javascript_string_module_pattern(
        string_values,
        MJS_RAW_FS_PROMISE_MODULES,
    )
    if not promise_module_pattern:
        return names
    namespace_pattern = re.compile(
        rf"\bimport\s+\*\s+as\s+({name_pattern})\s+from\s*"
        rf"(?:{promise_module_pattern})\s*;",
    )
    default_pattern = re.compile(
        rf"\bimport\s+({name_pattern})\s+from\s*"
        rf"(?:{promise_module_pattern})\s*;",
    )
    for match in namespace_pattern.finditer(code):
        names.add(match.group(1))
    for match in default_pattern.finditer(code):
        names.add(match.group(1))
    return names


def _javascript_dynamic_fs_promises_namespace_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_PROMISE_MODULES,
    )
    names = _javascript_dynamic_namespace_imports(code, module_pattern=module_pattern)
    names.update(
        _javascript_dynamic_default_namespace_imports(
            code,
            module_pattern=module_pattern,
        )
    )
    return names


def _javascript_require_fs_promises_namespace_imports(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
) -> set[str]:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        MJS_RAW_FS_PROMISE_MODULES,
    )
    return _javascript_require_namespace_imports(code, module_pattern=module_pattern)


def _javascript_dynamic_namespace_imports(
    code: str,
    *,
    module_pattern: str,
) -> set[str]:
    if not module_pattern:
        return set()
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    pattern = re.compile(
        rf"\b(?:const|let|var)\s+({name_pattern})\s*=\s*"
        rf"(?:await\s+)?import\s*\(\s*(?:{module_pattern})\s*\)\s*;",
    )
    return {match.group(1) for match in pattern.finditer(code)}


def _javascript_dynamic_default_namespace_imports(
    code: str,
    *,
    module_pattern: str,
) -> set[str]:
    if not module_pattern:
        return set()
    pattern = re.compile(
        rf"\b(?:const|let|var)\s*\{{(?P<body>[^}}]+)\}}\s*=\s*"
        rf"(?:await\s+)?import\s*\(\s*(?:{module_pattern})\s*\)\s*;",
    )
    names: set[str] = set()
    for match in pattern.finditer(code):
        names.update(_javascript_default_binding_names(match.group("body")))
    return names


def _javascript_default_binding_names(body: str) -> set[str]:
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    names: set[str] = set()
    for part in body.split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        cleaned = _javascript_binding_without_default_initializer(cleaned)
        match = re.match(
            rf"^default(?:\s+as|\s*:)\s+(?P<local>{name_pattern})$",
            cleaned,
        )
        if match:
            names.add(match.group("local"))
    return names


def _javascript_binding_without_default_initializer(binding: str) -> str:
    return binding.split("=", 1)[0].strip()


def _javascript_require_namespace_imports(
    code: str,
    *,
    module_pattern: str,
) -> set[str]:
    if not module_pattern:
        return set()
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    pattern = re.compile(
        rf"\b(?:const|let|var)\s+({name_pattern})\s*=\s*"
        rf"require\s*\(\s*(?:{module_pattern})\s*\)\s*;",
    )
    return {match.group(1) for match in pattern.finditer(code)}


def _javascript_inline_module_function_call(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
    *,
    module_values: set[str],
    function_name: str,
) -> bool:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        module_values,
    )
    if not module_pattern:
        return False
    access_pattern = _javascript_property_access_pattern(
        function_name,
        string_values,
        constants=constants,
    )
    default_access_pattern = _javascript_property_access_pattern(
        "default",
        string_values,
        constants=constants,
    )
    call_pattern = rf"(?:{access_pattern}|{default_access_pattern}\s*{access_pattern})"
    return any(
        re.search(rf"{module_expression}\s*{call_pattern}\s*\(", code)
        for module_expression in _javascript_inline_module_expressions(module_pattern)
    )


def _javascript_inline_module_promises_function_call(
    code: str,
    string_values: list[str],
    constants: dict[str, str],
    *,
    module_values: set[str],
    function_name: str,
) -> bool:
    module_pattern = _javascript_string_or_const_pattern(
        string_values,
        constants,
        module_values,
    )
    if not module_pattern:
        return False
    promises_access_pattern = _javascript_property_access_pattern(
        "promises",
        string_values,
        constants=constants,
    )
    function_access_pattern = _javascript_property_access_pattern(
        function_name,
        string_values,
        constants=constants,
    )
    default_access_pattern = _javascript_property_access_pattern(
        "default",
        string_values,
        constants=constants,
    )
    promise_chain_pattern = rf"{promises_access_pattern}\s*{function_access_pattern}"
    call_pattern = (
        rf"(?:{promise_chain_pattern}|"
        rf"{default_access_pattern}\s*{promise_chain_pattern})"
    )
    return any(
        re.search(rf"{module_expression}\s*{call_pattern}\s*\(", code)
        for module_expression in _javascript_inline_module_expressions(module_pattern)
    )


def _javascript_inline_module_expressions(module_pattern: str) -> list[str]:
    return [
        rf"require\s*\(\s*(?:{module_pattern})\s*\)",
        rf"\(\s*await\s+import\s*\(\s*(?:{module_pattern})\s*\)\s*\)",
    ]


def _javascript_namespace_function_call(
    code: str,
    *,
    namespace: str,
    function_name: str,
    string_values: list[str],
    constants: dict[str, str],
) -> bool:
    access_pattern = _javascript_property_access_pattern(
        function_name,
        string_values,
        constants=constants,
    )
    default_access_pattern = _javascript_property_access_pattern(
        "default",
        string_values,
        constants=constants,
    )
    return bool(
        re.search(
            rf"\b{re.escape(namespace)}\s*"
            rf"(?:{access_pattern}|{default_access_pattern}\s*{access_pattern})"
            rf"\s*\(",
            code,
        )
    )


def _javascript_namespace_promises_function_call(
    code: str,
    *,
    namespace: str,
    function_name: str,
    string_values: list[str],
    constants: dict[str, str],
) -> bool:
    promises_access_pattern = _javascript_property_access_pattern(
        "promises",
        string_values,
        constants=constants,
    )
    function_access_pattern = _javascript_property_access_pattern(
        function_name,
        string_values,
        constants=constants,
    )
    default_access_pattern = _javascript_property_access_pattern(
        "default",
        string_values,
        constants=constants,
    )
    promise_chain_pattern = (
        rf"{promises_access_pattern}\s*{function_access_pattern}"
    )
    return bool(
        re.search(
            rf"\b{re.escape(namespace)}\s*"
            rf"(?:{promise_chain_pattern}|"
            rf"{default_access_pattern}\s*{promise_chain_pattern})"
            rf"\s*\(",
            code,
        )
    )


def _javascript_property_access_pattern(
    property_name: str,
    string_values: list[str],
    *,
    constants: dict[str, str],
) -> str:
    patterns = [rf"(?:\?\.|\.)\s*{re.escape(property_name)}"]
    bracket_pattern = _javascript_string_module_pattern(string_values, {property_name})
    if bracket_pattern:
        bracket_access = rf"\[\s*(?:{bracket_pattern})\s*\]"
        optional_bracket_access = rf"\?\.\s*\[\s*(?:{bracket_pattern})\s*\]"
        patterns.append(rf"(?:{bracket_access}|{optional_bracket_access})")
    constant_pattern = "|".join(
        re.escape(name)
        for name, value in constants.items()
        if value == property_name
    )
    if constant_pattern:
        bracket_access = rf"\[\s*(?:{constant_pattern})\s*\]"
        optional_bracket_access = rf"\?\.\s*\[\s*(?:{constant_pattern})\s*\]"
        patterns.append(rf"(?:{bracket_access}|{optional_bracket_access})")
    return rf"(?:{'|'.join(patterns)})"


def _javascript_string_or_const_pattern(
    string_values: list[str],
    constants: dict[str, str],
    values: set[str],
) -> str:
    patterns = [
        re.escape(f"__JS_STRING_{index}__")
        for index, value in enumerate(string_values)
        if value in values
    ]
    patterns.extend(
        re.escape(name)
        for name, value in constants.items()
        if value in values
    )
    return "|".join(patterns)


def _javascript_string_module_pattern(
    string_values: list[str],
    modules: set[str],
) -> str:
    return "|".join(
        re.escape(f"__JS_STRING_{index}__")
        for index, value in enumerate(string_values)
        if value in modules
    )


def _mjs_probe_output_arg_return_properties(
    code: str,
    string_values: list[str],
) -> set[str]:
    if "process.argv" not in code:
        return set()

    parse_args_body = _javascript_function_body(code, "parseArgs")
    if not parse_args_body:
        return set()

    out_markers = [
        re.escape(f"__JS_STRING_{index}__")
        for index, value in enumerate(string_values)
        if value == "--out"
    ]
    out_equals_markers = [
        re.escape(f"__JS_STRING_{index}__")
        for index, value in enumerate(string_values)
        if value == "--out="
    ]
    if not out_markers or not out_equals_markers:
        return set()

    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    exact_arg_pattern = re.compile(
        rf"^\s*(?:\b{name_pattern}\s*===\s*(?:{'|'.join(out_markers)})|"
        rf"(?:{'|'.join(out_markers)})\s*===\s*\b{name_pattern})\s*$"
    )
    prefixed_arg_pattern = re.compile(
        rf"^\s*\b{name_pattern}\.startsWith\(\s*"
        rf"(?:{'|'.join(out_equals_markers)})\s*\)\s*$"
    )
    exact_assignments: set[str] = set()
    prefixed_assignments: set[str] = set()
    for condition, body in _javascript_if_blocks(parse_args_body):
        if exact_arg_pattern.fullmatch(condition):
            exact_assignments.update(_javascript_argv_next_value_assignments(body))
        if prefixed_arg_pattern.fullmatch(condition):
            prefixed_assignments.update(
                _javascript_string_prefix_slice_assignments(
                    body,
                    prefix_markers=out_equals_markers,
                )
            )

    output_variables = exact_assignments & prefixed_assignments
    if not output_variables:
        return set()
    return _javascript_returned_object_properties_for_variables(
        parse_args_body,
        output_variables,
    )


def _javascript_argv_next_value_assignments(body: str) -> set[str]:
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    pattern = re.compile(
        rf"\b({name_pattern})\s*=\s*argv\s*\[\s*{name_pattern}\s*\+\s*1\s*\]"
    )
    return {match.group(1) for match in pattern.finditer(body)}


def _javascript_string_prefix_slice_assignments(
    body: str,
    *,
    prefix_markers: list[str],
) -> set[str]:
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    prefix_expression = "|".join(prefix_markers)
    pattern = re.compile(
        rf"\b({name_pattern})\s*=\s*{name_pattern}\.slice\(\s*"
        rf"(?:{prefix_expression})\.length\s*\)"
    )
    return {match.group(1) for match in pattern.finditer(body)}


def _javascript_returned_object_properties_for_variables(
    body: str,
    variables: set[str],
) -> set[str]:
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    properties: set[str] = set()
    for match in re.finditer(r"\breturn\s*\{(?P<body>[^}]+)\}\s*;", body):
        for part in match.group("body").split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            if ":" in cleaned:
                property_name, local_name = [
                    item.strip()
                    for item in cleaned.split(":", 1)
                ]
            else:
                property_name = cleaned
                local_name = cleaned
            property_match = re.match(rf"^({name_pattern})\b", property_name)
            local_match = re.match(rf"^({name_pattern})\b", local_name)
            if (
                property_match
                and local_match
                and local_match.group(1) in variables
            ):
                properties.add(property_match.group(1))
    return properties


def _javascript_parse_args_destructured_variables(
    code: str,
    *,
    returned_properties: set[str],
) -> set[str]:
    name_pattern = r"[A-Za-z_$][A-Za-z0-9_$]*"
    variables: set[str] = set()
    destructure_pattern = re.compile(
        r"\bconst\s*\{(?P<body>[^}]+)\}\s*=\s*parseArgs\s*\(\s*"
        r"process\.argv\.slice\s*\(\s*2\s*\)\s*\)\s*;"
    )
    for match in destructure_pattern.finditer(code):
        for part in match.group("body").split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            if ":" in cleaned:
                property_name, local_name = [
                    item.strip()
                    for item in cleaned.split(":", 1)
                ]
            else:
                property_name = cleaned
                local_name = cleaned
            property_match = re.match(rf"^({name_pattern})\b", property_name)
            if not property_match or property_match.group(1) not in returned_properties:
                continue
            name_match = re.match(rf"^({name_pattern})\b", local_name)
            if name_match:
                variables.add(name_match.group(1))
    return variables


def _javascript_function_body(code: str, function_name: str) -> str:
    match = re.search(
        rf"\bfunction\s+{re.escape(function_name)}\s*\([^)]*\)\s*\{{",
        code,
    )
    if not match:
        return ""
    body_start = match.end()
    depth = 1
    index = body_start
    while index < len(code):
        char = code[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return code[body_start:index]
        index += 1
    return ""


def _javascript_body_calls_process_exit_nonzero(body: str) -> bool:
    for match in re.finditer(r"\bprocess\.exit\s*\(\s*([0-9]+)\s*\)", body):
        if int(match.group(1)) > 0:
            return True
    return False


def _javascript_top_level_if_blocks(code: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    depth = 0
    index = 0
    while index < len(code):
        if depth == 0 and _javascript_word_at(code, index, "if"):
            parsed = _javascript_parse_if_block(code, index)
            if parsed is not None:
                condition, body, next_index = parsed
                blocks.append((condition, body))
                index = next_index
                continue
        char = code[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(depth - 1, 0)
        index += 1
    return blocks


def _javascript_if_blocks(code: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(code):
        if _javascript_word_at(code, index, "if"):
            parsed = _javascript_parse_if_block(code, index)
            if parsed is not None:
                condition, body, next_index = parsed
                blocks.append((condition, body))
                index = next_index
                continue
        index += 1
    return blocks


def _javascript_call_argument_lists(code: str, function_name: str) -> list[list[str]]:
    calls: list[list[str]] = []
    for match in re.finditer(rf"\b{re.escape(function_name)}\s*\(", code):
        open_index = code.find("(", match.start())
        if open_index < 0:
            continue
        close_index = _javascript_matching_delimiter(code, open_index, "(", ")")
        if close_index is None:
            continue
        calls.append(_javascript_top_level_comma_parts(code[open_index + 1:close_index]))
    return calls


def _javascript_top_level_comma_parts(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for index, char in enumerate(text):
        if char in pairs:
            depth += 1
        elif char in closing:
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _javascript_parse_if_block(code: str, index: int) -> tuple[str, str, int] | None:
    cursor = index + len("if")
    cursor = _javascript_skip_whitespace(code, cursor)
    if cursor >= len(code) or code[cursor] != "(":
        return None
    condition_end = _javascript_matching_delimiter(code, cursor, "(", ")")
    if condition_end is None:
        return None
    condition = code[cursor + 1:condition_end]
    cursor = _javascript_skip_whitespace(code, condition_end + 1)
    if cursor >= len(code) or code[cursor] != "{":
        return None
    body_end = _javascript_matching_delimiter(code, cursor, "{", "}")
    if body_end is None:
        return None
    return condition, code[cursor + 1:body_end], body_end + 1


def _javascript_matching_delimiter(
    code: str,
    start: int,
    open_char: str,
    close_char: str,
) -> int | None:
    depth = 1
    index = start + 1
    while index < len(code):
        char = code[index]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _javascript_skip_whitespace(code: str, index: int) -> int:
    while index < len(code) and code[index].isspace():
        index += 1
    return index


def _javascript_word_at(code: str, index: int, word: str) -> bool:
    end = index + len(word)
    if code[index:end] != word:
        return False
    before = code[index - 1] if index > 0 else ""
    after = code[end] if end < len(code) else ""
    identifier_chars = "_$"
    return (
        not before.isalnum()
        and before not in identifier_chars
        and not after.isalnum()
        and after not in identifier_chars
    )


def _javascript_resolve_string_expression(
    expression: str,
    *,
    constants: dict[str, str],
    string_values: list[str],
) -> str:
    marker_match = re.fullmatch(r"__JS_STRING_([0-9]+)__", expression)
    if marker_match:
        return string_values[int(marker_match.group(1))]
    return constants.get(expression, "")


def _javascript_code_with_string_markers(source: str) -> tuple[str, list[str]]:
    output: list[str] = []
    string_values: list[str] = []
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if char == "/" and next_char == "/":
            output.extend("  ")
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if char == "/" and next_char == "*":
            output.extend("  ")
            index += 2
            while index < len(source):
                if source[index] == "*" and index + 1 < len(source) and source[index + 1] == "/":
                    output.extend("  ")
                    index += 2
                    break
                output.append("\n" if source[index] in "\r\n" else " ")
                index += 1
            continue
        if char == "`":
            output.append(" ")
            index += 1
            escaped = False
            while index < len(source):
                current = source[index]
                output.append("\n" if current in "\r\n" else " ")
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == "`":
                    index += 1
                    break
                index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            value: list[str] = []
            index += 1
            escaped = False
            while index < len(source):
                current = source[index]
                if escaped:
                    value.extend(["\\", current])
                    escaped = False
                    index += 1
                    continue
                if current == "\\":
                    escaped = True
                    index += 1
                    continue
                if current == quote:
                    index += 1
                    break
                value.append(current)
                index += 1
            marker = f"__JS_STRING_{len(string_values)}__"
            string_values.append("".join(value))
            output.append(marker)
            continue
        output.append(char)
        index += 1
    return "".join(output), string_values


def _workflow_production_override_env_is_manual_only(workflow_text: str) -> bool:
    values = [
        value
        for block in _workflow_env_blocks(workflow_text)
        for value in _workflow_mapping_direct_scalar_values(
            block,
            PRODUCTION_OVERRIDE_ENV,
        )
    ]
    return bool(values) and all(value == PRODUCTION_OVERRIDE_ENV_VALUE for value in values)


def _workflow_production_override_flag_steps_bind_env(workflow_text: str) -> bool:
    flag_blocks = [
        block
        for block in _workflow_step_blocks(workflow_text)
        if _workflow_step_has_executed_production_override_flag(block)
    ]
    return bool(flag_blocks) and all(
        _workflow_step_binds_production_override_env(block) for block in flag_blocks
    )


def _workflow_production_override_flag_steps_invoke_registered_probe(
    workflow_text: str,
    probe_paths: list[str],
) -> bool:
    flag_blocks = [
        block
        for block in _workflow_step_blocks(workflow_text)
        if _workflow_step_has_executed_production_override_flag(block)
    ]
    return bool(probe_paths) and bool(flag_blocks) and all(
        any(_workflow_run_block_invokes_probe(block, probe_path) for probe_path in probe_paths)
        for block in flag_blocks
    )


def _workflow_production_override_flag_steps_pass_args_to_probe(
    workflow_text: str,
    probe_paths: list[str],
) -> bool:
    flag_blocks = [
        block
        for block in _workflow_step_blocks(workflow_text)
        if _workflow_step_has_executed_production_override_flag(block)
    ]
    return bool(probe_paths) and bool(flag_blocks) and all(
        any(
            _workflow_probe_command_passes_production_override_args(block, probe_path)
            for probe_path in probe_paths
        )
        for block in flag_blocks
    )


def _workflow_production_override_registered_probe_steps_pass_args(
    workflow_text: str,
    probe_paths: list[str],
) -> bool:
    step_blocks = _workflow_step_blocks(workflow_text)
    return all(
        any(
            _workflow_probe_command_passes_production_override_args(block, probe_path)
            for block in step_blocks
        )
        for probe_path in probe_paths
    )


def _workflow_probe_command_passes_production_override_args(
    block: str,
    probe_path: str,
) -> bool:
    production_append_seen = False
    heredoc_delimiter: str | None = None
    normalized_probe_path = probe_path.replace("\\", "/")
    suffix = PurePosixPath(normalized_probe_path).suffix
    path_tokens = _workflow_probe_path_tokens(normalized_probe_path)
    for raw_line in _workflow_run_command_text(block).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if heredoc_delimiter is not None:
            if line == heredoc_delimiter:
                heredoc_delimiter = None
            continue
        heredoc_delimiter = _workflow_shell_heredoc_delimiter(line)
        if line == PRODUCTION_OVERRIDE_APPEND_LINE:
            production_append_seen = True
            continue
        if production_append_seen and _workflow_shell_resets_args_array(line):
            return False
        arguments = _workflow_command_arguments(line)
        if not _workflow_command_arguments_invoke_probe(
            arguments,
            suffix=suffix,
            path_tokens=path_tokens,
        ):
            continue
        return production_append_seen and PRODUCTION_OVERRIDE_ARGS_EXPANSION in arguments[2:]
    return False


def _workflow_shell_resets_args_array(line: str) -> bool:
    if re.match(r"^args(?:=|\[)", line):
        return True
    arguments = _workflow_command_arguments(line)
    if not arguments:
        return False
    if arguments[0] == "unset":
        return any(_workflow_shell_argument_targets_args_array(argument) for argument in arguments[1:])
    if arguments[0] in {"declare", "typeset", "local"}:
        return any(
            _workflow_shell_argument_targets_args_array(argument)
            for argument in arguments[1:]
            if not argument.startswith("-")
        )
    if arguments[0] in {"read", "readarray", "mapfile"}:
        return any(
            _workflow_shell_argument_targets_args_array(argument)
            for argument in arguments[1:]
            if not argument.startswith("-") and not argument.startswith("<")
        )
    return False


def _workflow_shell_argument_targets_args_array(argument: str) -> bool:
    target = argument.split("=", 1)[0]
    return target == "args" or target.startswith("args[")


def _workflow_step_has_executed_production_override_flag(block: str) -> bool:
    heredoc_delimiter: str | None = None
    for raw_line in _workflow_run_command_text(block).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if heredoc_delimiter is not None:
            if line == heredoc_delimiter:
                heredoc_delimiter = None
            continue
        heredoc_delimiter = _workflow_shell_heredoc_delimiter(line)
        if PRODUCTION_OVERRIDE_FLAG in line:
            return True
    return False


def _workflow_step_binds_production_override_env(block: str) -> bool:
    values = _workflow_mapping_direct_scalar_values(
        _workflow_mapping_block(block, "env"),
        PRODUCTION_OVERRIDE_ENV,
    )
    return values == [PRODUCTION_OVERRIDE_ENV_VALUE]


def _workflow_shell_heredoc_delimiter(line: str) -> str | None:
    match = re.search(r"(?<!<)<<-?\s*(?!<)(\S+)", line)
    if not match:
        return None
    delimiter = match.group(1).split(";", 1)[0].strip()
    if len(delimiter) >= 2 and delimiter[0] == delimiter[-1] and delimiter[0] in {"'", '"'}:
        delimiter = delimiter[1:-1]
    return delimiter or None



def _normalize_workflow_if_expression(expression: str) -> str:
    normalized = "".join(expression.split())
    if normalized.startswith("${{") and normalized.endswith("}}"):
        normalized = normalized[3:-2]
    return normalized


def _workflow_has_job_if_gate(workflow_text: str, token: str) -> bool:
    return any(
        _workflow_job_block_has_gate(job_block, token)
        for _, job_block in _workflow_job_blocks(workflow_text)
    )


def _workflow_job_if_text(job_block: str) -> str:
    lines = job_block.splitlines()
    if_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^\s{4}if:\s*", line)
        ),
        None,
    )
    if if_index is None:
        return ""

    first_line = lines[if_index]
    parts = first_line.split(":", 1)
    expression = parts[1].strip() if len(parts) == 2 else ""
    if expression and expression not in {">", ">-", "|", "|-"}:
        return expression

    block_lines: list[str] = []
    for line in lines[if_index + 1:]:
        if line.startswith("    ") and not line.startswith("      "):
            break
        block_lines.append(line.strip())
    return "\n".join(block_lines)


def _workflow_top_level_block(workflow_text: str, key: str) -> list[str]:
    lines = workflow_text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.startswith(f"{key}:")),
        None,
    )
    if start is None:
        return []
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" "):
            end = index
            break
    return lines[start:end]


def _workflow_top_level_key_count(workflow_text: str, key: str) -> int:
    return len(
        re.findall(
            rf"(?m)^{re.escape(key)}:(?:\s|$)",
            workflow_text,
        )
    )


def _workflow_dispatch_input_block(workflow_text: str, input_name: str) -> list[str]:
    event_block = _workflow_event_block(workflow_text, "workflow_dispatch")
    if not event_block:
        return []
    start = next(
        (index for index, line in enumerate(event_block) if line == f"      {input_name}:"),
        None,
    )
    if start is None:
        return []
    end = len(event_block)
    for index in range(start + 1, len(event_block)):
        line = event_block[index]
        if line.startswith("      ") and not line.startswith("        "):
            end = index
            break
        if line.startswith("  ") and not line.startswith("    "):
            end = index
            break
    return event_block[start:end]


def _workflow_dispatch_input_names(workflow_text: str) -> list[str]:
    event_block = _workflow_event_block(workflow_text, "workflow_dispatch")
    if not event_block:
        return []
    names: list[str] = []
    for line in event_block[1:]:
        if line.startswith("  ") and not line.startswith("    "):
            break
        if match := re.match(r"^      ([A-Za-z0-9_-]+):\s*(?:#.*)?$", line):
            names.append(match.group(1))
    return names


def _workflow_dispatch_duplicate_input_names(workflow_text: str) -> list[str]:
    counts: dict[str, int] = {}
    for name in _workflow_dispatch_input_names(workflow_text):
        counts[name] = counts.get(name, 0) + 1
    return [name for name, count in counts.items() if count > 1]


def _workflow_dispatch_input_duplicate_fields(
    input_block: list[str],
    fields: list[str],
) -> list[str]:
    counts: dict[str, int] = {}
    allowed = set(fields)
    for field in _workflow_dispatch_input_field_names(input_block):
        if field in allowed:
            counts[field] = counts.get(field, 0) + 1
    return [field for field in fields if counts.get(field, 0) > 1]


def _workflow_dispatch_input_field_names(input_block: list[str]) -> list[str]:
    fields: list[str] = []
    for line in input_block[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if match := re.match(r"^([A-Za-z-]+):\s*", stripped):
            fields.append(match.group(1))
    return fields


def _workflow_dispatch_input_is_boolean_default_false(input_block: list[str]) -> bool:
    entries: dict[str, str] = {}
    for line in input_block[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z-]+):\s*(.+?)\s*$", stripped)
        if match:
            entries[match.group(1)] = match.group(2).strip("\"'")
    return entries.get("type") == "boolean" and entries.get("default") == "false"


def _workflow_event_block(workflow_text: str, event_name: str) -> list[str]:
    lines = _workflow_top_level_block(workflow_text, "on")
    if not lines:
        return []
    start = next(
        (index for index, line in enumerate(lines) if line == f"  {event_name}:"),
        None,
    )
    if start is None:
        return []
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    "):
            end = index
            break
        if line and not line.startswith(" "):
            end = index
            break
    return lines[start:end]


def _workflow_event_names(workflow_text: str) -> list[str]:
    lines = _workflow_top_level_block(workflow_text, "on")
    if not lines or lines[0] != "on:":
        return []
    names: list[str] = []
    for line in lines[1:]:
        if line and not line.startswith(" "):
            break
        if match := re.match(r"^  ([A-Za-z0-9_-]+):(?:\s|$)", line):
            names.append(match.group(1))
    return names


def _workflow_duplicate_event_names(workflow_text: str) -> list[str]:
    counts: dict[str, int] = {}
    for name in _workflow_event_names(workflow_text):
        counts[name] = counts.get(name, 0) + 1
    return [name for name, count in counts.items() if count > 1]


def _workflow_event_duplicate_direct_fields(
    workflow_text: str,
    event_name: str,
    fields: list[str],
) -> list[str]:
    block = _workflow_event_block(workflow_text, event_name)
    if not block:
        return []
    counts: dict[str, int] = {}
    allowed = set(fields)
    for field in _workflow_event_direct_field_names(block):
        if field in allowed:
            counts[field] = counts.get(field, 0) + 1
    return [field for field in fields if counts.get(field, 0) > 1]


def _workflow_event_direct_field_names(event_block: list[str]) -> list[str]:
    fields: list[str] = []
    for line in event_block[1:]:
        if line.startswith("  ") and not line.startswith("    "):
            break
        if match := re.match(r"^    ([A-Za-z0-9_-]+):(?:\s|$)", line):
            fields.append(match.group(1))
    return fields


def _workflow_event_has_direct_field(
    workflow_text: str,
    event_name: str,
    field: str,
) -> bool:
    return field in _workflow_event_direct_field_names(
        _workflow_event_block(workflow_text, event_name)
    )


def _workflow_event_filter_values(
    workflow_text: str,
    event_name: str,
    field: str,
) -> set[str]:
    block = _workflow_event_block(workflow_text, event_name)
    if not block:
        return set()
    values: set[str] = set()
    for index, line in enumerate(block[1:], start=1):
        match = re.match(rf"^    {re.escape(field)}:\s*(.*?)\s*(?:#.*)?$", line)
        if not match:
            continue
        raw_value = match.group(1).strip()
        if raw_value:
            values.update(_workflow_inline_filter_values(raw_value))
            return values
        for child_line in block[index + 1:]:
            if child_line.startswith("    ") and not child_line.startswith("      "):
                break
            child_match = re.match(r"^\s*-\s*(.+?)\s*$", child_line)
            if child_match:
                values.add(child_match.group(1).strip("\"'"))
        return values
    return values


def _workflow_inline_filter_values(raw_value: str) -> set[str]:
    value = raw_value.strip().strip("\"'")
    if value.startswith("[") and value.endswith("]"):
        return {
            item.strip().strip("\"'")
            for item in value[1:-1].split(",")
            if item.strip()
        }
    return {value} if value else set()


def _workflow_event_paths(workflow_text: str, event_name: str) -> set[str]:
    block = _workflow_event_block(workflow_text, event_name)
    if not block:
        return set()
    in_paths = False
    paths: set[str] = set()
    for line in block[1:]:
        if line == "    paths:":
            in_paths = True
            continue
        if in_paths and line.startswith("    ") and not line.startswith("      "):
            break
        if in_paths:
            match = re.match(r"^\s*-\s*(.+?)\s*$", line)
            if match:
                paths.add(match.group(1).strip("\"'"))
    return paths


def _workflow_job_blocks(workflow_text: str) -> list[tuple[str, str]]:
    lines = workflow_text.splitlines()
    jobs_line_index = next(
        (index for index, line in enumerate(lines) if line == "jobs:"),
        None,
    )
    if jobs_line_index is None:
        return []
    job_starts: list[tuple[int, str]] = []
    for index in range(jobs_line_index + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" "):
            break
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            job_starts.append((index, match.group(1)))
    blocks: list[tuple[str, str]] = []
    for position, (start, job_name) in enumerate(job_starts):
        end = job_starts[position + 1][0] if position + 1 < len(job_starts) else len(lines)
        blocks.append((job_name, "\n".join(lines[start:end])))
    return blocks


def _workflow_duplicate_job_names(workflow_text: str) -> list[str]:
    counts: dict[str, int] = {}
    for job_name, _ in _workflow_job_blocks(workflow_text):
        counts[job_name] = counts.get(job_name, 0) + 1
    return [job_name for job_name, count in counts.items() if count > 1]


def load_registry(path: Path) -> dict[str, Any]:
    data = load_strict_json_file(path)
    if not isinstance(data, dict):
        raise ValueError("registry root must be a JSON object")
    return data


def _registry_fingerprint(registry: dict[str, Any]) -> str:
    contract = {
        "registry": registry.get("registry"),
        "version": registry.get("version"),
        "requirements": registry.get("requirements"),
    }
    encoded = json.dumps(
        contract,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for error in errors:
        code = _error_code(error)
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    return normalize_registry_error_code(error)


def normalize_registry_error_code(error: str) -> str:
    if error == "registry validation output path must not overwrite registry":
        return "registry_output_path_overwrites_registry"
    if error == REGISTRY_OUTPUT_PATH_SYMLINK_ERROR:
        return "registry_output_path_symlink"
    if error == REGISTRY_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "registry_output_path_parent_symlink"
    if error == REGISTRY_OUTPUT_PATH_DIRECTORY_ERROR:
        return "registry_output_path_directory"
    if (
        "No such file or directory" in error
        or "cannot find the file" in error.casefold()
        or "non-finite JSON number is not allowed" in error
        or "duplicate JSON object key(s)" in error
    ):
        return "registry_load_failed"
    if error == "registry root must be a JSON object":
        return "registry_root_not_object"
    if error.startswith("registry: `registry` must be "):
        return "registry_identity_mismatch"
    if error == "registry: `version` must be an integer >= 1":
        return "registry_version_invalid"
    if error == "registry: `requirements` must be a non-empty list":
        return "registry_requirements_empty"
    if error.startswith("registry: unknown field(s):"):
        return "registry_unknown_field"
    if error.endswith(": requirement must be an object"):
        return "registry_requirement_not_object"
    if ".freshness: unknown field(s):" in error:
        return "registry_freshness_unknown_field"
    if ".payload_checks[" in error and ": unknown field(s):" in error:
        return "registry_payload_check_unknown_field"
    if ".freshness:" in error and "dot-path syntax" in error:
        return "registry_freshness_path_invalid"
    if ".freshness: max_age_hours must be a positive integer" in error:
        return "registry_freshness_max_age_invalid"
    if ".payload_checks[" in error and "dot-path syntax" in error:
        return "registry_payload_check_path_invalid"
    if (
        ".payload_checks[" in error
        and ".when:" in error
        and "must be a non-null JSON scalar" in error
    ):
        return "registry_payload_check_when_value_invalid"
    if ".payload_checks[" in error and (
        "min must be a JSON number" in error
        or "sorted_equals must be a list" in error
        or "must be a non-null JSON scalar" in error
    ):
        return "registry_payload_check_value_invalid"
    if ".payload_checks[" in error and ".when:" in error and "equals or not_equals" in error:
        return "registry_payload_check_when_operation_invalid"
    if ": unknown field(s):" in error and "requirements[" in error:
        return "registry_requirement_unknown_field"
    if error.endswith(": `id` must be lowercase kebab-case"):
        return "registry_requirement_id_invalid"
    if error.endswith(": duplicate requirement id"):
        return "registry_requirement_id_duplicate"
    if ": unsupported layer " in error:
        return "registry_layer_unsupported"
    if ": `artifact` must be a file name, not a path" in error:
        return "registry_artifact_path_invalid"
    if ": `artifact` must be a JSON file" in error:
        return "registry_artifact_not_json"
    if "safe lowercase kebab-case JSON file name" in error:
        return "registry_artifact_name_invalid"
    if ": duplicate artifact name " in error:
        return "registry_artifact_name_duplicate"
    if ": invalid schema_version " in error:
        return "registry_schema_version_invalid"
    if ": unsupported payload_schema_field " in error:
        return "registry_payload_schema_field_unsupported"
    if ": path must be a non-empty string" in error:
        return "repo_path_missing"
    if ": path must be repo-relative:" in error:
        return "repo_path_not_relative"
    if ": path escapes repo root:" in error:
        return "repo_path_escapes_root"
    if ": file does not exist:" in error:
        return "repo_file_missing"
    if ": path must be a file:" in error:
        return "repo_path_not_file"
    if ": path must not contain symlinks:" in error:
        return "repo_path_symlink"
    if ": file is not UTF-8:" in error:
        return "repo_file_not_utf8"
    if ": missing token " in error:
        return "source_token_missing"
    if ".workflow: workflow must be a YAML file" in error:
        return "workflow_file_not_yaml"
    if ".workflow: workflow must live directly under .github/workflows/" in error:
        return "workflow_file_location_invalid"
    if "pull_request_target is not allowed" in error:
        return "workflow_pull_request_target_forbidden"
    if "duplicate top-level" in error:
        return "workflow_top_level_duplicate"
    if "duplicate workflow event name(s)" in error:
        return "workflow_event_duplicate"
    if "duplicate workflow job id(s)" in error:
        return "workflow_job_name_duplicate"
    if "duplicate job-level field(s)" in error:
        return "workflow_job_control_duplicate"
    if "validate_runtime_evidence_artifact.py" in error:
        return "workflow_validation_binding_invalid"
    if "unregistered upload-artifact step" in error:
        return "workflow_unregistered_upload_step"
    if "upload-artifact" in error or "if-no-files-found: error" in error or "retention-days" in error:
        return "workflow_upload_binding_invalid"
    if "actions/checkout" in error or "persist-credentials false" in error or "checkout before" in error:
        return "workflow_checkout_invalid"
    if "timeout-minutes" in error:
        return "workflow_timeout_invalid"
    if "continue-on-error" in error:
        return "workflow_continue_on_error_forbidden"
    if "shell xtrace" in error:
        return "workflow_shell_xtrace_forbidden"
    if "permissions" in error:
        return "workflow_permissions_invalid"
    if "concurrency" in error or "cancel-in-progress" in error:
        return "workflow_concurrency_invalid"
    if "live evidence job must declare `environment:" in error:
        return "workflow_environment_invalid"
    if "secret references" in error or "secret-bearing evidence job" in error:
        return "workflow_secret_scope_invalid"
    if "allow_production" in error or "ALLOW_PRODUCTION_INPUT" in error or "--allow-production" in error:
        return "workflow_production_override_invalid"
    if "dispatch_or_schedule_gate_tokens contains unsupported gate token" in error:
        return "registry_gate_token_unsupported"
    if "dispatch_or_schedule_gate_tokens must include exactly one" in error:
        return "registry_gate_token_pair_invalid"
    if "duplicate workflow_dispatch input" in error:
        return "workflow_dispatch_input_duplicate"
    if (
        "live_guard_tokens entries" in error
        or "must be an argparse store_true CLI flag" in error
        or "fail-closed process.argv.includes" in error
        or "MJS probe fail() must call process.exit" in error
    ):
        return "registry_live_guard_token_invalid"
    if (
        "workflow_dispatch input" in error
        or "workflow_dispatch runs must be guarded" in error
        or "scheduled runs must be guarded" in error
        or "guard token" in error
        or " live evidence job must be guarded " in error
    ):
        return "workflow_gate_binding_invalid"
    if "live_env_flags entries" in error:
        return "registry_live_env_flag_invalid"
    if "workflow env maps must not duplicate" in error:
        return "workflow_env_flag_duplicate"
    if ": artifact token must include requirement id " in error:
        return "registry_artifact_token_identity_invalid"
    if ": duplicate artifact token " in error:
        return "registry_artifact_token_duplicate"
    if (
        "registered probe invocation" in error
        or "registered Python probe invocation" in error
        or "workflow must set `" in error
        or "missing workflow step invoking" in error
    ):
        return "workflow_probe_binding_invalid"
    if "must import emit_json_payload from runtime_evidence_output" in error:
        return "registry_probe_output_helper_invalid"
    if "must call emit_json_payload with an output path argument" in error:
        return "registry_probe_output_helper_invalid"
    if "must define `--out` as an argparse CLI flag" in error:
        return "registry_probe_output_argument_invalid"
    if "registered MJS probe must parse `--out` from process.argv" in error:
        return "registry_probe_output_argument_invalid"
    if "must forward parsed `--out` path to WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON" in error:
        return "registry_probe_output_argument_invalid"
    if "must not write evidence files outside runtime_evidence_output" in error:
        return "registry_probe_raw_file_write_forbidden"
    if "must not write evidence files outside runtime-evidence-output.mjs" in error:
        return "registry_probe_raw_file_write_forbidden"
    if "runtime evidence output helper" in error and "atomic temp-file writes" in error:
        return "registry_output_helper_atomic_invalid"
    if "runtime evidence output helper test" in error:
        return "workflow_output_helper_contract_invalid"
    if ".probe: probe must be a script file" in error:
        return "registry_probe_suffix_invalid"
    if ": contract_tests entries must be Python " in error:
        return "registry_contract_test_path_invalid"
    if "contract test" in error or "registered contract test" in error or "`needs: contract`" in error:
        return "workflow_contract_test_invalid"
    if "unsupported workflow uses action" in error:
        return "workflow_action_not_allowed"
    if "40-character commit SHA" in error:
        return "workflow_action_ref_unpinned"
    if "missing paths filter" in error:
        return "workflow_path_filter_missing"
    if "duplicate event filter field(s)" in error:
        return "workflow_path_filter_duplicate"
    if "unsupported event filter field(s)" in error:
        return "workflow_path_filter_invalid"
    if "branches filter must include 'main'" in error:
        return "workflow_path_filter_invalid"
    if "`payload_checks` must be a non-empty list" in error:
        return "registry_payload_checks_missing"
    if "duplicate payload check" in error:
        return "registry_payload_check_duplicate"
    if "must not contain duplicate values" in error:
        return "registry_string_list_duplicate"
    if "`contract_tests` must not contain duplicate normalized paths" in error:
        return "registry_contract_test_duplicate"
    if "case-insensitive duplicate values" in error:
        return "registry_forbidden_payload_token_duplicate"
    if "forbidden_payload_regexes pattern must compile" in error:
        return "registry_forbidden_payload_regex_invalid"
    if "duplicate forbidden_payload_regexes pattern" in error:
        return "registry_forbidden_payload_regex_duplicate"
    if "payload_checks" in error and ("raw_content_included == false" in error or "identifier_strategy" in error):
        return "registry_payload_privacy_check_missing"
    if ".payload_checks[" in error:
        return "registry_payload_check_invalid"
    if "`freshness` must be an object" in error:
        return "registry_freshness_missing"
    if ".freshness:" in error:
        return "registry_freshness_invalid"
    return "validation_error"


def validate_registry(
    data: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    registry_path: Path = DEFAULT_REGISTRY,
) -> RegistryResult:
    validator = RegistryValidator(repo_root=repo_root, registry_path=registry_path)
    return validator.validate(data)


def format_summary(result: RegistryResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    lines = [
        f"{REGISTRY_NAME}: {status}",
        f"validation_schema: {result.validation_schema_version}",
        f"registry: {result.registry_path}",
        f"registry_version: {result.registry_version if result.registry_version is not None else '-'}",
        f"registry_fingerprint_sha256: {result.registry_fingerprint_sha256}",
        f"requirements: {result.requirement_count}",
        f"checks passed: {result.passed_checks}",
    ]
    if result.errors:
        lines.append("")
        lines.append(f"Error codes: {', '.join(_error_codes(result.errors)) or '-'}")
        lines.append(
            f"Error code counts: {_format_error_code_counts(_error_code_counts(result.errors))}"
        )
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in result.errors)
    return "\n".join(lines)


def _format_error_code_counts(error_code_counts: dict[str, int]) -> str:
    if not error_code_counts:
        return "-"
    return ", ".join(
        f"{error_code}={count}" for error_code, count in error_code_counts.items()
    )


def validate_output_path(*, registry_path: Path, out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.resolve() == registry_path.resolve():
        raise ValueError("registry validation output path must not overwrite registry")
    if out_path.is_symlink():
        raise ValueError(REGISTRY_OUTPUT_PATH_SYMLINK_ERROR)
    if _path_has_symlink_parent(out_path):
        raise ValueError(REGISTRY_OUTPUT_PATH_PARENT_SYMLINK_ERROR)
    if out_path.exists() and out_path.is_dir():
        raise ValueError(REGISTRY_OUTPUT_PATH_DIRECTORY_ERROR)


def _path_has_symlink_parent(path: Path) -> bool:
    return any(parent.is_symlink() for parent in path.parents)


def write_cli_output(rendered: str, out_path: Path | None) -> None:
    if out_path is None:
        print(rendered)
        return
    safe_write_report_text(out_path, rendered + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Validate {REGISTRY_NAME}.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation output.")
    parser.add_argument("--out", type=Path, default=None, help="Write output directly to a UTF-8 file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        validate_output_path(registry_path=args.registry, out_path=args.out)
    except Exception as exc:
        if args.json:
            error_code = _error_code(str(exc))
            print(
                json.dumps(
                    {
                        "validation_schema_version": REGISTRY_VALIDATION_SCHEMA_VERSION,
                        "ok": False,
                        "errors": [str(exc)],
                        "error_codes": [error_code],
                        "error_code_counts": {error_code: 1},
                    },
                    indent=2,
                    sort_keys=True,
                ),
                file=sys.stdout,
            )
        else:
            print(f"{REGISTRY_NAME}: FAIL\n- {exc}", file=sys.stderr)
        return 1

    try:
        data = load_registry(args.registry)
    except Exception as exc:
        if args.json:
            error_code = _error_code(str(exc))
            write_cli_output(
                json.dumps(
                    {
                        "validation_schema_version": REGISTRY_VALIDATION_SCHEMA_VERSION,
                        "ok": False,
                        "errors": [str(exc)],
                        "error_codes": [error_code],
                        "error_code_counts": {error_code: 1},
                    },
                    indent=2,
                    sort_keys=True,
                ),
                args.out,
            )
        else:
            print(f"{REGISTRY_NAME}: FAIL\n- {exc}", file=sys.stderr)
        return 1

    result = validate_registry(data, repo_root=args.repo_root, registry_path=args.registry)
    if args.json:
        write_cli_output(json.dumps(result.to_dict(), indent=2, sort_keys=True), args.out)
    else:
        write_cli_output(format_summary(result), args.out)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
