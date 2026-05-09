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
  and advanced fallback `deepseek-ai/deepseek-v4-pro`
- model-level health may temporarily mark the advanced model degraded after a
  timeout; routing should keep normal chat on the healthy primary model
- `ENABLE_MAGIC_LINK_AUTH=true` was enabled after Resend API validation and
  verified `holilihu.online` sender domain smoke
- `ENABLE_GOOGLE_OAUTH=false` remained the safe default until the Wiii callback
  is registered in Google Cloud Console

Treat any future public API health timeout as a release blocker until the deploy
script, Caddy routing, nginx health, and app health all agree.

## Current GCP Rebuild Target

The old documented GCP project `valued-range-443614-j4` is no longer accessible from the active deployment account. As of 2026-05-09, the active account has project `the-wiii-lab`.

Important guardrail:

- `lms-production` in `the-wiii-lab` is the LMS VM and must not be used for Wiii containers.
- Wiii should be deployed to a separate VM, default name `wiii-production`.
- The default VM profile is `e2-standard-2` in `asia-southeast1-c` with an `80GB` `pd-balanced` boot disk.
- Docker defaults are tuned for single-node production: `APP_REPLICAS=1`, `GUNICORN_WORKERS=2`, `ASYNC_POOL_MAX_SIZE=20`.

Production `.env.production` is secret-bearing and must stay on the VM. For the current NVIDIA-backed product lane, apply these non-secret shape requirements there rather than committing a changed `.env` template:

```bash
LLM_PROVIDER=nvidia
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=qwen/qwen3-next-80b-a3b-instruct
NVIDIA_MODEL_ADVANCED=deepseek-ai/deepseek-v4-pro
ENABLE_LLM_MODEL_HEALTH_PROBES=true
LLM_MODEL_HEALTH_PROBE_TIMEOUT_SECONDS=45
AGENT_PROVIDER_CONFIGS={"code_studio_agent":{"tier":"deep","provider":"nvidia","model":"deepseek-ai/deepseek-v4-pro"}}

# Required while production embeddings use models/gemini-embedding-001.
GOOGLE_API_KEY=<google-gemini-api-key>

APP_REPLICAS=1
GUNICORN_WORKERS=2
ASYNC_POOL_MAX_SIZE=20
APP_CPU_LIMIT=1.5
APP_MEM_LIMIT=2G
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
Magic Link enabled only while Resend smoke stays healthy. Keep
`ENABLE_GOOGLE_OAUTH=false` unless the matching Google OAuth callback setup has
been completed and smoke tested.

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
- probe `http://localhost:8080/api/v1/health/live`, `/health`, and `/embed/`
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
```

Minimum product smoke criteria:

- public health returns `200`
- `/embed/` returns `200` and has the expected frame policy
- SSE V3 smoke reaches metadata and done events
- a normal short chat returns without a long silent period
- LMS iframe loads Wiii without cross-origin console errors beyond known sandbox limitations
- optional Magic Link or Google OAuth smoke passes if that login method was
  changed during the release

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
