# Claude Code Entry Point

Status: Compatibility shim

Last updated: 2026-08-24

Claude Code agents working in Wiii must use the same canonical instructions as every other engineering agent:

1. Read `AGENTS.md` first.
2. Follow `docs/operations/WIII_GITHUB_GOVERNANCE.md` for issue, branch, PR, review, and merge workflow.
3. Use `.agents/skills/` plus the relevant `docs/` area for project-specific skills and source-of-truth context.
4. Treat local `.claude/` and `.Codex/` folders as ignored scratch space only. Do not commit them or use them as governance, runtime, memory, or architecture truth.
5. For Neko identity or motion work, read the `## Wiii + Neko Brand Memory`
   section in `AGENTS.md`, then the canonical brand and motion-lab documents it
   links. The approved Neko family must not be redesigned without explicit
   project-owner approval.
6. Read `docs/operations/WIII_AGENTIC_CODEBASE_HARNESS.md` for the layered
   context, focused-check, correction-mining, and release-truth workflow. Product
   entry and release naming invariants remain in canonical `AGENTS.md` files;
   do not duplicate or weaken them here.

The old tracked `.claude/` coordination tree was removed from `main` on 2026-05-10 as part of issue #279 so Wiii keeps one clean project control plane.
