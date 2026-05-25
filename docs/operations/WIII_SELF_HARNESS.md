# Wiii Self-Harness

Status: Active

Owner: Project leadership

Last updated: 2026-05-25

## Purpose

Wiii Self-Harness is the repository-owned harness for Wiii's active system
contracts. It keeps critical product paths explicit, typed where possible, and
traceable to living runtime, test, docs, and CI evidence.

This harness does not replace backend unit tests, desktop tests, browser smoke
tests, or LMS product E2E. It is the thin deterministic layer that answers:

```text
Do Wiii's critical contracts still have named scenarios, evidence files, and
focused verification commands?
```

## Current Scenarios

The canonical manifest lives at:

```text
tools/wiii_self_harness/wiii_self_harness_scenarios.json
```

The system-level operating map lives at:

```text
docs/operations/WIII_SYSTEM_CONTROL_PLANE.md
```

The first scenario set covers the active product risk surface:

- `system-flow-observability-map`: the control-plane map stays available and
  describes the active flow-monitoring ladder.
- `memory-context-provenance-ledger`: Runtime Flow Ledger embeds privacy-safe
  context provenance for conversation, document, memory, and host sources.
- `visual-tool-capability-sync`: visual intent selects the right tool lane.
- `code-studio-scaffold-boundary`: Code Studio scaffold fallback is typed and
  policy-gated.
- `lms-document-preview-apply-approval`: uploaded LMS documents use preview and
  approval before apply.
- `host-action-audit-route`: host action audit remains route-available and
  token-safe.
- `frontend-visual-code-studio-shell`: VisualBlock and CodeStudioPanel avoid
  raw output drift and keep app previews host-owned.

## How To Run

From the repository root:

```powershell
python tools/wiii_self_harness/run_wiii_self_harness.py
python -m unittest discover -s tools/wiii_self_harness -p "test_*.py"
```

To list scenarios:

```powershell
python tools/wiii_self_harness/run_wiii_self_harness.py --list
```

To emit JSON for another tool:

```powershell
python tools/wiii_self_harness/run_wiii_self_harness.py --json
```

## How It Works

The runner is standard-library Python. It validates:

- manifest identity and version
- required scenario IDs
- lowercase kebab-case scenario IDs
- scenario status, Wiii layer, risk, owner, contract, and invariants
- repo-relative evidence paths
- required tokens inside each evidence file
- verification command and purpose metadata

It fails closed when a scenario is malformed, a file disappears, or a required
contract token no longer exists in the evidence file.

## Extension Rules

Add or change a scenario when a product-critical contract becomes important
enough that losing it would create high-risk debt.

Each scenario should include:

- the active Wiii layer affected by the contract
- the risk level
- the concrete contract in one sentence
- invariants that should stay true
- runtime, test, docs, or CI evidence files
- focused verification commands

Do not add broad directory checks or vague evidence. A path should prove a
specific contract, not merely show that a subsystem exists.

## CI

`.github/workflows/wiii-self-harness.yml` runs the manifest validator and its
unit tests when harness files, workflow files, or the covered product contracts
change. The workflow uses only Python and does not install backend or desktop
dependencies.

## Non-Goals

Wiii Self-Harness does not:

- execute LMS mutations
- replace upload DOCX/PDF preview/apply E2E
- inspect production environments
- replace CodeRabbit, branch protection, or human review
- guarantee every possible architectural debt is gone

It is a deterministic guardrail for active product-path contracts. Runtime
behavior still needs the focused verification commands listed by each scenario
and the normal issue, branch, PR, risk, rollback, and review process.

Use `WIII_SYSTEM_CONTROL_PLANE.md` before adding new scenarios. If the issue is
not mapped to a Wiii layer, active runtime flow, and observable signal, it is
not ready to become a durable Self-Harness scenario.
