#!/usr/bin/env bash
# =============================================================================
# Wiii production status dashboard
# =============================================================================

set -euo pipefail

SERVICE_DIR="${SERVICE_DIR:-/opt/wiii/maritime-ai-service}"
APP_DIR="${APP_DIR:-$(dirname "$SERVICE_DIR")}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

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

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

env_value() {
    local key="$1"
    [ -f "$ENV_PATH" ] || return 1
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

NGINX_HTTP_PORT="$(clean_value "${NGINX_HTTP_PORT:-$(env_value NGINX_HTTP_PORT || true)}")"
NGINX_HTTP_PORT="${NGINX_HTTP_PORT:-8080}"
NGINX_LOCAL_URL="${NGINX_LOCAL_URL:-http://localhost:${NGINX_HTTP_PORT}}"
POSTGRES_USER_VALUE="$(clean_value "${POSTGRES_USER:-$(env_value POSTGRES_USER || true)}")"
POSTGRES_USER_VALUE="${POSTGRES_USER_VALUE:-wiii}"
POSTGRES_DB_VALUE="$(clean_value "${POSTGRES_DB:-$(env_value POSTGRES_DB || true)}")"
POSTGRES_DB_VALUE="${POSTGRES_DB_VALUE:-wiii_ai}"
APP_IMAGE="$(clean_value "${WIII_APP_IMAGE:-$(env_value WIII_APP_IMAGE || true)}")"
NGINX_IMAGE="$(clean_value "${WIII_NGINX_IMAGE:-$(env_value WIII_NGINX_IMAGE || true)}")"

echo ""
echo -e "${BLUE}============================================="
echo "   Wiii Production Dashboard"
echo "   $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo -e "=============================================${NC}"

echo ""
echo -e "${GREEN}--- Release ---${NC}"
if git -C "$APP_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  Git commit:  $(git -C "$APP_DIR" rev-parse --short=12 HEAD)"
    echo "  Git branch:  $(git -C "$APP_DIR" branch --show-current 2>/dev/null || echo detached)"
else
    echo -e "  Git:         ${YELLOW}not available${NC}"
fi
echo "  App image:   ${APP_IMAGE:-unknown}"
echo "  Nginx image: ${NGINX_IMAGE:-unknown}"
echo "  Local URL:   ${NGINX_LOCAL_URL}"

echo ""
echo -e "${GREEN}--- Container Status ---${NC}"
compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "Docker compose not running"

echo ""
echo -e "${GREEN}--- Resource Usage ---${NC}"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" 2>/dev/null || echo "No running containers"

echo ""
echo -e "${GREEN}--- System ---${NC}"
echo "  Uptime:  $(uptime -p 2>/dev/null || uptime)"
echo "  RAM:     $(free -h | awk 'NR==2 {printf "%s used / %s total (%s free)", $3, $2, $7}')"
echo "  Swap:    $(free -h | awk 'NR==3 {printf "%s used / %s total", $3, $2}')"
echo "  Disk:    $(df -h / | awk 'NR==2 {printf "%s used / %s total (%s free, %s)", $3, $2, $4, $5}')"

echo ""
echo -e "${GREEN}--- Docker Disk ---${NC}"
docker system df 2>/dev/null || echo "  Docker disk usage unavailable"

echo ""
echo -e "${GREEN}--- PostgreSQL ---${NC}"
compose exec -T postgres psql -U "$POSTGRES_USER_VALUE" -d "$POSTGRES_DB_VALUE" -t -c \
    "SELECT 'Active connections: ' || count(*) FROM pg_stat_activity WHERE state = 'active';" 2>/dev/null || echo "  PostgreSQL not reachable"
compose exec -T postgres psql -U "$POSTGRES_USER_VALUE" -d "$POSTGRES_DB_VALUE" -t -c \
    "SELECT 'Database size: ' || pg_size_pretty(pg_database_size('${POSTGRES_DB_VALUE}'));" 2>/dev/null || true

echo ""
echo -e "${GREEN}--- Backups ---${NC}"
BACKUP_DIR="${BACKUP_DIR:-${SERVICE_DIR}/backups}"
BACKUP_COUNT=$(find "$BACKUP_DIR" -type f \( -name "wiii_ai_*.dump" -o -name "predeploy_*.dump" \) 2>/dev/null | wc -l)
LATEST_BACKUP=$(find "$BACKUP_DIR" -type f \( -name "wiii_ai_*.dump" -o -name "predeploy_*.dump" \) -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2- || echo "")
echo "  Total backups: ${BACKUP_COUNT}"
if [ -n "$LATEST_BACKUP" ]; then
    BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_BACKUP")) / 3600 ))
    BACKUP_SIZE=$(du -h "$LATEST_BACKUP" | awk '{print $1}')
    echo "  Latest: $(basename "$LATEST_BACKUP") (${BACKUP_SIZE}, ${BACKUP_AGE}h ago)"
else
    echo -e "  Latest: ${RED}No backups found${NC}"
fi

echo ""
echo -e "${GREEN}--- Health ---${NC}"
API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${NGINX_LOCAL_URL}/api/v1/health/live" 2>/dev/null || echo "unreachable")
NGINX_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${NGINX_LOCAL_URL}/health" 2>/dev/null || echo "unreachable")
EMBED_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${NGINX_LOCAL_URL}/embed/" 2>/dev/null || echo "unreachable")

if [ "$API_STATUS" = "200" ]; then
    echo -e "  API via nginx: ${GREEN}OK${NC} (200)"
else
    echo -e "  API via nginx: ${RED}FAIL${NC} (${API_STATUS})"
fi

if [ "$NGINX_STATUS" = "200" ]; then
    echo -e "  Nginx:         ${GREEN}OK${NC} (200)"
else
    echo -e "  Nginx:         ${RED}FAIL${NC} (${NGINX_STATUS})"
fi

if [ "$EMBED_STATUS" = "200" ]; then
    echo -e "  Embed:         ${GREEN}OK${NC} (200)"
else
    echo -e "  Embed:         ${RED}FAIL${NC} (${EMBED_STATUS})"
fi

CADDY_STATUS=$(sudo systemctl is-active caddy 2>/dev/null || echo "inactive")
if [ "$CADDY_STATUS" = "active" ]; then
    echo -e "  Caddy:         ${GREEN}active${NC}"
else
    echo -e "  Caddy:         ${YELLOW}${CADDY_STATUS}${NC}"
fi

echo ""
