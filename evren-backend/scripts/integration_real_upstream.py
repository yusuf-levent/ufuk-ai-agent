"""Optional manual integration check against the REAL upstream provider.

Uses env config only (UPSTREAM_BASE_URL, UPSTREAM_API_KEY, UPSTREAM_AUTH_HEADER).
Never run in CI; run it by hand when the upstream changes:

    python scripts/integration_real_upstream.py                # list models
    python scripts/integration_real_upstream.py --chat "hi"    # tiny completion
    python scripts/integration_real_upstream.py --chat "hi" --stream
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app.config import get_settings


def auth_headers(settings) -> dict[str, str]:
    key = settings.upstream_api_key.get_secret_value()
    if settings.upstream_auth_header == "X-API-Key":
        return {"X-API-Key": key}
    return {"Authorization": f"Bearer {key}"}


async def list_models(client: httpx.AsyncClient, settings) -> None:
    response = await client.get(
        f"{settings.upstream_base_url}/models", headers=auth_headers(settings)
    )
    print(f"GET /models -> {response.status_code}")
    if response.status_code != 200:
        print(response.text[:500])
        return
    data = response.json()
    for model in data.get("data", []):
        print(f"  {model.get('id')}")


async def chat(
    client: httpx.AsyncClient, settings, *, prompt: str, model: str | None, stream: bool
) -> None:
    payload: dict[str, object] = {
        "model": model or "glm-5.3",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
        async with client.stream(
            "POST",
            f"{settings.upstream_base_url}/chat/completions",
            json=payload,
            headers=auth_headers(settings),
            timeout=settings.upstream_timeout_seconds,
        ) as response:
            print(f"POST /chat/completions (stream) -> {response.status_code}")
            if response.status_code != 200:
                print((await response.aread()).decode()[:500])
                return
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    usage = chunk.get("usage")
                    if usage:
                        print(f"  usage: {usage}")
                    else:
                        choices = chunk.get("choices") or []
                        if choices and choices[0].get("delta", {}).get("content"):
                            print(f"  delta: {choices[0]['delta']['content']!r}")
        print("  stream done")
    else:
        response = await client.post(
            f"{settings.upstream_base_url}/chat/completions",
            json=payload,
            headers=auth_headers(settings),
            timeout=settings.upstream_timeout_seconds,
        )
        print(f"POST /chat/completions -> {response.status_code}")
        if response.status_code != 200:
            print(response.text[:500])
            return
        data = response.json()
        print(f"  model: {data.get('model')}")
        print(f"  usage: {data.get('usage')}")
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
        print(f"  content: {content!r}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat", metavar="PROMPT", help="run a tiny chat completion")
    parser.add_argument("--model", help="upstream model id (default: glm-5.3)")
    parser.add_argument("--stream", action="store_true", help="use streaming")
    args = parser.parse_args()

    settings = get_settings()
    print(f"upstream: {settings.upstream_base_url} (auth header: {settings.upstream_auth_header})")
    async with httpx.AsyncClient() as client:
        await list_models(client, settings)
        if args.chat:
            await chat(client, settings, prompt=args.chat, model=args.model, stream=args.stream)


if __name__ == "__main__":
    asyncio.run(main())
