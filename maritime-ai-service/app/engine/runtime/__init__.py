"""Wiii native runtime — replaces LangChain/LangGraph orchestration.

Runtime Migration Epic (#207). Phase 0 lays the scaffold; Phase 1–7 fill in
messages, tools, providers, lane-first routing, harness/session split, eval
harness, and final cleanup.

Module map (incremental):
- ``lane.py``    — Phase 0 stub, full impl Phase 4 — execution lane enum
- ``spec.py``    — Phase 0 stub, full impl Phase 4 — canonical model spec

Patterns borrowed from public engineering writing as of May 2026:
- Anthropic Managed Agents — harness/session/sandbox split
- OpenAI Codex App Server — same harness drives every surface
- Unsloth — lane-first architecture + canonical model config

See ``maritime-ai-service/docs/architecture/RUNTIME-MIGRATION-FINAL-STATE.md``
for the canonical migration state.
"""
from .lane import ExecutionLane
from .spec import RuntimeModelSpec

__all__ = ["ExecutionLane", "RuntimeModelSpec"]
