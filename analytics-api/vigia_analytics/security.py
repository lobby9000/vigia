"""Authentication helpers: password hashing, role checks and JWT error format.

Authentication answers "who are you?" (a valid token signed by us).
Authorization answers "what may you do?" (the ``role`` claim inside it).
"""

from __future__ import annotations

from functools import wraps

from flask import jsonify
from flask_jwt_extended import JWTManager, get_jwt, verify_jwt_in_request
from flask_smorest import abort
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = ("viewer", "admin")

# OpenAPI security requirement used by every protected endpoint
BEARER_AUTH = [{"bearerAuth": []}]

# Computed once. Used when a username does not exist so that the response
# takes as long as a wrong password: response time must not reveal which
# usernames are valid (a timing side channel).
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def hash_password(password: str) -> str:
    """Salted, slow hash (scrypt by default in Werkzeug 3). Never store plain text."""
    return generate_password_hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    if stored_hash is None:
        check_password_hash(_DUMMY_HASH, password)
        return False
    return check_password_hash(stored_hash, password)


def roles_required(*allowed_roles: str):
    """Decorator: valid JWT required, and its ``role`` claim must be allowed."""

    unknown = set(allowed_roles) - set(ROLES)
    if unknown:
        raise ValueError(f"Unknown roles: {unknown}")

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()  # raises -> 401 handlers below
            if get_jwt().get("role") not in allowed_roles:
                abort(403, message="Your role does not allow this operation.")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def register_jwt_error_handlers(jwt: JWTManager) -> None:
    """Return JWT problems with the same JSON shape as every other API error."""

    def error(status: int, reason: str, message: str):
        return jsonify(code=status, status=reason, message=message), status

    @jwt.unauthorized_loader
    def missing_token(reason: str):
        return error(401, "Unauthorized", reason)

    @jwt.invalid_token_loader
    def invalid_token(reason: str):
        # flask-jwt-extended answers 422 by default; a bad token is a 401.
        return error(401, "Unauthorized", f"Invalid token: {reason}")

    @jwt.expired_token_loader
    def expired_token(_header, _payload):
        return error(401, "Unauthorized", "Token has expired. Log in again.")
