# Privacy Rules

This document is the authoritative description of what the Evren Agent Backend
stores, logs and deletes. Users send source code through the gateway, so the
default is: store and log as little as possible.

## Stored in PostgreSQL

| Data | Retention | Notes |
|---|---|---|
| `users` (email, argon2 password hash, role, flags, terms acceptance, soft security flag) | until account deletion | **no IP addresses, no device fingerprints** |
| `refresh_tokens` (SHA-256 hash only) | max 30 days, revoked on rotation/logout/password change | raw tokens are never stored |
| `email_tokens` (SHA-256 hash only) | 24 h (verify) / 1 h (reset) | |
| `subscriptions` (plan, period, status) | until account deletion | |
| `usage_events` (user id, request id, tier alias, upstream model id, token counts, credits, estimated flag, status, latency, real USD cost, cache/reasoning token buckets, selected model, parent request id, session id, finish reason) | billing records | **no prompts, no completions, no message bodies** |
| `cost_daily_rollup` (day, user id, tier alias, selected model, request/token/credit/USD totals) | billing records | daily aggregate of `usage_events` for margin reporting; `user_id` anonymized on account deletion |
| `plans`, `model_tiers` | configuration | |

## Stored in Redis (ephemeral)

| Key | Purpose | TTL |
|---|---|---|
| `rl:*` | login/register rate limiting | ≤ 1 h |
| `rpm:{user_id}:{period}` | requests-per-minute window | 60 s |
| `credits:{user_id}:{period}` | atomic credit reserve/settle ledger | period end + 5 days |
| `budget:{user_id}:{window_start}` | rolling-window burst budget (sub-agent kill-switch) | window + 5 s |
| `inflight:{user_id}` | concurrent in-flight request slots (account-sharing cap) | 10 min |
| `anomaly:{user_id}:{bucket}:clients` | SALTED hashes of client keys, for distinct-client cardinality only | window + 60 s |
| `anomaly:{user_id}:{bucket}:count` | request count in the anomaly window | window + 60 s |
| `tier:{alias}` | tier config cache | 60 s |

## Never stored, never logged

- Prompt or completion content, tool payloads, SSE chunks.
- `Authorization` headers, access tokens, refresh tokens, upstream API keys.
- Upstream request/response bodies.
- Raw client IP addresses or user agents. The account-sharing detector hashes
  `ip|user-agent` salted per user (so the same client hashes differently per
  account and cannot be correlated) and stores only that hash, only to count
  DISTINCT clients in a window. The raw value lives for the duration of the
  request and is never persisted or logged.

## Account-sharing deterrents

Three layers, none of which auto-bans (patterns that look like sharing also
occur for honest power users — a human always reviews):

1. **Contractual** — `users.terms_accepted_at` / `terms_version` record the
   "you may not share your account" acceptance at signup. Accounts created
   before the clause existed are grandfathered in, never locked out.
2. **Concurrency cap** — `plans.max_concurrent_requests` bounds in-flight LLM
   requests per account (blast-radius limiter). Slots always release at the
   single terminal point of every request path, so a failure can never lock a
   user out.
3. **Soft anomaly flag** — `users.security_flagged` / `security_flag_reason`
   are set when a window shows many distinct clients or a request burst.

## Logging

All logs go through structlog with a redaction processor that removes or masks
sensitive keys (`authorization`, `api_key`, `password`, `token`, `messages`,
`prompt`, `completion`, `body`, ...) before rendering, including nested values.
Log tests (`tests/test_log_redaction.py`) assert that secrets and message content
never appear in log output. Application logs contain metadata only: user id,
tier alias, token counts, latency, status, request id.

## Account deletion rule

`DELETE /me` (requires the account password) performs:

1. `usage_events.user_id` is set to `NULL` (rows are anonymized, not deleted, so
   aggregate billing totals stay correct — the row no longer points to any person).
   `cost_daily_rollup.user_id` is anonymized the same way.
2. `refresh_tokens`, `email_tokens` and `subscriptions` rows are deleted.
3. The `users` row is deleted.
4. Redis keys referencing the user (`credits:{user_id}:*`, `rpm:{user_id}:*`,
   `budget:{user_id}:*`, `inflight:{user_id}`, `anomaly:{user_id}:*`) are
   deleted; rate-limit keys expire on their own within an hour.

Email addresses are only kept while the account exists.
