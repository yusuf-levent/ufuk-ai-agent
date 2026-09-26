from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.models import ModelTier

router = APIRouter(prefix="/privacy", tags=["privacy"])


@router.get("/info")
async def privacy_info(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    database = request.app.state.database
    async with database.session() as session:
        provider_rows = (
            await session.execute(
                select(ModelTier.upstream_provider_name)
                .where(ModelTier.enabled.is_(True))
                .distinct()
                .order_by(ModelTier.upstream_provider_name)
            )
        ).scalars()
        providers = list(provider_rows)
    return {
        "upstream_base_url_host": urlparse(settings.upstream_base_url).hostname,
        "upstream_providers": providers,
        "data_handling": (
            "Prompts and completions are proxied to the upstream provider listed above "
            "and are never stored or logged by this gateway. Only usage metadata "
            "(token counts, tier, latency, status, request id) is retained for billing."
        ),
        "account_deletion": (
            "Deleting your account removes your profile, sessions and subscriptions; "
            "usage rows are anonymized (user reference removed). See docs/privacy-rules.md."
        ),
    }
