# Wiii Repository Harness

**Status:** Canonical
**Implementation:** `tools/wiii_self_harness/`
**Workflow:** `.github/workflows/wiii-repository-harness.yml`

## Purpose

The repository harness protects a small set of durable, cross-cutting
contracts. It does not attempt to simulate the whole product or replace focused
tests. A harness result should tell a maintainer what is broken directly, not
require interpreting a chain of generated plans, handoffs, attestations, and
recovery reports.

## Contract layers

| Layer | What the harness proves | Where behavior is proved |
| --- | --- | --- |
| Product identity | Canonical docs and brand assets exist; Wiii is positioned as an AI workbench | Documentation and brand verification tests |
| Release integrity | `VERSION`, package metadata, Tauri, Cargo, UI, and changelog agree | Release CLI tests and desktop build |
| Documentation | Local links in canonical entry points resolve | Repository harness |
| Runtime evidence | Registered live probes remain guarded, private, attributable, and connected to workflows | Registry validators and credentialed workflows |
| Product behavior | Not duplicated here | Backend, desktop, adapter, E2E, and ACP suites |

## Profiles

- `pr` is deterministic, read-only, network-free, and suitable for every pull
  request.
- `release` includes all PR checks plus a clean worktree and exact
  `wiii-v<version>` tag check. Use it on the release commit.

```powershell
python tools/wiii_self_harness/run_wiii_repository_harness.py --profile pr
python tools/wiii_self_harness/run_wiii_repository_harness.py --profile pr --json --out artifacts/wiii-repository-harness.json
```

## Runtime evidence registry

The registry is retained because it maps claims to actual workflows, probes,
schemas, privacy rules, freshness limits, contract tests, and guarded live-run
flags. The harness validates the registry structure; it does not fabricate live
evidence when credentials or external systems are unavailable.

An external integration may be `not run` or `blocked` with a precise reason.
It may not be reported as successful from synthetic output. LMS, Composio, and
social-channel evidence are adapter-specific rows, not global Wiii product
identity.

## Change policy

Add a harness check only when all of these are true:

1. It protects a repository-wide invariant.
2. Failure can identify the broken source directly.
3. It is deterministic and read-only in the PR profile.
4. A focused test or registry row cannot express the contract better.

Avoid generators whose only input is another generated harness artifact. Use a
single JSON sidecar for automation and preserve raw test or live-probe output as
the source evidence.
