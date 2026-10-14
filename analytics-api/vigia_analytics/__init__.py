"""Vigia Analytics API: application factory.

Run locally:   flask --app vigia_analytics run --debug --port 8000
Run in Docker: gunicorn --bind 0.0.0.0:8000 "vigia_analytics:create_app()"
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify
from flask_smorest import Api
from pymongo.errors import PyMongoError
from sqlalchemy.exc import OperationalError

from .blueprints import ALL_BLUEPRINTS
from .cli import register_cli
from .config import MIN_SECRET_LENGTH, Config
from .extensions import init_database, init_mongo, jwt
from .security import register_jwt_error_handlers
from .services import ConflictError, NotFoundError

log = logging.getLogger(__name__)


def create_app(overrides: dict | None = None) -> Flask:
    """Build a configured Flask app. ``overrides`` is how tests change settings."""
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    _check_config(app)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    init_database(app)
    init_mongo(app)

    jwt.init_app(app)
    register_jwt_error_handlers(jwt)

    api = Api(app)
    api.spec.components.security_scheme("bearerAuth", {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"})
    for blueprint in ALL_BLUEPRINTS:
        api.register_blueprint(blueprint)

    _register_error_handlers(app)
    register_cli(app)
    return app


def _check_config(app: Flask) -> None:
    secret = app.config.get("JWT_SECRET_KEY") or ""
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET_KEY must have at least {MIN_SECRET_LENGTH} characters. Generate one with: openssl rand -hex 32"
        )


def _register_error_handlers(app: Flask) -> None:
    """Domain exceptions -> HTTP answers with flask-smorest's JSON error shape."""

    def error(status: int, reason: str, message: str):
        return jsonify(code=status, status=reason, message=message), status

    @app.errorhandler(NotFoundError)
    def not_found(exc):
        return error(404, "Not Found", str(exc))

    @app.errorhandler(ConflictError)
    def conflict(exc):
        return error(409, "Conflict", str(exc))

    @app.errorhandler(PyMongoError)
    def mongo_unavailable(exc):
        log.error("MongoDB error: %s", exc)
        return error(503, "Service Unavailable", "MongoDB is not reachable right now.")

    @app.errorhandler(OperationalError)
    def database_unavailable(exc):
        log.error("PostgreSQL error: %s", exc)
        return error(503, "Service Unavailable", "PostgreSQL is not reachable right now.")
