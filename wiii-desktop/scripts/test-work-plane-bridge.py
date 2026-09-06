#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path

BRIDGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src-tauri"
    / "src"
    / "neko"
    / "computer"
    / "image"
    / "work_plane_bridge.py"
)
SPEC = importlib.util.spec_from_file_location("wiii_work_plane_bridge", BRIDGE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load Work Plane bridge")
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)


class WorkPlaneBridgeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="wiii-work-plane-test-")
        self.root = Path(self.temporary.name)
        self.previous_root = os.environ.get("WIII_WORK_PLANE_ROOT")
        os.environ["WIII_WORK_PLANE_ROOT"] = str(self.root)
        (self.root / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        (self.root / "unchanged.bin").write_bytes(b"\x00\x01\x02")

    def tearDown(self) -> None:
        if self.previous_root is None:
            os.environ.pop("WIII_WORK_PLANE_ROOT", None)
        else:
            os.environ["WIII_WORK_PLANE_ROOT"] = self.previous_root
        self.temporary.cleanup()

    def transaction(
        self,
        capability: str,
        target: str,
        revision: str,
        input_value: dict[str, object],
        operation: str = "operation-1",
    ) -> dict[str, object]:
        return {
            "requestId": operation,
            "environmentId": "must-not-be-returned",
            "projectId": "project-test",
            "capabilityId": capability,
            "capabilityVersion": "1",
            "targetRef": target,
            "ifRevision": revision,
            "input": input_value,
        }

    def test_descriptor_is_source_backed_and_provider_neutral(self) -> None:
        descriptor = BRIDGE.describe()
        self.assertEqual(descriptor["protocolVersion"], BRIDGE.PROTOCOL_VERSION)
        self.assertEqual(descriptor["sourceAuthority"], "source_application")
        self.assertEqual(descriptor["root"]["ref"], BRIDGE.PROJECT_REF)
        encoded = str(descriptor).lower()
        self.assertNotIn("docker", encoded)
        self.assertNotIn("/workspace/project", encoded)
        self.assertNotIn("environmentid", encoded)

    def test_file_slice_preserves_unrelated_source_state(self) -> None:
        before_unchanged = (self.root / "unchanged.bin").read_bytes()
        root_revision = BRIDGE.root_resource(self.root)["revision"]
        with self.assertRaisesRegex(BRIDGE.BridgeError, "parent_not_found"):
            BRIDGE.execute(
                self.transaction(
                    "project.file.create",
                    BRIDGE.PROJECT_REF,
                    root_revision,
                    {"path": "drafts/result.txt", "content": "first line\nsecond line\n"},
                )
            )
        (self.root / "drafts").mkdir()
        root_revision = BRIDGE.root_resource(self.root)["revision"]
        created = BRIDGE.execute(
            self.transaction(
                "project.file.create",
                BRIDGE.PROJECT_REF,
                root_revision,
                {"path": "drafts/result.txt", "content": "first line\nsecond line\n"},
            )
        )
        self.assertEqual(created["outcome"], "completed")
        created_ref = created["changes"][0]["ref"]
        queried = BRIDGE.query(
            {
                "resourceRef": created_ref,
                "view": "content",
                "offset": 0,
                "maxBytes": 4096,
            }
        )
        self.assertEqual(queried["data"]["content"], "first line\nsecond line\n")
        revision = queried["resource"]["revision"]
        patched = BRIDGE.execute(
            self.transaction(
                "project.file.patch_text",
                created_ref,
                revision,
                {"expectedText": "second line", "replacement": "verified line"},
                "operation-2",
            )
        )
        self.assertEqual(patched["outcome"], "completed")
        renamed = BRIDGE.execute(
            self.transaction(
                "project.file.rename",
                created_ref,
                patched["afterRevision"],
                {"destination": "drafts/final.txt"},
                "operation-3",
            )
        )
        self.assertEqual(renamed["outcome"], "completed")
        self.assertFalse((self.root / "drafts" / "result.txt").exists())
        self.assertEqual(
            (self.root / "drafts" / "final.txt").read_text(encoding="utf-8"),
            "first line\nverified line\n",
        )
        self.assertEqual((self.root / "unchanged.bin").read_bytes(), before_unchanged)

    def test_stale_and_escape_requests_make_no_source_change(self) -> None:
        source = self.root / "notes.txt"
        resource = BRIDGE.file_resource(self.root, source)
        before = source.read_bytes()
        stale = BRIDGE.execute(
            self.transaction(
                "project.file.patch_text",
                resource["ref"],
                "sha256:" + "0" * 64,
                {"expectedText": "alpha", "replacement": "changed"},
            )
        )
        self.assertEqual(stale["outcome"], "rejected")
        self.assertEqual(stale["code"], "stale_revision")
        self.assertEqual(source.read_bytes(), before)
        root_revision = BRIDGE.root_resource(self.root)["revision"]
        with self.assertRaisesRegex(BRIDGE.BridgeError, "path_escape"):
            BRIDGE.execute(
                self.transaction(
                    "project.file.create",
                    BRIDGE.PROJECT_REF,
                    root_revision,
                    {"path": "../escaped.txt", "content": "no"},
                )
            )
        self.assertFalse(self.root.parent.joinpath("escaped.txt").exists())

    def test_empty_files_and_formula_policy_are_explicit(self) -> None:
        root_revision = BRIDGE.root_resource(self.root)["revision"]
        created = BRIDGE.execute(
            self.transaction(
                "project.file.create",
                BRIDGE.PROJECT_REF,
                root_revision,
                {"path": "empty.txt", "content": ""},
            )
        )
        self.assertEqual(created["outcome"], "completed")
        self.assertEqual((self.root / "empty.txt").read_bytes(), b"")
        BRIDGE.validate_formula("=SUM(B2:C2)")
        BRIDGE.validate_formula("=SUMIFS(C2:C10;A2:A10;E2;B2:B10;F2)")
        BRIDGE.validate_formula("=INDEX(C2:C10;MATCH(E2;A2:A10;0))")
        with self.assertRaisesRegex(BRIDGE.BridgeError, "unsafe_formula"):
            BRIDGE.validate_formula('=WEBSERVICE("https://example.invalid")')

    def test_spreadsheet_structure_and_format_inputs_are_bounded(self) -> None:
        self.assertEqual(
            BRIDGE.validate_sheet_names(["SalesData", "Analysis", "Dashboard"]),
            ["SalesData", "Analysis", "Dashboard"],
        )
        with self.assertRaisesRegex(BRIDGE.BridgeError, "unique"):
            BRIDGE.validate_sheet_names(["SalesData", "salesdata"])
        with self.assertRaisesRegex(BRIDGE.BridgeError, "valid Excel"):
            BRIDGE.validate_sheet_names(["Bad/Name"])
        value = BRIDGE.validate_spreadsheet_format(
            {
                "bold": True,
                "fillColor": "#17365D",
                "fontColor": "#FFFFFF",
                "numberFormat": "#,##0.00",
                "horizontalAlignment": "center",
                "optimalWidth": True,
            }
        )
        self.assertEqual(value["fillColor"], "#17365D")
        with self.assertRaisesRegex(BRIDGE.BridgeError, "fontColor"):
            BRIDGE.validate_spreadsheet_format({"fontColor": "navy"})
        with self.assertRaisesRegex(BRIDGE.BridgeError, "unsupported or empty"):
            BRIDGE.validate_spreadsheet_format({"shadow": True})
        self.assertEqual(BRIDGE.parse_range("A1:M73", max_cells=1_000_000), (0, 0, 12, 72))
        with self.assertRaisesRegex(BRIDGE.BridgeError, "range_too_large"):
            BRIDGE.parse_range("A1:M73")

    def test_advanced_spreadsheet_objects_have_bounded_generic_inputs(self) -> None:
        table = BRIDGE.validate_table_input(
            {
                "sheet": "SalesData",
                "name": "Sales_Table",
                "range": "A1:M73",
                "hasHeaders": True,
                "autoFilter": True,
            }
        )
        self.assertEqual(table["range"], "A1:M73")
        with self.assertRaisesRegex(BRIDGE.BridgeError, "table_name"):
            BRIDGE.validate_table_input(
                {"sheet": "SalesData", "name": "1 bad", "range": "A1:M73"}
            )
        condition = BRIDGE.validate_conditional_format_input(
            {
                "sheet": "Analysis",
                "range": "G2:G5",
                "operator": "less_than",
                "formula1": 0,
                "style": {"bold": True, "fontColor": "#9C0006", "fillColor": "#FFC7CE"},
            }
        )
        self.assertEqual(condition["formula1"], "0")
        with self.assertRaisesRegex(BRIDGE.BridgeError, "formula2"):
            BRIDGE.validate_conditional_format_input(
                {
                    "sheet": "Analysis",
                    "range": "G2:G5",
                    "operator": "between",
                    "formula1": 0,
                    "style": {"bold": True},
                }
            )
        pivot = BRIDGE.validate_pivot_input(
            {
                "sourceSheet": "SalesData",
                "sourceRange": "A1:M73",
                "outputSheet": "Pivot",
                "outputCell": "A1",
                "name": "Sales_By_Region",
                "rows": ["Region"],
                "columns": [],
                "data": [
                    {"field": "Revenue", "function": "sum"},
                    {"field": "Profit", "function": "sum"},
                ],
            }
        )
        self.assertEqual(pivot["data"][1]["function"], "sum")
        with self.assertRaisesRegex(BRIDGE.BridgeError, "one orientation"):
            BRIDGE.validate_pivot_input(
                {
                    **pivot,
                    "data": [{"field": "Region", "function": "count"}],
                }
            )

    def test_children_query_is_bounded_and_uses_opaque_refs(self) -> None:
        result = BRIDGE.query(
            {
                "resourceRef": BRIDGE.PROJECT_REF,
                "view": "children",
                "offset": 0,
                "maxItems": 1,
            }
        )
        self.assertEqual(len(result["items"]), 1)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["items"][0]["ref"].startswith("work:file:"))
        self.assertNotIn(str(self.root), str(result))

    def test_protected_files_are_neither_listed_nor_addressable(self) -> None:
        paths = [".env", "nested/.ENV.production", ".git/config", ".ssh/id_ed25519", "signing.pfx"]
        original_revision = BRIDGE.directory_revision(self.root)
        for relative in paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private-fixture", encoding="utf-8")
        result = BRIDGE.query({"resourceRef": BRIDGE.PROJECT_REF, "view": "children"})
        self.assertEqual({item["name"] for item in result["items"]}, {"notes.txt", "unchanged.bin"})
        self.assertEqual(BRIDGE.directory_revision(self.root), original_revision)
        source = BRIDGE.file_resource(self.root, self.root / "notes.txt")
        for relative in paths:
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(BRIDGE.BridgeError, "protected_path"):
                    BRIDGE.query({"resourceRef": BRIDGE.encode_ref(relative), "view": "content"})
                operations = [
                    self.transaction("project.file.create", BRIDGE.PROJECT_REF, original_revision, {"path": relative, "content": "overwrite"}),
                    self.transaction("project.file.patch_text", BRIDGE.encode_ref(relative), original_revision, {"expectedText": "private-fixture", "replacement": "overwrite"}),
                    self.transaction("project.file.rename", source["ref"], source["revision"], {"destination": relative}),
                ]
                for operation in operations:
                    with self.assertRaisesRegex(BRIDGE.BridgeError, "protected_path"):
                        BRIDGE.execute(operation)
                self.assertEqual((self.root / relative).read_text(encoding="utf-8"), "private-fixture")

    @unittest.skipUnless(os.name == "posix", "POSIX executable permissions")
    def test_text_patch_preserves_executable_mode(self) -> None:
        source = self.root / "notes.txt"
        source.chmod(0o750)
        resource = BRIDGE.file_resource(self.root, source)
        result = BRIDGE.execute(self.transaction(
            "project.file.patch_text", resource["ref"], resource["revision"],
            {"expectedText": "alpha", "replacement": "updated"},
        ))
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o750)
        self.assertEqual(source.read_text(encoding="utf-8"), "updated\nbeta\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
