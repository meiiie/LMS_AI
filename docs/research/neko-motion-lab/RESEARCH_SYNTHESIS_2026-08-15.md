# Neko companion motion research

Cutoff: 2026-08-15. This document separates verified platform/runtime facts
from design inference.

## What is verified

- xAI documents Grok Companions as a consumer-app capability. Its public FAQ
  is useful for product-surface context, but does not publish a production
  animation rig or state graph: <https://docs.x.ai/grok/faq>
- Rive state machines combine animation timelines, transitions, and runtime
  inputs. Data Binding exposes View Models whose properties can be updated by
  runtime code or state machines: <https://rive.app/docs/runtimes/state-machines>
  and <https://rive.app/docs/runtimes/data-binding>
- Motion supports physical spring transitions, mid-flight retargeting, and an
  OS-aware `useReducedMotion` hook: <https://motion.dev/docs/react-transitions>
  and <https://motion.dev/docs/react-use-reduced-motion>
- Utsuwa is an open-source companion experiment using a 3D VRM character,
  lip-sync, expression states, and a desktop overlay. It is a useful systems
  comparison, not a Neko visual reference:
  <https://github.com/The-Lab-by-Ordinary-Company/utsuwa>
- Bunraku describes the difficulty of converting a single character image into
  a structured Live2D-ready asset. That supports building a parametric behavior
  contract before committing to a production authoring format:
  <https://arxiv.org/abs/2607.27348>

## Design inference for Neko

The useful quality in modern companions is not “more animation.” It is a tight
loop between real agent state and a small, legible response:

```text
runtime fact -> semantic Neko state -> one interruptible gesture -> settle
```

Neko therefore needs two layers:

1. a renderer-independent behavior model owned by Wiii; and
2. a renderer adapter (SVG now, Rive/Live2D/3D later) that cannot invent state.

This avoids coupling Wiii to one animation file and prevents animation from
claiming that the model is listening, thinking, or finished when the runtime
has not emitted that fact.

## What not to copy

Public demos and community recordings of Grok companions can help reviewers
notice contextual reactions and autonomous idle behavior. They are anecdotal
evidence, not an implementation specification. Neko does not copy another
product's silhouette, gestures, outfits, voice, or relationship framing.

## Chosen implementation

The first lab uses Motion and an SVG rig because both already ship in Wiii
Desktop and the SVG preserves exact approved paths. It deliberately postpones
a `.riv`, Live2D, or VRM production asset until motion tests prove which
parameters are actually needed. The state contract is designed so a future
Rive View Model can bind to the same values without changing product logic.
