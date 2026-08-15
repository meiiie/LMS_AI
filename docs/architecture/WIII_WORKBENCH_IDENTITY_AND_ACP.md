# Wiii Workbench: product identity and durable ACP boundary

Status: implemented in desktop `1.2.0` on 2026-08-15.

## Naming architecture

| Layer | Name | Meaning |
| --- | --- | --- |
| Organization | The Wiii Lab | Publisher and research/product organization |
| Platform | Wiii | Umbrella identity and stable technical namespace |
| Desktop product | Wiii Workbench | Workspace for conversations, agents, files, tools, memory, and artifacts |
| Cloud mode | Wiii Cloud | Account-backed assistant and managed services |
| Local mode | Neko Chill | No-account ACP agent workspace |
| Companion | Neko | State-bearing mascot and product guide |
| Local runtime | Neko Core | One ACP provider; not the desktop product or mascot name |

`Wiii` remains in package names, bundle identifiers, storage keys, executable
names, and upgrade metadata. Changing those technical identities during a
visual release could create a second installation or orphan local data.

Wiii is not an LMS product. LMS is a Wiii Connect adapter alongside local ACP
agents, MCP services, documents, embeds, browser surfaces, OAuth applications,
and future hosts.

## Neko Family v1 identity

The approved identity is **Neko**, a single calm companion shown in four poses.
Neko Peek is the primary product mark, application icon, avatar, and ready or
listening state. Mochi, Nap, and Tilt are completion, idle, and inspection
poses of the same character—not separate agents.

The mark combines a warm-ivory cat with two graphite capsule eyes and a
cocoa-graphite tail that wraps around the body like a protected workspace. The
tail is the ownable element and must remain visible in primary uses. Neko has no
mouth, nose, whiskers, paws, fur, pupils, eyebrows, costume, or provider color.

Canonical source:

- `docs/assets/brand/neko-family-v1/README.md` — asset map and export workflow
- `docs/assets/brand/neko-family-v1/BRAND_SYSTEM.md` — identity rules
- `docs/assets/brand/neko-family-v1/logo/` — vector marks and platform masters
- `docs/assets/brand/neko-family-v1/mascot/` — transparent animation master
- `docs/assets/brand/neko-family-v1/social/` — README banner and social card
- `docs/research/neko-motion-lab/` — state and motion research

Shipping derivatives are synchronized through
`sync_wiii_desktop_brand.py --apply`; individual PNG, ICO, ICNS, favicon, tray,
installer, or social derivatives must not be redrawn independently.

### Palette

| Token | Value | Use |
| --- | --- | --- |
| Milk | `#F5F0E6` | Neko body and warm light surfaces |
| Cocoa | `#2A2928` | Tail, eyes, primary dark ink |
| Cocoa Lift | `#454241` | Front tail sweep and secondary dark plane |
| Fog | `#A9A6A6` | Neutral icon environment |
| Mist | `#E7E3DE` | Light background and highlight |
| Sky | `#BBDDF2` | Optional status accent only |

Motion is state-driven, brief, interruptible, and reduced-motion safe. Error
states remain visually calm and communicate failure with adjacent UI text.

## Durable ACP ownership

Wiii owns the visible local transcript and append-only UI/runtime facts. The
ACP provider owns its canonical session and opaque continuation state. Wiii
persists the provider session ID as `backendSessionId` beside its local session
UUID.

On process replacement or app restart:

1. Wiii starts a new provider process.
2. If `backendSessionId` exists and the handshake advertises durable resume,
   Wiii calls `session/resume`.
3. Wiii does not call `session/load` for its already-restored local transcript;
   doing so would duplicate visible messages.
4. If resume is unavailable or fails, Wiii reports continuity loss and does not
   silently create `session/new`.
5. Intentional disposal calls `session/close` with a bounded timeout before the
   transport terminates, releasing the provider's single-writer lease.

When a provider reports `continuityLevel: recovered`, Wiii tells the user that
interrupted mutations remain `unknown outcome`. Such mutations are not retried
automatically. This is the exactly-once safety boundary for crash recovery.

`session/list` and `session/load` belong to an explicit import or history flow.
They are not an implicit fallback for ordinary Wiii-owned continuation.
