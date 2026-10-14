"""Read-only analytical queries in raw SQL.

The ORM is great for CRUD on one table (see models.py and admin.py). For
analytics with percentiles, FILTER clauses, date_bin() or materialized views,
plain SQL is clearer and faster. Values still travel as parameters (%s), never
inside the string.
"""

from datetime import timedelta

from django.db import connection


def _fetch_all(sql: str, params=None) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def status_last_hour() -> list[dict]:
    return _fetch_all("SELECT * FROM v_app_status_last_hour ORDER BY tier, code")


def slo_last_days(days: int = 7) -> dict[str, dict]:
    """Availability and error budget per application code (from the daily materialized view)."""
    rows = _fetch_all(
        """
        SELECT a.code,
               SUM(s.requests)                                              AS requests,
               1 - SUM(s.errors_5xx)::numeric / NULLIF(SUM(s.requests), 0)  AS availability,
               (SUM(s.errors_5xx)::numeric / NULLIF(SUM(s.requests), 0))
                   / (1 - a.slo_availability)                               AS budget_consumed
        FROM mv_app_daily_stats s
        JOIN applications a ON a.id = s.app_id
        WHERE s.day > (now() AT TIME ZONE 'UTC')::date - %s
        GROUP BY a.code, a.slo_availability
        """,
        [days],
    )
    return {row["code"]: row for row in rows}


def bucket_series(app_id: int, hours: int, bucket_minutes: int) -> list[dict]:
    return _fetch_all(
        """
        SELECT date_bin(%s, e.occurred_at, TIMESTAMPTZ '2000-01-01 00:00:00+00')  AS bucket,
               COUNT(*)                                                       AS requests,
               COUNT(*) FILTER (WHERE e.status_code >= 500)::float8 / COUNT(*) AS error_rate,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY e.latency_ms)     AS p95_latency_ms
        FROM request_events e
        WHERE e.app_id = %s
          AND e.occurred_at >= now() - %s
        GROUP BY bucket
        ORDER BY bucket
        """,
        [timedelta(minutes=bucket_minutes), app_id, timedelta(hours=hours)],
    )


def health_of(status: dict, open_incidents: int) -> str:
    """Traffic-light status from the last hour: idle, ok, degraded or critical."""
    if not status["requests"]:
        return "idle"
    allowed_error_rate = 1 - float(status["slo_availability"])
    error_rate = float(status["error_rate"] or 0)
    p95 = float(status["p95_latency_ms"] or 0)
    objective = status["slo_latency_p95_ms"]
    if error_rate > 5 * allowed_error_rate or p95 > 2 * objective:
        return "critical"
    if error_rate > allowed_error_rate or p95 > objective or open_incidents:
        return "degraded"
    return "ok"
