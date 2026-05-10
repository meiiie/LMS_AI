# Wiii x LMS Agent Coordination Protocol

Status: Draft operational protocol

Owner: Project leadership

Last updated: 2026-05-10

Applies to: Wiii repository, LMS repository, Codex workers, GitHub watchers,
cross-repository PR review, and product integration work.

## Purpose

This protocol lets two implementation agents work in parallel while a third
observer agent coordinates through GitHub. The goal is to integrate Wiii into
the Maritime LMS product safely, then support the flagship teacher flow:

```text
Teacher uploads Word/PDF
-> Wiii parses and normalizes source material
-> Wiii drafts course/lesson outline
-> Teacher reviews preview
-> LMS applies confirmed lesson patches
-> Sources remain traceable for RAG/citations
```

GitHub is the coordination bus. The agents do not need private chat with each
other; they exchange structured issue and PR comments that humans can review.

## Agent Roles

| Role | Workspace | Owns | Must not do |
|---|---|---|---|
| `wiii-agent` | `E:\Sach\Sua\AI_v1` | Wiii embed, Pointy, voice, document parsing, course-generation API, preview/apply contracts, RAG/memory | Edit LMS source directly, merge own PRs, deploy production |
| `lms-agent` | `E:\Sach\Sua\LMS_hohulili` | Angular LMS host UI, `data-wiii-id`, safe-click attributes, teacher upload UX, course editor, LMS auth/API integration | Edit Wiii source directly, merge own PRs, deploy production |
| `observer-agent` | Either workspace | Watch GitHub, detect blockers, summarize evidence, create coordination issues, request focused next steps | Auto-merge, auto-deploy, edit secrets, make unrelated code changes |

## Safety Rules

- Agents only edit their own repository.
- Agents never commit `.env*`, screenshots, local caches, generated build output,
  or secrets.
- Watchers are report-only unless run with explicit `--apply`.
- No agent merges its own PR.
- No agent deploys production without a human release owner.
- Product-changing actions must follow preview -> confirm -> apply.
- Cross-repo blockers must be represented as GitHub comments or issues, not lost
  in local chat.
- Every claim of "done" needs evidence: command output, CI link, screenshot, or
  product smoke summary.

## Labels

Use the same label vocabulary in both repositories where possible.

| Label | Meaning |
|---|---|
| `coord:watch` | The observer watcher should include this issue/PR in digests. |
| `integration:wiii-lms` | Cross-repository Wiii/LMS integration work. |
| `needs-wiii` | LMS work is blocked on Wiii contract/API/behavior. |
| `needs-lms` | Wiii work is blocked on LMS host/API/UI behavior. |
| `blocked:other-repo` | Cannot move without a partner-repo change. |
| `agent:wiii` | Wiii agent owns the next implementation step. |
| `agent:lms` | LMS agent owns the next implementation step. |
| `agent:observer` | Observer/reporting issue or PR. |

## Structured Comment Contract

Agents should post comments with this marker so watcher tooling can parse them.

```markdown
<!-- wiii-lms-sync:v1 -->
ROLE: wiii-agent
STATUS: blocked
BLOCKER: LMS course editor does not expose data-wiii-id on lesson toolbar.
NEEDS_OTHER_REPO: linhlinhlin/LMS_hohulili
EVIDENCE: Product smoke screenshot attached; selector inventory returned 0 toolbar targets.
NEXT_PATCH: Add stable data-wiii-id and data-wiii-click-safe to low-risk navigation controls.
```

Recommended `STATUS` values:

- `ready`
- `in_progress`
- `blocked`
- `needs_review`
- `verified`
- `not_applicable`

## Product Flow Gates

The Word/PDF-to-lesson goal is not complete until these gates pass:

1. LMS teacher can open Wiii inside the course editor.
2. LMS host sends page-aware context and stable target inventory.
3. Pointy can highlight, tour, and safe-click low-risk navigation controls.
4. Teacher uploads Word/PDF from LMS or Wiii embed.
5. Wiii parses source content into markdown with source metadata.
6. Wiii generates an outline with source-grounded lesson objectives.
7. LMS displays a preview/diff before any course mutation.
8. Teacher confirms apply.
9. LMS stores generated lesson blocks.
10. Wiii can answer follow-up questions with citations to the uploaded source.

## Observer Workflow

1. Bootstrap labels in both repos.
2. Create a central coordination issue in Wiii and a mirrored issue in LMS.
3. Ask each worker agent to comment with the structured contract above.
4. Run the watcher digest periodically.
5. When a blocker is detected, the observer posts one focused request to the
   owning repo.
6. When both repos report `verified`, the observer asks humans for merge/deploy
   review rather than merging directly.

## Active Coordination Threads

- Wiii central thread: `meiiie/wiii#283`
- LMS mirror thread: `linhlinhlin/LMS_hohulili#400`
- Current Wiii Pointy product fix under watch: `meiiie/wiii#282`

Use the Wiii central thread for observer digests. Use the LMS mirror thread when
the next step belongs to the LMS repository.

## Watcher Commands

From the Wiii workspace:

```bash
python scripts/agent_coordination/watcher.py bootstrap-labels --apply
python scripts/agent_coordination/watcher.py create-thread --apply --title "Wiii x LMS teacher doc-to-course integration"
python scripts/agent_coordination/watcher.py digest
python scripts/agent_coordination/watcher.py digest --post-to meiiie/wiii#123 --apply
```

The watcher depends on the GitHub CLI (`gh`) and the currently authenticated
GitHub user. It does not require project secrets.

## Product Smoke Prompts

Use these prompts as realistic end-to-end checks:

```text
Teacher: Toi vua upload file Word/PDF bai giang an toan hang hai. Hay tao outline 4 phan, moi phan co muc tieu hoc tap, noi dung chinh, cau hoi kiem tra nhanh, va trich nguon tu tai lieu.
```

```text
Teacher: Hay dua noi dung nay vao lesson hien tai, nhung truoc tien cho toi xem preview diff. Neu toi dong y moi apply.
```

```text
Teacher: Chi cho toi nut tiep tuc bai hoc va mo panel quiz mau, nhung dung bam vao nut nop bai hay xoa khoa hoc.
```

## Failure Modes

- Infinite comment loop: watcher only posts to a central issue by default.
- False "done": require evidence in every `verified` status.
- Unsafe LMS mutation: preview/apply contract and human confirmation are
  mandatory.
- Selector drift: LMS must prefer semantic `data-wiii-id`, not CSS class names.
- Large PR drift: split by Wiii contract, LMS host UI, document/course pipeline,
  and product smoke harness.
