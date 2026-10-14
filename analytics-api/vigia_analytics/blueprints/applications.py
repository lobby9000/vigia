"""Monitored applications: list, health series, anomaly scans and error breakdown."""

from flask.views import MethodView
from flask_jwt_extended import get_jwt_identity
from flask_smorest import Blueprint, abort

from .. import repository as repo
from .. import services
from ..extensions import get_engine, get_mongo
from ..schemas import (
    AnomalyScanArgs,
    AnomalyScanSchema,
    ApplicationSchema,
    BreakdownArgs,
    BreakdownSchema,
    HealthSeriesSchema,
    LimitArgs,
    TimeWindowArgs,
)
from ..security import BEARER_AUTH, roles_required

blp = Blueprint(
    "applications",
    __name__,
    url_prefix="/api/v1/applications",
    description="Monitored applications: health series, anomaly scans and error breakdowns",
)


@blp.route("")
@roles_required("viewer", "admin")
@blp.doc(security=BEARER_AUTH)
@blp.response(200, ApplicationSchema(many=True))
def list_applications():
    with get_engine().connect() as conn:
        return repo.list_applications(conn)


@blp.route("/<string:code>")
@roles_required("viewer", "admin")
@blp.doc(security=BEARER_AUTH)
@blp.response(200, ApplicationSchema)
def get_application(code):
    with get_engine().connect() as conn:
        app = repo.get_application(conn, code)
    if app is None:
        abort(404, message=f"Application '{code}' does not exist.")
    return app


@blp.route("/<string:code>/health")
@roles_required("viewer", "admin")
@blp.doc(security=BEARER_AUTH)
@blp.arguments(TimeWindowArgs, location="query")
@blp.response(200, HealthSeriesSchema)
def application_health(args, code):
    """Requests, 5xx rate and latency percentiles per time bucket."""
    return services.health_series(get_engine(), code, args["hours"], args["bucket_minutes"], args["end"])


@blp.route("/<string:code>/anomaly-scans")
class AnomalyScans(MethodView):
    @roles_required("viewer", "admin")
    @blp.doc(security=BEARER_AUTH)
    @blp.arguments(LimitArgs, location="query")
    @blp.response(200, AnomalyScanSchema(many=True))
    def get(self, args, code):
        """Most recent scan reports for this application (stored in MongoDB)."""
        return services.list_scan_reports(get_engine(), get_mongo(), code, args["limit"])

    @roles_required("admin")
    @blp.doc(security=BEARER_AUTH)
    @blp.arguments(AnomalyScanArgs, required=False)
    @blp.response(201, AnomalyScanSchema)
    def post(self, args, code):
        """Run the anomaly detector over a time window and open incidents for what it finds."""
        return services.run_anomaly_scan(get_engine(), get_mongo(), code, args, requested_by=get_jwt_identity())


@blp.route("/<string:code>/error-breakdown")
@roles_required("viewer", "admin")
@blp.doc(security=BEARER_AUTH)
@blp.arguments(BreakdownArgs, location="query")
@blp.response(200, BreakdownSchema)
def error_breakdown(args, code):
    """Error rate by application version and region over the last N minutes."""
    return services.error_breakdown(get_engine(), get_mongo(), code, args["minutes"])
