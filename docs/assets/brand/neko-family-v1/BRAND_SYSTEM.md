# Wiii + Neko brand system v1

## 1. Core idea

**A capable little companion that protects the work around you.**

Neko's graphite tail wraps around the ivory cat like a safe workspace. The cat
peeks over it rather than standing above the user, which makes the relationship
collaborative instead of authoritative. The form is cute because of posture,
proportion, and curiosity—not because of decorative kawaii features.

## 2. One Neko, four poses

| Pose | Product meaning | Recommended surfaces |
| --- | --- | --- |
| **Peek** | Present, listening, ready | App icon, product mark, navigation, welcome state |
| **Mochi** | Comfortable, complete, available | Success, task complete, friendly empty state |
| **Nap** | Resting without disappearing | Idle, paused, offline, suspended session |
| **Tilt** | Curious, checking, needs attention | Thinking, inspecting, clarification, reconnecting |

Do not present the four poses as separate named agents. They are behavioral
states of the same Neko.

## 3. Primary logo: Neko Peek

The mark has three essential parts:

1. A warm-ivory cat with two softly rounded ears.
2. Two widely spaced graphite capsule eyes.
3. One cocoa-graphite tail that wraps behind and sweeps across the foreground.

The tail is the ownable element. Removing it turns the mark into a generic cat
head, so it must remain visible in primary uses.

### Logo variants

- Use `neko-peek-mark.svg` on light or warm neutral surfaces.
- Use `neko-peek-mark-on-dark.svg` on charcoal surfaces.
- Use `neko-peek-mark-mono.svg` for one-color printing and very small UI.
- Use `neko-peek-wordmark.svg` when the Wiii name is not already visible.
- Use the rendered PNG/ICO app icon for OS launchers; do not place the raw
  transparent mascot directly on an uncontrolled desktop background.

## 4. Palette

| Token | Hex | Role |
| --- | --- | --- |
| Milk | `#F5F0E6` | Neko body and warm light surfaces |
| Cocoa | `#2A2928` | Tail, eyes, primary dark ink |
| Cocoa Lift | `#454241` | Front tail sweep in the flat color mark |
| Fog | `#A9A6A6` | Neutral app-icon environment |
| Mist | `#E7E3DE` | Light background and highlight |
| Sky | `#BBDDF2` | Optional live/status accent only |

Sky is a state accent, not a decorative gradient. Do not recolor Neko per
feature or provider.

## 5. Scale and clear space

- Keep clear space equal to at least one eye width around the flat mark.
- Use the mono mark below 24 px when the full material icon becomes muddy.
- At 24–48 px, preserve both eyes and the front tail sweep; remove microtexture
  before changing the silhouette.
- Use the 3D mascot only at 32 px or larger.
- Never stretch, crop the ears, or let the tail touch a container edge.

## 6. Motion and state language

Motion should be soft, brief, and interruptible.

| Agent state | Neko behavior |
| --- | --- |
| Ready/listening | Peek; one slow blink after arrival |
| Thinking | Tilt by 6–8 degrees; eyes shift once toward the workspace |
| Tool running | Peek; tail gives one restrained settling pulse |
| Completed | Mochi; tiny ease-out lift, then rest |
| Idle/paused | Nap; no continuous animation |
| Needs input | Tilt; optional single Sky status point outside the face |
| Error | Keep the same mascot; communicate failure in UI text/color, not a sad face |

Avoid perpetual bobbing, spinning, talking mouths, exaggerated squash, or
attention-seeking loops. Reduced motion must disable all nonessential motion.

## 7. Voice and personality

Neko is warm, concise, curious, and capable. Cute visual language must not make
the product sound infantile. Avoid baby talk, excessive exclamation marks,
animal noises, or treating the user as Neko's owner.

## 8. Do and do not

### Do

- Preserve the approved ivory/graphite relationship.
- Keep expressions in the eyes and pose.
- Use Peek as the stable product identifier.
- Use the other poses to clarify agent state.
- Keep the silhouette readable without texture.

### Do not

- Add a mouth, nose, whiskers, paws, fur, blush, costume, or accessories.
- Give Neko anime eyes, pupils, eyebrows, or angry/sad expressions.
- place the mark on a dark tile where the graphite tail disappears.
- turn every pose into a separate logo.
- replace the Wiii product name with Neko without a separate naming decision.
- use externally supplied reference art as a shipping asset.

## 9. Accessibility

- Mascot imagery is decorative unless it communicates an agent state.
- Decorative instances use empty alt text and `aria-hidden="true"`.
- State-bearing instances require adjacent text; never rely on pose or color
  alone.
- Keep foreground/background contrast sufficient around the tail outline.
- Do not animate more than once without direct user action.

## 10. Release surfaces

- The README banner uses a wide rounded rectangle with Neko Peek, the Wiii
  wordmark, one durable-workbench statement, and a restrained capability line.
- The 1200×630 social card uses the same hierarchy with less detail so it stays
  legible in link previews.
- Social graphics must be rendered from the checked-in SVG sources. Do not use
  generated typography or substitute mascot art.
- Keep Wiii as the product name and Neko as the companion. Do not put Neko Chill
  in the platform-level wordmark.

## 11. Implementation contract

The files in this folder are the canonical brand source. Shipping derivatives
are updated only through the synchronization and renderer scripts. Integration
must:

1. use the provided size-specific exports;
2. verify Windows title bar, taskbar, Start menu, installer, favicon, and tray;
3. visually check light/dark backgrounds at native size;
4. keep Neko pose changes driven by real agent state; and
5. preserve a text label or tooltip wherever icon meaning is not obvious.
