"""Incidents: list with filters and pagination, read one, change its status."""

from flask.views import MethodView
from flask_smorest import Blueprint, abort

from .. import repository as repo
from .. import services
from ..extensions import get_engine
from ..schemas import IncidentListArgs, IncidentPageSchema, IncidentSchema, IncidentUpdateSchema
from ..security import BEARER_AUTH, roles_required

blp = Blueprint("incidents", __name__, url_prefix="/api/v1/incidents", description="Incident management")


@blp.route("")
@roles_required("viewer", "admin")
@blp.doc(security=BEARER_AUTH)
@blp.arguments(IncidentListArgs, location="query")
@blp.response(200, IncidentPageSchema)
def list_incidents(args):
    page, page_size = args["page"], args["page_size"]
    with get_engine().connect() as conn:
        items, total = repo.list_incidents(
            conn,
            status=args.get("status"),
            app_code=args.get("app"),
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@blp.route("/<int:incident_id>")
class IncidentItem(MethodView):
    @roles_required("viewer", "admin")
    @blp.doc(security=BEARER_AUTH)
    @blp.response(200, IncidentSchema)
    def get(self, incident_id):
        with get_engine().connect() as conn:
            incident = repo.get_incident(conn, incident_id)
        if incident is None:
            abort(404, message=f"Incident {incident_id} does not exist.")
        return incident

    @roles_required("admin")
    @blp.doc(security=BEARER_AUTH)
    @blp.arguments(IncidentUpdateSchema)
    @blp.response(200, IncidentSchema)
    @blp.alt_response(409, description="Transition not allowed (for example RESOLVED -> ACKNOWLEDGED)")
    def patch(self, changes, incident_id):
        """Acknowledge or resolve an incident. RESOLVED is final."""
        return services.change_incident_status(get_engine(), incident_id, changes["status"])
