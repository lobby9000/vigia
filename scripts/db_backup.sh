#!/usr/bin/env bash
# Compressed PostgreSQL backup with simple retention.
#
#   scripts/db_backup.sh                 # writes backups/vigia_YYYYmmdd_HHMMSS.dump
#   KEEP_DAYS=3 scripts/db_backup.sh     # keep only 3 days of backups
#
# Restore into an empty database:
#   pg_restore --clean --if-exists -d vigia backups/vigia_20261007_031500.dump
#
# Cron, every night at 03:15:
#   15 3 * * * /home/you/vigia/scripts/db_backup.sh >> /home/you/vigia/backup.log 2>&1

# shellcheck source=scripts/common.sh
source "$(dirname "$0")/common.sh"

BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"
mkdir -p "$BACKUP_DIR"

file="$BACKUP_DIR/${POSTGRES_DB}_$(date +%Y%m%d_%H%M%S).dump"
tmp="$file.partial"
# If anything fails, never leave a half-written file that looks like a valid backup.
trap 'rm -f "$tmp"' ERR

# -Fc: custom format (compressed, restorable table by table with pg_restore)
run_pg pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$tmp"
mv "$tmp" "$file"
log "backup written: $file ($(du -h "$file" | cut -f1))"

# Retention: delete dumps older than KEEP_DAYS days
deleted=$(find "$BACKUP_DIR" -name "${POSTGRES_DB}_*.dump" -type f -mtime +"$KEEP_DAYS" -print -delete | wc -l)
log "retention: removed $deleted backup(s) older than $KEEP_DAYS days"
