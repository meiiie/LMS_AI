# Wiii Connect — LMS adapter

**Status:** Supported compatibility adapter
**Owner:** Wiii Connect maintainers
**Feature gates:** LMS integration and token exchange settings

## Purpose

The LMS adapter lets an external learning system provide identity, educational
context, dashboards, webhooks, and preview/apply host actions to Wiii. It is one
optional Wiii Connect provider. Wiii Core, Wiii Workbench, Neko Chill, ACP,
memory, artifacts, and general tools operate without it.

## Boundary

```text
LMS host
  -> signed token exchange / signed webhook / authenticated API
  -> LMS connector registry
  -> Wiii identity + organization + host-role overlay
  -> Wiii Core or host-action contract
  -> preview / explicit approval / apply
  -> audit and privacy-safe evidence
```

The canonical identity is a Wiii user. The LMS user ID, connector ID, course
role, and course ID are adapter-scoped references. A teacher/admin role from a
host is not Wiii platform-admin authority.

## Endpoint groups

All paths below are under `/api/v1`.

### Token exchange

| Method | Path | Contract |
| --- | --- | --- |
| `POST` | `/auth/lms/token` | Exchange a signed host identity assertion for Wiii tokens |
| `POST` | `/auth/lms/token/refresh` | Refresh a Wiii token pair |
| `GET` | `/auth/lms/health` | Sanitized connector readiness |

Token exchange is rate-limited. The LMS backend signs the exact raw request
body with HMAC-SHA256 in `X-LMS-Signature`. Wiii resolves the connector secret,
verifies the signature, and checks the timestamp for replay protection before
creating or linking identity state.

### Webhooks

| Method | Path | Contract |
| --- | --- | --- |
| `POST` | `/lms/webhook/{connector_id}` | Preferred per-connector signed event |
| `POST` | `/lms/webhook` | Legacy flat-configuration compatibility path |
| `GET` | `/lms/health` | Sanitized integration readiness |

Webhook verification occurs over raw bytes before JSON parsing. The trusted
connector ID comes from the route/registry, not the request body. Unsigned
webhooks fail closed. Error responses do not reveal internal exceptions.

### Data and dashboard

Authenticated data routes include student profile, grades, enrollments,
assignments, and quiz history under `/lms/students/{student_id}/...`.
Dashboard routes under `/lms/dashboard/` provide course and organization views.

Students can access only the linked LMS identity resolved for their canonical
Wiii user. Teacher/admin access is evaluated as a host-role overlay and remains
bounded by connector and organization context. `X-LMS-Connector` may select a
configured connector but cannot grant access by itself.

## Document-to-course host action

Course generation is a preview/apply capability, not a direct write from chat:

1. The user supplies or selects a document.
2. Wiii records bounded source references and generates a course-plan preview.
3. The host renders the preview and requests explicit approval.
4. Apply must carry the backend/host-issued preview token or equivalent ledger
   reference for the same actor, course, sources, and normalized plan.
5. The host executes the mutation once and returns a terminal result.
6. Wiii records status, hashes/counts, and provenance without raw document or
   approval-token leakage.

The relevant capability names include
`authoring.generate_course_from_document` and `authoring.apply_course_plan`.
Apply is never inferred from conversational approval text alone.

## Required security properties

- HMAC secrets, service tokens, JWTs, refresh tokens, and approval tokens never
  enter model context, logs, or evidence artifacts.
- Signature comparison is constant-time and uses the exact raw body.
- Token assertions have a bounded timestamp window.
- Connector, user, organization, and role mappings are resolved server-side.
- Students cannot query arbitrary student IDs.
- Mutations require preview/approval/apply and single-consumption semantics.
- A lost mutation response becomes unknown outcome and is not replayed
  automatically.
- Production/non-local evidence runs require an explicit guarded override.

## Evidence and tests

Focused contracts live in backend unit tests for LMS auth, webhook, data access,
identity mapping, capability policy, document preview, host-action audit, and
the replay probe.

The guarded workflow `Wiii Connect — LMS Adapter Evidence` runs
`probe_live_lms_test_course_replay.py`. The registry requirement remains
`lms-test-course-replay` because it names this adapter-specific scenario. Its
artifact may prove a real external write only when the external target returns
an authenticated acknowledgement; otherwise it must report the external write
gap explicitly.

## Configuration and rollout

Use `.env.example` and typed settings as the configuration source. Enable the
adapter only after connector secrets, allowed origins, identity mapping,
database migrations, and health checks are in place. Roll back by disabling the
adapter gates; do not remove Wiii user or audit records to hide a failed rollout.

Exact request/response schemas are generated from the running FastAPI OpenAPI
document. This page defines the durable trust and behavior contract.
