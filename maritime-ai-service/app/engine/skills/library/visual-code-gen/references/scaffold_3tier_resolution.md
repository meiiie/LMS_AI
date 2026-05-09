# Graceful scaffold — 3-tier spec-driven resolution

> Implementation: `app/engine/multi_agent/code_studio_template_scaffold.py`
> Last revision: Sprint 35i (2026-05-05)

When the LLM planning call cannot complete a `tool_create_visual_code`
invocation in time (NVIDIA NIM connection error, streaming stall,
post-tool synthesis timeout), the runtime engages a deterministic HTML
scaffold so the user always sees a visible canvas. The scaffold is a
safety net, not a teaching device — keep it out of the model's prompt.

This document specifies the spec-driven architecture introduced in
Sprint 35i. Read this when:
- adding rich content for a new famous topic
- diagnosing "scaffold doesn't match topic" reports
- adding a new primitive family
- updating the inference helpers

## Where the scaffold engages

Six fail points in `code_studio_tool_rounds.py` plus one outer catch in
`code_studio_node_runtime.py`:

| Trigger | Reason label (Prometheus) |
|---------|---------------------------|
| Streaming `astream` overall timeout | `stream_overall_timeout` |
| Streaming finished without tool_call or code_html | `stream_empty` |
| Streaming-path ainvoke fallback also failed | `ainvoke_fallback_fail` |
| Non-streaming ainvoke task cancelled | `ainvoke_cancelled` |
| Non-streaming ainvoke raised exception | `ainvoke_exception` |
| LLM returned prose without invoking the tool | `llm_prose_no_tool_call` |
| Outer node-level exception | `node_outer_<ExceptionName>` |

Each engagement increments
`wiii.code_studio.scaffold.engaged{kind, reason}` so operators can
catch provider-health regressions in Grafana.

## Three tiers, all deterministic

```
Query → Tier 1 (TOPIC_LIBRARY: rich curated content)
      → Tier 2 (PRIMITIVE_CONCEPTS: concept-level routing)
      → Tier 3 (smart inference defaults)
      → ScaffoldSpec → renderer → HTML
```

Each tier runs through the same `_enrich_spec()` helper so every
returned spec carries every field the renderers need (palette, title,
particle_label, drift_direction, etc.).

### Tier 1 — `TOPIC_LIBRARY` (5 entries today)

Hand-curated event/moment lists for famous, recurring topics. When
matched, the scaffold ships concrete years/quotes instead of placeholder
structure. Adding a new famous topic = +1 entry (~10 lines).

Currently shipped:
- Thế chiến II (timeline, 7 events 1939–1945)
- Khởi nghĩa Lam Sơn — Lê Lợi (timeline, 5 events 1418–1428)
- Kháng chiến chống Nguyên Mông — Bạch Đằng (timeline, 5 events 1257–1288)
- Truyện Kiều — Thúy Kiều ở lầu Ngưng Bích (scene, 4 moments + tower figure)
- Văn học Việt Nam (scene, generic 4-moment template for 14+ characters)

Adding a sixth: append a dict to `TOPIC_LIBRARY` with `keywords` (list of
substring matches against `lower(query) + diacritic_strip(query)`) and
a `spec` (renderer-ready dict).

### Tier 2 — `PRIMITIVE_CONCEPTS` (7 entries today)

Universal motion / structure / atmosphere signals → primitive type.
**Not topic-bound**: "rụng/rơi/lả tả" matches falling leaves, snow,
rain, ash, petals, tears — anything that falls. "lịch sử/triều đại/
chiến tranh" matches WW2, Lê Lợi, Roman empire, Genghis Khan.

| # | Concept | Signal examples | Primitive |
|---|---------|-----------------|-----------|
| 1 | Drift-down | rụng, rơi, la rung, tan tro, phun trao | particle_field down |
| 2 | Float | bay, lơ lửng, trôi, đom đóm, bướm | particle_field float |
| 3 | Twinkle | sao, ngân hà, lung linh, lấp lánh, ánh sáng | particle_field twinkle |
| 4 | Oscillation | con lắc, dao động, lò xo, quỹ đạo, viên đạn | oscillation |
| 5 | Function plot | hàm số, đồ thị, vector, toạ độ Oxy, sin( | function_plot |
| 6 | Timeline | lịch sử, triều đại, chiến tranh, khởi nghĩa | timeline |
| 7 | Scene | cảnh, tác phẩm, đoạn trích, nhân vật, thơ | scene |

These 7 cover every primitive family. Adding a topic that fits an
existing concept = **0 lines** (handled automatically). Adding a new
primitive family = +1 concept entry (~10 lines) plus a renderer.

### Tier 3 — smart inference defaults

When neither library nor concept matches, `_build_default_spec(query)`
runs five deterministic helpers on the query alone:

1. **`_extract_visual_title(query)`** — strips command words ("mô
   phỏng", "vẽ", "tạo", "hãy", "dựng") iteratively → noun phrase as
   title. Works for any topic; uses prefix matching only.

2. **`_infer_palette(query)`** — atmospheric / seasonal keywords →
   palette name. "đêm/khuya/trăng" → night_sky; "mùa thu" → autumn;
   "biển" → ocean; "rừng" → forest; "vật lý" → physics_warm;
   "lịch sử/chiến" → historical_dark; etc.

3. **`_infer_object_name(query)`** — object noun for slider labels.
   "lá" → "chiếc lá"; "tuyết" → "bông tuyết"; "mưa" → "giọt mưa";
   "ngôi sao" → "ngôi sao"; "đom đóm" → "đom đóm"; etc. Bag is
   space-padded so short keys (`" tro "`, `" mua "`) work as
   word-boundary matches.

4. **`_infer_drift_direction(query)`** — motion verb → drift mode.
   "rơi/rụng/đổ xuống" → down; "ào ào/tuôn/trút" → down_fast;
   "bay/lơ lửng/trôi" → float; "lung linh/lấp lánh" → twinkle.

5. **`_infer_count_range(query)`** — quantity hints → particle counts.
   "dày đặc/kín trời" → (60, 400, 250); "lác đác/vài/ít" → (5, 60, 25);
   default → (30, 250, 120).

If the inference detects any motion verb, the default returns a
`particle_field` (not data_band) so even queries like "hoa anh đào rơi"
or "cơn bão dữ dội" produce relevant scaffolds without a concept match.

## Diacritic-stripping collisions (important)

Vietnamese diacritic-strip creates ambiguity:

| Raw form A | Raw form B | Stripped |
|------------|------------|----------|
| rụng (fall) | rừng (forest) | rung |
| rơi (fall) | rồi (already) | roi |
| lượn (float) | lương (salary) | luon |
| sông (river) | sống (live) | song |

**Rule**: never use bare ambiguous stripped forms as keywords. Always
use one of:
- raw-diacritic form (`"rụng"`, `"rơi"`, `"lượn"`)
- compound stripped form (`"la rung"`, `"tan rung"`, `"la roi"`)
- space-padded stripped form (`" luon "`, `" sao "`, `" bay "`)

The bag is built as `f" {raw} \n {norm} "` (leading + trailing spaces
on both copies) so word-boundary keys actually behave as word boundaries.

## Adding a new topic — decision tree

```
Does an existing concept already match the query?
├── Yes → 0 lines. Done.
└── No  → Is the topic famous enough to deserve hand-curated content?
         ├── Yes → +1 entry to TOPIC_LIBRARY (~10 lines)
         └── No  → Does it need a new primitive family?
                  ├── Yes → +1 entry to PRIMITIVE_CONCEPTS + new renderer
                  └── No  → Inference helpers handle it. 0 lines.
```

## Six primitives and their fields

| Primitive | Required fields | Optional fields |
|-----------|-----------------|------------------|
| `particle_field` | palette, drift_direction | particle_label, slider_label, particle_count_*, particle_color, extra_layers, readout_lead, readout_phrase |
| `oscillation` | palette | slider_label, slider_min/max/default, slider_unit |
| `function_plot` | palette | slider_label, slider_*, function_expression, function_label_vi |
| `timeline` | palette, events[] | slider_label |
| `scene` | palette, moments[] | slider_label, scene_figure (`tower`/`character`) |
| `data_band` | palette | slider_label, slider_* |

Renderers live in the same module: `_render_particle_field`,
`_render_oscillation`, `_render_function_plot`, `_render_timeline`,
`_render_scene`, `_render_data_band`. Each emits a complete HTML
fragment satisfying the canvas-first contract (see below).

## Canvas-first contract (every primitive must satisfy)

Every emitted scaffold passes `validate_code_studio_output` for premium
simulations:

- `<canvas>` element with `getContext('2d')`
- `<input type="range">` slider with `aria-label`
- `<div aria-live="polite">` readout that updates per slider input
- `requestAnimationFrame(frame)` RAF loop
- `WiiiVisualBridge.reportResult` feedback hook
- `data-scaffold-kind="..."` + `data-scaffold-primitive="..."` on root
- `@media (max-width:480px)` responsive breakpoint
- `@media (prefers-reduced-motion:reduce)` accessibility breakpoint

If you change a renderer, run `tests/unit/test_code_studio_template_scaffold.py` —
the contract tests exercise every primitive end-to-end.

## Operator-tunable timeouts

These are settings fields, not constants. Tune per deployment via
`.env.production`:

```bash
CODE_STUDIO_STREAM_OVERALL_TIMEOUT_SECONDS=90    # 15-600
CODE_STUDIO_CHUNK_TIMEOUT_SECONDS=30             # 5-300
CODE_STUDIO_CODE_DONE_TIMEOUT_SECONDS=30         # 5-180
CODE_STUDIO_LLM_HARD_TIMEOUT_SECONDS=90          # 15-600
CODE_STUDIO_FALLBACK_AINVOKE_TIMEOUT_SECONDS=60  # 10-300
CODE_STUDIO_POST_TOOL_SYNTHESIS_TIMEOUT_SECONDS=90  # 15-600
```

Worst-case server-side latency under provider stress: ~190s (streaming
90s + non-streaming fallback 60s + post-tool synthesis 90s, with
overlap). Well below typical user HTTP timeout of 240s.

## Anti-patterns

- **Do not** add scaffold templates to the model's system prompt. The
  model should attempt the real `tool_create_visual_code` call every
  time; the scaffold is a deterministic safety net, not a few-shot
  example. Putting scaffold examples in the prompt biases the model
  toward producing trivial output even when the provider is healthy.
- **Do not** add per-topic patterns when adding "support for X". Almost
  every X already routes through Tier 2 + Tier 3. If you find yourself
  copying an existing pattern entry and tweaking keywords, you're
  fighting the architecture.
- **Do not** use bare ambiguous stripped forms as keywords (`"rung"`,
  `"roi"`, `"luon"`). Always use raw-diacritic or compound forms.
- **Do not** introduce another tier above Tier 1 (e.g., LLM-call-during-
  fallback). Tier 1–3 are intentionally LLM-free so the scaffold works
  precisely when the LLM is the failing component.

## Test references

- `tests/unit/test_code_studio_template_scaffold.py` — 51 contract tests
  (kind detection, canvas-first, theme variables, mobile, a11y, XSS,
  reduced-motion, kind override).
- Detection sweep: 30/30 on a mix of 5 known topics + 7 concept queries
  + 18 novel queries (đại bàng săn mồi, kim tự tháp, DNA, blockchain,
  photosynthesis, hoa anh đào rơi, vũ trụ deep space, etc.).

## Pattern reference

- Anthropic Claude Artifacts 2026 — spec-driven primitives with
  parameterized JSON specs.
- Vercel v0 (v0.dev 2026) — schema-first generation with smart defaults.
- Bolt.new (StackBlitz 2026) — WebContainer scaffolds + theme
  inheritance + heuristic fallbacks.
- Cursor Composer 2026 — 3-tier resolution: exact → semantic → LLM.
- W3C CSS Custom Properties Level 3 §3.2 — variable inheritance through
  nested scopes (used by `_KIND_VAR_HOOKS`).
