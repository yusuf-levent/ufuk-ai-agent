from __future__ import annotations

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

PASSWORD = "Passw0rd!123"


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def email_sender(app: FastAPI) -> FakeEmailSender:
    sender = FakeEmailSender()
    original = app.state.email_sender
    app.state.email_sender = sender
    yield sender
    app.state.email_sender = original


def token_from_email(sender: FakeEmailSender) -> str:
    assert sender.sent, "no email was sent"
    body = sender.sent[-1]["body"]
    return body.rsplit(":", 1)[-1].strip()


async def register(client: AsyncClient, email: str, password: str = PASSWORD) -> object:
    return await client.post("/auth/register", json={"email": email, "password": password})


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> object:
    return await client.post("/auth/login", json={"email": email, "password": password})


async def test_register_login_me(client: AsyncClient) -> None:
    response = await register(client, "user@example.com")
    assert response.status_code == 201
    assert response.json()["email"] == "user@example.com"
    assert response.json()["role"] == "user"

    response = await login(client, "user@example.com")
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0

    response = await client.get(
        "/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"
    assert response.json()["email_verified"] is False


async def test_me_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/me")
    assert response.status_code == 401
    response = await client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


async def test_login_wrong_password_generic_error(client: AsyncClient) -> None:
    await register(client, "known@example.com")
    response = await login(client, "known@example.com", "WrongPass!1")
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["message"] == "Invalid email or password"

    response = await login(client, "unknown@example.com", "WrongPass!1")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password"


async def test_register_duplicate_email_generic_error(client: AsyncClient) -> None:
    await register(client, "dup@example.com")
    response = await register(client, "dup@example.com")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "registration_failed"


async def test_register_validation(client: AsyncClient) -> None:
    response = await register(client, "not-an-email")
    assert response.status_code == 422
    response = await register(client, "short@example.com", password="short")
    assert response.status_code == 422


async def test_refresh_rotation_and_reuse_detection(client: AsyncClient) -> None:
    await register(client, "rotate@example.com")
    tokens = (await login(client, "rotate@example.com")).json()

    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    response = await client.get(
        "/me", headers={"Authorization": f"Bearer {rotated['access_token']}"}
    )
    assert response.status_code == 200

    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "refresh_token_reused"

    response = await client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert response.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    await register(client, "logout@example.com")
    tokens = (await login(client, "logout@example.com")).json()

    response = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200

    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


async def test_change_password(client: AsyncClient) -> None:
    await register(client, "change@example.com")
    tokens = (await login(client, "change@example.com")).json()

    response = await client.post(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "NewPass!456"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 401

    response = await client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "NewPass!456"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 200

    response = await login(client, "change@example.com", "NewPass!456")
    assert response.status_code == 200
    response = await login(client, "change@example.com", PASSWORD)
    assert response.status_code == 401

    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


async def test_verify_email_flow(client: AsyncClient, email_sender: FakeEmailSender) -> None:
    await register(client, "verify@example.com")
    token = token_from_email(email_sender)

    response = await client.post("/auth/verify-email", json={"token": token})
    assert response.status_code == 200

    tokens = (await login(client, "verify@example.com")).json()
    response = await client.get(
        "/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.json()["email_verified"] is True

    response = await client.post("/auth/verify-email", json={"token": token})
    assert response.status_code == 400


async def test_password_reset_flow(client: AsyncClient, email_sender: FakeEmailSender) -> None:
    await register(client, "reset@example.com")

    response = await client.post("/auth/reset-password", json={"email": "reset@example.com"})
    assert response.status_code == 200
    token = token_from_email(email_sender)

    response = await client.post(
        "/auth/reset-password/confirm",
        json={"token": token, "new_password": "Reset!789"},
    )
    assert response.status_code == 200

    response = await login(client, "reset@example.com", "Reset!789")
    assert response.status_code == 200
    response = await login(client, "reset@example.com", PASSWORD)
    assert response.status_code == 401


async def test_password_reset_unknown_email_is_silent(
    client: AsyncClient, email_sender: FakeEmailSender
) -> None:
    response = await client.post("/auth/reset-password", json={"email": "ghost@example.com"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert email_sender.sent == []


async def test_expired_access_token(client: AsyncClient, app: FastAPI) -> None:
    await register(client, "expired@example.com")
    settings = app.state.settings
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    token = pyjwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "type": "access", "iat": now, "exp": now},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    response = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


async def test_login_rate_limited_per_account(client: AsyncClient) -> None:
    await register(client, "brute@example.com")
    for _ in range(5):
        response = await login(client, "brute@example.com", "Wrong!123")
        assert response.status_code == 401
    response = await login(client, "brute@example.com", "Wrong!123")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert "retry-after" in {k.lower() for k in response.headers}

    response = await login(client, "brute@example.com", PASSWORD)
    assert response.status_code == 429


async def test_register_rate_limited_per_ip(client: AsyncClient) -> None:
    for i in range(10):
        await register(client, f"user{i}@example.com")
    response = await register(client, "toomany@example.com")
    assert response.status_code == 429
