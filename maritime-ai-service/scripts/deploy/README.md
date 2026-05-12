# Wiii Production Deployment Guide

> **Team**: Hong Linh Linh Hung (holilihu.online)
>
> GCP Compute Engine + Caddy (auto-SSL) + Nginx + Docker Compose
>
> Target: 10K+ users, ~380K VND/month (~$15 USD)

---

## Product Release Lane

For product launches and release-candidate deploys, use the repository-level runbook:

```text
docs/operations/WIII_PRODUCT_RELEASE_RUNBOOK.md
```

That runbook is the canonical checklist for pinned-SHA deploys, GHCR image verification, smoke tests, rollback, and parallel-team safety. The short version is: deploy from a clean `main` checkout, use matching `sha-...` tags for app and nginx, and probe the app through local nginx (`http://localhost:8080`) because the app container is not exposed on the host.

Current GCP rebuild helper:

```bash
PROJECT_ID=the-wiii-lab \
ZONE=asia-southeast1-c \
  bash maritime-ai-service/scripts/deploy/provision-gcp-vm.sh
```

This creates a separate `wiii-production` VM. Do not deploy Wiii containers onto the existing `lms-production` VM.
Canonical target details live in `docs/operations/WIII_PRODUCT_RELEASE_RUNBOOK.md#current-gcp-rebuild-target`.

---

## Architecture

```
Internet
    │
    ▼
┌──────────────────────────────────────┐
│  Cloudflare DNS (free)               │  DDoS protection, CDN
│  *.holilihu.online → GCP Static IP   │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│  GCP Compute Engine (e2-medium)      │  2 vCPU, 4GB RAM
│  Ubuntu 22.04 LTS                    │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ Caddy (host service)          │  │  Auto-SSL (Let's Encrypt)
│  │ :443 → Nginx :80              │  │  HTTPS termination
│  └────────────────────────────────┘  │
│           │                          │
│  ┌────────────────────────────────┐  │
│  │ docker-compose.prod.yml       │  │
│  │  Nginx → App (API :8000)      │  │  Subdomain routing + SPA
│  │  PostgreSQL  MinIO  Valkey    │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

**Flow**: Cloudflare → Caddy (SSL) → Nginx (routing + SPA) → App (API)

---

## Step 1: Domain (Done!)

Domain `holilihu.online` has been purchased (Hong Linh Linh Hung).

> DNS will be configured after GCP VM is created (Step 5).

---

## Step 2: Create GCP VM

Go to [Google Cloud Console](https://console.cloud.google.com/) → Compute Engine → Create Instance:

| Setting | Value |
|---------|-------|
| Name | `wiii-production` |
| Region | `asia-southeast1` (Singapore — lowest latency to Vietnam) |
| Zone | `asia-southeast1-c` |
| Machine | `e2-standard-4` (4 vCPU, 16GB RAM) for Docling precision; `e2-standard-2` only for fast MarkItDown |
| Boot disk | Ubuntu 24.04 LTS, **80GB pd-balanced** |
| Firewall | HTTP/HTTPS public, SSH restricted to maintainer IPs |

After creation:
1. Go to **VPC Network → External IP addresses**
2. Find your VM's IP → click **Reserve** (makes it static)
3. Note this IP — you'll need it for DNS

Prefer the provision helper above so the VM, static IP, firewall tags, and SSH source ranges match the product runbook.

The setup script assumes this single-node profile by default: 4G swap,
conservative Docker resource limits, one app replica until Postgres/cache/object
storage move off-host, and enough RAM headroom for the Docling precision parser
plus LibreOffice-based Office layout/image conversion. Production images also
include `ffmpeg`/`ffprobe` so bounded video upload context can extract metadata
and representative keyframes.

---

## Step 3: Server Setup

SSH into your VM:

```bash
# From Google Cloud Console: click "SSH" button on VM page
# Or from terminal:
gcloud compute ssh wiii-production --zone=asia-southeast1-c --project=the-wiii-lab
```

Run the setup script:

```bash
# Option A: Run directly from repo (if public)
curl -fsSL https://raw.githubusercontent.com/<your-org>/wiii/main/maritime-ai-service/scripts/deploy/setup-server.sh | bash

# Option B: Copy and run manually
nano setup-server.sh   # Paste contents of scripts/deploy/setup-server.sh
chmod +x setup-server.sh
./setup-server.sh
```

**Important**: Log out and back in after setup for Docker group:
```bash
exit
# SSH back in
```

Verify:
```bash
docker --version      # Docker 27.x+
docker compose version # Docker Compose v2.x+
caddy version         # Caddy v2.x+
```

---

## Step 4: Deploy Application

### 4.1 Clone Repository

```bash
cd /opt/wiii
git clone https://github.com/<your-org>/wiii.git .
# If private repo, use SSH key or personal access token
```

### 4.2 Create Production Environment

```bash
cd /opt/wiii/maritime-ai-service
cp scripts/deploy/.env.production.template .env.production
nano .env.production
```

**Replace ALL `CHANGE_ME_*` values**. Generate secrets with:
```bash
openssl rand -hex 32   # For API_KEY, JWT_SECRET_KEY
openssl rand -hex 16   # For database passwords
```

### 4.3 Configure Caddy

```bash
# Edit domain name if different from holilihu.online
nano /opt/wiii/maritime-ai-service/scripts/deploy/Caddyfile

# Install Caddyfile
sudo cp /opt/wiii/maritime-ai-service/scripts/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

### 4.4 Run Deploy Script

```bash
cd /opt/wiii
chmod +x maritime-ai-service/scripts/deploy/deploy.sh
./maritime-ai-service/scripts/deploy/deploy.sh
```

If your GHCR packages are private, authenticate the host before the first image-based deploy:

```bash
echo <github_pat_with_read_packages> | docker login ghcr.io -u <github_username> --password-stdin
```

Image-based deploy time now depends mostly on image pull size and container restart time rather than on-source Docker builds on the host.

### 4.5 Image-Based Deploy Path

The `/embed/` iframe is now baked into published production images.

Current production behavior:

- the app image contains embed assets at `/app-embed`
- the nginx image contains embed assets at `/usr/share/nginx/embed`
- CI builds `wiii-desktop/dist-embed/` before the image build, and the image build copies that artifact directly
- deploy no longer depends on `wiii-desktop/dist-embed/` being present in the server checkout
- deploy pulls prebuilt tagged images instead of building them on the host

Operational consequence:

- when an embed-related change is deployed, the target image tag must already exist in GHCR
- the deploy script verifies `/embed/` after rollout

Set image tags in `.env.production`:

```bash
WIII_APP_IMAGE=ghcr.io/meiiie/wiii-app:main
WIII_NGINX_IMAGE=ghcr.io/meiiie/wiii-nginx:main
```

The legacy `ghcr.io/meiiie/lms-ai-app` and `ghcr.io/meiiie/lms-ai-nginx` tags are still being published for one release cycle so existing deployments keep pulling while they migrate. New deploys should pin the `wiii-*` names.

To deploy a pinned revision, use matching `sha-...` tags for both images.

Local development can still use:

```bash
cd /opt/wiii/wiii-desktop
npm install
npm run build:embed
```

That remains useful for local verification, but it is no longer a production deploy prerequisite.

### 4.6 Current State: `dist-embed/` No Longer Drives Production Deploys

The old model expected a checked-in embed bundle because both the app and nginx containers mounted it directly.

That is no longer required in production. `wiii-desktop/dist-embed/` has already been removed from git tracking and is now treated as generated local output.

Current target state:

- CI builds and publishes production images
- production images include the embed assets directly
- deploy pulls immutable images instead of depending on a local frontend working tree
- rollback uses image tags or digests, not rebuilt assets on the server

Validation completed so far:

- the `Build Production Images` GitHub Actions workflow runs on push to `main`
- GHCR `main` tags resolve for both app and nginx images
- local production-like deployment validation passed, including `/embed/` smoke checks

Current release controls:

- `docs/operations/WIII_PRODUCT_RELEASE_RUNBOOK.md`

Local `npm run build:embed` remains useful for developer verification, but it is no longer part of the production deployment contract.

---

## Step 5: Configure DNS

### Option A: Cloudflare (Recommended — free DDoS protection)

1. Create account at [cloudflare.com](https://cloudflare.com) (free)
2. **Add site** → enter your domain (e.g., `holilihu.online`)
3. Cloudflare gives you **2 nameservers** — update these at your registrar
4. Add DNS records:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `@` | `<GCP_STATIC_IP>` | Proxied (orange cloud) |
| A | `*` | `<GCP_STATIC_IP>` | DNS only (grey cloud) — wildcard for org subdomains |

5. SSL/TLS settings → set to **Full (strict)**

### Option B: Direct DNS (at registrar)

At your registrar's DNS panel, add:
```
A    holilihu.online      →  <GCP_STATIC_IP>    TTL: 300
A    *.holilihu.online    →  <GCP_STATIC_IP>    TTL: 300
```

> DNS propagation takes 5 minutes to 24 hours. Check: `dig holilihu.online`

---

## Step 6: Configure Webhooks

### Facebook Messenger

1. Go to [Facebook Developer Dashboard](https://developers.facebook.com/)
2. Your App → Messenger → Settings → Webhooks
3. **Callback URL**: `https://holilihu.online/api/v1/messenger/webhook`
4. **Verify Token**: same as `FACEBOOK_VERIFY_TOKEN` in `.env.production`
5. Subscribe to: `messages`, `messaging_postbacks`

### Zalo OA

1. Go to [Zalo OA Admin](https://oa.zalo.me/)
2. Settings → Webhook Configuration
3. **Callback URL**: `https://holilihu.online/api/v1/zalo/webhook`
4. **Token**: same as `ZALO_WEBHOOK_TOKEN` in `.env.production`

---

## Step 7: Verify

```bash
# Recommended: run the smoke test script against the deployed host
API_KEY=your-api-key bash scripts/deploy/smoke-test.sh https://holilihu.online

# Manual spot checks if needed:

# 1. Health check
curl https://holilihu.online/api/v1/health/live

# 2. Embed entry point
curl -I https://holilihu.online/embed/

# 3. API docs
# Open in browser: https://holilihu.online/docs

# 4. Test chat endpoint
curl -X POST https://holilihu.online/api/v1/chat \
  -H "X-API-Key: your-api-key" \
  -H "X-Session-ID: test-session" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "api-client", "message": "Xin chào!", "role": "student", "session_id": "test-session"}'

# Note: production API-key auth is service-client auth and ignores X-User-ID.
# Use JWT or LMS service token when you need real end-user identity.

# 5. Facebook webhook verification
# Facebook Developer Dashboard → Messenger → Test Callback

# 6. Zalo webhook verification
# Zalo OA Admin → Webhook → Test Connection
```

---

## Common Operations

### View logs
```bash
cd /opt/wiii/maritime-ai-service

# App logs (live)
docker compose -f docker-compose.prod.yml logs -f app

# All services
docker compose -f docker-compose.prod.yml logs -f

# Caddy logs
sudo journalctl -u caddy -f
sudo tail -f /var/log/caddy/holilihu-access.log
```

### Restart services
```bash
cd /opt/wiii/maritime-ai-service

# Restart app only
docker compose -f docker-compose.prod.yml restart app

# Restart everything
docker compose -f docker-compose.prod.yml down && docker compose -f docker-compose.prod.yml up -d
```

### Update deployment
```bash
cd /opt/wiii
./maritime-ai-service/scripts/deploy/deploy.sh
```

### Database access (emergency)
```bash
cd /opt/wiii/maritime-ai-service

# Connect to PostgreSQL
docker compose -f docker-compose.prod.yml exec postgres psql -U wiii wiii_ai

# Run specific migration
docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head
```

### Check disk usage
```bash
df -h                                    # System disk
docker system df                         # Docker disk usage
docker system prune -af --volumes        # Clean unused (CAREFUL!)
```

---

## Troubleshooting

### "SSL certificate not working"
- Caddy needs ports 80+443 open (check: `sudo ufw status`)
- DNS must point to your GCP IP (check: `dig holilihu.online`)
- Cloudflare SSL must be "Full (strict)" if using Cloudflare proxy
- Check Caddy logs: `sudo journalctl -u caddy --since "5 minutes ago"`

### "App not starting"
```bash
# Check app logs
docker compose -f docker-compose.prod.yml logs app --tail 50

# Check if .env.production has all required values
grep "CHANGE_ME" .env.production    # Should return nothing

# Check Docker health
docker compose -f docker-compose.prod.yml ps
```

### "Database connection refused"
```bash
# Check PostgreSQL is running
docker compose -f docker-compose.prod.yml ps postgres

# Check PostgreSQL logs
docker compose -f docker-compose.prod.yml logs postgres --tail 20

# Verify DATABASE_URL uses container hostname (postgres, not localhost)
grep DATABASE_URL .env.production
```

### "Webhook verification fails"
- Ensure callback URL uses HTTPS (not HTTP)
- Check verify token matches `.env.production` exactly
- Caddy must be running with valid SSL: `sudo systemctl status caddy`
- Test endpoint directly: `curl -v https://holilihu.online/api/v1/messenger/webhook?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test`

### "Out of memory"
```bash
# Check memory usage
free -h
docker stats --no-stream

# If tight, keep Gunicorn workers conservative and disable precision as a
# temporary rollback until the VM is resized.
# GUNICORN_WORKERS=2
# DOCUMENT_CONTEXT_PARSER_MODE=fast
# USE_DOCLING_FOR_COURSE_GEN=false

# Deploy has a precision-docs capacity guard because production images include
# Docling and teacher uploads can request precision parsing per document. If it
# blocks a real emergency rollback, either resize the VM or set
# ALLOW_LOW_MEMORY_PRECISION=true with an explicit operator note. Only set
# SKIP_PRECISION_HOST_CAPACITY_CHECK=true after verifying the host is fast-only
# and cannot accept per-request precision parsing. Do not treat either override
# as a steady-state fix.

# If deploy pulls are slow or disk pressure appears, verify production images
# are still CPU-only on the current non-GPU VM:
# docker compose exec app python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

---

## Cost Summary

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| GCP VM | Use Google Cloud Pricing Calculator | `e2-standard-4` recommended for precision-docs |
| `.online` domain | ~20K VND | ~250K VND/year |
| Cloudflare DNS | Free | Free tier is sufficient |
| Caddy SSL | Free | Let's Encrypt automatic |
| **Total** | **~380K VND/month** | **~$15 USD/month** |

---

## Security Notes

- `.env.production` contains secrets — **never commit to git**
- PostgreSQL and MinIO ports are **not exposed** externally (internal Docker network only)
- Caddy handles all TLS termination — internal traffic is HTTP (within Docker network)
- UFW blocks all ports except 22 (SSH), 80 (HTTP→redirect), 443 (HTTPS)
- Use SSH keys for VM access — disable password auth in `/etc/ssh/sshd_config`
- Rotate secrets regularly: `openssl rand -hex 32`

---

## Neo4j (Optional)

Neo4j is disabled by default since Sprint 165. If you need GraphRAG:

1. Set `ENABLE_NEO4J=true` in `.env.production`
2. The `docker-compose.prod.yml` includes Neo4j — it will start automatically
3. Set a strong `NEO4J_PASSWORD`

> Note: Neo4j adds ~2GB RAM usage. If Neo4j and Docling precision run on the
> same VM, keep at least the `e2-standard-4` profile or move stateful services
> off-host before increasing app workers.
