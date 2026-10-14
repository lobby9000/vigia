"""Dashboard tests. Run with: python manage.py test

They use a throwaway PostgreSQL database (test_<name>) with the real shared
schema loaded by monitoring.test_runner.SharedSchemaTestRunner.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Application, Incident
from .queries import health_of


def insert_recent_traffic(code: str, requests: int, every_nth_fails: int, latency_ms: int) -> None:
    """Spread requests over the last hour; every Nth one is a 500."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO request_events (app_id, occurred_at, endpoint, http_method, status_code, latency_ms, region)
            SELECT a.id,
                   now() - (g * 3500.0 / %s) * INTERVAL '1 second',
                   '/v1/test', 'GET',
                   CASE WHEN g %% %s = 0 THEN 500 ELSE 200 END,
                   %s,
                   'mx-central'
            FROM applications a, generate_series(1, %s) AS g
            WHERE a.code = %s
            """,
            [requests, every_nth_fails, latency_ms, requests, code],
        )
        cursor.execute("REFRESH MATERIALIZED VIEW mv_app_daily_stats")


class HealthRulesTests(SimpleTestCase):
    """Pure function: no database needed."""

    base = {"requests": 1000, "slo_availability": "0.999", "slo_latency_p95_ms": 500}

    def test_idle_when_there_is_no_traffic(self):
        self.assertEqual(
            health_of(
                {
                    **self.base,
                    "requests": 0,
                    "error_rate": None,
                    "p95_latency_ms": None,
                },
                0,
            ),
            "idle",
        )

    def test_ok_within_objectives(self):
        self.assertEqual(
            health_of({**self.base, "error_rate": 0.0005, "p95_latency_ms": 300}, 0),
            "ok",
        )

    def test_degraded_when_an_objective_is_missed_or_an_incident_is_open(self):
        self.assertEqual(
            health_of({**self.base, "error_rate": 0.002, "p95_latency_ms": 300}, 0),
            "degraded",
        )
        self.assertEqual(
            health_of({**self.base, "error_rate": 0.0, "p95_latency_ms": 300}, 1),
            "degraded",
        )

    def test_critical_far_beyond_the_objectives(self):
        self.assertEqual(
            health_of({**self.base, "error_rate": 0.01, "p95_latency_ms": 300}, 0),
            "critical",
        )
        self.assertEqual(
            health_of({**self.base, "error_rate": 0.0, "p95_latency_ms": 1200}, 0),
            "critical",
        )


class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.viewer = user_model.objects.create_user("ops", password="vigia-test-pass-1")
        cls.admin = user_model.objects.create_superuser("boss", password="vigia-test-pass-2")
        insert_recent_traffic("payments-api", requests=200, every_nth_fails=20, latency_ms=150)  # 5 % errors
        insert_recent_traffic("catalog-api", requests=200, every_nth_fails=10_000, latency_ms=120)  # healthy

    def test_pages_require_login(self):
        response = self.client.get(reverse("monitoring:overview"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_overview_classifies_every_application(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("monitoring:overview"))

        self.assertEqual(response.status_code, 200)
        rows = {row["code"]: row for row in response.context["rows"]}
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows["payments-api"]["health"], "critical")  # 5 % vs 0.05 % allowed
        self.assertEqual(rows["catalog-api"]["health"], "ok")
        self.assertEqual(rows["loyalty-api"]["health"], "idle")
        self.assertAlmostEqual(rows["payments-api"]["error_pct"], 5.0)

    def test_application_page_embeds_the_chart_data(self):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("monitoring:application_detail", args=["payments-api"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="chart-data"')
        self.assertTrue(response.context["chart"]["p95"])
        self.assertEqual(response.context["chart"]["sloLatency"], 600)

    def test_unknown_application_is_404(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("monitoring:application_detail", args=["does-not-exist"]))
        self.assertEqual(response.status_code, 404)

    def test_admin_action_resolves_incidents_in_one_update(self):
        incident = Incident.objects.create(
            application=Application.objects.get(code="payments-api"),
            title="Errors on /v1/payments",
            severity="SEV2",
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:monitoring_incident_changelist"),
            {"action": "resolve", "_selected_action": [incident.pk]},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        incident.refresh_from_db()
        self.assertEqual(incident.status, Incident.Status.RESOLVED)
        self.assertIsNotNone(incident.resolved_at)
        self.assertIsNotNone(incident.acknowledged_at)


class IncidentModelTests(TestCase):
    def setUp(self):
        self.incident = Incident.objects.create(
            application=Application.objects.get(code="login-service"),
            title="Slow logins",
            severity="SEV3",
        )

    def test_saving_keeps_timestamps_consistent_with_the_status(self):
        self.incident.status = Incident.Status.RESOLVED
        self.incident.save()

        self.incident.refresh_from_db()
        self.assertIsNotNone(self.incident.acknowledged_at)
        self.assertIsNotNone(self.incident.resolved_at)

    def test_resolved_incidents_cannot_be_reopened(self):
        self.incident.status = Incident.Status.RESOLVED
        self.incident.save()

        self.incident.status = Incident.Status.OPEN
        with self.assertRaises(ValidationError):
            self.incident.full_clean()
