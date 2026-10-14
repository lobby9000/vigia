#!/usr/bin/env bash
# Log in to the analytics API as admin and run the anomaly detector on every
# application. Uses VIGIA_ADMIN_PASSWORD from .env.
#
#   scripts/scan_all.sh          # last 240 hours (10 days)
#   scripts/scan_all.sh 24       # last day only

# shellcheck source=scripts/common.sh
source "$(dirname "$0")/common.sh"

API="${API_URL:-http://localhost:8000}"
HOURS="${1:-240}"
[[ "$HOURS" =~ ^[0-9]+$ ]] || die "hours must be a whole number"
[[ -n "${VIGIA_ADMIN_PASSWORD:-}" ]] || die "VIGIA_ADMIN_PASSWORD is not set (run scripts/bootstrap.sh first)"

json_field='import json, sys
print(json.load(sys.stdin)[sys.argv[1]])'
app_codes='import json, sys
print(" ".join(app["code"] for app in json.load(sys.stdin)))'
summary='import json, sys
r = json.load(sys.stdin)
print("{:<18} episodes={}  incidents opened={}".format(r["appCode"], len(r["episodes"]), r["incidentsOpened"]))'

token=$(curl -fsS -X POST "$API/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\": \"admin\", \"password\": \"$VIGIA_ADMIN_PASSWORD\"}" | python3 -c "$json_field" accessToken)

apps=$(curl -fsS "$API/api/v1/applications" -H "Authorization: Bearer $token" | python3 -c "$app_codes")

for app in $apps; do
  curl -fsS -X POST "$API/api/v1/applications/$app/anomaly-scans" \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "{\"hours\": $HOURS}" | python3 -c "$summary"
done
