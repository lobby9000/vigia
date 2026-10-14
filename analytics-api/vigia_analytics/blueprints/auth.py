"""POST /api/v1/auth/login: exchange username and password for a JWT."""

from flask import current_app
from flask_jwt_extended import create_access_token
from flask_smorest import Blueprint, abort

from .. import services
from ..extensions import get_engine
from ..schemas import LoginSchema, TokenSchema

blp = Blueprint("auth", __name__, url_prefix="/api/v1/auth", description="Obtain an access token")


@blp.route("/login", methods=["POST"])
@blp.arguments(LoginSchema)
@blp.response(200, TokenSchema)
@blp.alt_response(401, description="Wrong username or password")
def login(credentials):
    user = services.authenticate(get_engine(), credentials["username"], credentials["password"])
    if user is None:
        # Same message for "unknown user" and "wrong password": do not help guessing.
        abort(401, message="Wrong username or password.")

    # The token is signed (HS256) with JWT_SECRET_KEY, not encrypted: anyone can
    # read its claims, nobody can change them without the secret. Never put
    # sensitive data in it.
    token = create_access_token(identity=user["username"], additional_claims={"role": user["role"]})
    lifetime = current_app.config["JWT_ACCESS_TOKEN_EXPIRES"]
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": int(lifetime.total_seconds()),
        "role": user["role"],
    }
