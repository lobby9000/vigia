# How the events table would look in Cassandra

Vigía stores events in PostgreSQL, which is the right tool up to a few billion rows on one
well-tuned server. If ingestion grew to hundreds of thousands of events per second across regions,
a wide-column store such as Apache Cassandra (or Amazon Keyspaces, Azure Cosmos DB for Apache
Cassandra) would be a candidate. This note shows how the design would change.

## Model the queries, not the entities

Cassandra has no joins and no ad hoc `WHERE`: every query must hit a known partition. So the design
starts from the questions:

1. Events of application X between T1 and T2, newest first.
2. Server errors of application X in the last hour.

```sql
-- Q1: one partition per application and day; rows sorted by time inside it
CREATE TABLE vigia.events_by_app_day (
    app_code     text,
    day          date,
    occurred_at  timestamp,
    event_id     timeuuid,
    endpoint     text,
    method       text,
    status_code  smallint,
    latency_ms   int,
    region       text,
    metadata     map<text, text>,
    PRIMARY KEY ((app_code, day), occurred_at, event_id)
) WITH CLUSTERING ORDER BY (occurred_at DESC, event_id DESC)
  AND default_time_to_live = 604800;   -- 7 days, like the MongoDB TTL

-- Q2: errors duplicated into their own table (denormalisation is normal here)
CREATE TABLE vigia.errors_by_app_hour (
    app_code     text,
    hour         timestamp,
    occurred_at  timestamp,
    event_id     timeuuid,
    endpoint     text,
    status_code  smallint,
    PRIMARY KEY ((app_code, hour), occurred_at, event_id)
) WITH CLUSTERING ORDER BY (occurred_at DESC, event_id DESC);
```

```sql
SELECT * FROM vigia.events_by_app_day
WHERE app_code = 'payments-api' AND day = '2026-10-07'
  AND occurred_at >= '2026-10-07 14:00:00' AND occurred_at < '2026-10-07 15:00:00';
```

## Key ideas

* **Partition key** `(app_code, day)` decides which nodes store the rows. Including `day` keeps
  partitions bounded (a busy application would otherwise grow one huge partition forever).
* **Clustering columns** `occurred_at, event_id` sort rows inside the partition, so time ranges are
  sequential reads. `event_id` (a timeuuid) makes the key unique when two events share a timestamp.
* **One table per query.** Writes are cheap in Cassandra; reading across partitions is not.
* **No aggregations at read time.** Percentiles and SLOs would be computed by a stream processor
  (Spark, Flink) and written to summary tables, the same role `mv_app_daily_stats` plays in PostgreSQL.
* **Tunable consistency:** writes at `LOCAL_QUORUM` survive a node failure without blocking.

## PostgreSQL vs MongoDB vs Cassandra in this project

| Need | PostgreSQL | MongoDB | Cassandra |
|---|---|---|---|
| Joins, constraints, transactions | Yes | Limited | No |
| Flexible documents | JSONB | Native | Maps and UDTs |
| Ad hoc analytical queries | Excellent | Aggregation pipeline | Poor (query-first design) |
| Write throughput across regions | One primary | Sharding | Designed for it |
| Choice in Vigía | Source of truth | Raw payloads, reports | Only at a much larger scale |
