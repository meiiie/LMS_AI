# Wiii Unified Workbench

**Status:** Implemented baseline
**Updated:** 2026-08-16
**Issue:** [#923](https://github.com/meiiie/wiii/issues/923)

Wiii is one Workbench with composable capabilities. Local and managed work are
not separate products and a future web deployment does not require a second UI
architecture.

## Capability model

| Capability | Desktop | Hosted web | Authority |
| --- | --- | --- | --- |
| Local process | Available | Unavailable | Native host |
| Project filesystem | Available after folder selection | Unavailable | Native host |
| Neko Core / Gemini CLI | Available when installed | Unavailable | Provider runtime via ACP |
| Codex | Available when installed | Unavailable | Codex App Server |
| Wiii Service runtime | Optional | Primary | Wiii account and deployment |
| Wiii Knowledge | Optional and independently switchable | Available through Wiii Service | Authorized organization scope |
| Memory and organization policy | Optional | Available through Wiii Service | Wiii Service |

Host capability derivation fails closed. The web build never renders or calls
local process, native window, tray, or project-folder operations. A remote
desktop/daemon bridge can be added later as an explicit remote runtime; it must
not masquerade as browser filesystem authority.

## Startup and migration

- A fresh desktop install opens the local Workbench without initializing cloud
  auth, conversations, polling, RAG, or organization state.
- An existing desktop user keeps their saved local/managed intent.
- A hosted-web build always opens the managed surface because it cannot satisfy
  local process and workspace requirements.
- Legacy mode/auth records are read for additive migration and are not deleted.
- The inactive surface stays unmounted, which makes the privacy and startup
  boundary structural rather than a collection of conditional effects.

## Runtime and account ownership

| Path | Login owner | Token storage | Model/thread owner | Billing owner |
| --- | --- | --- | --- | --- |
| Neko Core | Neko/provider profile | Provider | Neko Core | Provider account |
| Gemini CLI | Gemini CLI | Provider | Gemini CLI | Provider account |
| Codex | Codex App Server | Codex | Codex App Server | OpenAI/provider account |
| Wiii Service | Wiii Service | Wiii client/server contract | Wiii Service | Deployment policy |
| Claude API/cloud | Approved API/cloud path | Server only | Configured provider | API/cloud account |

Wiii never imports or persists Codex tokens. It requests browser login from
Codex App Server, opens the provider URL, and observes the provider completion
event. Third-party Claude subscription login remains disabled unless Anthropic
explicitly authorizes that integration; supported Claude access must use an API
or approved cloud-provider contract.

## Knowledge composition and model-visible facts

Wiii Knowledge is independent from runtime selection. A local Neko, Gemini, or
Codex turn can request authorized Wiii retrieval while generation remains with
that local provider.

For every retrieved context:

1. Wiii Service applies canonical authenticated organization scope before
   retrieval.
2. It returns bounded evidence and provenance, not a generated answer.
3. Desktop marks source content as untrusted evidence.
4. The complete rendered context and citation metadata enter the append-only
   session event log.
5. Strict persistence completes before the provider receives the augmented
   prompt.
6. A dispatch marker records that the staged context crossed the model
   boundary.

If step 4 fails, dispatch is blocked. If retrieval is unavailable, Wiii marks
the knowledge connection degraded and continues local work without RAG instead
of pretending grounding succeeded. Reopening a session replays the recorded
context and never reruns retrieval for an already dispatched turn.

“Model-visible facts” therefore means facts the model could actually have seen,
not every UI value. User prompts, retrieved evidence, permission decisions, and
committed provider controls belong in the ordered log. Panel width, hover state,
an unpersisted tool result, or a guessed crash outcome do not.

## Web deployment

`npm run build:web` compiles the same Workbench contracts for a hosted origin.
In production, the frontend uses `VITE_API_URL` when provided and otherwise the
current origin. The reverse proxy should expose Wiii Service under that origin,
terminate TLS, and preserve SSE. Web users authenticate with Wiii and receive
remote runtimes, RAG, memory, organizations, artifacts, and integrations.

Local coding on a web deployment requires a future explicit bridge or remote
sandbox with its own authentication, workspace identity, permission policy,
and lifecycle. The browser alone cannot launch Neko Core, Gemini CLI, Codex, or
read an arbitrary local folder.

## Verification and rollback

The owning checks cover pure host derivation, capability filtering, local-first
bootstrap, legacy migration, browser fail-closed behavior, Codex protocol
fixtures, provider-owned login, knowledge schema validation, pre-dispatch
durability, replay, TypeScript, web/embed builds, Rust detection, and focused
backend retrieval tests.

Rollback is additive: retain the new event parser and stored surface key, hide
new connection entry points, and restore the former surface renderer. Never
delete session snapshots, provider thread IDs, account records, or the new
knowledge events during rollback.
