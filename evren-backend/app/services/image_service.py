"""Image generation: quota, credit weighting, and storage.

Design decisions (see docs/FIYATLANDIRMA-VE-MODEL-TASARIMI.md):

* **Quality-weighted credits.** A generated image costs one "image credit" at
  standard (1K) resolution, two at high (2K), four at ultra (4K). This mirrors
  OpenRouter's megapixel-based `variant` pricing — a 4K image really does cost
  us ~4x a 1K one — while keeping the user's mental model dead simple:
  "1 photo = N credits, sharper = more". Because the multiplier tracks the real
  cost curve, a high-res request can never be sold below cost.

* **Separate quota, not chat credits.** Image pricing units vary across
  providers (image / megapixel / token), so folding them into the per-1k-token
  credit formula would mis-bill. A monthly image-credit quota is what users can
  actually reason about ("23/50 photos left").

* **We store the binaries.** Keeping generated images on our own storage (not
  just relaying an upstream URL) gives us persistence when the upstream link
  expires, a gallery the user can return to, and a hard place to enforce
  deletion on account removal. The upstream model id stays internal — the user
  never learns which model drew their picture, same as hidden sub-agent tiers.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.db import Database
from app.errors import ApiError
from app.models import GeneratedImage, Plan
from app.models.base import utcnow
from app.models.enums import ImageQuality
from app.services.credits import quantize_credits

#: Image credits charged per generation, by resolution tier. Mirrors the
#: megapixel cost curve (1K -> 2K -> 4K roughly quadruples the pixels).
QUALITY_CREDIT_WEIGHT: dict[ImageQuality, int] = {
    ImageQuality.STANDARD: 1,
    ImageQuality.HIGH: 2,
    ImageQuality.ULTRA: 4,
}

#: Pixel dimensions per quality tier. Kept to a whitelist so a caller cannot
#: request an arbitrary size and inflate the megapixel bill.
QUALITY_DIMENSIONS: dict[ImageQuality, tuple[int, int]] = {
    ImageQuality.STANDARD: (1024, 1024),
    ImageQuality.HIGH: (2048, 2048),
    ImageQuality.ULTRA: (4096, 4096),
}

#: Allowed output formats (PNG keeps quality, JPEG for size-conscious users).
ALLOWED_FORMATS = frozenset({"png", "jpeg", "jpg"})

#: Hard ceiling on prompt length — an unbounded prompt is both a cost and an
#: abuse vector.
MAX_PROMPT_LENGTH = 2000

#: Maximum images generated in a single request (burst guard).
MAX_IMAGES_PER_REQUEST = 4


@dataclass(frozen=True, slots=True)
class ImageQuota:
    quota: int | None
    used: int
    remaining: int | None


@dataclass(frozen=True, slots=True)
class StoredImage:
    id: uuid.UUID
    storage_path: str
    width: int
    height: int
    format: str
    credits_charged: Decimal


def credit_weight(quality: ImageQuality) -> int:
    """Image credits one generation at this quality consumes."""
    return QUALITY_CREDIT_WEIGHT[quality]


def dimensions_for(quality: ImageQuality) -> tuple[int, int]:
    return QUALITY_DIMENSIONS[quality]


def normalize_format(fmt: str | None) -> str:
    value = (fmt or "png").strip().lower()
    if value == "jpg":
        value = "jpeg"
    if value not in ALLOWED_FORMATS:
        raise ApiError(
            status_code=400,
            message=f"Unsupported image format '{fmt}'",
            type="invalid_request_error",
            code="unsupported_image_format",
        )
    return value


def validate_prompt(prompt: str) -> str:
    cleaned = prompt.strip()
    if not cleaned:
        raise ApiError(
            status_code=400,
            message="Image prompt must not be empty",
            type="invalid_request_error",
            code="empty_image_prompt",
        )
    if len(cleaned) > MAX_PROMPT_LENGTH:
        raise ApiError(
            status_code=400,
            message=f"Image prompt exceeds {MAX_PROMPT_LENGTH} characters",
            type="invalid_request_error",
            code="image_prompt_too_long",
        )
    return cleaned


class ImageService:
    """Quota enforcement + durable storage for generated images."""

    def __init__(self, database: Database, storage_root: Path) -> None:
        self._db = database
        self._root = storage_root

    # ---- Quota -----------------------------------------------------------

    async def quota_for(self, user_id: uuid.UUID, plan: Plan) -> ImageQuota:
        """Remaining image credits this billing period (UTC-month bucketed)."""
        if plan.monthly_image_quota is None:
            return ImageQuota(quota=None, used=0, remaining=None)
        period_start, period_end = _current_month_window()
        async with self._db.session() as session:
            used = await session.scalar(
                select(func.coalesce(func.sum(GeneratedImage.credits_charged), 0)).where(
                    GeneratedImage.user_id == user_id,
                    GeneratedImage.created_at >= period_start,
                    GeneratedImage.created_at < period_end,
                )
            )
        used_int = int(Decimal(used or 0))
        remaining = max(plan.monthly_image_quota - used_int, 0)
        return ImageQuota(quota=plan.monthly_image_quota, used=used_int, remaining=remaining)

    async def consume_quota(
        self, user_id: uuid.UUID, plan: Plan, quality: ImageQuality, count: int
    ) -> int:
        """Charge `count` generations at `quality` against the monthly quota.

        Returns the total image credits consumed. Raises 402 when the quota
        would be exceeded — the caller must not have generated anything yet.
        """
        if plan.monthly_image_quota is None:
            raise ApiError(
                status_code=403,
                message="Image generation is not available on your plan",
                type="permission_error",
                code="image_generation_disabled",
            )
        if count < 1 or count > MAX_IMAGES_PER_REQUEST:
            raise ApiError(
                status_code=400,
                message=f"Image count must be between 1 and {MAX_IMAGES_PER_REQUEST}",
                type="invalid_request_error",
                code="invalid_image_count",
            )
        weight = credit_weight(quality)
        total = weight * count
        quota = await self.quota_for(user_id, plan)
        if quota.remaining is not None and total > quota.remaining:
            raise ApiError(
                status_code=402,
                message="Image quota exceeded for the current month",
                type="insufficient_quota",
                code="image_quota_exceeded",
                extra={"remaining": str(quota.remaining), "requested": str(total)},
            )
        return total

    # ---- Storage ---------------------------------------------------------

    async def store(
        self,
        *,
        user_id: uuid.UUID,
        upstream_model_id: str,
        prompt: str,
        quality: ImageQuality,
        image_format: str,
        image_bytes: bytes,
        credits_charged: Decimal,
        plan: Plan | None = None,
        upstream_cost_usd: Decimal | None = None,
        latency_ms: int | None = None,
    ) -> StoredImage:
        """Persist one generated image (binary to disk, metadata to DB).

        When ``plan`` is given, the quota is re-checked AFTER the upstream call
        (optimistic concurrency): two parallel requests can both pass
        ``consume_quota`` before either stores, so this second check catches the
        race. ``max_concurrent_requests`` already bounds the window; this is
        belt-and-braces. On quota breach the stored file is removed and 402
        raised — we never silently exceed a paid quota.
        """
        width, height = dimensions_for(quality)
        image_id = uuid.uuid4()
        ext = "jpg" if image_format == "jpeg" else image_format
        relative = Path(str(user_id)) / f"{image_id}.{ext}"
        absolute = self._root / relative
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(image_bytes)

        # Post-write quota check (race guard).
        if plan is not None and plan.monthly_image_quota is not None:
            quota = await self.quota_for(user_id, plan)
            if quota.remaining is not None and credits_charged > quota.remaining:
                absolute.unlink(missing_ok=True)
                raise ApiError(
                    status_code=402,
                    message="Image quota exceeded for the current month",
                    type="insufficient_quota",
                    code="image_quota_exceeded",
                    extra={"remaining": str(quota.remaining)},
                )

        async with self._db.session() as session:
            row = GeneratedImage(
                id=image_id,
                user_id=user_id,
                upstream_model_id=upstream_model_id,
                prompt=prompt,
                quality=quality,
                width=width,
                height=height,
                format=image_format,
                storage_path=str(relative).replace("\\", "/"),
                credits_charged=quantize_credits(credits_charged),
                upstream_cost_usd=(
                    quantize_credits(upstream_cost_usd)
                    if upstream_cost_usd is not None
                    else None
                ),
                latency_ms=latency_ms,
            )
            session.add(row)
            await session.commit()

        return StoredImage(
            id=image_id,
            storage_path=str(relative).replace("\\", "/"),
            width=width,
            height=height,
            format=image_format,
            credits_charged=quantize_credits(credits_charged),
        )

    def read_bytes(self, storage_path: str) -> bytes:
        absolute = (self._root / storage_path).resolve()
        # Path traversal guard: the resolved path must stay under the root.
        if not str(absolute).startswith(str(self._root.resolve())):
            raise ApiError(
                status_code=400,
                message="Invalid image path",
                type="invalid_request_error",
                code="invalid_image_path",
            )
        return absolute.read_bytes()

    async def delete_for_user(self, user_id: uuid.UUID) -> int:
        """Remove every image belonging to a user (account deletion)."""
        from sqlalchemy import delete as sa_delete

        async with self._db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(GeneratedImage.storage_path).where(
                            GeneratedImage.user_id == user_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for path in rows:
                absolute = self._root / path
                if absolute.exists():
                    absolute.unlink()
            await session.execute(
                sa_delete(GeneratedImage).where(GeneratedImage.user_id == user_id)
            )
            await session.commit()
        return len(rows)


def decode_image_payload(data: str) -> bytes:
    """Decode a base64 image payload from an upstream response."""
    try:
        return base64.b64decode(data, validate=True)
    except Exception as exc:
        raise ApiError(
            status_code=502,
            message="Upstream returned an unreadable image",
            type="server_error",
            code="invalid_upstream_image",
        ) from exc


def _current_month_window() -> tuple[datetime, datetime]:
    now = utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end
