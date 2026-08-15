# Neko Motion Lab

Status: active research surface, 2026-08-15.

This is the canonical workspace for researching how the approved Neko family
behaves. It does not create a fifth mascot and it does not replace the approved
brand assets in `docs/assets/brand/neko-family-v1/`.

## Open the live lab

```powershell
cd wiii-desktop
npm run dev
```

Then open `http://localhost:1420/?preview=neko-motion`.

The preview is standalone: it does not initialize auth, chat, polling, Neko
Core, or cloud stores. It provides:

- eight explicit behavior states;
- a material render and a parametric vector rig;
- manual gaze, energy, blink, tail, and spring controls;
- pointer-follow experiments with an immediate opt-out;
- an autoplay sequence that is off by default;
- an OS-aware reduced-motion override;
- a chronological event ledger for comparing motion decisions.

## Files

- `RESEARCH_SYNTHESIS_2026-08-15.md`: sourced product and runtime findings.
- `STATE_MODEL.md`: behavior contract and runtime event mapping.
- `EXPERIMENT_PROTOCOL.md`: repeatable review checklist.
- `neko-motion-keyframes-01.png`: generated expression study; research only.
- `wiii-desktop/src/neko-motion-lab/`: executable lab and pure state model.

## Non-negotiable identity lock

Every experiment is one approved Neko. Keep the body, tail, eyes, silhouette,
palette, and no-mouth facial grammar unchanged. Motion may change perceived
attention; it must not invent anatomy. References to Grok companions describe
interaction qualities only, never a license to copy their character design.

## Promotion gate

Nothing in this directory is a shipping mascot animation by default. Promote
an experiment only after all of the following are true:

1. product state and interruption behavior are defined;
2. reduced motion communicates the same status in adjacent text;
3. the motion settles and consumes no idle animation frame budget;
4. native-size review passes at 24, 32, 48, and 96 px;
5. the project owner explicitly approves the motion family.
