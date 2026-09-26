from __future__ import annotations

from fastapi import FastAPI


async def test_health_ok(client, app: FastAPI) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["components"] == {"database": True, "redis": True}


async def test_security_headers_present(client) -> None:
    response = await client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


async def test_body_size_limit(client) -> None:
    response = await client.post(
        "/health",
        content=b"x",
        headers={"content-length": str(10 * 1024 * 1024 + 1)},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
