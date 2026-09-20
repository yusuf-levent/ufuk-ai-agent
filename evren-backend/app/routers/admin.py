from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import require_admin
from app.errors import ApiError
from app.models import ModelTier, Plan, User
from app.schemas.plans import (
    AdminUsageResponse,
    AssignPlanRequest,
    PlanCreate,
    PlanResponse,
    PlanUpdate,
    SubscriptionResponse,
    TierCreate,
    TierResponse,
    TierUpdate,
    TierUsageResponse,
)
from app.services import subscriptions as subscription_service
from app.services import usage_service
from app.services.tiers import invalidate_tier

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(request: Request) -> list[PlanResponse]:
    database = request.app.state.database
    async with database.session() as session:
        plans = (
            (await session.execute(select(Plan).order_by(Plan.monthly_credit_limit)))
            .scalars()
            .all()
        )
    return [PlanResponse.model_validate(plan) for plan in plans]


async def _get_plan_or_404(request: Request, plan_id: uuid.UUID) -> Plan:
    database = request.app.state.database
    async with database.session() as session:
        plan: Plan | None = await session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(body: PlanCreate, request: Request) -> PlanResponse:
    database = request.app.state.database
    try:
        async with database.session() as session:
            if body.is_default:
                await _clear_default_flag(session)
            plan = Plan(**body.model_dump())
            session.add(plan)
            await session.commit()
            await session.refresh(plan)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan '{body.name}' already exists",
        ) from exc
    return PlanResponse.model_validate(plan)


@router.patch("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(plan_id: uuid.UUID, body: PlanUpdate, request: Request) -> PlanResponse:
    database = request.app.state.database
    values = body.model_dump(exclude_unset=True)
    async with database.session() as session:
        plan = await session.get(Plan, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        if values.get("is_default"):
            await _clear_default_flag(session)
        for field, value in values.items():
            setattr(plan, field, value)
        await session.commit()
        await session.refresh(plan)
    return PlanResponse.model_validate(plan)


async def _clear_default_flag(session: AsyncSession) -> None:
    await session.execute(update(Plan).values(is_default=False))


@router.get("/tiers", response_model=list[TierResponse])
async def list_tiers(request: Request) -> list[TierResponse]:
    database = request.app.state.database
    async with database.session() as session:
        tiers = (await session.execute(select(ModelTier).order_by(ModelTier.alias))).scalars().all()
    return [TierResponse.model_validate(tier) for tier in tiers]


@router.post("/tiers", response_model=TierResponse, status_code=status.HTTP_201_CREATED)
async def create_tier(body: TierCreate, request: Request) -> TierResponse:
    database = request.app.state.database
    try:
        async with database.session() as session:
            tier = ModelTier(**body.model_dump())
            session.add(tier)
            await session.commit()
            await session.refresh(tier)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tier '{body.alias}' already exists",
        ) from exc
    await invalidate_tier(request.app.state.redis, body.alias)
    return TierResponse.model_validate(tier)


@router.patch("/tiers/{tier_id}", response_model=TierResponse)
async def update_tier(tier_id: uuid.UUID, body: TierUpdate, request: Request) -> TierResponse:
    database = request.app.state.database
    values = body.model_dump(exclude_unset=True)
    async with database.session() as session:
        tier = await session.get(ModelTier, tier_id)
        if tier is None:
            raise HTTPException(status_code=404, detail="Tier not found")
        for field, value in values.items():
            setattr(tier, field, value)
        await session.commit()
        await session.refresh(tier)
    await invalidate_tier(request.app.state.redis, tier.alias)
    return TierResponse.model_validate(tier)


@router.post(
    "/users/{user_id}/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_plan_to_user(
    user_id: uuid.UUID, body: AssignPlanRequest, request: Request
) -> SubscriptionResponse:
    database = request.app.state.database
    async with database.session() as session:
        user = await session.get(User, user_id)
        plan = await session.get(Plan, body.plan_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    subscription = await subscription_service.assign_plan(database, user_id, body.plan_id)
    return SubscriptionResponse.model_validate(subscription)


@router.get("/users/{user_id}/usage", response_model=AdminUsageResponse)
async def user_usage(user_id: uuid.UUID, request: Request) -> AdminUsageResponse:
    database = request.app.state.database
    active = await subscription_service.get_active_subscription(database, user_id)
    if active is None:
        raise ApiError(
            status_code=404,
            message="No active subscription for this user",
            type="invalid_request_error",
            code="subscription_inactive",
        )
    usage = await usage_service.period_usage(
        database, user_id, active.period_start, active.period_end
    )
    used = usage_service.total_credits(usage)
    return AdminUsageResponse(
        user_id=user_id,
        period_start=active.period_start,
        period_end=active.period_end,
        plan_name=active.plan.name,
        credit_limit=active.plan.monthly_credit_limit,
        credits_used=used,
        per_tier=[TierUsageResponse(**asdict(item)) for item in usage],
    )


@router.get("/users")
async def list_users(request: Request) -> list[dict[str, object]]:
    database = request.app.state.database
    async with database.session() as session:
        users = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    return [
        {
            "id": str(user.id),
            "email": user.email,
            "role": user.role.value,
            "is_active": user.is_active,
        }
        for user in users
    ]
