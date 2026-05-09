# Wiii Spec Kit Workflow

Status: Active

Owner: Project leadership

Last updated: 2026-05-09

## Purpose

Spec Kit gives Wiii a shared, reviewable workflow for large changes that involve runtime contracts, memory, RAG/CRAG, provider routing, Pointy/host control, streaming UX, auth, tenant isolation, or multi-agent implementation.

Use it to reduce ambiguity before many agents edit the same system. Do not use it as ceremony for small isolated fixes.

## Current Setup

Wiii is initialized with Spec Kit v0.8.7 for Codex skills:

- `.specify/memory/constitution.md`: Wiii-specific governing principles.
- `.specify/templates/`: official Spec Kit spec, plan, tasks, checklist, and constitution templates.
- `.specify/scripts/powershell/`: official PowerShell helpers for Windows development.
- `.agents/skills/speckit-*/SKILL.md`: Codex-invokable Spec Kit workflow skills.
- `.specify/init-options.json`: Codex skills mode, PowerShell scripts, sequential branch numbering.
- `.specify/integration.json`: installed Codex integration state.

The repository `.gitignore` tracks only `.agents/skills/speckit-*` and keeps the existing local `.agents/skills/*` skill library ignored.

## When To Use

Use Spec Kit for:

- Removing or redesigning runtime foundations such as LangChain/LangGraph compatibility, WiiiRunner contracts, provider routing, or native tool execution.
- Changing semantic memory, long-term memory, episodic recall, identity, persona, compacting, or tenant isolation.
- Changing SSE V3, streaming finalization, sync/stream parity, latency telemetry, or UI-visible chat lifecycle.
- Expanding Pointy, host bridge, LMS control, browser-like actions, voice, document/video context, visuals, simulations, or code studio.
- Splitting work across multiple agents or PRs where contracts need to be stable before implementation.

Prefer direct issue-to-PR workflow for:

- Small test additions.
- Narrow bug fixes with clear scope and low architectural risk.
- Documentation corrections that do not change governance or product behavior.

## Recommended Flow

1. Start with the issue.
   Link the GitHub issue or create one before non-trivial work.

2. Update or verify the constitution when rules change.
   Use `$speckit-constitution` for governance, architectural principles, or quality gates.

3. Write the behavior spec.
   Use `$speckit-specify` to capture user-visible behavior, non-goals, constraints, and acceptance criteria.

4. Create the technical plan.
   Use `$speckit-plan` to define contracts, data flow, risk, rollback, observability, and verification.

5. Split implementation.
   Use `$speckit-tasks` to produce dependency-ordered tasks suitable for parallel agents with disjoint write scopes.

6. Implement only after the artifacts agree.
   Use `$speckit-implement` or normal Codex work once the spec, plan, and tasks are coherent.

7. Keep artifacts honest.
   If implementation changes the design, update the spec or plan in the same PR.

## Wiii-Specific Checks

Every Spec Kit plan for Wiii should answer:

- Which runtime contract changes: message, tool, provider, router, supervisor, memory, RAG, host action, or SSE?
- What is the user-visible behavior in localhost web, Tauri desktop, and LMS embed?
- How will Wiii avoid silent waiting during slow work?
- What telemetry proves where latency is spent?
- What fails closed when provider, tool, host bridge, memory, or RAG fails?
- What tenant/org boundary is affected?
- What tests guard sync and streaming parity?
- What rollback is safe if production behavior regresses?

## Verification Baseline

For Spec Kit scaffolding or governance-only changes:

```powershell
specify check
git diff --check
git status --short
```

For implementation PRs, use the path-specific verification commands in `AGENTS.md` and include exact results in the PR.
