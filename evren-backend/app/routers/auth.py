from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.dependencies import get_current_user
from app.errors import ApiError
from app.models import User
from app.models.enums import EmailTokenPurpose
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordConfirmRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from app.security import sha256_hex
from app.services import auth_service
from app.services.rate_limiter import (
    check_rate_limit,
    register_failure,
    retry_after_if_blocked,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REGISTER_IP_LIMIT = 10
REGISTER_IP_WINDOW = 3600
LOGIN_IP_LIMIT = 30
LOGIN_IP_WINDOW = 60
LOGIN_ACCOUNT_FAILURES = 5
LOGIN_ACCOUNT_WINDOW = 300


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        status_code=429,
        message="Too many requests, please retry later",
        type="rate_limit_error",
        code="rate_limited",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request) -> UserResponse:
    redis = request.app.state.redis
    retry_after = await check_rate_limit(
        redis,
        key=f"rl:register:ip:{_client_ip(request)}",
        limit=REGISTER_IP_LIMIT,
        window_seconds=REGISTER_IP_WINDOW,
    )
    if retry_after is not None:
        raise _rate_limited(retry_after)

    database = request.app.state.database
    settings = request.app.state.settings
    user = await auth_service.register_user(
        database,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        admin_emails=settings.admin_emails,
    )
    token = await auth_service.create_email_token(database, user.id, EmailTokenPurpose.VERIFY_EMAIL)
    await request.app.state.email_sender.send(
        to=user.email,
        subject="Evren email verification",
        body=f"Use this token to verify your email (valid 24 hours): {token}",
    )
    return UserResponse.model_validate(user)


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    redis = request.app.state.redis
    database = request.app.state.database
    settings = request.app.state.settings

    retry_after = await check_rate_limit(
        redis,
        key=f"rl:login:ip:{_client_ip(request)}",
        limit=LOGIN_IP_LIMIT,
        window_seconds=LOGIN_IP_WINDOW,
    )
    if retry_after is not None:
        raise _rate_limited(retry_after)

    email_key = f"rl:login:acct:{sha256_hex(body.email.lower())}"
    retry_after = await retry_after_if_blocked(redis, key=email_key, limit=LOGIN_ACCOUNT_FAILURES)
    if retry_after is not None:
        raise _rate_limited(retry_after)

    user = await auth_service.authenticate_user(database, email=body.email, password=body.password)
    if user is None:
        await register_failure(redis, key=email_key, window_seconds=LOGIN_ACCOUNT_WINDOW)
        raise ApiError(
            status_code=401,
            message="Invalid email or password",
            type="authentication_error",
            code="invalid_credentials",
        )

    access_token, refresh_token, expires_in = await auth_service.issue_tokens(
        database, settings, user.id
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/refresh")
async def refresh(body: RefreshRequest, request: Request) -> TokenResponse:
    database = request.app.state.database
    settings = request.app.state.settings
    access_token, refresh_token, expires_in = await auth_service.rotate_refresh_token(
        database, settings, body.refresh_token
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/logout")
async def logout(body: RefreshRequest, request: Request) -> dict[str, bool]:
    await auth_service.revoke_refresh_token(request.app.state.database, body.refresh_token)
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    await auth_service.change_password(
        request.app.state.database,
        user,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return {"ok": True}


@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest, request: Request) -> dict[str, bool]:
    await auth_service.verify_email(request.app.state.database, body.token)
    return {"ok": True}


@router.post("/reset-password")
async def request_reset(body: ResetPasswordRequest, request: Request) -> dict[str, bool]:
    await auth_service.request_password_reset(
        request.app.state.database, request.app.state.email_sender, body.email
    )
    return {"ok": True}


@router.post("/reset-password/confirm")
async def confirm_reset(body: ResetPasswordConfirmRequest, request: Request) -> dict[str, bool]:
    await auth_service.confirm_password_reset(
        request.app.state.database, raw_token=body.token, new_password=body.new_password
    )
    return {"ok": True}
