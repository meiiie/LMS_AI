#!/usr/bin/env python3
"""Validate standalone Wiii Self-Harness control-plane sidecars match the bundle."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402
from strict_json import load_strict_json_file  # noqa: E402


SIDECAR_PARITY_VALIDATION_SCHEMA_VERSION = (
    "wiii.self_harness_sidecar_parity_validation.v1"
)
SELF_HARNESS_REPORT_NAME = "self-harness-validation.json"
REGISTRY_REPORT_NAME = "runtime-evidence-registry-validation.json"
REPORT_OUTPUT_PATH_DIRECTORY_ERROR = "sidecar parity output path must not be a directory"
REPORT_OUTPUT_PATH_SYMLINK_ERROR = "sidecar parity output path must not be a symlink"
REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "sidecar parity output path parent must not be a symlink"
)
REPORT_OUTPUT_PATH_INSIDE_BUNDLE_ERROR = (
    "sidecar parity output path must be outside bundle root"
)
REPORT_OUTPUT_PATH_OVERWRITES_INPUT_ERROR = (
    "sidecar parity output path must not overwrite input report"
)


@dataclass(frozen=True)
class SidecarParityComparison:
    bundle_report: str
    bundle_path: str
    sidecar_path: str
    bundle_payload_sha256: str
    sidecar_payload_sha256: str
    matched: bool


@dataclass(frozen=True)
class SidecarParityResult:
    ok: bool
    validation_schema_version: str
    bundle_root: str
    compared_count: int
    comparisons: list[SidecarParityComparison]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        error_codes = _error_codes(self.errors)
        data["error_codes"] = error_codes
        data["error_code_counts"] = {
            code: sum(1 for error in self.errors if _error_code(error) == code)
            for code in error_codes
        }
        return data


def validate_sidecar_parity(
    *,
    bundle_root: Path,
    self_harness_sidecar: Path,
    registry_sidecar: Path,
) -> SidecarParityResult:
    errors: list[str] = []
    compared_count = 0
    comparisons: list[SidecarParityComparison] = []

    if bundle_root.is_symlink():
        errors.append(f"bundle root must not be a symlink: {bundle_root}")
    elif not bundle_root.exists():
        errors.append(f"bundle root does not exist: {bundle_root}")
    elif not bundle_root.is_dir():
        errors.append(f"bundle root must be a directory: {bundle_root}")

    for bundle_name, sidecar_path in (
        (SELF_HARNESS_REPORT_NAME, self_harness_sidecar),
        (REGISTRY_REPORT_NAME, registry_sidecar),
    ):
        bundle_payload = _load_json_file(bundle_root / bundle_name, errors)
        sidecar_payload = _load_json_file(sidecar_path, errors)
        if _path_is_inside_bundle(sidecar_path, bundle_root):
            errors.append(
                f"{sidecar_path}: standalone sidecar path must be outside bundle root"
            )
        if bundle_payload is None or sidecar_payload is None:
            continue
        compared_count += 1
        matched = sidecar_payload == bundle_payload
        comparisons.append(
            SidecarParityComparison(
                bundle_report=bundle_name,
                bundle_path=str(bundle_root / bundle_name),
                sidecar_path=str(sidecar_path),
                bundle_payload_sha256=_payload_sha256(bundle_payload),
                sidecar_payload_sha256=_payload_sha256(sidecar_payload),
                matched=matched,
            )
        )
        if not matched:
            errors.append(
                f"{sidecar_path}: standalone sidecar JSON must match "
                f"{bundle_name} from bundle"
            )

    return SidecarParityResult(
        ok=not errors,
        validation_schema_version=SIDECAR_PARITY_VALIDATION_SCHEMA_VERSION,
        bundle_root=str(bundle_root),
        compared_count=compared_count,
        comparisons=comparisons,
        errors=errors,
    )


def _payload_sha256(payload: Any) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _load_json_file(path: Path, errors: list[str]) -> Any | None:
    if path.is_symlink():
        errors.append(f"{path}: report file must not be a symlink")
        return None
    if not path.exists():
        errors.append(f"{path}: report file is missing")
        return None
    if not path.is_file():
        errors.append(f"{path}: report path must be a file")
        return None
    try:
        return load_strict_json_file(path)
    except UnicodeDecodeError as exc:
        errors.append(f"{path}: report file is not valid UTF-8: {exc}")
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"{path}: report JSON is invalid: {exc}")
    return None


def _path_is_inside_bundle(path: Path, bundle_root: Path) -> bool:
    try:
        common_path = os.path.commonpath(
            [
                str(bundle_root.resolve()),
                str(path.resolve(strict=False)),
            ]
        )
    except (OSError, ValueError):
        return False
    return common_path == str(bundle_root.resolve())


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code(error: str) -> str:
    if error.startswith("bundle root does not exist:"):
        return "sidecar_parity_bundle_root_missing"
    if error.startswith("bundle root must not be a symlink:"):
        return "sidecar_parity_bundle_root_symlink"
    if error.startswith("bundle root must be a directory:"):
        return "sidecar_parity_bundle_root_not_directory"
    if "standalone sidecar path must be outside bundle root" in error:
        return "sidecar_parity_path_inside_bundle_root"
    if "report file must not be a symlink" in error:
        return "sidecar_parity_report_file_symlink"
    if "report file is missing" in error:
        return "sidecar_parity_report_file_missing"
    if "report path must be a file" in error:
        return "sidecar_parity_report_path_not_file"
    if "report file is not valid UTF-8" in error:
        return "sidecar_parity_report_file_not_utf8"
    if "report JSON is invalid" in error:
        return "sidecar_parity_report_json_invalid"
    if "standalone sidecar JSON must match" in error:
        return "sidecar_parity_report_mismatch"
    if error == REPORT_OUTPUT_PATH_SYMLINK_ERROR:
        return "sidecar_parity_output_path_symlink"
    if error == REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "sidecar_parity_output_path_parent_symlink"
    if error == REPORT_OUTPUT_PATH_DIRECTORY_ERROR:
        return "sidecar_parity_output_path_directory"
    if error == REPORT_OUTPUT_PATH_INSIDE_BUNDLE_ERROR:
        return "sidecar_parity_output_path_inside_bundle_root"
    if error == REPORT_OUTPUT_PATH_OVERWRITES_INPUT_ERROR:
        return "sidecar_parity_output_path_overwrites_input"
    return "sidecar_parity_unknown"


def _format_error_code_counts(error_code_counts: dict[str, int]) -> str:
    if not error_code_counts:
        return "-"
    return ", ".join(
        f"{error_code}={count}" for error_code, count in error_code_counts.items()
    )


def format_summary(result: SidecarParityResult) -> str:
    data = result.to_dict()
    status = "OK" if result.ok else "FAIL"
    lines = [
        f"Wiii Self-Harness sidecar parity: {status}",
        f"Schema: {result.validation_schema_version}",
        f"Bundle root: {result.bundle_root}",
        f"Compared reports: {result.compared_count}",
        f"Error code counts: {_format_error_code_counts(data['error_code_counts'])}",
    ]
    if result.comparisons:
        lines.append("Comparisons:")
        lines.extend(
            "- "
            + comparison.bundle_report
            + ": "
            + ("MATCH" if comparison.matched else "MISMATCH")
            + f" bundle_sha256={comparison.bundle_payload_sha256} "
            + f"sidecar_sha256={comparison.sidecar_payload_sha256}"
            for comparison in result.comparisons
        )
    if result.errors:
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in result.errors)
    return "\n".join(lines)


def validate_output_path(
    *,
    out_path: Path | None,
    bundle_root: Path | None = None,
    input_paths: tuple[Path, ...] = (),
) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(REPORT_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(REPORT_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR)
    if bundle_root is not None and _path_is_inside_bundle(out_path, bundle_root):
        raise ValueError(REPORT_OUTPUT_PATH_INSIDE_BUNDLE_ERROR)
    out_resolved = out_path.resolve(strict=False)
    for input_path in input_paths:
        if out_resolved == input_path.resolve(strict=False):
            raise ValueError(REPORT_OUTPUT_PATH_OVERWRITES_INPUT_ERROR)


def write_cli_output(rendered: str, out_path: Path | None) -> None:
    if out_path is None:
        print(rendered)
        return
    safe_write_report_text(out_path, rendered + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate standalone Wiii Self-Harness sidecars against a report bundle."
    )
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--self-harness-sidecar", type=Path, required=True)
    parser.add_argument("--registry-sidecar", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        validate_output_path(
            out_path=args.out,
            bundle_root=args.bundle_root,
            input_paths=(
                args.bundle_root / SELF_HARNESS_REPORT_NAME,
                args.bundle_root / REGISTRY_REPORT_NAME,
                args.self_harness_sidecar,
                args.registry_sidecar,
            ),
        )
    except Exception as exc:
        result = SidecarParityResult(
            ok=False,
            validation_schema_version=SIDECAR_PARITY_VALIDATION_SCHEMA_VERSION,
            bundle_root=str(args.bundle_root),
            compared_count=0,
            comparisons=[],
            errors=[str(exc)],
        )
        print(
            json.dumps(result.to_dict(), indent=2, sort_keys=True)
            if args.json
            else format_summary(result),
            file=sys.stdout if args.json else sys.stderr,
        )
        return 1

    result = validate_sidecar_parity(
        bundle_root=args.bundle_root,
        self_harness_sidecar=args.self_harness_sidecar,
        registry_sidecar=args.registry_sidecar,
    )
    rendered = (
        json.dumps(result.to_dict(), indent=2, sort_keys=True)
        if args.json
        else format_summary(result)
    )
    write_cli_output(rendered, args.out)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
