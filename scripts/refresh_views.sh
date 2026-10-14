#!/usr/bin/env bash
# Rebuild the daily statistics materialized view without blocking readers.
#
# Meant for cron. Every 15 minutes, logging to a file:
#   */15 * * * * /home/you/vigia/scripts/refresh_views.sh >> /home/you/vigia/refresh.log 2>&1

# shellcheck source=scripts/common.sh
source "$(dirname "$0")/common.sh"

started=$(date +%s)
psql_cmd -q -c "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_app_daily_stats"
log "mv_app_daily_stats refreshed in $(( $(date +%s) - started )) s"
