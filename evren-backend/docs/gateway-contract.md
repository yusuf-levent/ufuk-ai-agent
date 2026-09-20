# Evren Gateway Contract

This file is the source of truth for how the desktop agent (`evren-agent`) talks to
`evren-backend`. Update it whenever the API changes; the agent side is built
against this document.

## Conventions

- Base URL (dev): `http://localhost:8000`
- Authentication: `Authorization: Bearer <access_token>` — the short-lived (15 min)
  JWT from `POST /auth/login`. The desktop app handles refresh via
  `POST /auth/refresh`; the agent core only needs the access token.
- The `model` field is always a **tier alias** (`fast`, `balanced`, `strong`, ...).
  The gateway maps it to the real upstream model server-side. The real
  provider/model is visible in `GET /v1/models` details and `GET /privacy/info`
  for transparency, but clients can never override routing or credentials.
- Error bodies are OpenAI-style:

  ```json
  {
    "error": {
      "message": "human readable message",
      "type": "insufficient_quota",
      "code": "quota_exceeded"
    }
  }
  ```

- `429` responses always include a `Retry-After` header (seconds). The agent may
  prefer a body hint `error.resets_at` (ISO-8601) when present.

## Endpoints

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/health` | GET | — | `{status, components: {database, redis}}`, 200/503 |
| `/auth/register` | POST | — | `{email, password, display_name?}` → 201 user |
| `/auth/login` | POST | — | `{email, password}` → `{access_token, refresh_token, token_type, expires_in}` |
| `/auth/refresh` | POST | — | `{refresh_token}` → new pair; rotation with reuse detection (reuse revokes all sessions) |
| `/auth/logout` | POST | — | `{refresh_token}` → revokes it |
| `/auth/change-password` | POST | JWT | `{current_password, new_password}` → revokes all sessions |
| `/auth/verify-email` | POST | — | `{token}` (token arrives via the console email sender in dev) |
| `/auth/reset-password` | POST | — | `{email}` → always `{ok: true}` (no enumeration) |
| `/auth/reset-password/confirm` | POST | — | `{token, new_password}` |
| `/me` | GET | JWT | profile |
| `/me` | DELETE | JWT | `{password}` → deletes account, anonymizes usage |
| `/plans` | GET | — | public plan catalogue |
| `/usage` | GET | JWT | current period: used/remaining credits, per-tier totals |
| `/v1/chat/completions` | POST | JWT | gateway (streaming + non-streaming) |
| `/v1/models` | GET | JWT | tier aliases allowed for the plan, with `details` |
| `/privacy/info` | GET | — | upstream providers that may process data |
| `/admin/plans`, `/admin/tiers` | GET/POST/PATCH | JWT+admin | plan/tier management |
| `/admin/users` | GET | JWT+admin | user list |
| `/admin/users/{id}/subscriptions` | POST | JWT+admin | assign plan |
| `/admin/users/{id}/usage` | GET | JWT+admin | user usage summary |

## Gateway

### POST /v1/chat/completions (non-streaming)

Request (unknown fields are dropped via an allowlist; `max_tokens` is clamped to
the tier/plan cap):

```json
{
  "model": "fast",
  "messages": [{"role": "user", "content": "hello"}],
  "temperature": 0.2,
  "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
  "tool_choice": "auto",
  "max_tokens": 1024
}
```

Response (standard OpenAI shape; `model` is the tier alias):

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "fast",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi!"}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
}
```

### POST /v1/chat/completions (streaming)

Send `"stream": true`. The response is standard OpenAI SSE
(`text/event-stream`, no buffering, `X-Accel-Buffering: no`). The gateway
injects `stream_options: {"include_usage": true}` upstream and passes the final
usage chunk through. `tool_calls` deltas pass through unchanged. Every data
chunk's `model` field shows the tier alias. If the client disconnects
mid-stream, the upstream call is cancelled and partial usage is recorded
(estimated).

### GET /v1/models

```json
{
  "object": "list",
  "data": [
    {
      "id": "fast",
      "object": "model",
      "created": 1700000000,
      "owned_by": "evren-llmapi",
      "details": {
        "display_name": "Fast",
        "upstream_provider": "evren-llmapi",
        "upstream_model": "gpt-4o-mini",
        "max_output_tokens": 4096,
        "context_window": 128000
      }
    }
  ]
}
```

## Error codes

| HTTP | `code` | When |
|---|---|---|
| 400 | `registration_failed` / `invalid_token` / `upstream_bad_request` | client errors |
| 401 | `invalid_credentials` / `invalid_api_key` / `token_expired` / `invalid_refresh_token` / `refresh_token_reused` | auth problems |
| 402 | `quota_exceeded` | monthly credit limit exhausted (do NOT retry until period reset) |
| 403 | `model_not_allowed` / `subscription_inactive` / `forbidden` | plan/permission problems |
| 429 | `rate_limited` | RPM exceeded or upstream rate limit (`Retry-After` always set) |
| 502 | `upstream_error` / `upstream_unavailable` / `upstream_auth_error` | upstream failures (one connect retry, circuit breaker) |
| 503 | `upstream_unavailable` | circuit breaker open (`Retry-After: 30`) |
| 504 | `timeout` | upstream timeout |

## Behavioral notes for the agent

- On `402 quota_exceeded`: stop retrying — the period limit is exhausted.
- On `429 rate_limited`: honor `Retry-After` (seconds), then retry.
- On `502/503/504`: back off and retry; the gateway already retries connection
  errors once (never after streaming started) and protects itself with a
  circuit breaker.
- Usage accounting: credits = prompt×in_rate + completion×out_rate per 1k tokens
  (tier rates). Concurrent requests reserve before calling upstream, so
  overspending is not possible. Missing upstream usage is estimated
  (`estimated: true` in internal records).

## Changelog

- M1: skeleton, config, DB schema, migrations, `/health`, CI. Contract drafted.
- M2: auth endpoints (register/login/refresh rotation/logout/change-password,
  email verification, password reset), login/register rate limiting.
- M3: plans, tiers, subscriptions, credit accounting (reserve/settle), admin API,
  public `/plans`.
- M4: non-streaming `/v1/chat/completions` proxy with usage recording and quota
  checks against a mocked upstream.
- M5: streaming SSE passthrough with usage capture, model alias rewrite and
  client-disconnect partial usage.
- M6: upstream error normalization, single connect retry, circuit breaker,
  `/v1/models`, `/usage`, `/privacy/info`, account deletion, log-redaction tests.
- M7: seed script, real-upstream integration script, README, contract finalized.
