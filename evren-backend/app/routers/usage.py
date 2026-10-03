from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_current_user
from app.errors import ApiError
from app.models import User
from app.schemas.plans import TierUsageResponse
from app.services import subscriptions as subscription_service
from app.services import usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


def _window_share(total: Decimal, divisor: float) -> Decimal:
    """Spread a period limit evenly across `divisor` sub-windows (pacing)."""
    return Decimal(str(round(float(total) / divisor, 6)))


def _window_block(used: Decimal, share: Decimal) -> dict[str, object]:
    """Remaining percentage for one pacing window (0-100, never negative)."""
    share_f = float(share)
    used_f = float(used)
    if share_f <= 0:
        remaining_pct = 0.0
    else:
        remaining_pct = max(0.0, min(100.0, (share_f - used_f) / share_f * 100.0))
    return {
        "used": str(used),
        "limit": str(share),
        "remaining_pct": round(remaining_pct, 1),
    }


@router.get("")
async def get_usage(request: Request, user: User = Depends(get_current_user)) -> dict[str, object]:
    database = request.app.state.database
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
    usage = await usage_service.period_usage(
        database, user.id, active.period_start, active.period_end
    )
    used = usage_service.total_credits(usage)
    remaining = max(
        active.plan.monthly_credit_limit - used,
        type(active.plan.monthly_credit_limit)("0"),
    )

    # Daily / weekly pacing windows: the period limit spread evenly across the
    # period's days and weeks. The UI shows only remaining percentages for
    # these — raw credit counts are never surfaced to the user.
    now = datetime.now(UTC)
    period_days = max(1.0, (active.period_end - active.period_start) / timedelta(days=1))
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    daily_used = usage_service.total_credits(
        await usage_service.period_usage(database, user.id, day_start, now)
    )
    weekly_used = usage_service.total_credits(
        await usage_service.period_usage(database, user.id, week_start, now)
    )
    daily_share = _window_share(active.plan.monthly_credit_limit, period_days)
    weekly_share = _window_share(active.plan.monthly_credit_limit, period_days / 7.0)

    return {
        "period_start": active.period_start,
        "period_end": active.period_end,
        "period_key": active.period_key,
        "plan_name": active.plan.name,
        "credit_limit": active.plan.monthly_credit_limit,
        "credits_used": used,
        "credits_remaining": remaining,
        # Quota policy surfaced to the UI: unused credits never roll over —
        # each billing period starts with the plan's full limit.
        "rolls_over": False,
        "reset_at": active.period_end,
        "requests_per_minute": active.plan.requests_per_minute,
        # Pacing windows: remaining percentage only (0-100).
        "daily": _window_block(daily_used, daily_share),
        "weekly": _window_block(weekly_used, weekly_share),
        "period": _window_block(used, active.plan.monthly_credit_limit),
        "per_tier": [TierUsageResponse(**asdict(item)) for item in usage],
    }
