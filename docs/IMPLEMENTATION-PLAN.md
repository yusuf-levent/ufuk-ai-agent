# Ufuk Agent System — Düzeltilmiş Implementasyon Planı

> Tarih: 2026-09-26
> Hedef: Claude Code / Codex ile yarışacak masaüstü coding agent (Windows öncelikli)
> İlke: Sunucu minimal (backend + DB + dosya/sohbet persistence), agent loop masaüstünde
> Önceki rapor: `docs/ARASTIRMA-RAPORU.md` — bu doküman onun hatalarını düzeltir ve en ince ayrıntıya iner

---

## 0. Önceki Plan Neden Yetersizdi — Düzeltmeler

| Sorun | Önceki Plan | Doğrusu |
|---|---|---|
| `evren-agent` silinmiş | Yeni projede yok sayılmış | **Geri getirilmeli** — `agent-core` (loop, provider, context, permissions, checkpoints) + `local-runner` (workspace, tools, shell, shadow-store) 237 test ile en değerli parça. VS Code fork bunu sıfırdan yazamaz |
| `pnpm-workspace.yaml` bozuk | `evren-agent/packages/*` + `frontend` referans ediyor ama klasörler yok | Faz 0'da düzelt: `evren-agent` geri gelinceye kadar `packages: [frontend]` veya `evren-agent` geri ekle |
| VS Code fork stratejisi fazla iyimser | "VS Code'u al, provider hook'la, bitti" | VS Code fork **bakım maliyeti çok yüksek** (ayda ~500 commit upstream). Strateji: **minimal fork** — sadece `product.json` + `extensions/copilot` içinde `evrenProvider.ts`, core `src/vs/*` değişikliği sıfıra yakın. Workbench sadeleştirme `when` clause ile, dosya silerek değil |
| Backend "hazır" sanılmış | Ödeme yok, global rate limit yok, observability yok | Faz 1'de hardening şart (Stripe/Iyzico, global limiter, Sentry, backup) |
| IDE sadeleştirme belirsiz | "terminal/debug/scm gizle" | Hangi contribution, hangi dosyada, nasıl gizlenir — Faz 4'te dosya dosya liste |
| Token/kredi akışı yüzeysel | Sadece reserve/settle anlatılmış | Faz 1'de OpenRouter gerçek SSE formatı, `usage.cost` strip, `X-RateLimit-Reset` HTTP-date parse, disconnect estimate — testlerle doğrulanmalı |
| Test/build planı yok | "gulp + electron-winstaller" | Faz 7'de `electron-vite` + `electron-builder` NSIS, Playwright Electron e2e, `pnpm typecheck && lint && test` her fazda |

---

## 1. Mimari Kararlar (Değişmez)

### 1.1 Nerede ne çalışır

```
[Masaüstü — Electron App]                [Sunucu — evren-backend]
┌─────────────────────────┐              ┌──────────────────────┐
│ Main process            │  HTTPS/SSE   │ FastAPI + Postgres   │
│  ├─ evren-agent         │◄────────────►│  + Redis             │
│  │   ├─ agent-core      │  /v1/chat/*  │  auth/plans/tiers/   │
│  │   └─ local-runner    │  /auth/*     │  subscriptions/      │
│  ├─ gateway client      │  /usage      │  credits/rate-limit/ │
│  ├─ safeStorage (DPAPI) │              │  upstream proxy      │
│  └─ IPC (zod-validated) │              │  OpenRouter          │
│ Preload (contextBridge) │              └──────────────────────┘
│ Renderer                │
│  ├─ VS Code workbench   │  ← fork, sadece chat+editor+explorer
│  │   (chat contrib)     │
│  └─ veya Monaco+custom  │  ← fallback eğer fork ağır gelirse
│     chat (eski Ufuk UI) │
└─────────────────────────┘
```

- **Agent loop asla sunucuda değil** — `agent-core/src/agent/loop.ts` masaüstünde, `local-runner` ile dosyaya/shell'e erişir. Sunucu sadece LLM proxy + auth + kredi.
- **Kullanıcı dosyaları/sohbetler:** Sohbet geçmişi ve proje haritası **masaüstünde** (SQLite `better-sqlite3` + JSONL fallback, `local-runner/src/db/*`). Sunucuda sadece `users`, `subscriptions`, `usage_events`, `plans`, `tiers` — GDPR/privacy için minimal.
- **Neden VS Code fork?** Eski Ufuk UI (Composer/Transcript/DiffViewer) sıfırdan ve zayıf. VS Code'un editor + diff + chat + tool timeline'ı 10 yıllık. Fork ile bedavaya geliyor.

### 1.2 VS Code fork kapsamı

- **Fork derinliği:** `product.json` rebrand + `extensions/copilot/src/extension/byok/evrenProvider.ts` (yeni dosya) + `src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts` quota hook. `src/vs/workbench/contrib/*` silme yok, sadece `package.json` contribution `when: false` ile gizleme.
- **Güncelleme:** `vscode/` ayrı git history, `.gitignore`'da. `git -C vscode fetch origin && git merge` ile ayda bir rebase. Hook'lar `extensions/` içinde olduğu için conflict riski düşük.

### 1.3 Model / kredi haritası

- `ModelTier.alias` (örn. `fast`, `pro`, `strong`) → `upstream_model_id` (örn. `openai/gpt-4o`, `anthropic/claude-3.5-sonnet`). Kullanıcı alias seçer, gateway `sanitize_request()` ile upstream ID'ye çevirir. `max_tokens` plan limitine kırpılır.
- Kredi: `input_credits_per_1k` + `output_credits_per_1k` DB'de, `scripts/derive_credit_rates.py` ile USD → kredi çevrimi. Redis `credits:{user}:{period_key}` atomik ledger.

---

## 2. Fazlar — En İnce Ayrıntı

### Faz 0 — Repo Sağlamlaştırma (1–2 gün)

**Hedef:** `pnpm install` ve `pytest` yeşil.

- `pnpm-workspace.yaml` düzelt:
  - Seçenek A (önerilen): `evren-agent/` geri kopyala (`C:\Users\Yusuf\Desktop\ufuk agent system\evren-agent` → `C:\Users\Yusuf\Desktop\ufuk_agent_system\evren-agent`), `packages: [evren-agent/packages/*, frontend]` korunur.
  - Seçenek B: `evren-agent` gelene kadar `packages: [frontend]` yap, `allowBuilds` korunur.
- `frontend/` iskeletini geri getir (eski `frontend/electron/*`, `frontend/src/*`, `frontend/package.json`, `electron-vite.config.ts`). Eski Ufuk frontend'i VS Code fork gelene kadar fallback UI olarak kalır.
- `vscode/` `.gitignore`'da kalır, `README.md` güncellenir (iki UI stratejisi anlatılır).
- Kabul: `pnpm install` (root) + `pnpm -r test` (evren-agent) + `evren-backend: pytest -q` yeşil.

### Faz 1 — Backend Hardening (1 hafta)

**Hedef:** Production'a hazır gateway.

- **Dosyalar:** `evren-backend/app/config.py`, `app/services/upstream.py`, `app/services/credits.py`, `app/routers/gateway.py`, `app/services/rate_limiter.py`, `app/routers/admin.py`, `app/main.py`, `alembic/`, `scripts/seed.py`, `tests/*`
- **Adımlar:**
  1. OpenRouter doğrulama: `tests/test_openrouter_upstream.py` zaten var — mock OpenRouter SSE (final chunk'ta `usage`, `{"error":{"message","code":123}}`, `429` + `X-RateLimit-Reset: Wed, 21 Oct 2026 07:28:00 GMT` → `Retry-After` + `resets_at` forward, `usage.cost` strip). `app/services/upstream.py: _parse_resets_at` HTTP-date parse ekle (zaten planlanmış, uygula).
  2. Global rate limiter: `app/services/rate_limiter.py` içine `global_upstream_limiter` (Redis `INCR` + `EXPIRE`, örn. 60 req/min tüm kullanıcılar için) — tek OpenRouter anahtarını korur. `gateway.py: _reserve` öncesi kontrol.
  3. Ödeme webhook: `app/routers/billing.py` yeni dosya — `POST /billing/webhook` (Stripe/Iyzico imzası doğrula → `subscription_service.assign_plan(db, user_id, plan_id)`). `Plan` içine `stripe_price_id` / `iyzico_plan_id` kolonu ekle (alembic migration). `app/main.py` router ekle.
  4. Observability: `structlog` zaten var — Sentry ekle (`sentry-sdk[fastapi]`), `app/logging.py` içine `sentry_init` (env `SENTRY_DSN`). `/health` içine `GET /health/ready` (DB+Redis ping).
  5. Backup: `docs/backup-restore.md` + `docker-compose.prod.yml` (DB/Redis host port kapalı, Caddy TLS) — zaten planlanmış, uygula.
  6. `scripts/derive_credit_rates.py` + README formül: `rate = usd_per_1k / credits_per_usd * (1+margin)` — operatör gerçek fiyatlarla tier üretir.
- **Kabul:** `pytest -q` 115+ test yeşil, `test_openrouter_upstream` + `test_gateway_streaming` + yeni `test_billing_webhook` yeşil, `docker compose -f docker-compose.prod.yml config` valid.

### Faz 2 — Agent Core Geri Getirme + Güçlendirme (1 hafta)

**Hedef:** Claude/Codex ayarında loop.

- **Dosyalar:** `evren-agent/packages/agent-core/src/agent/loop.ts`, `agent/system-prompt.ts`, `context/manager.ts`, `context/estimator.ts`, `provider/openai-compat.ts`, `provider/sse.ts`, `permissions/policy.ts`, `checkpoints.ts` + `local-runner/src/tools/*`, `workspace.ts`, `permissions/*`
- **Adımlar:**
  1. `evren-agent` geri kopyala, `pnpm -r test` yeşil doğrula (237 test).
  2. Loop güçlendirme: `loop.ts` içine `maxSteps` (plan'dan `max_output_tokens_per_request` ile uyumlu), `loop-detector.ts` zaten var — eşik sıkılaştır, `context/manager.ts` compaction (eski mesajları özetle, `estimator.ts` ile token say).
  3. Tool set: `read`, `write`, `edit`, `glob`, `grep`, `shell`, `git` zaten var — `shell.ts` içine `run_command` timeout + output cap + process-tree kill (zaten var, test et). Yeni: `web_fetch` (opsiyonel, izinli domain listesi).
  4. Permission: `permissions/policy.ts` + `dangerous.ts` floors — `prompt-injection.test.ts` ekle (tool output içindeki gizli talimatlar engellenir, approval modal gerçek komutu gösterir).
  5. Checkpoint/undo: `checkpoints.ts` + `local-runner/src/checkpoints/shadow-store.ts` — her `write/edit` öncesi shadow copy, `undo` ile geri al.
  6. Gateway provider: `gateway/provider.ts` + `gateway/client.ts` — `evren-backend` SSE'yi `openai-compat.ts` üzerinden tüketir, `tool-accumulator.ts` ile tool_call reassembly.
- **Kabul:** `pnpm -r test` 237+ yeşil, `prompt-injection` + `path-safety.adversarial` + `commands.adversarial` testleri yeşil, CLI `evren-agent/apps/cli` ile `sample-repo` fix-it senaryosu çalışır.

### Faz 3 — VS Code Fork Rebrand + Provider Hook (1–1.5 hafta)

**Hedef:** VS Code, senin gateway'ine konuşur.

- **Dosyalar:** `vscode/product.json`, `vscode/extensions/copilot/src/extension/byok/evrenProvider.ts` (yeni), `vscode/src/vs/workbench/contrib/chat/common/languageModels.ts`, `vscode/src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts`, `vscode/src/vs/workbench/services/authentication/*`, `frontend/electron/main/gateway.ts` (referans)
- **Adımlar:**
  1. `product.json` rebrand: `nameShort: "Ufuk"`, `nameLong: "Ufuk Agent"`, `applicationName: "ufuk"`, `dataFolderName: ".ufuk"`, `win32DirName: "Ufuk"`, `darwinBundleIdentifier: "com.ufuk.agent"`, `urlProtocol: "ufuk"`, `agentsTelemetryAppName: "ufuk"`, `extensionsGallery: null` (marketplace kapalı, Faz 5'te opsiyonel).
  2. `evrenProvider.ts` yaz: `ILanguageModelProvider` implemente et, `provideLanguageModels` içinde `GET /plans` + `GET /tiers` (veya `GET /v1/models`) ile model listesi, `provideCompletion` içinde `POST /v1/chat/completions` SSE (header `Authorization: ******` JWT, `stream: true`, `stream_options: {include_usage:true}`), SSE `data:` parse, `usage` strip, `model` alias'a rewrite (gateway zaten yapıyor ama double-check).
  3. Auth hook: `ISecretStorageService` + `IAuthenticationService` ile login view — `POST /auth/login` → `access_token` + `refresh_token` → `secretStorage.store("ufuk:jwt", token)`, her istekte header ekle, `401` → `POST /auth/refresh` single-flight (gateway `auth.ts` zaten var).
  4. Model picker: `chatSelectedModel.ts` / `modelSelection.ts` — picker listesini `evrenProvider`'dan doldur, seçilen `alias` → `model` alanına yaz.
  5. Quota hook: `chatQuotaNotification.ts` + `chatErrorMessages.ts` — `402 quota_exceeded` → "Kredin bitti, plan yükselt" + `GET /usage` ile kalan kredi göster, `429` → `Retry-After` countdown.
  6. Build test: `npm run compile` (VS Code gulp) + `electron` launch, chat'te "hello" → gateway → upstream → SSE stream doğrula.
- **Kabul:** VS Code `Ufuk` adıyla açılır, login olur, chat'te model picker tier alias'ları gösterir, mesaj SSE akar, 402/429 notification çıkar.

### Faz 4 — Workbench Sadeleştirme (3–5 gün)

**Hedef:** IDE kalabalığı gider, sadece agent + editor + explorer.

- **Dosyalar:** `vscode/src/vs/workbench/contrib/*` (gizlenecekler), `vscode/src/vs/workbench/browser/workbench.ts`, `vscode/product.json` `builtInExtensions`
- **Adımlar:**
  1. Gizlenecek contrib'ler (dosya silme yok, `when: false` veya `isEnabled: false`):
     - `terminal` (`workbench/contrib/terminal`), `debug` (`workbench/contrib/debug`), `scm` (`workbench/contrib/scm`), `search` (`workbench/contrib/search`), `testing` (`workbench/contrib/testing`), `notebook` (`workbench/contrib/notebook`), `mergeEditor`, `timeline`, `outline`, `extensions` (marketplace view).
  2. Bırakılacaklar: `files` (explorer), `editor`, `chat` (agent), `output`, `problems` (opsiyonel).
  3. `builtInExtensions` temizle: `cpp`, `go`, `java`, `python`, `rust`, `php`, `ruby` gibi dil eklentilerini listeden çıkar, sadece `json`, `markdown`, `typescript-basics` bırak (agent kod okusun diye).
  4. "Agent System'den IDE'ye geç" butonu yok — zaten workbench tek. İstenirse `View > Appearance > Activity Bar` gizle, `chat` view'i default `sideBar` yap (`workbench.startupEditor: "none"`, `workbench.activityBar.location: "hidden"` settings default).
- **Kabul:** Ufuk açıldığında sadece Explorer + Editor + Chat görünür, terminal/debug/scm yok, `Help > About` "Ufuk" gösterir.

### Faz 5 — MCP / Plugin Görsel Düzenleme (3–5 gün)

**Hedef:** MCP sade ve güvenli.

- **Dosyalar:** `vscode/src/vs/workbench/contrib/mcp/*`, `vscode/src/vs/workbench/contrib/chat/browser/*` (CSS)
- **Adımlar:**
  1. `mcpServersView.ts` filtre: sadece `mcp.json` içinde `allowed: true` olan sunucuları göster, kullanıcı rastgele MCP ekleyemez (veya eklerse approval modal).
  2. `mcpGatewayService.ts` — MCP tool call'ları `local-runner` permission engine'den geçir (aynı `dangerous.ts` floors).
  3. CSS: `chat/browser/chatView.css`, `mcp/mcpServersView.css` — VS Code CSS variable (`--vscode-*`) ile tema uyumlu, Tailwind yok. Gerekirse `workbench` theme override.
  4. Marketplace kapalı (`extensionsGallery: null`) — ileride kendi gallery'n olursa `product.json` içinde URL ver.
- **Kabul:** MCP view sadece onaylı sunucuları gösterir, tool call approval modal çıkar, CSS bozulmaz.

### Faz 6 — Ödeme + Abonelik UI (1 hafta)

**Hedef:** Kullanıcı para verir, plan otomatik atanır.

- **Dosyalar:** `evren-backend/app/routers/billing.py`, `evren-backend/app/models/plan.py` (stripe_price_id), `vscode/src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts`, `frontend/src/stores/*` (referans)
- **Adımlar:**
  1. Stripe (veya Iyzico) webhook: `POST /billing/webhook` → imza doğrula → `user_id` bul (email) → `assign_plan(db, user_id, plan_id)` → `period_start/end` korunur (Faz 1'de düzeltildi).
  2. `GET /plans` + `GET /usage` + `GET /me` ile chat içinde "Plan: Pro — 12.3/100 kredi" indicator (`CreditIndicator.tsx` mantığı VS Code status bar'a taşınır).
  3. `GET /billing/portal` → Stripe Customer Portal link (plan yükselt/düşür).
  4. Test: Stripe CLI `stripe trigger checkout.session.completed` → webhook → DB `subscriptions` ACTIVE doğrula.
- **Kabul:** Test kartıyla ödeme → webhook → plan atanır, chat'te kredi indicator güncellenir, 402 sonrası "Yükselt" butonu portal'a gider.

### Faz 7 — Build, Test, Release (1 hafta)

**Hedef:** `Ufuk-Setup-0.1.0.exe` üret, e2e yeşil.

- **Dosyalar:** `vscode/gulpfile.mjs`, `vscode/build/*`, `frontend/electron/*` (referans), `evren-backend/tests/*`, `evren-agent/packages/*/test/*`
- **Adımlar:**
  1. Her fazda: `pnpm typecheck && pnpm lint && pnpm test` (frontend) + `pnpm -r test` (agent) + `pytest -q` (backend) — asla kırık bırakma.
  2. Playwright Electron e2e: `frontend` eski e2e'yi VS Code fork'a taşı — `login → add sample project (evren-agent/apps/cli/fixtures/sample-repo) → "The test in this repo is failing. Fix it and verify." → approve edit + npm test → diff → undo` — `docs/screenshots` ile.
  3. Build: `vscode: npm run gulp vscode-win32-x64` + `electron-builder --win nsis` (unsigned, `release/Ufuk-Setup-0.1.0.exe`, ~100–150 MB). `product.json` `win32AppId` yeni GUID.
  4. `README.md` güncelle: `evren-backend` (docker), `evren-agent` (pnpm), `vscode` (gulp) nasıl çalıştırılır, `docs/IMPLEMENTATION-PLAN.md` linkle.
  5. `docs/PROGRESS.md` her fazda append (test sayıları, ekran görüntüleri).
- **Kabul:** Tüm testler yeşil, e2e fix-it geçer, installer üretilir, `README` ile sıfırdan kurulum çalışır.

---

## 3. Riskler ve Önlemler

| Risk | Önlem |
|---|---|
| VS Code upstream conflict | Hook'ları `extensions/copilot` içinde tut, `src/vs/*` değişikliği minimal, ayda bir `git -C vscode pull` + manuel merge |
| `better-sqlite3` native build (Electron 44, ABI 149) | `electron-rebuild` + JSONL fallback (zaten var, `local-runner/src/db/jsonl-store.ts`) |
| OpenRouter tek anahtar limiti | Faz 1 global limiter + circuit breaker (zaten var) |
| Prompt injection | Faz 2 `prompt-injection.test.ts` + permission engine asla bypass edilmez |
| Kod imzalama yok | NSIS unsigned (TODO: cert + auto-update `electron-updater`) |

---

## 4. Dosya Haritası (Yeni Oluşacak / Değişecek)

```
evren-agent/                          ← geri kopyalanacak (eski projeden)
frontend/                             ← geri kopyalanacak (fallback UI)
vscode/
  product.json                        ← rebrand
  extensions/copilot/src/extension/byok/evrenProvider.ts  ← YENİ
  src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts ← hook
  src/vs/workbench/contrib/mcp/mcpServersView.ts ← filtre
evren-backend/
  app/routers/billing.py              ← YENİ (Stripe/Iyzico webhook)
  app/models/plan.py                  ← stripe_price_id kolonu
  app/services/rate_limiter.py        ← global limiter
  app/logging.py                      ← Sentry
  scripts/derive_credit_rates.py      ← YENİ
  tests/test_billing_webhook.py       ← YENİ
docs/
  ARASTIRMA-RAPORU.md                 ← mevcut
  IMPLEMENTATION-PLAN.md              ← bu dosya
  PROGRESS.md                         ← her fazda güncellenecek
```

---

## 5. Zaman Çizelgesi (Gerçekçi)

| Faz | Süre | Bağımlılık |
|---|---|---|
| 0 Repo düzeltme | 1–2 gün | — |
| 1 Backend hardening | 1 hafta | Faz 0 |
| 2 Agent core | 1 hafta | Faz 0 |
| 3 VS Code provider hook | 1–1.5 hafta | Faz 1 + 2 |
| 4 Workbench sadeleştirme | 3–5 gün | Faz 3 |
| 5 MCP/plugin | 3–5 gün | Faz 3 |
| 6 Ödeme | 1 hafta | Faz 1 |
| 7 Build/e2e/release | 1 hafta | Tümü |
| **Toplam** | **~6–7 hafta** | |

---

*Bu plan kod değişikliği içermez, sadece yol haritasıdır. Her faz küçük commit'lerle, testler yeşilken ilerler.*
