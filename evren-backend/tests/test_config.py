from __future__ import annotations

import pytest
from app.config import Settings
from pydantic import ValidationError

SECRET = "x" * 32


def make_settings(**kwargs: object) -> Settings:
    values: dict[str, object] = {
        "upstream_api_key": "upstream-key",
        "jwt_secret": SECRET,
    }
    values.update(kwargs)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_defaults() -> None:
    settings = make_settings()
    assert settings.upstream_base_url == "https://evren-llmapi.ssyz.org.tr/v1"
    assert settings.upstream_auth_header == "Authorization"
    assert settings.upstream_timeout_seconds == 300.0
    assert settings.access_token_ttl_seconds == 900
    assert settings.environment == "dev"
    assert settings.request_max_body_bytes == 10 * 1024 * 1024


def test_trailing_slash_stripped() -> None:
    settings = make_settings(upstream_base_url="https://example.com/v1/")
    assert settings.upstream_base_url == "https://example.com/v1"


def test_short_jwt_secret_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(jwt_secret="short")


def test_invalid_auth_header_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(upstream_auth_header="X-Weird")


def test_negative_ttl_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(access_token_ttl_seconds=-1)


def test_secrets_hidden_in_repr() -> None:
    settings = make_settings(upstream_api_key="super-secret-upstream-key", jwt_secret="z" * 40)
    dumped = repr(settings) + str(settings.model_dump())
    assert "super-secret-upstream-key" not in dumped
    assert "zzzzzzzzzz" not in dumped
