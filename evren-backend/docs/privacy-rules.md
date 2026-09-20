# Privacy Rules

This document is the authoritative description of what the Evren Agent Backend
stores, logs and deletes. Users send source code through the gateway, so the
default is: store and log as little as possible.

## Stored in PostgreSQL

| Data | Retention | Notes |
|---|---|---|
| `users` (email, argon2 password hash, role, flags) | until account deletion | |
| `refresh_tokens` (SHA-256 hash only) | max 30 days, revoked on rotation/logout/password change | raw tokens are never stored |
| `email_tokens` (SHA-256 hash only) | 24 h (verify) / 1 h (reset) | |
| `subscriptions` (plan, period, status) | until account deletion | |
| `usage_events` (user id, request id, tier alias, upstream model id, token counts, credits, estimated flag, status, latency) | billing records | **no prompts, no completions, no message bodies** |
| `plans`, `model_tiers` | configuration | |

## Stored in Redis (ephemeral)

| Key | Purpose | TTL |
|---|---|---|
| `rl:*` | login/register rate limiting | ≤ 1 h |
| `rpm:{user_id}:{period}` | requests-per-minute window | 60 s |
| `credits:{user_id}:{period}` | atomic credit reserve/settle ledger | period end + 5 days |
| `tier:{alias}` | tier config cache | 60 s |

## Never stored, never logged

- Prompt or completion content, tool payloads, SSE chunks.
- `Authorization` headers, access tokens, refresh tokens, upstream API keys.
- Upstream request/response bodies.

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
2. `refresh_tokens`, `email_tokens` and `subscriptions` rows are deleted.
3. The `users` row is deleted.
4. Redis keys referencing the user (`credits:{user_id}:*`, `rpm:{user_id}:*`)
   are deleted; rate-limit keys expire on their own within an hour.

Email addresses are only kept while the account exists.
