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

- `429` responses always include a `Retry-After` header (seconds). The body also
  carries `error.resets_at` (ISO-8601, UTC) whenever the gateway can derive it:
  for its own RPM limit it is `now + Retry-After`; for upstream 429s it comes
  from the upstream `resets_at` body hint or the `X-RateLimit-Reset` header
  (epoch seconds). When no hint exists, `Retry-After` defaults to 30.

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

Request (unknown fields are dropped via an allowlist; `max_tokens` is clamped
to the effective ceiling = `min(tier.max_output_tokens, plan.
max_output_tokens_per_request)` — seeded ceilings: `fast` 8192, `balanced`
8192, `strong` 16384, with plan caps never below the tier ceiling; when the
client omits `max_tokens` the full effective ceiling is used):

```json
{
  "model": "fast",
  "messages": [{"role": "user", "content": "hello"}],
  "temperature": 0.2,
  "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
  "tool_choice": "auto",
  "max_tokens": 8192
}
```

Response (standard OpenAI shape; `model` is the tier alias):

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "fast",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi!", "reasoning": "..."}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
            "prompt_tokens_details": null,
            "completion_tokens_details": {"reasoning_tokens": 3}}
}
```

EVREN-specific notes (verified against the real upstream):

- All current upstream models are **reasoning models**: `message.reasoning`
  (non-streaming) and `delta.reasoning` (streaming) carry chain-of-thought
  text that IS billed as completion tokens. `usage.completion_tokens_details.
  reasoning_tokens` shows the split. With small `max_tokens` the entire budget
  can be consumed by reasoning and `content` may be `null` — request enough
  `max_tokens` for reasoning + answer.
- Tokenizer overhead: short prompts are billed with a per-request overhead
  (measured: "Say OK" ≈ 90 prompt tokens on `fast`, ≈ 21 on `balanced`,
  ≈ 17 on `strong`).
- The upstream attaches a private `usage.evren` sub-object (platform credits,
  routed model). The gateway **strips it** before returning anything to the
  client; only the standard usage fields above are forwarded.

### POST /v1/chat/completions (streaming)

Send `"stream": true`. The response is standard OpenAI SSE
(`text/event-stream`, no buffering, `X-Accel-Buffering: no`; measured first
chunk ≈ 0.2–0.3 s, inter-chunk gap ≈ 15 ms against the real upstream). The
gateway injects `stream_options: {"include_usage": true}` upstream and passes
the final usage chunk through (with the private `evren` sub-object stripped).
`tool_calls` deltas pass through unchanged, including `delta.reasoning`
fragments. Every data chunk's `model` field shows the tier alias. If the
client disconnects mid-stream, the upstream call is cancelled and partial
usage is recorded (estimated from streamed content INCLUDING reasoning text).

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
        "upstream_model": "deepseek-v4-flash",
        "max_output_tokens": 8192,
        "context_window": 128000
      }
    }
  ]
}
```

### Tier → real upstream model mapping (verified live, 2026-09)

| Tier alias | Requested model ID | Upstream routes to |
|---|---|---|
| `fast` | `deepseek-v4-flash` | `deepseek/deepseek-v4-flash` |
| `balanced` | `gemma-4-31b` | `google/gemma-4-31b` |
| `strong` | `glm-5.3` | `zai/glm-5.3-fp8` |

Other models available on the upstream account: `qwen3-vl-30b` (vision),
`qwen3-embedding-8b`, `qwen3-reranker-8b`, `qwen3-asr-1.7b`, `dots-ocr`,
`deepseek-ocr-2`, `auto`. The response `model`/`usage` never exposes the
routed model to clients; only `GET /v1/models` details show the configured
upstream model IDs.

### Upstream rate limiting (EVREN)

The upstream enforces a per-minute **token bucket** (response headers
`X-RateLimit-Limit-Tokens: 1000000`, `X-RateLimit-Remaining-Tokens`,
`X-RateLimit-Reset` epoch seconds; small requests carry a per-model quota
weight). When it returns 429, the gateway forwards 429 with `Retry-After`
computed as: upstream `Retry-After` header, else `resets_at`/`X-RateLimit-Reset`
derived seconds, else 30 — and surfaces `error.resets_at` in the body.

## Error codes

| HTTP | `code` | When |
|---|---|---|
| 400 | `registration_failed` / `invalid_token` / `upstream_bad_request` | client errors |
| 401 | `invalid_credentials` / `invalid_api_key` / `token_expired` / `invalid_refresh_token` / `refresh_token_reused` | auth problems |
| 402 | `quota_exceeded` | monthly credit limit exhausted (do NOT retry until period reset) |
| 403 | `model_not_allowed` / `subscription_inactive` / `forbidden` | plan/permission problems |
| 409 | `Plan '...' already exists` / `Tier '...' already exists` | admin create with duplicate name/alias |
| 429 | `rate_limited` | RPM exceeded or upstream rate limit (`Retry-After` always set, `error.resets_at` when derivable) |
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
  (`estimated: true` in internal records). Every request gets a fresh
  gateway-generated `request_id`; there is NO client-supplied idempotency key —
  a retried request is a new charge (internal settle is idempotent, so a
  request is never double-charged).
- Measured cost per minimal request ("Say OK", gateway credits):
  `fast` ≈ 0.06, `balanced` ≈ 0.15, `strong` ≈ 0.40; a tool-call round on
  `fast` (schema in prompt) ≈ 0.26. The free plan's 100 credits therefore
  cover roughly 1,100–1,600 plain requests or ~380 tool-call rounds on `fast`.

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
- M8: live validation against the real EVREN upstream — real model IDs seeded,
  `usage.evren` stripped from client responses, 429 `resets_at` parsing
  (body hint / `X-RateLimit-Reset`), RPM 429 carries `error.resets_at`,
  disconnect estimates include reasoning text, admin duplicate plan/tier
  returns 409, per-tier `max_tokens` ceilings raised for reasoning models
  (fast/balanced 8192, strong 16384; plan caps raised to match).
