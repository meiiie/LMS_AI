# Wiii security policy

## Reporting a vulnerability

Do not open a public issue, discussion, or pull request for a suspected
vulnerability or exposed secret.

Use a [private GitHub security advisory](https://github.com/meiiie/wiii/security/advisories/new).
If that channel is unavailable, contact the maintainer at
`meokhp888@gmail.com` with the subject `Wiii security report`.

Include, when safe:

- affected commit/version and surface;
- reproduction steps or a minimal proof of concept;
- expected impact and required privileges;
- whether credentials, personal data, tenant data, or external side effects may
  be involved;
- a suggested mitigation, if known.

Do not include live secrets or unrelated private data. Revoke an exposed
credential first, then report only a redacted identifier.

## Supported versions

| Line | Security support |
| --- | --- |
| Public stable GitHub Release | None published yet |
| `main` | Development branch; security fixes land here before release |
| Candidate workflow artifacts | Evaluation only; not a supported distribution |
| Older releases | Not supported unless a release notice says otherwise |

## Response process

The Wiii Lab will acknowledge a complete report as capacity allows, validate
impact, coordinate a fix and release, and agree on disclosure timing with the
reporter. Critical credential exposure or active exploitation is handled ahead
of normal issue work.

## Security boundaries

High-risk areas include:

- JWT/API-key/OAuth/Magic Link and adapter token exchange;
- organization, ownership, and cross-user data isolation;
- semantic memory and model-visible context provenance;
- ACP/MCP/tools, host actions, filesystem access, and code execution;
- Wiii Connect vaults, provider scopes, previews, approvals, and mutations;
- webhook signature and replay protection;
- desktop session persistence and unknown mutation outcomes;
- migrations, release signing, update trust, CI credentials, and artifacts.

Expected controls include timing-safe secret comparison, server-side
authorization, least privilege, bounded input and rate limits, sanitized
errors/logs, preview-before-apply where applicable, no automatic replay of
unknown mutations, and verifiable release artifacts.

## Out of scope

- Vulnerabilities that require an unsupported modified build and do not affect
  upstream Wiii.
- Reports consisting only of automated scanner output without a reproducible
  security impact.
- Social engineering, physical access, or third-party service issues that do
  not arise from Wiii's integration.
- Denial-of-service claims that only demonstrate expected rate limiting.

Third-party dependency vulnerabilities that affect a shipped Wiii version are
in scope even when the root defect belongs upstream.
