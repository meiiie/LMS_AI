#!/usr/bin/env bash
# =============================================================================
# Wiii production health check
#
# This script is meant for cron/systemd monitoring on the production VM.
# It probes the public-facing app through local nginx, not localhost:8000,
# because the app container is intentionally private on the Docker network.
# =============================================================================

set -euo pipefail

SERVICE_DIR="${SERVICE_DIR:-/opt/wiii/maritime-ai-service}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
ALERT_FILE="${ALERT_FILE:-/tmp/wiii_alert_sent}"
LOG_FILE="${LOG_FILE:-/var/log/wiii-health.log}"
REQUIRED_SERVICES=(postgres minio valkey app nginx pg-backup)

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
DOMAIN="$(clean_value "${WIII_DOMAIN:-${DOMAIN:-$(env_value DOMAIN || true)}}")"
DOMAIN="${DOMAIN:-wiii.holilihu.online}"

DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

check_api() {
    local response_code
    response_code=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time 10 --connect-timeout 5 \
        "${NGINX_LOCAL_URL}/api/v1/health/live") || response_code=0

    if [ "$response_code" != "200" ]; then
        echo "API health via nginx returned ${response_code} (expected 200)"
        return 1
    fi
    return 0
}

check_nginx() {
    local response_code
    response_code=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time 5 --connect-timeout 3 \
        "${NGINX_LOCAL_URL}/health") || response_code=0

    if [ "$response_code" != "200" ]; then
        echo "Nginx health returned ${response_code}"
        return 1
    fi
    return 0
}

check_containers() {
    local unhealthy
    local running_services
    local missing_services=""
    local service

    running_services=$(compose ps --services --status running 2>/dev/null || echo "")
    for service in "${REQUIRED_SERVICES[@]}"; do
        if ! printf '%s\n' "$running_services" | grep -qx "$service"; then
            missing_services="${missing_services}${service} "
        fi
    done

    unhealthy=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" 2>/dev/null || echo "")

    if [ -n "$missing_services" ] && [ -n "$unhealthy" ]; then
        echo "Missing required services: ${missing_services%% }. Unhealthy containers: ${unhealthy}"
        return 1
    fi

    if [ -n "$missing_services" ]; then
        echo "Missing required services: ${missing_services%% }"
        return 1
    fi

    if [ -n "$unhealthy" ]; then
        echo "Unhealthy containers: ${unhealthy}"
        return 1
    fi

    return 0
}

check_disk() {
    local usage
    usage=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
    if [ "$usage" -gt 85 ]; then
        echo "Disk usage at ${usage}%"
        return 1
    fi
    return 0
}

check_memory() {
    local available
    available=$(free -m | awk 'NR==2 {print $7}')
    if [ "$available" -lt 256 ]; then
        echo "Only ${available}MB RAM available"
        return 1
    fi
    return 0
}

send_alert() {
    local message="$1"
    local is_recovery="${2:-false}"
    local marker="[ALERT]"
    local title="Wiii Production Alert"

    if [ "$is_recovery" = "true" ]; then
        marker="[RECOVERED]"
        title="Wiii Production Recovered"
    fi

    if [ -n "$DISCORD_WEBHOOK_URL" ]; then
        curl -s -H "Content-Type: application/json" \
            -d "{\"content\":\"${marker} **${title}**\n${message}\nTime: $(date -Iseconds)\nDomain: ${DOMAIN}\"}" \
            "$DISCORD_WEBHOOK_URL" >/dev/null 2>&1 || true
    fi

    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${marker} ${title}%0A${message}%0ATime: $(date -Iseconds)" \
            -d "parse_mode=HTML" >/dev/null 2>&1 || true
    fi
}

ERRORS=""

api_err=$(check_api 2>&1) || ERRORS+="${api_err}. "
nginx_err=$(check_nginx 2>&1) || ERRORS+="${nginx_err}. "
container_err=$(check_containers 2>&1) || ERRORS+="${container_err}. "
disk_err=$(check_disk 2>&1) || ERRORS+="${disk_err}. "
memory_err=$(check_memory 2>&1) || ERRORS+="${memory_err}. "

if [ -n "$ERRORS" ]; then
    if [ ! -f "$ALERT_FILE" ] || [ $(( $(date +%s) - $(stat -c %Y "$ALERT_FILE" 2>/dev/null || echo 0) )) -gt 1800 ]; then
        send_alert "$ERRORS"
        touch "$ALERT_FILE"
    fi
    echo "[$(date)] ALERT: ${ERRORS}" >> "$LOG_FILE" 2>/dev/null || true
    echo "$ERRORS"
    exit 1
fi

if [ -f "$ALERT_FILE" ]; then
    send_alert "All checks passing." "true"
    rm -f "$ALERT_FILE"
fi

echo "Wiii production health OK via ${NGINX_LOCAL_URL}"
