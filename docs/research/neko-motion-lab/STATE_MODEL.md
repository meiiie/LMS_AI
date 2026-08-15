# Neko motion state model v0.1

## Contract

The runtime owns facts. The mascot only reflects them. Each transition runs
from the current presentation value, can be interrupted immediately, and
settles to a static pose.

| State | Runtime evidence | Pose | One-shot motion | Settle |
| --- | --- | --- | --- | --- |
| `ready` | session available, no turn running | Peek | one slow arrival blink | centered |
| `listening` | user is composing or voice input is active | Peek | slight forward attention | centered |
| `thinking` | model turn/reasoning is active | Tilt | one 7° tilt and gaze shift | tilted |
| `tool-running` | a tool call has started | Peek | one restrained tail pulse | centered |
| `success` | turn or task completed | Mochi semantics | one small lift | centered |
| `attention` | permission or user input is required | Tilt | opposite tilt; optional external Sky dot | tilted |
| `idle` | paused, suspended, or intentionally inactive | Nap semantics | lower and close eyes once | still |
| `recover` | reconnect/restart completed or error UI is visible | Peek | return to neutral | centered |

`error` is not a face. Wiii maps an error event to `recover` while adjacent UI
text and color describe the failure. This preserves dignity and avoids a mascot
performing distress.

## Inputs

The renderer receives only normalized, bounded values:

- `state`: one of the eight states above;
- `energy`: `0..1`, scales amplitude but never changes identity;
- `gazeX`, `gazeY`: `-1..1`;
- `eyeOpen`: `0.12..1` so eyes remain capsule/slit geometry;
- `tilt`: `-8..8` degrees;
- `tail`: `-1..1`, a small front-sweep transform;
- `reducedMotion`: boolean; removes nonessential translation/rotation/scale;
- `eventId`: changes only for an intentional one-shot reaction.

## Event mapping

```text
session ready / turn settled       -> ready
composer focus / voice listening   -> listening
model delta / reasoning start      -> thinking
tool call start                    -> tool-running
turn complete                      -> success -> ready
permission request / clarification -> attention
manual pause / inactive session    -> idle
reconnect / visible error          -> recover -> ready
```

Timeouts never promote a state. If completion evidence is absent, the mascot
must not animate success.

## Production renderer boundary

A future Rive View Model should expose the same normalized fields and a small
set of triggers (`blink`, `tailPulse`, `complete`). A `.riv` file must not own
network timing, infer tool success, or keep autonomous loops alive when its
host state is settled.
