# API reference

Both services publish an OpenAPI document; this page is the overview.

* Analytics API: Swagger UI at `http://localhost:8000/docs`, JSON at `/openapi.json`
* Ingest service: Swagger UI at `http://localhost:8080/swagger-ui.html`, JSON at `/v3/api-docs`

JSON uses camelCase in both services. Timestamps are ISO 8601 in UTC.

## Analytics API (Flask, port 8000)

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/health` | public | Liveness and database checks (503 without PostgreSQL) |
| POST | `/api/v1/auth/login` | public | `{username, password}` -> `{accessToken, tokenType, expiresIn, role}` |
| GET | `/api/v1/applications` | viewer | Monitored applications with their objectives |
| GET | `/api/v1/applications/{code}` | viewer | One application |
| GET | `/api/v1/applications/{code}/health` | viewer | Time series: `hours` (1 to 720), `bucketMinutes` (5, 15, 30, 60), optional `end` |
| GET | `/api/v1/applications/{code}/anomaly-scans` | viewer | Latest scan reports (MongoDB), `limit` |
| POST | `/api/v1/applications/{code}/anomaly-scans` | admin | Run the detector: `hours`, `bucketMinutes`, `window`, `latencyThreshold`, `errorThreshold`, `openIncidents`, `end` (all optional). 201 with the report |
| GET | `/api/v1/applications/{code}/error-breakdown` | viewer | Errors by app version and region over the last `minutes` (MongoDB aggregation) |
| GET | `/api/v1/incidents` | viewer | Filters `status`, `app`; pagination `page`, `pageSize` |
| GET | `/api/v1/incidents/{id}` | viewer | One incident |
| PATCH | `/api/v1/incidents/{id}` | admin | `{status: ACKNOWLEDGED or RESOLVED}`. 409 for invalid transitions (RESOLVED is final) |
| GET | `/api/v1/reports/slo` | viewer | Availability, error budget and latency compliance, worst first. `days` (1 to 90) |
| POST | `/api/v1/reports/refresh` | admin | Refresh the daily statistics view |

Errors share one shape: `{"code": 404, "status": "Not Found", "message": "..."}`; validation errors
(422) add `"errors": {"json" | "query": {field: [messages]}}`.

## Ingest service (Spring Boot, port 8080)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/events` | `X-API-Key` | 1 to 1 000 events. 202 `{accepted, receivedAt}`; 400 invalid fields; 422 implausible timestamps |
| GET | `/api/v1/applications` | JWT viewer | Registered applications |
| GET | `/api/v1/applications/{code}` | JWT viewer | One application |
| POST | `/api/v1/applications` | JWT admin | Register an application. 201 with `Location` and the API key, shown once |
| PATCH | `/api/v1/applications/{code}` | JWT admin | Change objectives or deactivate (`sloAvailability`, `sloLatencyP95Ms`, `active`) |
| GET | `/actuator/health` | public | Health, with `/liveness` and `/readiness` probes |

Errors use RFC 9457 problem details: `{"type", "title", "status", "detail"}`, plus `errors`
(field -> message) for validation failures and `index` for a rejected event.

### Event payload

```json
{
  "events": [
    {
      "occurredAt": "2026-10-07T15:04:05.123Z",
      "endpoint": "/v1/payments",
      "method": "POST",
      "statusCode": 201,
      "latencyMs": 182,
      "region": "mx-central",
      "metadata": { "appVersion": "4.7.2", "client": "android" }
    }
  ]
}
```

`metadata` is free-form: it is archived in MongoDB, not stored in PostgreSQL.
