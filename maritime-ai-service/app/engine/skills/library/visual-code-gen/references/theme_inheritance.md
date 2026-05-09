# Theme inheritance contract

> Bridge: `wiii-desktop/src/components/common/InlineVisualFrame.tsx`
> Last revision: Sprint 35e (kind-namespaced vars), Sprint 35h+ (per-primitive vars also exposed)

Code Studio outputs render inside a sandboxed iframe (CSP-locked,
allowed CDNs whitelisted). The iframe is **isolated from the host
stylesheet** — parent `--accent` etc. do **not** flow in by default.

To keep the canvas palette aligned with the active Wiii theme
(light/dark mode, per-org branding, accessibility contrast tweaks),
Wiii ships a small theme-inheritance bridge between the host and every
visual frame.

## How the bridge works

1. **Host side** — `InlineVisualFrame.tsx::readHostThemeOverrides()`
   reads a curated subset of Wiii host CSS variables from
   `document.documentElement.computedStyle`:

   | Host variable        | → Iframe variable           |
   |----------------------|------------------------------|
   | `--accent`           | `--wiii-accent`              |
   | `--surface`          | `--wiii-bg`                  |
   | `--surface-white`    | `--wiii-panel`               |
   | `--border`           | `--wiii-border`              |
   | `--text`             | `--wiii-text`                |
   | `--text-secondary`   | `--wiii-text-secondary`      |
   | `--text-tertiary`    | `--wiii-muted`               |

2. **Iframe `:root` defaults** — `buildVisualFrameDocument` ships a
   conservative palette so the iframe is renderable on its own
   (download HTML, share with peers, preview in another browser tab).
   The defaults are overwritten by step 1's values in the cascade.

3. **Generated code** — every color, font, and shadow declaration reads
   through `var(--wiii-*, fallback)` so it picks up either the host
   override or the iframe default in deterministic order.

## Generated-code palette

When you emit `code_html`, prefer this palette:

| Purpose                  | Variable                            | Conservative fallback |
|--------------------------|-------------------------------------|-----------------------|
| Primary action / accent  | `var(--wiii-accent, #b85a33)`       | warm orange           |
| Body text                | `var(--wiii-text, #1c1917)`         | near-black            |
| Secondary text / hints   | `var(--wiii-text-secondary, #5b4a4a)` | warm grey           |
| Muted / placeholder      | `var(--wiii-muted, #5f5a52)`        | warm grey             |
| Surface (cards, panels)  | `var(--wiii-bg, #fcfaf6)`           | warm cream            |
| Border / divider         | `var(--wiii-border, rgba(161,145,127,0.26))` | warm tint    |
| Body sans-serif font     | `var(--wiii-body, "Manrope", system-ui, sans-serif)` | Manrope    |
| Display / serif font     | `var(--wiii-display, "Newsreader", Georgia, serif)` | Newsreader   |

## Scaffold-specific kind-namespaced variables

For graceful-fallback canvases (`code_studio_template_scaffold.py`),
additional namespaced variables exist so each kind has its own palette:

```css
/* Literary scaffold */
--wiii-scene-sky-deep   /* gradient — top */
--wiii-scene-sky-mid    /* gradient — mid */
--wiii-scene-sky-warm   /* gradient — warm band */
--wiii-scene-sand       /* gradient — base */
--wiii-scene-fg         /* foreground */
--wiii-scene-caption-fg /* caption text */

/* Physics scaffold */
--wiii-phys-bg-light    /* radial — bright center */
--wiii-phys-bg-mid      /* radial — middle ring */
--wiii-phys-bg-warm     /* radial — outer warmth */
--wiii-phys-fg          /* rod / text */
--wiii-phys-axis        /* axis line */
--wiii-phys-bob-light   /* bob highlight */

/* Math scaffold */
--wiii-math-bg-light    /* gradient — top */
--wiii-math-bg-warm     /* gradient — base */
--wiii-math-fg          /* axis + text */
--wiii-math-grid        /* grid lines */

/* Default scaffold */
--wiii-default-bg-light /* gradient — top */
--wiii-default-bg-warm  /* gradient — base */
--wiii-default-fg       /* foreground */

/* History / celestial (Sprint 35i) */
--wiii-history-bg-deep  --wiii-history-fg
--wiii-celestial-bg-deep --wiii-celestial-fg
```

These are optional — the scaffold ships with calibrated fallbacks. Hosts
who want a fully bespoke palette inject all four ramps; hosts who accept
Wiii defaults touch only `--wiii-accent` / `--wiii-text-*`.

## Mobile responsive contract

Every scaffold ships an `@media (max-width: 480px)` block that:

- Switches `aspect-ratio` from 16/9 → 4/3 to keep content readable on
  iPhone SE (375px) and similar narrow viewports.
- Reduces inset padding from 24px → 14px.
- Drops base font-size by ~1px so caption fits two lines without
  ellipsis.

Generated code should follow the same shape: prefer `aspect-ratio` over
fixed pixel heights, use `clamp(min, vw-relative, max)` for character
widths, ship a 480px media query for any animation that uses pixel
deltas in a `transform`.

## Accessibility contract

Every scaffold root carries a kind-specific `aria-label` describing
both the topic family AND the temporary nature of the canvas:

- Literary: `"Khung mô phỏng văn học cho {title} — màn hình tạm, Wiii sẽ mở rộng khi bạn mô tả thêm chi tiết"`
- Physics: `"Khung mô phỏng vật lý cho {title} — màn hình tạm, Wiii sẽ mở rộng khi bạn mô tả thêm chi tiết"`
- Math: `"Khung dựng đồ thị cho {title} — màn hình tạm, Wiii sẽ mở rộng khi bạn mô tả thêm chi tiết"`
- Default: `"Khung mô phỏng cho {title} — màn hình tạm, Wiii sẽ mở rộng khi bạn mô tả thêm chi tiết"`

The root also exposes `data-scaffold-kind="literary|physics|math|history|celestial|default"`
and `data-scaffold-primitive="particle_field|oscillation|timeline|function_plot|scene|data_band"`
for downstream telemetry and CSS hooks.

Generated code aimed at the same lane should follow this shape: a
single `role="img"` (or `role="status"` for non-static placeholders)
with a descriptive Vietnamese `aria-label` that names the topic and the
canvas state, plus a stable `data-*` attribute so the host can attach
CSS or analytics without parsing class names.

## Pattern reference

- `app/engine/multi_agent/code_studio_template_scaffold.py` — emitter
- `wiii-desktop/src/components/common/InlineVisualFrame.tsx` —
  `readHostThemeOverrides()` + `buildVisualFrameDocument`
- `tests/unit/test_code_studio_template_scaffold.py` — contract tests
- W3C CSS Custom Properties Cascade (Level 3) §3.2 — variable
  inheritance through nested scopes
