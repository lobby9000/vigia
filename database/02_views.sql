-- =============================================================================
-- Vigia | Views and materialized views
--
-- Regular views: saved queries, always fresh, computed on every read.
-- Materialized view: a stored result set. Fast to read, refreshed on demand
-- (scripts/refresh_views.sh runs it from cron, the analytics API can too).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Daily statistics per application (feeds the SLO report and the dashboard)
--
-- Percentiles cannot be re-aggregated (the p95 of a week is NOT the average of
-- seven daily p95 values), so the view stores raw counts plus one percentile
-- per day, and consumers only sum the counts.
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_app_daily_stats AS
SELECT
    e.app_id,
    (e.occurred_at AT TIME ZONE 'UTC')::date                            AS day,
    COUNT(*)                                                            AS requests,
    COUNT(*) FILTER (WHERE e.status_code >= 500)                        AS errors_5xx,
    COUNT(*) FILTER (WHERE e.status_code BETWEEN 400 AND 499)           AS errors_4xx,
    ROUND(AVG(e.latency_ms)::numeric, 1)                                AS avg_latency_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY e.latency_ms)          AS p95_latency_ms
FROM request_events e
GROUP BY e.app_id, day
WITH DATA;

-- A unique index is required for REFRESH MATERIALIZED VIEW CONCURRENTLY,
-- which rebuilds the view without blocking readers.
CREATE UNIQUE INDEX ux_mv_app_daily_stats ON mv_app_daily_stats (app_id, day);

-- -----------------------------------------------------------------------------
-- Live status of every active application during the last hour.
-- LEFT JOIN keeps silent applications in the result (0 requests is a signal!).
-- -----------------------------------------------------------------------------
CREATE VIEW v_app_status_last_hour AS
SELECT
    a.id                                                                AS app_id,
    a.code,
    a.name,
    t.name                                                              AS team,
    a.tier,
    COUNT(e.id)                                                         AS requests,
    COUNT(e.id) FILTER (WHERE e.status_code >= 500)                     AS errors_5xx,
    ROUND(COUNT(e.id) FILTER (WHERE e.status_code >= 500)::numeric
          / NULLIF(COUNT(e.id), 0), 4)                                  AS error_rate,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY e.latency_ms)          AS p95_latency_ms,
    a.slo_availability,
    a.slo_latency_p95_ms
FROM applications a
JOIN teams t ON t.id = a.team_id
LEFT JOIN request_events e
       ON e.app_id = a.id
      AND e.occurred_at >= now() - INTERVAL '1 hour'
WHERE a.active
GROUP BY a.id, t.id;

-- -----------------------------------------------------------------------------
-- Open incidents with their business context
-- -----------------------------------------------------------------------------
CREATE VIEW v_open_incidents AS
SELECT
    i.id,
    a.code                                                              AS app_code,
    a.name                                                              AS app_name,
    t.name                                                              AS team,
    a.tier,
    i.title,
    i.severity,
    i.status,
    i.source,
    i.opened_at,
    ROUND(EXTRACT(EPOCH FROM (now() - i.opened_at)) / 60)               AS minutes_open
FROM incidents i
JOIN applications a ON a.id = i.app_id
JOIN teams t        ON t.id = a.team_id
WHERE i.status <> 'RESOLVED';

COMMIT;
