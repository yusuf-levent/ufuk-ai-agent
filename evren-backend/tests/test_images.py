"""Image generation: quota, credit weighting, storage, and API.

Finansal güvenlik odaklı testler:
- Çözünürlük çarpanı gerçek megapixel maliyet eğrisini takip etmeli (4K = 4x)
- Kota aşımı ÜRETİMDEN ÖNCE reddedilmeli (upstream maliyeti olmasın)
- Kullanıcı kendi görsellerine erişebilmeli, başkasınınkine ASLA
- `model` parametresi asla kullanıcıdan gelmemeli (pahalı model enjeksiyonu)
"""

from __future__ import annotations

import base64
import uuid
from decimal import Decimal

import httpx
import pytest
from app.errors import ApiError
from app.models.enums import ImageQuality
from app.services.image_service import (
    MAX_IMAGES_PER_REQUEST,
    ImageService,
    credit_weight,
    dimensions_for,
    normalize_format,
    validate_prompt,
)
from fastapi import FastAPI
from httpx import AsyncClient
from tests.helpers import register_and_login
from tests.test_plans_admin import create_plan_direct, create_tier_direct

# 1x1 red PNG
TINY_PNG = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
        "7753de0000000c4944415408d763f8cfc000000301010018dd8db0000000"
        "0049454e44ae426082"
    )
)


def _fake_image_response(count: int = 1) -> dict:
    return {
        "created": 1700000000,
        "data": [{"b64_json": TINY_PNG.decode()} for _ in range(count)],
        "usage": {"cost": 0.002},
    }


@pytest.fixture
async def image_env(tmp_path, app: FastAPI, client: AsyncClient):
    """Plan + tier + user with image quota, and a stubbed upstream."""
    app.state.images_root = tmp_path
    await create_plan_direct(
        app,
        name="free",
        monthly_credit_limit="1000",
        max_output_tokens_per_request=2048,
        requests_per_minute=600,
        monthly_image_quota=10,
        allowed_tier_aliases=["fast"],
        is_default=True,
    )
    await create_tier_direct(app)
    headers = await register_and_login(client, "img@example.com")
    user_id = uuid.UUID((await client.get("/me", headers=headers)).json()["id"])
    return headers, user_id


@pytest.fixture
async def install_image_upstream(app: FastAPI):
    created = []

    async def install(handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        created.append(client)

        class _Shim:
            async def generate_image(self, payload):
                req = httpx.Request("POST", "http://test/images/generations", json=payload)
                return handler(req)

            async def aclose(self):
                pass

        shim = _Shim()
        app.state.upstream = shim
        return shim

    yield install
    for c in created:
        await c.aclose()


# ---------------------------------------------------------------------------
# Unit: credit weighting + validation
# ---------------------------------------------------------------------------


def test_credit_weight_tracks_megapixel_curve() -> None:
    """4K must cost 4x a 1K image — the multiplier mirrors the real megapixel
    cost curve so a high-res request can never be sold below cost."""
    assert credit_weight(ImageQuality.STANDARD) == 1
    assert credit_weight(ImageQuality.HIGH) == 2
    assert credit_weight(ImageQuality.ULTRA) == 4


def test_dimensions_whitelist() -> None:
    assert dimensions_for(ImageQuality.STANDARD) == (1024, 1024)
    assert dimensions_for(ImageQuality.HIGH) == (2048, 2048)
    assert dimensions_for(ImageQuality.ULTRA) == (4096, 4096)


def test_normalize_format() -> None:
    assert normalize_format(None) == "png"
    assert normalize_format("PNG") == "png"
    assert normalize_format("jpg") == "jpeg"
    with pytest.raises(ApiError) as exc:
        normalize_format("bmp")
    assert exc.value.code == "unsupported_image_format"


def test_validate_prompt() -> None:
    assert validate_prompt("  hello  ") == "hello"
    with pytest.raises(ApiError):
        validate_prompt("")
    with pytest.raises(ApiError):
        validate_prompt("x" * 2001)


# ---------------------------------------------------------------------------
# Unit: quota
# ---------------------------------------------------------------------------


async def test_consume_quota_charges_by_quality(app: FastAPI, tmp_path):
    from app.models import Plan
    from tests.helpers import create_user

    service = ImageService(app.state.database, tmp_path)
    plan = Plan(
        name="test",
        monthly_credit_limit=Decimal("100"),
        max_output_tokens_per_request=1024,
        requests_per_minute=10,
        monthly_image_quota=10,
        allowed_tier_aliases=["fast"],
    )
    user = await create_user(app, "quota-charge@example.com")

    # 1 ultra (weight 4) + 1 standard (weight 1) = 5 credits
    total1 = await service.consume_quota(user.id, plan, ImageQuality.ULTRA, 1)
    assert total1 == 4
    total2 = await service.consume_quota(user.id, plan, ImageQuality.STANDARD, 1)
    assert total2 == 1


async def test_consume_quota_rejects_over_quota(app: FastAPI, tmp_path):
    from app.models import Plan
    from tests.helpers import create_user

    service = ImageService(app.state.database, tmp_path)
    plan = Plan(
        name="test",
        monthly_credit_limit=Decimal("100"),
        max_output_tokens_per_request=1024,
        requests_per_minute=10,
        monthly_image_quota=3,
        allowed_tier_aliases=["fast"],
    )
    user = await create_user(app, "quota-over@example.com")

    # 2 ultra = 8 credits > 3 quota
    with pytest.raises(ApiError) as exc:
        await service.consume_quota(user.id, plan, ImageQuality.ULTRA, 2)
    assert exc.value.code == "image_quota_exceeded"


async def test_consume_quota_rejects_disabled_plan(app: FastAPI, tmp_path):
    from app.models import Plan
    from tests.helpers import create_user

    service = ImageService(app.state.database, tmp_path)
    plan = Plan(
        name="test",
        monthly_credit_limit=Decimal("100"),
        max_output_tokens_per_request=1024,
        requests_per_minute=10,
        monthly_image_quota=None,
        allowed_tier_aliases=["fast"],
    )
    user = await create_user(app, "quota-disabled@example.com")
    with pytest.raises(ApiError) as exc:
        await service.consume_quota(user.id, plan, ImageQuality.STANDARD, 1)
    assert exc.value.code == "image_generation_disabled"


async def test_consume_quota_rejects_invalid_count(app: FastAPI, tmp_path):
    from app.models import Plan
    from tests.helpers import create_user

    service = ImageService(app.state.database, tmp_path)
    plan = Plan(
        name="test",
        monthly_credit_limit=Decimal("100"),
        max_output_tokens_per_request=1024,
        requests_per_minute=10,
        monthly_image_quota=100,
        allowed_tier_aliases=["fast"],
    )
    user = await create_user(app, "quota-count@example.com")
    with pytest.raises(ApiError):
        await service.consume_quota(user.id, plan, ImageQuality.STANDARD, 0)
    with pytest.raises(ApiError):
        await service.consume_quota(
            user.id, plan, ImageQuality.STANDARD, MAX_IMAGES_PER_REQUEST + 1
        )


# ---------------------------------------------------------------------------
# Unit: storage
# ---------------------------------------------------------------------------


async def test_store_and_read_image(app: FastAPI, tmp_path):
    from tests.helpers import create_user

    service = ImageService(app.state.database, tmp_path)
    user = await create_user(app, "store-read@example.com")
    result = await service.store(
        user_id=user.id,
        upstream_model_id="google/gemini-3.1-flash-lite-image",
        prompt="a cat",
        quality=ImageQuality.STANDARD,
        image_format="png",
        image_bytes=TINY_PNG,
        credits_charged=Decimal("1"),
    )
    assert result.width == 1024
    data = service.read_bytes(result.storage_path)
    assert data == TINY_PNG


async def test_read_bytes_blocks_path_traversal(app: FastAPI, tmp_path):
    service = ImageService(app.state.database, tmp_path)
    with pytest.raises(ApiError) as exc:
        service.read_bytes("../../etc/passwd")
    assert exc.value.code == "invalid_image_path"


async def test_delete_for_user_removes_files_and_rows(app: FastAPI, tmp_path):
    from app.models import GeneratedImage
    from sqlalchemy import select
    from tests.helpers import create_user

    service = ImageService(app.state.database, tmp_path)
    user = await create_user(app, "delete-cleanup@example.com")
    result = await service.store(
        user_id=user.id,
        upstream_model_id="m",
        prompt="x",
        quality=ImageQuality.STANDARD,
        image_format="png",
        image_bytes=TINY_PNG,
        credits_charged=Decimal("1"),
    )
    assert (tmp_path / result.storage_path).exists()

    deleted = await service.delete_for_user(user.id)
    assert deleted == 1
    assert not (tmp_path / result.storage_path).exists()
    async with app.state.database.session() as session:
        rows = (await session.execute(select(GeneratedImage))).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# Integration: API
# ---------------------------------------------------------------------------


async def test_generate_image_happy_path(
    client: AsyncClient, app: FastAPI, image_env, install_image_upstream
):
    headers, _user_id = image_env

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fake_image_response(1))

    await install_image_upstream(handler)
    resp = await client.post(
        "/images/generate",
        json={"prompt": "a red circle", "quality": "standard", "count": 1},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["credit_weight"] == 1
    assert data["credits_charged"] == "1"
    assert data["quota_remaining"] == 9
    assert len(data["images"]) == 1


async def test_generate_image_ultra_costs_4x(
    client: AsyncClient, app: FastAPI, image_env, install_image_upstream
):
    headers, _ = image_env

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fake_image_response(1))

    await install_image_upstream(handler)
    resp = await client.post(
        "/images/generate",
        json={"prompt": "a red circle", "quality": "ultra", "count": 1},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["credit_weight"] == 4
    assert data["credits_charged"] == "4"
    assert data["quota_remaining"] == 6


async def test_generate_image_pins_model_server_side(
    client: AsyncClient, app: FastAPI, image_env, install_image_upstream
):
    """SECURITY: the upstream model must be pinned server-side. A client that
    tries to name an expensive model must not be able to."""
    headers, _ = image_env
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content))
        return httpx.Response(200, json=_fake_image_response(1))

    await install_image_upstream(handler)
    resp = await client.post(
        "/images/generate",
        json={
            "prompt": "a red circle",
            "model": "openai/gpt-5.4-image-2",  # must be ignored
            "quality": "standard",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert captured[0]["model"] == "google/gemini-3.1-flash-lite-image"


async def test_generate_image_rejects_over_quota_before_generating(
    client: AsyncClient, app: FastAPI, image_env, install_image_upstream
):
    """Quota must be checked BEFORE the upstream call — a rejected request must
    not cost us an upstream call."""
    headers, _user_id = image_env
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_fake_image_response(1))

    await install_image_upstream(handler)
    # Exhaust quota: 10 standard images = 10 credits (quota=10)
    for _ in range(10):
        resp = await client.post(
            "/images/generate",
            json={"prompt": "x", "quality": "standard", "count": 1},
            headers=headers,
        )
        assert resp.status_code == 200

    # 11th must be rejected WITHOUT calling upstream
    resp = await client.post(
        "/images/generate",
        json={"prompt": "x", "quality": "standard", "count": 1},
        headers=headers,
    )
    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "image_quota_exceeded"
    assert len(calls) == 10  # upstream called exactly 10 times, not 11


async def test_get_image_ownership_enforced(
    client: AsyncClient, app: FastAPI, image_env, install_image_upstream
):
    """SECURITY: a user must only fetch their own images."""
    headers, _ = image_env

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fake_image_response(1))

    await install_image_upstream(handler)
    resp = await client.post(
        "/images/generate",
        json={"prompt": "x", "quality": "standard", "count": 1},
        headers=headers,
    )
    image_id = resp.json()["images"][0]["id"]

    # Owner can fetch
    resp = await client.get(f"/images/{image_id}", headers=headers)
    assert resp.status_code == 200

    # Another user cannot
    other_headers = await register_and_login(client, "other@example.com")
    resp = await client.get(f"/images/{image_id}", headers=other_headers)
    assert resp.status_code == 404


async def test_get_image_quota(client: AsyncClient, app: FastAPI, image_env):
    headers, _ = image_env
    resp = await client.get("/images/quota", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["quota"] == 10
    assert data["used"] == 0
    assert data["remaining"] == 10
    assert data["quality_weights"] == {"standard": 1, "high": 2, "ultra": 4}
