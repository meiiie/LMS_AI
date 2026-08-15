# Neko motion experiment protocol

Use the live lab at `?preview=neko-motion`. Record the date, viewport, OS motion
setting, render mode, state, and parameter values for every accepted result.

## Review sequence

1. Start with autoplay off and pointer following off.
2. Trigger every state manually and interrupt it halfway with another state.
3. Confirm the second state begins from the visible pose without snapping.
4. Run the demo once; confirm it stops and settles instead of looping forever.
5. Trigger blink rapidly three times; confirm the rig does not become stuck.
6. Turn on pointer following, cross all stage edges, then turn it off and confirm
   gaze returns to center.
7. Enable simulated reduced motion and repeat every state.
8. Verify adjacent text and the event ledger communicate status without motion.
9. Review at 24, 32, 48, and 96 px before promotion.

## Acceptance thresholds

- Rotation never exceeds 8°.
- Gaze displacement never exceeds 5 SVG units.
- Entry lift never exceeds 9 SVG units at full energy.
- No default autonomous loop runs indefinitely.
- State changes remain operable during motion.
- Reduced motion removes translation, rotation, scale pulses, and autoplay.
- The mascot never gains unapproved facial or body features.
- Error/recovery remains neutral and relies on UI copy for meaning.

## Performance probes

- Animate transform and opacity; avoid layout properties.
- No requestAnimationFrame loop remains active after the pose settles.
- A future Rive renderer should pause or settle when offscreen.
- Inspect long tasks and GPU compositing in WebView2/Chrome DevTools before
  enabling any animation in the production shell.
