# Ufuk — local-first desktop coding agent

Ufuk is a Windows desktop coding agent: an Electron app whose main process
hosts the existing agent runtime (`evren-agent`) and talks to a self-hosted
LLM gateway (`evren-backend`).

## Layout

| Folder | What it is | Stack |
|---|---|---|
| `evren-agent/` | Agent core + local runner + CLI (nested git repo, tracked as a gitlink) | TypeScript, pnpm workspace, vitest |
| `evren-backend/` | OpenAI-compatible LLM gateway (accounts, plans, credits, tiers, SSE) | Python 3.12 / FastAPI, Postgres + Redis (Docker) |
| `frontend/` | **Ufuk** desktop app | Electron 44, React 18, TypeScript strict, Tailwind, Zustand, electron-vite |
| `docs/` | STATUS / PLAN / PROGRESS / SECURITY, gateway contract | markdown |

A root `pnpm-workspace.yaml` links `evren-agent/packages/*` and `frontend`
into one workspace so the app imports `@evren/agent-core` and
`@evren/local-runner` directly (`workspace:*`) — no forked logic.

## Running each part

### Backend (gateway)

```powershell
cd evren-backend
copy .env.example .env        # then fill in real secrets (never committed)
docker compose up -d          # postgres :5433, redis :6380, api :8000
.venv\Scripts\python -m pytest tests -q
```

### Agent (packages + CLI)

```powershell
cd evren-agent
pnpm install
pnpm -r test
```

### Frontend (Ufuk)

```powershell
cd frontend
pnpm install                  # installs into the root workspace
pnpm test                     # 52 unit tests (vitest)
pnpm typecheck && pnpm lint
pnpm build                    # build out/{main,preload,renderer}
pnpm e2e                      # Playwright Electron smoke tests (builds first: pnpm build)
pnpm dev                      # run the app in dev mode (backend not required for the shell)
```

Default backend URL is `http://localhost:8000` (configurable in Settings;
the renderer never talks to the backend directly — everything goes through
the main process).

## Git strategy

`evren-agent/` is its own git repo, recorded by the outer repo as a gitlink.
Commit inside `evren-agent/` first, then commit the updated pointer together
with everything else in the outer repo. No remotes are configured anywhere.

## Docs

- `docs/STATUS.md` — current state, gaps, risks
- `docs/PLAN.md` — milestone plan
- `docs/PROGRESS.md` — per-milestone reports and test counts
- `docs/SECURITY.md` — agent security model and known limits
- `evren-backend/docs/gateway-contract.md` — gateway API contract
