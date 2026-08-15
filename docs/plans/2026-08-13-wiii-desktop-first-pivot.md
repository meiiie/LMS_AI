# Wiii Desktop-First Pivot (superseded)

> Superseded on 2026-08-16 by the
> [Unified Workbench architecture](../architecture/WIII_UNIFIED_WORKBENCH.md).
> Desktop remains local-first, but hosted web is now a supported remote-authority
> host rather than a maintenance-only product fork. This file is retained only
> as decision history.

Status: Superseded (2026-08-16)

Owner: Maintainer; execution delegated to the engineering agent with standing
authority (see issue for provenance).

## The decision

Wiii's primary product surface is the **desktop app** (`wiii-desktop/`, Tauri
v2). The previous strategic direction — web-app delivery (browser build,
iframe/embed, LMS-hosted surfaces) — is **demoted to maintenance**: kept
working, no longer driving architecture or feature decisions.

This continues the simplification program (architecture audit → technical
simplification roadmap → runtime-migration completion #207) under one thesis:

> Wiii is a desktop-first AI companion. One native app, two engines:
> **Neko Chill** (local ACP agents, no account — #886) and **Wiii Cloud**
> (the personal assistant backend). Everything that does not strengthen that
> app must justify its complexity or leave.

## Why

- The desktop client had become the starving surface while the platform
  accumulated first-class subsystems faster than they could be kept coherent
  (audit 2026-08-12: 143 feature flags — 24 foundational, 28 production,
  **82 experimental**, 9 dormant).
- Neko Chill v0 (5 merged PRs, #886) proved the desktop-first thesis: a
  no-login local mode with real product value shipped in two days because the
  desktop shell, not the platform, was the unit of work.
- Single-maintainer reality: one coherent product beats three delivery
  surfaces (README already records the operational cost of embed/LMS image
  pipelines, bypass governance, evidence workflows).

## What changes

1. **Product defaults become desktop-first.** Fresh installs land in the
   no-login Neko Chill mode; the cloud account is opt-in. Signed-in users are
   unaffected (persisted mode/auth wins).
2. **Web/embed/LMS surfaces: demote, do not delete (yet).** Builds and deploy
   images keep working; they receive fixes only. Any removal happens as its
   own evidenced wave (usage data or maintainer confirmation) — never as a
   side effect.
3. **Complexity-cut waves continue** on the flag-tier evidence base:
   - Wave 1: the 9 DORMANT flags — delete or archive each with a per-flag
     verdict; EXPERIMENTAL flags triaged (dead bets deleted, active bets get
     an owner note).
   - Waves follow the #207 model: narrow PRs, feature-tier guard green, full
     unit gates, honest CHANGELOG entries.
4. **Backend serves the app.** `maritime-ai-service` is the cloud engine
   behind the desktop app (and the demoted surfaces). Stabilization order:
   green the baseline (#210, #120), then flag demotion, then measured
   extraction — per the existing simplification roadmap. No rewrites.
5. **Desktop quality bar rises.** The red desktop baseline items
   (sprint120 router-registration FastAPI drift) get fixed, not tolerated;
   #891 (transcript virtualization) and installer/branding polish join the
   product backlog.

## Non-goals

- No deletion of embed/LMS/web code in this pivot document — demotion only.
- No backend rewrite in any language (standing decision, 2026-08-12).
- No change to the Neko Chill guardrails (no-login, own stores, fail-closed
  permissions — spec `specs/731-neko-chill-mode/`).

## Sequencing (living list — checked items link their PRs)

- [ ] Desktop-first landing: fresh installs open Neko Chill (mode default
      resolves against persisted auth), cloud opt-in.
- [ ] Green the desktop baseline: sprint120 router-registration failures.
- [ ] Complexity wave 1: DORMANT flag verdicts (9 flags).
- [ ] Complexity wave 2+: EXPERIMENTAL triage in evidence-sized batches.
- [ ] Wiii-cloud driver as the second DriverEvent backend inside the desktop
      app (superapp convergence — one client, both engines).
- [ ] Desktop polish backlog: #891, installer/branding, first-run experience.
