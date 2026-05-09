#!/bin/bash
# setup-backup-cron.sh
# One-time setup for automated PostgreSQL backups.
#
# Runs daily at 3 AM UTC+7 (8 PM UTC).
# Logs to /opt/wiii/maritime-ai-service/backups/backup.log
#
# Usage: sudo bash setup-backup-cron.sh

set -euo pipefail

SERVICE_DIR="${SERVICE_DIR:-/opt/wiii/maritime-ai-service}"
BACKUP_DIR="${BACKUP_DIR:-${SERVICE_DIR}/backups}"
BACKUP_SCRIPT="${BACKUP_SCRIPT:-${SERVICE_DIR}/scripts/deploy/backup-db.sh}"
CRON_SCHEDULE="0 20 * * *"  # 8 PM UTC = 3 AM UTC+7

# Verify script exists
if [ ! -f "$BACKUP_SCRIPT" ]; then
    echo "ERROR: Backup script not found at $BACKUP_SCRIPT"
    exit 1
fi

chmod +x "$BACKUP_SCRIPT"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Add to crontab (idempotent — removes old entry first)
(crontab -l 2>/dev/null | grep -v "backup-db.sh") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_SCHEDULE BACKUP_DIR=$BACKUP_DIR $BACKUP_SCRIPT >> $BACKUP_DIR/backup.log 2>&1") | crontab -

echo "Backup cron installed:"
crontab -l | grep backup-db
echo ""
echo "Next steps:"
echo "  1. Run a test backup: $BACKUP_SCRIPT"
echo "  2. Check logs: tail -f $BACKUP_DIR/backup.log"
echo "  3. (Optional) Set GCS_BACKUP_BUCKET=gs://your-bucket for cloud upload"
