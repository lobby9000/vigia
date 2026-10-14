"""Authentication (who are you?) and authorization (what may you do?)."""

from datetime import timedelta

import jwt as pyjwt
from flask_jwt_extended import create_access_token

from .conftest import ADMIN, TEST_SECRET, VIEWER


def test_login_returns_a_bearer_token_with_the_role(client):
    response = client.post("/api/v1/auth/login", json={"username": VIEWER[0], "password": VIEWER[1]})

    assert response.status_code == 200
    body = response.get_json()
    assert body["tokenType"] == "Bearer" and body["role"] == "viewer" and body["expiresIn"] == 3600
    claims = pyjwt.decode(body["accessToken"], TEST_SECRET, algorithms=["HS256"], issuer="vigia-analytics")
    assert claims["sub"] == VIEWER[0] and claims["role"] == "viewer"


def test_wrong_password_and_unknown_user_get_the_same_answer(client):
    wrong_password = client.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": "nope"})
    unknown_user = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.get_json()["message"] == unknown_user.get_json()["message"]


def test_login_validates_its_payload(client):
    response = client.post("/api/v1/auth/login", json={"username": "ana"})

    assert response.status_code == 422
    assert "password" in response.get_json()["errors"]["json"]


def test_protected_endpoints_require_a_token(client):
    response = client.get("/api/v1/applications")

    assert response.status_code == 401
    assert response.get_json()["status"] == "Unauthorized"


def test_viewers_cannot_run_admin_operations(client, viewer_headers):
    response = client.post("/api/v1/applications/payments-api/anomaly-scans", json={}, headers=viewer_headers)

    assert response.status_code == 403


def test_expired_tokens_are_rejected(app, client):
    with app.app_context():
        token = create_access_token(
            identity=ADMIN[0], additional_claims={"role": "admin"}, expires_delta=timedelta(seconds=-1)
        )
    response = client.get("/api/v1/applications", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert "expired" in response.get_json()["message"]


def test_tokens_signed_with_another_secret_are_rejected(client):
    forged = pyjwt.encode(
        {"sub": "mallory", "role": "admin", "iss": "vigia-analytics", "type": "access", "fresh": False, "jti": "x"},
        "some-other-secret-that-is-long-enough-for-hs256-0000",
        algorithm="HS256",
    )
    response = client.get("/api/v1/applications", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401
