# AI slop — anti-patterns and corrective patterns

> Source: Claude Design analysis 2026-Q1 + Wiii visual quality review

These patterns make output look "obviously AI-generated". Detect them
before shipping and prefer the corrective patterns instead.

## DO NOT

### Visual chrome

- **Gradient overuse**: do not put `linear-gradient` on every
  background. Use solid colors or at most 1–2 subtle gradients per
  output.
- **Purple-blue gradient hero**: the most recognizable AI slop pattern.
  Never use purple-blue gradients for hero/banner sections.
- **"AI card" trope**: the combination `border-radius` +
  `border-left: 4px solid <accent>` + gradient background is the most
  recognizable card pattern. Vary card styles.
- **Symmetric everything**: intentional asymmetry feels more human. Not
  every section needs equal-width columns.

### Iconography

- **Emoji in UI elements**: NEVER use emoji in buttons, headings,
  labels, or any structural UI element. Use inline SVG icons (`<svg>`)
  for play, pause, reset, check, cross, arrow indicators. The
  `visual_html_core` module provides `_svg_icon()` for standard icons.
  Emoji in user-content text (paragraphs, data cells) is acceptable
  when contextually appropriate, but the UI chrome itself must be
  emoji-free.
- **SVG drawings as imagery**: do not attempt to draw complex imagery
  (people, objects, scenes) with SVG. Use simple placeholders instead —
  a colored box with a label is better than a bad attempt at the real
  thing.

### Typography

- **Overused fonts**: avoid Inter, Roboto, Arial, Fraunces, system-ui
  as primary font. Use distinctive fonts like DM Sans, Outfit, Sora, or
  Wiii's system font stack.

### Content density

- **"Data slop"**: do not pad designs with unnecessary stats, numbers,
  icons, or metrics. Every element must earn its place. One thousand
  no's for every yes.
- **Cookie-cutter sections**: do not repeat the same heading + icon +
  description pattern for every section. Vary layout density, visual
  treatment, and composition.

## DO

### Color and typography

- Use `oklch()` for harmonious colors that match Wiii palette
  (`#D97757`, `#85CDCA`, `#FFD166`).
- Use `text-wrap: pretty` for better text rendering.
- Use typography hierarchy (size + weight + color) instead of
  decorative elements.

### Layout and structure

- Use CSS Grid, `container queries`, `subgrid` — advanced CSS is your
  friend.
- Add intentional visual variety and rhythm (different background
  colors, varied layouts).
- Prefer fewer, higher-quality elements over many filler elements.

### Imagery and icons

- Use simple colored placeholders for missing images — do not draw with
  SVG.
- Use inline SVG icons from the `_SVG_ICONS` library for common UI
  actions (play, pause, reset, check, close). Never substitute emoji
  for icon elements.

### Editorial discipline

- Every element must justify its existence — if a section feels empty,
  solve with layout not content.
- "Less is more" — a clean, focused output beats a busy, comprehensive
  one.
