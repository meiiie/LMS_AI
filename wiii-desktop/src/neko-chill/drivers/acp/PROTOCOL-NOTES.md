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

## Session controls and commands (verified 2026-08-13)

- Current ACP v1 reports mutable controls through `configOptions` and updates
  them with `session/set_config_option`. Select and boolean controls are
  normalized by category (`mode`, `model`, `model_config`, `thought_level`).
- `available_commands_update` is the stable source for agent slash commands.
- `session_info_update` may carry an agent-authored title and `updatedAt`.
- Gemini CLI's captured fixture still reports legacy `modes` and `models`, and
  accepts `session/set_mode` / `session/set_model`. These routes are strictly
  feature-detected compatibility; a model switch is never shown unless the
  agent advertised it.
- Neko Core 0.24 reports four legacy modes but does not advertise model
  switching or slash commands. Neko model/provider selection is therefore
  config-first: discover with read-only `neko profiles`, then launch the ACP
  runtime with `neko acp --profile <id>`.

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
