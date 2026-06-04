#!/usr/bin/env python3
"""Validate a produced Wiii runtime evidence JSON artifact.

The registry validator proves workflows are wired correctly. This script checks
the JSON file those workflows produce, using the same registry entry as the
source of truth for schema, privacy, and minimal success evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from strict_json import loads_strict_json  # noqa: E402
from validate_runtime_evidence_registry import (  # noqa: E402
    DEFAULT_REGISTRY,
    load_registry,
    validate_registry as validate_registry_contract,
)


ARTIFACT_VALIDATION_SCHEMA_VERSION = "wiii.runtime_evidence_artifact_validation.v1"


@dataclass(frozen=True)
class ArtifactResult:
    validation_schema_version: str
    requirement_id: str
    artifact_path: str
    schema_version: str
    passed_checks: int
    generated_at: str | None
    max_age_hours: int | None
    age_hours: float | None
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


class ArtifactValidator:
    def __init__(
        self,
        *,
        requirement: dict[str, Any],
        artifact_path: Path,
        as_of: datetime | None = None,
        enforce_freshness: bool = True,
    ) -> None:
        self.requirement = requirement
        self.artifact_path = artifact_path
        self.as_of = _normalize_as_of(as_of)
        self.enforce_freshness = enforce_freshness
        self.errors: list[str] = []
        self.passed_checks = 0
        self.generated_at: str | None = None
        self.max_age_hours: int | None = None
        self.age_hours: float | None = None

    def pass_check(self) -> None:
        self.passed_checks += 1

    def error(self, message: str) -> None:
        self.errors.append(message)

    def validate_file(self) -> ArtifactResult:
        requirement_id = str(self.requirement.get("id") or "")
        schema_version = str(self.requirement.get("schema_version") or "")
        if self.artifact_path.is_symlink():
            self.error(f"artifact: path must not be a symlink: {self.artifact_path}")
            payload = None
        else:
            try:
                payload = loads_strict_json(
                    self.artifact_path.read_text(encoding="utf-8")
                )
            except Exception as exc:  # noqa: BLE001
                self.error(f"artifact: could not read JSON artifact: {exc}")
                payload = None
        if not isinstance(payload, dict):
            self.error("artifact: root must be a JSON object")
            payload = {}
        else:
            self.pass_check()

        self.validate_payload(payload)
        return ArtifactResult(
            validation_schema_version=ARTIFACT_VALIDATION_SCHEMA_VERSION,
            requirement_id=requirement_id,
            artifact_path=str(self.artifact_path),
            schema_version=schema_version,
            passed_checks=self.passed_checks,
            generated_at=self.generated_at,
            max_age_hours=self.max_age_hours,
            age_hours=self.age_hours,
            errors=self.errors,
        )

    def validate_payload(self, payload: dict[str, Any]) -> None:
        self.requirement_payload = payload
        schema_field = str(self.requirement.get("payload_schema_field") or "schema_version")
        expected_schema = str(self.requirement.get("schema_version") or "")
        actual_schema = _get_path(payload, schema_field)
        if actual_schema != expected_schema:
            self.error(
                f"artifact: {schema_field} must be {expected_schema!r}, got {actual_schema!r}"
            )
        else:
            self.pass_check()

        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        rendered_casefold = rendered.casefold()
        for token in _string_list(self.requirement.get("forbidden_payload_tokens")):
            if token.casefold() in rendered_casefold:
                self.error(f"artifact: forbidden token leaked: {token!r}")
            else:
                self.pass_check()
        for pattern in _string_list(self.requirement.get("forbidden_payload_regexes")):
            if re.search(pattern, rendered, re.IGNORECASE):
                self.error(f"artifact: forbidden regex matched: {pattern!r}")
            else:
                self.pass_check()

        if self.enforce_freshness:
            self.validate_freshness(payload)

        checks = self.requirement.get("payload_checks")
        if not isinstance(checks, list) or not checks:
            self.error("artifact: registry entry must define non-empty payload_checks")
            return
        self.pass_check()
        for index, check in enumerate(checks):
            self.validate_check(check, context=f"payload_checks[{index}]")

    def validate_check(self, check: Any, *, context: str) -> None:
        if not isinstance(check, dict):
            self.error(f"{context}: check must be an object")
            return
        when = check.get("when")
        if isinstance(when, dict) and not _condition_matches(self.requirement_payload, when):
            self.pass_check()
            return
        raw_path = check.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            self.error(f"{context}: `path` must be a non-empty string")
            return

        values = _get_path_values(self.requirement_payload, raw_path)
        if _path_has_wildcard(raw_path) and not values:
            self.error(f"{context}: {raw_path} matched no values")
            return
        if "equals" in check:
            expected = check.get("equals")
            mismatches = [value for value in values if value != expected]
            if mismatches:
                self.error(
                    f"{context}: {raw_path} must equal {expected!r}, "
                    f"got {_preview_values(mismatches)!r}"
                )
            else:
                self.pass_check()
            return
        if "min" in check:
            expected_min = check.get("min")
            numeric_min = _as_float(expected_min)
            if numeric_min is None:
                self.error(f"{context}: min value must be numeric, got {expected_min!r}")
                return
            bad_values: list[Any] = []
            for value in values:
                numeric_value = _as_float(value)
                if numeric_value is None or numeric_value < numeric_min:
                    bad_values.append(value)
            if bad_values:
                self.error(
                    f"{context}: {raw_path} must be >= {expected_min!r}, "
                    f"got {_preview_values(bad_values)!r}"
                )
                return
            self.pass_check()
            return
        if "sorted_equals" in check:
            expected = check.get("sorted_equals")
            if not isinstance(expected, list):
                self.error(f"{context}: sorted_equals must be a list")
                return
            bad_values = [
                value
                for value in values
                if not isinstance(value, list) or not _json_multiset_matches(value, expected)
            ]
            if bad_values:
                self.error(f"{context}: {raw_path} sorted value mismatch: {_preview_values(bad_values)!r}")
                return
            self.pass_check()
            return
        if "length_equals_path" in check:
            expected_path = check.get("length_equals_path")
            if not isinstance(expected_path, str) or not expected_path:
                self.error(f"{context}: length_equals_path must be a non-empty string")
                return
            value = _get_path(self.requirement_payload, raw_path)
            expected_value = _get_path(self.requirement_payload, expected_path)
            if not isinstance(value, list):
                self.error(f"{context}: {raw_path} must be a list for length check")
                return
            expected_length = _as_integer(expected_value)
            if expected_length is None:
                self.error(
                    f"{context}: {expected_path} must be an integer length, "
                    f"got {expected_value!r}"
                )
                return
            actual_length = len(value)
            if actual_length != expected_length:
                self.error(
                    f"{context}: len({raw_path}) must equal {expected_path} "
                    f"({expected_length}), got {actual_length}"
                )
                return
            self.pass_check()
            return
        self.error(f"{context}: unsupported check operation")

    def validate_freshness(self, payload: dict[str, Any]) -> None:
        freshness = self.requirement.get("freshness")
        if not isinstance(freshness, dict):
            self.error("artifact: registry entry must define freshness policy")
            return
        self.pass_check()

        timestamp_path = freshness.get("timestamp_path")
        if not isinstance(timestamp_path, str) or not timestamp_path.strip():
            self.error("artifact: freshness timestamp_path is missing")
            return
        self.pass_check()

        max_age_hours = freshness.get("max_age_hours")
        self.max_age_hours = (
            max_age_hours
            if isinstance(max_age_hours, int) and not isinstance(max_age_hours, bool)
            else None
        )
        if self.max_age_hours is None or self.max_age_hours <= 0:
            self.error("artifact: freshness max_age_hours is missing")
            return
        self.pass_check()

        generated_at = _get_path(payload, timestamp_path)
        self.generated_at = generated_at if isinstance(generated_at, str) else None
        if not isinstance(generated_at, str) or not generated_at.strip():
            self.error(f"artifact: freshness timestamp {timestamp_path!r} is missing")
            return
        self.pass_check()

        try:
            generated_dt = _parse_timestamp(generated_at)
        except ValueError as exc:
            self.error(f"artifact: {exc}")
            return
        self.pass_check()

        age_hours = (self.as_of - generated_dt).total_seconds() / 3600
        self.age_hours = round(age_hours, 3)
        if age_hours < 0:
            self.error(f"artifact: timestamp {generated_at!r} is in the future")
        elif age_hours > self.max_age_hours:
            self.error(
                f"artifact: stale evidence age_hours={age_hours:.2f} "
                f"max_age_hours={self.max_age_hours}"
            )
        else:
            self.pass_check()

    @property
    def requirement_payload(self) -> dict[str, Any]:
        # Set by validate_payload before checks run.
        return getattr(self, "_payload", {})

    @requirement_payload.setter
    def requirement_payload(self, payload: dict[str, Any]) -> None:
        setattr(self, "_payload", payload)


def _get_path(payload: Any, raw_path: str) -> Any:
    value = payload
    for part in raw_path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            value = value[index] if 0 <= index < len(value) else None
        else:
            return None
    return value


def _get_path_values(payload: Any, raw_path: str) -> list[Any]:
    values = [payload]
    for part in raw_path.split("."):
        next_values: list[Any] = []
        for value in values:
            if part == "*":
                if isinstance(value, list):
                    next_values.extend(value)
                continue
            if isinstance(value, dict):
                next_values.append(value.get(part))
            elif isinstance(value, list) and part.isdigit():
                index = int(part)
                next_values.append(value[index] if 0 <= index < len(value) else None)
            else:
                next_values.append(None)
        values = next_values
    return values


def _path_has_wildcard(raw_path: str) -> bool:
    return "*" in raw_path.split(".")


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _as_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _json_multiset_matches(actual: list[Any], expected: list[Any]) -> bool:
    return sorted(_json_sort_key(item) for item in actual) == sorted(
        _json_sort_key(item) for item in expected
    )


def _json_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _preview_values(values: list[Any], limit: int = 3) -> list[Any]:
    if len(values) <= limit:
        return values
    return [*values[:limit], f"... {len(values) - limit} more"]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _condition_matches(payload: dict[str, Any], condition: dict[str, Any]) -> bool:
    path = condition.get("path")
    if not isinstance(path, str):
        return False
    value = _get_path(payload, path)
    if "equals" in condition:
        return value == condition.get("equals")
    if "not_equals" in condition:
        return value != condition.get("not_equals")
    return bool(value)


def _normalize_as_of(as_of: datetime | None) -> datetime:
    effective = as_of or datetime.now(timezone.utc)
    if effective.tzinfo is None:
        return effective.replace(tzinfo=timezone.utc)
    return effective.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"freshness timestamp is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"freshness timestamp must include timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def find_requirement(
    registry: dict[str, Any],
    *,
    requirement_id: str | None,
    artifact_path: Path,
) -> dict[str, Any]:
    requirements = registry.get("requirements")
    if not isinstance(requirements, list):
        raise ValueError("registry `requirements` must be a list")
    artifact_name = artifact_path.name
    matches: list[dict[str, Any]] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        if requirement_id and item.get("id") == requirement_id:
            matches.append(item)
        elif not requirement_id and item.get("artifact") == artifact_name:
            matches.append(item)
    if not matches:
        target = requirement_id or artifact_name
        raise ValueError(f"no runtime evidence registry requirement matches {target!r}")
    if len(matches) > 1:
        raise ValueError(f"multiple registry requirements match {artifact_name!r}")
    registered_artifact = str(matches[0].get("artifact") or "")
    if registered_artifact != artifact_name:
        raise ValueError(
            f"artifact filename {artifact_name!r} does not match registered artifact "
            f"{registered_artifact!r} for requirement {str(matches[0].get('id') or '')!r}"
        )
    return matches[0]


def validate_artifact(
    *,
    registry: dict[str, Any],
    artifact_path: Path,
    requirement_id: str | None = None,
    as_of: datetime | None = None,
    enforce_freshness: bool = True,
) -> ArtifactResult:
    requirement = find_requirement(
        registry,
        requirement_id=requirement_id,
        artifact_path=artifact_path,
    )
    validator = ArtifactValidator(
        requirement=requirement,
        artifact_path=artifact_path,
        as_of=as_of,
        enforce_freshness=enforce_freshness,
    )
    return validator.validate_file()


def require_valid_registry_contract(registry: dict[str, Any], *, registry_path: Path) -> None:
    result = validate_registry_contract(registry, registry_path=registry_path)
    if result.ok:
        return
    codes = ", ".join(result.to_dict()["error_codes"])
    preview = "; ".join(result.errors[:3])
    if len(result.errors) > 3:
        preview = f"{preview}; ... {len(result.errors) - 3} more"
    raise ValueError(f"registry validation failed ({codes}): {preview}")


def format_summary(result: ArtifactResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    lines = [
        f"Wiii Runtime Evidence Artifact: {status}",
        f"validation_schema: {result.validation_schema_version}",
        f"requirement: {result.requirement_id}",
        f"artifact: {result.artifact_path}",
        f"schema: {result.schema_version}",
        f"checks passed: {result.passed_checks}",
        f"generated_at: {result.generated_at or '-'}",
        f"freshness: {_freshness_summary(result)}",
    ]
    if result.errors:
        error_code_counts = _error_code_counts(result.errors)
        lines.append("")
        lines.append(f"Error codes: {', '.join(_error_codes(result.errors)) or '-'}")
        lines.append(f"Error code counts: {_format_error_code_counts(error_code_counts)}")
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in result.errors)
    return "\n".join(lines)


def _freshness_summary(result: ArtifactResult) -> str:
    if result.max_age_hours is None:
        return "-"
    age = "-" if result.age_hours is None else f"{result.age_hours:.2f}h"
    return f"{age} / {result.max_age_hours}h"


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for error in errors:
        code = _error_code(error)
        counts[code] = counts.get(code, 0) + 1
    return {code: counts[code] for code in sorted(counts)}


def _format_error_code_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "-"
    return ", ".join(f"{code}={count}" for code, count in counts.items())


def _error_code(error: str) -> str:
    return normalize_artifact_error_code(error)


def normalize_artifact_error_code(error: str) -> str:
    if error.startswith("artifact: could not read JSON artifact:"):
        return "artifact_json_read_failed"
    if error.startswith("artifact: path must not be a symlink:"):
        return "artifact_path_symlink"
    if error == "artifact: root must be a JSON object":
        return "artifact_root_not_object"
    if error.startswith("artifact: ") and " must be " in error and ", got " in error:
        return "artifact_schema_mismatch"
    if error.startswith("artifact: forbidden token leaked:"):
        return "artifact_forbidden_token"
    if error.startswith("artifact: forbidden regex matched:"):
        return "artifact_forbidden_regex"
    if error == "artifact: registry entry must define non-empty payload_checks":
        return "artifact_payload_checks_missing"
    if error == "artifact: registry entry must define freshness policy":
        return "artifact_missing_freshness_policy"
    if error == "artifact: freshness timestamp_path is missing":
        return "artifact_freshness_timestamp_path_missing"
    if error == "artifact: freshness max_age_hours is missing":
        return "artifact_freshness_max_age_hours_missing"
    if error.startswith("artifact: freshness timestamp ") and error.endswith(" is missing"):
        return "artifact_freshness_timestamp_missing"
    if error.startswith("artifact: freshness timestamp is not ISO-8601:"):
        return "artifact_freshness_timestamp_invalid_iso8601"
    if error.startswith("artifact: freshness timestamp must include timezone:"):
        return "artifact_freshness_timestamp_missing_timezone"
    if error.startswith("artifact: timestamp ") and error.endswith(" is in the future"):
        return "artifact_freshness_timestamp_future"
    if error.startswith("artifact: stale evidence age_hours="):
        return "artifact_freshness_stale"
    if error.startswith("payload_checks[") and error.endswith(": check must be an object"):
        return "payload_check_not_object"
    if error.startswith("payload_checks[") and ": `path` must be a non-empty string" in error:
        return "payload_check_path_missing"
    if error.startswith("payload_checks[") and error.endswith(" matched no values"):
        return "payload_check_path_no_values"
    if error.startswith("payload_checks[") and " must equal " in error and ", got " in error:
        return "payload_check_equals_mismatch"
    if error.startswith("payload_checks[") and ": min value must be numeric" in error:
        return "payload_check_min_not_numeric"
    if error.startswith("payload_checks[") and " must be >= " in error and ", got " in error:
        return "payload_check_min_mismatch"
    if error.startswith("payload_checks[") and ": sorted_equals must be a list" in error:
        return "payload_check_sorted_equals_not_list"
    if error.startswith("payload_checks[") and " sorted value mismatch: " in error:
        return "payload_check_sorted_equals_mismatch"
    if error.startswith("payload_checks[") and ": length_equals_path must be a non-empty string" in error:
        return "payload_check_length_equals_path_missing"
    if error.startswith("payload_checks[") and " must be a list for length check" in error:
        return "payload_check_length_subject_not_countable"
    if error.startswith("payload_checks[") and " must be an integer length, got " in error:
        return "payload_check_length_expected_not_integer"
    if error.startswith("payload_checks[") and ": len(" in error and "), got " in error:
        return "payload_check_length_mismatch"
    if error.startswith("payload_checks[") and error.endswith(": unsupported check operation"):
        return "payload_check_unsupported_operation"
    if error.startswith("registry validation failed "):
        return "registry_contract_invalid"
    if error == "registry `requirements` must be a list":
        return "registry_requirements_not_list"
    if error.startswith("no runtime evidence registry requirement matches "):
        return "registry_requirement_not_found"
    if error.startswith("multiple registry requirements match "):
        return "registry_requirement_ambiguous"
    if error.startswith("artifact filename ") and " does not match registered artifact " in error:
        return "registry_artifact_filename_mismatch"
    if error.startswith("freshness timestamp is not ISO-8601:"):
        return "freshness_timestamp_invalid_iso8601"
    if error.startswith("freshness timestamp must include timezone:"):
        return "freshness_timestamp_missing_timezone"
    return "validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a Wiii runtime evidence artifact.")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--requirement-id", default=None)
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO-8601 timestamp used for freshness checks; defaults to now.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        registry = load_registry(args.registry)
        require_valid_registry_contract(registry, registry_path=args.registry)
        as_of = _parse_timestamp(args.as_of) if args.as_of else None
        result = validate_artifact(
            registry=registry,
            artifact_path=args.artifact,
            requirement_id=args.requirement_id,
            as_of=as_of,
        )
    except Exception as exc:  # noqa: BLE001
        if args.json:
            error_code = _error_code(str(exc))
            print(
                json.dumps(
                    {
                        "validation_schema_version": ARTIFACT_VALIDATION_SCHEMA_VERSION,
                        "ok": False,
                        "errors": [str(exc)],
                        "error_codes": [error_code],
                        "error_code_counts": {error_code: 1},
                    },
                    indent=2,
                ),
                file=sys.stdout,
            )
        else:
            print(f"Wiii Runtime Evidence Artifact: FAIL\n- {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_summary(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
