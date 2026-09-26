from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import ModelTier, Plan
from app.models.enums import SubscriptionStatus


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    monthly_credit_limit: Decimal
    max_output_tokens_per_request: int
    requests_per_minute: int
    allowed_tier_aliases: list[str]
    is_default: bool


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    monthly_credit_limit: Decimal = Field(gt=0)
    max_output_tokens_per_request: int = Field(gt=0)
    requests_per_minute: int = Field(gt=0)
    allowed_tier_aliases: list[str] = Field(min_length=1)
    is_default: bool = False


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    monthly_credit_limit: Decimal | None = Field(default=None, gt=0)
    max_output_tokens_per_request: int | None = Field(default=None, gt=0)
    requests_per_minute: int | None = Field(default=None, gt=0)
    allowed_tier_aliases: list[str] | None = Field(default=None, min_length=1)
    is_default: bool | None = None


class TierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alias: str
    display_name: str
    upstream_model_id: str
    upstream_provider_name: str
    input_credits_per_1k_tokens: Decimal
    output_credits_per_1k_tokens: Decimal
    max_output_tokens: int
    context_window: int
    enabled: bool


class TierCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=100)
    upstream_model_id: str = Field(min_length=1, max_length=200)
    upstream_provider_name: str = Field(min_length=1, max_length=100)
    input_credits_per_1k_tokens: Decimal = Field(ge=0)
    output_credits_per_1k_tokens: Decimal = Field(ge=0)
    max_output_tokens: int = Field(gt=0)
    context_window: int = Field(gt=0)
    enabled: bool = True


class TierUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    upstream_model_id: str | None = Field(default=None, min_length=1, max_length=200)
    upstream_provider_name: str | None = Field(default=None, min_length=1, max_length=100)
    input_credits_per_1k_tokens: Decimal | None = Field(default=None, ge=0)
    output_credits_per_1k_tokens: Decimal | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    context_window: int | None = Field(default=None, gt=0)
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
