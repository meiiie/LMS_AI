#!/usr/bin/env bash
# =============================================================================
# Wiii production deployment script
#
# Safe release lane:
#   - deploy only from a clean server checkout
#   - optionally pin the repository with DEPLOY_SHA
#   - pull prebuilt GHCR images
#   - validate compose topology before rollout
#   - create a pre-migration database backup when Postgres is already running
#   - probe the app through local nginx, matching production topology
#
# Usage:
#   cd /opt/wiii
#   DEPLOY_SHA=<full-or-short-sha> \
#   WIII_APP_IMAGE=ghcr.io/meiiie/wiii-app:sha-<full-sha> \
#   WIII_NGINX_IMAGE=ghcr.io/meiiie/wiii-nginx:sha-<full-sha> \
#     ./maritime-ai-service/scripts/deploy/deploy.sh
#
# Useful overrides:
#   APP_DIR=/opt/wiii
#   BRANCH=main
#   ENV_FILE=.env.production
#   REQUIRE_PINNED_IMAGES=true
#   RUN_EXTERNAL_SMOKE=true
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

APP_DIR="${APP_DIR:-/opt/wiii}"
SERVICE_DIR="${SERVICE_DIR:-${APP_DIR}/maritime-ai-service}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
BRANCH="${BRANCH:-main}"
DEPLOY_SHA="${DEPLOY_SHA:-}"
ALLOW_PLACEHOLDERS="${ALLOW_PLACEHOLDERS:-false}"
REQUIRE_PINNED_IMAGES="${REQUIRE_PINNED_IMAGES:-false}"
SKIP_IMAGE_MANIFEST_CHECK="${SKIP_IMAGE_MANIFEST_CHECK:-false}"
IMAGE_MANIFEST_RETRIES="${IMAGE_MANIFEST_RETRIES:-4}"
IMAGE_MANIFEST_RETRY_DELAY_SECONDS="${IMAGE_MANIFEST_RETRY_DELAY_SECONDS:-5}"
SKIP_PREDEPLOY_BACKUP="${SKIP_PREDEPLOY_BACKUP:-false}"
RUN_EXTERNAL_SMOKE="${RUN_EXTERNAL_SMOKE:-false}"
SKIP_PRE_PULL_DOCKER_CLEANUP="${SKIP_PRE_PULL_DOCKER_CLEANUP:-false}"
SKIP_PRECISION_HOST_CAPACITY_CHECK="${SKIP_PRECISION_HOST_CAPACITY_CHECK:-false}"
ALLOW_LOW_MEMORY_PRECISION="${ALLOW_LOW_MEMORY_PRECISION:-false}"
MIN_PRECISION_HOST_MEM_GIB="${MIN_PRECISION_HOST_MEM_GIB:-12}"
MIN_PRECISION_DOCKER_FREE_GIB="${MIN_PRECISION_DOCKER_FREE_GIB:-12}"

case "$ENV_FILE" in
    /*)
        ENV_PATH="$ENV_FILE"
        ENV_ARG="$ENV_FILE"
        ;;
    *)
        ENV_PATH="${SERVICE_DIR}/${ENV_FILE}"
        ENV_ARG="$ENV_FILE"
        ;;
esac

env_value() {
    local key="$1"
    awk -v key="$key" '
        BEGIN { FS = "="; found = 0 }
        $0 !~ /^[[:space:]]*#/ && $1 == key {
            sub(/^[^=]*=/, "")
            print
            found = 1
        }
        END { exit found ? 0 : 1 }
    ' "$ENV_PATH" | tail -n 1
}

clean_value() {
    local value="${1:-}"
    value="${value%$'\r'}"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    printf '%s' "$value"
}

compose() {
    (cd "$SERVICE_DIR" && docker compose --env-file "$ENV_ARG" -f "$COMPOSE_FILE" "$@")
}

require_command() {
    local name="$1"
    if ! command -v "$name" >/dev/null 2>&1; then
        error "Required command not found: $name"
        exit 1
    fi
}

require_clean_checkout() {
    cd "$APP_DIR"
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        error "$APP_DIR is not a git checkout."
        exit 1
    fi

    local dirty
    dirty="$(git status --porcelain=v1)"
    if [ -n "$dirty" ]; then
        error "Server checkout has local changes. Refusing to deploy from a dirty tree."
        echo "$dirty"
        echo ""
        error "Commit, stash, or move local work before deploying. Do not deploy parallel-agent WIP."
        exit 1
    fi
}

validate_environment() {
    if [ ! -d "$SERVICE_DIR" ]; then
        error "Service directory not found: $SERVICE_DIR"
        exit 1
    fi

    if [ ! -f "$ENV_PATH" ]; then
        error "Missing production env file: $ENV_PATH"
        error "Create it from scripts/deploy/.env.production.template and replace all secrets."
        exit 1
    fi

    local required_keys=(
        WIII_APP_IMAGE
        WIII_NGINX_IMAGE
        POSTGRES_PASSWORD
        MINIO_SECRET_KEY
        API_KEY
        JWT_SECRET_KEY
        SESSION_SECRET_KEY
    )

    local key
    for key in "${required_keys[@]}"; do
        if ! grep -Eq "^${key}=.+" "$ENV_PATH"; then
            error "Missing required production env value: $key"
            exit 1
        fi
    done

    local placeholders
    placeholders="$(grep -nE '^[A-Za-z0-9_]+=.*(CHANGE_ME|your_)' "$ENV_PATH" || true)"
    if [ -n "$placeholders" ] && [ "$ALLOW_PLACEHOLDERS" != "true" ]; then
        error "Production env still contains placeholder values."
        echo "$placeholders" | head -20
        echo ""
        error "Set ALLOW_PLACEHOLDERS=true only for a non-production dry run."
        exit 1
    fi
}

sync_release_code() {
    info "Step 1/11: Syncing release code..."
    require_clean_checkout

    cd "$APP_DIR"
    git fetch --tags --prune origin "$BRANCH"

    if [ -n "$DEPLOY_SHA" ]; then
        git cat-file -e "${DEPLOY_SHA}^{commit}" 2>/dev/null || {
            error "DEPLOY_SHA is not present after fetch: $DEPLOY_SHA"
            exit 1
        }
        git checkout --detach "$DEPLOY_SHA"
    else
        if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
            git checkout "$BRANCH"
        else
            git checkout -b "$BRANCH" "origin/${BRANCH}"
        fi
        git pull --ff-only origin "$BRANCH"
    fi

    require_clean_checkout
    DEPLOYED_SHA="$(git rev-parse --short=12 HEAD)"
    info "Release checkout: ${DEPLOYED_SHA}"
}

validate_images() {
    info "Step 2/11: Validating image tags..."

    APP_IMAGE="$(clean_value "${WIII_APP_IMAGE:-$(env_value WIII_APP_IMAGE || true)}")"
    NGINX_IMAGE="$(clean_value "${WIII_NGINX_IMAGE:-$(env_value WIII_NGINX_IMAGE || true)}")"

    if [ -z "$APP_IMAGE" ] || [ -z "$NGINX_IMAGE" ]; then
        error "WIII_APP_IMAGE and WIII_NGINX_IMAGE must be set."
        exit 1
    fi

    if [[ "$APP_IMAGE" == *":main" || "$NGINX_IMAGE" == *":main" ]]; then
        if [ "$REQUIRE_PINNED_IMAGES" = "true" ]; then
            error "Floating :main image tags are blocked by REQUIRE_PINNED_IMAGES=true."
            error "Use matching sha-<commit> tags for app and nginx."
            exit 1
        fi
        warn "Using floating :main image tags. Prefer sha-<commit> tags for product releases."
    fi

    if [ "$SKIP_IMAGE_MANIFEST_CHECK" != "true" ]; then
        inspect_image_manifest_with_retry "$APP_IMAGE"
        inspect_image_manifest_with_retry "$NGINX_IMAGE"
    else
        warn "Skipping docker manifest validation."
    fi

    info "App image:   ${APP_IMAGE}"
    info "Nginx image: ${NGINX_IMAGE}"
}

validate_compose_config() {
    info "Step 3/11: Validating docker compose configuration..."
    compose config --quiet
}

inspect_image_manifest_with_retry() {
    local image="$1"
    local attempt=1
    local inspect_output=""
    local inspect_status=0

    while [ "$attempt" -le "$IMAGE_MANIFEST_RETRIES" ]; do
        set +e
        inspect_output="$(docker manifest inspect "$image" 2>&1 >/dev/null)"
        inspect_status=$?
        set -e

        if [ "$inspect_status" -eq 0 ]; then
            info "Validated image manifest: ${image}"
            return 0
        fi

        if [ -n "$inspect_output" ]; then
            inspect_output="$(printf '%s\n' "$inspect_output" | tail -n 1)"
        else
            inspect_output="unknown image manifest failure"
        fi

        if [ "$attempt" -lt "$IMAGE_MANIFEST_RETRIES" ]; then
            warn "Image manifest check failed for ${image} (attempt ${attempt}/${IMAGE_MANIFEST_RETRIES}); retrying in ${IMAGE_MANIFEST_RETRY_DELAY_SECONDS}s. Last error: ${inspect_output}"
            sleep "$IMAGE_MANIFEST_RETRY_DELAY_SECONDS"
        fi
        attempt=$((attempt + 1))
    done

    error "Image manifest check failed after ${IMAGE_MANIFEST_RETRIES} attempts: ${image}. Last error: ${inspect_output}"
    return 1
}

is_truthy() {
    case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|y|on)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

capacity_failure() {
    local message="$1"
    if is_truthy "$ALLOW_LOW_MEMORY_PRECISION"; then
        warn "${message}"
        warn "Continuing because ALLOW_LOW_MEMORY_PRECISION=true."
        return 0
    fi

    error "${message}"
    error "Resize the VM, disable precision temporarily, or set ALLOW_LOW_MEMORY_PRECISION=true for an explicit emergency deploy."
    exit 1
}

validate_host_capacity() {
    info "Step 4/11: Validating host capacity for precision document parsing..."

    local parser_mode
    local use_docling
    parser_mode="$(clean_value "${DOCUMENT_CONTEXT_PARSER_MODE:-$(env_value DOCUMENT_CONTEXT_PARSER_MODE || echo precision)}")"
    use_docling="$(clean_value "${USE_DOCLING_FOR_COURSE_GEN:-$(env_value USE_DOCLING_FOR_COURSE_GEN || echo true)}")"
    info "Configured parser profile: DOCUMENT_CONTEXT_PARSER_MODE=${parser_mode:-unset}, USE_DOCLING_FOR_COURSE_GEN=${use_docling:-unset}."

    if is_truthy "$SKIP_PRECISION_HOST_CAPACITY_CHECK"; then
        warn "Skipping precision-docs capacity guard because SKIP_PRECISION_HOST_CAPACITY_CHECK=true."
        warn "Use this only for an emergency deploy or a verified fast-only host that cannot accept per-request precision parsing."
        return 0
    fi

    local mem_total_kb=0
    local swap_total_kb=0
    local docker_path="/var/lib/docker"
    local docker_free_kb=0
    local min_mem_kb
    local min_docker_free_kb

    if [ -r /proc/meminfo ]; then
        mem_total_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
        swap_total_kb="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"
    fi
    mem_total_kb="${mem_total_kb:-0}"
    swap_total_kb="${swap_total_kb:-0}"

    [ -d "$docker_path" ] || docker_path="/"
    docker_free_kb="$(df -Pk "$docker_path" | awk 'NR==2 {print $4}')"
    docker_free_kb="${docker_free_kb:-0}"

    min_mem_kb=$((MIN_PRECISION_HOST_MEM_GIB * 1024 * 1024))
    min_docker_free_kb=$((MIN_PRECISION_DOCKER_FREE_GIB * 1024 * 1024))

    info "Precision-docs host profile: RAM=$((mem_total_kb / 1024 / 1024))GiB, swap=$((swap_total_kb / 1024 / 1024))GiB, docker-free=$((docker_free_kb / 1024 / 1024))GiB."

    if [ "$mem_total_kb" -lt "$min_mem_kb" ]; then
        capacity_failure "Precision document parsing needs at least ${MIN_PRECISION_HOST_MEM_GIB}GiB physical RAM on this single-node profile; detected $((mem_total_kb / 1024 / 1024))GiB."
    fi

    if [ "$docker_free_kb" -lt "$min_docker_free_kb" ]; then
        capacity_failure "Precision document parsing needs at least ${MIN_PRECISION_DOCKER_FREE_GIB}GiB free Docker/root disk before pulling images; detected $((docker_free_kb / 1024 / 1024))GiB at ${docker_path}."
    fi
}

cleanup_docker_before_pull() {
    if [ "$SKIP_PRE_PULL_DOCKER_CLEANUP" = "true" ]; then
        warn "Skipping Docker pre-pull cleanup because SKIP_PRE_PULL_DOCKER_CLEANUP=true."
        return 0
    fi

    info "Step 5/11: Reclaiming unused Docker image/build cache before pulling images..."
    docker system df || true

    # Do not prune volumes: production data lives in Docker volumes.
    # Running containers keep their current images pinned, so image prune only
    # removes layers not referenced by the live stack.
    docker image prune -af || true
    docker builder prune -af || true

    docker system df || true
}

pull_images() {
    info "Step 6/11: Pulling production images..."
    compose pull app nginx
}

wait_for_health() {
    local service="$1"
    local timeout="$2"
    local interval="${3:-3}"
    local elapsed=0
    local statuses=""

    while true; do
        statuses="$(compose ps --format '{{.Status}}' "$service" 2>/dev/null || true)"
        if [ -n "$statuses" ] &&
            printf '%s\n' "$statuses" | grep -qi "healthy" &&
            ! printf '%s\n' "$statuses" | grep -Eiq "unhealthy|starting"; then
            info "${service} is healthy."
            return 0
        fi

        if [ "$elapsed" -ge "$timeout" ]; then
            error "${service} did not become healthy within ${timeout}s"
            compose logs "$service" --tail 80 || true
            exit 1
        fi

        sleep "$interval"
        elapsed=$((elapsed + interval))
        echo -n "."
    done
}

start_data_services() {
    info "Step 7/11: Starting data services..."
    compose up -d postgres minio minio-init valkey
    info "Waiting for PostgreSQL..."
    wait_for_health postgres 90 3
}

create_predeploy_backup() {
    info "Step 8/11: Creating pre-deploy database backup..."

    if [ "$SKIP_PREDEPLOY_BACKUP" = "true" ]; then
        warn "Skipping pre-deploy backup because SKIP_PREDEPLOY_BACKUP=true."
        return 0
    fi

    if ! compose ps --services --status running | grep -qx "postgres"; then
        warn "PostgreSQL is not running yet; assuming first deploy and skipping backup."
        return 0
    fi

    mkdir -p "${SERVICE_DIR}/backups"
    local backup_name="predeploy_${DEPLOYED_SHA:-unknown}_$(date -u +%Y%m%d_%H%M%S).dump"
    local backup_path="${SERVICE_DIR}/backups/${backup_name}"

    compose exec -T postgres sh -c \
        'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "${POSTGRES_USER:-wiii}" -d "${POSTGRES_DB:-wiii_ai}" --format=custom --compress=6 --no-owner' \
        > "$backup_path"

    if [ ! -s "$backup_path" ]; then
        error "Pre-deploy backup was not created: $backup_path"
        exit 1
    fi

    info "Backup created: ${backup_path}"
}

run_migrations() {
    info "Step 9/11: Running Alembic migrations..."
    compose run --rm app alembic upgrade head
    info "Migrations complete."
}

start_runtime() {
    info "Step 10/11: Starting application and nginx..."
    compose up -d app
    wait_for_health app 150 3

    compose up -d nginx pg-backup
    wait_for_health nginx 60 3
}

reload_caddy() {
    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl reload caddy 2>/dev/null || warn "Caddy reload failed or Caddy is not configured yet."
    else
        warn "systemctl is unavailable; skipping Caddy reload."
    fi
}

run_final_smoke() {
    info "Step 11/11: Running local release smoke checks..."

    local nginx_port
    nginx_port="$(clean_value "${NGINX_HTTP_PORT:-$(env_value NGINX_HTTP_PORT || true)}")"
    nginx_port="${nginx_port:-8080}"
    NGINX_LOCAL_URL="${NGINX_LOCAL_URL:-http://localhost:${nginx_port}}"

    curl -fsS --max-time 15 "${NGINX_LOCAL_URL}/api/v1/health/live" >/dev/null
    curl -fsS --max-time 15 "${NGINX_LOCAL_URL}/health" >/dev/null
    curl -fsS --max-time 15 "${NGINX_LOCAL_URL}/embed/" >/dev/null

    local pointy_body
    pointy_body="$(curl -fsS --max-time 15 "${NGINX_LOCAL_URL}/pointy/wiii-pointy.umd.js")"
    if [ -z "$pointy_body" ] || printf '%s' "$pointy_body" | grep -qiE '<!doctype html|<html'; then
        error "Pointy bundle route returned empty content or SPA HTML: ${NGINX_LOCAL_URL}/pointy/wiii-pointy.umd.js"
        exit 1
    fi

    info "Local nginx smoke passed: ${NGINX_LOCAL_URL}"

    if [ "$RUN_EXTERNAL_SMOKE" = "true" ]; then
        local domain
        local base_url
        local smoke_api_key
        domain="$(clean_value "${DOMAIN:-$(env_value DOMAIN || true)}")"
        domain="${domain:-wiii.holilihu.online}"
        base_url="${BASE_URL:-https://${domain}}"
        smoke_api_key="${EXTERNAL_SMOKE_API_KEY:-$(clean_value "$(env_value API_KEY || true)")}"

        info "Running external smoke against ${base_url}"
        API_KEY="$smoke_api_key" bash "${SERVICE_DIR}/scripts/deploy/smoke-test.sh" "$base_url"
    else
        info "External smoke skipped. Run with RUN_EXTERNAL_SMOKE=true after DNS/CDN is ready."
    fi
}

print_summary() {
    local domain
    domain="$(clean_value "${DOMAIN:-$(env_value DOMAIN || true)}")"
    domain="${domain:-wiii.holilihu.online}"

    echo ""
    echo "============================================="
    info "Deployment completed"
    echo "============================================="
    echo ""
    echo "  Commit:      ${DEPLOYED_SHA:-unknown}"
    echo "  App image:   ${APP_IMAGE:-unknown}"
    echo "  Nginx image: ${NGINX_IMAGE:-unknown}"
    echo "  URL:         https://${domain}"
    echo "  Health:      https://${domain}/api/v1/health/live"
    echo ""
    echo "Useful commands:"
    echo "  cd ${SERVICE_DIR}"
    echo "  docker compose --env-file ${ENV_ARG} -f ${COMPOSE_FILE} ps"
    echo "  docker compose --env-file ${ENV_ARG} -f ${COMPOSE_FILE} logs -f app"
    echo "  bash scripts/deploy/status.sh"
    echo ""
}

main() {
    echo ""
    echo "============================================="
    echo "   Wiii Production Deploy"
    echo "   $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "============================================="
    echo ""

    require_command git
    require_command docker
    require_command curl

    validate_environment
    sync_release_code
    validate_images
    validate_compose_config
    validate_host_capacity
    cleanup_docker_before_pull
    pull_images
    start_data_services
    create_predeploy_backup
    run_migrations
    start_runtime
    reload_caddy
    run_final_smoke
    print_summary
}

main "$@"
