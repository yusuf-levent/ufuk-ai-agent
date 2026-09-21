# Ufuk — Progress

## 2026-09-21 — Milestone 1: Backend fixes

**Baseline before:** agent 188 tests / backend 100 tests, all green
(verified fresh, see docs/STATUS.md).

### What was done

1. **Plan change no longer resets usage counters.** `assign_plan`
   (evren-backend/app/services/subscriptions.py) now inherits the current
   billing period when a subscription is active at assignment time: the new
   plan's limit applies to credits already used in that period. A fresh
   30-day period starts only when there is no active subscription. The Redis
   credit-ledger key (derived from `period_start.date()`) is preserved
   automatically, so concurrent-request protection carries over too.
   Rule documented in the function docstring, README (Credits section) and
   gateway-contract changelog (M9).
   - New regression tests: `tests/test_plan_change_usage.py` (5 tests):
     period+usage preserved on upgrade, **re-assigning the same plan does not
     reset the period** (the abuse vector), downgrade below usage → next
     request 402 with the upstream never called, expired subscription → fresh
     period, first assignment for a user without subscription.
2. **Credit rates are data, not code.** Rates were already DB columns
   (admin-editable); added the missing operator tooling and documentation:
   - `scripts/derive_credit_rates.py`: converts upstream USD/1M list prices
     into per-tier credit rates given margin and credits-per-USD; prints
     ready-to-use admin PATCH bodies. Placeholder prices only.
   - README "Credits" section: billing-period rule, rate-change semantics
     (future requests only), derivation formula
     `rate = usd_per_1k × credits_per_usd × (1 + margin)` with worked example.
   - `tests/test_derive_rates.py` (2 tests) pins the formula and the
     6-decimal HALF_UP quantization used by the gateway.
3. **OpenRouter switch by env only — verified.** No code path changed
   provider behavior; verified with a mocked OpenRouter-style upstream
   (`tests/test_openrouter_upstream.py`, 8 tests): usage in the final SSE
   chunk, `: OPENROUTER PROCESSING` comment lines, OpenRouter-style error
   bodies (numeric `code`), 429 with `X-RateLimit-Reset` verbose HTTP-date,
   `Retry-After` forwarded with correct precedence, env-only URL/auth-header
   switch (`Authorization: Bearer` / `X-API-Key`), failed requests never
   charged (usage row FAILED, credits 0, reserve released → next request
   still possible).
   - `app/services/upstream.py::_parse_resets_at` now also accepts HTTP-date
     strings (RFC 1123 via `email.utils.parsedate_to_datetime`, plus the
     verbose "…PM UTC" format some providers use) — previously only epoch
     seconds and ISO-8601.
   - `PROTECTED_USAGE_FIELDS` extended with `cost` (OpenRouter-style upstream
     USD cost) — stripped from client responses like the EVREN-private
     `usage.evren` object.
   - README section "Switching the upstream to OpenRouter (env only)" with
     seed overrides for tier model placeholders.
4. **Ops documentation.** `docs/backup-restore.md` (pg_dump/restore
   procedures, secrets handling, why Redis needs no backup, upgrade/rollback)
   and `docker-compose.prod.yml` + `deploy/Caddyfile` (no DB/Redis host
   ports, api unpublished, Caddy TLS reverse proxy for `UFUK_DOMAIN`,
   SSE-friendly settings, `restart: unless-stopped`). Merged config
   validated with `docker compose config` (needs Compose ≥ v2.24 for
   `!reset`). `.env.example` documents `UFUK_DOMAIN`. Not deployed.

### Test counts

- evren-backend: **115 passed** (100 before, +15 new)
- evren-agent: 188 (untouched this milestone)

### Open issues / notes

- Seeded credit rates (0.5/1.0, 1.5/3.0, 4.0/8.0) remain placeholder values —
  replace with derived rates before production (script provided).
- Renewal at period end is still manual (no background job): when a period
  expires the gateway returns 403 `subscription_inactive` until an admin
  assigns a plan again. Pre-existing behavior, documented in STATUS.md.
- The `.env` on this machine contains real secrets (never committed).
