from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)
    # Contractual account-sharing deterrent: the client must record that the
    # user accepted the terms ("you may not share your account with anyone").
    accept_terms: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class OAuthLoginRequest(BaseModel):
    """Exchange a provider authorization code for a Ufuk session.

    The desktop app hands the `code` it received on the `ufuk://auth/callback`
    deep link; the server swaps it for the provider's id token, verifies it and
    provisions (or links) the matching Ufuk account.
    """

    provider: Literal["google", "apple"]
    code: str = Field(min_length=1, max_length=2048)
    # Apple only: the user's name from the first consent, which Apple sends
    # once and never again. Optional and cosmetic.
    display_name: str | None = Field(default=None, max_length=100)


class OAuthProviderInfo(BaseModel):
    id: Literal["google", "apple"]
    label: str
    authorize_url: str


class OAuthProvidersResponse(BaseModel):
    providers: list[OAuthProviderInfo]
    redirect_uri: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class ResetPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordConfirmRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str | None
    role: UserRole
    email_verified: bool
    created_at: datetime
    terms_accepted_at: datetime | None = None
    terms_version: str | None = None
