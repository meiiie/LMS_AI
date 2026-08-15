# Research: Unified Wiii Workbench

**Issue**: #923
**Date**: 2026-08-16

## Decisions

### One shell, multiple capability providers

The current `ModeGate` prevents cloud initialization while Neko Chill is
active, which was the correct safety seam for the first local-mode release.
It is now the wrong product seam: it makes runtime, account, knowledge, and UI
mutually exclusive. Preserve the safety property by making managed services
lazy connections inside one shell instead of mounting them at process start.

Decision: promote the Neko Chill workspace interaction model into Wiii
Workbench. Keep the current cloud app as a compatibility surface until its
runtime and knowledge behavior have adapters and parity tests.

### Host capabilities, not platform guesses

Tauri can spawn local child processes and mediate selected filesystem actions.
A hosted browser cannot safely do either. Both can render the same React shell
and consume a remote event transport.

Decision: derive an immutable `WorkbenchHost` from runtime evidence. The web
host has no local process, arbitrary filesystem, window chrome, tray, or native
secret-store capability. Components request capabilities rather than checking
`__TAURI_INTERNALS__` independently.

### Keep RAG outside the agent runtime

`maritime-ai-service` already owns organization-scoped retrieval, memory,
citations, integrations, and durable data. Moving that logic into the desktop
would duplicate tenant/security rules and require shipping PostgreSQL/pgvector,
Neo4j, object storage, and cache infrastructure.

Decision: model Wiii Knowledge as an optional remote `KnowledgeConnection`.
Later local indexing can implement the same contract with a deliberately small
storage engine. A service outage degrades knowledge, not the local agent.

### Model-visible knowledge is durable input

DeepSeek Harness derives model history from its session log. Wiii already has
a strict persistence barrier before provider dispatch for model-visible facts.

Decision: retrieval query, selected evidence, source/citation identity, and a
content digest enter a `model-context-attached` session event before prompt
dispatch. Raw provider secrets never enter the event log.

### Codex uses App Server, not copied credentials

Official OpenAI documentation describes Codex App Server as the interface for
embedding Codex into a product, including authentication, threads, approvals,
models, and streamed events. It supports provider-owned ChatGPT browser or
device-code login and API-key login.

Decision: spawn the installed `codex app-server` over stdio. Let App Server own
token persistence/refresh. Wiii stores only non-secret account metadata and the
provider thread id. External-token mode is not used.

### Claude stays at the approved product boundary

Claude Code supports subscription login for Anthropic's own runtime, but its
published legal guidance says third-party products must not offer Claude.ai
login or route subscription credentials without approval.

Decision: public Wiii exposes Claude through API/cloud credentials or a future
approved integration. Never inspect Claude credential files. Keep branding as
Wiii with a provider label such as `Claude`, not an imitation of Claude Code.

## Alternatives rejected

### Move the backend into Neko Chill

Rejected because it couples desktop installation to server infrastructure,
duplicates security logic, and makes hosted web harder rather than easier.

### Keep two permanent product modes

Rejected because sessions, provider selection, knowledge, and account state
remain artificially separated and first-run stays blocked by server setup.

### Universal OAuth broker in Wiii

Rejected because provider terms, token lifecycles, billing, scopes, and data
handling differ. Official runtimes or supported API credentials own auth.

### Browser polyfills for native agents

Rejected because a web page cannot safely gain local process or unrestricted
filesystem authority. Web uses authenticated remote runtimes.

## Primary references

- OpenAI Codex App Server documentation: <https://learn.chatgpt.com/docs/app-server>
- OpenAI authentication documentation: <https://learn.chatgpt.com/docs/auth>
- Anthropic Claude Code authentication: <https://code.claude.com/docs/en/authentication>
- Anthropic Agent SDK and third-party auth boundary: <https://code.claude.com/docs/en/agent-sdk/overview>
- Anthropic legal and credential policy: <https://code.claude.com/docs/en/legal-and-compliance>
- Agent Client Protocol architecture: <https://agentclientprotocol.com/get-started/architecture>
- DeepSeek Harness architecture: <https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md>
- Zed external-agent ownership boundary: <https://github.com/zed-industries/zed/blob/main/docs/src/ai/external-agents.md>
