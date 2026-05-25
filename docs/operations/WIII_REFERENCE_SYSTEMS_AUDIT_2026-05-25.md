# Wiii Reference Systems Audit

Status: Active research baseline

Owner: Project leadership

Created: 2026-05-25

Related issue: #640

## Purpose

Wiii should not keep evolving by isolated bug repair. Before the next runtime
slice, maintainers should compare Wiii's active flows against strong external
systems and then decide which contracts, signals, and harnesses Wiii needs.

This document records the reference set and the local clone workspace for that
audit. It is not an endorsement to copy architecture wholesale.

## Local Research Workspace

External reference repositories are cloned outside tracked Wiii source:

```text
.Codex/external/reference-systems/
```

This path is intentionally ignored by `.gitignore` through the existing
`.Codex/` rule. Do not vendor external repositories into Wiii history.

Current local clones:

| Project | Local path | Remote | Local HEAD | Clone mode | Why it is first-class |
|---|---|---|---|---|---|
| OpenHuman | `.Codex/external/reference-systems/openhuman` | `https://github.com/tinyhumansai/openhuman.git` | `5e31d3e` | shallow, sparse, no submodules | living memory, local-first knowledge vault, typed integrations, background context ingestion, personal-agent UX |
| OpenClaw | `.Codex/external/reference-systems/openclaw` | `https://github.com/openclaw/openclaw.git` | `d967760` | shallow, sparse | gateway control plane, multi-channel routing, operator commands, session isolation, tool permission defaults, trace/doctor UX |

If deeper audit needs full history or extra directories, expand the sparse
checkout locally. Do not commit cloned files, generated indexes, or local audit
scratch output.

## First-Class References

### OpenHuman

Focused audit:

- `WIII_OPENHUMAN_REFERENCE_AUDIT_2026-05-26.md`: source snapshot,
  memory/context findings, Wiii Context Provenance Ledger v1 requirements, and
  non-copy boundaries.

Use OpenHuman to audit Wiii's Living, Data, and Host ambitions.

What to study:

- local versus managed-service boundary
- Memory Tree and Obsidian-style vault as inspectable memory
- integration data ingestion and auto-fetch loops
- typed tools for external connections
- token compression before LLM calls
- personal-agent onboarding and always-on continuity

Wiii questions:

- Can Wiii memory become inspectable enough that failures are not hidden inside
  a black-box embedding store?
- Should uploaded documents, LMS context, and long-term memory all produce a
  human-readable context ledger?
- Where does Wiii currently mix local/dev/prod/managed assumptions in a way
  that makes debugging harder?

### OpenClaw

Focused audit:

- `WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md`: source snapshot,
  control-plane findings, Wiii Runtime Flow Ledger v1 requirements, and Chat
  Baseline Acceptance Harness requirements.

Use OpenClaw to audit Wiii's Host, Core, and governance surfaces.

What to study:

- gateway as a control plane for sessions, channels, tools, and events
- multi-channel routing into isolated agents/workspaces
- operator commands such as status, trace, reset, compact, usage, and restart
- default-deny or sandboxed handling for non-main sessions
- channel pairing and allowlist safety
- doctor/trace style diagnostics for risky runtime config

Wiii questions:

- Should Wiii expose an operator-grade turn/session trace before a UI dashboard?
- Which Wiii host actions should be denied by default outside explicit LMS
  preview/apply flows?
- How should Wiii separate normal chat, LMS embed, Pointy, and future channels
  as different host surfaces rather than one generic chat path?

## Supporting References

These remain useful, but they are second-order for the immediate Wiii problem:

| Project | Best use for Wiii |
|---|---|
| Dify | workflow/app orchestration, RAG pipeline visibility, model/app logs |
| Open WebUI | self-hosted chat UX, users, permissions, plugin surface, telemetry |
| LibreChat | practical multi-model chat, agents, artifacts, MCP-style integrations |
| RAGFlow | document understanding, chunking, citations, source-grounded document answers |
| Haystack | explicit RAG/agent pipelines and component boundaries |
| Langfuse, Phoenix, Opik | LLM observability, traces, datasets, evals, prompt/version discipline |
| Activepieces, n8n | connector/workflow automation and approval/audit boundaries |

Clone these only when the audit needs source-level comparison. For many
questions, primary docs and targeted file reads are enough.

## Audit Method

For each reference system, capture only durable findings:

1. Product role: which Wiii layer or flow it informs.
2. Flow map: ingress, routing, tools, memory, output, finalization.
3. Contract map: typed inputs/outputs, permissions, fail-closed boundaries.
4. Observability map: trace IDs, operator commands, logs, evals, replay.
5. What Wiii should adopt.
6. What Wiii should explicitly avoid.

Keep findings in this doc or a follow-up issue. Do not leave durable reasoning
only in chat or local scratch notes.

## Immediate Next Step

Before implementing more Wiii runtime fixes, run a focused audit of:

1. OpenHuman memory/context ingestion.
2. OpenClaw gateway/session/tool/trace model.
3. Wiii chat stream baseline.

The output should directly shape the next Wiii implementation slice:

```text
Runtime Flow Ledger + Chat Baseline Acceptance Harness
```

That slice should answer, for every normal chat turn:

- what host surface sent the turn
- which route/lane Wiii selected
- which context and memory sources were included
- whether tools were bound or suppressed
- which provider/model was used
- which SSE events reached the client
- whether finalization and persistence completed
