from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import ModelTier, Plan
from app.models.enums import PricingUnit, SubscriptionStatus


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    monthly_credit_limit: Decimal
    max_output_tokens_per_request: int
    requests_per_minute: int
    max_credits_per_request: Decimal | None = None
    max_credits_per_window: Decimal | None = None
    budget_window_seconds: int = 300
    max_concurrent_requests: int | None = None
    monthly_image_quota: int | None = None
    allowed_tier_aliases: list[str]
    is_default: bool
    stripe_price_id: str | None = None
    provider_price_id: str | None = None
    price_usd: Decimal | None = None


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    monthly_credit_limit: Decimal = Field(gt=0)
    max_output_tokens_per_request: int = Field(gt=0)
    requests_per_minute: int = Field(gt=0)
    max_credits_per_request: Decimal | None = Field(default=None, gt=0)
    max_credits_per_window: Decimal | None = Field(default=None, gt=0)
    budget_window_seconds: int = Field(default=300, gt=0)
    max_concurrent_requests: int | None = Field(default=None, gt=0)
    monthly_image_quota: int | None = Field(default=None, ge=0)
    allowed_tier_aliases: list[str] = Field(min_length=1)
    is_default: bool = False
    stripe_price_id: str | None = Field(default=None, max_length=100)
    provider_price_id: str | None = Field(default=None, max_length=100)
    price_usd: Decimal | None = Field(default=None, ge=0)


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    monthly_credit_limit: Decimal | None = Field(default=None, gt=0)
    max_output_tokens_per_request: int | None = Field(default=None, gt=0)
    requests_per_minute: int | None = Field(default=None, gt=0)
    max_credits_per_request: Decimal | None = Field(default=None, gt=0)
    max_credits_per_window: Decimal | None = Field(default=None, gt=0)
    budget_window_seconds: int | None = Field(default=None, gt=0)
    max_concurrent_requests: int | None = Field(default=None, gt=0)
    monthly_image_quota: int | None = Field(default=None, ge=0)
    allowed_tier_aliases: list[str] | None = Field(default=None, min_length=1)
    is_default: bool | None = None
    stripe_price_id: str | None = Field(default=None, max_length=100)
    provider_price_id: str | None = Field(default=None, max_length=100)
    price_usd: Decimal | None = Field(default=None, ge=0)


class TierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alias: str
    display_name: str
    upstream_model_id: str
    upstream_provider_name: str
    input_credits_per_1k_tokens: Decimal
    output_credits_per_1k_tokens: Decimal
    cache_read_multiplier: Decimal
    cache_write_multiplier: Decimal
    reasoning_multiplier: Decimal
    max_output_tokens: int
    context_window: int
    input_modalities: list[str] = ["text"]
    output_modalities: list[str] = ["text"]
    supports_tools: bool = True
    pricing_unit: PricingUnit = PricingUnit.TOKEN
    max_images_per_request: int | None = None
    is_internal: bool = False
    fallback_model_ids: list[str] = []
    routing_plugin: str | None = None
    # Tooltip metadata for the model picker (ℹ️ hover card). Curated manually
    # via seed/admin — never derived from upstream pricing.
    tooltip_title: str | None = None
    tooltip_body: str | None = None
    tooltip_cost_level: int | None = None  # 1=very cheap … 5=very expensive
    tooltip_speed_level: int | None = None  # 1=slow … 5=fast
    tooltip_quality_level: int | None = None  # 1=basic … 5=exceptional
    tooltip_best_for: str | None = None
    price_note: str | None = None
    price_note_tr: str | None = None
    speed_hint: int | None = None
    quality_hint: int | None = None
    enabled: bool


class TierCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=100)
    upstream_model_id: str = Field(min_length=1, max_length=200)
    upstream_provider_name: str = Field(min_length=1, max_length=100)
    input_credits_per_1k_tokens: Decimal = Field(ge=0)
    output_credits_per_1k_tokens: Decimal = Field(ge=0)
    cache_read_multiplier: Decimal = Field(default=Decimal("1.0"), ge=0)
    cache_write_multiplier: Decimal = Field(default=Decimal("1.0"), ge=0)
    reasoning_multiplier: Decimal = Field(default=Decimal("1.0"), ge=0)
    max_output_tokens: int = Field(gt=0)
    context_window: int = Field(gt=0)
    input_modalities: list[str] = Field(default_factory=lambda: ["text"], min_length=1)
    output_modalities: list[str] = Field(default_factory=lambda: ["text"], min_length=1)
    supports_tools: bool = True
    pricing_unit: PricingUnit = PricingUnit.TOKEN
    max_images_per_request: int | None = Field(default=None, gt=0)
    is_internal: bool = False
    fallback_model_ids: list[str] = Field(default_factory=list)
    routing_plugin: str | None = Field(default=None, max_length=50)
    tooltip_title: str | None = Field(default=None, max_length=100)
    tooltip_body: str | None = Field(default=None, max_length=500)
    tooltip_cost_level: int | None = Field(default=None, ge=1, le=5)
    tooltip_speed_level: int | None = Field(default=None, ge=1, le=5)
    tooltip_quality_level: int | None = Field(default=None, ge=1, le=5)
    tooltip_best_for: str | None = Field(default=None, max_length=200)
    price_note: str | None = Field(default=None, max_length=200)
    price_note_tr: str | None = Field(default=None, max_length=200)
    speed_hint: int | None = Field(default=None, ge=1, le=5)
    quality_hint: int | None = Field(default=None, ge=1, le=5)
    enabled: bool = True


class TierUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    upstream_model_id: str | None = Field(default=None, min_length=1, max_length=200)
    upstream_provider_name: str | None = Field(default=None, min_length=1, max_length=100)
    input_credits_per_1k_tokens: Decimal | None = Field(default=None, ge=0)
    output_credits_per_1k_tokens: Decimal | None = Field(default=None, ge=0)
    cache_read_multiplier: Decimal | None = Field(default=None, ge=0)
    cache_write_multiplier: Decimal | None = Field(default=None, ge=0)
    reasoning_multiplier: Decimal | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    context_window: int | None = Field(default=None, gt=0)
    input_modalities: list[str] | None = Field(default=None, min_length=1)
    output_modalities: list[str] | None = Field(default=None, min_length=1)
    supports_tools: bool | None = None
    pricing_unit: PricingUnit | None = None
    max_images_per_request: int | None = Field(default=None, gt=0)
    is_internal: bool | None = None
    fallback_model_ids: list[str] | None = None
    routing_plugin: str | None = Field(default=None, max_length=50)
    tooltip_title: str | None = Field(default=None, max_length=100)
    tooltip_body: str | None = Field(default=None, max_length=500)
    tooltip_cost_level: int | None = Field(default=None, ge=1, le=5)
    tooltip_speed_level: int | None = Field(default=None, ge=1, le=5)
    tooltip_quality_level: int | None = Field(default=None, ge=1, le=5)
    tooltip_best_for: str | None = Field(default=None, max_length=200)
    price_note: str | None = Field(default=None, max_length=200)
    price_note_tr: str | None = Field(default=None, max_length=200)
    speed_hint: int | None = Field(default=None, ge=1, le=5)
    quality_hint: int | None = Field(default=None, ge=1, le=5)
    enabled: bool | None = None


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    plan_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    status: SubscriptionStatus


class AssignPlanRequest(BaseModel):
    plan_id: uuid.UUID


class TierUsageResponse(BaseModel):
    tier_alias: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    credits_charged: Decimal


class AdminUsageResponse(BaseModel):
    user_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    plan_name: str
    credit_limit: Decimal
    credits_used: Decimal
    per_tier: list[TierUsageResponse]


def plan_response(plan: Plan) -> PlanResponse:
    return PlanResponse.model_validate(plan)


def tier_response(tier: ModelTier) -> TierResponse:
    return TierResponse.model_validate(tier)
