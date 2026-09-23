# Ufuk — Status (2026-09-23, final)

Product name: **Ufuk**. The desktop app lives in `frontend/` — Milestones
1–10 complete (skeleton + security baseline, auth/settings/privacy,
projects & conversations, chat & agent view, approvals/diffs/undo,
tiers/credits/errors, hardening, E2E + packaging + launch).

## Baseline (verified today)

| Component | Stack | Tests |
|---|---|---|
| `evren-agent` | TypeScript, pnpm monorepo (agent-core, local-runner, apps/cli) | **237 passed** (agent-core 76, local-runner 161) |
| `evren-backend` | Python 3.12 / FastAPI, Postgres 17 + Redis 7 (Docker) | **115 passed** |
| `frontend` | Electron 44 + React 18 + TS strict | **128 unit + 12 e2e passed** |

Tooling: Node 24.11.1, pnpm 12.4.2, Python 3.12.7, Docker 29.6.2. The
backend stack (postgres :5433, redis :6380, api :8000) is running on this
machine, and the packaged app is running against it. No git remotes are
configured anywhere — nothing gets pushed.

Tooling: Node 24.11.1, pnpm 12.4.2, Python 3.12.7, Docker 29.6.2. The backend
stack (postgres :5433, redis :6380, api :8000) is currently running on this
machine. No git remotes are configured anywhere (outer repo, evren-agent, or
anything else) — nothing gets pushed.

## Repo layout and git strategy

- The **outer repo** (`evren agent system`) tracks `evren-backend/` as normal
  files and `evren-agent/` as a **gitlink** (nested git repo, recorded as a
  commit pointer).
- Strategy: commit inside `evren-agent` first, then commit the updated
  gitlink + everything else in the outer repo. Docs (`docs/`) and `frontend/`
  live in the outer repo.
- Workspace strategy for the frontend: a **root pnpm workspace** whose packages
  include `evren-agent/packages/*` and `frontend` (see `pnpm-workspace.yaml`).
  `evren-agent` keeps its own `pnpm-workspace.yaml`; pnpm resolves the nearest
  workspace file when run inside `evren-agent/`, so its own tests keep working
  unchanged. The frontend imports `@evren/agent-core` and `@evren/local-runner`
  via `workspace:*` — no forked logic.

## What already works

- Agent core: provider (OpenAI-compatible SSE + tool-call reassembly), agent
  loop with typed events, context compaction, permission engine with hard
  floors, checkpoints/undo, SQLite/JSONL persistence, audit log with redaction.
- evren-gateway provider: login, single-flight refresh, tier aliases, usage,
  error mapping (402/429/5xx), Retry-After honored, tokens in
  `%LOCALAPPDATA%\evren-agent\gateway\tokens-*.json` (file store, to be
  replaced with Electron safeStorage in M3).
- Local runner: Windows path safety (lexical + native realpath: traversal,
  symlink/junction escape, 8.3 short names, dangling links), file denylist,
  run_command with sanitized env, output caps, process-tree kills, shadow
  checkpoints outside the workspace.
- Backend: auth (rotation + reuse detection), plans/tiers/subscriptions,
  reserve/settle credits (Redis ledger + idempotent DB settle), streaming SSE
  passthrough with usage capture and disconnect estimates, upstream error
  normalization incl. 429 Retry-After forwarding, circuit breaker, admin API,
  privacy endpoints, seeded tiers fast/balanced/strong.
- End-to-end CLI scenario: "The test in this repo is failing. Fix it and
  verify." works against the sample repo fixture with approvals + undo.

## Known gaps (input list, confirmed against code)

### Backend

1. **Plan change resets usage mid-period.** `assign_plan`
   (app/services/subscriptions.py:79) cancels the active subscription and
   creates a new one with `period_start=now` — the billing window moves, so
   credits used in the old period stop counting. Abuse vector: exhaust
   credits, switch plan (even to the same plan), get a fresh period.
2. Credit rates are already **data** (DB rows + admin API + seed), but there
   is no documented formula or helper to derive them from upstream $/token
   prices with a margin.
3. Upstream is env-configurable (`UPSTREAM_BASE_URL`, `UPSTREAM_API_KEY`,
   `UPSTREAM_AUTH_HEADER`) but has never been verified against an
   OpenRouter-style upstream (usage in final stream chunk, OpenRouter-style
   error bodies, `X-RateLimit-Reset` as an HTTP date string).
4. No backup/restore docs; no production compose (DB/Redis ports are
   published on the host; no TLS terminator).

### Agent security (to be turned into an adversarial suite in M2)

- Path safety does **not** cover: Windows reserved device names (CON, NUL,
  COM1…), alternate data streams (`file.txt:stream`), trailing dots/spaces,
  very long paths (the `\\?\` prefix handling exists but is untested at
  extremes), and mixed-slash/absolute/UNC variants are only partially tested.
- run_command floors cover encoded PowerShell, IEX, download-and-execute,
  registry, format/disk; **not** covered: obfuscated `Invoke-Expression` via
  string concatenation/backticks/env indirection, `cmd /c` chaining (`&`,
  `&&`, `|`, `;`), output flooding at the permission layer (caps exist at the
  runner layer), hung/orphan process cleanup beyond timeout kills (tested).
- **Prompt injection is not tested at all** (only a system-prompt rule).
- Unattended mode is implemented (allowlist-only, floors still deny) but not
  adversarially tested.

### Frontend

- Milestones 3–10 done; see docs/PROGRESS.md for details.
- better-sqlite3 is not bundled (no Electron 44 / ABI 149 prebuild, no VS
  Build Tools) — the app runs on the tested JSONL fallback.
- Installer: `frontend/release/Ufuk-Setup-0.1.0.exe` (unsigned, 106 MB).
- Open follow-ups: code signing + auto-update, MCP, GitHub integration,
  scheduled tasks, cloud mode, payments, vitest ≥4.1.11 upgrade (audit).

## Risks

- Electron + better-sqlite3 (native module) requires electron-rebuild; JSONL
  fallback must keep working.
- Nested pnpm workspaces (root + evren-agent) work because pnpm picks the
  nearest `pnpm-workspace.yaml`, but installs must be run from the right
  directories; documented in the root README.
- No code signing certificate — the NSIS installer will be unsigned (documented
  as a TODO with auto-update).
- Real upstream (EVREN) availability is not guaranteed during E2E; the mock
  gateway is the fallback and the report will say which was used.
