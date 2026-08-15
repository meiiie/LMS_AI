# Generation record

All raster concepts in this folder were produced with OpenAI's built-in
`imagegen` tool on 2026-08-15. No external logo is included in these assets.
Reference images were used only for broad quality attributes or to preserve the
approved Neko identity.

## Approved four-pose board

```text
Use case: logo-brand
Asset type: premium cute mascot and desktop app-icon exploration for Wiii / Neko Chill.
Primary request: Reimagine the previous serious NEKO FOLD direction as a genuinely adorable, warm, quietly playful cat companion. Create one polished 2x2 concept sheet with four ORIGINAL directions. The result should trigger an immediate gentle smile, while still feeling like a world-class consumer AI product—not corporate, stern, childish, or cheap.
Input images: Image 1 is the previous NEKO FOLD identity board. Treat it as a concept seed and material-quality reference only. Preserve the ideas of one reduced silhouette, warm ivory soft surface, graphite facial cutouts, and premium industrial-design finish; do not merely duplicate its exact form.
Cute design language: compact soft proportions; slightly oversized face area; tiny rounded ear gestures; eyes spaced wider and placed lower; a subtle head tilt, peek, tuck, or curl; expression from pose and eyes; tactile but app-icon simple.
Directions: NEKO PEEK, NEKO MOCHI, NEKO NAP, and NEKO TILT.
Style: premium soft-touch 3D industrial character design using warm milk ivory, cocoa graphite, fog gray, and one restrained pale-blue or muted-peach accent.
Constraints: original, unmistakably feline, approachable, readable at 24–32 px; no mouth, whiskers, detailed fur, anime, giant sparkling eyes, blush, hostile/sad expression, ghost/skull resemblance, glossy toy plastic, square backing, extra text, or watermark.
```

## Neko Peek transparent master source

```text
Use case: logo-brand
Asset type: master mascot cutout source for the approved Wiii / Neko Chill identity.
Primary request: Render a single, identity-locked NEKO PEEK mascot matching the approved top-left character: a shy-curious warm-ivory cat head peeking from inside its own thick curled graphite tail. Preserve the compact proportions, softly blunted ears, wide-spaced vertical oval charcoal eyes, low cozy posture, and tail sweeping across the foreground.
Scene: perfectly flat uniform #00FF00 chroma key; no floor, horizon, gradient, texture, reflection, vignette, shadow, halo, or lighting variation.
Style: warm milk-ivory satin ceramic cat, cocoa-graphite velvety tail, subtle form shading only on the mascot, crisp antialiased edges.
Composition: centered front three-quarter view on a square canvas with generous even padding.
Constraints: exactly two eye apertures; no mouth, nose, whiskers, paws, text, label, app tile, objects, watermark, green spill, redesign, extra ears, or extra tail.
```

The chroma source is converted locally with the installed imagegen
`remove_chroma_key.py` helper using border auto-key detection, soft matte, and
despill. All downstream icon sizes are generated deterministically by
`scripts/export_neko_family.py`.
