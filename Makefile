# Shortcuts for everyday tasks. Run `make` to list them.
-include .env
export

DB_URL = postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:5432/$(POSTGRES_DB)
PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help bootstrap up down logs ps seed simulate scan calibrate refresh backup psql test test-python test-django test-java lint

help: ## List the available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-12s %s\n", $$1, $$2}'

bootstrap: ## First run: .env with secrets, containers, users
	./scripts/bootstrap.sh

up: ## Build and start the whole stack
	docker compose up -d --build

down: ## Stop the stack (the data volumes are kept)
	docker compose down

logs: ## Follow the logs of every service
	docker compose logs -f --tail=100

ps: ## Show the containers and their health
	docker compose ps

seed: ## Load 10 days of synthetic history (wipes previous events)
	$(PYTHON) scripts/generate_history.py --truncate --database-url $(DB_URL)

simulate: ## Send the last hour of live traffic through the Java API, with a failing canary
	$(PYTHON) scripts/simulate_traffic.py --canary checkout-web

scan: ## Run the anomaly detector on every application (logs in as admin)
	./scripts/scan_all.sh

calibrate: ## Re-check the detector thresholds by simulation (about 30 s, no database needed)
	$(PYTHON) scripts/calibrate_detector.py

refresh: ## Refresh the daily statistics materialized view
	./scripts/refresh_views.sh

backup: ## Compressed pg_dump into backups/
	./scripts/db_backup.sh

psql: ## Open psql inside the PostgreSQL container
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

test: test-python test-django test-java ## Run every test suite

test-python: ## Flask API tests (needs: docker compose up -d postgres)
	-docker compose exec -T postgres createdb -U $(POSTGRES_USER) vigia_test 2>/dev/null
	cd analytics-api && TEST_DATABASE_URL=postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:5432/vigia_test $(PYTHON) -m pytest

test-django: ## Django tests (creates and drops a test database)
	cd dashboard && DJANGO_DEBUG=1 DATABASE_URL=postgres://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:5432/$(POSTGRES_DB) $(PYTHON) manage.py test

test-java: ## Spring Boot tests
	cd ingest-service && mvn -B -q test

lint: ## Ruff for Python, shellcheck for Bash
	ruff check analytics-api dashboard scripts
	shellcheck -x scripts/*.sh
