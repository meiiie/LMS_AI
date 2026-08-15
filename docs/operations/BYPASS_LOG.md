# Wiii Branch Protection Bypass Log

Required by `docs/operations/WIII_BRANCH_PROTECTION.md`, section "Bypass and emergency repair".

Every bypass event is appended here within 24 hours. Format:

```
### <date> — <actor> — <branch>

- Reason:
- Linked incident / ticket:
- Protection change applied:
- Merged PRs / commits produced during bypass:
- Re-enable confirmation:
- Follow-up:
```

---

## 2026-04-24 — @meiiie — main

- **Reason**: Initial self-merge after branch protection was activated on `main` (CodeRabbit required status, 1 approving review, code owner review, require-last-push-approval). The repo had a single code owner (@meiiie) who was also the author of both PRs. GitHub forbids a PR author from self-approving, so the protection could not be satisfied by any in-workflow action. Two PRs were blocked.
- **Linked incident / ticket**: None (initial setup — PRs were #6 and #7). Future events should link a GitHub issue.
- **Protection change applied**: `DELETE /repos/meiiie/wiii/branches/main/protection` to temporarily remove all rules. Original config was captured via `GET` before the delete and restored verbatim after the merges via `PUT`.
- **Merged PRs / commits produced during bypass**:
  - PR #6 — `docs + chore: governance gap close + naming migration (CoC, Dependabot, agent template, branch protection)` — merged as squash commit `4c29c4e`.
  - PR #7 — `fix + feat: demo stabilization bundle (Gemini 2.5 compat, magic-link dev, admin embed, SOTA search)` — merged as squash commit `db0efe2`.
- **Re-enable confirmation**: `PUT /repos/meiiie/wiii/branches/main/protection` succeeded with the exact pre-bypass payload. `gh api repos/meiiie/wiii/branches/main/protection` post-restore shows `required_status_checks.contexts: ["CodeRabbit"]`, `enforce_admins.enabled: true`, `required_pull_request_reviews.required_approving_review_count: 1`, `require_last_push_approval: true`, `require_code_owner_reviews: true`, `required_conversation_resolution.enabled: true`. Configuration matches pre-bypass verbatim.
- **Follow-up** (resolved same day):
  - Added **@wiiiii123** as `write` collaborator (invitation ID 316160239, sent 2026-04-24 15:49 UTC). @wiiiii123 is an existing second GitHub account belonging to the same maintainer; using it as a second code owner avoided the overhead of provisioning a new bot identity.
  - Updated `.github/CODEOWNERS` to list `@meiiie @wiiiii123` on every path — OR semantics means either can approve any PR they are not the author of.
  - Updated `docs/operations/WIII_BRANCH_PROTECTION.md` with a dedicated "Second code owner — avoiding the self-approval deadlock" section describing the pattern.
  - @wiiiii123 accepted the collaborator invitation later the same day and is now listed with `write` role.

---

## 2026-04-24 (second event) — @meiiie — main

- **Reason**: Even after @wiiiii123 accepted the collaborator invitation, GitHub's "require review from Code Owners" gate reads `CODEOWNERS` from the **base branch** (main). Until the updated CODEOWNERS (listing @wiiiii123) was actually present on main, an approval from @wiiiii123 on PR #25 would not satisfy the gate — only @meiiie's would, and @meiiie cannot self-approve. A second bypass was needed to land the CODEOWNERS update itself.
- **Linked incident / ticket**: PR #26 (`docs(governance): bring @wiiiii123 code-owner + bypass log onto main`).
- **Protection change applied**: same procedure as the first event — `GET` current protection, `DELETE`, merge, `PUT` original config back.
- **Merged PR / commit produced**: PR #26 merged as squash commit `a14757d`. Contains: `.github/CODEOWNERS` (adds @wiiiii123), `docs/operations/WIII_BRANCH_PROTECTION.md` (adds "Second code owner" section), `docs/operations/BYPASS_LOG.md` (initial file with the first event recorded).
- **Re-enable confirmation**: Protection restored from the pre-bypass snapshot. All fields verbatim: `enforce_admins: true`, `require_code_owner_reviews: true`, `required_approving_review_count: 1`, `require_last_push_approval: true`, `required_status_checks.contexts: ["CodeRabbit"]`, `required_conversation_resolution: true`.
- **Follow-up**:
  - Every subsequent PR (including the still-open PR #25 for CI stabilization and the Dependabot queue) can now merge via the normal workflow: @wiiiii123 approves PRs authored by @meiiie, and vice versa.
  - PR #25 and PR #27 were subsequently merged on 2026-04-25 after the admin-override policy change (see below).

---

## 2026-04-25 — Policy change, not a bypass event

Not strictly a bypass event, but recorded here so the audit trail is complete.

Rationale: on review, the maintainer decided that routing every @meiiie-authored PR through @wiiiii123 added more friction than review-value, given there is only one architectural owner. See `WIII_BRANCH_PROTECTION.md` → "Admin override policy" for the full rationale.

Change applied:

- `enforce_admins` flipped from `true` to `false` on `main`.
- Admins (@meiiie) can now `gh pr merge --admin --squash` without a second approval.
- Non-admins (@wiiiii123, Dependabot, future collaborators) remain bound by review, status checks, signed commits, and conversation resolution.
- CodeRabbit continues to run on every PR; its commit status is the primary pre-merge signal when @meiiie self-reviews.

Immediate merges enabled by this change:

- PR #25 (CI stabilization, 55 files) — merged as squash commit `61d6e3a`.
- PR #27 (bypass-log entry for 2026-04-24 event #2) — merged as squash commit `e5accaf`.

This is reversible. If the admin-override policy is rescinded (see "When to reconsider" in the policy doc), flip `enforce_admins` back to `true` via `gh api -X PUT` on the protection endpoint.

---

## 2026-08-16 — Owner-directed review-policy migration — main

This was a deliberate policy change with an immediately corrected configuration gap, recorded here for a complete audit trail.

- **Authority and ticket**: repository owner direction; issue #925.
- **Intent**: retain PR traceability and required CI while removing mandatory approval, CODEOWNERS approval, and last-push approval. `@wiiiii123` remains an ownership contact, not a mechanical merge token.
- **Initial change**: `DELETE .../required_pull_request_reviews` removed the approval block. This also temporarily removed the classic-protection PR requirement and was broader than intended.
- **Correction**: `PATCH .../required_pull_request_reviews` restored the PR requirement with `required_approving_review_count: 0`, `dismiss_stale_reviews: false`, `require_code_owner_reviews: false`, and `require_last_push_approval: false`.
- **Merge activity during the gap**: PR #924 was merged through GitHub's PR flow only after `Gate Summary`, all independent CI jobs, and all review conversations were green/resolved. No direct push, force-push, or branch deletion occurred.
- **Final verification**: strict required status `Gate Summary`; PR block present with zero approvals; conversation resolution and linear history enabled; force-push and deletion disabled; `enforce_admins: false` retained.
- **Rollback**: patch the same endpoint to `required_approving_review_count: 1` and re-enable the desired review flags, then update the policy documents in a PR.

---
