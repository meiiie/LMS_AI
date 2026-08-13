# ACP Wire Contract — verified notes (T201)

Verified 2026-08-12 against agentclientprotocol.com (protocol/overview,
protocol/prompt-turn, protocol/initialization). Pin: **`protocolVersion: 1`**
(integer). JSON-RPC 2.0 over stdio; camelCase property keys, snake_case
discriminator values; all file paths absolute; line numbers 1-based.

**Agent roster invocations (verified 2026-08-13):**

- Gemini CLI ≥0.38: `gemini --experimental-acp`
- **neko-core ≥0.24.0** (released 2026-08-13, "Stable ACP v1"): **`neko acp`**
  (subcommand, not a flag; optional `--profile <p>`; `--yolo` = neko's `auto`
  mode). Per its `docs/process/ACP.md`: newline-delimited JSON-RPC on stdio;
  ACP session modes map to neko's default/accept-edits/plan/auto; client
  approvals cannot bypass neko's own safety boundary; it REFUSES
  client-supplied MCP servers at session creation — send `mcpServers: []`.

## Flow

1. Client spawns agent binary with its ACP flag (Gemini CLI:
   `gemini --experimental-acp`) and sends `initialize`:
   `{ protocolVersion: 1, clientCapabilities: { fs: { readTextFile, writeTextFile }, terminal }, clientInfo? }`
   → response carries `agentCapabilities` (`loadSession`,
   `promptCapabilities.{image,audio,embeddedContext}`, `mcpCapabilities`) and
   `authMethods: []`.
2. `session/new` → `{ sessionId }` (params include `cwd`, `mcpServers` —
   exact optionality to be confirmed from the real fixture, see below).
3. `session/prompt` request:
   `{ sessionId, prompt: [{ type: "text", text } | { type: "resource", resource: { uri, mimeType, text } }] }`.
   The response arrives only when the TURN ends:
   `{ stopReason: "end_turn" | "max_tokens" | "max_turn_requests" | "refusal" | "cancelled" }`.
4. While the turn runs, the agent streams `session/update` NOTIFICATIONS:
   `{ sessionId, update: { sessionUpdate: <discriminator>, ...fields } }` with
   discriminators:
   - `agent_message_chunk` — `content: { type: "text", text }` (answer delta)
   - `agent_thought_chunk` — reasoning delta
   - `tool_call` — `{ toolCallId, title, kind, status: "pending" }`
   - `tool_call_update` — `{ toolCallId, status: "in_progress"|"completed"|"cancelled", content? }`
   - `plan` — `{ entries: [{ content, priority, status }] }`
   - `usage_update` — `{ used, size, cost? }`
5. Agent→client REQUESTS during a turn: `session/request_permission`
   (toolCall + options; option kinds along the lines of allow-once /
   allow-always / reject — **exact optionId/kind/outcome shapes MUST be taken
   from the recorded Gemini CLI fixture in T203, not from these notes**),
   plus optional `fs/read_text_file`, `fs/write_text_file`, `terminal/*`.
   v0 policy: advertise `fs: { readTextFile: false, writeTextFile: false },
   terminal: false` so the agent uses its own tools and every side effect
   surfaces through `session/request_permission` only.
6. Cancellation: client sends `session/cancel` notification `{ sessionId }`;
   the running `session/prompt` resolves with `stopReason: "cancelled"`.

## Open items (close via T203 golden fixture from real Gemini CLI)

- `session/new` params exact shape (`cwd` required? `mcpServers` optional?).
- `session/request_permission` request/response exact shapes (outcome:
  selected vs cancelled).
- Whether Gemini CLI requires `authenticate` before `session/new` when
  already logged in (expected: no; `authMethods: []`).

## Mapping to DriverEvent (drivers/types.ts)

| ACP | DriverEvent |
|---|---|
| `session/prompt` sent | `turn-started` |
| `agent_thought_chunk` | `reasoning-delta` |
| `agent_message_chunk` | `answer-delta` |
| `tool_call` / `tool_call_update` | `activity` (upsert by `toolCallId`) |
| `plan` | `activity` (kind `plan`) |
| `session/request_permission` | `permission-request` (turn pauses) |
| `session/prompt` response | `turn-finished` (carries stopReason) |
| transport/JSON-RPC failure | `error` |
| process exit | `process-exited` |
