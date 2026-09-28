# Ufuk — İlerleme Kaydı (PROGRESS)

> Son güncelleme: 2026-09-28. Her satır bir commit'e karşılık gelir.

## Durum Özeti

| Faz | Durum | Kanıt |
|---|---|---|
| Faz 0 — Repo düzelt | ✅ | `dc3d5b6` |
| Faz 1 — Backend hardening | ✅ | `400aeee`, `a3d7d58`, `fd84876` |
| Faz 2 — VS Code → Ufuk (proxy, login, picker) | ✅ | `8e4fef51`, `7906b1cb`, `dffa0020` |
| Faz 3 — Sadeleştirme + branding | ✅ | `3346fdff`, `02565bb5` |
| Faz 4 — Limit/abonelik UI | ✅ | `cc7e358`, `c09b5a80`, `22ba4bae`, `e3ff6409`, `c77c18b1` |
| Faz 5 — Build + release | 🔄 | bu dosya |
| ADIM 6 — Workspace context araştırması | ✅ | `47df0bd` |

## Faz 4 Detayları (2026-09-28)

1. **`cc7e358` — Backend billing altyapısı**
   - `POST /billing/checkout` (Stripe Checkout Session), `GET /billing/portal` (Customer Portal)
   - `Plan.price_usd` + `User.stripe_customer_id` kolonları (migration `d5e6f7a8b9c0`)
   - Seed fiyatları: free 0$ / pro 20$ / team 200$
   - 10 yeni test → **129 passed**, mypy 0 hata

2. **`c09b5a80` — Status bar kredi göstergesi**
   - `ufukQuotaStatus.ts`: `Pro — 42.3/100 kredi — 12 gün kaldı`
   - %80'de sarı, %100'de kırmızı; hover'da detay; tıklayınca hesap ekranı
   - 30 sn'de bir + her hesap değişiminde tazeleme
   - 18 yeni test → **18 passing**

3. **`22ba4bae` — Chat input kredi barı**
   - `ufukCreditBarWidget.ts`: yeşil→sarı→kırmızı ince bar (context usage yanında)
   - `chatInputPart.ts`'e 3 satır eklendi (çekirdek yapı korundu)
   - 12 yeni test → **12 passing**

4. **`e3ff6409` — Hesap/plan ekranı**
   - `IUfukAccountService`: `refreshPlans`, `getCheckoutUrl`, `getBillingPortalUrl`
   - Plan listesi (ad, kredi, fiyat, mevcut rozeti) + "Choose" (Stripe Checkout)
   - "Manage Billing" → Stripe Customer Portal

5. **`c77c18b1` — 402/429 quota akışı**
   - `workbench.action.chat.upgradePlan` + `manageAdditionalSpend` artık
     `ufuk.openAccountSettings` açıyor (GitHub URL'leri Ufuk'ta bozuktu)
   - Tüm "Upgrade / Manage Budget" butonları tek noktadan Ufuk'a yönlenir

## Faz 5 — Build + Release (bu adım)

- [x] `electron-builder.yml` (NSIS, x64) yazıldı
- [x] `LICENSE.txt` (MIT) eklendi
- [x] `build/resources/ufuk.ico` üretildi (PNG'den, çok boyutlu ICO)
- [x] `extensions/copilot/.../shims.txt` marker'ı oluşturuldu (build önkoşulu)
- [ ] `npm run gulp vscode-win32-x64` → `.build/win32-x64`
- [ ] `npx electron-builder --win nsis` → `release/Ufuk-Setup-<version>.exe`
- [ ] Playwright e2e: login → Agent "şu testi düzelt" → tool call → diff → undo

## Bilinen Boşluklar (bilinçli ertelendi)

- `semantic_search` Ufuk'ta işlevsiz (GitHub embedding API gerekir) — ADIM 11
- Auto-select heuristik — ADIM 10 (tasarım notu hazır, kod yok)
- `GET /billing/portal` gerçek Stripe çağrısı canlı anahtarla test edilmedi
  (unit testler mock'lu; canlı doğrulama release öncesi yapılmalı)