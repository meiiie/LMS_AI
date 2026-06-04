# LinkedIn Operator (Wiii)

Status: Active
Owner: Project leadership
Last updated: 2026-06-01

## Purpose

Maintain the owner’s LinkedIn presence for Wiii and related AI/product engineering work:

- Improve profile clarity, credibility, and positioning.
- Publish a steady stream of **evidence-based** posts about verified milestones.
- Keep tone professional, practical, and non-inflated.

## Guardrails

- **No DMs, no connection requests, no outreach automation.**
- Posts must be grounded in **verifiable repository evidence** (merged PRs, tests, docs, tagged releases, demo runbooks).
- Do not claim production scale, customer adoption, or revenue unless a public source exists.
- Avoid vendor/partner name-dropping unless it’s already in repo docs or public announcements.
- Never post secrets, access instructions, private URLs, internal logs, screenshots containing private data, or customer info.

## Content pillars (priority order)

1. **Agentic RAG engineering**: memory boundaries, tool execution safety, citations, tenant isolation, streaming UX.
2. **Education technology**: LMS integration patterns, campus/VMU concepts, evaluation/feedback loops.
3. **3D simulation / digital twins**: simulation-as-understanding, runtime constraints, learn-by-seeing artifacts.
4. **Concrete milestones**: “what shipped”, “what we learned”, “what we’re validating next”.

## Evidence standard

Every post must reference at least one of:

- A specific merged change set (commit/PR title) and what it enabled.
- A test suite added/updated and what risk it reduced.
- A doc/runbook updated and what workflow it clarified.

Avoid “AI will change everything” claims; prefer **mechanics** (boundaries, contracts, invariants, failure modes).

## Operating workflow (weekly)

1. **Profile baseline check**
   - Review `docs/operations/LINKEDIN_PROFILE_BASELINE.md` and track any gaps.
2. **Progress scan**
   - `git log --since "<last_run_date>" --date=short --pretty=oneline`
   - Identify 1–2 changes that are:
     - understandable to a broad technical audience,
     - meaningful (risk reduction, UX improvement, safety boundary),
     - demonstrably real (tests/docs/code).
3. **Draft**
   - 6–14 lines, 1 clear takeaway, 1 short list max.
   - Use plain language; minimize acronyms; expand the first mention.
4. **Quality gates**
   - Clear: What changed? Why? What’s next?
   - Honest: No unverified claims.
   - Safe: No sensitive details.
5. **Publish**
   - Publish **at most 1 post** per run unless explicitly requested.

## Post template

- Hook: a practical engineering problem (1–2 lines).
- What we built/changed: 2–4 bullets.
- Why it matters: 1–2 lines.
- Next step: 1 line.
- Close: 2–4 relevant hashtags (keep consistent).

Suggested hashtags (rotate, don’t spam): `#AgenticAI #RAG #LLM #MCP #EdTech #DigitalTwins #Tauri #FastAPI`
