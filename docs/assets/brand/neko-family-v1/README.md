# Neko Family v1

Status: **approved visual direction** on 2026-08-15.

This folder is the canonical design workspace for the cute Neko identity used
by Wiii and Neko Chill. The four approved images are not four unrelated
characters. They are one companion, **Neko**, shown in four poses.

## Brand architecture

- **Wiii** is the product name.
- **Neko** is the companion identity inside the product.
- **Neko Peek** is the primary logo, app icon, avatar, and default listening
  pose.
- **Neko Mochi**, **Neko Nap**, and **Neko Tilt** are supporting mascot poses.

The primary mark is intentionally more expressive than a conventional
developer-tool logo. Its curled tail communicates safety and continuity while
the peeking cat makes the agent approachable.

## Folder map

```text
neko-family-v1/
|-- README.md                 Start here
|-- BRAND_SYSTEM.md           Meaning, roles, palette, states, and rules
|-- PROMPTS.md                Generation provenance and reproducible briefs
|-- manifest.json             Generated asset inventory and SHA-256 hashes
|-- source/                   Approved board and lossless generation sources
|-- concepts/                 The four approved pose crops
|-- mascot/                   Transparent Neko Peek master
|-- logo/                     SVG marks, wordmark, PNG sizes, and Windows ICO
|-- previews/                 Light/dark validation renders
|-- social/                   Rounded README banner and 1200x630 social card
`-- scripts/                  Deterministic export pipeline
```

## Rebuild exports

From the repository root:

```powershell
python docs/assets/brand/neko-family-v1/scripts/export_neko_family.py
node docs/assets/brand/neko-family-v1/scripts/render_svg_previews.mjs
node docs/assets/brand/neko-family-v1/scripts/render_social_surfaces.mjs
python docs/assets/brand/neko-family-v1/scripts/verify_neko_family.py
```

After approval, synchronize the verified assets into Wiii Desktop:

```powershell
python docs/assets/brand/neko-family-v1/scripts/sync_wiii_desktop_brand.py --apply
```

The exporter never writes into the shipping application icon folders. Product
integration should be a separate reviewed change after visual approval at
16 px, 24 px, 32 px, light theme, and dark theme.

## Recommended files

- Product/app icon master: `logo/png/neko-peek-icon-1024.png`
- Windows multi-resolution icon: `logo/neko-peek.ico`
- UI/vector mark: `logo/neko-peek-mark.svg`
- Single-color fallback: `logo/neko-peek-mark-mono.svg`
- Horizontal lockup: `logo/neko-peek-wordmark.svg`
- Mascot/animation master: `mascot/neko-peek-master.png`
- GitHub README banner: `social/wiii-readme-banner.png`
- Open Graph/social preview: `social/wiii-social-card.png`

## Motion research

The interactive behavior lab and current expression research live at
`docs/research/neko-motion-lab/`. Open Wiii Desktop with
`?preview=neko-motion` to inspect the state contract without starting auth,
chat, or an agent runtime.
