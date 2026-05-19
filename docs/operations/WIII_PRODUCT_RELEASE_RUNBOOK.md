# Wiii Product Release Runbook

Status: Active

Owner: Project leadership

Last updated: 2026-05-09

Related issue: [#243](https://github.com/meiiie/wiii/issues/243)

## Purpose

This runbook defines the safe path for moving Wiii to production while multiple agents and teammates continue active development in parallel.

The release lane is intentionally narrow:

- deploy only merged `main` commits or an explicitly reviewed release SHA
- never deploy from a dirty local checkout or a parallel-agent WIP branch
- use prebuilt GHCR images instead of building on the production host
- verify API, web, embed, and SSE smoke signals after rollout
- keep rollback tied to a previous Git SHA and matching image tags

## Current Production Topology

Production traffic is expected to flow through:

```text
Cloudflare/DNS -> Caddy on host -> local nginx on :8080 -> app on Docker network :8000
```

Important implication: the app container is private. Health probes on the VM must use nginx-local URLs such as `http://localhost:8080/api/v1/health/live`, not `http://localhost:8000`.

On 2026-05-10, production was verified on `wiii-production` in project
`the-wiii-lab`:

- `https://wiii.holilihu.online/api/v1/health/llm-models` was reachable
- the active model pool contained primary `qwen/qwen3-next-80b-a3b-instruct`
  and advanced fallback `qwen/qwen3-next-80b-a3b-thinking`
- model-level health may temporarily mark the advanced model degraded after a
  timeout; routing should keep normal chat on the healthy primary model
- `ENABLE_MAGIC_LINK_AUTH=true` was enabled after Resend API validation and
  verified `holilihu.online` sender domain smoke
- `ENABLE_GOOGLE_OAUTH=true` was enabled after the shared `LMS Maritime` Google
  OAuth web client included the Wiii callback URI

Treat any future public API health timeout as a release blocker until the deploy
script, Caddy routing, nginx health, and app health all agree.

## Current GCP Rebuild Target

The old documented GCP project `valued-range-443614-j4` is no longer accessible from the active deployment account. As of 2026-05-09, the active account has project `the-wiii-lab`.

Important guardrail:

- `lms-production` in `the-wiii-lab` is the LMS VM and must not be used for Wiii containers.
- Wiii should be deployed to a separate VM, default name `wiii-production`.
- The default VM profile for the teacher document-to-course lane is
  `e2-standard-4` in `asia-southeast1-c` with an `80GB` `pd-balanced` boot disk.
  `e2-standard-2` is acceptable only for the fast MarkItDown profile; Docling
  precision parsing plus PostgreSQL/MinIO/Valkey on one VM needs the extra RAM
  headroom.
- Docker defaults are tuned for single-node production: `APP_REPLICAS=1`,
  `GUNICORN_WORKERS=2`, `ASYNC_POOL_MAX_SIZE=20`, `APP_MEM_LIMIT=4G`.
- Deploys fail early when the host has less than `12GiB` physical RAM or less
  than `12GiB` free Docker/root disk because production images include the
  precision document parser and teacher uploads can request precision parsing
  per document. This is a guardrail, not a performance target: the recommended
  product profile remains `e2-standard-4` with an `80GB` boot disk. Use
  `ALLOW_LOW_MEMORY_PRECISION=true` only for an explicit emergency deploy where
  the operator accepts the risk. Use
  `SKIP_PRECISION_HOST_CAPACITY_CHECK=true` only for a verified fast-only host
  that cannot accept per-request precision parsing.
- Production app images are built with `INSTALL_PRECISION_DOCS=true`, which
  installs `maritime-ai-service/requirements-precision.txt` and enables the
  Docling parser without slowing every regular unit-test install. The production
  runtime image also includes LibreOffice for Office layout conversion and
  `ffmpeg`/`ffprobe` for bounded video upload context.
- Production app images intentionally build PyTorch with `UV_TORCH_BACKEND=cpu`
  on the current `e2-standard-4` CPU-only VM. Do not switch to a CUDA backend
  unless the target host, budget, and rollback plan explicitly include GPU
  capacity; otherwise unused CUDA wheels add several GB to the image and slow
  deploys without improving parsing quality.

Production `.env.production` is secret-bearing and must stay on the VM. For the current NVIDIA-backed product lane, apply these non-secret shape requirements there rather than committing a changed `.env` template:

```bash
LLM_PROVIDER=nvidia
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=qwen/qwen3-next-80b-a3b-instruct
NVIDIA_MODEL_ADVANCED=qwen/qwen3-next-80b-a3b-thinking
ENABLE_LLM_MODEL_HEALTH_PROBES=true
LLM_MODEL_HEALTH_PROBE_TIMEOUT_SECONDS=45
AGENT_PROVIDER_CONFIGS={"code_studio_agent":{"tier":"deep","provider":"nvidia","model":"qwen/qwen3-next-80b-a3b-thinking"}}

# Required while production embeddings use models/gemini-embedding-001.
# Use only the minimum Gemini/API permissions needed for embeddings, track its
# rotation independently from NVIDIA_API_KEY, and document any provider-specific
# rotation procedure in the release or auth runbook.
GOOGLE_API_KEY=<google-gemini-api-key>

APP_REPLICAS=1
GUNICORN_WORKERS=2
ASYNC_POOL_MAX_SIZE=20
APP_CPU_LIMIT=2.0
APP_MEM_LIMIT=4G
DOCUMENT_CONTEXT_PARSER_MODE=precision
USE_DOCLING_FOR_COURSE_GEN=true
DOCLING_VLM_BACKEND=none
DOCLING_VLM_API_URL=
DOCLING_VLM_API_KEY=
DOCLING_VLM_MODEL=gemini-3.1-flash-lite
DOCLING_LIBREOFFICE_CMD=/usr/bin/soffice
POSTGRES_CPU_LIMIT=1.0
POSTGRES_MEM_LIMIT=1536M
MINIO_CPU_LIMIT=0.35
MINIO_MEM_LIMIT=384M
VALKEY_CPU_LIMIT=0.25
VALKEY_MEM_LIMIT=192M
NGINX_CPU_LIMIT=0.25
NGINX_MEM_LIMIT=192M
BACKUP_CPU_LIMIT=0.25
BACKUP_MEM_LIMIT=192M
```

`NVIDIA_API_KEY` and all database/auth/object-storage secrets must be copied through the operator's secure channel only; never paste them into issues, PR comments, docs, or shell logs.

Optional production login methods are governed by
[`WIII_PRODUCTION_AUTH_RUNBOOK.md`](./WIII_PRODUCTION_AUTH_RUNBOOK.md). Keep
Magic Link enabled only while Resend smoke stays healthy. Keep Google OAuth
enabled only while the Google Cloud Console client keeps the exact Wiii callback
URI and login smoke returns a redirect to Google Accounts.

Provision the new VM:

```bash
PROJECT_ID=the-wiii-lab \
ZONE=asia-southeast1-c \
  bash maritime-ai-service/scripts/deploy/provision-gcp-vm.sh
```

After provisioning, update DNS or Cloudflare so `wiii.holilihu.online` points to the new static IP. Do not route Wiii traffic to the LMS VM IP.

For the current Caddy origin configuration, set Cloudflare SSL/TLS mode to `Full` while the record is proxied. Caddy uses an internal origin certificate (`tls internal`), so `Full (strict)` should wait until a Cloudflare Origin Certificate or a public certificate is installed on the VM.

Verify DNS and edge routing before deploying:

```bash
dig wiii.holilihu.online +short
curl -fsSI https://wiii.holilihu.online/embed/
```

If DNS still resolves to Cloudflare, confirm the Cloudflare origin points to the new static IP and that proxying is intentional. If DNS resolves to the old LMS VM IP, stop and fix DNS before running the deploy script.

## Preflight Gate

Before deploying, confirm the target commit is suitable for product:

```bash
cd /path/to/wiii
git fetch origin main
git status --short
git log --oneline -5 origin/main
```

GitHub gates:

```bash
gh pr list --repo meiiie/wiii --state open --limit 20
gh run list --repo meiiie/wiii --branch main --limit 10
gh run list --repo meiiie/wiii --workflow "Build Production Images" --branch main --limit 5
```

Required release evidence:

- `Gate Summary` is green on the PR that reached `main`
- the latest `Build Production Images` run for the target SHA succeeded
- app and nginx images exist in GHCR
- the nginx image contains the Pointy host bundle and serves `/pointy/wiii-pointy.umd.js` as JavaScript, not SPA HTML
- no unresolved P0/P1 issue blocks the release
- production secrets are present on the VM and contain no `CHANGE_ME` placeholders
- optional auth flags are either disabled or backed by real provider secrets and
  exact callback/origin configuration

Image existence check:

```bash
SHA=<target-full-sha>
docker manifest inspect ghcr.io/meiiie/wiii-app:sha-${SHA}
docker manifest inspect ghcr.io/meiiie/wiii-nginx:sha-${SHA}
```

Use the same SHA tag for app and nginx. Floating `:main` is acceptable only for emergency recovery or a low-risk internal deploy. Product releases should use `sha-...` tags.

## Deploy

Preferred path after the VM has been provisioned is the manual GitHub Actions
workflow `Deploy Production`. Configure the GitHub `production` environment with
these secrets:

- `WIII_PRODUCTION_HOST`: production VM hostname or public IP
- `WIII_PRODUCTION_USER`: SSH user that owns `/opt/wiii`
- `WIII_PRODUCTION_SSH_KEY`: private key allowed to SSH to the VM
- `WIII_PRODUCTION_KNOWN_HOSTS`: optional but recommended pinned SSH host key;
  if absent, the workflow uses `ssh-keyscan` during the run

Optional environment variables:

- `WIII_PRODUCTION_SSH_PORT`: defaults to `22`
- `WIII_PRODUCTION_APP_DIR`: defaults to `/opt/wiii`

The workflow validates that the target SHA is reachable from `origin/main`,
checks the matching `wiii-app:sha-...` and `wiii-nginx:sha-...` GHCR images,
runs the production deploy script over SSH, then verifies that
`/pointy/wiii-pointy.umd.js` returns JavaScript instead of the SPA shell.

Manual VM deploy remains supported and is the recovery path if GitHub-hosted
deployment is unavailable.

SSH to the production VM:

```bash
gcloud compute ssh wiii-production --zone=asia-southeast1-c --project=the-wiii-lab
```

Run a pinned deploy:

```bash
cd /opt/wiii

SHA=<target-full-sha>
DEPLOY_SHA=${SHA} \
WIII_APP_IMAGE=ghcr.io/meiiie/wiii-app:sha-${SHA} \
WIII_NGINX_IMAGE=ghcr.io/meiiie/wiii-nginx:sha-${SHA} \
REQUIRE_PINNED_IMAGES=true \
RUN_EXTERNAL_SMOKE=true \
BASE_URL=https://wiii.holilihu.online \
  bash ./maritime-ai-service/scripts/deploy/deploy.sh
```

The deploy script will:

- refuse dirty server checkouts
- fail on active placeholder secrets unless explicitly overridden
- validate the target image manifests
- validate `docker compose` configuration with `.env.production`
- create a pre-migration database backup when Postgres is already running
- run migrations
- start app and nginx
- probe `http://localhost:8080/api/v1/health/live`, `/health`, `/embed/`, and `/pointy/wiii-pointy.umd.js`
- optionally run external smoke through `scripts/deploy/smoke-test.sh`

## Post-Deploy Smoke

Run these from the VM:

```bash
cd /opt/wiii/maritime-ai-service
bash scripts/deploy/status.sh
API_KEY=<production-api-key> bash scripts/deploy/smoke-test.sh https://wiii.holilihu.online
```

Run these from a local machine:

```bash
curl -fsS https://wiii.holilihu.online/api/v1/health/live
curl -fsSI https://wiii.holilihu.online/embed/
curl -fsSI https://wiii.holilihu.online/pointy/wiii-pointy.umd.js
API_KEY=<production-api-key>
curl -fsS \
  -H "X-API-Key: ${API_KEY}" \
  https://wiii.holilihu.online/api/v1/voice/status
```

For Wiii x LMS releases that touch Pointy, host actions, or LMS DOM targets,
run the product Pointy contract smoke from a local machine with Playwright:

```bash
LMS_TEACHER_EMAIL=<teacher-email> \
LMS_TEACHER_PASSWORD=<teacher-password> \
LMS_COURSE_ID=<course-id> \
LMS_CHAPTER_ID=<chapter-id> \
LMS_LESSON_ID=<lesson-id> \
python scripts/product_smoke/lms_pointy_contract_smoke.py
```

This smoke logs into the LMS, audits `data-wiii-id` inventory, verifies safe
navigation targets, ensures publish/save/delete targets are not safe-clickable,
then sends real Pointy `wiii:action-request` messages through the embedded Wiii
iframe to validate highlight, tour, fail-closed unsafe clicks, and one safe
navigation click.

Minimum product smoke criteria:

- public health returns `200`
- `/embed/` returns `200` and has the expected frame policy
- `/pointy/wiii-pointy.umd.js` returns JavaScript content and never falls through to the SPA shell
- `/api/v1/voice/status` is registered and returns provider `elevenlabs` when authenticated
- Pointy LMS contract smoke passes if Pointy, host actions, or LMS DOM targets changed
- SSE V3 smoke reaches metadata and done events
- a normal short chat returns without a long silent period
- LMS iframe loads Wiii without cross-origin console errors beyond known sandbox limitations
- optional Magic Link or Google OAuth smoke passes if that login method was
  changed during the release

## Pointy Voice Operator Notes

The chat composer includes `Pointy` and `Voice` controls. The ElevenLabs key
input appears only after Pointy mode is on and the operator clicks `Voice` while
the backend reports missing voice config. The key is sent to
`/api/v1/voice/config` and stored encrypted server-side; the frontend must not
store the raw key.

Production can also be preconfigured on the VM:

```bash
ENABLE_HOST_ACTIONS=true
ENABLE_POINTY_VOICE=true
ELEVENLABS_API_KEY=<elevenlabs-api-key>
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb
ELEVENLABS_MODEL_ID=eleven_flash_v2_5
ELEVENLABS_OUTPUT_FORMAT=mp3_22050_32
```

If the public Pointy URL returns `text/html`, production is still serving the old
SPA/nginx image or the nginx route has not rolled out. Redeploy the matching
`wiii-nginx:sha-...` image before debugging LMS iframe code.

## Rollback

Rollback uses the last known-good Git SHA and matching image tags.

```bash
cd /opt/wiii

PREV_SHA=<previous-good-full-sha>
DEPLOY_SHA=${PREV_SHA} \
WIII_APP_IMAGE=ghcr.io/meiiie/wiii-app:sha-${PREV_SHA} \
WIII_NGINX_IMAGE=ghcr.io/meiiie/wiii-nginx:sha-${PREV_SHA} \
REQUIRE_PINNED_IMAGES=true \
RUN_EXTERNAL_SMOKE=true \
BASE_URL=https://wiii.holilihu.online \
  bash ./maritime-ai-service/scripts/deploy/deploy.sh
```

If rollback follows a migration, check whether the migration is backward-compatible before restarting the previous app image. If not, restore the predeploy dump created in `maritime-ai-service/backups/` and document the recovery in the release issue.

## Parallel-Team Rule

Product deploys must not use:

- the dirty Codex desktop workspace
- an unmerged feature branch
- local generated assets
- manually edited container state
- a PR that has required review/checks pending

When multiple agents are working, create a clean worktree for release operations and keep runtime work on separate branches. The release owner should merge only narrow, reviewed PRs into `main`, then deploy from that resulting SHA.

## If Public Health Still Times Out

Investigate in this order:

```bash
cd /opt/wiii/maritime-ai-service
bash scripts/deploy/status.sh
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail 120 nginx
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail 120 app
sudo journalctl -u caddy --since "15 minutes ago"
curl -v http://localhost:8080/api/v1/health/live
curl -v http://localhost:8080/health
curl -v https://wiii.holilihu.online/api/v1/health/live
```

Interpretation:

- local nginx health fails: inspect app/nginx compose health and container logs
- local nginx health passes but public health fails: inspect Caddy, DNS, Cloudflare, and firewall
- health passes but chat is slow: use the runtime latency timeline and provider health probes before changing orchestration code
