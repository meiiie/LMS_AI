# Runbook: Provider Failover Storm

**Alert:** ≥ 5 provider failover events in 5 minutes
**Severity:** P3 ticket (no page — failover is the system working as
designed; the alert is a heads-up so the team can investigate the
upstream)
**SLO impact:** failovers are NOT a customer-visible failure if the
secondary provider holds. The ticket exists to catch upstream
provider degradation early so the team can pause the canary or
switch the priority order.

## Symptom shape

`enable_llm_failover=True` (the default) means LLMPool tries provider
A, falls back to B on a transient failure. A burst of failover
events is normal during a brief provider blip. ≥ 5 in 5 minutes
indicates either:

- The primary provider is genuinely degraded (the common case).
- The failover threshold is too sensitive (less common; LLMPool
  retries before declaring failover).
- A model-config mismatch (rare: requesting a model the primary
  no longer hosts → instant fallback every call).

## First 5 minutes

1. **Check provider status pages:**
   - OpenAI: https://status.openai.com
   - Google Gemini: https://status.cloud.google.com
   - NVIDIA NIM: https://status.nvidia.com
   - DeepSeek (NVIDIA-routed): same as NVIDIA
2. **Pull the recent failover log:** filter for `provider failover`
   in the application logs over the last 15 minutes. Look for the
   error class — `RateLimitError`, `TimeoutError`, `BadRequestError`
   each tell different stories.
3. **Check secondary provider health.** If failover is firing and
   the secondary is ALSO degrading (look for elevated `runtime.native_dispatch.runs{status="error"}`),
   you have correlated failure. Page on-call for **chat-5xx-surge.md**
   immediately.

## Live provider runtime probe

Use this only against approved staging or a controlled live operator account.
It makes credentialed provider calls through `LLMPool` and `WiiiChatModel`,
forces a harmless `record_probe_fact` tool call, feeds back a synthetic tool
result, and reports hash/count-only evidence.

```powershell
cd maritime-ai-service
$env:WIII_LIVE_PROVIDER_RUNTIME_PROBE='1'
python scripts\probe_live_provider_runtime.py --allow-call --provider auto
```

To also prove the terminal `/api/v1/chat/stream/v3` `runtime_flow_ledger`, add
the stream flags. This path may persist a chat turn, so keep it out of
production unless explicitly approved.

```powershell
python scripts\probe_live_provider_runtime.py --allow-call --include-stream-ledger --allow-stream-write --provider auto
```

Expected pass evidence:

- `direct_provider_tool_roundtrip.status=pass`
- `direct_provider_tool_roundtrip.provider_present=true`,
  `model_present=true`, and `selectable_provider_count>=1`
- request/session and organization scope are hash-present, with
  `raw_request_identifiers_included=false`
- exactly one tool call is observed:
  `tool_call_count_exactly_one=true`, `tool_call.name=record_probe_fact`,
  `tool_call.id_hash_present=true`, and
  `tool_call.argument_values_included=false`
- the runtime boundary remains Wiii-native:
  `runtime_boundary.llm_pool_route_used=true`,
  `runtime_boundary.wiii_chat_model_interface_used=true`,
  `runtime_boundary.raw_provider_http_used=false`, and
  `tool_contract.forced_tool_choice_used=true`
- `tool_result.role=tool`, `tool_result_linked_to_tool_call=true`, and no
  raw tool argument/content values in the artifact
- two tracing spans:
  `live_provider_runtime_probe.tool_call` and
  `live_provider_runtime_probe.tool_result`, with duration evidence and
  `trace.raw_attribute_values_included=false`
- when stream mode is included, `stream_runtime_ledger.status=pass`,
  `metadata_seen=true`, `done_seen=true`, `runtime_authoritative=true`,
  `finalization_status=saved`, `post_turn_lifecycle_schema_version=wiii.post_turn_lifecycle.v1`,
  provider/model authority is present in `runtime_flow_ledger.runtime`,
  done-event counts match the terminal ledger, request/session/org hashes are
  present, and `stream_runtime_ledger.privacy.stream_prompt_included=false`
  plus `stream_runtime_ledger.privacy.auth_secret_included=false`
- root `privacy` must report `raw_content_included=false`,
  `tool_argument_values_included=false`, `provider_arguments_included=false`,
  `provider_payload_included=false`, `provider_response_included=false`, and
  `stream_payload_included=false`

## Decision tree

### Branch A — Primary provider has a public incident

- **Reorder the priority** if `enable_unified_providers=True`:
  ```bash
  # via env var, no redeploy needed
  export UNIFIED_PROVIDER_PRIORITY='["openai","google","ollama"]'
  ```
- Watch latency on the new primary; if it's holding, this is the
  right state until the original primary's incident clears.
- File the ticket noting the provider, duration, and which fallback
  was used. Quarterly provider review aggregates these.

### Branch B — No public incident, only Wiii sees the failures

- Likely a model-config drift. Did a recent deploy change
  `GOOGLE_MODEL` or similar to a model the provider no longer
  hosts? Check `git log --since="24 hours ago" maritime-ai-service/app/engine/llm_providers/`.
- Test the primary directly: `curl` the provider's `/models` endpoint
  with the configured API key. A 401/403 means key rotation hit.
- Test failover behavior is reciprocal: temporarily flip the primary
  to the secondary in the priority list. If it works, primary is
  the issue.

### Branch C — Both primary and secondary failing

- Treat as **correlated upstream incident** OR **internal Wiii bug**
  (a recent change broke the LLM call shape itself).
- Roll back any deploy from the last 2 hours.
- If rollback doesn't help, escalate to **chat-5xx-surge.md** path.

## When the alert clears

- Failover event count must drop below 1 per 5 minutes for 30
  minutes. Provider blips often come in waves.
- File a single ticket per incident, even if the alert fires multiple
  times during the same upstream issue. Ticket spam dilutes the
  quarterly provider review.

## What NOT to do

- **Do not disable failover** (`enable_llm_failover=False`) just to
  silence the alert. That removes the safety net; if the primary
  stays degraded, every chat turn breaks.
- **Do not page on-call for failover storms.** This is a P3 ticket
  by design — the system is doing its job. Page only if the
  *secondary* also degrades.

## Related runbooks

- `chat-5xx-surge.md` — Branch C escalation target.
- `chat-latency-spike.md` — failover often costs ~200ms per turn.
