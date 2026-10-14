"""All SQL lives here: one function per question the API asks PostgreSQL.

Rules followed in every query
* Values always travel as bound parameters (``:name``), never with string
  formatting. That is what makes SQL injection impossible.
* Aggregations happen in the database, close to the data. Python receives
  hundreds of rows, not millions.
* Functions receive a ``Connection`` so the caller decides the transaction
  boundaries (one read, or several writes that must succeed together).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

# ---------------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------------
_APPLICATIONS = text("""
    SELECT a.id, a.code, a.name, t.name AS team, a.tier,
           a.slo_availability, a.slo_latency_p95_ms, a.active
    FROM applications a
    JOIN teams t ON t.id = a.team_id
    ORDER BY a.tier, a.code
""")

_APPLICATION_BY_CODE = text("""
    SELECT a.id, a.code, a.name, t.name AS team, a.tier,
           a.slo_availability, a.slo_latency_p95_ms, a.active
    FROM applications a
    JOIN teams t ON t.id = a.team_id
    WHERE a.code = :code
""")


def list_applications(conn: Connection) -> list[dict]:
    return [dict(row) for row in conn.execute(_APPLICATIONS).mappings()]


def get_application(conn: Connection, code: str) -> dict | None:
    row = conn.execute(_APPLICATION_BY_CODE, {"code": code}).mappings().first()
    return dict(row) if row else None


# ---------------------------------------------------------------------------------
# Health time series
# ---------------------------------------------------------------------------------
# date_bin() snaps every timestamp to the start of its bucket (5, 15, 30 or 60
# minutes, aligned to midnight UTC). The (app_id, occurred_at) covering index
# answers the WHERE clause with an index-only scan.
_BUCKET_SERIES = text("""
    SELECT date_bin(:bucket, e.occurred_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket,
           COUNT(*)                                                     AS requests,
           COUNT(*) FILTER (WHERE e.status_code >= 500)                 AS errors_5xx,
           AVG(e.latency_ms)::float8                                    AS avg_latency_ms,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY e.latency_ms)   AS p50_latency_ms,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY e.latency_ms)   AS p95_latency_ms
    FROM request_events e
    WHERE e.app_id = :app_id
      AND e.occurred_at >= :start
      AND e.occurred_at <  :end
    GROUP BY bucket
    ORDER BY bucket
""")


def fetch_bucket_series(
    conn: Connection, app_id: int, start: datetime, end: datetime, bucket_minutes: int
) -> pd.DataFrame:
    """One row per bucket that had traffic. Buckets without requests are absent."""
    frame = pd.read_sql(
        _BUCKET_SERIES,
        conn,
        params={"app_id": app_id, "start": start, "end": end, "bucket": timedelta(minutes=bucket_minutes)},
    )
    frame["bucket"] = pd.to_datetime(frame["bucket"], utc=True)
    frame["error_rate"] = frame["errors_5xx"] / frame["requests"]
    return frame


# ---------------------------------------------------------------------------------
# SLO report (reads the materialized view)
# ---------------------------------------------------------------------------------
# error_budget_consumed = observed error rate / allowed error rate.
# Example: SLO 99.9 % allows 0.1 % errors; observing 0.05 % means 50 % of the
# budget is spent. RANK() orders applications by how much of their own budget
# they have burned (worst first), so a 99 % app is not compared with a 99.95 % one.
_SLO_REPORT = text("""
    WITH window_stats AS (
        SELECT s.app_id,
               SUM(s.requests)                                                AS requests,
               SUM(s.errors_5xx)                                              AS errors_5xx,
               COUNT(*) FILTER (WHERE s.p95_latency_ms > a.slo_latency_p95_ms) AS days_breaching_latency,
               COUNT(*)                                                       AS days_with_data
        FROM mv_app_daily_stats s
        JOIN applications a ON a.id = s.app_id
        WHERE s.day > (now() AT TIME ZONE 'UTC')::date - CAST(:days AS integer)
        GROUP BY s.app_id
    ),
    scored AS (
        SELECT w.*,
               w.errors_5xx::numeric / NULLIF(w.requests, 0) AS error_rate
        FROM window_stats w
    )
    SELECT a.code                                              AS app_code,
           a.name                                              AS app_name,
           t.name                                              AS team,
           a.tier,
           s.requests,
           s.errors_5xx,
           1 - s.error_rate                                    AS availability,
           a.slo_availability,
           s.error_rate / (1 - a.slo_availability)             AS error_budget_consumed,
           s.days_breaching_latency,
           s.days_with_data,
           RANK() OVER (ORDER BY s.error_rate / (1 - a.slo_availability) DESC NULLS LAST) AS worst_rank,
           CASE
               WHEN 1 - s.error_rate < a.slo_availability              THEN 'BREACHED'
               WHEN s.error_rate / (1 - a.slo_availability) >= 0.75
                    OR s.days_breaching_latency > 0                    THEN 'AT_RISK'
               ELSE 'OK'
           END                                                 AS status
    FROM scored s
    JOIN applications a ON a.id = s.app_id
    JOIN teams t        ON t.id = a.team_id
    ORDER BY worst_rank, a.code
""")


def slo_report(conn: Connection, days: int) -> list[dict]:
    return [dict(row) for row in conn.execute(_SLO_REPORT, {"days": days}).mappings()]


def refresh_daily_stats(conn: Connection) -> None:
    # CONCURRENTLY keeps the view readable while it is rebuilt (needs the unique index).
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_app_daily_stats"))


# ---------------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------------
_INCIDENT_COLUMNS = """
    i.id, a.code AS app_code, a.name AS app_name, i.title, i.description,
    i.severity, i.status, i.source, i.opened_at, i.acknowledged_at, i.resolved_at,
    i.window_start, i.window_end, i.report_id
"""

# CAST(:x AS text) IS NULL OR ... turns a filter off when the parameter is None,
# so one parameterised statement serves every filter combination.
# COUNT(*) OVER () returns the total before LIMIT in the same round trip.
_LIST_INCIDENTS = text(f"""
    SELECT {_INCIDENT_COLUMNS},
           COUNT(*) OVER () AS total_count
    FROM incidents i
    JOIN applications a ON a.id = i.app_id
    WHERE (CAST(:status AS text) IS NULL OR i.status = :status)
      AND (CAST(:app_code AS text) IS NULL OR a.code = :app_code)
    ORDER BY i.opened_at DESC, i.id DESC
    LIMIT :limit OFFSET :offset
""")

_GET_INCIDENT = text(f"""
    SELECT {_INCIDENT_COLUMNS}
    FROM incidents i
    JOIN applications a ON a.id = i.app_id
    WHERE i.id = :id
""")

# FOR UPDATE locks the row until the transaction ends: two people resolving the
# same incident at the same time cannot both read "OPEN" and both write.
_LOCK_INCIDENT = text("SELECT status FROM incidents WHERE id = :id FOR UPDATE")

# The explicit CAST gives :status one type in both places it appears; without
# it PostgreSQL deduces varchar (column) and text (comparison) and refuses.
_UPDATE_INCIDENT_STATUS = text("""
    UPDATE incidents
    SET status          = CAST(:status AS varchar),
        acknowledged_at = COALESCE(acknowledged_at, now()),
        resolved_at     = CASE WHEN CAST(:status AS varchar) = 'RESOLVED' THEN now() ELSE NULL END
    WHERE id = :id
""")

# Insert only if the detector has not already opened an incident whose time
# window overlaps this one (&& is the "ranges overlap" operator). Re-running a
# scan over the same period therefore never duplicates incidents.
_INSERT_DETECTOR_INCIDENT = text("""
    INSERT INTO incidents (app_id, title, description, severity, source,
                           window_start, window_end, report_id)
    SELECT :app_id, :title, :description, :severity, 'anomaly_detector',
           :window_start, :window_end, :report_id
    WHERE NOT EXISTS (
        SELECT 1
        FROM incidents i
        WHERE i.app_id = :app_id
          AND i.source = 'anomaly_detector'
          AND tstzrange(i.window_start, i.window_end, '[]')
              && tstzrange(CAST(:window_start AS timestamptz), CAST(:window_end AS timestamptz), '[]')
    )
    RETURNING id
""")


def list_incidents(
    conn: Connection, status: str | None, app_code: str | None, limit: int, offset: int
) -> tuple[list[dict], int]:
    rows = (
        conn.execute(
            _LIST_INCIDENTS,
            {"status": status, "app_code": app_code, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    total = rows[0]["total_count"] if rows else 0
    return [{k: v for k, v in row.items() if k != "total_count"} for row in rows], total


def get_incident(conn: Connection, incident_id: int) -> dict | None:
    row = conn.execute(_GET_INCIDENT, {"id": incident_id}).mappings().first()
    return dict(row) if row else None


def lock_incident_status(conn: Connection, incident_id: int) -> str | None:
    return conn.execute(_LOCK_INCIDENT, {"id": incident_id}).scalar()


def update_incident_status(conn: Connection, incident_id: int, status: str) -> None:
    conn.execute(_UPDATE_INCIDENT_STATUS, {"id": incident_id, "status": status})


def insert_detector_incident(conn: Connection, **values) -> int | None:
    """Returns the new id, or None when an overlapping incident already exists."""
    return conn.execute(_INSERT_DETECTOR_INCIDENT, values).scalar()


# ---------------------------------------------------------------------------------
# API users
# ---------------------------------------------------------------------------------
def find_active_user(conn: Connection, username: str) -> dict | None:
    row = (
        conn.execute(
            text("SELECT username, password_hash, role FROM api_users WHERE username = :u AND active"),
            {"u": username},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def upsert_user(conn: Connection, username: str, password_hash: str, role: str) -> None:
    conn.execute(
        text("""
            INSERT INTO api_users (username, password_hash, role)
            VALUES (:u, :h, :r)
            ON CONFLICT (username) DO UPDATE
               SET password_hash = EXCLUDED.password_hash,
                   role          = EXCLUDED.role,
                   active        = TRUE
        """),
        {"u": username, "h": password_hash, "r": role},
    )


def ping(conn: Connection) -> None:
    conn.execute(text("SELECT 1"))
