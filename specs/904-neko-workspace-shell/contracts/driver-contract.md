# Contract: Neko Chill Driver Session Capabilities

## New normalized events

- `session-controls`: complete replacement list of normalized controls.
- `available-commands`: complete replacement list of agent commands.
- `session-info`: partial display metadata update (title, updatedAt).

Every event carries the local Neko Chill session id. Stores ignore events for
unknown sessions.

## New driver operation

```ts
setConfigOption(optionId: string, value: string | boolean): Promise<void>
```

Rules:

1. Unknown option ids reject.
2. Value type/choice is validated against the last reported option.
3. Stable ACP options use `session/set_config_option`.
4. Legacy modes use `session/set_mode`.
5. Legacy Gemini models use `session/set_model`.
6. Success emits a complete `session-controls` snapshot.
7. Failure emits no changed control state.

## ACP input mapping

- `session/new.configOptions` -> stable normalized controls.
- `session/new.modes` -> legacy mode control only when no stable mode option.
- `session/new.models` -> legacy model control only when no stable model option.
- `config_option_update` -> replace stable options and re-merge fallbacks.
- `current_mode_update` -> update the legacy mode fallback.
- `available_commands_update` -> `available-commands`.
- `session_info_update` -> `session-info`.
