from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ImageQuality


class GenerateImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    quality: ImageQuality | None = None
    count: int | None = Field(default=None, ge=1, le=4)
    format: str | None = Field(default=None, max_length=10)


class GenerateImageResponse(BaseModel):
    images: list[dict[str, Any]]
    credits_charged: str
    quality: str
    credit_weight: int
    quota_remaining: int | None


class ImageQuotaResponse(BaseModel):
    quota: int | None
    used: int
    remaining: int | None
    quality_weights: dict[str, int]
