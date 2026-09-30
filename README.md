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
- `docs/FIYATLANDIRMA-VE-MODEL-TASARIMI.md` — fiyat merdiveni ($10/$100/takim), model katalogu
  (OpenRouter), cache pricing, gizli sub-agent modelleri, kacirilan riskler ve kararlar
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

### Sandbox/test durumu — TAMAMLANDI (2026-09-30)

Gerçek Dodo test-mode ortaminda uctan uca dogrulandi (gercek para YOK):

- Test checkout olusturuldu (`POST /billing/checkout` -> Dodo `test.checkout.dodopayments.com`)
- Test karti ile odeme yapildi (TRY goruntulu, Adaptive Currency aktif)
- Webhook'lar geldi: `subscription.updated` (ignored), `subscription.active` +
  `subscription.renewed` (`assign_plan()` -> **pro** plani atandi), `payment.succeeded` (ignored)
- DB dogrulandi: eski plan `cancelled`, yeni `pro` aboneligi `active` (period mirasi ile)

Yakalanan ve duzeltilen bug: Standard Webhooks'ta HMAC anahtari `whsec_`'den sonraki
**base64-decoded** degerdir; ilk surumde ham string kullanilmisti. Gercek Dodo
teslimatlari 400 alirken birim testler geciyordu (test secret'i kendimiz uretip
kendimiz imzaliyorduk). Duzeltme: `dodo.py` -> `base64.b64decode(...)`, commit `7301c4e`.

### Test ortamini yeniden kurma (gelistirme icin)

Gerekli 3 sey (Dodo panosu, Test Modu):

1. **API anahtari**: Gelistrici -> API Keys -> test anahtari -> `BILLING_API_KEY`
2. **Webhook secret**: Gelistrici -> Webhooks -> endpoint -> `whsec_...` -> `BILLING_WEBHOOK_SECRET`
3. **Urun ID**: Urunler -> abonelik urunu -> `pdt_...` (bkz. `scripts/seed.py`
   `DEFAULT_PLANS["pro"]["provider_price_id"]`)

`.env` (yalnizca `evren-backend/.env`, baska env yok):

```env
BILLING_PROVIDER=dodo
BILLING_API_KEY=...
BILLING_WEBHOOK_SECRET=whsec_...
```

Webhook icin localhost'a tunel gerekir (Dodo disariya istek atar):

```powershell
.\cloudflared.exe tunnel --url http://127.0.0.1:8000
# cikan https://xxx.trycloudflare.com adresini Dodo'daki webhook URL'ine yaz:
#   https://xxx.trycloudflare.com/billing/webhook
```

Not: quick tunnel adresleri her acilista degisir. Test kartlari:
`4242 4242 4242 4242` / `06/32` / CVV `123` (bkz. docs.dodopayments.com/miscellaneous/testing-process).

### Canliya gecis — HENUZ YAPILMADI

**Dodo hesabi henuz canli moda cekilmedi.** Test modu calisiyor, canli odeme alinmiyor.
Canliya gecmek icin sirasiyla:

1. Dodo panosunda **Dogrulama (KYC)** tamamlanacak — kimlik + banka dogrulamasi
   incelemede (72 saat surebiliyor). Reddedilirse sebebiyle birlikte tekrar denenir.
2. Dogrulama onaylaninca Dodo panosundan **Live Mode** acilir, **canli API anahtari**
   + **canli webhook secret** alinir.
3. `.env`'de sadece 3 satir degisir (KOD DEGISIKLIGI GEREKMEZ):

   ```env
   BILLING_PROVIDER=dodo_live
   BILLING_API_KEY=<canli anahtar>
   BILLING_WEBHOOK_SECRET=<canli whsec_>
   ```

4. Webhook URL'i **kalici** bir adrese tasinir (tunel degil; ornek: api.ufuk.dev/billing/webhook).
5. Dodo'da **canli urun** olusturulur (test urunu canliya kopyalanabilir), yeni
   `pdt_...` `scripts/seed.py`'deki `provider_price_id` alanina yazilir.
6. Canli urunun **fiyat para birimi** kararlastirilir: USD (varsayilan) veya TRY.
   Dodo Adaptive Currency sayesinde Turkiye musterileri zaten TL gorur; sabit TRY
   fiyat istenirse Localized Pricing kullanilir.
7. Smoke test: kendi kartiyla kucuk tutarli bir canli odeme yapilir, webhook ->
   `assign_plan()` zinciri son kez dogrulanir, ardindan iade edilir.

Guvenlik notlari: canli anahtarlar asla commit edilmez (`.env` gitignore'da);
webhook secret rotasyonu eski sirri 24 saat gecerli tutar; `BILLING_PROVIDER`
`dodo` (test) ile `dodo_live` arasinda kod degisikligi olmadan gecis yapilir.

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
