# Wiii Core API

**Base path:** `/api/v1`
**Source of truth:** registered FastAPI routers and generated OpenAPI schema

This page is an operator/developer map, not a hand-maintained enumeration of
every request field. When enabled in the target environment, use `/docs` and
`/openapi.json` for the exact schema of the running commit.

## Endpoint families

| Family | Representative paths | Purpose |
| --- | --- | --- |
| Chat | `/chat`, `/chat/stream/v3`, `/threads` | Turn execution, SSE, conversation history |
| Health/runtime | `/health/*`, `/llm/status`, `/admin/runtime-flow/*` | Liveness, readiness, providers, runtime diagnosis |
| Identity | `/auth/*`, `/users/me`, `/organizations/*` | Login, tokens, profile, tenant and role context |
| Knowledge | `/knowledge/*`, `/sources/*`, `/document-context/*` | Ingestion, source retrieval, uploaded-document context |
| Memory/living | `/memories/*`, `/insights/*`, `/living-agent/*` | Continuity, insights, goals, reflection and schedules |
| Host/artifacts | `/host-actions/*`, `/generated-files/*`, `/course-generation/*` | Audited host actions and generated work |
| Wiii Connect | `/wiii-connect/*` | Providers, connections, scopes, actions, approvals, execution |
| LMS adapter | `/auth/lms/*`, `/lms/*`, `/lms/dashboard/*` | Optional host token exchange, webhook, data, dashboard |
| Administration | `/admin/*` | Protected platform operations and audits |

## Authentication and tenant context

Supported entry modes are configured per deployment and may include bearer
JWT, API key, Google OAuth, Magic Link, and trusted adapter token exchange.
Authorization is enforced by the route and service layer, not by the client UI.

- Treat `user_id`, organization headers, connector IDs, and role strings from a
  request as untrusted until resolved against authenticated context.
- A host role is an adapter-local overlay; it does not redefine the canonical
  Wiii user or platform role.
- Cross-user and cross-organization resources require explicit authorization.
- Never place access tokens, API keys, approval tokens, raw provider payloads,
  or private document content in logs or evidence artifacts.

## Chat streaming

`POST /api/v1/chat/stream/v3` emits ordered SSE events. Clients must:

1. retain the request/session correlation identifiers;
2. process events in order;
3. treat tool/host actions as explicit lifecycle records;
4. render recoverable errors rather than inventing a final response;
5. reconnect only according to the session contract.

The event schema evolves through additive, typed events. A consumer must ignore
unknown event types safely but may not reinterpret a failed or unknown action as
success.

## Error contract

Use HTTP status for transport/auth/policy outcome and a sanitized response body
for client handling. Internal exceptions, provider credentials, SQL details,
and raw connector responses must remain server-side. Rate-limited endpoints may
return `429`; clients should use bounded backoff.

## Example health check

```bash
curl http://127.0.0.1:8000/api/v1/health/live
```

For production, call the public ingress or the documented local reverse-proxy
address; do not assume the application container port is exposed.

## Compatibility

Public request/response schemas, SSE event kinds, persisted session formats,
and adapter security contracts are versioned interfaces. Breaking changes
require a Wiii major release or an explicitly versioned route with a migration
window.
