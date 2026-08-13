# Complexity Wave 1 — DORMANT Flag Verdicts

Status: Executed (this PR) · Parent: desktop-first pivot (#893),
`docs/plans/2026-08-13-wiii-desktop-first-pivot.md`

Method: every DORMANT-tier flag (9, per `app/core/feature_tiers.py`) was
traced to its guarded code; the verdict is per-flag evidence, not a batch
judgment. Rule of the pivot: cheap deferred options may live; dead code may
not; production surfaces are demoted, never casually deleted.

## Verdicts

| Flag | Verdict | Evidence |
|---|---|---|
| `enable_neo4j` | **KEEP** (dormant) | Documented optional graph-context infrastructure (README, 12 guarded sites). An infra opt-in, not dead code. |
| `enable_telegram` | KEEP dormant | Vietnamese-market messaging channel bet (notifications service adapter). Tiny guarded surface, real option value. |
| `enable_zalo` | KEEP dormant | Same class — Zalo is the #1 Vietnamese messenger; adapter + router guard only. |
| `enable_zalo_webhook` | KEEP dormant | Router mount guard only. |
| `enable_messenger_webhook` | KEEP dormant | Router mount guard only. |
| `enable_auto_group_discovery` | KEEP dormant | Small tool registration inside the LIVE product-search subsystem (`product_search_tools.py:625`). |
| `enable_cross_soul_query` | KEEP dormant | Feature-node registration in the live runner, double-gated with `enable_soul_bridge` (a production_supported subsystem with its own desktop dashboard). |
| `enable_subagent_architecture` | KEEP dormant | Gates the parallel-dispatch/aggregator path inside the CURRENT WiiiRunner (`runner.py:909,921`, `supervisor.py:822`) and has its own CI evidence workflow (`subagent-boundary-evidence.yml`). A live architecture bet, not a relic. |
| `enable_oauth_token_store` | **DELETE** (this PR) | The guarded module self-describes as "a skeleton — no runtime behavior until enable_oauth_token_store=True" (`search_platforms/oauth/token_store.py`); the flag is never enabled anywhere; nothing imports the package except its own tests. |

## Deletion scope (`enable_oauth_token_store`)

- `app/engine/search_platforms/oauth/` (skeleton package, 84-line store)
- Settings field `enable_oauth_token_store` (**`oauth_encryption_key` STAYS** —
  `app/api/v1/voice.py:82` uses it for the voice surface's Fernet key)
- `_settings_validation.py` warning block; `feature_tiers.py` DORMANT entry;
  `tests/conftest.py` fixture line; tier + field assertions in
  `test_feature_tiers.py` / `test_sprint149_search_platforms.py` and the
  skeleton's own store tests.

## Wave 2 direction

The honest finding of wave 1: the DORMANT tier is mostly healthy — 8 of 9
flags are cheap, coherent options. The real complexity mass sits in the
**82 EXPERIMENTAL flags**. Wave 2 triages them in evidence-sized batches
(subsystem by subsystem), with the same per-flag verdict discipline and the
feature-tier guard green on every batch.
