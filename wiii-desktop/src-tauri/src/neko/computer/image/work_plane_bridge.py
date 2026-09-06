#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import mimetypes
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL_VERSION = "wiii-work-plane.preview.v1"
PROJECT_REF = "work:project"
DEFAULT_ROOT = "/workspace/project"
MAX_FILES = 10_000
MAX_FILE_BYTES = 128 * 1024
MAX_QUERY_BYTES = 64 * 1024
MAX_CELLS = 512
SPREADSHEET_EXTENSIONS = {".ods", ".xlsx", ".xls", ".csv"}
CELL_RANGE = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6})(?::\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6}))?$")
FORMULA_CHARACTERS = re.compile(r"^=[A-Za-z0-9_.$:+\-*/(),; <>=]+$")
FORMULA_FUNCTION = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
SAFE_FORMULA_FUNCTIONS = {
    "ABS",
    "AND",
    "AVERAGE",
    "AVERAGEIF",
    "AVERAGEIFS",
    "COUNT",
    "COUNTA",
    "COUNTIF",
    "COUNTIFS",
    "HLOOKUP",
    "IF",
    "IFERROR",
    "INDEX",
    "MAX",
    "MAXIFS",
    "MATCH",
    "MIN",
    "MINIFS",
    "NOT",
    "OR",
    "POWER",
    "RANK",
    "RANK.EQ",
    "ROUND",
    "SQRT",
    "SUM",
    "SUMIF",
    "SUMIFS",
    "VLOOKUP",
}

SPREADSHEET_FORMAT_KEYS = {
    "bold",
    "fontColor",
    "fontSize",
    "fillColor",
    "horizontalAlignment",
    "numberFormat",
    "wrapText",
    "optimalWidth",
    "columnWidth",
    "rowHeight",
}
CHART_TYPES = {
    "bar": "com.sun.star.chart.BarDiagram",
    "column": "com.sun.star.chart.BarDiagram",
    "line": "com.sun.star.chart.LineDiagram",
    "pie": "com.sun.star.chart.PieDiagram",
}
TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,99}$")
CONDITION_OPERATORS = {
    "between": "BETWEEN",
    "equal": "EQUAL",
    "greater_than": "GREATER",
    "greater_than_or_equal": "GREATER_EQUAL",
    "less_than": "LESS",
    "less_than_or_equal": "LESS_EQUAL",
    "not_equal": "NOT_EQUAL",
}
PIVOT_FUNCTIONS = {
    "average": "AVERAGE",
    "count": "COUNT",
    "max": "MAX",
    "min": "MIN",
    "sum": "SUM",
}


class BridgeError(Exception):
    pass


def project_root() -> Path:
    root = Path(os.environ.get("WIII_WORK_PLANE_ROOT", DEFAULT_ROOT))
    if not root.is_dir():
        raise BridgeError("project_unavailable: the granted Project is not mounted")
    return root.resolve(strict=True)


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def file_revision(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(128 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def directory_revision(root: Path) -> str:
    digest = hashlib.sha256()
    for path in list_files(root):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        digest.update(
            f"file\0{relative}\0{metadata.st_size}\0{metadata.st_mtime_ns}\n".encode("utf-8")
        )
    return "sha256:" + digest.hexdigest()


def encode_ref(relative: str) -> str:
    token = base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii").rstrip("=")
    return "work:file:" + token


def decode_ref(resource_ref: str) -> str:
    if not resource_ref.startswith("work:file:"):
        raise BridgeError("invalid_resource_ref: expected a Project file resource")
    token = resource_ref[len("work:file:") :]
    if not token or len(token) > 500 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise BridgeError("invalid_resource_ref: malformed file identity")
    try:
        return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise BridgeError("invalid_resource_ref: malformed file identity") from error


def protected_path(path: PurePosixPath) -> bool:
    protected_names = {".git", ".ssh", ".aws", ".azure", ".gnupg", ".npmrc", ".pypirc", ".wiii-perf-secret"}
    return any(
        part.casefold() in protected_names
        or part.casefold().startswith(".env")
        or PurePosixPath(part).suffix.casefold() in {".pem", ".key", ".p12", ".pfx"}
        for part in path.parts
    )


def logical_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or len(value) > 240 or "\x00" in value:
        raise BridgeError("invalid_path: logical Project path is invalid")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BridgeError("path_escape: path must stay inside the granted Project")
    if protected_path(path):
        raise BridgeError("protected_path: credential and repository metadata are not Work Plane resources")
    return path


def resolve_relative(root: Path, value: str, *, must_exist: bool) -> Path:
    relative = logical_path(value)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            if cursor.is_symlink():
                raise BridgeError("symlink_forbidden: Work Plane does not follow Project symlinks")
    if must_exist and not candidate.is_file():
        raise BridgeError("resource_not_found: Project file does not exist")
    try:
        parent = candidate.parent.resolve(strict=True)
    except FileNotFoundError as error:
        raise BridgeError("parent_not_found: destination parent must already exist") from error
    if parent != root and root not in parent.parents:
        raise BridgeError("path_escape: path must stay inside the granted Project")
    return candidate


def path_from_ref(root: Path, resource_ref: str) -> Path:
    return resolve_relative(root, decode_ref(resource_ref), must_exist=True)


def spreadsheet_available() -> bool:
    return shutil.which("libreoffice") is not None and importlib.util.find_spec("uno") is not None


def resource_type(path: Path) -> str:
    return "spreadsheet.workbook" if path.suffix.lower() in SPREADSHEET_EXTENSIONS else "project.file"


def resource_capabilities(path: Path) -> list[str]:
    capabilities = ["project.file.patch_text", "project.file.rename"]
    if resource_type(path) == "spreadsheet.workbook":
        capabilities = ["project.file.rename"]
        if spreadsheet_available():
            capabilities.extend(
                (
                    "spreadsheet.range.set",
                    "spreadsheet.range.format",
                    "spreadsheet.range.merge",
                    "spreadsheet.table.upsert",
                    "spreadsheet.conditional_format.upsert",
                    "spreadsheet.pivot.upsert",
                    "spreadsheet.chart.upsert",
                    "spreadsheet.sheet.layout",
                    "spreadsheet.batch",
                    "spreadsheet.export",
                )
            )
    return capabilities


def file_resource(root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {
        "ref": encode_ref(relative),
        "resourceType": resource_type(path),
        "name": path.name,
        "parentRef": PROJECT_REF,
        "revision": file_revision(path),
        "mediaType": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "capabilities": resource_capabilities(path),
        "source": "project",
        "metadata": {"path": relative, "sizeBytes": path.stat().st_size},
    }


def root_resource(root: Path) -> dict[str, Any]:
    return {
        "ref": PROJECT_REF,
        "resourceType": "project.root",
        "name": "Project",
        "parentRef": None,
        "revision": directory_revision(root),
        "mediaType": None,
        "capabilities": ["project.file.create"],
        "source": "project",
        "metadata": {},
    }


def capability(
    identifier: str,
    resource_types: list[str],
    schema: dict[str, Any],
    reversible: bool,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "id": identifier,
        "version": "1",
        "resourceTypes": resource_types,
        "inputSchema": schema,
        "mutating": True,
        "risk": "reversible_local_edit" if reversible else "local_export",
        "approval": "project_write_grant",
        "retry": "idempotency_key_and_revision",
        "reversible": reversible,
        "maxInputBytes": 256 * 1024,
        "evidence": evidence,
    }


def capability_catalog() -> list[dict[str, Any]]:
    catalog = [
        capability(
            "project.file.create",
            ["project.root"],
            {
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string", "maxLength": 240},
                    "content": {"type": "string", "maxLength": MAX_FILE_BYTES},
                },
                "additionalProperties": False,
            },
            True,
            ["file_hash_readback"],
        ),
        capability(
            "project.file.patch_text",
            ["project.file"],
            {
                "type": "object",
                "required": ["expectedText", "replacement"],
                "properties": {
                    "expectedText": {"type": "string", "maxLength": MAX_QUERY_BYTES},
                    "replacement": {"type": "string", "maxLength": MAX_FILE_BYTES},
                },
                "additionalProperties": False,
            },
            True,
            ["file_hash_readback", "exact_patch_count"],
        ),
        capability(
            "project.file.rename",
            ["project.file", "spreadsheet.workbook"],
            {
                "type": "object",
                "required": ["destination"],
                "properties": {"destination": {"type": "string", "maxLength": 240}},
                "additionalProperties": False,
            },
            True,
            ["source_absent", "destination_hash_readback"],
        ),
    ]
    if spreadsheet_available():
        catalog.extend(
            (
                capability(
                    "spreadsheet.workbook.create",
                    ["project.root"],
                    {
                        "type": "object",
                        "required": ["path", "sheets"],
                        "properties": {
                            "path": {"type": "string", "maxLength": 240},
                            "sheets": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 16,
                                "items": {"type": "string", "maxLength": 100},
                            },
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["workbook_structure_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.range.set",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["sheet", "range", "cells"],
                        "properties": {
                            "sheet": {"type": "string", "maxLength": 200},
                            "range": {"type": "string", "maxLength": 100},
                            "cells": {"type": "array", "maxItems": MAX_CELLS},
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["formula_readback", "recalculated_value", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.range.format",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["sheet", "range", "format"],
                        "properties": {
                            "sheet": {"type": "string", "maxLength": 200},
                            "range": {"type": "string", "maxLength": 100},
                            "format": {"type": "object"},
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["format_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.range.merge",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["sheet", "range", "merged"],
                        "properties": {
                            "sheet": {"type": "string", "maxLength": 200},
                            "range": {"type": "string", "maxLength": 100},
                            "merged": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["merge_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.table.upsert",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["sheet", "name", "range"],
                        "properties": {
                            "sheet": {"type": "string", "maxLength": 200},
                            "name": {"type": "string", "maxLength": 100},
                            "range": {"type": "string", "maxLength": 100},
                            "hasHeaders": {"type": "boolean"},
                            "autoFilter": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["table_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.conditional_format.upsert",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["sheet", "range", "operator", "formula1", "style"],
                        "properties": {
                            "sheet": {"type": "string", "maxLength": 200},
                            "range": {"type": "string", "maxLength": 100},
                            "operator": {"enum": sorted(CONDITION_OPERATORS)},
                            "formula1": {"type": ["number", "string"]},
                            "formula2": {"type": ["number", "string"]},
                            "style": {"type": "object"},
                            "replace": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["conditional_format_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.pivot.upsert",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": [
                            "sourceSheet",
                            "sourceRange",
                            "outputSheet",
                            "outputCell",
                            "name",
                            "rows",
                            "columns",
                            "data",
                        ],
                        "properties": {
                            "sourceSheet": {"type": "string", "maxLength": 200},
                            "sourceRange": {"type": "string", "maxLength": 100},
                            "outputSheet": {"type": "string", "maxLength": 200},
                            "outputCell": {"type": "string", "maxLength": 100},
                            "name": {"type": "string", "maxLength": 100},
                            "rows": {"type": "array", "maxItems": 8},
                            "columns": {"type": "array", "maxItems": 8},
                            "data": {"type": "array", "minItems": 1, "maxItems": 16},
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["pivot_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.chart.upsert",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["sheet", "name", "sourceRange", "anchorRange", "chartType"],
                        "properties": {
                            "sheet": {"type": "string", "maxLength": 200},
                            "name": {"type": "string", "maxLength": 100},
                            "sourceRange": {"type": "string", "maxLength": 100},
                            "anchorRange": {"type": "string", "maxLength": 100},
                            "chartType": {"enum": sorted(CHART_TYPES)},
                            "title": {"type": "string", "maxLength": 200},
                            "hasLegend": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["chart_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.sheet.layout",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["sheet", "printRange", "orientation", "fitWidth", "fitHeight"],
                        "properties": {
                            "sheet": {"type": "string", "maxLength": 200},
                            "printRange": {"type": "string", "maxLength": 100},
                            "orientation": {"enum": ["portrait", "landscape"]},
                            "fitWidth": {"type": "integer", "minimum": 1, "maximum": 10},
                            "fitHeight": {"type": "integer", "minimum": 0, "maximum": 10},
                            "margin": {"type": "integer", "minimum": 0, "maximum": 5000},
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["page_layout_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.batch",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["operations"],
                        "properties": {
                            "operations": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 64,
                                "items": {"type": "object"},
                            }
                        },
                        "additionalProperties": False,
                    },
                    True,
                    ["batch_readback", "file_hash_readback"],
                ),
                capability(
                    "spreadsheet.export",
                    ["spreadsheet.workbook"],
                    {
                        "type": "object",
                        "required": ["format", "destination"],
                        "properties": {
                            "format": {"enum": ["pdf"]},
                            "destination": {"type": "string", "maxLength": 240},
                        },
                        "additionalProperties": False,
                    },
                    False,
                    ["export_hash_readback"],
                ),
            )
        )
    return catalog


def describe() -> dict[str, Any]:
    root = project_root()
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "sourceAuthority": "source_application",
        "resourceModel": "typed_revisioned_resources",
        "transactionModel": "optimistic_idempotent",
        "root": root_resource(root),
        "capabilities": capability_catalog(),
    }


def list_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if not (Path(current) / name).is_symlink()
            and not protected_path((Path(current) / name).relative_to(root))
        )
        for name in sorted(files):
            path = Path(current) / name
            if not path.is_symlink() and not protected_path(path.relative_to(root)):
                paths.append(path)
            if len(paths) > MAX_FILES:
                raise BridgeError("project_too_large: Work Plane supports at most 10000 files")
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix().casefold())


def query_children(request: dict[str, Any], root: Path) -> dict[str, Any]:
    if request.get("resourceRef") != PROJECT_REF:
        raise BridgeError("invalid_view: children requires the Project root")
    offset = bounded_integer(request.get("offset", 0), 0, 10_000_000, "offset")
    limit = bounded_integer(request.get("maxItems", 100), 1, 200, "maxItems")
    paths = list_files(root)
    selected = paths[offset : offset + limit]
    next_offset = offset + len(selected) if offset + len(selected) < len(paths) else None
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "resource": root_resource(root),
        "items": [file_resource(root, path) for path in selected],
        "data": {"totalItems": len(paths)},
        "truncated": next_offset is not None,
        "nextOffset": next_offset,
        "evidence": ["directory_enumeration", "source_revision"],
    }


def query_content(request: dict[str, Any], root: Path) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "resourceRef", 512))
    if resource_type(path) == "spreadsheet.workbook":
        raise BridgeError("unsupported_view: use spreadsheet view for workbook resources")
    offset = bounded_integer(request.get("offset", 0), 0, 10_000_000, "offset")
    limit = bounded_integer(request.get("maxBytes", MAX_QUERY_BYTES), 1, MAX_QUERY_BYTES, "maxBytes")
    with path.open("rb") as source:
        source.seek(offset)
        payload = source.read(limit + 1)
    truncated = len(payload) > limit
    payload = payload[:limit]
    next_offset = offset + len(payload) if truncated else None
    try:
        text = payload.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = None
        encoding = "base64"
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "resource": file_resource(root, path),
        "items": [],
        "data": {
            "offset": offset,
            "encoding": encoding,
            "content": text,
            "contentBase64": base64.b64encode(payload).decode("ascii") if text is None else None,
        },
        "truncated": truncated,
        "nextOffset": next_offset,
        "evidence": ["file_hash_readback", "bounded_content_read"],
    }


def bounded_integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BridgeError(f"invalid_{label}: expected integer between {minimum} and {maximum}")
    return value


def required_string(value: dict[str, Any], key: str, maximum: int) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate or len(candidate) > maximum:
        raise BridgeError(f"invalid_{key}: expected non-empty bounded string")
    return candidate


def bounded_string(value: dict[str, Any], key: str, maximum_bytes: int) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or len(candidate.encode("utf-8")) > maximum_bytes:
        raise BridgeError(f"invalid_{key}: expected bounded UTF-8 text")
    return candidate


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BridgeError(f"invalid_{label}: expected object")
    return value


def parse_range(
    value: str, *, max_cells: int = MAX_CELLS
) -> tuple[int, int, int, int]:
    match = CELL_RANGE.fullmatch(value.upper())
    if not match:
        raise BridgeError("invalid_range: expected an A1 range")
    start_column = column_index(match.group(1))
    start_row = int(match.group(2)) - 1
    end_column = column_index(match.group(3) or match.group(1))
    end_row = int(match.group(4) or match.group(2)) - 1
    if end_column < start_column or end_row < start_row:
        raise BridgeError("invalid_range: range end precedes start")
    if (end_column - start_column + 1) * (end_row - start_row + 1) > max_cells:
        raise BridgeError(f"range_too_large: at most {max_cells} cells are allowed")
    return start_column, start_row, end_column, end_row


def column_index(value: str) -> int:
    result = 0
    for character in value:
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def column_name(index: int) -> str:
    value = index + 1
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


class OfficeSession:
    def __init__(self) -> None:
        if not spreadsheet_available():
            raise BridgeError("adapter_unavailable: LibreOffice spreadsheet adapter is not installed")
        import uno

        self.uno = uno
        self.profile = None
        self.process = None
        self.owns_process = False
        self.context = None
        local_context = uno.getComponentContext()
        resolver = local_context.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_context
        )
        shared_pipe = os.environ.get("WIII_WORK_PLANE_OFFICE_PIPE", "wiii_work_plane_office")
        try:
            self.context = resolver.resolve(
                f"uno:pipe,name={shared_pipe};urp;StarOffice.ComponentContext"
            )
        except Exception:
            self.context = None
        if self.context is not None:
            self.desktop = self.context.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", self.context
            )
            return
        self.profile = tempfile.TemporaryDirectory(prefix="wiii-work-plane-office-")
        self.pipe = "wiii_work_plane_" + secrets.token_hex(8)
        self.process = subprocess.Popen(
            [
                "libreoffice",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--norestore",
                f"-env:UserInstallation={Path(self.profile.name).as_uri()}",
                f"--accept=pipe,name={self.pipe};urp;StarOffice.ServiceManager",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.owns_process = True
        local_context = uno.getComponentContext()
        resolver = local_context.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_context
        )
        for _ in range(200):
            if self.process.poll() is not None:
                break
            try:
                self.context = resolver.resolve(
                    f"uno:pipe,name={self.pipe};urp;StarOffice.ComponentContext"
                )
                break
            except Exception:
                time.sleep(0.1)
        if self.context is None:
            self.close()
            raise BridgeError("adapter_unavailable: LibreOffice did not become ready")
        self.desktop = self.context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", self.context
        )

    def property(self, name: str, value: Any) -> Any:
        item = self.uno.createUnoStruct("com.sun.star.beans.PropertyValue")
        item.Name = name
        item.Value = value
        return item

    def open(self, path: Path, *, read_only: bool) -> Any:
        document = self.desktop.loadComponentFromURL(
            self.uno.systemPathToFileUrl(str(path)),
            "_blank",
            0,
            (
                self.property("Hidden", True),
                self.property("ReadOnly", read_only),
                self.property(
                    "MacroExecutionMode",
                    self.uno.getConstantByName(
                        "com.sun.star.document.MacroExecMode.NEVER_EXECUTE"
                    ),
                ),
                self.property(
                    "UpdateDocMode",
                    self.uno.getConstantByName(
                        "com.sun.star.document.UpdateDocMode.NO_UPDATE"
                    ),
                ),
            ),
        )
        if document is None or not document.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
            if document is not None:
                document.close(True)
            raise BridgeError("unsupported_resource: file is not a LibreOffice spreadsheet")
        return document

    def create_spreadsheet(self) -> Any:
        document = self.desktop.loadComponentFromURL(
            "private:factory/scalc",
            "_blank",
            0,
            (self.property("Hidden", True),),
        )
        if document is None or not document.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
            if document is not None:
                document.close(True)
            raise BridgeError("adapter_unavailable: LibreOffice could not create a spreadsheet")
        return document

    def close(self) -> None:
        if self.owns_process and getattr(self, "desktop", None) is not None:
            try:
                self.desktop.terminate()
            except Exception:
                pass
        process = getattr(self, "process", None)
        if self.owns_process and process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        profile = getattr(self, "profile", None)
        if self.owns_process and profile is not None:
            profile.cleanup()

    def __enter__(self) -> "OfficeSession":
        return self

    def __exit__(self, _kind: Any, _error: Any, _traceback: Any) -> None:
        self.close()


def used_range(sheet: Any) -> str:
    cursor = sheet.createCursor()
    cursor.gotoEndOfUsedArea(True)
    address = cursor.RangeAddress
    return (
        f"{column_name(address.StartColumn)}{address.StartRow + 1}:"
        f"{column_name(address.EndColumn)}{address.EndRow + 1}"
    )


def range_payload(sheet: Any, range_name: str, document: Any | None = None) -> dict[str, Any]:
    parse_range(range_name)
    selected = sheet.getCellRangeByName(range_name)
    formulas = [list(row) for row in selected.getFormulaArray()]
    values = [list(row) for row in selected.getDataArray()]
    displayed = [
        [selected.getCellByPosition(column, row).getString() for column in range(len(values[row]))]
        for row in range(len(values))
    ]
    first = selected.getCellByPosition(0, 0)
    number_format = None
    if document is not None:
        try:
            number_format = str(
                document.getNumberFormats().getByKey(int(first.NumberFormat)).FormatString
            )
        except Exception:
            number_format = None
    alignment_text = str(first.HoriJustify)
    alignment_match = re.search(r"\('([A-Z]+)'\)", alignment_text)
    horizontal_alignment = (
        alignment_match.group(1).lower()
        if alignment_match
        else alignment_text.rsplit(".", 1)[-1].lower()
    )
    return {
        "range": range_name.upper(),
        "values": values,
        "formulas": formulas,
        "displayed": displayed,
        "format": {
            "bold": float(first.CharWeight) >= 140,
            "fontColor": color_text(int(first.CharColor)),
            "fontSize": float(first.CharHeight),
            "fillColor": color_text(int(first.CellBackColor)),
            "horizontalAlignment": horizontal_alignment,
            "numberFormat": number_format,
            "wrapText": bool(first.IsTextWrapped),
        },
    }


def color_text(value: int) -> str:
    return f"#{value & 0xFFFFFF:06X}"


def chart_payload(sheet: Any) -> list[dict[str, Any]]:
    charts = sheet.getCharts()
    result: list[dict[str, Any]] = []
    for name in charts.getElementNames():
        chart = charts.getByName(name)
        embedded = chart.getEmbeddedObject()
        diagram = embedded.getDiagram()
        try:
            diagram_type = str(diagram.getDiagramType())
        except Exception:
            diagram_type = ""
        if diagram.supportsService("com.sun.star.chart.BarDiagram") or diagram_type.endswith(
            "BarDiagram"
        ):
            chart_type = "bar" if bool(getattr(diagram, "Vertical", False)) else "column"
        else:
            chart_type = next(
                (key for key, service in CHART_TYPES.items() if diagram.supportsService(service)),
                "unknown",
            )
        title = ""
        if bool(getattr(embedded, "HasMainTitle", False)):
            title = str(embedded.getTitle().String)
        result.append(
            {
                "name": name,
                "chartType": chart_type,
                "title": title,
                "hasLegend": bool(getattr(embedded, "HasLegend", False)),
            }
        )
    return result


def range_address_text(address: Any) -> str:
    return (
        f"{column_name(int(address.StartColumn))}{int(address.StartRow) + 1}:"
        f"{column_name(int(address.EndColumn))}{int(address.EndRow) + 1}"
    )


def enum_name(value: Any) -> str:
    text = str(value)
    match = re.search(r"\('([A-Z_]+)'\)", text)
    return (match.group(1) if match else text.rsplit(".", 1)[-1]).lower()


def database_ranges(document: Any) -> Any:
    getter = getattr(document, "getDatabaseRanges", None)
    if callable(getter):
        return getter()
    return document.DatabaseRanges


def table_payload(document: Any, sheet_name: str | None = None) -> list[dict[str, Any]]:
    sheets = document.getSheets()
    sheet_names = list(sheets.getElementNames())
    ranges = database_ranges(document)
    result: list[dict[str, Any]] = []
    for name in ranges.getElementNames():
        item = ranges.getByName(name)
        address = item.getDataArea()
        current_sheet = sheet_names[int(address.Sheet)]
        if sheet_name is not None and current_sheet != sheet_name:
            continue
        result.append(
            {
                "name": name,
                "sheet": current_sheet,
                "range": range_address_text(address),
                "hasHeaders": bool(getattr(item, "ContainsHeader", True)),
                "autoFilter": bool(getattr(item, "AutoFilter", False)),
            }
        )
    return result


def pivot_payload(sheet: Any) -> list[dict[str, Any]]:
    tables = sheet.getDataPilotTables()
    result: list[dict[str, Any]] = []
    for name in tables.getElementNames():
        table = tables.getByName(name)
        source = table.getSourceRange()
        output = table.getOutputRange()
        fields: list[dict[str, str]] = []
        for index in range(table.getDataPilotFields().getCount()):
            field = table.getDataPilotFields().getByIndex(index)
            orientation = enum_name(getattr(field, "Orientation", ""))
            if orientation in {"hidden", "automatic"}:
                continue
            fields.append(
                {
                    "name": str(getattr(field, "Name", "")),
                    "orientation": orientation,
                    "function": enum_name(getattr(field, "Function", "")),
                }
            )
        result.append(
            {
                "name": name,
                "sourceRange": range_address_text(source),
                "outputRange": range_address_text(output),
                "fields": fields,
            }
        )
    return result


def style_payload(document: Any, style_name: str) -> dict[str, Any] | None:
    try:
        styles = document.getStyleFamilies().getByName("CellStyles")
        if not styles.hasByName(style_name):
            return None
        style = styles.getByName(style_name)
        number_format = str(
            document.getNumberFormats().getByKey(int(style.NumberFormat)).FormatString
        )
        return {
            "bold": float(style.CharWeight) >= 140,
            "fontColor": color_text(int(style.CharColor)),
            "fontSize": float(style.CharHeight),
            "fillColor": color_text(int(style.CellBackColor)),
            "numberFormat": number_format,
        }
    except Exception:
        return None


def conditional_format_payload(document: Any, selected: Any) -> list[dict[str, Any]]:
    entries = selected.ConditionalFormat
    result: list[dict[str, Any]] = []
    for index in range(entries.getCount()):
        entry = entries.getByIndex(index)
        style_name = str(getattr(entry, "StyleName", ""))
        result.append(
            {
                "operator": enum_name(getattr(entry, "Operator", "")),
                "formula1": str(getattr(entry, "Formula1", "")),
                "formula2": str(getattr(entry, "Formula2", "")),
                "styleName": style_name,
                "style": style_payload(document, style_name),
            }
        )
    return result


def query_spreadsheet(request: dict[str, Any], root: Path) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "resourceRef", 512))
    if resource_type(path) != "spreadsheet.workbook":
        raise BridgeError("unsupported_resource: spreadsheet view requires a workbook")
    sheet_name = request.get("sheet")
    range_name = request.get("range")
    with OfficeSession() as office:
        document = office.open(path, read_only=True)
        try:
            sheets = document.getSheets()
            names = list(sheets.getElementNames())
            data: dict[str, Any] = {"sheets": []}
            for name in names:
                sheet = sheets.getByName(name)
                data["sheets"].append({"name": name, "usedRange": used_range(sheet)})
            if sheet_name is not None:
                if not isinstance(sheet_name, str) or sheet_name not in names:
                    raise BridgeError("sheet_not_found: workbook does not contain the requested sheet")
                selected_sheet = sheets.getByName(sheet_name)
                selected_range = range_name or used_range(selected_sheet)
                if not isinstance(selected_range, str):
                    raise BridgeError("invalid_range: expected an A1 range")
                data["selection"] = {
                    "sheet": sheet_name,
                    **range_payload(selected_sheet, selected_range, document),
                }
                data["charts"] = chart_payload(selected_sheet)
                data["tables"] = table_payload(document, sheet_name)
                data["pivots"] = pivot_payload(selected_sheet)
                data["conditionalFormats"] = conditional_format_payload(
                    document, selected_sheet.getCellRangeByName(selected_range)
                )
        finally:
            document.close(True)
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "resource": file_resource(root, path),
        "items": [],
        "data": data,
        "truncated": False,
        "nextOffset": None,
        "evidence": ["libreoffice_readback", "file_hash_readback"],
    }


def query(request: dict[str, Any]) -> dict[str, Any]:
    root = project_root()
    view = request.get("view")
    if view == "children":
        return query_children(request, root)
    if view == "content":
        return query_content(request, root)
    if view == "spreadsheet":
        return query_spreadsheet(request, root)
    raise BridgeError("invalid_view: Work Plane view is not supported")


def rejection(
    request: dict[str, Any],
    code: str,
    detail: str,
    revision: str,
    evidence: list[str],
    recovery: str,
) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "outcome": "rejected",
        "code": code,
        "detail": detail,
        "capabilityId": request.get("capabilityId", "unknown"),
        "targetRef": request.get("targetRef", PROJECT_REF),
        "beforeRevision": revision,
        "afterRevision": revision,
        "changes": [],
        "evidence": evidence,
        "reversible": True,
        "recovery": recovery,
    }


def completed(
    request: dict[str, Any],
    before: str,
    after: str,
    changes: list[dict[str, Any]],
    evidence: list[str],
    *,
    reversible: bool,
) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "outcome": "completed",
        "code": None,
        "detail": "Source mutation completed and read back.",
        "capabilityId": request["capabilityId"],
        "targetRef": request["targetRef"],
        "beforeRevision": before,
        "afterRevision": after,
        "changes": changes,
        "evidence": evidence,
        "reversible": reversible,
        "recovery": None,
    }


def atomic_write(path: Path, payload: bytes) -> None:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    handle, temporary = tempfile.mkstemp(prefix=".wiii-work-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def ensure_revision(request: dict[str, Any], current: str) -> dict[str, Any] | None:
    expected = required_string(request, "ifRevision", 96)
    if current == expected:
        return None
    return rejection(
        request,
        "stale_revision",
        "The source changed; query the resource before retrying.",
        current,
        ["revision_mismatch"],
        "query_resource",
    )


def execute_create(request: dict[str, Any], root: Path, input_value: dict[str, Any]) -> dict[str, Any]:
    before = directory_revision(root)
    if stale := ensure_revision(request, before):
        return stale
    destination = resolve_relative(root, required_string(input_value, "path", 240), must_exist=False)
    if destination.exists():
        return rejection(request, "resource_exists", "Destination already exists.", before, ["destination_exists"], "choose_destination")
    content = bounded_string(input_value, "content", MAX_FILE_BYTES)
    if directory_revision(root) != before:
        return ensure_revision(request, directory_revision(root)) or rejection(request, "stale_revision", "Project changed.", before, [], "query_resource")
    atomic_write(destination, content.encode("utf-8"))
    created = file_resource(root, destination)
    after = directory_revision(root)
    return completed(
        request,
        before,
        after,
        [{"ref": created["ref"], "kind": "created", "beforeRevision": None, "afterRevision": created["revision"]}],
        ["file_hash_readback"],
        reversible=True,
    )


def execute_patch(request: dict[str, Any], root: Path, input_value: dict[str, Any]) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    if resource_type(path) != "project.file":
        raise BridgeError("unsupported_resource: text patch requires a normal Project file")
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    payload = path.read_bytes()
    if len(payload) > MAX_FILE_BYTES:
        raise BridgeError("resource_too_large: text patch supports files up to 131072 bytes")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BridgeError("unsupported_encoding: text patch requires UTF-8") from error
    expected = required_string(input_value, "expectedText", MAX_QUERY_BYTES)
    replacement = input_value.get("replacement")
    if not isinstance(replacement, str) or len(replacement.encode("utf-8")) > MAX_FILE_BYTES:
        raise BridgeError("invalid_replacement: replacement must be bounded UTF-8 text")
    count = text.count(expected)
    if count != 1:
        return rejection(request, "patch_ambiguous", "Expected text must occur exactly once.", before, [f"match_count:{count}"], "query_resource")
    updated = text.replace(expected, replacement, 1).encode("utf-8")
    if len(updated) > MAX_FILE_BYTES:
        raise BridgeError("result_too_large: patched file exceeds 131072 bytes")
    if file_revision(path) != before:
        return ensure_revision(request, file_revision(path)) or rejection(request, "stale_revision", "File changed.", before, [], "query_resource")
    atomic_write(path, updated)
    after = file_revision(path)
    return completed(
        request,
        before,
        after,
        [{"ref": request["targetRef"], "kind": "updated", "beforeRevision": before, "afterRevision": after}],
        ["exact_patch_count", "file_hash_readback"],
        reversible=True,
    )


def execute_rename(request: dict[str, Any], root: Path, input_value: dict[str, Any]) -> dict[str, Any]:
    source = path_from_ref(root, required_string(request, "targetRef", 512))
    before = file_revision(source)
    if stale := ensure_revision(request, before):
        return stale
    destination = resolve_relative(root, required_string(input_value, "destination", 240), must_exist=False)
    if destination.exists():
        return rejection(request, "resource_exists", "Destination already exists.", before, ["destination_exists"], "choose_destination")
    if file_revision(source) != before:
        return ensure_revision(request, file_revision(source)) or rejection(request, "stale_revision", "File changed.", before, [], "query_resource")
    os.replace(source, destination)
    after = file_revision(destination)
    destination_ref = encode_ref(destination.relative_to(root).as_posix())
    return completed(
        request,
        before,
        after,
        [
            {"ref": request["targetRef"], "kind": "removed", "beforeRevision": before, "afterRevision": None},
            {"ref": destination_ref, "kind": "created", "beforeRevision": None, "afterRevision": after},
        ],
        ["source_absent", "destination_hash_readback"],
        reversible=True,
    )


def validate_sheet_names(value: Any) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise BridgeError("invalid_sheets: workbook requires between 1 and 16 sheets")
    names: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 31
            or any(character in item for character in "[]:*?/\\")
            or any(ord(character) < 32 or ord(character) == 127 for character in item)
        ):
            raise BridgeError("invalid_sheet: sheet names must be valid Excel identifiers")
        names.append(item)
    if len({name.casefold() for name in names}) != len(names):
        raise BridgeError("invalid_sheets: sheet names must be unique")
    return names


def execute_spreadsheet_create(
    request: dict[str, Any], root: Path, input_value: dict[str, Any]
) -> dict[str, Any]:
    before = directory_revision(root)
    if stale := ensure_revision(request, before):
        return stale
    destination = resolve_relative(
        root, required_string(input_value, "path", 240), must_exist=False
    )
    if destination.suffix.lower() not in {".xlsx", ".ods"}:
        raise BridgeError("invalid_destination: workbook creation requires .xlsx or .ods")
    if destination.exists():
        return rejection(
            request,
            "resource_exists",
            "Destination already exists.",
            before,
            ["destination_exists"],
            "choose_destination",
        )
    sheet_names = validate_sheet_names(input_value.get("sheets"))
    if directory_revision(root) != before:
        return ensure_revision(request, directory_revision(root)) or rejection(
            request, "stale_revision", "Project changed.", before, [], "query_resource"
        )
    with OfficeSession() as office:
        document = office.create_spreadsheet()
        try:
            sheets = document.getSheets()
            existing = list(sheets.getElementNames())
            first = sheets.getByName(existing[0])
            first.setName(sheet_names[0])
            for name in sheet_names[1:]:
                sheets.insertNewByName(name, sheets.getCount())
            for name in existing[1:]:
                if sheets.hasByName(name):
                    sheets.removeByName(name)
            document.storeAsURL(
                office.uno.systemPathToFileUrl(str(destination)),
                (
                    office.property(
                        "FilterName",
                        "Calc MS Excel 2007 XML"
                        if destination.suffix.lower() == ".xlsx"
                        else "calc8",
                    ),
                    office.property("Overwrite", False),
                ),
            )
        finally:
            document.close(True)
    created = file_resource(root, destination)
    return completed(
        request,
        before,
        directory_revision(root),
        [
            {
                "ref": created["ref"],
                "kind": "created",
                "beforeRevision": None,
                "afterRevision": created["revision"],
            }
        ],
        ["workbook_structure_readback", "file_hash_readback"],
        reversible=True,
    )


def validate_formula(value: str) -> None:
    if (
        len(value) > 4096
        or not FORMULA_CHARACTERS.fullmatch(value)
        or any(
            function.upper() not in SAFE_FORMULA_FUNCTIONS
            for function in FORMULA_FUNCTION.findall(value)
        )
    ):
        raise BridgeError("unsafe_formula: preview formulas must be data-only")


def validate_cell_value(value: Any) -> None:
    if isinstance(value, dict):
        if set(value) == {"formula"} and isinstance(value["formula"], str):
            validate_formula(value["formula"])
            return
        if set(value) == {"value"}:
            value = value["value"]
        else:
            raise BridgeError("invalid_cell: use a scalar, {value}, or {formula}")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str) and len(value) <= 16_384:
        return
    raise BridgeError("invalid_cell: unsupported or oversized cell value")


def set_cell(cell: Any, value: Any) -> None:
    validate_cell_value(value)
    if isinstance(value, dict):
        if "formula" in value:
            cell.setFormula(value["formula"])
            return
        value = value["value"]
    if value is None:
        cell.setString("")
    elif isinstance(value, bool):
        cell.setValue(1.0 if value else 0.0)
    elif isinstance(value, (int, float)):
        cell.setValue(float(value))
    elif isinstance(value, str) and len(value) <= 16_384:
        cell.setString(value)


def apply_spreadsheet_set(document: Any, input_value: dict[str, Any]) -> dict[str, Any]:
    sheet_name = required_string(input_value, "sheet", 200)
    range_name = required_string(input_value, "range", 100).upper()
    start_column, start_row, end_column, end_row = parse_range(range_name)
    cells = input_value.get("cells")
    rows = end_row - start_row + 1
    columns = end_column - start_column + 1
    if not isinstance(cells, list) or len(cells) != rows or any(not isinstance(row, list) or len(row) != columns for row in cells):
        raise BridgeError("invalid_cells: cells must match the requested rectangular range")
    for row in cells:
        for value in row:
            validate_cell_value(value)
    sheets = document.getSheets()
    if not sheets.hasByName(sheet_name):
        raise BridgeError("sheet_not_found: workbook does not contain the requested sheet")
    selected = sheets.getByName(sheet_name).getCellRangeByName(range_name)
    for row_index, row in enumerate(cells):
        for column_index_value, value in enumerate(row):
            set_cell(selected.getCellByPosition(column_index_value, row_index), value)
    return {"sheet": sheet_name, "range": range_name}


def execute_spreadsheet_set(request: dict[str, Any], root: Path, input_value: dict[str, Any]) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    if resource_type(path) != "spreadsheet.workbook":
        raise BridgeError("unsupported_resource: spreadsheet update requires a workbook")
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    with OfficeSession() as office:
        document = office.open(path, read_only=False)
        try:
            applied = apply_spreadsheet_set(document, input_value)
            document.calculateAll()
            if file_revision(path) != before:
                return ensure_revision(request, file_revision(path)) or rejection(request, "stale_revision", "Workbook changed.", before, [], "query_resource")
            document.store()
            sheet = document.getSheets().getByName(applied["sheet"])
            readback = range_payload(sheet, applied["range"], document)
        finally:
            document.close(True)
    after = file_revision(path)
    return completed(
        request,
        before,
        after,
        [{"ref": request["targetRef"], "kind": "updated", "beforeRevision": before, "afterRevision": after}],
        ["formula_readback", "recalculated_value", "file_hash_readback", sha256_bytes(json.dumps(readback, sort_keys=True).encode("utf-8"))],
        reversible=True,
    )


def parse_color(value: Any, key: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise BridgeError(f"invalid_format: {key} must use #RRGGBB")
    return int(value[1:], 16)


def validate_spreadsheet_format(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value or not set(value) <= SPREADSHEET_FORMAT_KEYS:
        raise BridgeError("invalid_format: unsupported or empty spreadsheet format")
    for key in ("bold", "wrapText", "optimalWidth"):
        if key in value and not isinstance(value[key], bool):
            raise BridgeError(f"invalid_format: {key} must be boolean")
    for key in ("fontColor", "fillColor"):
        if key in value:
            parse_color(value[key], key)
    if "fontSize" in value and (
        not isinstance(value["fontSize"], (int, float))
        or isinstance(value["fontSize"], bool)
        or not 6 <= float(value["fontSize"]) <= 72
    ):
        raise BridgeError("invalid_format: fontSize must be between 6 and 72")
    if value.get("horizontalAlignment") not in {None, "left", "center", "right"}:
        raise BridgeError("invalid_format: horizontalAlignment is unsupported")
    if "numberFormat" in value and (
        not isinstance(value["numberFormat"], str)
        or not value["numberFormat"]
        or len(value["numberFormat"]) > 120
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in value["numberFormat"]
        )
    ):
        raise BridgeError("invalid_format: numberFormat must be bounded text")
    for key in ("columnWidth", "rowHeight"):
        if key in value and (
            not isinstance(value[key], int)
            or isinstance(value[key], bool)
            or not 200 <= value[key] <= 20_000
        ):
            raise BridgeError(f"invalid_format: {key} must be between 200 and 20000")
    return value


def apply_spreadsheet_format(
    office: OfficeSession, document: Any, selected: Any, value: dict[str, Any]
) -> None:
    if "bold" in value:
        selected.CharWeight = office.uno.getConstantByName(
            "com.sun.star.awt.FontWeight.BOLD"
            if value["bold"]
            else "com.sun.star.awt.FontWeight.NORMAL"
        )
    if "fontColor" in value:
        selected.CharColor = parse_color(value["fontColor"], "fontColor")
    if "fontSize" in value:
        selected.CharHeight = float(value["fontSize"])
    if "fillColor" in value:
        selected.CellBackColor = parse_color(value["fillColor"], "fillColor")
    if "horizontalAlignment" in value:
        selected.HoriJustify = office.uno.Enum(
            "com.sun.star.table.CellHoriJustify",
            value["horizontalAlignment"].upper(),
        )
    if "numberFormat" in value:
        locale = office.uno.createUnoStruct("com.sun.star.lang.Locale")
        locale.Language = "en"
        locale.Country = "US"
        formats = document.getNumberFormats()
        key = formats.queryKey(value["numberFormat"], locale, True)
        if key == -1:
            key = formats.addNew(value["numberFormat"], locale)
        selected.NumberFormat = key
    if "wrapText" in value:
        selected.IsTextWrapped = value["wrapText"]
    if value.get("optimalWidth"):
        selected.Columns.OptimalWidth = True
    if "columnWidth" in value:
        selected.Columns.Width = value["columnWidth"]
    if "rowHeight" in value:
        selected.Rows.Height = value["rowHeight"]


def execute_spreadsheet_format(
    request: dict[str, Any], root: Path, input_value: dict[str, Any]
) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    if resource_type(path) != "spreadsheet.workbook":
        raise BridgeError("unsupported_resource: spreadsheet formatting requires a workbook")
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    sheet_name = required_string(input_value, "sheet", 200)
    range_name = required_string(input_value, "range", 100).upper()
    parse_range(range_name)
    format_value = validate_spreadsheet_format(input_value.get("format"))
    with OfficeSession() as office:
        document = office.open(path, read_only=False)
        try:
            sheets = document.getSheets()
            if not sheets.hasByName(sheet_name):
                raise BridgeError("sheet_not_found: workbook does not contain the requested sheet")
            if file_revision(path) != before:
                return ensure_revision(request, file_revision(path)) or rejection(
                    request, "stale_revision", "Workbook changed.", before, [], "query_resource"
                )
            selected = sheets.getByName(sheet_name).getCellRangeByName(range_name)
            apply_spreadsheet_format(office, document, selected, format_value)
            document.store()
            readback = range_payload(sheets.getByName(sheet_name), range_name, document)["format"]
        finally:
            document.close(True)
    after = file_revision(path)
    return completed(
        request,
        before,
        after,
        [{"ref": request["targetRef"], "kind": "updated", "beforeRevision": before, "afterRevision": after}],
        [
            "format_readback",
            "file_hash_readback",
            sha256_bytes(json.dumps(readback, sort_keys=True).encode("utf-8")),
        ],
        reversible=True,
    )


def apply_spreadsheet_merge(document: Any, input_value: dict[str, Any]) -> dict[str, Any]:
    if set(input_value) != {"sheet", "range", "merged"}:
        raise BridgeError("invalid_merge: fields are invalid")
    sheet_name = required_string(input_value, "sheet", 200)
    range_name = required_string(input_value, "range", 100).upper()
    parse_range(range_name)
    merged = input_value.get("merged")
    if not isinstance(merged, bool):
        raise BridgeError("invalid_merge: merged must be boolean")
    sheets = document.getSheets()
    if not sheets.hasByName(sheet_name):
        raise BridgeError("sheet_not_found: workbook does not contain the requested sheet")
    selected = sheets.getByName(sheet_name).getCellRangeByName(range_name)
    selected.merge(merged)
    return {"sheet": sheet_name, "range": range_name, "merged": merged}


def execute_spreadsheet_merge(
    request: dict[str, Any], root: Path, input_value: dict[str, Any]
) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    if resource_type(path) != "spreadsheet.workbook":
        raise BridgeError("unsupported_resource: range merge requires a workbook")
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    with OfficeSession() as office:
        document = office.open(path, read_only=False)
        try:
            if file_revision(path) != before:
                return ensure_revision(request, file_revision(path)) or rejection(
                    request, "stale_revision", "Workbook changed.", before, [], "query_resource"
                )
            applied = apply_spreadsheet_merge(document, input_value)
            document.store()
            selected = document.getSheets().getByName(applied["sheet"]).getCellRangeByName(
                applied["range"]
            )
            readback = {
                **applied,
                "merged": bool(selected.getCellByPosition(0, 0).IsMerged),
            }
        finally:
            document.close(True)
    after = file_revision(path)
    return completed(
        request,
        before,
        after,
        [{"ref": request["targetRef"], "kind": "updated", "beforeRevision": before, "afterRevision": after}],
        [
            "merge_readback",
            "file_hash_readback",
            sha256_bytes(json.dumps(readback, sort_keys=True).encode("utf-8")),
        ],
        reversible=True,
    )


def validate_table_input(input_value: dict[str, Any]) -> dict[str, Any]:
    if not set(input_value) <= {"sheet", "name", "range", "hasHeaders", "autoFilter"}:
        raise BridgeError("invalid_table: unsupported table field")
    sheet_name = required_string(input_value, "sheet", 200)
    name = required_string(input_value, "name", 100)
    if not TABLE_NAME.fullmatch(name):
        raise BridgeError("invalid_table_name: use a letter or underscore followed by letters, digits, dots or underscores")
    range_name = required_string(input_value, "range", 100).upper()
    start_column, start_row, end_column, end_row = parse_range(
        range_name, max_cells=1_000_000
    )
    if start_row == end_row or start_column == end_column:
        raise BridgeError("invalid_table_range: a table needs at least two rows and two columns")
    has_headers = input_value.get("hasHeaders", True)
    auto_filter = input_value.get("autoFilter", True)
    if not isinstance(has_headers, bool) or not isinstance(auto_filter, bool):
        raise BridgeError("invalid_table: hasHeaders and autoFilter must be boolean")
    return {
        "sheet": sheet_name,
        "name": name,
        "range": range_name,
        "hasHeaders": has_headers,
        "autoFilter": auto_filter,
    }


def apply_spreadsheet_table(document: Any, input_value: dict[str, Any]) -> dict[str, Any]:
    value = validate_table_input(input_value)
    sheets = document.getSheets()
    if not sheets.hasByName(value["sheet"]):
        raise BridgeError("sheet_not_found: workbook does not contain the requested sheet")
    selected = sheets.getByName(value["sheet"]).getCellRangeByName(value["range"])
    ranges = database_ranges(document)
    if ranges.hasByName(value["name"]):
        ranges.removeByName(value["name"])
    ranges.addNewByName(value["name"], selected.RangeAddress)
    table = ranges.getByName(value["name"])
    table.ContainsHeader = value["hasHeaders"]
    table.AutoFilter = value["autoFilter"]
    table.KeepFormats = True
    readback = next(
        item for item in table_payload(document, value["sheet"]) if item["name"] == value["name"]
    )
    return readback


def validate_condition_formula(value: Any, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise BridgeError(f"invalid_conditional_format: {label} must be a number or formula")
    text = str(value)
    if not text or len(text) > 256 or any(
        ord(character) < 32 or ord(character) == 127 for character in text
    ):
        raise BridgeError(f"invalid_conditional_format: {label} must be bounded text")
    if text.startswith("="):
        validate_formula(text)
    elif not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", text):
        raise BridgeError(f"invalid_conditional_format: {label} must be numeric or a safe formula")
    return text


def validate_conditional_format_input(input_value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"sheet", "range", "operator", "formula1", "formula2", "style", "replace"}
    if not set(input_value) <= allowed:
        raise BridgeError("invalid_conditional_format: unsupported field")
    sheet_name = required_string(input_value, "sheet", 200)
    range_name = required_string(input_value, "range", 100).upper()
    parse_range(range_name)
    operator = input_value.get("operator")
    if operator not in CONDITION_OPERATORS:
        raise BridgeError("invalid_conditional_format: operator is unsupported")
    formula1 = validate_condition_formula(input_value.get("formula1"), "formula1")
    formula2 = input_value.get("formula2")
    if operator == "between":
        formula2 = validate_condition_formula(formula2, "formula2")
    elif formula2 is not None:
        raise BridgeError("invalid_conditional_format: formula2 is only valid for between")
    style = validate_spreadsheet_format(input_value.get("style"))
    if set(style) - {"bold", "fontColor", "fontSize", "fillColor", "numberFormat"}:
        raise BridgeError("invalid_conditional_format: style contains a range-only format")
    replace = input_value.get("replace", True)
    if not isinstance(replace, bool):
        raise BridgeError("invalid_conditional_format: replace must be boolean")
    return {
        "sheet": sheet_name,
        "range": range_name,
        "operator": operator,
        "formula1": formula1,
        "formula2": formula2,
        "style": style,
        "replace": replace,
    }


def apply_spreadsheet_conditional_format(
    office: OfficeSession, document: Any, input_value: dict[str, Any]
) -> dict[str, Any]:
    value = validate_conditional_format_input(input_value)
    sheets = document.getSheets()
    if not sheets.hasByName(value["sheet"]):
        raise BridgeError("sheet_not_found: workbook does not contain the requested sheet")
    selected = sheets.getByName(value["sheet"]).getCellRangeByName(value["range"])
    style_families = document.getStyleFamilies()
    cell_styles = style_families.getByName("CellStyles")
    style_digest = hashlib.sha256(
        json.dumps(value["style"], sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    style_name = f"Wiii_CF_{style_digest}"
    if not cell_styles.hasByName(style_name):
        cell_styles.insertByName(
            style_name, document.createInstance("com.sun.star.style.CellStyle")
        )
    apply_spreadsheet_format(
        office, document, cell_styles.getByName(style_name), value["style"]
    )
    entries = selected.ConditionalFormat
    if value["replace"]:
        entries.clear()
    properties = [
        office.property(
            "Operator",
            office.uno.Enum(
                "com.sun.star.sheet.ConditionOperator",
                CONDITION_OPERATORS[value["operator"]],
            ),
        ),
        office.property("Formula1", value["formula1"]),
        office.property("SourcePosition", selected.getCellByPosition(0, 0).CellAddress),
        office.property("StyleName", style_name),
    ]
    if value["formula2"] is not None:
        properties.append(office.property("Formula2", value["formula2"]))
    entries.addNew(tuple(properties))
    selected.ConditionalFormat = entries
    return {
        "sheet": value["sheet"],
        "range": value["range"],
        "operator": value["operator"],
        "styleName": style_name,
        "entries": conditional_format_payload(document, selected),
    }


def validate_pivot_input(input_value: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "sourceSheet",
        "sourceRange",
        "outputSheet",
        "outputCell",
        "name",
        "rows",
        "columns",
        "data",
    }
    if set(input_value) != expected:
        raise BridgeError("invalid_pivot: fields are invalid")
    source_sheet = required_string(input_value, "sourceSheet", 200)
    source_range = required_string(input_value, "sourceRange", 100).upper()
    parse_range(source_range, max_cells=1_000_000)
    output_sheet = required_string(input_value, "outputSheet", 200)
    output_cell = required_string(input_value, "outputCell", 100).upper()
    start_column, start_row, end_column, end_row = parse_range(output_cell)
    if (start_column, start_row) != (end_column, end_row):
        raise BridgeError("invalid_pivot: outputCell must identify one cell")
    name = required_string(input_value, "name", 100)
    if not TABLE_NAME.fullmatch(name):
        raise BridgeError("invalid_pivot_name: use a letter or underscore followed by letters, digits, dots or underscores")
    rows = input_value.get("rows")
    columns = input_value.get("columns")
    data = input_value.get("data")
    for label, values in (("rows", rows), ("columns", columns)):
        if not isinstance(values, list) or len(values) > 8 or any(
            not isinstance(item, str) or not item or len(item) > 100 for item in values
        ):
            raise BridgeError(f"invalid_pivot: {label} must contain bounded field names")
    if not isinstance(data, list) or not 1 <= len(data) <= 16:
        raise BridgeError("invalid_pivot: data must contain between 1 and 16 fields")
    normalized_data: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict) or set(item) != {"field", "function"}:
            raise BridgeError("invalid_pivot: each data field needs field and function")
        field = required_string(item, "field", 100)
        function = item.get("function")
        if function not in PIVOT_FUNCTIONS:
            raise BridgeError("invalid_pivot: data function is unsupported")
        normalized_data.append({"field": field, "function": function})
    all_fields = [*rows, *columns, *(item["field"] for item in normalized_data)]
    if len({field.casefold() for field in all_fields}) != len(all_fields):
        raise BridgeError("invalid_pivot: a field can only have one orientation")
    return {
        "sourceSheet": source_sheet,
        "sourceRange": source_range,
        "outputSheet": output_sheet,
        "outputCell": output_cell,
        "name": name,
        "rows": rows,
        "columns": columns,
        "data": normalized_data,
    }


def apply_spreadsheet_pivot(
    office: OfficeSession, document: Any, input_value: dict[str, Any]
) -> dict[str, Any]:
    value = validate_pivot_input(input_value)
    sheets = document.getSheets()
    if not sheets.hasByName(value["sourceSheet"]) or not sheets.hasByName(
        value["outputSheet"]
    ):
        raise BridgeError("sheet_not_found: workbook does not contain a pivot sheet")
    source_sheet = sheets.getByName(value["sourceSheet"])
    output_sheet = sheets.getByName(value["outputSheet"])
    source = source_sheet.getCellRangeByName(value["sourceRange"])
    headers = [str(item) for item in source.getDataArray()[0]]
    if any(not header for header in headers) or len(set(headers)) != len(headers):
        raise BridgeError("invalid_pivot_source: source headers must be non-empty and unique")
    header_indexes = {header: index for index, header in enumerate(headers)}
    requested_fields = [
        *value["rows"],
        *value["columns"],
        *(item["field"] for item in value["data"]),
    ]
    missing = [field for field in requested_fields if field not in header_indexes]
    if missing:
        raise BridgeError("pivot_field_not_found: " + ", ".join(missing))
    tables = output_sheet.getDataPilotTables()
    if tables.hasByName(value["name"]):
        tables.removeByName(value["name"])
    descriptor = tables.createDataPilotDescriptor()
    descriptor.setSourceRange(source.RangeAddress)
    fields = descriptor.getDataPilotFields()
    orientation = "com.sun.star.sheet.DataPilotFieldOrientation"
    for field_name in value["rows"]:
        fields.getByIndex(header_indexes[field_name]).Orientation = office.uno.Enum(
            orientation, "ROW"
        )
    for field_name in value["columns"]:
        fields.getByIndex(header_indexes[field_name]).Orientation = office.uno.Enum(
            orientation, "COLUMN"
        )
    for item in value["data"]:
        field = fields.getByIndex(header_indexes[item["field"]])
        field.Function = office.uno.Enum(
            "com.sun.star.sheet.GeneralFunction", PIVOT_FUNCTIONS[item["function"]]
        )
        field.Orientation = office.uno.Enum(orientation, "DATA")
    output = output_sheet.getCellRangeByName(value["outputCell"]).getCellByPosition(0, 0)
    tables.insertNewByName(value["name"], output.CellAddress, descriptor)
    tables.getByName(value["name"]).refresh()
    readback = next(
        item for item in pivot_payload(output_sheet) if item["name"] == value["name"]
    )
    return {
        **value,
        "outputRange": readback["outputRange"],
        "fields": readback["fields"],
    }


def execute_spreadsheet_object(
    request: dict[str, Any],
    root: Path,
    input_value: dict[str, Any],
    apply: Any,
    evidence: str,
) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    if resource_type(path) != "spreadsheet.workbook":
        raise BridgeError("unsupported_resource: spreadsheet object requires a workbook")
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    with OfficeSession() as office:
        document = office.open(path, read_only=False)
        try:
            if file_revision(path) != before:
                return ensure_revision(request, file_revision(path)) or rejection(
                    request, "stale_revision", "Workbook changed.", before, [], "query_resource"
                )
            readback = apply(office, document, input_value)
            document.calculateAll()
            document.store()
        finally:
            document.close(True)
    after = file_revision(path)
    return completed(
        request,
        before,
        after,
        [{"ref": request["targetRef"], "kind": "updated", "beforeRevision": before, "afterRevision": after}],
        [evidence, "file_hash_readback", sha256_bytes(json.dumps(readback, sort_keys=True).encode("utf-8"))],
        reversible=True,
    )


def apply_spreadsheet_chart(
    office: OfficeSession, document: Any, input_value: dict[str, Any]
) -> dict[str, Any]:
    sheet_name = required_string(input_value, "sheet", 200)
    chart_name = required_string(input_value, "name", 100)
    if not re.fullmatch(r"[A-Za-z0-9 _-]+", chart_name):
        raise BridgeError("invalid_chart_name: use letters, digits, spaces, underscores or hyphens")
    source_range = required_string(input_value, "sourceRange", 100).upper()
    anchor_range = required_string(input_value, "anchorRange", 100).upper()
    parse_range(source_range)
    parse_range(anchor_range)
    chart_type = input_value.get("chartType")
    if chart_type not in CHART_TYPES:
        raise BridgeError("invalid_chart_type: unsupported chart type")
    title = input_value.get("title", "")
    if not isinstance(title, str) or len(title) > 200 or any(
        ord(character) < 32 or ord(character) == 127 for character in title
    ):
        raise BridgeError("invalid_chart_title: title must be bounded text")
    has_legend = input_value.get("hasLegend", True)
    if not isinstance(has_legend, bool):
        raise BridgeError("invalid_chart_legend: hasLegend must be boolean")
    sheets = document.getSheets()
    if not sheets.hasByName(sheet_name):
        raise BridgeError("sheet_not_found: workbook does not contain the requested sheet")
    sheet = sheets.getByName(sheet_name)
    source = sheet.getCellRangeByName(source_range)
    anchor = sheet.getCellRangeByName(anchor_range)
    position = anchor.Position
    size = anchor.Size
    rectangle = office.uno.createUnoStruct("com.sun.star.awt.Rectangle")
    rectangle.X = position.X
    rectangle.Y = position.Y
    rectangle.Width = max(size.Width, 5000)
    rectangle.Height = max(size.Height, 3500)
    charts = sheet.getCharts()
    for existing_name in list(charts.getElementNames()):
        existing = charts.getByName(existing_name)
        existing_embedded = existing.getEmbeddedObject()
        existing_title = ""
        if bool(getattr(existing_embedded, "HasMainTitle", False)):
            existing_title = str(existing_embedded.getTitle().String)
        if existing_name == chart_name or (title and existing_title == title):
            charts.removeByName(existing_name)
    charts.addNewByName(
        chart_name,
        rectangle,
        (source.RangeAddress,),
        True,
        True,
    )
    embedded = charts.getByName(chart_name).getEmbeddedObject()
    diagram = embedded.createInstance(CHART_TYPES[chart_type])
    if chart_type in {"bar", "column"}:
        diagram.Vertical = chart_type == "bar"
    embedded.setDiagram(diagram)
    embedded.HasLegend = has_legend
    if title:
        embedded.HasMainTitle = True
        embedded.getTitle().String = title
    return {"sheet": sheet_name, "name": chart_name}


def execute_spreadsheet_chart_upsert(
    request: dict[str, Any], root: Path, input_value: dict[str, Any]
) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    if resource_type(path) != "spreadsheet.workbook":
        raise BridgeError("unsupported_resource: chart creation requires a workbook")
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    with OfficeSession() as office:
        document = office.open(path, read_only=False)
        try:
            if file_revision(path) != before:
                return ensure_revision(request, file_revision(path)) or rejection(
                    request, "stale_revision", "Workbook changed.", before, [], "query_resource"
                )
            applied = apply_spreadsheet_chart(office, document, input_value)
            document.store()
            readback = chart_payload(document.getSheets().getByName(applied["sheet"]))
        finally:
            document.close(True)
    after = file_revision(path)
    return completed(
        request,
        before,
        after,
        [{"ref": request["targetRef"], "kind": "updated", "beforeRevision": before, "afterRevision": after}],
        [
            "chart_readback",
            "file_hash_readback",
            sha256_bytes(json.dumps(readback, sort_keys=True).encode("utf-8")),
        ],
        reversible=True,
    )


def apply_spreadsheet_layout(
    document: Any, input_value: dict[str, Any]
) -> dict[str, Any]:
    expected = {
        "sheet",
        "printRange",
        "orientation",
        "fitWidth",
        "fitHeight",
        "margin",
    }
    if not set(input_value) <= expected:
        raise BridgeError("invalid_layout: unsupported layout field")
    sheet_name = required_string(input_value, "sheet", 200)
    print_range = required_string(input_value, "printRange", 100).upper()
    parse_range(print_range, max_cells=1_000_000)
    orientation = input_value.get("orientation")
    if orientation not in {"portrait", "landscape"}:
        raise BridgeError("invalid_layout: orientation is unsupported")
    fit_width = input_value.get("fitWidth")
    fit_height = input_value.get("fitHeight")
    if (
        not isinstance(fit_width, int)
        or isinstance(fit_width, bool)
        or not 1 <= fit_width <= 10
        or not isinstance(fit_height, int)
        or isinstance(fit_height, bool)
        or not 0 <= fit_height <= 10
    ):
        raise BridgeError("invalid_layout: fit dimensions are out of range")
    margin = input_value.get("margin", 800)
    if (
        not isinstance(margin, int)
        or isinstance(margin, bool)
        or not 0 <= margin <= 5000
    ):
        raise BridgeError("invalid_layout: margin must be between 0 and 5000")
    sheets = document.getSheets()
    if not sheets.hasByName(sheet_name):
        raise BridgeError("sheet_not_found: workbook does not contain the requested sheet")
    sheet = sheets.getByName(sheet_name)
    selected = sheet.getCellRangeByName(print_range)
    sheet.setPrintAreas((selected.RangeAddress,))
    page_styles = document.getStyleFamilies().getByName("PageStyles")
    style_name = "Wiii_" + hashlib.sha256(sheet_name.encode("utf-8")).hexdigest()[:12]
    if not page_styles.hasByName(style_name):
        page_styles.insertByName(
            style_name, document.createInstance("com.sun.star.style.PageStyle")
        )
    sheet.PageStyle = style_name
    style = page_styles.getByName(style_name)
    landscape = orientation == "landscape"
    if bool(style.IsLandscape) != landscape:
        width = int(style.Width)
        style.Width = int(style.Height)
        style.Height = width
    style.IsLandscape = landscape
    style.ScaleToPagesX = fit_width
    style.ScaleToPagesY = fit_height
    style.LeftMargin = margin
    style.RightMargin = margin
    style.TopMargin = margin
    style.BottomMargin = margin
    style.HeaderIsOn = False
    style.FooterIsOn = False
    return {
        "sheet": sheet_name,
        "printRange": print_range,
        "orientation": orientation,
        "fitWidth": fit_width,
        "fitHeight": fit_height,
        "margin": margin,
    }


def execute_spreadsheet_layout(
    request: dict[str, Any], root: Path, input_value: dict[str, Any]
) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    if resource_type(path) != "spreadsheet.workbook":
        raise BridgeError("unsupported_resource: sheet layout requires a workbook")
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    with OfficeSession() as office:
        document = office.open(path, read_only=False)
        try:
            if file_revision(path) != before:
                return ensure_revision(request, file_revision(path)) or rejection(
                    request, "stale_revision", "Workbook changed.", before, [], "query_resource"
                )
            readback = apply_spreadsheet_layout(document, input_value)
            document.store()
        finally:
            document.close(True)
    after = file_revision(path)
    return completed(
        request,
        before,
        after,
        [{"ref": request["targetRef"], "kind": "updated", "beforeRevision": before, "afterRevision": after}],
        [
            "page_layout_readback",
            "file_hash_readback",
            sha256_bytes(json.dumps(readback, sort_keys=True).encode("utf-8")),
        ],
        reversible=True,
    )


def execute_spreadsheet_batch(
    request: dict[str, Any], root: Path, input_value: dict[str, Any]
) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    if resource_type(path) != "spreadsheet.workbook":
        raise BridgeError("unsupported_resource: spreadsheet batch requires a workbook")
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    operations = input_value.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 64:
        raise BridgeError("invalid_batch: operations must contain between 1 and 64 items")
    with OfficeSession() as office:
        document = office.open(path, read_only=False)
        touched_ranges: list[tuple[str, str]] = []
        touched_charts: set[str] = set()
        touched_tables: set[str] = set()
        touched_pivots: set[str] = set()
        touched_conditions: list[tuple[str, str]] = []
        touched_cells = 0
        try:
            for raw_operation in operations:
                operation = require_object(raw_operation, "batch_operation")
                operation_type = required_string(operation, "type", 20)
                payload = {key: value for key, value in operation.items() if key != "type"}
                if operation_type == "set":
                    if set(operation) != {"type", "sheet", "range", "cells"}:
                        raise BridgeError("invalid_batch: set operation fields are invalid")
                    applied = apply_spreadsheet_set(document, payload)
                    touched_ranges.append((applied["sheet"], applied["range"]))
                elif operation_type == "format":
                    if set(operation) != {"type", "sheet", "range", "format"}:
                        raise BridgeError("invalid_batch: format operation fields are invalid")
                    sheet_name = required_string(payload, "sheet", 200)
                    range_name = required_string(payload, "range", 100).upper()
                    start_column, start_row, end_column, end_row = parse_range(range_name)
                    format_value = validate_spreadsheet_format(payload.get("format"))
                    sheets = document.getSheets()
                    if not sheets.hasByName(sheet_name):
                        raise BridgeError(
                            "sheet_not_found: workbook does not contain the requested sheet"
                        )
                    selected = sheets.getByName(sheet_name).getCellRangeByName(range_name)
                    apply_spreadsheet_format(office, document, selected, format_value)
                    touched_ranges.append((sheet_name, range_name))
                    touched_cells += (end_column - start_column + 1) * (
                        end_row - start_row + 1
                    )
                elif operation_type == "merge":
                    if set(operation) != {"type", "sheet", "range", "merged"}:
                        raise BridgeError("invalid_batch: merge operation fields are invalid")
                    applied = apply_spreadsheet_merge(document, payload)
                    touched_ranges.append((applied["sheet"], applied["range"]))
                    start_column, start_row, end_column, end_row = parse_range(
                        applied["range"]
                    )
                    touched_cells += (end_column - start_column + 1) * (
                        end_row - start_row + 1
                    )
                elif operation_type == "table":
                    allowed = {"type", "sheet", "name", "range", "hasHeaders", "autoFilter"}
                    if not set(operation) <= allowed:
                        raise BridgeError("invalid_batch: table operation fields are invalid")
                    applied = apply_spreadsheet_table(document, payload)
                    touched_tables.add(applied["sheet"])
                    start_column, start_row, end_column, end_row = parse_range(
                        applied["range"], max_cells=1_000_000
                    )
                    touched_cells += (end_column - start_column + 1) * (
                        end_row - start_row + 1
                    )
                elif operation_type == "conditionalFormat":
                    allowed = {
                        "type",
                        "sheet",
                        "range",
                        "operator",
                        "formula1",
                        "formula2",
                        "style",
                        "replace",
                    }
                    if not set(operation) <= allowed:
                        raise BridgeError(
                            "invalid_batch: conditional format operation fields are invalid"
                        )
                    applied = apply_spreadsheet_conditional_format(
                        office, document, payload
                    )
                    touched_conditions.append((applied["sheet"], applied["range"]))
                    start_column, start_row, end_column, end_row = parse_range(applied["range"])
                    touched_cells += (end_column - start_column + 1) * (
                        end_row - start_row + 1
                    )
                elif operation_type == "pivot":
                    if set(operation) != {
                        "type",
                        "sourceSheet",
                        "sourceRange",
                        "outputSheet",
                        "outputCell",
                        "name",
                        "rows",
                        "columns",
                        "data",
                    }:
                        raise BridgeError("invalid_batch: pivot operation fields are invalid")
                    applied = apply_spreadsheet_pivot(office, document, payload)
                    touched_pivots.add(applied["outputSheet"])
                    start_column, start_row, end_column, end_row = parse_range(
                        applied["sourceRange"], max_cells=1_000_000
                    )
                    touched_cells += (end_column - start_column + 1) * (
                        end_row - start_row + 1
                    )
                elif operation_type == "chart":
                    allowed = {
                        "type",
                        "sheet",
                        "name",
                        "sourceRange",
                        "anchorRange",
                        "chartType",
                        "title",
                        "hasLegend",
                    }
                    if not set(operation) <= allowed:
                        raise BridgeError("invalid_batch: chart operation fields are invalid")
                    applied = apply_spreadsheet_chart(office, document, payload)
                    touched_charts.add(applied["sheet"])
                elif operation_type == "layout":
                    allowed = {
                        "type",
                        "sheet",
                        "printRange",
                        "orientation",
                        "fitWidth",
                        "fitHeight",
                        "margin",
                    }
                    if not set(operation) <= allowed:
                        raise BridgeError("invalid_batch: layout operation fields are invalid")
                    apply_spreadsheet_layout(document, payload)
                else:
                    raise BridgeError("invalid_batch: unsupported operation type")
                if operation_type == "set":
                    start_column, start_row, end_column, end_row = parse_range(
                        required_string(payload, "range", 100).upper()
                    )
                    touched_cells += (end_column - start_column + 1) * (
                        end_row - start_row + 1
                    )
                if touched_cells > 8192:
                    raise BridgeError("batch_too_large: at most 8192 touched cells are allowed")
            document.calculateAll()
            if file_revision(path) != before:
                return ensure_revision(request, file_revision(path)) or rejection(
                    request, "stale_revision", "Workbook changed.", before, [], "query_resource"
                )
            document.store()
            readback: dict[str, Any] = {
                "operations": len(operations),
                "ranges": [],
                "charts": [],
                "tables": [],
                "conditionalFormats": [],
                "pivots": [],
            }
            for sheet_name, range_name in touched_ranges[-16:]:
                sheet = document.getSheets().getByName(sheet_name)
                payload = range_payload(sheet, range_name, document)
                readback["ranges"].append(
                    {
                        "sheet": sheet_name,
                        "range": range_name,
                        "digest": sha256_bytes(
                            json.dumps(payload, sort_keys=True).encode("utf-8")
                        ),
                    }
                )
            for sheet_name in sorted(touched_charts):
                readback["charts"].extend(
                    chart_payload(document.getSheets().getByName(sheet_name))
                )
            for sheet_name in sorted(touched_tables):
                readback["tables"].extend(table_payload(document, sheet_name))
            for sheet_name, range_name in touched_conditions[-16:]:
                selected = document.getSheets().getByName(sheet_name).getCellRangeByName(
                    range_name
                )
                readback["conditionalFormats"].append(
                    {
                        "sheet": sheet_name,
                        "range": range_name,
                        "entries": conditional_format_payload(document, selected),
                    }
                )
            for sheet_name in sorted(touched_pivots):
                readback["pivots"].extend(
                    pivot_payload(document.getSheets().getByName(sheet_name))
                )
        finally:
            document.close(True)
    after = file_revision(path)
    return completed(
        request,
        before,
        after,
        [{"ref": request["targetRef"], "kind": "updated", "beforeRevision": before, "afterRevision": after}],
        [
            "batch_readback",
            "file_hash_readback",
            sha256_bytes(json.dumps(readback, sort_keys=True).encode("utf-8")),
        ],
        reversible=True,
    )


def execute_spreadsheet_export(request: dict[str, Any], root: Path, input_value: dict[str, Any]) -> dict[str, Any]:
    path = path_from_ref(root, required_string(request, "targetRef", 512))
    before = file_revision(path)
    if stale := ensure_revision(request, before):
        return stale
    if input_value.get("format") != "pdf":
        raise BridgeError("unsupported_format: spreadsheet export currently supports PDF")
    destination = resolve_relative(root, required_string(input_value, "destination", 240), must_exist=False)
    if destination.suffix.lower() != ".pdf":
        raise BridgeError("invalid_destination: PDF export requires a .pdf destination")
    if destination.exists():
        return rejection(request, "resource_exists", "Export destination already exists.", before, ["destination_exists"], "choose_destination")
    handle, temporary_name = tempfile.mkstemp(prefix=".wiii-work-", suffix=".pdf", dir=destination.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        with OfficeSession() as office:
            document = office.open(path, read_only=True)
            try:
                if file_revision(path) != before:
                    return ensure_revision(request, file_revision(path)) or rejection(request, "stale_revision", "Workbook changed.", before, [], "query_resource")
                document.storeToURL(
                    office.uno.systemPathToFileUrl(str(temporary)),
                    (office.property("FilterName", "calc_pdf_Export"),),
                )
            finally:
                document.close(True)
        if destination.exists() or destination.is_symlink():
            return rejection(request, "resource_exists", "Export destination already exists.", before, ["destination_exists"], "choose_destination")
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    exported_revision = file_revision(destination)
    destination_ref = encode_ref(destination.relative_to(root).as_posix())
    return completed(
        request,
        before,
        file_revision(path),
        [{"ref": destination_ref, "kind": "created", "beforeRevision": None, "afterRevision": exported_revision}],
        ["export_hash_readback"],
        reversible=False,
    )


def execute(request: dict[str, Any]) -> dict[str, Any]:
    root = project_root()
    if required_string(request, "capabilityVersion", 32) != "1":
        raise BridgeError("capability_version_mismatch: refresh the Work Plane descriptor")
    input_value = require_object(request.get("input"), "input")
    capability_id = required_string(request, "capabilityId", 120)
    if capability_id == "spreadsheet.workbook.create" and request.get("targetRef") == PROJECT_REF:
        return execute_spreadsheet_create(request, root, input_value)
    if capability_id == "project.file.create" and request.get("targetRef") == PROJECT_REF:
        return execute_create(request, root, input_value)
    if capability_id == "project.file.patch_text":
        return execute_patch(request, root, input_value)
    if capability_id == "project.file.rename":
        return execute_rename(request, root, input_value)
    if capability_id == "spreadsheet.range.set":
        return execute_spreadsheet_set(request, root, input_value)
    if capability_id == "spreadsheet.range.format":
        return execute_spreadsheet_format(request, root, input_value)
    if capability_id == "spreadsheet.range.merge":
        return execute_spreadsheet_merge(request, root, input_value)
    if capability_id == "spreadsheet.table.upsert":
        return execute_spreadsheet_object(
            request,
            root,
            input_value,
            lambda _office, document, value: apply_spreadsheet_table(document, value),
            "table_readback",
        )
    if capability_id == "spreadsheet.conditional_format.upsert":
        return execute_spreadsheet_object(
            request,
            root,
            input_value,
            apply_spreadsheet_conditional_format,
            "conditional_format_readback",
        )
    if capability_id == "spreadsheet.pivot.upsert":
        return execute_spreadsheet_object(
            request,
            root,
            input_value,
            apply_spreadsheet_pivot,
            "pivot_readback",
        )
    if capability_id == "spreadsheet.chart.upsert":
        return execute_spreadsheet_chart_upsert(request, root, input_value)
    if capability_id == "spreadsheet.sheet.layout":
        return execute_spreadsheet_layout(request, root, input_value)
    if capability_id == "spreadsheet.batch":
        return execute_spreadsheet_batch(request, root, input_value)
    if capability_id == "spreadsheet.export":
        return execute_spreadsheet_export(request, root, input_value)
    raise BridgeError("unsupported_capability: refresh the Work Plane descriptor")


def read_request() -> dict[str, Any]:
    payload = sys.stdin.buffer.read(512 * 1024 + 1)
    if len(payload) > 512 * 1024:
        raise BridgeError("request_too_large: Work Plane request exceeds 524288 bytes")
    try:
        value = json.loads(payload or b"{}")
    except json.JSONDecodeError as error:
        raise BridgeError("invalid_json: Work Plane request is malformed") from error
    return require_object(value, "request")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"describe", "query", "execute"}:
        print(json.dumps({"status": "error", "code": "usage"}), file=sys.stderr)
        return 64
    try:
        request = read_request()
        if sys.argv[1] == "describe":
            response = {"status": "ok", "descriptor": describe()}
        elif sys.argv[1] == "query":
            response = {"status": "ok", "result": query(request)}
        else:
            response = {"status": "ok", "result": execute(request)}
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return 0
    except BridgeError as error:
        print(json.dumps({"status": "error", "code": str(error)[:1000]}), file=sys.stderr)
        return 2
    except Exception as error:
        print(json.dumps({"status": "error", "code": "work_plane_failed", "detail": str(error)[:1000]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
