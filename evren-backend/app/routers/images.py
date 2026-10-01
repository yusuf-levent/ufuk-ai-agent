from __future__ import annotations

import time
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.dependencies import get_current_user
from app.errors import ApiError
from app.models import User
from app.models.enums import ImageQuality
from app.schemas.images import (
    GenerateImageRequest,
    GenerateImageResponse,
    ImageQuotaResponse,
)
from app.services import subscriptions as subscription_service
from app.services.image_service import (
    MAX_IMAGES_PER_REQUEST,
    ImageService,
    credit_weight,
    decode_image_payload,
    dimensions_for,
    normalize_format,
    validate_prompt,
)

router = APIRouter(prefix="/images", tags=["images"])

#: Server-pinned image model. NEVER taken from the client â€” a user must not be
#: able to name an expensive image model (e.g. openai/gpt-5.4-image-2 at
#: $8/$15 per 1M) and blow the budget. This is the cheapest vision-capable
#: image model on OpenRouter (Gemini 3.1 Flash Lite Image, $0.25/$1.50 per 1M).
DEFAULT_IMAGE_MODEL = "google/gemini-3.1-flash-lite-image"


def _image_service(request: Request) -> ImageService:
    return ImageService(request.app.state.database, request.app.state.images_root)


@router.post("/generate", response_model=GenerateImageResponse)
async def generate_images(
    body: GenerateImageRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> GenerateImageResponse:
    """Generate one or more images and store them on our backend.

    Flow: validate -> quota check (BEFORE generating) -> upstream call ->
    decode + store -> return metadata. The upstream model is pinned server-side;
    the client only chooses quality (which drives the credit multiplier).
    """
    database = request.app.state.database
    service = _image_service(request)
    # Rolled lookup: free periods extend automatically; paid ones require a
    # renewal payment (no payment, no service).
    active = await subscription_service.get_active_or_rolled_subscription(database, user.id)
    if active is None:
        raise ApiError(
            status_code=403,
            message="No active subscription",
            type="permission_error",
            code="subscription_inactive",
        )

    prompt = validate_prompt(body.prompt)
    image_format = normalize_format(body.format)
    count = min(max(body.count or 1, 1), MAX_IMAGES_PER_REQUEST)
    quality = body.quality or ImageQuality.STANDARD

    # Charge quota BEFORE generating so a rejected request never costs us an
    # upstream call. The weight reflects the real megapixel cost curve. The
    # quota window is the BILLING period (not the calendar month) and never
    # rolls over.
    total_credits = await service.consume_quota(
        user.id, active.plan, quality, count, active.period
    )

    width, height = dimensions_for(quality)
    upstream_payload = {
        "model": DEFAULT_IMAGE_MODEL,
        "prompt": prompt,
        "n": count,
        "size": f"{width}x{height}",
        "response_format": "b64_json",
    }

    started = time.monotonic()
    upstream = request.app.state.upstream
    response = await upstream.generate_image(upstream_payload)
    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        body_text = (await response.aread()).decode("utf-8", errors="replace")
        raise ApiError(
            status_code=502,
            message="Image generation failed upstream",
            type="server_error",
            code="image_generation_failed",
            extra={"upstream_status": response.status_code, "detail": body_text[:200]},
        )

    data = response.json()
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ApiError(
            status_code=502,
            message="Image generation returned no images",
            type="server_error",
            code="image_generation_empty",
        )

    # Real USD cost (for margin tracking) â€” captured before any stripping.
    usage = data.get("usage") if isinstance(data, dict) else None
    upstream_cost_usd: Decimal | None = None
    if isinstance(usage, dict) and isinstance(usage.get("cost"), (int, float)):
        upstream_cost_usd = Decimal(str(usage["cost"]))

    # Per-image credit: total charged is split evenly across the batch so each
    # stored row carries its share (keeps per-image cost attribution honest).
    per_image_credits = Decimal(total_credits) / Decimal(len(items))

    stored = []
    for item in items:
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json") or item.get("url")
        if not isinstance(b64, str):
            continue
        if item.get("b64_json"):
            image_bytes = decode_image_payload(b64)
        else:
            # URL variant: fetch is intentionally not supported here to avoid
            # SSRF; the b64 path is what we request from the upstream.
            raise ApiError(
                status_code=502,
                message="Image generation returned an unsupported URL response",
                type="server_error",
                code="image_generation_unsupported_response",
            )
        result = await service.store(
            user_id=user.id,
            plan=active.plan,
            period=active.period,
            upstream_model_id=DEFAULT_IMAGE_MODEL,
            prompt=prompt,
            quality=quality,
            image_format=image_format,
            image_bytes=image_bytes,
            credits_charged=per_image_credits,
            upstream_cost_usd=upstream_cost_usd,
            latency_ms=latency_ms,
        )
        stored.append(result)

    if not stored:
        raise ApiError(
            status_code=502,
            message="Image generation produced no storable images",
            type="server_error",
            code="image_generation_empty",
        )

    quota = await service.quota_for(user.id, active.plan, active.period)
    return GenerateImageResponse(
        images=[
            {
                "id": str(img.id),
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "credits_charged": str(img.credits_charged),
            }
            for img in stored
        ],
        credits_charged=str(Decimal(total_credits)),
        quality=quality.value,
        credit_weight=credit_weight(quality),
        quota_remaining=quota.remaining,
    )


@router.get("/quota", response_model=ImageQuotaResponse)
async def get_image_quota(
    request: Request,
    user: User = Depends(get_current_user),
) -> ImageQuotaResponse:
    database = request.app.state.database
    service = _image_service(request)
    active = await subscription_service.get_active_or_rolled_subscription(database, user.id)
    if active is None:
        raise ApiError(
            status_code=403,
            message="No active subscription",
            type="permission_error",
            code="subscription_inactive",
        )
    quota = await service.quota_for(user.id, active.plan, active.period)
    return ImageQuotaResponse(
        quota=quota.quota,
        used=quota.used,
        remaining=quota.remaining,
        reset_at=active.period_end,
        quality_weights={
            "standard": 1,
            "high": 2,
            "ultra": 4,
        },
    )


@router.get("/{image_id}")
async def get_image(
    image_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
) -> Response:
    """Serve a stored image. Ownership enforced â€” a user can only fetch their
    own images (prevents enumeration of other users' galleries)."""
    from sqlalchemy import select

    from app.models import GeneratedImage

    database = request.app.state.database
    service = _image_service(request)
    async with database.session() as session:
        row = await session.scalar(
            select(GeneratedImage).where(
                GeneratedImage.id == image_id, GeneratedImage.user_id == user.id
            )
        )
    if row is None:
        raise ApiError(
            status_code=404,
            message="Image not found",
            type="invalid_request_error",
            code="image_not_found",
        )
    try:
        data = service.read_bytes(row.storage_path)
    except FileNotFoundError as exc:
        raise ApiError(
            status_code=404,
            message="Image data missing",
            type="server_error",
            code="image_data_missing",
        ) from exc
    media_type = "image/jpeg" if row.format == "jpeg" else f"image/{row.format}"
    return Response(content=data, media_type=media_type)
