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

## Test

```powershell
docker compose up -d postgres redis   # must be running
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check app tests alembic
.venv\Scripts\ruff format --check app tests alembic
.venv\Scripts\mypy
.venv\Scripts\pip-audit --skip-editable
```

CI runs the same steps (`.github/workflows/backend-ci.yml` at the repo root).

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `UPSTREAM_BASE_URL` | `https://evren-llmapi.ssyz.org.tr/v1` | switch to OpenRouter later by changing only this |
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
