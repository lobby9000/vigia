#!/usr/bin/env bash
# Where are the server errors of one application coming from?
# Exports the 5xx requests of the last N hours and summarises them with
# classic UNIX text tools (cut, sort, uniq, awk) instead of more SQL.
#
#   scripts/top_errors.sh payments-api        # last 24 hours
#   scripts/top_errors.sh login-service 168   # last 7 days

# shellcheck source=scripts/common.sh
source "$(dirname "$0")/common.sh"

app="${1:-}"
hours="${2:-24}"
[[ -n "$app" ]] || die "usage: $0 <app-code> [hours]"
[[ "$hours" =~ ^[0-9]+$ ]] || die "hours must be a whole number"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

# The SQL arrives on stdin so psql can substitute :'app' and :hours safely
# (:'app' is quoted by psql itself: no shell or SQL injection possible).
psql_cmd -At -F ',' -v app="$app" -v hours="$hours" > "$tmp" <<'SQL'
SELECT to_char(e.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24'), e.endpoint, e.status_code, e.region
FROM request_events e
JOIN applications a ON a.id = e.app_id
WHERE a.code = :'app'
  AND e.status_code >= 500
  AND e.occurred_at >= now() - make_interval(hours => :hours)
ORDER BY e.occurred_at;
SQL

total=$(wc -l < "$tmp")
echo "5xx errors of $app in the last $hours h: $total"
[[ "$total" -gt 0 ]] || exit 0

echo
echo "By endpoint"
cut -d',' -f2 "$tmp" | sort | uniq -c | sort -rn | head -10

echo
echo "By status code and region"
awk -F',' '{ count[$3 " " $4]++ } END { for (key in count) printf "%7d  %s\n", count[key], key }' "$tmp" | sort -rn

echo
echo "Per hour (UTC), busiest first"
cut -d',' -f1 "$tmp" | sort | uniq -c | sort -rn | head -10 |
  awk '{ bar = ""; for (i = 0; i < $1 && i < 60; i++) bar = bar "#"; printf "%s %s:00  %5d  %s\n", $2, $3, $1, bar }'
