"""Shared fixtures.

Integration tests run against a real PostgreSQL (the SQL uses PostgreSQL
features: percentile_cont, date_bin, FILTER, ranges, materialized views), so
an in-memory SQLite substitute would test the wrong thing.

    docker compose up -d postgres
    TEST_DATABASE_URL=postgresql+psycopg://vigia:<password>@localhost:5432/vigia_test pytest

The database named in TEST_DATABASE_URL is wiped and rebuilt from
database/*.sql. Without a reachable server those tests are skipped, unless
REQUIRE_DB=1 (CI sets it) turns the skip into a failure.
MongoDB is replaced by mongomock, an in-memory fake with the pymongo API.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mongomock
import numpy as np
import psycopg
import pytest
from flask_jwt_extended import create_access_token

from vigia_analytics import create_app
from vigia_analytics import repository as repo
from vigia_analytics.security import hash_password

SQL_DIR = Path(__file__).resolve().parents[2] / "database"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://vigia:vigia@localhost:5432/vigia_test")
TEST_SECRET = "test-only-secret-" + "0123456789abcdef" * 3  # 65 chars

VIEWER = ("ana", "viewer-pass-123")
ADMIN = ("root", "admin-pass-123")


def _plain_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def database_url() -> str:
    try:
        conn = psycopg.connect(_plain_url(TEST_DATABASE_URL), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        if os.environ.get("REQUIRE_DB"):
            raise
        pytest.skip(f"PostgreSQL not reachable ({exc}). Start it with: docker compose up -d postgres")
    with conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        for name in ("01_schema.sql", "02_views.sql", "03_seed_reference.sql"):
            conn.execute((SQL_DIR / name).read_text())
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def app(database_url):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": database_url,
            "JWT_SECRET_KEY": TEST_SECRET,
            "MONGO_CLIENT": mongomock.MongoClient(tz_aware=True),
        }
    )
    engine = app.extensions["vigia.engine"]
    with engine.begin() as conn:
        repo.upsert_user(conn, VIEWER[0], hash_password(VIEWER[1]), "viewer")
        repo.upsert_user(conn, ADMIN[0], hash_password(ADMIN[1]), "admin")
    _load_events(engine)
    yield app
    engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def engine(app):
    return app.extensions["vigia.engine"]


@pytest.fixture()
def mongo(app):
    return app.extensions["vigia.mongo"]


def _bearer(app, username: str, role: str) -> dict:
    with app.app_context():
        token = create_access_token(identity=username, additional_claims={"role": role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def viewer_headers(app):
    return _bearer(app, VIEWER[0], "viewer")


@pytest.fixture()
def admin_headers(app):
    return _bearer(app, ADMIN[0], "admin")


# --------------------------------------------------------------------------------
# Test data: 48 h of traffic for two applications, with two known incidents
# --------------------------------------------------------------------------------
NOW = datetime.now(UTC).replace(second=0, microsecond=0)
LATENCY_INCIDENT = (NOW - timedelta(hours=10), NOW - timedelta(hours=9))  # payments-api, p95 x5
ERROR_INCIDENT = (NOW - timedelta(hours=4), NOW - timedelta(hours=3, minutes=30))  # login-service, 25 % 5xx


def _load_events(engine) -> None:
    """Insert ~150 requests per 15 minutes for payments-api and login-service.

    More than 100 per bucket on purpose: below that, the detector does not judge latency.
    """
    rng = np.random.default_rng(7)
    start = NOW - timedelta(hours=48)
    with engine.begin() as conn:
        ids = dict(conn.exec_driver_sql("SELECT code, id FROM applications").all())
        raw = conn.connection.dbapi_connection
        with (
            raw.cursor() as cur,
            cur.copy(
                "COPY request_events (app_id, occurred_at, endpoint, http_method, status_code, latency_ms, region) "
                "FROM STDIN"
            ) as copy,
        ):
            for code, endpoint, median_ms in (
                ("payments-api", "/v1/payments", 150),
                ("login-service", "/v1/login", 80),
            ):
                minutes = 48 * 60
                offsets = np.sort(rng.uniform(0, minutes * 60, size=minutes * 10))  # 10 requests per minute
                for offset in offsets:
                    ts = start + timedelta(seconds=float(offset))
                    latency = rng.lognormal(np.log(median_ms), 0.3)
                    status = 500 if rng.random() < 0.002 else 200
                    if code == "payments-api" and LATENCY_INCIDENT[0] <= ts < LATENCY_INCIDENT[1]:
                        latency *= 5
                    if code == "login-service" and ERROR_INCIDENT[0] <= ts < ERROR_INCIDENT[1]:
                        status = 503 if rng.random() < 0.25 else 200
                    copy.write_row((ids[code], ts, endpoint, "POST", status, int(latency), "mx-central"))
    with engine.begin() as conn:
        repo.refresh_daily_stats(conn)
