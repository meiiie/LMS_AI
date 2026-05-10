# Agent Coordination Watcher

This folder contains the local watcher used by the observer agent for Wiii x LMS
coordination. It is intentionally small and depends only on Python 3 plus the
GitHub CLI.

Default mode is read-only. Add `--apply` only when you intentionally want to
write labels, issues, or comments through `gh`.

## Quick Start

```bash
python scripts/agent_coordination/watcher.py --help
python scripts/agent_coordination/watcher.py bootstrap-labels
python scripts/agent_coordination/watcher.py bootstrap-labels --apply
python scripts/agent_coordination/watcher.py create-thread --title "Wiii x LMS teacher doc-to-course integration"
python scripts/agent_coordination/watcher.py digest
```

## Comment Marker

The watcher parses comments that contain:

```markdown
<!-- wiii-lms-sync:v1 -->
ROLE: wiii-agent
STATUS: blocked
BLOCKER: What is blocked.
NEEDS_OTHER_REPO: owner/repo
EVIDENCE: Link, command, screenshot, or smoke result.
NEXT_PATCH: One concrete next patch.
```

## Supported Repos

The default config watches:

- `meiiie/wiii`
- `linhlinhlin/LMS_hohulili`

Copy `coordination_config.example.json` if you need a custom fork or a different
central issue.
