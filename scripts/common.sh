#!/usr/bin/env bash
# Shared helpers, sourced by the other scripts:  source "$(dirname "$0")/common.sh"
#
# PostgreSQL commands run INSIDE the postgres container by default, so the
# client (psql, pg_dump) always matches the server version. Set PG_MODE=local
# to use the psql/pg_dump on your PATH instead (configure PGHOST, PGPASSWORD...).

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT

# Load .env (KEY=VALUE lines) without overriding variables already set.
if [[ -f "$ROOT/.env" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    if [[ -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < "$ROOT/.env"
fi

: "${POSTGRES_DB:=vigia}"
: "${POSTGRES_USER:=vigia}"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# run_pg <command> [args...]: run a PostgreSQL client command (psql, pg_dump...).
run_pg() {
  if [[ "${PG_MODE:-docker}" == "local" ]]; then
    "$@"
  else
    docker compose -f "$ROOT/docker-compose.yml" exec -T postgres "$@"
  fi
}

# psql_cmd [psql args...]: psql connected to the Vigia database, stopping at the first error.
psql_cmd() {
  run_pg psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 "$@"
}
