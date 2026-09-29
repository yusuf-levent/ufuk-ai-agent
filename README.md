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
- `docs/workspace-context-research.md` — ADIM 6: VS Code workspace context mekanizmalari
- `docs/auto-select-design-note.md` — otomatik model secimi tasarim notu

## Billing (provider-agnostic: Dodo Payments / Paddle / Stripe)

Uc secenegi `BILLING_PROVIDER` ile secilir (`stripe` | `dodo` | `dodo_live` |
`paddle` | `paddle_live`). Hepsi MoR (Merchant of Record) veya saglayici olarak
calisir; webhook -> `assign_plan()` zinciri saglayicidan bagimsizdir.

Uclar (hepsi ayni):

- `POST /billing/checkout` — hosted checkout session olusturur (plan secimi)
- `GET /billing/portal` — musteri self-service portal (odeme yontemi, iptal, fatura)
- `POST /billing/webhook` — saglayici webhook'u (imza dogrulanir)

Plan eslesmesi `plans.provider_price_id` uzerinden yapilir (eski
`plans.stripe_price_id` hala okunur, geriye donuk uyumluluk icin).

### Ortam degiskenleri

| Degisken | Anlam |
| --- | --- |
| `BILLING_PROVIDER` | `stripe` (varsayilan) / `dodo` / `dodo_live` / `paddle` / `paddle_live` |
| `BILLING_API_KEY` | Saglayici API anahtari (Dodo: `DODO_PAYMENTS_API_KEY`, Paddle: `PADDLE_API_KEY`) |
| `BILLING_WEBHOOK_SECRET` | Webhook imza sirri (Dodo: `whsec_...`, Paddle: `pds_...`) |
| `BILLING_SUCCESS_URL` / `BILLING_CANCEL_URL` | Checkout donus URL'leri (varsayilan `ufuk://billing/...`) |

Eski `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_SUCCESS_URL` /
`STRIPE_CANCEL_URL` hala calisir: `BILLING_*` tanimli degilse bunlar kullanilir.

### Hangi saglayici secilirse ne degisir?

| Konu | Dodo Payments | Paddle | Stripe |
| --- | --- | --- | --- |
| Sirket gerekli mi? | Hayir (bireysel hesap acik, TR kimlik kabul) | Dogrulanmadi | Evet (TR'de desteklenmiyor) |
| `BILLING_PROVIDER` | `dodo` (test) / `dodo_live` | `paddle` (sandbox) / `paddle_live` | `stripe` |
| `plans.provider_price_id` | Dodo urun id (`pdt_...`) | Paddle price id (`pri_...`) | Stripe price id (`price_...`) |
| Webhook imzasi | Standard Webhooks (`webhook-id`/`-timestamp`/`-signature`) | `Paddle-Signature: ts=..;h1=..` | `Stripe-Signature: t=..,v1=..` |
| Test ortami | `https://test.dodopayments.com` | `https://sandbox-api.paddle.com` | `https://api.stripe.com` (test anahtar) |
| TRY fiyat | Adaptive Currency / Localized Pricing | `TRY` destekli | - |

Kod degisikligi gerekmez: sadece `.env` + dashboard'daki urun/price id'lerini
`plans.provider_price_id` alanina girin. `assign_plan()`, kredi ve quota
mantigi butun saglayicilarda aynidir.

### Sandbox/test durumu

- Webhook -> `assign_plan()` zinciri **test edildi**: her saglayici icin gercek
  imza uretilip dogrulandi (`tests/test_billing_webhooks.py`).
- Gercek checkout session olusturma **bekliyor**: test hesabi/API anahtari
  gerektirir. Anahtar gelince `BILLING_API_KEY` + `BILLING_WEBHOOK_SECRET`
  doldurulur, `POST /billing/checkout` ile dogrulanir. (Uydurma test yok.)

Masaustu tarafinda: hesap ayarlari diyalogunda plan listesi + "Choose" (Checkout)
+ "Manage Billing" (Portal) butonlari; status bar'da kredi gostergesi; chat input'ta
yesil/sari/kirmizi kredi bari.

## Release (Windows installer)

```powershell
cd vscode
npm run gulp vscode-win32-x64          # .build/win32-x64
npx electron-builder --win nsis --config electron-builder.yml
# -> release/Ufuk-Setup-<version>.exe
```
