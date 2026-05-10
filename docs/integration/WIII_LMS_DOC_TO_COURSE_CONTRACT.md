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

- Preview action: `authoring.preview_lesson_patch`
- Apply action: `authoring.apply_lesson_patch`
- Preview kind: `lesson_patch`
- Apply input must include the preview token returned by the preview action.
- The preview payload must carry source references from the uploaded document.
- The apply action must fail closed when the preview token is missing, expired, or
  does not match the patch being applied.

Expected preview metadata:

```json
{
  "preview_kind": "lesson_patch",
  "apply_action": "authoring.apply_lesson_patch",
  "preview_token": "opaque-host-token",
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

## LMS-Side Requirements

The LMS host must implement the apply side in its own repository:

- expose `authoring.preview_lesson_patch`
- expose `authoring.apply_lesson_patch`
- bind each apply call to a valid preview token
- keep apply idempotent where practical
- reject publish/enroll/delete/grading/quiz-submit mutations from Wiii safe-click
  or preview/apply lanes unless a separate reviewed contract exists

Do not implement LMS mutations in the Wiii repository.
