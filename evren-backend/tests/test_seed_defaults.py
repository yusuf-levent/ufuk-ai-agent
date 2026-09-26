"""Guards for the seeded tier/plan defaults.

Reasoning models spend the max_tokens budget on chain-of-thought before any
content is produced, so per-tier ceilings must stay generous
(fast/balanced 8192, strong 16384) and plan caps must never silently clamp
them below the tier ceiling.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seed.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("evren_seed_defaults", SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_tier_ceilings_match_reasoning_model_needs() -> None:
    seed = _load_seed_module()
    assert seed.DEFAULT_TIERS["fast"]["max_output_tokens"] == 8192
    assert seed.DEFAULT_TIERS["balanced"]["max_output_tokens"] == 8192
    assert seed.DEFAULT_TIERS["strong"]["max_output_tokens"] == 16384


def test_seed_plan_caps_never_clamp_tier_ceilings() -> None:
    seed = _load_seed_module()
    for plan in seed.DEFAULT_PLANS.values():
        for alias in plan["allowed_tier_aliases"]:
            assert (
                plan["max_output_tokens_per_request"]
                >= seed.DEFAULT_TIERS[alias]["max_output_tokens"]
            ), f"plan cap would clamp tier '{alias}' below its ceiling"
