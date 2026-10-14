"""Configuration read from environment variables (12-factor style).

Nothing secret has a usable default: the app refuses to start without a
proper JWT secret, so a forgotten variable fails loudly instead of silently
running with a weak key.
"""

from __future__ import annotations

import os
from datetime import timedelta

MIN_SECRET_LENGTH = 32  # HS256 needs a key of at least 256 bits (Java enforces it too)


class Config:
    # Databases ---------------------------------------------------------------
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://vigia:vigia@localhost:5432/vigia")
    MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    MONGO_DB = os.environ.get("MONGO_DB", "vigia")
    MONGO_CLIENT = None  # tests inject a mongomock client here

    # JWT (flask-jwt-extended) ------------------------------------------------
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.environ.get("JWT_ACCESS_TOKEN_MINUTES", "60")))
    JWT_TOKEN_LOCATION = ["headers"]
    # The Java ingest service validates this issuer before trusting a token.
    JWT_ENCODE_ISSUER = "vigia-analytics"
    JWT_DECODE_ISSUER = "vigia-analytics"

    # OpenAPI and Swagger UI (flask-smorest) ----------------------------------
    API_TITLE = "Vigia Analytics API"
    API_VERSION = "1.0.0"
    OPENAPI_VERSION = "3.0.3"
    OPENAPI_URL_PREFIX = "/"
    OPENAPI_JSON_PATH = "openapi.json"
    OPENAPI_SWAGGER_UI_PATH = "/docs"
    OPENAPI_SWAGGER_UI_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    API_SPEC_OPTIONS = {
        "info": {
            "description": (
                "Stability analytics for the applications monitored by Vigia: "
                "health time series, SLO compliance, statistical anomaly detection "
                "and incident management. Authenticate with POST /api/v1/auth/login "
                "and send the token as `Authorization: Bearer <token>`."
            )
        }
    }
