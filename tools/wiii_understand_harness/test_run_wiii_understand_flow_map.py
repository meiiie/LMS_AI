import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import run_wiii_understand_flow_map as flow_map


def _file(path: str, language: str = "python", category: str = "code") -> dict:
    return {"path": path, "language": language, "fileCategory": category, "sizeLines": 10}


class WiiiUnderstandFlowMapTests(unittest.TestCase):
    def test_select_profile_files_keeps_primary_and_support_separate(self) -> None:
        scan = {
            "files": [
                _file("maritime-ai-service/app/services/chat_stream_coordinator.py"),
                _file("wiii-desktop/tsconfig.json", "json", "config"),
                _file("docs/operations/unrelated.md", "markdown", "docs"),
            ]
        }

        selected = flow_map.select_profile_files(scan, flow_map.FLOW_PROFILES["chat-baseline"])

        self.assertEqual(
            ["maritime-ai-service/app/services/chat_stream_coordinator.py"],
            [item["path"] for item in selected.primary],
        )
        self.assertEqual(["wiii-desktop/tsconfig.json"], [item["path"] for item in selected.support])

    def test_select_profile_files_fails_when_profile_has_no_primary_match(self) -> None:
        scan = {"files": [_file("docs/operations/unrelated.md", "markdown", "docs")]}

        with self.assertRaisesRegex(ValueError, "selected no primary"):
            flow_map.select_profile_files(scan, flow_map.FLOW_PROFILES["lms-document-preview"])

    def test_build_summary_reports_guardrails_and_import_hubs(self) -> None:
        scan = {
            "totalFiles": 3,
            "estimatedComplexity": "small",
            "stats": {"filesScanned": 3},
            "files": [
                _file("a.py"),
                _file("b.py"),
                _file("pyproject.toml", "toml", "config"),
            ],
        }
        selected = flow_map.SelectedFiles(
            primary=(_file("a.py"), _file("b.py")),
            support=(_file("pyproject.toml", "toml", "config"),),
        )
        import_output = {
            "stats": {"filesScanned": 3, "filesWithImports": 2, "totalEdges": 2},
            "importMap": {"a.py": ["b.py"], "b.py": ["a.py"]},
        }

        summary = flow_map.build_summary(
            profile_name="sample",
            profile=flow_map.FlowProfile(description="sample", include=("*.py",)),
            scan_result=scan,
            selected=selected,
            import_output=import_output,
            scan_path=flow_map.REPO_ROOT / ".understand-anything/tmp/scan.json",
            import_input_path=flow_map.REPO_ROOT / ".understand-anything/tmp/input.json",
            import_output_path=flow_map.REPO_ROOT / ".understand-anything/tmp/import.json",
        )

        self.assertFalse(summary["guardrails"]["runtime_dependency"])
        self.assertFalse(summary["guardrails"]["llm_graph_workflow"])
        self.assertEqual(3, summary["selection"]["total_file_count"])
        self.assertEqual("a.py", summary["import_map"]["top_outbound"][0]["path"])
        self.assertEqual(1, summary["import_map"]["top_inbound"][0]["edge_count"])

    def test_run_flow_map_reuses_scan_input_and_writes_ignored_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            plugin_root = temp / "plugin"
            skill_dir = plugin_root / "skills" / "understand"
            skill_dir.mkdir(parents=True)
            (skill_dir / "scan-project.mjs").write_text("// fake", encoding="utf-8")
            (skill_dir / "extract-import-map.mjs").write_text("// fake", encoding="utf-8")
            scan_input = temp / "scan.json"
            scan_input.write_text(
                json.dumps(
                    {
                        "totalFiles": 2,
                        "estimatedComplexity": "small",
                        "stats": {"filesScanned": 2},
                        "files": [
                            _file("maritime-ai-service/app/services/chat_stream_coordinator.py"),
                            _file("wiii-desktop/tsconfig.json", "json", "config"),
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_run(args: list[str], *, cwd: Path, verbose: bool) -> None:
                output_path = Path(args[-1])
                output_path.write_text(
                    json.dumps(
                        {
                            "scriptCompleted": True,
                            "stats": {"filesScanned": 2, "filesWithImports": 1, "totalEdges": 1},
                            "importMap": {
                                "maritime-ai-service/app/services/chat_stream_coordinator.py": [
                                    "wiii-desktop/tsconfig.json"
                                ]
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            with mock.patch.object(flow_map, "run_command", side_effect=fake_run):
                summary = flow_map.run_flow_map(
                    profile_name="chat-baseline",
                    plugin_root=plugin_root,
                    output_dir=temp / "out",
                    scan_input=scan_input,
                    verbose=False,
                )

        self.assertEqual("chat-baseline", summary["profile"])
        self.assertEqual(2, summary["selection"]["total_file_count"])
        self.assertTrue(summary["summary_path"].endswith("wiii-flow-map-chat-baseline-summary.json"))

    def test_list_profiles_cli_does_not_require_reference_clone(self) -> None:
        with mock.patch("sys.stdout") as stdout:
            result = flow_map.main(["--list-profiles"])

        self.assertEqual(0, result)
        written = "".join(call.args[0] for call in stdout.write.call_args_list if call.args)
        self.assertIn("chat-baseline", written)


if __name__ == "__main__":
    unittest.main()
