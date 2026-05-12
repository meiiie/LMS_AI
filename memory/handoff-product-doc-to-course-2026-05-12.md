# Handoff: Product Doc-to-Course Hardening

Date: 2026-05-12

Status: production deployed and smoke-tested

## TL;DR

Wiii x Maritime LMS doc-to-course is product-usable for the flagship flow:

1. Teacher uploads Word/PDF/DOCX in LMS Wiii iframe.
2. Wiii parses with precision document context (`docling` in production).
3. Wiii generates a course-plan preview with source references.
4. LMS shows preview/diff/citation and waits for teacher confirmation.
5. LMS applies only after approval-token gated confirmation.

Latest deployed Wiii commit:

- `df0d226d3e6f3b7d15fe2fcc611cf26374f99212`
- Deploy run: `https://github.com/meiiie/wiii/actions/runs/25729067217`
- Deploy smoke: `19 passed, 0 failed`

## Merged PRs In This Hardening Pass

- `#358` / `fd0301a5` - Guard precision parser capacity by product capability.
- `#360` / `e14eae8c` - Accept valid structured visual `visual_patch`/`visual_open` lifecycle in production smoke.
- `#362` / `873e7b50` - Remove duplicate course-plan caution copy in Wiii preview summary.
- `#364` / `a00b25d0` - Add bounded retries around GHCR manifest checks.
- `#366` / `d48101f9` - Fix manifest retry under strict shell mode (`set +e` capture around Docker CLI).
- `#368` / `df0d226d` - Polish model selector label from `Tu dong` to `Tự động`.

Related issues should be closed by PR keywords:

- `#357`, `#359`, `#361`, `#363`, `#365`, `#367`

## Production Evidence

### Deploy

Command path used:

```powershell
gh workflow run "Deploy Production" --repo meiiie/wiii `
  -f deploy_sha=df0d226d3e6f3b7d15fe2fcc611cf26374f99212 `
  -f base_url=https://wiii.holilihu.online `
  -f require_pinned_images=true
```

Important log anchors:

- Manifest validation passed for both app and nginx pinned images.
- Precision profile: `DOCUMENT_CONTEXT_PARSER_MODE=precision`, `USE_DOCLING_FOR_COURSE_GEN=true`.
- Host profile: `RAM=15GiB`, `swap=3GiB`, `docker-free=57GiB`.
- Structured visual SSE included `visual_open` and `visual_commit`.
- Final deploy smoke: `=== Results: 19 passed, 0 failed ===`.

### Long Maritime Research DOCX Preview

Input:

```text
C:\Users\Admin\Downloads\40 - GV.25-26.01.31 - Nghiên cứu xây dựng hệ thống quản lý vận hành và hồ sơ tàu thủy phục vụ doanh nghiệp vận tải biển.docx
```

Latest report:

```text
E:\Sach\Sua\AI_v1\artifacts\wiii-lms-e2e\product_course_plan_preview_maritime_doc_after_vietnamese_copy_report.json
```

Observed:

- Parser/status: `docling · 14 MB · 225491 ký tự · 168 asset · đã rút gọn`.
- UI label is now `Tự động`.
- Preview visible: yes.
- Title: `Quản lý vận hành và hồ sơ tàu thủy cho doanh nghiệp vận tải biển`.
- Course plan: `6` chapters, `18` lessons, `12` sources.
- Expected terms found: `tàu thủy`, `vận hành`, `hồ sơ`, `vận tải biển`.
- Forbidden HoLiLiHu/manual leakage: false.
- Apply and cancel buttons visible.

### Verified Apply Smoke

Latest report:

```text
E:\Sach\Sua\AI_v1\artifacts\wiii-lms-e2e\product_verified_apply_smoke_report.json
```

Observed:

- Preview visible: true.
- Source/citation visible: true.
- Apply status visible: true.
- Authenticated API verification found the marker after apply.
- Marker section title OK: true.
- Stale section title found: false.

## Technical Changes That Matter

### Precision Parser Capacity

Production deploy no longer skips host capacity checks just because parser flags are absent in the workflow environment. The guard resolves the product capability defaults and fails early unless the host is sized for precision document parsing or an explicit emergency override is set.

### Visual Smoke

Production smoke accepts both valid structured visual lifecycles:

- `visual_open` + `visual_commit`
- `visual_patch` + `visual_commit`

It still rejects raw widget fences and still requires a committed visual lifecycle.

### GHCR Manifest Robustness

There are two retry layers:

- GitHub Actions workflow validates pinned GHCR image manifests before SSH.
- Server deploy script validates pinned manifests again on the VM.

The second fix was necessary because `docker manifest inspect` could short-circuit under strict shell mode before retrying. The helper now captures the exit code under `set +e`, restores strict mode, and fails closed only after bounded retries.

### UX Copy

The model selector now shows `Tự động`, not `Tu dong`, and has focused Vitest coverage.

## Do Not Regress

- Do not reintroduce direct LMS mutation from Wiii `/expand` without explicit legacy confirmation.
- Do not bypass LMS preview/diff/citation or teacher approval-token confirmation.
- Do not mark publish/delete/enroll/grade/payment/quiz-submit as safe-click targets.
- Do not weaken precision capacity guard silently; use the documented emergency override only when deliberately accepting degraded parsing risk.
- Do not treat CodeRabbit/CI green as proof of product quality; keep running product smoke for doc-to-course.

## Remaining True Debt

1. Pointy product E2E coverage is still thinner than doc-to-course coverage. Public bundle and unit/integration tests are strong, but real LMS multi-step safe-click tours should get a dedicated product smoke.
2. Citation page/layout precision for DOCX is better with Docling, but exact page provenance still depends on parser fidelity and document structure.
3. Video ingestion/course generation was not revalidated in this pass.
4. Vision model/provider routing was not revalidated in this pass.
5. Chunk sizes in `build:embed` remain large; this is a performance debt, not a current correctness blocker.

## Recommended Next Step

Create a committed product smoke for Pointy against the LMS host contract:

- log in as teacher,
- discover `data-wiii-id` inventory on key pages,
- verify safe-click succeeds only for `data-wiii-click-safe="true"`,
- verify unsafe mutate actions fail closed,
- capture screenshots for tour positioning.

This should live as a repeatable smoke script, not only as manual evidence in `artifacts/`.
