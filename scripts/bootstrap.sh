#!/usr/bin/env bash
# First run on a new machine: secrets, containers, users and demo data.
#
#   ./scripts/bootstrap.sh
#
# Safe to run again: it keeps an existing .env and existing users.

# shellcheck source=scripts/common.sh
source "$(dirname "$0")/common.sh"
cd "$ROOT" || exit 1

command -v docker >/dev/null || die "Docker is not installed (see the README, 'Requirements')."
docker compose version >/dev/null 2>&1 || die "The Docker Compose plugin is missing (sudo apt install docker-compose-plugin)."
command -v openssl >/dev/null || die "openssl is required to generate secrets."
command -v curl >/dev/null || die "curl is required (sudo apt install curl)."

# 1) .env with random secrets (hex keeps them URL-safe for connection strings)
if [[ ! -f .env ]]; then
  log "Creating .env with random secrets"
  sed -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 16)/" \
      -e "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" \
      -e "s/^DJANGO_SECRET_KEY=.*/DJANGO_SECRET_KEY=$(openssl rand -hex 32)/" \
      -e "s/^VIGIA_ADMIN_PASSWORD=.*/VIGIA_ADMIN_PASSWORD=$(openssl rand -hex 8)/" \
      -e "s/^VIGIA_VIEWER_PASSWORD=.*/VIGIA_VIEWER_PASSWORD=$(openssl rand -hex 8)/" \
      .env.example > .env
  chmod 600 .env   # only your user can read the secrets
  # shellcheck disable=SC1091
  set -a; source .env; set +a
else
  log ".env already exists, keeping it"
fi

# 2) Build and start everything
log "Building and starting containers (the first build downloads a lot, be patient)"
docker compose up -d --build

# 3) Wait until the services answer
wait_for() {
  local name="$1" url="$2"
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then log "$name is up"; return 0; fi
    sleep 3
  done
  die "$name did not answer at $url. Check: docker compose logs $name"
}
wait_for analytics-api http://localhost:8000/health
wait_for ingest-service http://localhost:8080/actuator/health
wait_for dashboard http://localhost:8001/login/

# 4) Users: one admin and one viewer for the API, one superuser for Django
log "Creating API users (admin, viewer)"
docker compose exec -T -e VIGIA_USER_PASSWORD="$VIGIA_ADMIN_PASSWORD" analytics-api \
  flask --app vigia_analytics create-user admin --role admin
docker compose exec -T -e VIGIA_USER_PASSWORD="$VIGIA_VIEWER_PASSWORD" analytics-api \
  flask --app vigia_analytics create-user viewer --role viewer

log "Creating the Django superuser 'admin' (skipped if it exists)"
docker compose exec -T -e DJANGO_SUPERUSER_PASSWORD="$VIGIA_ADMIN_PASSWORD" dashboard \
  python manage.py createsuperuser --noinput --username admin --email admin@example.com 2>/dev/null \
  || log "Django user 'admin' already exists"

cat <<EOF

Vigia is running.
  Dashboard (Django)        http://localhost:8001         user: admin
  Analytics API (Flask)     http://localhost:8000/docs    users: admin / viewer
  Ingest service (Spring)   http://localhost:8080/swagger-ui.html
Passwords are in .env (VIGIA_ADMIN_PASSWORD, VIGIA_VIEWER_PASSWORD).

Next: load demo data
  python3 scripts/generate_history.py --truncate --database-url postgresql://$POSTGRES_USER:<POSTGRES_PASSWORD>@localhost:5432/$POSTGRES_DB
  python3 scripts/simulate_traffic.py --canary checkout-web
(or simply: make seed && make simulate)
EOF
