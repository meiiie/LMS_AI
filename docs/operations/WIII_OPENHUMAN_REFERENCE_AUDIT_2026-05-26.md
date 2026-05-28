# Wiii OpenHuman Reference Audit

Status: Active reference audit

Owner: Project leadership

Created: 2026-05-26

Related issue: #660

Related docs:

- `docs/operations/WIII_REFERENCE_SYSTEMS_AUDIT_2026-05-25.md`
- `docs/operations/WIII_SYSTEM_CONTROL_PLANE.md`
- `docs/operations/WIII_SELF_HARNESS.md`
- `docs/operations/WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md`

## Purpose

This audit turns OpenHuman source-level observations into concrete Wiii
memory/context observability requirements. The goal is not to copy OpenHuman.
The goal is to make Wiii's chat, document, memory, and host context path
inspectable enough that maintainers can tell which sources shaped a turn
without reading raw prompts or uploaded documents.

## Source Snapshot

External code was originally inspected from an ignored local research
workspace. The current refreshed OpenHuman reference clone used for later
Composio/Connections audit work is kept outside the Wiii repository:

```text
../_reference_research/openhuman
```

Do not treat legacy `.Codex/` exploratory folders as canonical Wiii source
inputs or committed artifacts.

| Field | Value |
|---|---|
| Remote | `https://github.com/tinyhumansai/openhuman.git` |
| Original inspected commit | `0e4729e7f2214f2fed3e23fb8d352018c0393fb3` |
| Original commit date | `2026-05-25T23:33:40+05:30` |
| Original commit title | `test(memory): serialize tests that drive the process-global memory client (#2649)` |
| Refreshed local commit for 2026-05-28 Composio pass | `6736467` |
| Local checkout note | Later Composio/Connections checks use the external `_reference_research/openhuman` clone without vendoring it into Wiii. |
| Clone mode | shallow, sparse, no submodules |

Primary OpenHuman areas reviewed:

- `README.md`
- `gitbooks/README.md`
- `gitbooks/developing/architecture/agent-harness.md`
- `docs/agent-subagent-tool-flow.md`
- `gitbooks/features/obsidian-wiki/memory-tree.md`

## Audit Summary

OpenHuman's strongest lesson for Wiii is not a specific storage engine. It is
the product discipline of making context ingestion, memory recall, and tool
output compression visible as harness contracts:

- local versus managed-service boundaries are explicit
- every connected source feeds a provenance-aware Memory Tree pipeline
- agent turns load memory context with citations instead of hiding it in an
  uninspectable prompt blob
- heavy extraction and summarization happens after the hot path
- sub-agents inherit bounded parent context and return compact results instead
  of becoming nested full sessions
- the desktop memory surface exposes source, chunk, topic, and retrieval
  diagnostics to users

Wiii does not need to become OpenHuman. Wiii needs the same class of
inspectable facts for its own active product path: chat stream, uploaded
documents, LMS preview/apply, host context, visual/Code Studio routing, and
post-turn memory.

## OpenHuman Patterns To Adopt

### 1. Memory Has A Human-Readable Provenance Shape

OpenHuman's Memory Tree canonicalizes source data into bounded Markdown chunks
with deterministic IDs and provenance metadata before later scoring and tree
summaries.

Wiii should adopt the provenance shape, not the implementation. Uploaded
documents, RAG sources, semantic memory, core memory, and host context should
all produce a bounded turn ledger that says which source classes were present,
how many items were included, and whether citations/source refs were available.

### 2. Hot Path Stays Fast; Heavy Memory Work Runs Later

OpenHuman keeps ingest cheap in the hot path and sends embeddings, entity
extraction, sealing, and digests to background workers.

Wiii should keep chat response assembly focused on context selection and source
accounting. This audit slice therefore adds an observational Context Provenance
Ledger v1 instead of changing memory retrieval or write behavior.

### 3. Dynamic Memory Context Is A Turn Input, Not Prompt Drift

OpenHuman distinguishes a stable system prompt from dynamic per-turn memory
context. Memory context is injected with citations so the UI and operators can
show provenance.

Wiii currently assembles `conversation_history`, `semantic_context`,
`core_memory_block`, `document_context`, host context, and source refs into the
multi-agent context. The missing contract is a typed summary of that context
which can be emitted through `runtime_flow_ledger` without exposing raw text.

### 4. Sub-Agent Context Is Inherited And Bounded

OpenHuman's parent session owns memory loading. Sub-agents receive a filtered
or inherited parent context and return compact results; their inner history is
not spliced back into the parent.

Wiii should apply the same debugging rule: when a tool, visual lane, LMS action,
or Code Studio path misbehaves, first inspect the parent turn's ledger before
changing a leaf agent.

### 5. Token Compression Is A Contract, Not A Hope

OpenHuman treats large tool outputs and fetched content as budgeted payloads
that must be summarized, truncated, or compressed with identifiers preserved.

Wiii should continue recording large document and tool payloads as counts,
hashes, source refs, and warning codes. Runtime ledgers must never become raw
document or prompt dumps.

### 6. Memory Diagnostics Are Product Infrastructure

OpenHuman surfaces memory metrics, source counts, chunk counts, topic counts,
first/latest memory, vault links, and retrieval paths.

Wiii's first step is lower-level: stream metadata gets a context provenance
ledger. A later admin/operator surface can aggregate those ledgers into a
doctor view, but the per-turn schema must stabilize first.

## Context Provenance Ledger v1

Wiii should emit a privacy-safe context ledger under:

```text
runtime_flow_ledger.context.context_provenance
```

The v1 schema records:

- conversation history presence, char count, history item count, and summary
  presence
- document context presence, attachment counts, parser names, media kinds,
  provenance levels, source-ref counts, and hashed attachment identifiers
- semantic memory context presence, typed memory counts, memory type names,
  user fact counts, and core-memory presence
- host context presence, declared surface, capability names, and action count
- warning codes such as `document_context_without_source_refs`,
  `memory_context_without_typed_items`, and
  `host_context_without_capabilities`
- explicit privacy metadata: `raw_content_included=false` and
  `identifier_strategy=hash_or_count_only`

The schema must not include:

- raw user message text
- raw assistant text
- uploaded document Markdown
- semantic memory content
- core memory content
- raw file names
- provider request/response bodies
- raw approval tokens
- tool output payloads

## Do Not Copy

Wiii should not copy these OpenHuman assumptions:

- **GPL implementation code.** This audit records design lessons only.
- **Personal local-first trust boundary.** Wiii is org-aware and LMS-aware, so
  tenant, role, course, host surface, and approval boundaries remain mandatory.
- **A wholesale Obsidian vault before source safety.** Wiii should first make
  turn provenance visible, then decide whether a user/admin memory vault is
  needed.
- **Broad auto-fetch before tenant controls.** Wiii should not ingest or recall
  background data unless org and user scope are proven.
- **Managed Composio/OAuth assumptions.** Wiii host tools and LMS actions need
  Wiii-owned capability and approval contracts.
- **Diagnostics with raw content.** Counts, warning codes, hashes, and bounded
  names are acceptable; raw document and memory text are not.

## Wiii Implementation Slice

This audit maps to issue #660 and the first implementation contract:

- `maritime-ai-service/app/engine/multi_agent/context_provenance_ledger.py`
  builds the privacy-safe context ledger.
- `maritime-ai-service/app/engine/multi_agent/runtime_flow_ledger.py` embeds it
  in stream metadata.
- `maritime-ai-service/tests/unit/test_context_provenance_ledger.py` proves
  source counts and warning codes without raw content leakage.
- `tools/wiii_self_harness/wiii_self_harness_scenarios.json` adds the
  `memory-context-provenance-ledger` scenario.

This slice is intentionally observational. It does not change memory retrieval,
memory writes, document parsing, LMS mutation behavior, or provider routing.

## Follow-Up Issues

Open separate issues before changing these larger surfaces:

1. Add source-backed replay cases for uploaded document and LMS preview turns.
2. Add a read-only doctor/admin view that summarizes recent runtime ledgers.
3. Audit post-turn memory write hooks and tenant filters.
4. Decide whether Wiii needs a user-visible memory vault after provenance data
   is stable.
