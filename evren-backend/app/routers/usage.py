from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_current_user
from app.errors import ApiError
from app.models import User
from app.schemas.plans import TierUsageResponse
from app.services import subscriptions as subscription_service
from app.services import usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
async def get_usage(request: Request, user: User = Depends(get_current_user)) -> dict[str, object]:
    database = request.app.state.database
    active = await subscription_service.get_active_subscription(database, user.id)
    if active is None:
        raise ApiError(
            status_code=403,
            message="No active subscription",
            type="permission_error",
            code="subscription_inactive",
        )
    usage = await usage_service.period_usage(
        database, user.id, active.period_start, active.period_end
    )
    used = usage_service.total_credits(usage)
    remaining = max(
        active.plan.monthly_credit_limit - used,
        type(active.plan.monthly_credit_limit)("0"),
    )
    return {
        "period_start": active.period_start,
        "period_end": active.period_end,
        "plan_name": active.plan.name,
        "credit_limit": active.plan.monthly_credit_limit,
        "credits_used": used,
        "credits_remaining": remaining,
        "requests_per_minute": active.plan.requests_per_minute,
        "per_tier": [TierUsageResponse(**asdict(item)) for item in usage],
    }
