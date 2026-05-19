# Wiii Repository Recovery Audit - 2026-05-19

Status: Active local recovery record

Owner: Project leadership

Purpose: document how the large local WIP was preserved and how the repository
was returned to a clean, reviewable state.

Tracking issue: https://github.com/meiiie/wiii/issues/397

## Decision

The large WIP branch was not pushed to `main`.

Reason: the work touched backend runtime, frontend UX, voice, visual artifacts,
LMS contracts, deploy files, tests, and docs at the same time. That is not a
reviewable or safely deployable unit.

## Main Sync

`main` was synchronized in a separate product worktree:

- Worktree label: `product-main-worktree`
- Branch: `main`
- Current commit: `181e43c4`
- Status: clean against `origin/main`

Verify the concrete local path with:

```powershell
git worktree list
git -C <product-main-worktree-path> status -sb
```

No WIP was merged into `main`.

## WIP Preservation

The full dirty investigation worktree was preserved with:

```powershell
git stash push -u -m "wiii-full-surface-wip-before-repo-cleanup-2026-05-19"
```

Verified stash entry:

```text
0f88ba8632984b450c7157817756245ccc766ebb On codex/full-surface-test-2026-05-13: wiii-full-surface-wip-before-repo-cleanup-2026-05-19
```

The positional ref was `stash@{0}` at capture time, but future recovery should
use the commit hash or re-resolve the entry by message because stash positions
can change.

Snapshot scale before stashing:

- 161 modified tracked files
- 35 untracked paths
- 8,584 insertions
- 1,603 deletions

The stash is the recovery source for future focused PRs.

## What Was Cleaned

The working tree was returned to a clean state without deleting the WIP:

- no tracked WIP remains in the active cleanup branch
- no untracked WIP remains in the active cleanup branch
- the large mixed change set is isolated in a named stash
- local `main` is synced in the product worktree

## Current Cleanup Branch

The active cleanup branch is:

```text
codex/repo-harness-cleanup-2026-05-19
```

This branch should contain only documentation and codebase-harness work unless a
maintainer explicitly expands its scope.

## How To Recover A Slice

Inspect the stash:

```powershell
git stash list --format="%H %gd %s"
git stash show --stat 0f88ba8632984b450c7157817756245ccc766ebb
```

Restore one file or folder into a new focused branch:

```powershell
git switch -c codex/<focused-slice>
git checkout 0f88ba8632984b450c7157817756245ccc766ebb -- path/to/file
```

Do not apply the whole stash into a PR branch unless the goal is explicitly to
recreate the full investigation state.

## Recommended Slice Order

1. Raw provider tool-call JSON guard.
2. Markdown and chat presentation repair.
3. LMS document authoring approval contract.
4. Voice mode stabilization.
5. Visual and Code Studio quality contracts.
6. Deploy and production config.
7. Additional docs and cleanup.

Each slice should have focused tests, risk notes, and rollback notes.

## Safety Notes

- No deploy was performed.
- No merge was performed.
- No WIP changes were deleted.
- No known provider secret was committed.
- Future PRs must still run their own secret and diff hygiene checks.
