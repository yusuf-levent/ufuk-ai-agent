"""Google / Apple federated sign-in.

Flow (authorization code + PKCE-less, desktop app):

1. ``GET /auth/oauth/providers`` lists the configured providers and the
   authorize URL each one expects. The desktop app opens that URL in the
   system browser.
2. The user consents; the provider redirects to ``oauth_redirect_uri``
   (``ufuk://auth/callback``) carrying a one-time ``code``.
3. ``POST /auth/oauth/login`` exchanges the code at the provider's token
   endpoint, verifies the resulting id token signature and claims, then finds
   or creates the matching Ufuk account and issues the usual token pair.

Only the id token's ``sub``, ``email`` and ``email_verified`` claims are used.
The provider's tokens are never stored.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
import structlog
from sqlalchemy import select

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.models import User
from app.models.base import utcnow
from app.models.enums import UserRole
from app.services.auth_service import normalize_email
from app.services.subscriptions import ensure_default_subscription

logger = structlog.get_logger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
APPLE_AUTH_ENDPOINT = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_ENDPOINT = "https://appleid.apple.com/auth/token"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"

PROVIDER_LABELS = {"google": "Google", "apple": "Apple"}


@dataclass(frozen=True)
class OAuthIdentity:
    """Verified identity claims from a provider id token."""

    subject: str
    email: str
    display_name: str | None


def _oauth_not_configured(provider: str) -> ApiError:
    return ApiError(
        status_code=503,
        message=f"{PROVIDER_LABELS.get(provider, provider)} sign-in is not configured",
        type="invalid_request_error",
        code="oauth_not_configured",
    )


def _oauth_failed(message: str = "Could not sign in with this account") -> ApiError:
    return ApiError(
        status_code=401,
        message=message,
        type="authentication_error",
        code="oauth_failed",
    )


def configured_providers(settings: Settings) -> list[str]:
    """Provider ids that have a client id configured (and thus can be offered)."""
    providers: list[str] = []
    if settings.google_client_id:
        providers.append("google")
    if settings.apple_client_id:
        providers.append("apple")
    return providers


def build_authorize_url(settings: Settings, provider: str) -> str:
    """The provider consent URL the desktop app should open in the browser."""
    if provider == "google":
        if not settings.google_client_id:
            raise _oauth_not_configured(provider)
        query = urlencode(
            {
                "client_id": settings.google_client_id,
                "redirect_uri": settings.oauth_redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "prompt": "select_account",
            }
        )
        return f"{GOOGLE_AUTH_ENDPOINT}?{query}"

    if provider == "apple":
        if not settings.apple_client_id:
            raise _oauth_not_configured(provider)
        query = urlencode(
            {
                "client_id": settings.apple_client_id,
                "redirect_uri": settings.oauth_redirect_uri,
                "response_type": "code",
                "scope": "name email",
                "response_mode": "query",
                "prompt": "login",
            }
        )
        return f"{APPLE_AUTH_ENDPOINT}?{query}"

    raise ApiError(
        status_code=400,
        message=f"Unknown sign-in provider '{provider}'",
        type="invalid_request_error",
        code="unknown_oauth_provider",
    )


def _apple_client_secret(settings: Settings) -> str:
    """Apple's client secret: a prebuilt ES256 JWT or one minted from the key."""
    if settings.apple_client_secret:
        return settings.apple_client_secret.get_secret_value()

    missing = [
        name
        for name, value in (
            ("APPLE_TEAM_ID", settings.apple_team_id),
            ("APPLE_KEY_ID", settings.apple_key_id),
            ("APPLE_PRIVATE_KEY", settings.apple_private_key),
        )
        if not value
    ]
    if missing:
        raise _oauth_not_configured("apple")

    now = int(time.time())
    private_key = settings.apple_private_key
    if private_key is None:
        raise _oauth_not_configured("apple")
    return jwt.encode(
        {
            "iss": settings.apple_team_id,
            "iat": now,
            "exp": now + 600,
            "aud": "https://appleid.apple.com",
            "sub": settings.apple_client_id,
        },
        private_key.get_secret_value(),
        algorithm="ES256",
        headers={"kid": settings.apple_key_id},
    )


async def _fetch_provider_keys(client: httpx.AsyncClient, jwks_url: str) -> dict[str, object]:
    response = await client.get(jwks_url, timeout=15)
    response.raise_for_status()
    payload = response.json()
    keys: dict[str, object] = {}
    for jwk in payload.get("keys", []):
        kid = jwk.get("kid")
        if kid:
            keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
    return keys


async def _verify_id_token(
    client: httpx.AsyncClient,
    *,
    id_token: str,
    jwks_url: str,
    audience: str,
    issuer: str,
) -> dict[str, object]:
    """Verify the id token's signature and standard claims, returning its payload."""
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        logger.warning("oauth_id_token_malformed", error=str(exc))
        raise _oauth_failed() from exc

    keys = await _fetch_provider_keys(client, jwks_url)
    key = keys.get(header.get("kid", ""))
    if key is None:
        # Keys may have rotated since the last fetch; retry once.
        keys = await _fetch_provider_keys(client, jwks_url)
        key = keys.get(header.get("kid", ""))
    if key is None:
        logger.warning("oauth_id_token_unknown_kid", kid=header.get("kid"))
        raise _oauth_failed()

    try:
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("oauth_id_token_invalid", error=str(exc))
        raise _oauth_failed() from exc

    email = claims.get("email")
    if not isinstance(email, str) or not email:
        raise _oauth_failed("The account did not share an email address.")
    # Providers only guarantee `email_verified` as a string on some flows.
    if str(claims.get("email_verified", "")).lower() not in ("true", "1"):
        raise _oauth_failed("The email address is not verified with the provider.")

    name = claims.get("name")
    display_name = name if isinstance(name, str) and name else None
    return {
        "subject": str(claims["sub"]),
        "email": email,
        "display_name": display_name,
    }


async def _exchange_google_code(
    client: httpx.AsyncClient, settings: Settings, code: str
) -> dict[str, object]:
    response = await client.post(
        GOOGLE_TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value()
            if settings.google_client_secret
            else "",
            "redirect_uri": settings.oauth_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if response.status_code != 200:
        logger.warning("oauth_google_exchange_failed", status=response.status_code)
        raise _oauth_failed()
    payload = response.json()
    id_token = payload.get("id_token")
    if not isinstance(id_token, str):
        raise _oauth_failed()
    return await _verify_id_token(
        client,
        id_token=id_token,
        jwks_url=GOOGLE_JWKS_URL,
        audience=settings.google_client_id or "",
        issuer="https://accounts.google.com",
    )


async def _exchange_apple_code(
    client: httpx.AsyncClient, settings: Settings, code: str
) -> dict[str, object]:
    response = await client.post(
        APPLE_TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": settings.apple_client_id,
            "client_secret": _apple_client_secret(settings),
            "redirect_uri": settings.oauth_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if response.status_code != 200:
        logger.warning("oauth_apple_exchange_failed", status=response.status_code)
        raise _oauth_failed()
    payload = response.json()
    id_token = payload.get("id_token")
    if not isinstance(id_token, str):
        raise _oauth_failed()
    return await _verify_id_token(
        client,
        id_token=id_token,
        jwks_url=APPLE_JWKS_URL,
        audience=settings.apple_client_id or "",
        issuer="https://appleid.apple.com",
    )


async def resolve_identity(
    settings: Settings, provider: str, code: str
) -> OAuthIdentity:
    """Exchange the authorization code and return the verified identity."""
    if provider not in PROVIDER_LABELS:
        raise ApiError(
            status_code=400,
            message=f"Unknown sign-in provider '{provider}'",
            type="invalid_request_error",
            code="unknown_oauth_provider",
        )

    async with httpx.AsyncClient() as client:
        if provider == "google":
            if not settings.google_client_id or not settings.google_client_secret:
                raise _oauth_not_configured(provider)
            claims = await _exchange_google_code(client, settings, code)
        else:
            if not settings.apple_client_id:
                raise _oauth_not_configured(provider)
            claims = await _exchange_apple_code(client, settings, code)

    return OAuthIdentity(
        subject=str(claims["subject"]),
        email=normalize_email(str(claims["email"])),
        display_name=claims["display_name"] if isinstance(claims["display_name"], str) else None,
    )


async def find_or_create_user(
    db: Database,
    settings: Settings,
    *,
    provider: str,
    identity: OAuthIdentity,
    display_name_override: str | None = None,
    accept_terms: bool = True,
) -> User:
    """Link the provider identity to an existing account or provision a new one."""
    normalized = normalize_email(identity.email)
    display_name = display_name_override or identity.display_name

    async with db.session() as session:
        user: User | None = await session.scalar(
            select(User).where(
                User.auth_provider == provider,
                User.provider_subject == identity.subject,
            )
        )
        if user is None:
            # Same email already registered with a password (or another
            # provider): link this identity to that account rather than
            # creating a duplicate. The provider already proved ownership of
            # the address (email_verified), so this is safe to auto-link.
            user = await session.scalar(select(User).where(User.email == normalized))

        if user is not None:
            if not user.is_active:
                raise _oauth_failed("This account has been disabled.")
            changed = False
            if user.auth_provider is None and user.provider_subject is None:
                user.auth_provider = provider
                user.provider_subject = identity.subject
                changed = True
            elif user.auth_provider != provider or user.provider_subject != identity.subject:
                # The email is already bound to a different federated identity.
                logger.warning(
                    "oauth_identity_conflict",
                    user_id=str(user.id),
                    provider=provider,
                )
                raise _oauth_failed("This email is already linked to a different sign-in method.")
            if display_name and not user.display_name:
                user.display_name = display_name
                changed = True
            if user.auth_provider == provider and not user.email_verified:
                user.email_verified = True
                changed = True
            if changed:
                await session.commit()
                await session.refresh(user)
            return user

        role = (
            UserRole.ADMIN
            if normalized in {e.lower() for e in settings.admin_emails}
            else UserRole.USER
        )
        user = User(
            email=normalized,
            password_hash=None,
            display_name=display_name,
            role=role,
            auth_provider=provider,
            provider_subject=identity.subject,
            email_verified=True,
            terms_accepted_at=utcnow() if accept_terms else None,
            terms_version="2026-10" if accept_terms else None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    logger.info(
        "user_registered_oauth", user_id=str(user.id), provider=provider, role=user.role.value
    )
    await ensure_default_subscription(db, user.id)
    return user


__all__ = [
    "PROVIDER_LABELS",
    "OAuthIdentity",
    "build_authorize_url",
    "configured_providers",
    "find_or_create_user",
    "resolve_identity",
]
