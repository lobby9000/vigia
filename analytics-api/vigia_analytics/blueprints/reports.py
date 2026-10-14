"""SLO compliance report and refresh of the daily statistics."""

import time

from flask_smorest import Blueprint

from .. import repository as repo
from ..extensions import get_engine
from ..schemas import RefreshResultSchema, SloArgs, SloReportSchema
from ..security import BEARER_AUTH, roles_required
from ..services import utcnow

blp = Blueprint("reports", __name__, url_prefix="/api/v1/reports", description="Service level reports")


@blp.route("/slo")
@roles_required("viewer", "admin")
@blp.doc(security=BEARER_AUTH)
@blp.arguments(SloArgs, location="query")
@blp.response(200, SloReportSchema)
def slo_report(args):
    """Availability and latency objectives per application, worst first."""
    with get_engine().connect() as conn:
        rows = repo.slo_report(conn, args["days"])
    return {"days": args["days"], "generated_at": utcnow(), "applications": rows}


@blp.route("/refresh", methods=["POST"])
@roles_required("admin")
@blp.doc(security=BEARER_AUTH)
@blp.response(200, RefreshResultSchema)
def refresh_statistics():
    """Rebuild mv_app_daily_stats (normally done by cron, see scripts/refresh_views.sh)."""
    started = time.perf_counter()
    with get_engine().begin() as conn:
        repo.refresh_daily_stats(conn)
    return {"refreshed": "mv_app_daily_stats", "seconds": round(time.perf_counter() - started, 3)}
