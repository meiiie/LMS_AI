# Wiii Understand-Anything Flow Map

This wrapper lets Wiii maintainers run the deterministic parts of
Understand-Anything against a scoped Wiii flow without committing generated
graphs or making Understand-Anything a runtime dependency.

It uses the ignored local reference checkout by default:

```text
.Codex/external/reference-systems/understand-anything/understand-anything-plugin
```

Generated output is written to:

```text
.understand-anything/tmp/
```

## Commands

List available flow profiles:

```powershell
python tools/wiii_understand_harness/run_wiii_understand_flow_map.py --list-profiles
```

Run the LMS document preview/apply profile:

```powershell
python tools/wiii_understand_harness/run_wiii_understand_flow_map.py --profile lms-document-preview
```

Run from an existing scan file when you only need to refresh the scoped import
map:

```powershell
python tools/wiii_understand_harness/run_wiii_understand_flow_map.py --profile chat-baseline --scan-input .understand-anything/tmp/wiii-flow-map-chat-baseline-scan.json
```

## Guardrails

- The wrapper does not run the full LLM graph workflow.
- The wrapper does not enable Understand-Anything auto-update.
- Output remains ignored under `.understand-anything/`.
- The generated summary is a navigation aid, not proof of runtime behavior.
- Runtime safety still comes from Wiii Self-Harness, focused tests, browser E2E,
  and LMS preview/apply acceptance.
