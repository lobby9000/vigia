# Architecture

## Components

| Component | Language | Responsibility | Talks to |
|---|---|---|---|
| `ingest-service` | Java 21, Spring Boot 4.1 | Receives telemetry batches from monitored applications; registers applications and issues their API keys | PostgreSQL (write), MongoDB (write) |
| `analytics-api` | Python 3.12, Flask | Login (issues JWTs), health series, SLO report, anomaly detection, incidents, error breakdown | PostgreSQL (read/write), MongoDB (read/write) |
| `dashboard` | Python 3.12, Django 5.2 | Back-office for people: overview, per-application charts, incident administration | PostgreSQL |
| PostgreSQL 17 | | Source of truth: applications, events, incidents, API users, views | |
| MongoDB 8 | | Raw event payloads (7-day TTL) and anomaly scan reports | |

## Data flow

1. A monitored application sends `POST /api/v1/events` with up to 1 000 events and its `X-API-Key`.
2. `ApiKeyAuthenticationFilter` hashes the key (SHA-256) and finds the owning application with a
   unique-index lookup. Unknown key: 401, nothing else runs.
3. Bean Validation checks every field; the service rejects implausible timestamps (older than
   7 days, or more than 5 minutes in the future) with a 422 that names the offending event.
4. `EventJdbcRepository` writes the batch in one transaction with a JDBC batch
   (`reWriteBatchedInserts=true` turns it into multi-row INSERTs).
5. After the commit, `RawEventArchive` stores the original payloads in MongoDB. If MongoDB fails,
   the request still succeeds: PostgreSQL is the source of truth (see trade-offs).
6. A cron job (`scripts/refresh_views.sh`) refreshes `mv_app_daily_stats` every 15 minutes.
7. People query the analytics API or the dashboard. An admin runs anomaly scans, which create
   incidents (PostgreSQL) and reports (MongoDB).

## Authentication and authorization

| Client | Mechanism | Where it is enforced |
|---|---|---|
| Monitored application | Per-application API key in `X-API-Key`; only its SHA-256 is stored | `ingest-service`, first security filter chain |
| API user (person or tool) | JWT (HS256) from `POST /api/v1/auth/login`, claim `role` = `viewer` or `admin` | `analytics-api` decorator `roles_required`; `ingest-service` as an OAuth2 resource server |
| Dashboard user | Django session and the Django permission system | `dashboard` |

* Viewers read; admins also write (scans, incident changes, application registration).
* Authorization is deny-by-default in the Java service: an endpoint without an explicit rule
  answers 403.
* Passwords use scrypt (Werkzeug) or PBKDF2 (Django). API keys use a fast hash on purpose: they are
  256 random bits, so there is nothing to brute force, and a deterministic hash allows an indexed
  lookup.
* Login answers take the same time for unknown users and wrong passwords (a dummy hash is checked),
  so response timing does not reveal valid usernames.

## Polyglot persistence

| Data | Store | Why |
|---|---|---|
| Applications, teams, incidents, users | PostgreSQL | Relations, constraints, transactions |
| Request events (typed fields) | PostgreSQL | SQL aggregations, percentiles, indexes tuned for time ranges |
| Raw payloads with free-form metadata | MongoDB | No fixed schema; TTL index expires them after 7 days |
| Anomaly scan reports | MongoDB | Nested, variable-size documents (episodes, scored buckets) |

**Ownership rule:** each collection or table has exactly one writer service. `raw_events` is written
by Java (camelCase fields, the Spring Data default); `anomaly_reports` by Python (snake_case).

## Anomaly detection

The detector (`analytics-api/vigia_analytics/anomaly.py`) works on a series of buckets
(15 minutes by default) with request count, 5xx count and p95 latency.

* **Latency:** robust z-score of each bucket's p95 against the previous 16 buckets (anomalous above 4.5):
  `z = 0.6745 (x - median) / MAD`. The median and the MAD (median absolute deviation) barely move
  when an outlier enters the window, unlike the mean and the standard deviation.
* **Errors:** with `n` requests and a baseline error probability `p0`, the number of errors follows
  a Binomial(n, p0). The detector computes the exact tail probability `P(X >= k)` with SciPy and
  converts it to an equivalent z-score. The textbook normal approximation is badly calibrated when
  `n p0` is close to 1: it calls five errors where one was expected a "4 sigma" event, while the
  exact probability is about 0.4 %. `p0` uses Laplace smoothing (`(errors + 1) / (requests + 2)`) so
  it is never exactly zero.
* **Practical significance:** latency must also be 30 % above its baseline and is only judged in
  buckets with at least 100 requests (with fewer, the p95 is one or two slow calls); errors need at
  least 5 occurrences and twice the baseline rate.
* **Persistence:** consecutive anomalous buckets (one normal bucket of tolerance) become an
  episode; a single-bucket episode survives only with a score of 10 or more.
* **Severity** depends on business impact, not on statistics: peak error rate, p95 relative to the
  objective, and the application tier.

Baselines only use buckets *before* the one being scored (`shift(1)`): otherwise an incident would
be part of its own baseline and hide itself.

### Calibration

The defaults were chosen by simulation, not by taste. `scripts/calibrate_detector.py` (`make
calibrate`) replays `make seed`, `make simulate` and `make scan` in memory many times, with different
seeds and end times, and counts misses and false alarms. Over 40 runs (2 400 application-days,
120 injected incidents, 40 failing canary releases):

| Minimum requests for latency | Latency threshold | Missed | False alarms |
|---|---|---|---|
| 30 | 3.5 (textbook value) | 0 | 18 |
| 100 | 3.5 | 0 | 4 |
| 100 | 4.5 (default) | 0 | 1 |

Most false alarms came from night buckets of the two smallest applications. Fixing that cause (a
p95 needs enough requests above it) did most of the work; the higher threshold is a safety margin.

## Trade-offs and what production would add

| Decision | Benefit | Cost | Production answer |
|---|---|---|---|
| Write PostgreSQL, then MongoDB (best effort) | Ingestion never fails because of MongoDB | A MongoDB outage loses diagnostic metadata for that batch | Transactional outbox: write an outbox row in the same transaction, relay it to MongoDB |
| Synchronous ingestion | Simple, read-your-writes | Peaks hit the database directly | Kafka or SQS behind the endpoint (the 202 status already allows it) |
| One `request_events` table | Simple queries | Very large tables slow down maintenance | Monthly partitions or TimescaleDB, retention by dropping partitions |
| SQL init scripts | No migration tool to learn | Changes after the first start need manual SQL | Flyway (Java side) or Alembic |
| HS256 shared secret | One secret, two languages | Every validator can also sign | RS256 or an identity provider (Keycloak, Cognito) with a JWKS endpoint |
| Rolling-window baseline | Robust and explainable | Lags behind slow drifts (memory leaks) | Seasonal baseline (same time last week), change-point detection |
