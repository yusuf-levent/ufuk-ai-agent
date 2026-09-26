# Backup, restore and production deployment

This document describes how to back up and restore the Ufuk backend state, and
how the production compose stack is shaped. **Nothing here is deployed by this
repo** — these are operational procedures for the operator.

## What state exists, and where

| State | Where | Backup strategy |
|---|---|---|
| Accounts, plans, tiers, subscriptions, usage rows | Postgres (`pgdata` named volume) | `pg_dump` (below) |
| Credit ledger, tier cache, RPM counters, sessions blacklist | Redis (in-container memory) | **None needed** — rebuildable from Postgres (see below) |
| TLS certificates | `caddy_data` volume | Let's Encrypt re-issues; keep the volume to avoid rate limits |
| Secrets (JWT secret, upstream API key, admin emails) | `.env` on the host | Secure secret storage; NEVER commit, never include in DB backups |

### Why Redis needs no backup

Every Redis structure the gateway depends on is derived from Postgres:

- Credit ledger (`credits:{user_id}:{period_key}`): `ensure_ledger_synced`
  rebuilds it from settled/reserved usage rows when the key is missing.
- Tier views (`tier:{alias}`): a 60 s TTL cache; admin edits invalidate it.
- RPM counters (`rpm:{user_id}:...`): fixed-window counters; losing one
  briefly widens the rate-limit window, which is acceptable.
- Refresh-token blacklist: refresh-token rotation records live in Postgres;
  the in-memory blacklist is a convenience cache (`app/security.py`).

So losing Redis costs at most one rebuild query per active user and a softer
RPM edge for a minute. Restoring an old Redis dump is **not** required and
**not** recommended (it can resurrect stale ledgers).

## Backup (while the stack runs)

```powershell
# from the backend root, stack running (any compose project name works)
docker compose exec postgres pg_dump -U evren -Fc evren > backup-$(Get-Date -Format yyyyMMdd-HHmmss).dump

# stop-the-world variant (maximum consistency, brief downtime):
docker compose stop api
docker compose exec postgres pg_dump -U evren -Fc evren > backup-cold.dump
docker compose start api
```

Take backups on a schedule (e.g. daily cron/Task Scheduler) and store them
off-host. The `-Fc` (custom) format is compressed and allows parallel restore.

## Restore

```powershell
# 1. bring the stack up (fresh or existing)
docker compose up -d postgres redis

# 2. restore the dump into a clean database
docker compose exec postgres dropdb -U evren --if-exists evren
docker compose exec postgres createdb -U evren evren
Get-Content backup-20260921.du | docker compose exec -T postgres pg_restore -U evren -d evren --no-owner
```

> Note: `Get-Content` can corrupt binary dumps on Windows PowerShell 5.1.
> Prefer `cmd /c "type backup.du | docker compose exec -T postgres pg_restore ..."`
> or run the restore from inside the container. Verify row counts afterwards.

Migrations do not need to be re-run after a full restore (the schema comes with
the dump). After restoring:

```powershell
# 3. flush stale Redis (forces ledger rebuild from the restored DB)
docker compose exec redis redis-cli FLUSHDB

# 4. start the api (runs `alembic upgrade head` automatically, no-ops here)
docker compose up -d api
```

## Production stack (docker-compose.prod.yml)

```powershell
# .env for prod (beyond the dev keys):
#   ENVIRONMENT=prod
#   ALLOWED_ORIGINS=https://app.example.com
#   UFUK_DOMAIN=api.example.com     # needs a DNS A record to this host
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

What the override changes:

- postgres/redis: **no host ports** (dev publishes 5433/6380 on the host —
  prod must not).
- api: no host port; only Caddy reaches it (`api:8000` on the compose network).
- Caddy 2 (ports 80/443, HTTP/3) terminates TLS with automatic certificates
  for `UFUK_DOMAIN` and reverse-proxies to the api with SSE-friendly settings
  (`flush_interval -1`, 600 s response header timeout) and HSTS headers.
- All services `restart: unless-stopped`.

`docker compose -f docker-compose.yml -f docker-compose.prod.yml config` can
be used to preview the merged configuration. The `!reset []` syntax removes
the dev port mappings; it requires Docker Compose v2.24+ / v5+.

## Upgrade procedure

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml build api
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# migrations run automatically at container start (alembic upgrade head)
```

Rollback: restore the pre-upgrade DB dump taken before upgrading, then
`git checkout <previous tag> && docker compose ... up -d --build`.

## What is explicitly NOT handled here

- No SMTP configured (email is console-only in dev; password reset tokens are
  printed to the api logs — replace `app/services/email.py` for production).
- No monitoring/alerting/metrics; only the `/health` endpoint and structured
  logs.
- No automated backup scheduling (operator's cron/Task Scheduler).
- No horizontal scaling of the api (single node assumption; the circuit
  breaker is per-process).
