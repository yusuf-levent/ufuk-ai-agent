from __future__ import annotations

import uuid
from datetime import timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.models import EmailToken, RefreshToken, User
from app.models.base import utcnow
from app.models.enums import EmailTokenPurpose, UserRole
from app.security import (
    create_access_token,
    generate_token,
    hash_password,
    sha256_hex,
    verify_password,
)
from app.services.email import EmailSender
from app.services.subscriptions import ensure_default_subscription

logger = structlog.get_logger(__name__)

REFRESH_TOKEN_TTL = timedelta(days=30)
EMAIL_TOKEN_TTL = timedelta(hours=24)
RESET_TOKEN_TTL = timedelta(hours=1)


def _auth_error(message: str, code: str) -> ApiError:
    return ApiError(status_code=401, message=message, type="authentication_error", code=code)


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(db: Database, email: str) -> User | None:
    async with db.session() as session:
        user: User | None = await session.scalar(
            select(User).where(User.email == normalize_email(email))
        )
        return user


async def register_user(
    db: Database,
    *,
    email: str,
    password: str,
    display_name: str | None,
    admin_emails: list[str],
) -> User:
    normalized = normalize_email(email)
    role = UserRole.ADMIN if normalized in {e.lower() for e in admin_emails} else UserRole.USER
    user = User(
        email=normalized,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
    )
    try:
        async with db.session() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
    except IntegrityError as exc:
        raise ApiError(
            status_code=400,
            message="Unable to complete registration with this email",
            type="invalid_request_error",
            code="registration_failed",
        ) from exc
    logger.info("user_registered", user_id=str(user.id), role=role.value)
    await ensure_default_subscription(db, user.id)
    return user


async def authenticate_user(db: Database, *, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


async def issue_tokens(
    db: Database, settings: Settings, user_id: uuid.UUID
) -> tuple[str, str, int]:
    access_token, _ = create_access_token(settings, user_id)
    refresh_token = generate_token()
    async with db.session() as session:
        session.add(
            RefreshToken(
                user_id=user_id,
                token_hash=sha256_hex(refresh_token),
                expires_at=utcnow() + REFRESH_TOKEN_TTL,
            )
        )
        await session.commit()
    return access_token, refresh_token, settings.access_token_ttl_seconds


async def rotate_refresh_token(
    db: Database, settings: Settings, refresh_token: str
) -> tuple[str, str, int]:
    token_hash = sha256_hex(refresh_token)
    now = utcnow()
    async with db.session() as session:
        row = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        if row is None:
            raise _auth_error("Invalid refresh token", "invalid_refresh_token")
        if row.revoked_at is not None:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await session.commit()
            logger.warning("refresh_token_reuse_detected", user_id=str(row.user_id))
            raise _auth_error(
                "Refresh token reuse detected; all sessions were revoked",
                "refresh_token_reused",
            )
        if row.expires_at < now:
            raise _auth_error("Refresh token expired", "invalid_refresh_token")

        user = await session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise _auth_error("Invalid refresh token", "invalid_refresh_token")

        new_refresh_token = generate_token()
        new_row = RefreshToken(
            user_id=row.user_id,
            token_hash=sha256_hex(new_refresh_token),
            expires_at=now + REFRESH_TOKEN_TTL,
        )
        session.add(new_row)
        await session.flush()
        row.revoked_at = now
        row.replaced_by = new_row.id
        await session.commit()
        user_id = row.user_id

    access_token, _ = create_access_token(settings, user_id)
    return access_token, new_refresh_token, settings.access_token_ttl_seconds


async def revoke_refresh_token(db: Database, refresh_token: str) -> None:
    token_hash = sha256_hex(refresh_token)
    async with db.session() as session:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await session.commit()


async def revoke_all_user_tokens(db: Database, user_id: uuid.UUID) -> None:
    async with db.session() as session:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await session.commit()


async def change_password(
    db: Database, user: User, *, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise _auth_error("Current password is incorrect", "invalid_credentials")
    async with db.session() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(password_hash=hash_password(new_password))
        )
        await session.commit()
    await revoke_all_user_tokens(db, user.id)
    logger.info("password_changed", user_id=str(user.id))


async def create_email_token(db: Database, user_id: uuid.UUID, purpose: EmailTokenPurpose) -> str:
    token = generate_token()
    ttl = EMAIL_TOKEN_TTL if purpose == EmailTokenPurpose.VERIFY_EMAIL else RESET_TOKEN_TTL
    async with db.session() as session:
        session.add(
            EmailToken(
                user_id=user_id,
                token_hash=sha256_hex(token),
                purpose=purpose,
                expires_at=utcnow() + ttl,
            )
        )
        await session.commit()
    return token


async def consume_email_token(
    db: Database, raw_token: str, purpose: EmailTokenPurpose
) -> uuid.UUID:
    token_hash = sha256_hex(raw_token)
    now = utcnow()
    async with db.session() as session:
        row = await session.scalar(
            select(EmailToken).where(
                EmailToken.token_hash == token_hash, EmailToken.purpose == purpose
            )
        )
        if row is None or row.used_at is not None or row.expires_at < now:
            raise ApiError(
                status_code=400,
                message="Invalid or expired token",
                type="invalid_request_error",
                code="invalid_token",
            )
        row.used_at = now
        await session.commit()
        return row.user_id


async def verify_email(db: Database, raw_token: str) -> None:
    user_id = await consume_email_token(db, raw_token, EmailTokenPurpose.VERIFY_EMAIL)
    async with db.session() as session:
        await session.execute(update(User).where(User.id == user_id).values(email_verified=True))
        await session.commit()
    logger.info("email_verified", user_id=str(user_id))


async def request_password_reset(db: Database, email_sender: EmailSender, email: str) -> None:
    user = await get_user_by_email(db, email)
    if user is None:
        return
    token = await create_email_token(db, user.id, EmailTokenPurpose.RESET_PASSWORD)
    await email_sender.send(
        to=user.email,
        subject="Evren password reset",
        body=f"Use this token to reset your password (valid 1 hour): {token}",
    )


async def confirm_password_reset(db: Database, *, raw_token: str, new_password: str) -> None:
    user_id = await consume_email_token(db, raw_token, EmailTokenPurpose.RESET_PASSWORD)
    async with db.session() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(password_hash=hash_password(new_password))
        )
        await session.commit()
    await revoke_all_user_tokens(db, user_id)
    logger.info("password_reset_completed", user_id=str(user_id))
