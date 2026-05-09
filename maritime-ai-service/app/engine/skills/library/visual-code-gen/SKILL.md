---
name: visual-code-gen
description: |
  Lane policy, quality rubric, and runtime contract for Code Studio
  outputs. USE THIS SKILL whenever the user asks for a simulation,
  interactive widget, mini app, dashboard, quiz, search-result explorer,
  or any bespoke interactive surface that ships rendered code (HTML +
  CSS + JS, SVG, or Canvas). TRIGGER for queries containing 'mô phỏng',
  'simulation', 'tạo widget', 'build app', 'interactive', 'canvas',
  'mini tool', 'dashboard'. DO NOT trigger for chart/comparison/process-
  flow figures — those route to `tool_generate_visual` (article figure
  runtime), not Code Studio.
version: 6.3.0
---

# Visual Code Generation — Wiii V5

Code Studio follows **LLM-first planning, host-governed runtime**:

- the model decides what should be built
- the host decides which lane should render it
- Code Studio is **not** the default lane for every visual

## When to use this skill

Use Code Studio (`tool_create_visual_code`) only when the user truly
needs:

- simulation (physics, particle, atmospheric, narrative scene)
- quiz / interactive learning widget
- search widget / result explorer
- code widget / runner
- mini tool / utility
- dashboard / KPI surface
- mini HTML app or artifact
- bespoke interactive surface that structured figures cannot express

## When NOT to use

For these, route back to `tool_generate_visual` (article figure / chart
runtime) — it's faster, cheaper, and produces SVG-first deterministic
output:

- explanation in charts
- comparison tables / bar charts
- process / step flow diagrams
- architecture / infographic
- timeline / benchmark charts

For chart and comparison work, prefer writing HTML directly in
`code_html` of `tool_generate_visual`. `spec_json` still works when
data is pre-structured or the chart is very simple.

Wiii palette: `#D97757`, `#85CDCA`, `#FFD166`. Title nhỏ, warm tones,
rounded corners.

## Core philosophy

- Plan with the LLM.
- Reuse host shell, host controls, host spacing, host bridge.
- Do not freestyle the whole product shell from scratch.
- Prefer approved recipes and scaffolds when available.
- Keep outputs patchable and session-aware.
- Article figures and chart runtime are SVG-first by default.
- Premium simulations are Canvas-first by default.
- Wiii should feel alive through pedagogy, pacing, and motion choices,
  not through extra chrome.

## Quality rubric — every output must pass

### Planning-first for premium tasks

For premium simulations and complex app widgets, do a hidden planning
pass first. Decide:

- the state model
- the render surface
- the control set
- the live readouts
- the feedback / reporting hooks

Then draft the HTML/CSS/JS. Run one quick self-critique before the
final tool call.

### Semantic fit

- Is this really an app/widget/artifact task?
- If this is only an explanatory figure, stop and route back to
  `tool_generate_visual`.

### Runtime fit

- Host shell owns chrome.
- Generated code should focus on body logic, render surface, controls,
  and state.
- Do not recreate the entire chat card or app container.
- For simulations, a trivial scripted scene with two buttons is **not**
  enough for premium quality. Prefer a real runtime surface (`canvas`,
  `svg`, or equivalent) plus parameter controls and live readouts.

### Visual quality

- Embed real data trực tiếp trong code — output có data thật luôn đẹp
  và có ý nghĩa hơn placeholder.
- Ưu tiên SVG hoặc Canvas cho chart — chúng sắc nét và responsive hơn
  div-based layouts.
- Màu sắc warm tones (`#D97757`, `#85CDCA`, `#FFD166`) tạo cảm giác
  thân thiện hơn corporate palettes.
- `overflow: visible` hoặc `overflow: clip` cho text containers — tránh
  clip chữ ở rounded corners.
- See `references/ai_slop_anti_patterns.md` for the full list of
  patterns to detect and avoid.

### Accessibility

- Keyboard reachable controls.
- Clear labels and `aria-live` readouts where state updates.
- Reduced-motion friendly (`@media (prefers-reduced-motion:reduce)`).
- A short textual summary should still be inferable from the UI.
- Mobile responsive: `@media (max-width:480px)` block on every output.
- See `references/theme_inheritance.md` for the full a11y + theme
  contract.

### LMS fit

- Tone and framing should work in an educational context.
- Avoid gimmicky effects that distract from learning.

### Feedback bridge

- Widget-style outputs should report meaningful outcomes through
  `window.WiiiVisualBridge.reportResult(category, payload, summary, status)`
  when the user completes a meaningful interaction.
- Simulation or app widgets should emit summaries after notable user
  actions, not only raw UI state.

## Required output structure

Generated code should separate concerns:

- `data / state`
- `render surface`
- `controls`
- `feedback / reporting hooks`

Even in a single HTML file, do not mix everything into one messy block.

## Approved scaffold families

Prefer these scaffold families over free-form invention:

- pendulum / oscillation simulation
- ship encounter / COLREG manoeuvre
- particle field / atmospheric scene explainer
- timeline scrub simulation
- function plot / coordinate grid
- quiz widget
- search result explorer
- code runner / preview
- mini dashboard

When a scaffold fits, adapt it to the request instead of inventing a
new shell.

## Artifact vs inline visual

| Inline visual | Artifact |
|---------------|----------|
| belongs inside the answer | longer-lived app/document/widget |
| used for explanation | okay to open in Studio / panel |
| should not open Studio by default | versioned, patchable, inspectable |
| may offer artifact handoff later via follow-up prompt | |

Do not confuse the two.

## Response guidance

When Code Studio is used:

- talk like a maker shipping something usable
- do not dump payload JSON
- do not narrate internal tool plumbing
- hand back the artifact / app clearly

When Code Studio is not the right lane:

- do not force it
- route back to `tool_generate_visual`

## Examples of correct routing

### Good

- "Hãy mô phỏng vật lý con lắc" → Code Studio app
- "Tạo widget tìm kiếm nguồn" → Code Studio widget
- "Tạo một mini app HTML để nhúng" → Code Studio artifact

### Not good

- "So sánh Kimi linear attention bằng biểu đồ" → not Code Studio
- "Vẽ biểu đồ giá xăng RON95" → not freestyle HTML bars in Code Studio
- "Giải thích kiến trúc RAG" → article figure, not Studio panel

## Pre-shipping checklist

Before calling `tool_create_visual_code`, ask:

1. Is this truly an app/widget/artifact task?
2. Would chart runtime or article figure solve it better?
3. Does the output respect host shell and bridge contracts?
4. Is the quality above demo-grade?
5. If this is premium simulation/app work, did I plan state + controls
   + readouts before coding?
6. If this should feel like Wiii, does the scene guide the learner
   toward one mechanism or insight instead of just showing off UI?

If any answer is "no", do not use Code Studio yet.

## Graceful fallback (when LLM planning fails)

When the LLM planning call cannot complete a `tool_create_visual_code`
invocation in time (NVIDIA timeout, streaming stall, post-tool synthesis
timeout), the runtime engages a **deterministic spec-driven scaffold**
so the user always sees a visible canvas. The scaffold:

- runs through a 3-tier resolution (TOPIC_LIBRARY → PRIMITIVE_CONCEPTS
  → smart inference defaults)
- ships a complete `<canvas>` + RAF loop + slider + aria-live readout +
  `WiiiVisualBridge.reportResult` hook
- emits a Vietnamese caption that **clearly invites extension** — never
  claims the output is final
- is LLM-free — works precisely when the LLM is the failing component

**Do not** add scaffold templates to the system prompt. The model
should attempt the real `tool_create_visual_code` call every time.

For the full architecture (3 tiers, 7 primitive concepts, 5 inference
helpers, 6 fail-point engagement, operator timeouts, anti-patterns),
see `references/scaffold_3tier_resolution.md`.

## Reference examples

When the runtime injects a `## REFERENCE EXAMPLE` section into your
prompt, study its structure, design system, and depth of interactivity.
**Do not copy verbatim** — adapt the patterns to the user's request.

Inventory of available examples (canvas simulations, SVG diagrams,
HTML widgets, dashboards) lives in
`references/reference_examples_inventory.md`.

## React + Babel widgets

When building interactive prototypes that benefit from React state
management (quiz widgets, dashboards, multi-state UIs, forms, tabs),
follow the pinned-CDN + integrity-hash + global-scope discipline in
`references/react_widget_guidelines.md`.

For physics simulations or particle systems, prefer **vanilla + Canvas**
— React adds unnecessary overhead.

## References (progressive disclosure)

Detailed contracts are split into reference files so this main SKILL
stays focused on routing and quality. Load them as needed:

| File | When to read |
|------|--------------|
| `references/scaffold_3tier_resolution.md` | Adding a new topic / debugging "scaffold doesn't match topic" / extending a primitive |
| `references/theme_inheritance.md` | Adding new CSS variables / debugging theme overrides / mobile breakpoint work |
| `references/ai_slop_anti_patterns.md` | Pre-ship visual review / detecting cookie-cutter output |
| `references/react_widget_guidelines.md` | Building a React widget / Babel CDN setup |
| `references/reference_examples_inventory.md` | Studying a loaded reference example / picking the right scaffold family |

## Pattern reference

- Anthropic Claude Artifacts 2026 — spec-driven primitives
- Anthropic Computer Use 2026 — evidence-pool fallback pattern
- Vercel v0 (v0.dev 2026) — schema-first generation
- Bolt.new (StackBlitz 2026) — WebContainer + theme inheritance
- Cursor Composer 2026 — 3-tier resolution
- Perplexity Pro Search 2026 — source-backed best-effort
