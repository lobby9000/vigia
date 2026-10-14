"""Connections to PostgreSQL and MongoDB, created once per application.

Both live in ``app.extensions`` and are reached through ``get_engine()`` and
``get_mongo()`` so views never build connections themselves (and tests can
swap MongoDB for an in-memory fake).
"""

from __future__ import annotations

import logging

from flask import Flask, current_app
from flask_jwt_extended import JWTManager
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError
from sqlalchemy import Engine, create_engine

log = logging.getLogger(__name__)

jwt = JWTManager()

_ENGINE_KEY = "vigia.engine"
_MONGO_KEY = "vigia.mongo"


def init_database(app: Flask) -> None:
    engine = create_engine(
        app.config["DATABASE_URL"],
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,  # transparently replaces connections the server closed
        # Work in UTC inside the API. Converting to local time is a display concern.
        connect_args={"options": "-c timezone=UTC"},
    )
    app.extensions[_ENGINE_KEY] = engine


def init_mongo(app: Flask) -> None:
    client = app.config.get("MONGO_CLIENT") or MongoClient(
        app.config["MONGO_URL"], tz_aware=True, serverSelectionTimeoutMS=2000
    )
    database = client[app.config["MONGO_DB"]]
    app.extensions[_MONGO_KEY] = database
    try:
        # Idempotent: creating an index that already exists is a no-op.
        database.anomaly_reports.create_index([("app_code", ASCENDING), ("created_at", DESCENDING)])
    except PyMongoError as exc:  # MongoDB down: the SQL features still work
        log.warning("Could not create MongoDB indexes (%s). They will be created on the next start.", exc)


def get_engine() -> Engine:
    return current_app.extensions[_ENGINE_KEY]


def get_mongo() -> Database:
    return current_app.extensions[_MONGO_KEY]
