"""GET /health: liveness and dependency check for load balancers and Docker."""

from flask_smorest import Blueprint
from pymongo.errors import PyMongoError
from sqlalchemy.exc import SQLAlchemyError

from .. import repository as repo
from ..extensions import get_engine, get_mongo
from ..schemas import ServiceHealthSchema

blp = Blueprint("health", __name__, description="Service health")


@blp.route("/health")
@blp.response(200, ServiceHealthSchema)
@blp.alt_response(503, schema=ServiceHealthSchema, description="PostgreSQL is unreachable")
def health():
    """PostgreSQL is required (503 without it). MongoDB down only degrades the service."""
    result = {"status": "ok", "database": "up", "mongo": "up"}
    try:
        with get_engine().connect() as conn:
            repo.ping(conn)
    except SQLAlchemyError:
        result.update(status="down", database="down")
    try:
        get_mongo().command("ping")
    except PyMongoError:
        result["mongo"] = "down"
        if result["status"] == "ok":
            result["status"] = "degraded"
    return result, (503 if result["database"] == "down" else 200)
