# Ufuk Agent System — Implementasyon Plani (DUZELTILMIS)

> Tarih: 2026-09-26
> Hedef: Claude Code / Codex ayari masaustu coding agent (Windows oncelikli)
> Ilke: Sunucu MINIMAL (sadece backend + DB), agent motoru TAMAMEN masaustunde (VS Code'un kendi motoru)
> Onceki hata: evren-agent geri getirilsin yazmistik — YANLIS. evren-agent COP, VS Code'un agent motoru zaten var ve daha iyi.

---

## 0. Duzeltme — Neden evren-agent Yok?

Onceki planda "evren-agent geri kopyala" yazdik. Bu hataydi. Senin dedigin dogru:

- **evren-agent** = eski Ufuk'un amatörce yazilmis `loop.ts` + `local-runner` + `workspace.ts` + `shell.ts`. 237 testi var ama VS Code'un 10 yillik agent altyapisinin yaninda oyuncak.
- **VS Code'un kendi agent motoru** zaten var ve fork'layinca bedavaya senin oluyor. Sifirdan loop yazmaya gerek YOK.

VS Code'da agent 3 parcadan olusur:

| Parca | Dosya | Ne yapar |
|---|---|---|
| Arayuz + Modlar | `vscode/src/vs/workbench/contrib/chat/` — `chat.ts`, `chatModes.ts`, `chatQuotaNotification.ts` | Ask/Edit/Agent modlari, tool timeline, diff viewer, checkpoint/undo, quota UI |
| Beyin (loop) | `vscode/extensions/copilot/` | Asil multi-step agent loop, tool calling, MCP cagrilari. VS Code OSS ile geliyor |
| LLM baglantisi | `vscode/src/vs/workbench/contrib/chat/common/languageModels.ts` — `ILanguageModelService` | Copilot'a bagli, biz kesip `evren-backend`'e baglayacagiz |

Yani `evren-agent/packages/agent-core/src/agent/loop.ts` falan — hepsi VS Code'da daha iyisi var. Cift motor sacmalik.

**Dogru mimari:**

```
[Masaustu — VS Code Fork = Ufuk]          [Sunucu — evren-backend]
┌────────────────────────────┐            ┌──────────────────────┐
│ VS Code workbench          │  HTTPS/SSE │ FastAPI + Postgres   │
│  ├─ chat (Agent modu)     │◄──────────►│  + Redis             │
│  ├─ editor + explorer     │  /v1/chat/ │  /auth, /plans,      │
│  ├─ copilot ext (loop)    │  /auth/*   │  /usage, /v1/models  │
│  └─ evrenProvider.ts ─────┘  JWT       │  OpenRouter proxy    │
│     (gateway'e SSE)        │            │  kredi/rate-limit    │
│  Storage: VS Code          │            │  tek API key sende   │
│  globalState/workspaceState│            └──────────────────────┘
└────────────────────────────┘
  Dosya/shell/chat gecmisi
  TAMAMEN masaustunde.
  Sunucuda SADECE users,
  subscriptions, usage_events,
  plans, tiers var.
```

---

## 1. Mimari Kararlar (Degismez)

### 1.1 Sunucu minimal — ne var ne yok

**Var:** `evren-backend/app/` — `config.py` (UPSTREAM_BASE_URL, UPSTREAM_API_KEY), `routers/gateway.py` (`POST /v1/chat/completions` SSE), `routers/auth.py` (register/login/refresh), `routers/plans.py`, `routers/admin.py`, `services/credits.py` (Redis ledger), `services/upstream.py` (httpx proxy), `services/rate_limiter.py`, `models/` (Plan, Tier, Subscription, UsageEvent, User).

**Yok:** Kullanici dosyalari, sohbet gecmisi, proje haritasi — hepsi masaustunde. Sunucu sadece abonelik + LLM proxy. GDPR icin de dogru.

**Yok:** evren-agent, frontend (eski Ufuk UI), local-runner — hepsi cop, VS Code karsiliyor.

### 1.2 Masaustu — VS Code fork kapsami

- **Fork derinligi MINIMAL:** Sadece `vscode/product.json` rebrand + `vscode/extensions/copilot/src/extension/byok/evrenProvider.ts` (YENI dosya, 1 dosya) + `chatQuotaNotification.ts` quota hook. `src/vs/workbench/contrib/*` dosya silme YOK, sadece `when: false` ile gizleme.
- **Guncelleme:** `vscode/` `.gitignore`'da, ayri git history. `git -C vscode fetch origin && git merge` ayda bir. Hook'lar `extensions/` icinde oldugu icin conflict riski dusuk.
- **Storage:** Sohbet gecmisi VS Code'un `globalState` / `workspaceState` veya `src/vs/platform/storage/` uzerinden — ayri SQLite kurmaya gerek yok.

### 1.3 Model / kredi haritasi

- `ModelTier.alias` (örn. `fast`, `pro`, `strong`) → `upstream_model_id` (örn. `openai/gpt-4o`, `anthropic/claude-3.5-sonnet`). Kullanici alias secer, gateway `sanitize_request()` ile upstream ID'ye cevirir. `max_tokens` plan limitine kirpilir.
- Kredi: `input_credits_per_1k` + `output_credits_per_1k` DB'de, `scripts/derive_credit_rates.py` ile USD → kredi cevimi. Redis `credits:{user}:{period_key}` atomik ledger. `402 quota_exceeded`, `429 rate_limited` (Retry-After).

---

## 2. Fazlar — En Ince Ayrinti (evren-agent YOK)

### Faz 0 — Repo Duzeltme (1 gun)

**Hedef:** `pnpm install` ve `pytest` yesil, evren-agent referansi temizlenir.

- `pnpm-workspace.yaml` duzelt:
  ```yaml
  # ONCEKI (bozuk):
  packages:
    - evren-agent/packages/*
    - frontend
  # YENI (dogru):
  packages:
    - frontend  # sadece fallback icin, VS Code fork ana UI
  # veya frontend de yoksa bos birak, sadece evren-backend kalir
  ```
  `allowBuilds` korunur ama `better-sqlite3` artik gerekmez (VS Code storage kullaniyor).
- `frontend/` ve `evren-agent/` klasorleri ZATEN yok — dogru, oyle kalsin. Eski `C:\Users\Yusuf\Desktop\ufuk agent system\frontend` ve `evren-agent` legacy olarak durur, yeni projeye kopyalanmaz.
- `README.md` guncelle: "Masaustu = VS Code fork (Ufuk), Sunucu = evren-backend, evren-agent yok" yaz.
- Kabul: `pnpm install` (varsa) + `evren-backend: pytest -q` yesil.

### Faz 1 — Backend Hardening (1 hafta)

**Hedef:** Production'a hazir gateway. Dosyalar: `evren-backend/app/config.py`, `app/services/upstream.py`, `app/services/credits.py`, `app/routers/gateway.py`, `app/services/rate_limiter.py`, `app/routers/admin.py`, `app/main.py`, `alembic/`, `scripts/seed.py`, `tests/*`

1. **OpenRouter dogrulama:** `tests/test_openrouter_upstream.py` zaten var — mock OpenRouter SSE (final chunk'ta `usage`, `{"error":{"message","code":123}}`, `429` + `X-RateLimit-Reset: Wed, 21 Oct 2026 07:28:00 GMT` → `Retry-After` + `resets_at` forward, `usage.cost` strip). `app/services/upstream.py: _parse_resets_at` HTTP-date parse ekle.
2. **Global rate limiter:** `app/services/rate_limiter.py` icine `global_upstream_limiter` (Redis `INCR` + `EXPIRE`, örn. 60 req/min tum kullanicilar icin) — tek OpenRouter anahtarini korur. `gateway.py: _reserve` oncesi kontrol.
3. **Odeme webhook:** `app/routers/billing.py` YENI dosya — `POST /billing/webhook` (Stripe/Iyzico imzasi dogrula → `subscription_service.assign_plan(db, user_id, plan_id)`). `Plan` icine `stripe_price_id` kolonu ekle (alembic migration). `app/main.py` router ekle.
4. **Observability:** `structlog` zaten var — Sentry ekle (`sentry-sdk[fastapi]`), `app/logging.py` icine `sentry_init` (env `SENTRY_DSN`). `/health` icine `GET /health/ready` (DB+Redis ping).
5. **Backup:** `docs/backup-restore.md` + `docker-compose.prod.yml` (DB/Redis host port kapali, Caddy TLS).
6. **Kredi formulu:** `scripts/derive_credit_rates.py` + README: `rate = usd_per_1k / credits_per_usd * (1+margin)` — operator gercek fiyatlarla tier uretir.
- Kabul: `pytest -q` 115+ yesil, `test_openrouter_upstream` + `test_gateway_streaming` + yeni `test_billing_webhook` yesil.

### Faz 2 — VS Code Fork Rebrand + Provider Hook (1–1.5 hafta) — EN KRITIK FAZ

**Hedef:** VS Code, senin gateway'ine konusur. evren-agent YOK, VS Code'un kendi loop'u kullanilir.

- **Dosyalar:** `vscode/product.json`, `vscode/extensions/copilot/src/extension/byok/evrenProvider.ts` (YENI), `vscode/src/vs/workbench/contrib/chat/common/languageModels.ts`, `vscode/src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts`, `vscode/src/vs/workbench/services/authentication/*`

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
   `win32AppId` yeni GUID uret. `builtInExtensions` icinden `cpp`, `go`, `java`, `python`, `rust` gibi dil eklentilerini cikar, sadece `json`, `markdown`, `typescript-basics` birak.

2. **evrenProvider.ts YAZ (tek yeni dosya, en onemli is):**
   - `ILanguageModelProvider` implemente et.
   - `provideLanguageModels()` → `GET /v1/models` veya `GET /plans` + `GET /tiers` ile model listesi (alias: fast/pro/strong, displayName, contextWindow).
   - `provideCompletion()` → `POST /v1/chat/completions` SSE:
     ```
     POST https://api.ufuk.ai/v1/chat/completions
     Authorization: ****** <JWT>
     Body: { model: "fast", messages: [...], stream: true, stream_options: {include_usage:true}, tools: [...] }
     ```
     SSE `data: {...}\n\n` parse, `usage` strip (gateway zaten yapiyor ama double-check), `model` alias'a rewrite.
   - Hata: `402` → `quota_exceeded`, `429` → `rate_limited` + `Retry-After` header oku.

3. **Auth hook:**
   - `ISecretStorageService` + `IAuthenticationService` ile login view — `POST /auth/login` → `access_token` (900s) + `refresh_token` → `secretStorage.store("ufuk:jwt", token)`.
   - Her LLM isteğinde `Authorization` header ekle, `401` → `POST /auth/refresh` single-flight (gateway `auth.ts` zaten var).

4. **Model picker:**
   - `chatSelectedModel.ts` / `modelSelection.ts` — picker listesini `evrenProvider`'dan doldur, secilen `alias` → `model` alanina yaz. Gateway `sanitize_request()` zaten alias → `upstream_model_id` ceviriyor.

5. **Quota hook:**
   - `chatQuotaNotification.ts` + `chatErrorMessages.ts` — `402 quota_exceeded` → "Kredin bitti, plan yukselt" + `GET /usage` ile kalan kredi goster, `429` → `Retry-After` countdown.

6. **Build test:**
   - `npm run compile` (VS Code gulp) + `electron` launch, chat'te "hello" → gateway → OpenRouter → SSE stream dogrula.

- Kabul: VS Code `Ufuk` adiyla acilir, login olur, chat'te model picker tier alias'lari gosterir, mesaj SSE akar, 402/429 notification cikar. Agent modu (Edit/Agent) calisir, dosya yazar, diff gosterir — cunku VS Code'un kendi loop'u.

### Faz 3 — Workbench Sadelestirme (3–5 gun)

**Hedef:** IDE kalabaligi gider, sadece agent + editor + explorer.

- **Dosyalar:** `vscode/src/vs/workbench/contrib/*`, `vscode/src/vs/workbench/browser/workbench.ts`, `vscode/product.json`

1. **Gizlenecek contrib'ler (dosya silme YOK, `when: false` veya `isEnabled: false`):**
   - `terminal` (`workbench/contrib/terminal`), `debug` (`workbench/contrib/debug`), `scm` (`workbench/contrib/scm`), `search` (`workbench/contrib/search`), `testing` (`workbench/contrib/testing`), `notebook` (`workbench/contrib/notebook`), `mergeEditor`, `timeline`, `outline`, `extensions` (marketplace view).
2. **Birakilacaklar:** `files` (explorer), `editor`, `chat` (agent), `output`, `problems` (opsiyonel).
3. **Activity Bar gizle (opsiyonel):** `workbench.activityBar.location: "hidden"` default settings, `chat` view'i default `sideBar` yap, `workbench.startupEditor: "none"`.
4. **"Agent System'den IDE'ye gec" butonu YOK** — zaten workbench tek. Gerekirse `View > Appearance` menusu gizlenir.

- Kabul: Ufuk acildiginda sadece Explorer + Editor + Chat gorunur, terminal/debug/scm yok, `Help > About` "Ufuk" gosterir.

### Faz 4 — MCP / Plugin Gorsel Duzenleme (3–5 gun)

**Hedef:** MCP sade ve guvenli.

- **Dosyalar:** `vscode/src/vs/workbench/contrib/mcp/*`, `vscode/src/vs/workbench/contrib/chat/browser/*` (CSS)

1. `mcpServersView.ts` filtre: sadece `mcp.json` icinde `allowed: true` olan sunuculari goster, kullanici rastgele MCP ekleyemez (veya eklerse approval modal).
2. `mcpGatewayService.ts` — MCP tool call'lari VS Code'un permission engine'inden gecer (zaten var, sadece dogrula).
3. CSS: `chat/browser/chatView.css`, `mcp/mcpServersView.css` — VS Code CSS variable (`--vscode-*`) ile tema uyumlu, Tailwind yok. Gerekirse `workbench` theme override.
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

1. Her fazda: `pnpm typecheck && pnpm lint && pnpm test` (varsa) + `pytest -q` (backend) — asla kirik birakma.
2. Playwright Electron e2e: `login → add sample project → "The test in this repo is failing. Fix it and verify." → approve edit + npm test → diff → undo` — `docs/screenshots` ile.
3. Build: `vscode: npm run gulp vscode-win32-x64` + `electron-builder --win nsis` (unsigned, `release/Ufuk-Setup-0.1.0.exe`, ~100–150 MB). `product.json` `win32AppId` yeni GUID.
4. `README.md` guncelle: `evren-backend` (docker), `vscode` (gulp) nasil calistirilir.
5. `docs/PROGRESS.md` her fazda append (test sayilari, ekran goruntuleri).

- Kabul: Tum testler yesil, e2e fix-it gecer, installer uretilir, `README` ile sifirdan kurulum calisir.

---

## 3. Dosya Haritasi (YENI / DEGISECEK — evren-agent YOK)

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
  extensions/copilot/src/extension/byok/evrenProvider.ts  ← YENI (TEK KRITIK DOSYA)
  src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts ← hook
  src/vs/workbench/contrib/mcp/mcpServersView.ts ← filtre
docs/
  ARASTIRMA-RAPORU.md                 ← mevcut
  IMPLEMENTATION-PLAN.md              ← bu dosya (duzeltilmis)
  PROGRESS.md                         ← her fazda guncellenecek
pnpm-workspace.yaml                   ← duzelt (evren-agent satiri sil)
```

**OLMAYACAKLAR:** `evren-agent/`, `frontend/` (eski Ufuk UI) — cop, geri gelmeyecek. VS Code'un kendi agent motoru kullanilacak.

---

## 4. Riskler ve Onlemler

| Risk | Onlem |
|---|---|
| VS Code upstream conflict | Hook'lar `extensions/copilot` icinde, `src/vs/*` degisikligi minimal, ayda bir `git -C vscode pull` |
| OpenRouter tek anahtar limiti | Faz 1 global limiter + circuit breaker (zaten var) |
| Prompt injection | VS Code'un permission engine'i zaten var, sadece dogrula |
| Kod imzalama yok | NSIS unsigned (TODO: cert + auto-update) |
| pnpm-workspace bozuk | Faz 0'da duzelt |

---

## 5. Zaman Cizelgesi (Gercekci — evren-agent olmadan daha kisa)

| Faz | Sure | Bagimlilik |
|---|---|---|
| 0 Repo duzeltme | 1 gun | — |
| 1 Backend hardening | 1 hafta | Faz 0 |
| 2 VS Code provider hook | 1–1.5 hafta | Faz 1 |
| 3 Workbench sadelestirme | 3–5 gun | Faz 2 |
| 4 MCP/plugin | 3–5 gun | Faz 2 |
| 5 Odeme | 1 hafta | Faz 1 |
| 6 Build/e2e/release | 1 hafta | Tumu |
| **Toplam** | **~5–6 hafta** | |

Onceki plan 6–7 haftaydi, evren-agent'i cikarinca 5–6 haftaya dustu. Cunku en agir is (loop yazmak) zaten VS Code'da hazir.

---

*Bu plan kod degisikligi icermez, sadece yol haritasidir. evren-agent YOK, VS Code'un kendi agent motoru kullanilacak. Her faz kucuk commit'lerle, testler yesilken ilerler.*
