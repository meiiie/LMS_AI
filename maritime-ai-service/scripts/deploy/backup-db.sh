#!/bin/bash
# =============================================================================
# Wiii PostgreSQL Backup Script
# by The Wiii Lab (Hong Linh Linh Hung)
#
# Usage:
#   ./backup-db.sh                    # Manual backup
#   crontab: 0 20 * * * /opt/wiii/maritime-ai-service/scripts/deploy/backup-db.sh
#   (Daily at 3 AM UTC+7 = 8 PM UTC)
#
# What this does:
#   1. Creates compressed PostgreSQL dump (pg_dump --format=custom)
#   2. Verifies backup is not empty/corrupt
#   3. Cleans old backups (keeps last 7 days locally)
#   4. Logs backup status
# =============================================================================

set -euo pipefail

# Configuration
APP_DIR="${APP_DIR:-/opt/wiii}"
SERVICE_DIR="${SERVICE_DIR:-${APP_DIR}/maritime-ai-service}"
BACKUP_DIR="${BACKUP_DIR:-${SERVICE_DIR}/backups}"
COMPOSE_FILE="docker-compose.prod.yml"
RETENTION_DAYS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/wiii_ai_${TIMESTAMP}.dump"
LOG_FILE="${BACKUP_DIR}/backup.log"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

log "=== Starting backup ==="

# ─────────────────────────────────────────────────
# Step 1: Create backup
# ─────────────────────────────────────────────────
log "Creating PostgreSQL dump..."
cd "$SERVICE_DIR"

docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U wiii -d wiii_ai \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    > "$BACKUP_FILE" 2>> "$LOG_FILE"

# ─────────────────────────────────────────────────
# Step 2: Verify backup
# ─────────────────────────────────────────────────
FILESIZE=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || echo 0)

if [ "$FILESIZE" -lt 1000 ]; then
    log "ERROR: Backup file suspiciously small (${FILESIZE} bytes). Backup may have failed!"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Verify backup integrity (pg_restore --list should work)
if ! docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_restore --list < "$BACKUP_FILE" > /dev/null 2>&1; then
    log "ERROR: Backup integrity check failed!"
    exit 1
fi

FILESIZE_HUMAN=$(numfmt --to=iec "$FILESIZE" 2>/dev/null || echo "${FILESIZE} bytes")
log "Backup created: ${BACKUP_FILE} (${FILESIZE_HUMAN})"

# ─────────────────────────────────────────────────
# Step 2b: Upload to GCS (optional — if gsutil available)
# ─────────────────────────────────────────────────
if command -v gsutil &> /dev/null; then
    GCS_BUCKET="${GCS_BACKUP_BUCKET:-}"
    if [ -n "$GCS_BUCKET" ]; then
        log "Uploading to ${GCS_BUCKET}..."
        gsutil -q cp "$BACKUP_FILE" "${GCS_BUCKET}/daily/$(basename $BACKUP_FILE)"
        if [ $? -eq 0 ]; then
            log "Upload complete: ${GCS_BUCKET}/daily/$(basename $BACKUP_FILE)"
        else
            log "WARNING: GCS upload failed — backup still saved locally"
        fi
    fi
fi

# ─────────────────────────────────────────────────
# Step 3: Clean old backups
# ─────────────────────────────────────────────────
DELETED=$(find "$BACKUP_DIR" -name "wiii_ai_*.dump" -mtime +"$RETENTION_DAYS" -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    log "Cleaned ${DELETED} old backup(s) (older than ${RETENTION_DAYS} days)"
fi

# ─────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────
TOTAL_BACKUPS=$(find "$BACKUP_DIR" -name "wiii_ai_*.dump" | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR"/*.dump 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")
log "=== Backup complete. ${TOTAL_BACKUPS} backup(s) on disk. ==="
