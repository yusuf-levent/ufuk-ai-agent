"""Derive tier credit rates from upstream per-token prices.

The gateway bills in internal *credits*:

    credits = prompt_tokens * input_credits_per_1k / 1000
            + completion_tokens * output_credits_per_1k / 1000

This script converts upstream list prices (USD per 1M tokens) into the two
per-tier columns (`input_credits_per_1k_tokens`, `output_credits_per_1k_tokens`)
given a margin and a credits-per-USD exchange rate:

    input_credits_per_1k  = (usd_per_1m_in  / 1000) * credits_per_usd * (1 + margin)
    output_credits_per_1k = (usd_per_1m_out / 1000) * credits_per_usd * (1 + margin)

- `credits_per_usd` is a product decision: how many credits a paying user gets
  per dollar (e.g. 1000 -> one credit is worth $0.001 of upstream budget).
- `margin` (0.0 - 1.0+) covers tokenizer overhead vs. the upstream's own count,
  connection failures already refunded, payment processing and free usage.

IMPORTANT: never guess upstream prices. Either pass them explicitly (verified
on the provider's pricing page) or use `--source openrouter`, which reads the
live public model listing (GET https://openrouter.ai/api/v1/models — no API
key needed) and fails loudly when a tier's model id is missing.

Usage (from the backend root):
    # Live OpenRouter prices for the seeded tier aliases:
    python scripts/derive_credit_rates.py --source openrouter

    # Explicit prices (single tier):
    python scripts/derive_credit_rates.py \
        --input-usd-per-1m 0.15 --output-usd-per-1m 0.60 \
        --margin 0.3 --credits-per-usd 1000 --alias fast

    # multiple tiers at once (JSON list on stdout):
    python scripts/derive_credit_rates.py --tiers fast=0.15:0.60 balanced=0.50:2.00
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from decimal import ROUND_HALF_UP, Decimal

CREDIT_QUANTUM = Decimal("0.000001")  # same as app.services.credits

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Tier alias -> OpenRouter model id (verified against the public listing; see
# .env.example for the verification date). Used only with --source openrouter.
TIER_MODEL_IDS: dict[str, str] = {
    "fast": "deepseek/deepseek-v4-flash",
    "fast2": "deepseek/deepseek-v4.1-flash",
    "balanced": "google/gemma-4-31b-it",
    "balanced2": "qwen/qwen3.8-flash",
    "strong": "z-ai/glm-5.3",
    "strong2": "xiaomi/mimo-v2.6-pro",
}


def derive_rates(
    input_usd_per_1m: Decimal,
    output_usd_per_1m: Decimal,
    *,
    margin: Decimal,
    credits_per_usd: Decimal,
) -> tuple[Decimal, Decimal]:
    factor = credits_per_usd * (Decimal(1) + margin)
    input_rate = input_usd_per_1m / Decimal(1000) * factor
    output_rate = output_usd_per_1m / Decimal(1000) * factor
    return (
        input_rate.quantize(CREDIT_QUANTUM, rounding=ROUND_HALF_UP),
        output_rate.quantize(CREDIT_QUANTUM, rounding=ROUND_HALF_UP),
    )


def parse_tier_spec(spec: str) -> tuple[str, Decimal, Decimal]:
    alias, _, rest = spec.partition("=")
    try:
        in_price, out_price = rest.split(":")
        return alias.strip(), Decimal(in_price), Decimal(out_price)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"bad tier spec {spec!r}: expected alias=input_usd_per_1m:output_usd_per_1m"
        ) from exc


def fetch_openrouter_tier_prices() -> list[tuple[str, Decimal, Decimal]]:
    """Fetch live USD/1M prices for every tier in TIER_MODEL_IDS.

    Reads OpenRouter's public model listing (no API key). Fails loudly when a
    tier's model id is missing or carries no pricing, so a price is never
    silently defaulted or guessed.
    """
    with urllib.request.urlopen(OPENROUTER_MODELS_URL, timeout=30) as response:
        payload = json.loads(response.read().decode())
    by_id = {
        model.get("id"): model.get("pricing") or {}
        for model in payload.get("data", [])
        if isinstance(model.get("id"), str)
    }
    tiers: list[tuple[str, Decimal, Decimal]] = []
    missing: list[str] = []
    for alias, model_id in TIER_MODEL_IDS.items():
        pricing = by_id.get(model_id)
        prompt = pricing.get("prompt") if isinstance(pricing, dict) else None
        completion = pricing.get("completion") if isinstance(pricing, dict) else None
        if not isinstance(prompt, str) or not isinstance(completion, str):
            missing.append(f"{alias} ({model_id})")
            continue
        # OpenRouter prices are USD per token; scale to per 1M tokens.
        tiers.append(
            (
                alias,
                (Decimal(prompt) * Decimal(1_000_000)).quantize(Decimal("0.0001")),
                (Decimal(completion) * Decimal(1_000_000)).quantize(Decimal("0.0001")),
            )
        )
    if missing:
        raise SystemExit(
            "ERROR: no OpenRouter price found for: "
            + ", ".join(missing)
            + "\nVerify the model ids in TIER_MODEL_IDS against the listing."
        )
    return tiers


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--input-usd-per-1m", type=Decimal, help="upstream input price, USD per 1M tokens"
    )
    parser.add_argument(
        "--output-usd-per-1m", type=Decimal, help="upstream output price, USD per 1M tokens"
    )
    parser.add_argument(
        "--margin", type=Decimal, default=Decimal("0.3"), help="fraction, e.g. 0.3 = +30%%"
    )
    parser.add_argument(
        "--credits-per-usd", type=Decimal, default=Decimal("1000"), help="credits per USD"
    )
    parser.add_argument("--alias", default="fast", help="tier alias for the printed admin body")
    parser.add_argument("--display-name", default=None, help="display name (default: alias)")
    parser.add_argument(
        "--tiers",
        nargs="*",
        type=parse_tier_spec,
        default=[],
        help="multiple tiers: alias=input_usd_per_1m:output_usd_per_1m ...",
    )
    parser.add_argument(
        "--source",
        choices=["openrouter"],
        help="fetch live prices for the seeded tier aliases from OpenRouter's public listing",
    )
    args = parser.parse_args()

    tiers: list[tuple[str, Decimal, Decimal]] = list(args.tiers)
    if args.source == "openrouter":
        if tiers or args.input_usd_per_1m is not None:
            parser.error("--source openrouter cannot be combined with --tiers or explicit prices")
        tiers = fetch_openrouter_tier_prices()
    if args.input_usd_per_1m is not None and args.output_usd_per_1m is not None:
        tiers.append((args.alias, args.input_usd_per_1m, args.output_usd_per_1m))
    elif not tiers:
        parser.error(
            "pass --source openrouter, --input-usd-per-1m/--output-usd-per-1m, "
            "or --tiers alias=in:out"
        )

    results = []
    for alias, input_usd, output_usd in tiers:
        in_rate, out_rate = derive_rates(
            input_usd, output_usd, margin=args.margin, credits_per_usd=args.credits_per_usd
        )
        results.append(
            {
                "alias": alias,
                "display_name": args.display_name if len(tiers) == 1 else alias.title(),
                "input_credits_per_1k_tokens": str(in_rate),
                "output_credits_per_1k_tokens": str(out_rate),
            }
        )

    print(json.dumps(results, indent=2))
    print("\n# Apply with the admin API (rates take effect immediately):")
    print("#   PATCH http://localhost:8000/admin/tiers/<tier-id> with admin JWT, body:")
    for item in results:
        body = {
            "input_credits_per_1k_tokens": item["input_credits_per_1k_tokens"],
            "output_credits_per_1k_tokens": item["output_credits_per_1k_tokens"],
        }
        print(f"#   {json.dumps(body)}  # {item['alias']}")


if __name__ == "__main__":
    main()
