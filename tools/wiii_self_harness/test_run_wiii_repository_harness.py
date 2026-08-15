from __future__ import annotations

import re
import unittest
from pathlib import Path

import run_wiii_repository_harness as harness


WORKFLOW = harness.REPO_ROOT / ".github/workflows/wiii-repository-harness.yml"


class RepositoryHarnessTests(unittest.TestCase):
    def test_pr_profile_passes_for_repository(self) -> None:
        result = harness.run_harness("pr")
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("wiii.repository-harness.v2", result.schema)
        self.assertGreaterEqual(len(result.checks), 5)

    def test_link_normalization(self) -> None:
        self.assertEqual("docs/README.md", harness._normalize_link_target("docs/README.md#start"))
        self.assertEqual("path with spaces.md", harness._normalize_link_target("<path with spaces.md>"))
        self.assertEqual("", harness._normalize_link_target("..."))
        self.assertEqual("", harness._normalize_link_target("…"))

    def test_workflow_is_bounded_read_only_and_pinned(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("timeout-minutes: 12", text)
        self.assertRegex(text, r"(?m)^permissions:\s*\n  contents: read$")
        self.assertNotRegex(text, r"(?m)^\s+[A-Za-z-]+: write$")
        for action, ref in re.findall(r"uses:\s*([^@\s]+)@([^\s]+)", text):
            with self.subTest(action=action):
                self.assertRegex(ref, r"^[0-9a-f]{40}$")

    def test_release_profile_adds_git_gate(self) -> None:
        result = harness.run_harness("release")
        self.assertEqual("release-git-state", result.checks[-1].check)
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
