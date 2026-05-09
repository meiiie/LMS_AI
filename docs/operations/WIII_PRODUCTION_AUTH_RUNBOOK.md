# Wiii Production Auth Runbook

Status: Active

Owner: Project leadership

Last updated: 2026-05-10

Related issue: [#264](https://github.com/meiiie/wiii/issues/264)

## Purpose

This runbook defines the production-safe setup for Wiii login methods after the
fail-closed auth guard shipped in [#263](https://github.com/meiiie/wiii/pull/263).

Production auth must be boring, explicit, and reversible:

- never commit auth secrets, API keys, OAuth client secrets, or `.env.production`
- keep login methods disabled until the matching provider secret is present
- validate Google redirect URIs in Google Cloud Console before enabling OAuth
- smoke test from the public domain after each auth change
- rollback by disabling the feature flag and restarting the app

## Current Production State

As of 2026-05-10, Magic Link is provisioned on production with a verified
Resend domain, and Google OAuth is enabled through the shared `LMS Maritime`
web client in project `the-wiii-lab`.

```env
ENABLE_MAGIC_LINK_AUTH=true
ENABLE_GOOGLE_OAUTH=true
MAGIC_LINK_BASE_URL=https://wiii.holilihu.online
MAGIC_LINK_FROM_EMAIL=Wiii <noreply@holilihu.online>
ENABLE_DISTRIBUTED_MAGIC_LINK_SESSIONS=true
VALKEY_URL=redis://valkey:6379/0
OAUTH_REDIRECT_BASE_URL=https://wiii.holilihu.online
OAUTH_ALLOWED_REDIRECT_ORIGINS=https://wiii.holilihu.online
```

The Resend API key lives only in the VM runtime `.env.production`. It must not
appear in Git, GitHub, docs, PR comments, or shell output. Rotate any key that
was pasted into chat before using it for a higher-stakes production launch.

The Google OAuth client secret also lives only in the VM runtime
`.env.production`. The downloaded OAuth JSON must not be committed or left on
the production host after enablement.

## Fail-Closed Contract

In production, Wiii refuses unsafe optional auth configuration:

- `ENABLE_MAGIC_LINK_AUTH=true` requires a non-placeholder `RESEND_API_KEY`
- `ENABLE_GOOGLE_OAUTH=true` requires non-placeholder Google OAuth client ID and secret
- Magic Link never returns `dev_verify_url` in production
- `ENABLE_DEV_LOGIN=true` is forbidden in production

If one of these checks fails, treat startup failure as the correct outcome.
Fix the environment, do not loosen validation.

## Magic Link With Resend

### Provisioning Checklist

1. Verify the sender domain in Resend.
2. Prefer a domain sender such as `noreply@holilihu.online`.
3. Store the Resend API key only in the production runtime environment.
4. Use Valkey-backed Magic Link sessions in production so WebSocket handoff
   survives multiple workers or app restarts.

Required runtime variables:

```env
ENABLE_MAGIC_LINK_AUTH=true
RESEND_API_KEY=<real-resend-api-key>
MAGIC_LINK_BASE_URL=https://wiii.holilihu.online
MAGIC_LINK_FROM_EMAIL=Wiii <noreply@holilihu.online>
ENABLE_DISTRIBUTED_MAGIC_LINK_SESSIONS=true
VALKEY_URL=redis://valkey:6379/0
```

### Smoke Test

From a trusted operator machine, request a link for a real test inbox:

```bash
curl -fsS https://wiii.holilihu.online/api/v1/auth/magic-link/request \
  -H 'content-type: application/json' \
  --data '{"email":"<operator-test-email>"}'
```

Expected result:

- response contains `session_id`, `message`, and `expires_in`
- response does not contain `dev_verify_url`
- the test inbox receives a link under `https://wiii.holilihu.online`
- opening the link verifies the session and issues Wiii tokens

If the request returns `500`, check the app logs for Resend rejection, sender
domain status, or rate limits before changing application code.

### Rollback

```env
ENABLE_MAGIC_LINK_AUTH=false
```

Restart the app container, then confirm the request endpoint no longer exposes a
working login path.

## Google OAuth

Wiii uses Google OAuth authorization code flow through the Wiii backend. This is
different from the current LMS GIS browser-token flow documented in
`E:/Sach/Sua/LMS_hohulili/docs/runbooks/GOOGLE_LOGIN_GIS_SETUP_RUNBOOK.md`.

Wiii's Google Cloud Console redirect URI is:

```text
https://wiii.holilihu.online/api/v1/auth/google/callback
```

The public login endpoint is:

```text
https://wiii.holilihu.online/api/v1/auth/google/login
```

Required runtime variables:

```env
ENABLE_GOOGLE_OAUTH=true
GOOGLE_OAUTH_CLIENT_ID=<google-web-client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<google-web-client-secret>
OAUTH_REDIRECT_BASE_URL=https://wiii.holilihu.online
OAUTH_ALLOWED_REDIRECT_ORIGINS=https://wiii.holilihu.online
SESSION_SECRET_KEY=<real-32-byte-or-longer-secret>
```

### Can Wiii Reuse The LMS Google OAuth Client?

Yes, but only if the same Google Cloud OAuth web client is intentionally shared
inside the same project/trust boundary and has every required origin or redirect
URI configured.

The current production setup reuses the existing `LMS Maritime` web client. That
client must keep all LMS redirect URIs and the Wiii callback URI:

```text
http://localhost:8088/api/v3/auth/google/callback
https://holilihu.online/api/v3/auth/google/callback
https://wiii.holilihu.online/api/v1/auth/google/callback
```

If Wiii is pointed at a client that lacks the exact Wiii redirect URI, Google
will fail with `redirect_uri_mismatch`. Fix Google Cloud Console, not Wiii code.

Recommended production setup:

- use a dedicated Wiii production OAuth web client when possible
- use a shared LMS/Wiii client only when project ownership, consent screen,
  authorized domains, and rollback ownership are shared
- keep local, staging, and production OAuth clients separate if the team can
  manage the extra secrets

### Smoke Test

After enabling OAuth and restarting the app:

```bash
curl -fsSI https://wiii.holilihu.online/api/v1/auth/google/login
```

Expected result:

- endpoint returns a redirect toward Google Accounts
- browser login returns to Wiii without `redirect_uri_mismatch`
- callback delivers tokens to the expected Wiii web or desktop redirect flow

Production smoke evidence from 2026-05-10:

- `GET /api/v1/auth/google/login` returned `302`
- `Location` pointed to `https://accounts.google.com/o/oauth2/v2/auth`
- the redirect URI in the Google URL was
  `https://wiii.holilihu.online/api/v1/auth/google/callback`

### Rollback

```env
ENABLE_GOOGLE_OAUTH=false
```

Restart the app container. Keep client secrets in the runtime store if rotation
is not required; remove or rotate them if there is any exposure concern.

## Production Change Procedure

- Edit `/opt/wiii/maritime-ai-service/.env.production` on the Wiii VM.
- Never paste secrets into GitHub issues, pull requests, docs, chat logs, or
  shell output.
- Restart through the pinned deploy path when possible:

```bash
cd /opt/wiii
SHA=<current-production-sha>
DEPLOY_SHA=${SHA} \
WIII_APP_IMAGE=ghcr.io/meiiie/wiii-app:sha-${SHA} \
WIII_NGINX_IMAGE=ghcr.io/meiiie/wiii-nginx:sha-${SHA} \
REQUIRE_PINNED_IMAGES=true \
RUN_EXTERNAL_SMOKE=true \
BASE_URL=https://wiii.holilihu.online \
  bash ./maritime-ai-service/scripts/deploy/deploy.sh
```

After deploy:

- Run auth-specific smoke tests.
- Record outcome and rollback notes in the release issue or PR.

## Operator Notes

- If a test key was pasted in an AI chat, rotate it before real production use.
- A Resend key alone is not enough; sender/domain verification still matters.
- A Google client ID and secret alone are not enough; exact redirect URIs matter.
- Do not enable both optional login methods at once unless the rollback owner is
  online and the release smoke window is clear.
