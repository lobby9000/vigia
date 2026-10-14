"""Server-rendered pages (Django's MVT: Model, View, Template).

Views prepare display-ready numbers (percentages, bar widths) so templates
stay free of arithmetic.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from . import queries
from .models import Application, Incident

RANGES = ((6, "6 h"), (24, "24 h"), (72, "72 h"), (168, "7 d"))


def _pct(value):
    return None if value is None else 100 * float(value)


@login_required
def overview(request):
    """One row per application: last hour, last 7 days and open incidents."""
    slo = queries.slo_last_days(7)
    open_counts = dict(
        Incident.objects.exclude(status=Incident.Status.RESOLVED)
        .values_list("application__code")
        .annotate(total=Count("id"))
    )
    rows = []
    for status in queries.status_last_hour():
        week = slo.get(status["code"], {})
        open_incidents = open_counts.get(status["code"], 0)
        budget_pct = _pct(week.get("budget_consumed"))
        rows.append(
            {
                **status,
                "health": queries.health_of(status, open_incidents),
                "open_incidents": open_incidents,
                "error_pct": _pct(status["error_rate"]),
                "objective_pct": _pct(status["slo_availability"]),
                "availability_pct": _pct(week.get("availability")),
                "budget_pct": budget_pct,
                "budget_bar": None if budget_pct is None else min(budget_pct, 100),
            }
        )
    # select_related: one JOIN instead of one extra query per incident (the N+1 problem)
    incidents = Incident.objects.select_related("application").exclude(status=Incident.Status.RESOLVED)[:10]
    return render(
        request,
        "monitoring/overview.html",
        {"rows": rows, "incidents": incidents, "generated_at": timezone.now()},
    )


@login_required
def application_detail(request, code):
    app = get_object_or_404(Application.objects.select_related("team"), code=code)
    try:
        hours = min(max(int(request.GET.get("hours", 24)), 1), 168)
    except ValueError:
        hours = 24
    bucket_minutes = 15 if hours <= 48 else 60
    series = queries.bucket_series(app.id, hours, bucket_minutes)
    chart = {
        "labels": [timezone.localtime(row["bucket"]).strftime("%d %b %H:%M") for row in series],
        "p95": [round(row["p95_latency_ms"], 1) for row in series],
        "errorRatePct": [round(100 * row["error_rate"], 3) for row in series],
        "sloLatency": app.slo_latency_p95_ms,
    }
    return render(
        request,
        "monitoring/application_detail.html",
        {
            "app": app,
            "chart": chart,
            "hours": hours,
            "ranges": RANGES,
            "bucket_minutes": bucket_minutes,
            "incidents": app.incidents.order_by("-opened_at")[:20],
        },
    )
