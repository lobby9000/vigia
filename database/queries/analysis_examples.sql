-- =============================================================================
-- Vigia | SQL you can run by hand (psql: \i database/queries/analysis_examples.sql)
-- Each block answers one operational question and shows one SQL technique.
-- =============================================================================

-- 1) JOIN + GROUP BY + FILTER: requests and 5xx per team, last 24 hours
SELECT t.name                                        AS team,
       COUNT(*)                                      AS requests,
       COUNT(*) FILTER (WHERE e.status_code >= 500)  AS errors_5xx,
       ROUND(100.0 * COUNT(*) FILTER (WHERE e.status_code >= 500) / COUNT(*), 3) AS error_pct
FROM request_events e
JOIN applications a ON a.id = e.app_id
JOIN teams t        ON t.id = a.team_id
WHERE e.occurred_at >= now() - INTERVAL '24 hours'
GROUP BY t.name
ORDER BY error_pct DESC;

-- 2) Ordered-set aggregates: latency percentiles per endpoint (one app, 24 h)
SELECT e.endpoint,
       COUNT(*)                                                     AS requests,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY e.latency_ms)   AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY e.latency_ms)   AS p95_ms,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY e.latency_ms)   AS p99_ms
FROM request_events e
JOIN applications a ON a.id = e.app_id
WHERE a.code = 'payments-api'
  AND e.occurred_at >= now() - INTERVAL '24 hours'
GROUP BY e.endpoint
ORDER BY p95_ms DESC;

-- 3) CTE + window functions: hourly error rate, its 6-hour moving average and
--    the change versus the previous hour (LAG).
WITH hourly AS (
    SELECT date_trunc('hour', e.occurred_at)                                   AS hour,
           COUNT(*) FILTER (WHERE e.status_code >= 500)::numeric / COUNT(*)     AS error_rate
    FROM request_events e
    JOIN applications a ON a.id = e.app_id
    WHERE a.code = 'login-service'
      AND e.occurred_at >= now() - INTERVAL '7 days'
    GROUP BY 1
)
SELECT hour,
       ROUND(100 * error_rate, 3)                                                            AS error_pct,
       ROUND(100 * AVG(error_rate) OVER (ORDER BY hour ROWS BETWEEN 5 PRECEDING AND CURRENT ROW), 3)
                                                                                             AS moving_avg_6h_pct,
       ROUND(100 * (error_rate - LAG(error_rate) OVER (ORDER BY hour)), 3)                   AS change_vs_prev_pct
FROM hourly
ORDER BY error_rate DESC
LIMIT 10;

-- 4) RANK() per partition: the slowest endpoint of every application (p95, 24 h)
WITH per_endpoint AS (
    SELECT a.code,
           e.endpoint,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY e.latency_ms) AS p95_ms
    FROM request_events e
    JOIN applications a ON a.id = e.app_id
    WHERE e.occurred_at >= now() - INTERVAL '24 hours'
    GROUP BY a.code, e.endpoint
)
SELECT code, endpoint, ROUND(p95_ms::numeric) AS p95_ms
FROM (
    SELECT per_endpoint.*, RANK() OVER (PARTITION BY code ORDER BY p95_ms DESC) AS position
    FROM per_endpoint
) ranked
WHERE position = 1
ORDER BY p95_ms DESC;

-- 5) Indexes in action. Compare the plans (run each EXPLAIN separately):
--    a) uses idx_events_app_time and, after VACUUM, an Index Only Scan
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), AVG(latency_ms)
FROM request_events
WHERE app_id = 1 AND occurred_at >= now() - INTERVAL '6 hours';

--    b) the partial index idx_events_app_errors only stores 5xx rows
EXPLAIN (ANALYZE, BUFFERS)
SELECT occurred_at, status_code
FROM request_events
WHERE app_id = 1 AND status_code >= 500 AND occurred_at >= now() - INTERVAL '7 days';

--    c) every app, last hour: the tiny BRIN index narrows the scan to recent blocks
EXPLAIN (ANALYZE, BUFFERS)
SELECT app_id, COUNT(*)
FROM request_events
WHERE occurred_at >= now() - INTERVAL '1 hour'
GROUP BY app_id;

-- 6) Index sizes: BRIN is orders of magnitude smaller than a B-tree
SELECT indexrelname AS index, pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE relname = 'request_events'
ORDER BY pg_relation_size(indexrelid) DESC;
