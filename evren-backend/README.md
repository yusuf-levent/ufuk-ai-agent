# Evren Agent Backend

Accounts, plans/credits and an OpenAI-compatible LLM gateway for the
[Evren desktop agent](../evren-agent). The agent never sees upstream API keys and
never selects raw upstream models — it authenticates with its own account JWT and
asks for a **tier alias** (`fast`, `balanced`, `strong`).

```
agent (fetch, OpenAI-compatible)                     upstream provider
   │  POST /v1/chat/completions                          ▲
   │  Authorization: Bearer <user JWT>                   │ (server-side key only)
   ▼                                                     │
┌──────────────── backend ───────────────────────────────┘
│ auth → plan checks → credit reserve (Redis) → allowlist → proxy
│ usage recording (idempotent, per request_id) → settle
└──────────────────────────────────────────────────────────────
```

## Requirements

- Python 3.12+
- Docker (Postgres 17 + Redis 7 via docker-compose)

## Setup

```powershell
cd evren-backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
Copy-Item .env.example .env   # then edit: UPSTREAM_API_KEY, JWT_SECRET, ADMIN_EMAILS
docker compose up -d postgres redis
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python scripts\seed.py
```

> Ports: the stack uses **5433** (Postgres), **6380** (Redis) and **8000** (API) on the
> host to avoid clashing with a locally installed Postgres/Redis. Change them in
> `docker-compose.yml` + `.env` if needed.

## Run

```powershell
# dev server
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# or the whole stack in Docker (migrations run automatically)
docker compose up --build
```

OpenAPI docs: <http://localhost:8000/docs>

## Credit rates for the OpenRouter cutover

Tier credit rates (`input/output_credits_per_1k_tokens`) are derived from the
upstream's **verified** USD prices plus a parametric margin — never invented:

    credits_per_1k = (usd_per_1m / 1000) * credits_per_usd * (1 + margin)

- `usd_per_1m` — the upstream's published USD price per 1M tokens. With
  `--source openrouter` the script reads them live from OpenRouter's public
  model listing (`GET https://openrouter.ai/api/v1/models`, no API key) and
  fails loudly when a tier's model id is missing, so a price is never guessed.
- `credits_per_usd` — product decision: how many credits a paying user gets
  per dollar (default `1000`).
- `margin` — markup over upstream cost (default `0.30` = +30%): covers
  tokenizer overhead vs. the upstream's own count, refunded failures, payment
  processing and free-tier usage.

```powershell
# Live OpenRouter prices for the seeded tier aliases:
.venv\Scripts\python scripts\derive_credit_rates.py --source openrouter

# Different economics:
.venv\Scripts\python scripts/derive_credit_rates.py --source openrouter --margin 0.5 --credits-per-usd 500
```

The output is a JSON list plus ready-to-paste `PATCH /admin/tiers/<id>` bodies
(rates take effect immediately; no restart needed). The tier alias -> OpenRouter
model id mapping lives in the script's `TIER_MODEL_IDS` and is mirrored in
`.env.example`.
## Test

```powershell
docker compose up -d postgres redis   # must be running
.venv\Scripts\python -m pytest -q
```

Tests run against a **dedicated database** (`evren_test`) and Redis logical DB 15 —
never the dev database. `tests/conftest.py` rewrites `DATABASE_URL`/`REDIS_URL`
before any app import (so a misconfigured env cannot point the suite at dev data),
creates `evren_test` if missing, and `clean_tables` refuses to TRUNCATE any database
whose name does not contain "test" (defense in depth; pinned by
`tests/test_db_isolation.py`).
.venv\Scripts\ruff check app tests alembic
.venv\Scripts\ruff format --check app tests alembic
.venv\Scripts\mypy
.venv\Scripts\pip-audit --skip-editable
```

CI runs the same steps (`.github/workflows/backend-ci.yml` at the repo root).

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `UPSTREAM_BASE_URL` | `https://evren-llmapi.ssyz.org.tr/v1` | switch to OpenRouter by changing only this (see below) |
| `UPSTREAM_API_KEY` | — | required, never sent to clients, never logged |
| `UPSTREAM_AUTH_HEADER` | `Authorization` | `Authorization` (Bearer) or `X-API-Key` |
| `UPSTREAM_TIMEOUT_SECONDS` | `300` | read timeout for upstream calls |
| `JWT_SECRET` | — | required, min 32 chars |
| `ACCESS_TOKEN_TTL_SECONDS` | `900` | access token lifetime (15 min) |
| `DATABASE_URL` | `postgresql+asyncpg://evren:evren@localhost:5433/evren` | |
| `REDIS_URL` | `redis://localhost:6380/0` | |
| `ALLOWED_ORIGINS` | — | comma-separated CORS origins |
| `ADMIN_EMAILS` | — | comma-separated; these emails get the admin role at registration |
| `ENVIRONMENT` | `dev` | `dev` = console logs, `prod` = JSON logs + HSTS |
| `REQUEST_MAX_BODY_BYTES` | `10485760` | request size limit |

## Using the gateway

```powershell
# 1. login (the desktop app keeps/refreshes these tokens)
$login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/auth/login `
  -ContentType "application/json" `
  -Body '{"email": "user@example.com", "password": "..."}'

# 2. chat completion via tier alias
Invoke-RestMethod -Method Post -Uri http://localhost:8000/v1/chat/completions `
  -ContentType "application/json" `
  -Headers @{Authorization = "Bearer $($login.access_token)"} `
  -Body '{"model": "fast", "messages": [{"role": "user", "content": "hi"}]}'
```

Streaming works exactly like OpenAI SSE (`"stream": true`); the final usage chunk is
passed through and the `model` field always shows the tier alias.

## Switching the upstream to OpenRouter (env only)

No code changes are required — the gateway talks to any OpenAI-compatible
upstream. Set in `.env`:

```ini
UPSTREAM_BASE_URL=https://openrouter.ai/api/v1
UPSTREAM_API_KEY=sk-or-...            # your OpenRouter key
UPSTREAM_AUTH_HEADER=Authorization    # Bearer (default); X-API-Key also supported
```

Then point each tier's `upstream_model_id` at the model you want (these are
**configurable placeholders** — pick current ids from the OpenRouter model
pages, don't trust examples):

```powershell
# seed-time overrides (upstream renames a model id)
$env:SEED_PROVIDER = "evren-llmapi"
$env:SEED_QWEN37_FLASH_MODEL = "qwen/qwen3.7-flash-new-id"   # example
.venv\Scripts\python scripts\seed.py

# or per-tier at runtime via the admin API (PATCH /admin/tiers/{id})
```

`scripts/seed.py` reconciles the database against `DEFAULT_TIERS` /
`DEFAULT_PLANS` on every run: it inserts what is missing, overwrites what
exists with the seeded values, retires seed-owned tiers that the defaults no
longer define (so a replaced model cannot linger in the picker) and prunes
plan `allowed_tier_aliases` entries that no longer resolve to a usable tier.
`--force` is deprecated and no longer changes behaviour. Permanent
customisation belongs in the admin API, not in hand-edited rows — the next
seed run overwrites them.

Verified behavior against a mocked OpenRouter-style upstream
(`tests/test_openrouter_upstream.py`): usage in the final stream chunk
(`: OPENROUTER PROCESSING` comment lines tolerated), OpenRouter-style error
bodies (`{"error": {"message", "code"}}` with numeric codes), 429s with
`X-RateLimit-Reset` verbose HTTP-dates (and RFC 1123), `Retry-After`
forwarding, and failed requests never charged. OpenRouter's upstream
`usage.cost` (USD) is stripped from client responses just like the EVREN
private `usage.evren` object.

## Backup, restore and production deployment

See [docs/backup-restore.md](docs/backup-restore.md) for backup/restore
procedures (pg_dump, secrets, Redis rebuildability) and
[docker-compose.prod.yml](docker-compose.prod.yml) + [deploy/Caddyfile](deploy/Caddyfile)
for the production stack (no exposed DB/Redis ports, Caddy TLS reverse proxy).
Nothing is deployed by this repo; both are documentation-grade artifacts.

## Adding a tier (no code change)



```powershell
# as an admin (ADMIN_EMAILS) user
Invoke-RestMethod -Method Post -Uri http://localhost:8000/admin/tiers `
  -ContentType "application/json" -Headers @{Authorization = "Bearer <admin jwt>"} `
  -Body '{
    "alias": "reasoning",
    "display_name": "Reasoning",
    "upstream_model_id": "openai/o3-mini",
    "upstream_provider_name": "openrouter",
    "input_credits_per_1k_tokens": "5.0",
    "output_credits_per_1k_tokens": "10.0",
    "max_output_tokens": 16384,
    "context_window": 200000,
    "enabled": true
  }'
```

Then allow it on a plan: `PATCH /admin/plans/{id}` with
`{"allowed_tier_aliases": ["fast", "reasoning"]}`. Tier changes take effect within
60 s (Redis cache) or immediately when edited through the admin API.

## Adding a plan

`POST /admin/plans` with name, monthly credit limit, per-request max tokens, RPM and
allowed tier aliases. Assign to a user with
`POST /admin/users/{user_id}/subscriptions {"plan_id": "..."}`. New users
automatically get the plan with `is_default: true` for a 30-day period.

## Credits

`credits = prompt_tokens × input_rate + completion_tokens × output_rate` (per 1k
tokens, per tier). Before each call the gateway reserves an estimated maximum
(Redis, atomic) and settles the real cost afterwards, so concurrent requests cannot
overspend. Usage rows are keyed by a unique `request_id`; settling is an
idempotent state transition (`reserved → settled/failed`), so a request is never
double-charged. If the upstream does not report usage, tokens are estimated
(chars/4) and the row is marked `estimated = true`.

**Plan changes never reset usage.** Assigning a plan while a subscription is
active keeps the current billing period; the new plan's limit applies to the
credits already used in that period (regression-tested in
`tests/test_plan_change_usage.py`). A fresh 30-day period starts only when the
user has no active subscription.

### Credit rates are data, not code

The two rate columns live on the `model_tiers` table
(`input_credits_per_1k_tokens`, `output_credits_per_1k_tokens`) and are edited
through the admin API (`POST/PATCH /admin/tiers`) or set initially by
`scripts/seed.py`. Nothing in the app code hardcodes rates; changing a rate
affects only future requests (settled rows keep the amount actually charged).

Derive rates from the upstream's real USD/1M-token list prices:

```
input_credits_per_1k  = (usd_per_1m_in  / 1000) × credits_per_usd × (1 + margin)
output_credits_per_1k = (usd_per_1m_out / 1000) × credits_per_usd × (1 + margin)
```

- `credits_per_usd` — product decision: how many credits a user gets per dollar
  (e.g. `1000` → one credit ≈ $0.001 of upstream budget).
- `margin` — covers tokenizer overhead vs. the upstream's own token counts,
  refunded failed requests, payment fees and free usage (e.g. `0.3` = +30%).

Helper (placeholders below, **not real prices** — always take current prices
from the upstream's pricing page):

```powershell
.venv\Scripts\python scripts\derive_credit_rates.py `
  --tiers fast=0.15:0.60 balanced=0.50:2.00 strong=1.25:10.00 `
  --margin 0.3 --credits-per-usd 1000
# prints the rates plus ready-to-use admin PATCH bodies
```

The seeded rates (`fast` 0.5/1.0, `balanced` 1.5/3.0, `strong` 4.0/8.0 per 1k)
are initial placeholder values for the EVREN upstream, not derived from a real
price sheet — replace them before production.

## Privacy

- Prompts/completions are proxied, never stored, never logged.
- Structured logs carry metadata only (user id, tier, token counts, latency,
  status, request id) and pass through a redaction processor (tested).
- Account deletion (`DELETE /me` with password): profile, sessions and
  subscriptions are removed; usage rows are anonymized (`user_id → NULL`).
  Details: [docs/privacy-rules.md](docs/privacy-rules.md).
- `GET /privacy/info` lists which upstream providers may process user data.

## Repo layout

```
app/
├── main.py            # app factory, middleware, error handlers
├── config.py          # pydantic-settings (env only)
├── security.py        # argon2, JWT, token hashing
├── routers/           # auth, me, plans, admin, gateway (/v1/*), usage, privacy, health
├── services/          # auth, subscriptions, tiers, credits, usage, upstream, breaker, email
├── models/            # SQLAlchemy models
└── schemas/           # pydantic request/response
alembic/               # migrations
scripts/               # seed.py, integration_real_upstream.py
tests/                 # unit + integration (mock upstream)
docs/                  # gateway-contract.md, privacy-rules.md
```

The agent-side contract lives in [docs/gateway-contract.md](docs/gateway-contract.md).
