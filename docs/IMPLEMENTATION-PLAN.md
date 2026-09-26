# Ufuk Agent System — Implementasyon Plani (DUZELTILMIS v2)

> Tarih: 2026-09-26
> Hedef: Claude Code / Codex ayari masaustu coding agent (Windows oncelikli)
> Ilke: Sunucu MINIMAL (sadece backend + DB), agent motoru TAMAMEN masaustunde
> Kritik duzeltme: Onceki planda "beyin = extensions/copilot" yazmistik — YANLIS.
>   Dogru: Agentic kisim VS Code cekirdeginde, 3 katmanli. Copilot sadece bir harness.

---

## 0. Neden Onceki Plan Yanlisti — Koddan Teyit

### 0.1 "Open in Agent" dedigin sey ne?

VS Code'da ust kisimda **"Open in Agents"** butonu var. Basinca IDE'den ayri bir **Agents Window** (ayri pencere) aciliyor. Bu window'un icinde:

- `welcomeAgentSessions` — hosgeldin ekrani (`src/vs/workbench/contrib/welcomeAgentSessions/browser/agentSessionsWelcome.ts`)
- `agentSessions` — session listesi + "Open in Agents" aksiyonlari (`src/vs/workbench/contrib/chat/electron-browser/agentSessions/agentSessionsActions.ts`)
- `chat` — Agent modunda chat (Ask/Edit/Agent secici, tool timeline, diff, checkpoint)

Bu **ayri bir pencere**, IDE'nin icindeki chat degil. `INativeHostService.openAgentsWindow()` ile aciliyor, `IsSessionsWindowContext` ile ayirt ediliyor.

### 0.2 Gercek agent motoru nerede? (koddan)

```
src/vs/platform/agentHost/          ← GERCEK BEYIN (cekirdek, extensions degil)
├── AGENTS.md                       ← Multi-Chat Architecture spec (Status: COMPLETE 2026-07-01)
├── common/
│   ├── agent.ts                    ← IAgent, IAgentChats, IAgentCapabilities (provider model)
│   ├── agentService.ts             ← IAgentService, IAgentConnection (orchestrator)
│   ├── agentHostByokLm.ts          ← BYOK LM bridge (OpenAI-compatible proxy)
│   └── state/protocol/             ← AHP wire protocol (SessionState, ChatState, Turn)
├── node/
│   ├── agentService.ts             ← AgentService (orchestrator, session registry)
│   ├── agentHostStateManager.ts    ← State tree (_sessionStates, _chatEntries)
│   ├── claude/claudeAgent.ts       ← Claude harness
│   ├── copilot/copilotAgent.ts     ← Copilot harness
│   └── codex/codexAgent.ts         ← Codex harness
└── browser/
    └── agentHostProtocolClient.ts  ← Renderer ↔ Agent Host IPC

src/vs/workbench/contrib/chat/      ← ARAYUZ
├── common/chatModes.ts             ← Ask/Edit/Agent modlari (ChatMode.Agent)
├── common/chat.ts                  ← Chat model
├── browser/chat.ts                 ← Chat widget
└── electron-browser/agentSessions/ ← "Open in Agents" aksiyonlari

src/vs/workbench/contrib/welcomeAgentSessions/ ← HOSGELDIN EKRANI

extensions/copilot/                 ← SADECE BIR HARNESS (Copilot), beyin degil
```

**3 harness var, hepsi esit:**

| Harness | Dosya | SDK |
|---|---|---|
| Claude | `platform/agentHost/node/claude/claudeAgent.ts` | Anthropic SDK |
| Copilot | `platform/agentHost/node/copilot/copilotAgent.ts` | Copilot SDK |
| Codex | `platform/agentHost/node/codex/codexAgent.ts` | Codex SDK |

Hepsi `IAgent` interface'ini implemente eder (`common/agent.ts`). Orchestrator (`AgentService` + `AgentHostStateManager`) provider-agnostic — `if (provider === 'claude')` yok, sadece `IAgentCapabilities` flag'leri var.

**BYOK (Bring Your Own Key) LM bridge:**

```
Renderer (extension LM API) ←→ IByokLmProxyService ←→ Node Agent Host ←→ SDK
         agentHostByokLm.ts         byokLmProxyService.ts
```

`agentHostByokLm.ts` — OpenAI Responses wire payload ↔ `IByokLmChatRequest` (vendor, modelId, input, tools, reasoningEffort). Node tarafi `byokLmProxyService.ts` ile renderer'daki `ILanguageModelsService`'e baglanir. Bu bridge sayesinde herhangi bir `vscode.lm` provider'i (OpenAI, Anthropic, OpenRouter, custom) agent harness'a LLM saglayabilir.

### 0.3 Onceki planin hatasi

| Onceki plan | Dogru |
|---|---|
| "Beyin = extensions/copilot" | Beyin = `platform/agentHost` (cekirdek). `extensions/copilot` sadece Copilot harness'i, 3'ten biri |
| "evrenProvider.ts yaz, extensions/copilot icine" | BYOK bridge zaten var (`agentHostByokLm.ts` + `byokLmProxyService.ts`). Yeni provider `vscode.lm` API ile eklenir, copilot extension'ina dokunmaya gerek yok |
| "evren-agent geri getir" | evren-agent cop, VS Code'un agentHost'u zaten daha iyi — dogru ama gerekce yanlisti |

---

## 1. Mimari Kararlar (Degismez)

### 1.1 Nerede ne calisir

```
[Masaustu — VS Code Fork = Ufuk]                    [Sunucu — evren-backend]
┌──────────────────────────────────┐                ┌──────────────────────┐
│ VS Code Workbench                │    HTTPS/SSE   │ FastAPI + Postgres   │
│  ├─ chat (Ask/Edit/Agent mod)   │◄──────────────►│  + Redis             │
│  ├─ editor + explorer            │  /v1/chat/*    │  /auth, /plans,      │
│  ├─ Agents Window (ayri pencere) │  /auth/*       │  /usage, /v1/models  │
│  │   └─ welcomeAgentSessions     │  /usage        │  OpenRouter proxy    │
│  └─ Agent Host (node process)    │  JWT           │  kredi/rate-limit    │
│      ├─ AgentService             │                │  tek API key sende   │
│      ├─ AgentHostStateManager    │                └──────────────────────┘
│      ├─ Claude/Copilot/Codex     │
│      │   harness (IAgent)        │
│      └─ BYOK LM bridge ──────────┘
│         (agentHostByokLm.ts)     │
│              ↕                   │
│         vscode.lm API            │
│         (evrenProvider) ─────────┘
│              ↕
│         evren-backend (/v1/chat/completions SSE)
│
│  Storage: VS Code globalState/workspaceState + agent-host.db
│  Dosya/shell/chat gecmisi TAMAMEN masaustunde.
│  Sunucuda SADECE users, subscriptions, usage_events, plans, tiers.
└──────────────────────────────────┘
```

- **Agent loop asla sunucuda degil** — `platform/agentHost/node/agentService.ts` masaustundeki node utility process'te. Sunucu sadece LLM proxy + auth + kredi.
- **Kullanici dosyalari/sohbetler:** `agent-host.db` (sessions_v2, session_chat_catalogs) + VS Code storage — masaustunde. Sunucuda minimal.
- **Neden VS Code fork?** `chat` + `agentHost` + `welcomeAgentSessions` 10 yillik, Claude/Codex/Copilot harness'lari hazir. Sifirdan loop yazmak sacmalik.

### 1.2 VS Code fork kapsami — MINIMAL

- **Degisecek dosyalar (sadece 3 yer):**
  1. `vscode/product.json` — rebrand (Ufuk)
  2. `vscode/src/vs/platform/agentHost/common/agentHostByokLm.ts` veya yeni `evrenLmProvider.ts` — BYOK bridge'e evren-backend provider'i ekle (veya `vscode.lm` extension olarak)
  3. `vscode/src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts` — quota hook (402/429)

- **Dokunulmayacak:** `platform/agentHost/node/claude|codex|copilot` harness'lari, `agentService.ts`, `agentHostStateManager.ts` — cekirdek, provider-agnostic. Workbench sadelestirme `when: false` ile, dosya silme yok.

- **Guncelleme:** `vscode/` `.gitignore`'da, ayri git history. `git -C vscode fetch origin && git merge` ayda bir. Hook'lar BYOK bridge'de oldugu icin conflict riski dusuk.

### 1.3 Model / kredi haritasi

- `ModelTier.alias` (örn. `fast`, `pro`, `strong`) → `upstream_model_id` (örn. `openai/gpt-4o`, `anthropic/claude-3.5-sonnet`). Kullanici alias secer, gateway `sanitize_request()` ile upstream ID'ye cevirir. `max_tokens` plan limitine kirpilir.
- Kredi: `input_credits_per_1k` + `output_credits_per_1k` DB'de, `scripts/derive_credit_rates.py` ile USD → kredi cevimi. Redis `credits:{user}:{period_key}` atomik ledger. `402 quota_exceeded`, `429 rate_limited` (Retry-After).

---

## 2. Fazlar — En Ince Ayrinti

### Faz 0 — Repo Duzeltme (1 gun)

**Hedef:** `pnpm install` ve `pytest` yesil, evren-agent referansi temizlenir.

- `pnpm-workspace.yaml` duzelt:
  ```yaml
  # ONCEKI (bozuk):
  packages:
    - evren-agent/packages/*
    - frontend
  # YENI (dogru):
  packages: []  # veya sadece evren-backend testleri icin bos
  # frontend ve evren-agent YOK, VS Code fork ana UI
  ```
  `allowBuilds` icindeki `better-sqlite3` artik gerekmez (VS Code `agent-host.db` kullaniyor).
- `frontend/` ve `evren-agent/` klasorleri ZATEN yok — dogru, oyle kalsin. Eski `C:\Users\Yusuf\Desktop\ufuk agent system\frontend` ve `evren-agent` legacy, yeni projeye kopyalanmaz.
- `README.md` guncelle: "Masaustu = VS Code fork (Ufuk), Sunucu = evren-backend, evren-agent yok, agent motoru = platform/agentHost" yaz.
- Kabul: `evren-backend: pytest -q` yesil.

### Faz 1 — Backend Hardening (1 hafta)

**Hedef:** Production'a hazir gateway.

- **Dosyalar:** `evren-backend/app/config.py`, `app/services/upstream.py`, `app/services/credits.py`, `app/routers/gateway.py`, `app/services/rate_limiter.py`, `app/routers/admin.py`, `app/main.py`, `alembic/`, `scripts/seed.py`, `tests/*`

1. **OpenRouter dogrulama:** `tests/test_openrouter_upstream.py` zaten var — mock OpenRouter SSE (final chunk'ta `usage`, `{"error":{"message","code":123}}`, `429` + `X-RateLimit-Reset: Wed, 21 Oct 2026 07:28:00 GMT` → `Retry-After` + `resets_at` forward, `usage.cost` strip). `app/services/upstream.py: _parse_resets_at` HTTP-date parse ekle.
2. **Global rate limiter:** `app/services/rate_limiter.py` icine `global_upstream_limiter` (Redis `INCR` + `EXPIRE`, örn. 60 req/min tum kullanicilar icin) — tek OpenRouter anahtarini korur. `gateway.py: _reserve` oncesi kontrol.
3. **Odeme webhook:** `app/routers/billing.py` YENI dosya — `POST /billing/webhook` (Stripe/Iyzico imzasi dogrula → `subscription_service.assign_plan(db, user_id, plan_id)`). `Plan` icine `stripe_price_id` kolonu ekle (alembic migration). `app/main.py` router ekle.
4. **Observability:** `structlog` zaten var — Sentry ekle (`sentry-sdk[fastapi]`), `app/logging.py` icine `sentry_init` (env `SENTRY_DSN`). `/health` icine `GET /health/ready` (DB+Redis ping).
5. **Backup:** `docs/backup-restore.md` + `docker-compose.prod.yml` (DB/Redis host port kapali, Caddy TLS).
6. **Kredi formulu:** `scripts/derive_credit_rates.py` + README: `rate = usd_per_1k / credits_per_usd * (1+margin)`.

- Kabul: `pytest -q` 115+ yesil, `test_openrouter_upstream` + `test_gateway_streaming` + yeni `test_billing_webhook` yesil.

### Faz 2 — VS Code Fork Rebrand + BYOK Provider Hook (1–1.5 hafta) — EN KRITIK FAZ

**Hedef:** VS Code'un agent motoru senin gateway'ine konusur. evren-agent YOK, platform/agentHost kullanilir.

- **Dosyalar:** `vscode/product.json`, `vscode/src/vs/platform/agentHost/common/agentHostByokLm.ts` (veya yeni `evrenLmProvider.ts`), `vscode/src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts`, `vscode/src/vs/platform/agentHost/node/copilot/byokLmProxyService.ts`

1. **product.json rebrand:**
   ```json
   "nameShort": "Ufuk",
   "nameLong": "Ufuk Agent",
   "applicationName": "ufuk",
   "dataFolderName": ".ufuk",
   "win32DirName": "Ufuk",
   "win32NameVersion": "Ufuk",
   "darwinBundleIdentifier": "com.ufuk.agent",
   "urlProtocol": "ufuk",
   "agentsTelemetryAppName": "ufuk",
   "extensionsGallery": null
   ```
   `win32AppId` yeni GUID. `builtInExtensions` icinden `cpp`, `go`, `java`, `python`, `rust` gibi dil eklentilerini cikar, sadece `json`, `markdown`, `typescript-basics` birak.

2. **BYOK Provider (EN ONEMLI IS) — 2 secenek:**

   **Secenek A (onerilen) — vscode.lm extension olarak:**
   - Yeni bir extension yaz: `vscode/extensions/evren-provider/` (veya `vscode/extensions/ufuk-provider/`)
   - `package.json` icinde `contributes.languageModels` ile provider kaydet
   - `vscode.lm.registerLanguageModelProvider("evren", provider)` — `provideLanguageModelChatResponse` icinde `POST https://api.ufuk.ai/v1/chat/completions` SSE
   - Avantaj: `src/vs/platform/agentHost` cekirdegine HIC dokunmaz, sadece extension. Upstream merge conflict sifir.

   **Secenek B — BYOK bridge'e dogrudan:**
   - `src/vs/platform/agentHost/common/agentHostByokLm.ts` icine `evren` vendor'u ekle
   - `src/vs/platform/agentHost/node/copilot/byokLmProxyService.ts` icinde `IByokLmChatRequest` → `POST /v1/chat/completions` SSE cevir
   - Dezavantaj: cekirdek dosyaya dokunur, merge conflict riski var.

   **Onerilen: Secenek A.** Extension olarak yaz, cekirdege dokunma.

   SSE akisi:
   ```
   Agent harness (Claude/Copilot/Codex)
     → IAgent.chats.sendMessage(chatUri, { vendor: "evren", modelId: "fast", input, tools })
     → AgentService → BYOK bridge (agentHostByokLm.ts)
     → vscode.lm provider (evren) → POST /v1/chat/completions SSE
     → evren-backend → OpenRouter → SSE stream
     → IByokLmChatResult { output, usage } → harness → UI (tool timeline, diff, checkpoint)
   ```

3. **Auth hook:**
   - `ISecretStorageService` ile login view — `POST /auth/login` → `access_token` (900s) + `refresh_token` → `secretStorage.store("ufuk:jwt", token)`.
   - Her LLM isteğinde `Authorization: ******` header ekle, `401` → `POST /auth/refresh` single-flight.

4. **Model picker:**
   - `chatModes.ts` / `modelSelection.ts` — picker listesini BYOK provider'dan doldur (`IByokLmModelInfo[]`), secilen `vendor/modelId` → `model` alanina yaz. Gateway `sanitize_request()` zaten alias → `upstream_model_id` ceviriyor.

5. **Quota hook:**
   - `chatQuotaNotification.ts` + `chatErrorMessages.ts` — `402 quota_exceeded` → "Kredin bitti, plan yukselt" + `GET /usage` ile kalan kredi goster, `429` → `Retry-After` countdown.

6. **Build test:**
   - `npm run compile` (VS Code gulp) + `electron` launch, chat'te Agent modunda "hello" → BYOK → gateway → OpenRouter → SSE stream dogrula. Tool call (dosya yaz) → diff → checkpoint dogrula.

- Kabul: VS Code `Ufuk` adiyla acilir, login olur, chat'te Agent modunda model picker tier alias'lari gosterir, mesaj SSE akar, tool call calisir (dosya yazar, diff gosterir), 402/429 notification cikar. Cunku platform/agentHost'un kendi loop'u.

### Faz 3 — Workbench Sadelestirme (3–5 gun)

**Hedef:** IDE kalabaligi gider, sadece agent + editor + explorer. "Open in Agents" window korunur.

- **Dosyalar:** `vscode/src/vs/workbench/contrib/*`, `vscode/src/vs/workbench/browser/workbench.ts`, `vscode/product.json`

1. **Gizlenecek contrib'ler (dosya silme YOK, `when: false` veya `isEnabled: false`):**
   - `terminal` (`workbench/contrib/terminal`), `debug` (`workbench/contrib/debug`), `scm` (`workbench/contrib/scm`), `search` (`workbench/contrib/search`), `testing` (`workbench/contrib/testing`), `notebook` (`workbench/contrib/notebook`), `mergeEditor`, `timeline`, `outline`, `extensions` (marketplace view).
2. **Birakilacaklar:** `files` (explorer), `editor`, `chat` (Agent modu), `output`, `problems` (opsiyonel), `welcomeAgentSessions` (hosgeldin ekrani), `agentSessions` (Agents Window).
3. **Activity Bar gizle (opsiyonel):** `workbench.activityBar.location: "hidden"` default settings, `chat` view'i default `sideBar` yap, `workbench.startupEditor: "agentSessionsWelcomePage"` (Agents hosgeldin ekrani).
4. **"Agent System'den IDE'ye gec" butonu YOK** — zaten workbench tek. Gerekirse `View > Appearance` menusu gizlenir.

- Kabul: Ufuk acildiginda sadece Explorer + Editor + Chat (Agent modu) + Agents Window gorunur, terminal/debug/scm yok, `Help > About` "Ufuk" gosterir.

### Faz 4 — MCP / Plugin Gorsel Duzenleme (3–5 gun)

**Hedef:** MCP sade ve guvenli.

- **Dosyalar:** `vscode/src/vs/workbench/contrib/mcp/*`, `vscode/src/vs/workbench/contrib/chat/browser/*` (CSS)

1. `mcpServersView.ts` filtre: sadece `mcp.json` icinde `allowed: true` olan sunuculari goster, kullanici rastgele MCP ekleyemez (veya eklerse approval modal).
2. `mcpGatewayService.ts` — MCP tool call'lari VS Code'un permission engine'inden gecer (zaten var, sadece dogrula).
3. CSS: `chat/browser/chatView.css`, `mcp/mcpServersView.css` — VS Code CSS variable (`--vscode-*`) ile tema uyumlu, Tailwind yok.
4. Marketplace kapali (`extensionsGallery: null`) — ileride kendi gallery'n olursa `product.json` icinde URL ver.

- Kabul: MCP view sadece onayli sunuculari gosterir, tool call approval modal cikar, CSS bozulmaz.

### Faz 5 — Odeme + Abonelik UI (1 hafta)

**Hedef:** Kullanici para verir, plan otomatik atanir.

- **Dosyalar:** `evren-backend/app/routers/billing.py`, `evren-backend/app/models/plan.py` (stripe_price_id), `vscode/src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts`

1. Stripe (veya Iyzico) webhook: `POST /billing/webhook` → imza dogrula → `user_id` bul (email) → `assign_plan(db, user_id, plan_id)` → `period_start/end` korunur.
2. `GET /plans` + `GET /usage` + `GET /me` ile chat icinde "Plan: Pro — 12.3/100 kredi" indicator (VS Code status bar).
3. `GET /billing/portal` → Stripe Customer Portal link (plan yukselt/dusur).
4. Test: Stripe CLI `stripe trigger checkout.session.completed` → webhook → DB `subscriptions` ACTIVE dogrula.

- Kabul: Test kartiyla odeme → webhook → plan atanir, chat'te kredi indicator guncellenir, 402 sonrasi "Yukselt" butonu portal'a gider.

### Faz 6 — Build, Test, Release (1 hafta)

**Hedef:** `Ufuk-Setup-0.1.0.exe` uret, e2e yesil.

- **Dosyalar:** `vscode/gulpfile.mjs`, `vscode/build/*`, `evren-backend/tests/*`

1. Her fazda: `pytest -q` (backend) — asla kirik birakma.
2. Playwright Electron e2e: `login → Agent modunda "The test in this repo is failing. Fix it and verify." → tool call (edit + npm test) → diff → undo` — `docs/screenshots` ile. VS Code'un kendi e2e altyapisini kullan (`vscode/test/electron`).
3. Build: `vscode: npm run gulp vscode-win32-x64` + `electron-builder --win nsis` (unsigned, `release/Ufuk-Setup-0.1.0.exe`, ~100–150 MB). `product.json` `win32AppId` yeni GUID.
4. `README.md` guncelle: `evren-backend` (docker), `vscode` (gulp) nasil calistirilir.
5. `docs/PROGRESS.md` her fazda append (test sayilari, ekran goruntuleri).

- Kabul: Tum testler yesil, e2e fix-it gecer, installer uretilir, `README` ile sifirdan kurulum calisir.

---

## 3. Dosya Haritasi (YENI / DEGISECEK — evren-agent YOK, extensions/copilot degil)

```
evren-backend/
  app/routers/billing.py              ← YENI (Stripe/Iyzico webhook)
  app/models/plan.py                  ← stripe_price_id kolonu
  app/services/rate_limiter.py        ← global limiter
  app/logging.py                      ← Sentry
  scripts/derive_credit_rates.py      ← YENI
  tests/test_billing_webhook.py       ← YENI
vscode/
  product.json                        ← rebrand (Ufuk)
  extensions/evren-provider/          ← YENI EXTENSION (Secenek A, onerilen)
    package.json                      ← contributes.languageModels
    src/evrenProvider.ts              ← vscode.lm provider → POST /v1/chat/completions SSE
  src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts ← hook
  src/vs/workbench/contrib/mcp/mcpServersView.ts ← filtre
docs/
  ARASTIRMA-RAPORU.md                 ← mevcut
  IMPLEMENTATION-PLAN.md              ← bu dosya (duzeltilmis v2)
  PROGRESS.md                         ← her fazda guncellenecek
pnpm-workspace.yaml                   ← duzelt (evren-agent satiri sil)
```

**OLMAYACAKLAR:** `evren-agent/`, `frontend/` (eski Ufuk UI) — cop, geri gelmeyecek. `extensions/copilot` degistirilmeyecek — beyin `platform/agentHost`, copilot sadece 3 harness'tan biri.

---

## 4. Riskler ve Onlemler

| Risk | Onlem |
|---|---|
| VS Code upstream conflict | BYOK extension olarak yaz, `src/vs/platform/agentHost` cekirdegine dokunma, ayda bir `git -C vscode pull` |
| OpenRouter tek anahtar limiti | Faz 1 global limiter + circuit breaker (zaten var) |
| Prompt injection | VS Code'un permission engine'i zaten var, sadece dogrula |
| Kod imzalama yok | NSIS unsigned (TODO: cert + auto-update) |
| pnpm-workspace bozuk | Faz 0'da duzelt |

---

## 5. Zaman Cizelgesi (Gercekci)

| Faz | Sure | Bagimlilik |
|---|---|---|
| 0 Repo duzeltme | 1 gun | — |
| 1 Backend hardening | 1 hafta | Faz 0 |
| 2 BYOK provider hook | 1–1.5 hafta | Faz 1 |
| 3 Workbench sadelestirme | 3–5 gun | Faz 2 |
| 4 MCP/plugin | 3–5 gun | Faz 2 |
| 5 Odeme | 1 hafta | Faz 1 |
| 6 Build/e2e/release | 1 hafta | Tumu |
| **Toplam** | **~5–6 hafta** | |

---

*Bu plan kod degisikligi icermez, sadece yol haritasidir. evren-agent YOK, extensions/copilot beyin degil — gercek beyin platform/agentHost. BYOK extension olarak baglanilacak. Her faz kucuk commit'lerle, testler yesilken ilerler.*
