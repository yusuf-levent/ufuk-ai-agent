from __future__ import annotations

import jwt as pyjwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.models import User
from app.models.enums import UserRole
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def app_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


async def get_current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(
            status_code=401,
            message="Missing bearer token",
            type="authentication_error",
            code="invalid_api_key",
        )
    settings: Settings = request.app.state.settings
    try:
        user_id = decode_access_token(settings, credentials.credentials)
    except pyjwt.ExpiredSignatureError as exc:
        raise ApiError(
            status_code=401,
            message="Access token expired",
            type="authentication_error",
            code="token_expired",
        ) from exc
    except pyjwt.PyJWTError as exc:
        raise ApiError(
            status_code=401,
            message="Invalid access token",
            type="authentication_error",
            code="invalid_api_key",
        ) from exc
    database: Database = request.app.state.database
    async with database.session() as session:
        user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise ApiError(
            status_code=401,
            message="Invalid access token",
            type="authentication_error",
            code="invalid_api_key",
        )
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise ApiError(
            status_code=403,
            message="Admin access required",
            type="permission_error",
            code="forbidden",
        )
    return user
