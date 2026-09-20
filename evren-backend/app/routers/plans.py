from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.models import Plan
from app.schemas.plans import PlanResponse

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PlanResponse])
async def list_plans(request: Request) -> list[PlanResponse]:
    database = request.app.state.database
    async with database.session() as session:
        plans = (
            (await session.execute(select(Plan).order_by(Plan.monthly_credit_limit)))
            .scalars()
            .all()
        )
    return [PlanResponse.model_validate(plan) for plan in plans]
