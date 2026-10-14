"""End-to-end tests of the HTTP API against PostgreSQL (and mongomock)."""

from datetime import timedelta

from sqlalchemy import text

from vigia_analytics.services import utcnow

from .conftest import ERROR_INCIDENT, LATENCY_INCIDENT


def test_health_reports_both_databases(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["database"] == "up"


def test_list_applications(client, viewer_headers):
    response = client.get("/api/v1/applications", headers=viewer_headers)

    assert response.status_code == 200
    apps = {a["code"]: a for a in response.get_json()}
    assert len(apps) == 6
    assert apps["payments-api"] == {
        "code": "payments-api",
        "name": "Payments API",
        "team": "Payments",
        "tier": 1,
        "sloAvailability": 0.9995,
        "sloLatencyP95Ms": 600,
        "active": True,
    }


def test_unknown_application_is_404(client, viewer_headers):
    assert client.get("/api/v1/applications/nope", headers=viewer_headers).status_code == 404
    assert client.get("/api/v1/applications/nope/health", headers=viewer_headers).status_code == 404


def test_health_series_buckets_the_traffic(client, viewer_headers):
    response = client.get("/api/v1/applications/payments-api/health?hours=24&bucketMinutes=60", headers=viewer_headers)

    assert response.status_code == 200
    body = response.get_json()
    assert body["bucketMinutes"] == 60
    assert 24 <= len(body["points"]) <= 25  # a partial bucket at each edge is possible
    point = body["points"][len(body["points"]) // 2]
    assert set(point) == {
        "bucket",
        "requests",
        "errors5xx",
        "errorRate",
        "avgLatencyMs",
        "p50LatencyMs",
        "p95LatencyMs",
    }
    assert 520 <= point["requests"] <= 680  # ~10 requests per minute, 600 per hour


def test_query_parameters_are_validated(client, viewer_headers):
    response = client.get("/api/v1/applications/payments-api/health?bucketMinutes=7", headers=viewer_headers)

    assert response.status_code == 422
    assert "bucketMinutes" in response.get_json()["errors"]["query"]


def test_anomaly_scan_finds_the_incidents_and_never_duplicates_them(client, admin_headers, mongo):
    first = client.post("/api/v1/applications/payments-api/anomaly-scans", json={"hours": 48}, headers=admin_headers)

    assert first.status_code == 201
    scan = first.get_json()
    assert len(scan["episodes"]) == 1
    episode = scan["episodes"][0]
    assert episode["metrics"] == ["latency_p95"]
    assert episode["severity"] == "SEV1"  # tier 1 app, p95 far above its 600 ms objective
    assert _iso_hour(episode["start"]) == LATENCY_INCIDENT[0].replace(minute=0).isoformat()[:13]
    assert scan["incidentsOpened"] == [episode["incidentId"]]
    stored = mongo.anomaly_reports.find_one({"app_code": "payments-api"})
    assert stored["episodes"][0]["incident_id"] == episode["incidentId"]

    second = client.post("/api/v1/applications/payments-api/anomaly-scans", json={"hours": 48}, headers=admin_headers)
    assert second.status_code == 201
    assert len(second.get_json()["episodes"]) == 1
    assert second.get_json()["incidentsOpened"] == []  # overlapping incident already exists


def test_error_bursts_are_detected_too(client, admin_headers):
    response = client.post(
        "/api/v1/applications/login-service/anomaly-scans",
        json={"hours": 24, "openIncidents": False},
        headers=admin_headers,
    )

    episodes = response.get_json()["episodes"]
    assert [e["metrics"] for e in episodes] == [["error_rate"]]
    assert episodes[0]["peakErrorRate"] > 0.15
    assert episodes[0]["incidentId"] is None  # openIncidents=false
    assert _iso_hour(episodes[0]["start"]) <= ERROR_INCIDENT[0].isoformat()[:13]


def test_scan_reports_are_listed_newest_first(client, admin_headers, viewer_headers):
    client.post("/api/v1/applications/loyalty-api/anomaly-scans", json={"hours": 1}, headers=admin_headers)
    response = client.get("/api/v1/applications/loyalty-api/anomaly-scans?limit=5", headers=viewer_headers)

    assert response.status_code == 200
    reports = response.get_json()
    assert reports and reports[0]["appCode"] == "loyalty-api"
    assert reports[0]["bucketsAnalyzed"] == 0  # no traffic for this app in the test data


def test_incident_life_cycle(client, admin_headers, viewer_headers, engine):
    with engine.begin() as conn:
        incident_id = conn.execute(
            text("""
                INSERT INTO incidents (app_id, title, severity)
                SELECT id, 'Checkout slow for some users', 'SEV3' FROM applications WHERE code = 'checkout-web'
                RETURNING id
            """)
        ).scalar()
    url = f"/api/v1/incidents/{incident_id}"

    assert client.patch(url, json={"status": "ACKNOWLEDGED"}, headers=viewer_headers).status_code == 403

    acknowledged = client.patch(url, json={"status": "ACKNOWLEDGED"}, headers=admin_headers)
    assert acknowledged.status_code == 200
    assert acknowledged.get_json()["acknowledgedAt"] is not None

    resolved = client.patch(url, json={"status": "RESOLVED"}, headers=admin_headers).get_json()
    assert resolved["status"] == "RESOLVED" and resolved["resolvedAt"] is not None

    reopened = client.patch(url, json={"status": "ACKNOWLEDGED"}, headers=admin_headers)
    assert reopened.status_code == 409

    assert (
        client.patch("/api/v1/incidents/999999", json={"status": "RESOLVED"}, headers=admin_headers).status_code == 404
    )
    assert client.patch(url, json={"status": "OPEN"}, headers=admin_headers).status_code == 422


def test_incidents_are_filtered_and_paginated(client, viewer_headers, engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO incidents (app_id, title, severity, opened_at)
                SELECT a.id, 'Notification delay #' || g, 'SEV3', now() - g * INTERVAL '1 minute'
                FROM applications a, generate_series(1, 5) AS g
                WHERE a.code = 'notifications-api'
            """)
        )

    page = client.get(
        "/api/v1/incidents?app=notifications-api&status=OPEN&page=2&pageSize=2", headers=viewer_headers
    ).get_json()

    assert page["total"] == 5 and page["page"] == 2 and page["pageSize"] == 2
    assert [i["title"] for i in page["items"]] == ["Notification delay #3", "Notification delay #4"]


def test_slo_report_ranks_the_worst_application_first(client, admin_headers, viewer_headers):
    assert client.post("/api/v1/reports/refresh", headers=admin_headers).status_code == 200

    report = client.get("/api/v1/reports/slo?days=7", headers=viewer_headers).get_json()

    rows = {row["appCode"]: row for row in report["applications"]}
    assert set(rows) == {"payments-api", "login-service"}  # the only apps with traffic
    login = rows["login-service"]
    assert login["worstRank"] == 1
    assert login["status"] == "BREACHED"  # the error burst blew the 99.95 % objective
    assert login["errorBudgetConsumed"] > 1
    assert 0 < login["availability"] < login["sloAvailability"]


def test_error_breakdown_points_at_the_failing_version(client, viewer_headers, mongo):
    now = utcnow()
    events = []
    for i in range(200):
        version = "3.2.0" if i % 4 == 0 else "3.1.4"  # canary takes 25 % of the traffic
        failing = version == "3.2.0" and i % 8 == 0
        events.append(
            {
                "appCode": "checkout-web",
                "occurredAt": now - timedelta(minutes=i % 30),
                "statusCode": 503 if failing else 200,
                "latencyMs": 900 if failing else 200,
                "region": "mx-central",
                "metadata": {"appVersion": version, "client": "web"},
            }
        )
    mongo.raw_events.insert_many(events)

    body = client.get("/api/v1/applications/checkout-web/error-breakdown?minutes=60", headers=viewer_headers).get_json()

    assert body["totalRequests"] == 200
    worst = body["rows"][0]
    assert worst["appVersion"] == "3.2.0"
    assert worst["errorRate"] == 0.5 and worst["errors5xx"] == 25


def test_openapi_document_describes_auth_and_parameters(client):
    spec = client.get("/openapi.json").get_json()

    assert spec["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
    health = spec["paths"]["/api/v1/applications/{code}/health"]["get"]
    assert {"bucketMinutes", "hours", "end"} <= {p["name"] for p in health["parameters"]}
    assert health["security"] == [{"bearerAuth": []}]


def _iso_hour(value: str) -> str:
    """'2026-10-07T14:15:00+00:00' -> '2026-10-07T14' (compare at hour precision)."""
    return value[:13]
