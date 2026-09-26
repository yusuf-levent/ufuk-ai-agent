from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, update

from app.dependencies import get_current_user
from app.errors import ApiError
from app.models import EmailToken, RefreshToken, Subscription, UsageEvent, User
from app.schemas.auth import DeleteAccountRequest, UserResponse
from app.security import verify_password

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.delete("/me")
async def delete_me(
    body: DeleteAccountRequest, request: Request, user: User = Depends(get_current_user)
) -> dict[str, bool]:
    if not verify_password(body.password, user.password_hash):
        raise ApiError(
            status_code=401,
            message="Invalid email or password",
            type="authentication_error",
            code="invalid_credentials",
        )
    database = request.app.state.database
    redis = request.app.state.redis
    async with database.session() as session:
        await session.execute(
            update(UsageEvent).where(UsageEvent.user_id == user.id).values(user_id=None)
        )
        await session.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
        await session.execute(delete(EmailToken).where(EmailToken.user_id == user.id))
        await session.execute(delete(Subscription).where(Subscription.user_id == user.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()
    user_keys = [key async for key in redis.scan_iter(match=f"credits:{user.id}:*")] + [
        key async for key in redis.scan_iter(match=f"rpm:{user.id}:*")
    ]
    if user_keys:
        await redis.delete(*user_keys)
    return {"ok": True}
