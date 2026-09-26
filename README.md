# Ufuk — VS Code fork + abonelikli agent

Ufuk, VS Code'un hazir agent arayuzunu (Ask/Edit/Agent, tool timeline, diff, checkpoint)
alip icine login + abonelik + kredi ekleyen bir VS Code fork'udur. LLM istekleri
kendi backend'imize (`evren-backend` → OpenRouter) proxy'lenir.

## Layout

| Folder | What it is | Stack |
|---|---|---|
| `vscode/` | **Ufuk masaustu** — VS Code fork (rebrand: Ufuk) | TypeScript, Electron |
| `evren-backend/` | LLM gateway — auth, plans, credits, tiers, SSE proxy | Python 3.12 / FastAPI, Postgres + Redis |
| `docs/` | IMPLEMENTATION-PLAN.md, arastirma raporu | markdown |

Masaustu = VS Code fork (Ufuk), Sunucu = evren-backend. Eklenti yok, evren-agent yok.

## Running

### Backend (gateway)

```powershell
cd evren-backend
copy .env.example .env        # then fill in real secrets (never committed)
docker compose up -d          # postgres :5433, redis :6380, api :8000
.venv\Scripts\python -m pytest tests -q
```

### Masaustu (Ufuk — VS Code fork)

```powershell
cd vscode
npm run compile               # build
.\scripts\code.bat            # launch (Ufuk adiyla)
```

## Docs

- `docs/IMPLEMENTATION-PLAN.md` — faz plani (Faz 0-5)
- `docs/ARASTIRMA-RAPORU.md` — arastirma raporu
