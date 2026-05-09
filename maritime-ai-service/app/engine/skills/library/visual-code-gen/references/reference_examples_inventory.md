# Reference examples — inventory and study notes

> Examples live in `app/engine/reasoning/skills/subagents/code_studio_agent/examples/`.
> Loaded on-demand into context based on the resolved `visual_type`.

When the runtime injects a `## REFERENCE EXAMPLE` section into your
prompt, study its structure, design system, and depth of interactivity.
Do **NOT** copy verbatim — adapt the patterns to the user's request.

## Premium simulations (Canvas-first)

### `canvas_wave_interference.html` (~800 lines)
- Physics engine + `requestAnimationFrame` loop
- Interactive controls (frequency, amplitude, phase) with live
  slider → readout updates
- `WiiiVisualBridge.reportResult` feedback hook on meaningful state
  changes
- Demonstrates: state separation, render-only `frame()` body, single
  IIFE wrapper

## Interactive SVG diagrams

### `svg_ship_encounter.html` (~830 lines)
- Inline SVG with drag interaction
- Real-time bearing / CPA calculation as user drags either ship
- Annotation labels follow ship positions
- Demonstrates: inline SVG + JS event handlers + reactive labels

### `svg_flow_diagram.html` (~310 lines)
- Step-by-step process boxes with arrow connectors
- Decision diamond branch
- Detail panel updates on click
- Keyboard navigation (Tab + Enter)
- Demonstrates: keyboard a11y + focus management + detail-on-demand

### `svg_comparison_chart.html` (~280 lines)
- Horizontal bar chart with dataset toggle
- Sort by value/name
- Hover highlight + detail bar
- Demonstrates: D3-style data binding without D3, accessible chart
  patterns

## HTML/CSS/JS widgets

### `widget_maritime_calculator.html` (~370 lines)
- Tab-based forms (CPA, set & drift, etc.)
- Instant calculation on input
- Compass SVG visualization
- Bridge feedback on submit
- Demonstrates: form UX without React, compass arc math

## Dashboards

### `dashboard_metrics.html` (~480 lines)
- KPI cards with trend indicators
- SVG line chart + SVG donut chart
- Data table with mini-bar cells
- Tooltips on hover
- Demonstrates: dashboard layout, chart composition, hover tooltips

## Study order

When you see a reference example loaded into your context:

1. **Read the structure first** — section comments, function ordering,
   how state/render/controls/feedback are separated.
2. **Identify the design system** — palette, spacing, typography,
   `var(--wiii-*)` usage.
3. **Study the interaction patterns** — what does the user drag, click,
   type, slide? How do readouts update?
4. **Note the bridge calls** — when does it `reportResult`? On every
   tick? Only on meaningful actions?
5. **Adapt, do not copy** — the user's request is different. Take the
   *patterns*, leave the *content*.

## Quality bar

A good reference example fits in your 200k context window AND teaches
one thing well. If a "reference" pads with cookie-cutter sections, it
fails the AI-slop test (see `ai_slop_anti_patterns.md`).
