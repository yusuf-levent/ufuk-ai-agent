# Ufuk Agent System — Implementasyon Plani (FINAL)

> Tarih: 2026-09-26
> Hedef: VS Code'un hazir agent arayuzunu al, kendi abonelik sistemini tak, backend'e bagla, para kazan.
> Yontem: VS Code FORK (eklenti degil). Tek repo, tek installer.

---

## Senin Istegin (1 cumlede)

VS Code'un ust kisimdaki **"Open in Agents"** ile acilan agentic arayuzu (Ask/Edit/Agent modlari, tool timeline, diff, checkpoint) zaten var. Biz onu aliyoruz, icine **login + abonelik + kredi** koyuyoruz, LLM isteklerini **kendi backend'imize** (`evren-backend` → OpenRouter) yonlendiriyoruz, **Ufuk** adiyla paketleyip satiyoruz.

Eklenti yok. evren-agent yok. Sifirdan loop yazmak yok. VS Code'un kendi motoru kullanilacak.

---

## Mimari (cok basit)

```
Kullanici indirir: Ufuk-Setup-0.1.0.exe (VS Code fork, adi Ufuk)
        │
        ▼
┌─────────────────────────────┐         ┌──────────────────────┐
│  Ufuk (masaustu)            │  HTTPS  │  evren-backend       │
│  = VS Code fork             │  + SSE  │  (sunucu)            │
│                             │────────►│                      │
│  - Agent arayuzu (hazir)    │  JWT    │  - /auth (login)     │
│  - Editor + Explorer        │         │  - /plans, /usage    │
│  - Agent loop (hazir)       │         │  - /v1/chat/completions (SSE proxy)
│  - Login ekrani (eklenecek) │         │  - kredi / rate limit│
│  - Kredi gostergesi         │         │  - Stripe webhook    │
│                             │         │         │            │
└─────────────────────────────┘         └─────────┼────────────┘
                                                  │ tek API key
                                                  ▼
                                            OpenRouter
                                            (openai/gpt-4o, claude-3.5 vb.)
```

- **Masaustu:** VS Code fork. Agent loop, tool calling, dosya yazma, diff, checkpoint hepsi hazir. Biz sadece 3 sey ekliyoruz: login, model picker'i kendi modellerimize baglama, kredi bitince uyari.
- **Sunucu:** Sadece `evren-backend` (FastAPI + Postgres + Redis). Kullanici dosyalari/sohbetleri sunucuda DEGIL, masaustunde. Sunucu sadece: kim bu kullanici, hangi planda, ne kadar kredisi kaldi, LLM'e proxy.
- **Para:** Kullanici Stripe ile oder → webhook → `assign_plan()` → plan atanir. LLM maliyeti OpenRouter tek key'inden duser, biz krediyle sinirlariz, ustune kar koyariz.

---

## Ne Degisecek? (sadece 4 yer, hepsi VS Code fork icinde)

| # | Dosya | Ne yapilacak | Neden |
|---|---|---|---|
| 1 | `vscode/product.json` | `nameShort: "Ufuk"`, `applicationName: "ufuk"`, `dataFolderName: ".ufuk"`, `urlProtocol: "ufuk"` | VS Code → Ufuk rebrand. 5 satir. |
| 2 | `vscode/src/vs/platform/agentHost/node/copilot/copilotAgent.ts` (veya yeni `evrenAgent.ts`) | LLM istegini `POST https://api.ufuk.ai/v1/chat/completions` SSE'ye yonlendir, `Authorization: ******` JWT ekle | Agent loop'un LLM'i Copilot degil, senin backend'in olsun. ~50 satir. |
| 3 | `vscode/src/vs/workbench/contrib/chat/browser/chatQuotaNotification.ts` | `402 quota_exceeded` → "Kredin bitti, yukselt" + `429` → "Biraz bekle" | Kredi bitince kullanici anlasin. ~30 satir. |
| 4 | `vscode/src/vs/workbench/contrib/chat/common/chatModes.ts` + login view | Model picker `fast/pro/strong` alias'lari, login ekrani (`POST /auth/login` → JWT → `secretStorage`) | Kullanici giris yapsin, model secsin. ~100 satir. |

Baska hicbir cekirdek dosyaya dokunulmayacak. `terminal`, `debug`, `scm` gibi gereksiz paneller `when: false` ile gizlenecek (dosya silme yok).

Toplam: **~200 satir degisiklik**. VS Code 1.5 milyon satir, biz 200 satir degistiriyoruz.

---

## Fazlar (sirasiyla, her faz bitince test yesil)

### Faz 0 — Repo duzelt (1 gun)

- `pnpm-workspace.yaml` duzelt: `evren-agent/packages/*` ve `frontend` satirlarini sil (o klasorler yok, VS Code fork ana UI). Bos birak veya sadece `evren-backend` icin ayarla.
- `README.md` guncelle: "Masaustu = VS Code fork (Ufuk), Sunucu = evren-backend" yaz.
- Kabul: `evren-backend: pytest -q` yesil.

### Faz 1 — Backend'i production'a hazirla (1 hafta)

- **OpenRouter dogrulama:** `tests/test_openrouter_upstream.py` zaten var — mock SSE, `usage.cost` strip, `429` + `X-RateLimit-Reset` HTTP-date → `Retry-After` forward. `app/services/upstream.py` icine HTTP-date parse ekle.
- **Global rate limiter:** `app/services/rate_limiter.py` icine tum kullanicilar icin 60 req/min limit (tek OpenRouter key'ini korur).
- **Odeme:** `app/routers/billing.py` YENI — `POST /billing/webhook` (Stripe imzasi dogrula → `assign_plan()`). `Plan` tablosuna `stripe_price_id` kolonu (migration).
- **Sentry + /health/ready + backup:** `app/logging.py` Sentry, `docker-compose.prod.yml` Caddy TLS.
- Kabul: `pytest -q` 115+ yesil.

### Faz 2 — VS Code'u Ufuk yap (1–1.5 hafta) — EN ONEMLI FAZ

1. `product.json` rebrand (5 satir).
2. `copilotAgent.ts` icine evren-backend SSE hook'u (50 satir) — `POST /v1/chat/completions`, JWT header, SSE `data:` parse.
3. Login ekrani + `secretStorage` (100 satir) — `POST /auth/login` → token sakla, her istekte gonder, `401` → refresh.
4. Model picker `fast/pro/strong` (chatModes.ts), quota hook `402/429` (chatQuotaNotification.ts).
5. `npm run compile` + `electron` launch → Agent modunda "hello" yaz → backend → OpenRouter → SSE akar, tool call dosya yazar, diff cikar.
- Kabul: Ufuk adiyla acilir, login olur, Agent modunda chat calisir, dosya yazar, kredi bitince uyari cikar.

### Faz 3 — Sadelestir (3–5 gun)

- `terminal`, `debug`, `scm`, `search`, `testing`, `notebook`, `extensions` marketplace `when: false` ile gizle. Sadece `explorer + editor + chat (Agent)` + `Agents Window` kalsin.
- `builtInExtensions` icinden `cpp`, `go`, `java`, `python` gibi dil eklentilerini cikar.
- Kabul: Ufuk acilinca sadece Explorer + Editor + Chat gorunur.

### Faz 4 — MCP + odeme UI (1 hafta)

- `mcpServersView.ts` filtre: sadece onayli MCP'ler.
- Stripe webhook → plan atanir, chat'te "Plan: Pro — 12.3/100 kredi" status bar, `402` sonrasi "Yukselt" butonu Stripe portal'a gider.
- Kabul: Test kartiyla odeme → plan atanir, kredi gostergesi guncellenir.

### Faz 5 — Build + release (1 hafta)

- `npm run gulp vscode-win32-x64` + `electron-builder --win nsis` → `release/Ufuk-Setup-0.1.0.exe` (~100–150 MB).
- Playwright e2e: `login → Agent modunda "The test in this repo is failing. Fix it." → tool call → diff → undo`.
- `README.md` + `docs/PROGRESS.md` guncelle.
- Kabul: Installer uretilir, e2e gecer.

---

## Zaman

| Faz | Sure |
|---|---|
| 0 Repo duzelt | 1 gun |
| 1 Backend hardening | 1 hafta |
| 2 VS Code fork (en kritik) | 1–1.5 hafta |
| 3 Sadelestir | 3–5 gun |
| 4 MCP + odeme | 1 hafta |
| 5 Build/release | 1 hafta |
| **Toplam** | **~5 hafta** |

---

## Ozet (kisa)

1. VS Code'u fork'la, `product.json`'da adini Ufuk yap.
2. Agent loop'un LLM istegini Copilot'tan kes, kendi backend'ine (`/v1/chat/completions` SSE) bagla — 50 satir.
3. Login + kredi gostergesi + quota uyari ekle — 130 satir.
4. Gereksiz panelleri gizle, installer al, sat.

Eklenti yok. evren-agent yok. Sifirdan agent yazmak yok. Toplam ~200 satir degisiklikle VS Code'un hazir agent motorunu kendi abonelik sisteminle satiyorsun.

*Kod degisikligi icermez, sadece plan.*
