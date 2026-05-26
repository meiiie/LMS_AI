# Wiii LMS Doc-To-Course Contract

Status: Draft for product integration

Owner: Wiii/LMS integration agents

Last updated: 2026-05-10

## Product Safety Rule

The LMS doc-to-course product flow is:

1. Teacher uploads a Word/PDF/DOCX document to Wiii.
2. Wiii parses the document and returns an outline plus source references.
3. Wiii/LMS produces a lesson or course patch preview.
4. Teacher explicitly confirms the preview.
5. LMS applies the confirmed patch.

Wiii must not publish, mutate, or push LMS content from a product doc-to-course
flow before the teacher has reviewed a preview.

## Safe Contract

Use the host action preview/apply lane for LMS authoring:

- Wiii only exposes LMS authoring preview/apply actions when the current turn has
  an active LMS host connection: `host_type="lms"`, a concrete `connector_id`,
  and a linked LMS/host user identity. Uploaded documents in standalone Wiii may
  still produce a draft/export artifact, but must not bind LMS preview/apply
  tools.
- Preview action: `authoring.preview_lesson_patch`
- Apply action: `authoring.apply_lesson_patch`
- Preview kind: `lesson_patch`
- Apply input must include the preview token returned by the preview action.
- If the LMS preview dialog performs the teacher confirmation itself, the
  preview response may also return an opaque, short-lived `approval_token`.
  Wiii may forward that token with `preview_token` to the apply action, but
  should not log it in audit metadata.
- The preview payload must carry source references from the uploaded document.
- The apply action must fail closed when the preview token is missing, expired, or
  does not match the patch being applied.

Expected preview metadata:

```json
{
  "preview_kind": "lesson_patch",
  "apply_action": "authoring.apply_lesson_patch",
  "preview_token": "opaque-host-token",
  "approval_token": "opaque-teacher-approval-token",
  "source_references": [
    {
      "kind": "chapter",
      "chapter_index": 0,
      "title": "Chapter title",
      "source_pages": [1, 2]
    }
  ]
}
```

## Legacy Direct Expansion

`POST /course-generation/{generation_id}/expand` is a legacy direct LMS mutation
path. It can create a course shell and push generated chapters to LMS without a
preview/apply host action.

New calls to this endpoint must set:

```json
{
  "legacy_lms_mutation_confirmed": true
}
```

Without that explicit opt-in, Wiii returns HTTP 409 with:

- `code`: `legacy_lms_mutation_confirmation_required`
- `required_field`: `legacy_lms_mutation_confirmed`
- `safe_contract`: `host_action_preview_apply`

This guard is for accidental product calls. Existing recovery/resume behavior for
already-persisted legacy jobs remains runtime-owned and should not be presented
as the safe LMS product flow.

## Source References

`GET /course-generation/{generation_id}` returns `source_references` derived from
outline `sourcePages`. LMS previews should surface these references so teachers
can verify generated material against the uploaded document before applying it.

The current Wiii status response emits references for:

- chapter-level `sourcePages`
- lesson-level `sourcePages`

LMS may display these references as page chips, source rows, or citation links,
but should preserve the page values verbatim.

## Parser And Provenance Levels

Wiii uses a hybrid parser policy:

- `fast`: MarkItDown only. Best for quick LLM-ready Markdown from clean Office/PDF
  files.
- `auto`: MarkItDown first, then promote to Docling when the fast parse has weak
  page/layout provenance.
- `precision`: Docling first, MarkItDown fallback. Use this for teacher
  doc-to-course flows where citations, embedded figures, tables, or page/layout
  provenance matter.

MarkItDown plugins such as OCR can recover text from embedded images, but that
is still an inline text extraction lane. For teacher-facing citation UX, Docling
or an equivalent structured document map should own page/figure/table
provenance so LMS can show what Wiii relied on.

The parse response should be treated as a source contract, not just text:

- `parser`: final parser that produced the usable context.
- `parser_chain`: parsers attempted/used, for example `["markitdown", "docling"]`.
- `provenance_level`: one of `text_only`, `structured_text`, `page_marker`,
  `page_layout`.
- `embedded_asset_count`, `figure_count`, `table_count`: signals that the source
  had visual/table material that may require citation or vision review.

`page_layout` is the preferred level for LMS citations. `structured_text` is
valid for DOCX/PPTX files when the parser can see headings, tables, and figures
but the source format does not expose stable page numbers. `text_only` is usable
for drafting, but LMS should avoid presenting exact page/figure claims as
verified unless the preview carries source references that the teacher can
inspect.

Operational note: Docling is intentionally optional because it can add several GB
of model/runtime footprint. Local development can enable it with
`pip install -e ".[precision-docs]"`. Production app images enable it by building
`maritime-ai-service/Dockerfile.prod` with `INSTALL_PRECISION_DOCS=true`, then
setting `DOCUMENT_CONTEXT_PARSER_MODE=precision` and
`USE_DOCLING_FOR_COURSE_GEN=true`. The production precision image also installs
LibreOffice and sets `DOCLING_LIBREOFFICE_CMD=/usr/bin/soffice` so Office files
can expose richer layout/image signals where Docling supports them. If Docling or
the Office converter is unavailable, Wiii must fall back or surface a parser
warning rather than silently pretending the citation precision is higher than it
is. Because the upload API can request `parser_mode=precision` per document, the
production deploy capacity guard treats precision parsing as an installed
product capability, not only as a global default setting.

## LMS-Side Requirements

The LMS host must implement the apply side in its own repository:

- expose `authoring.preview_lesson_patch`
- expose `authoring.apply_lesson_patch`
- bind each apply call to a valid preview token
- keep apply idempotent where practical
- reject publish/enroll/delete/grading/quiz-submit mutations from Wiii safe-click
  or preview/apply lanes unless a separate reviewed contract exists

Do not implement LMS mutations in the Wiii repository.
