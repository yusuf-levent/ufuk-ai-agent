# Fiyatlandırma ve Model Tasarımı — Araştırma Raporu

> Tarih: 2026-09-29
> Kapsam: Abonelik merdiveni, token/kredi matematiği, model kataloğu (OpenRouter), cache pricing,
> gizli sub-agent modelleri, kaçırılan riskler ve alınan kararlar.
> **Not: Bu rapor sadece araştırma + yöntem önerisidir. Kod değişikliği yapılmamıştır.**
> Tüm fiyatlar OpenRouter `GET /api/v1/models` canlı listesinden çekilmiştir (460 model, 2026-09-29).

---

## 0. Yönetici Özeti

| Konu | Karar |
|---|---|
| Fiyat merdiveni | **$10 Plus / $100 Pro / $30 koltuk Takım** (GitHub Copilot AI Credits emsali) |
| Kullanıcıya gösterim | Sadece **"bu ay %X kaldı"** + renkli bar. Token/kredi/çarpan **görünmez** |
| Ölçüm birimi | İçeride **kredi** (token bazlı), dışarıda **yüzde/kota** |
| Model felsefesi | Giriş-orta = **Çinli** (Qwen/MiMo/GLM/Seed/Ling), üst = **frontier** (GPT-6, Claude-5.x), + **Auto** varsayılan |
| Tool şartı | Kullanıcıya açılan **her** model `tools` + `tool_choice` + `response_format` desteklemeli |
| Görsel şartı | Kullanıcıya açılan **her** model görsel girdi desteklemeli |
| Gizli sub-agent | Kullanıcı görmez; `gpt-oss-120b` (tam 120B) veya `openrouter/pareto-code` |
| Cache pricing | **Dahil** + `session_id` sticky routing (3-4x maliyet düşüşü) |
| 5 saat + hafta limiti | Aylık kota ana ölçü + yumuşak 5s/haftalık hız kırıcılar |
| Kota devri | **Devrolmaz**, aylık sıfırla |

---

## 1. Mevcut Sistem (kod tabanı tespitleri)

### 1.1 Planlar — `evren-backend/scripts/seed.py`

| Plan | Fiyat | Aylık kredi | Modeller | RPM | Max çıktı |
|---|---|---|---|---|---|
| `free` | $0 | 100 | sadece `fast` | 10 | 8.192 |
| `pro` | $20 | 5.000 | hepsi | 60 | 16.384 |
| `team` | $200 | 50.000 | hepsi | 200 | 16.384 |

**Tespitler:**
- `plans.provider_price_id = None` → **hiçbir plan satın alınabilir değil**. Ödeme linki bağlanmamış.
- Sadece `price_usd` alanı var (TRY yok — zaten gerekmiyor).
- Marj: 1 kredi ≈ $0.001 upstream bütçesi (`credits_per_usd=1000`). Pro = 5.000 kredi ≈ $5 maliyet, $20 satış → ~%75 brüt marj.

### 1.2 Token/kredi hesabı — `app/services/credits.py`

$$\text{kredi} = \frac{\text{prompt\_tokens} \times \text{in\_rate} + \text{completion\_tokens} \times \text{out\_rate}}{1000}$$

**Akış (sağlam tasarlanmış):**
1. **Ön provizyon:** `estimate_messages_tokens()` ≈ `(karakter+3)/4 + 4×mesaj` → `reserve_amount()` → Redis'te atomik rezerve. Aşarsa `402 quota_exceeded`.
2. **Kesinleştirme:** SSE `usage` alanından gerçek token → `token_cost()` → fark düzeltilir (`settle_usage_event`, idempotent). Bağlantı koparsa `completion_estimate()` fallback.
3. **Dayanıklılık:** Redis ledger kaybolursa `ensure_ledger_synced()` DB'den yeniden kurar.

**Per-user takip: ✅ HAZIR** — `usage_events` tablosu (prompt/completion token, kredi, tier, durum, gecikme) + `/usage` endpoint'i tier bazlı döküm veriyor.

### 1.3 Limitler

| Limit | Durum |
|---|---|
| 30 günlük dönem kredisi | ✅ Var (`subscriptions.PERIOD_DAYS = 30`) |
| Dakikalık RPM | ✅ Var (sabit 60sn pencere) |
| **5 saatlik pencere** | ❌ **Yok** |
| **Haftalık kapak** | ❌ **Yok** |
| Sub-agent bütçe kill-switch | ❌ **Yok** |
| Burst/eşzamanlı stream limiti | ❌ **Yok** |

### 1.4 Masaüstü UI

- `ufukCreditBarWidget.ts` → şu an **ham kredi sayısı** gösteriyor (`42.3/100`). Hedef: saf yüzde/doluluk.
- `chatQuotaNotification.ts` → `THRESHOLDS = [50, 75, 90, 95]` eşik bildirimi **zaten port edilmiş**.
- `ufukAccountService.ts` → `IQuotaSnapshot` / `IRateLimitSnapshot` taşıyor (5s/haftalık için doğal takılma noktası).

---

## 2. Piyasa Fiyatlandırma Araştırması

### 2.1 Rakip fotoğrafı (2026-09 itibarıyla doğrulandı)

| Ürün | Ücretsiz | Giriş | Üst | Takım | Ölçüm |
|---|---|---|---|---|---|
| **GitHub Copilot** | $0 (sınırlı, sadece Auto model) | **$10 = 1.000 AI kredi** | $39 = 3.900 / **$100 Max = 10.000** | Business/Enterprise | **Kredi + model çarpanı** |
| **Devin (Windsurf)** | $0 (hafif kota) | **$20** Pro | **$200** Max | **$80 takım + $40/koltuk** | **Günlük + haftalık kota yenileme**, aşınca API fiyatından ek paket |
| **Cursor** | var | $20 Pro | Pro+ / Ultra | Teams/Enterprise | "Request" + model çarpanı, bazı modeller **"Hidden by default"** |
| **Claude (Pro/Max)** | — | $20 Pro | $100 Max 5x / $200 Max 20x | Team/Enterprise | **5 saatlik pencere + haftalık limit**, kota bitince **usage credits** veya bekle |
| **Lovable** | — | kredili | — | **Workspace havuzlu kredi** + üye başına limit | Kredi |

**Kritik emsaller:**
- **Copilot'un $10 → $100 merdiveni** ve "AI Credits" soyutlaması → bizim hayalin **birebir piyasada var**.
- **Devin'in "günlük + haftalık kota"** + **Claude'un "5 saat + hafta"** → 5s/haftalık limit için iki hazır emsal.
- **Cursor'un "Hidden by default"** → gizli model kavramının emsali.
- **Lovable'ın havuz + üye limiti** → takım paketi için emsal.

### 2.2 Hesap paylaşımı politikası (madde 6)

**Anthropic Consumer Terms §2 (birebir):**
> *"You may not share your Account login information, Anthropic API key, or Account credentials with anyone else. You also may not make your Account available to anyone else."*

**OpenAI:** Rate limit'ler organizasyon/proje seviyesinde. Spend arttıkça tier atlar.
**Devin:** Koltuk bazlı + "Concurrent sessions limit" (Free/Pro: 10, Max/Team: sınırsız).
**Copilot:** Seat lisansı.

**Sonuç:** Kimse teknik DRM yapmıyor. Standart = **sözleşme maddesi + eşzamanlı oturum limiti + anormal kullanım tespiti**.

### 2.3 Tokenizer piyasası (madde 5)

| Şirket | Yöntem |
|---|---|
| OpenAI | `tiktoken` (o200k_base) — model-özel tokenizer, offline, ücretsiz |
| Anthropic | `/v1/messages/count_tokens` API — resmi token sayım endpoint'i |
| Google Gemini | `countTokens` API |
| OpenRouter | Yanıtta **native tokenizer** ile gerçek sayım |

**Sonuç: Piyasa "dile göre heuristic" DEĞİL, gerçek tokenizer kullanıyor.**

---

## 3. Önerilen Fiyat Merdiveni

| Paket | Fiyat | İç kredi | ≈ Kullanım | Kim için |
|---|---|---|---|---|
| **Ücretsiz** | $0 | 100 kredi/ay | ~30 agent mesajı | Deneme. Sadece **Auto + en ucuz Çinli**, RPM 5 |
| **Plus** ⭐ | **$10/ay** | 2.500 kredi/ay | ~800 mesaj (≈27/gün) | Bireysel geliştirici — **giriş seviyesi** |
| **Pro** | **$100/ay** | 30.000 kredi/ay | ~10.000 mesaj | Günlük ağır kullanım + geniş sub-agent + öncelik |
| **Takım** | **$30/koltuk** (min 3) | koltuk 2.000 + %20 ortak havuz | — | Ekipler (Lovable havuz modeli) |

**Marj matematiği** (1 kredi ≈ $0.001 upstream tavanı, gerçek ortalama ~%40'ı çünkü cache + Çinli ağırlıklı):
- Plus: $10 gelir, ~$1.0 gerçek maliyet → **~%90 brüt marj**
- Pro: $100 gelir, ~$12-15 gerçek maliyet → **~%85 brüt marj**

**Neden bu rakamlar:**
1. **$10 psikolojik eşik** — "Codex/Claude $20, biz yarı fiyatına".
2. **$100 Pro = 10x fiyat, 12x kota** — üst segmente geçiş cazip (Copilot Max de tam 10x yapıyor).
3. **Takım ayrı paket** — koltuk + ortak havuz karışımı (tek başına koltuk limiti adaletsiz).
4. **Kullanıcıya gösterim:** Sadece **"Bu ay %37 kaldı"** + renkli bar.

### 3.1 5 saat + haftalık limit tasarımı

Aylık kota **ana ölçü**, üzerine yumuşak hız kırıcılar:

| Katman | Kural | UX |
|---|---|---|
| **5 saatlik pencere** | Saatte ~X mesaj (Plus: 60, Pro: 400) | "Birazdan devam edebilirsin, kalan: 23 dk" |
| **Haftalık kapak** | Aylık kotanın ~%40'ı | Bir günde tüm ayı bitirmeyi engeller |
| **Aylık kota** | Nihai sınır (hard stop) | Bitince "ek paket al" / "yükselt" |

**Kota devri: DEVROLMAZ.** Sözleşmeye tek cümle: *"Kullanılmayan kota bir sonraki döneme devretmez."*

---

## 4. Model Kataloğu (canlı OpenRouter fiyatları, 2026-09-29)

### 4.1 Eleme kriterleri

Kullanıcıya açılacak her model için **zorunlu**:
- ✅ `supported_parameters` içinde `tools` + `tool_choice` + `response_format`/`structured_outputs`
- ✅ Görsel girdi (`input_modalities` içinde `image`)

**Elenenler:**
| Model | Sebep |
|---|---|
| `nex-agi/nex-n2.5-mini` | `tools` **yok** |
| `amazon/nova-lite-v1` | `tool_choice` **yok** |
| `moonshotai/kimi-k2` | `response_format`/structured output **yok** |
| `deepseek/deepseek-v4-flash` | görsel yok → sadece gizli sub-agent |
| `z-ai/glm-5.3` | görsel yok → sadece gizli sub-agent |
| `qwen/qwen3-coder` | görsel yok → sadece gizli sub-agent |

### 4.2 🟢 Kullanıcıya Açık — Giriş / Orta (Çinli ağırlıklı)

| Model | Menşe | $/1M in | $/1M out | Cache read | Ctx | Konum |
|---|---|---|---|---|---|---|
| ⭐ **Auto** (`openrouter/auto`) | — | dinamik | dinamik | — | — | **Varsayılan / Önerilen** |
| `qwen/qwen3.7-flash` | 🇨🇳 Alibaba | **0.03** | **0.13** | 0.006 | 1M | **Ucuz** |
| `inclusionai/ling-3.0-flash-vl` | 🇨🇳 Ant Group | **0.021** | **0.062** | 0.004 | 262k | Ultra-ucuz |
| `qwen/qwen3.8-flash` | 🇨🇳 Alibaba | 0.15 | 0.47 | 0.016 | 1M | **Dengeli** |
| `bytedance-seed/seed-1.6-flash` | 🇨🇳 ByteDance | 0.075 | 0.30 | — | 262k | Hızlı |
| `google/gemma-4-31b-it` | 🇺🇸 Google | 0.09 | 0.34 | 0.05 | 262k | Batılı alternatif |
| `xiaomi/mimo-v2.6-pro` | 🇨🇳 Xiaomi | 0.435 | 0.87 | **0.0036** | 1M | **Güçlü-orta** |
| `z-ai/glm-5.3-flash` | 🇨🇳 Z.ai | 0.15 | 0.50 | 0.03 | 1.3M | Güçlü-orta |
| `openai/gpt-5-nano` | 🇺🇸 OpenAI | 0.05 | 0.40 | 0.005 | 400k | Marka sevenler |

> "Sadece Çinli olmayacak" — Batılı ucuz modeller (Gemma, GPT-nano, Mistral) listede var ama
> **varsayılan ve "Önerilen" rozetli olanlar Çinli**.

### 4.3 🔥 Kullanıcıya Açık — Frontier (GPT-6 / Claude-5.x)

| Model | $/1M in | $/1M out | Cache read | Ctx | Not |
|---|---|---|---|---|---|
| `openai/gpt-6-sol` | **2** | **10** | 0.2 | 1M | **Frontier makul** |
| `anthropic/claude-sonnet-5.5` | **2** | **10** | 0.2 | 1M | **Frontier makul** |
| `anthropic/claude-opus-5.5` | 4 | 20 | 0.2 | 1M | **Frontier güçlü** |
| `openai/gpt-6-sol-pro` | 2 | 10 | 0.2 | 1M | Pro varyant |
| `google/gemini-3.5-flash` | 1.5 | 9 | 0.15 | 1M | Orta-üst (opsiyonel) |
| `x-ai/grok-4.7` | 2 | 6 | 0.5 | 500k | Orta-üst (opsiyonel) |

⚠️ **Kaçınılacaklar** (marjı mahveder): `openai/gpt-6-astra` ($10/$50), `anthropic/claude-fable-5.1` ($10/$50),
`openai/gpt-5.5-pro` ($30/$180), `openai/o1-pro` ($150/$600).

### 4.4 🕵️ Gizli Sub-Agent Tier'ları (kullanıcı asla görmeyecek)

| İş zorluğu | Model | $/1M in | $/1M out | Not |
|---|---|---|---|---|
| Basit (arama, özet, tarama) | `openai/gpt-oss-120b` 🎯 | 0.037 | 0.17 | **Tam 120B parametre**, Apache-2.0 |
| Çok basit | `inclusionai/ling-3.0-flash` | 0.021 | 0.063 | Metin-only, bedavaya yakın |
| Kod | `qwen/qwen3-coder` | 0.30 | 1.00 | Kod-özel, 262k ctx |
| Kod (ucuz) | `deepseek/deepseek-v4-flash` | 0.076 | 0.153 | 1M ctx |
| **Otomatik (önerim)** | `openrouter/pareto-code` + `minCodingScore: 0.33` | dinamik | dinamik | En ucuz uygun kod modeli + 2 fallback |

**"120B parametre" hakkında teknik not:** Popüler modeller MoE olduğu için iki rakam telaffuz edilir
(DeepSeek V3 **671B toplam / 37B aktif**, Kimi K2 **~1T / 32B aktif**). Ama **fiyatlar token başına**,
parametre başına değil → maliyeti belirleyen `$ / token` ve kalitedir. `gpt-oss-120b` tam 120B **dense**
bir model ve ucuz — hayalin kelimesi kelimesine gerçek.

### 4.5 Kredi çarpanı sistemi (doğal olarak zaten var)

Copilot'un "model multiplier" tablosuna gerek yok. `input/output_credits_per_1k_tokens` alanları
**zaten doğal çarpan sistemi**. Örnek oranlar (marj %30, 1 kredi ≈ $0.001):

| Tier | in kredi/1k | out kredi/1k | Tur (20k+1k) | Ucuz modele göre |
|---|---|---|---|---|
| Qwen3.7-flash | 0.04 | 0.17 | **~1 kredi** | 1x |
| Qwen3.8-flash | 0.20 | 0.61 | ~4.6 kredi | 5x |
| MiMo v2.6 Pro | 0.57 | 1.13 | ~12.5 kredi | 13x |
| **gpt-6-sol / claude-sonnet-5.5** | 2.6 | 13 | **~65 kredi** | **68x** |
| claude-opus-5.5 | 5.2 | 26 | ~130 kredi | 137x |

**Paket başına gerçek kullanım:**

| Paket | Kredi | Sadece ucuz | Karışım | Sadece frontier |
|---|---|---|---|---|
| **Plus $10** | 2.500 | ~2.600 tur (85/gün) | ~830 tur (27/gün) | ~38 tur (1/gün) |
| **Pro $100** | 30.000 | ~31.000 tur | ~10.000 tur (330/gün) | ~460 tur (15/gün) |

→ *"İster en iyi modeli kullansın, 5 sohbette bitirsin limitini"* — frontier seçen hızlı biter,
ucuz seçen bol kullanır. **Kullanıcının kendi seçimi.**

---

## 5. Cache Pricing (madde 1)

### 5.1 OpenRouter cache mekanizması (doğrulandı)

Her yanıtta `usage` alanı gelir:
```json
{
  "prompt_tokens": 194,
  "prompt_tokens_details": {
    "cached_tokens": 0,
    "cache_write_tokens": 100
  },
  "completion_tokens": 2,
  "completion_tokens_details": { "reasoning_tokens": 0 },
  "cost": 0.95
}
```

**Cache okuma çarpanları:**

| Sağlayıcı | Cache read | Cache write |
|---|---|---|
| DeepSeek | **0.1x** | — |
| Alibaba (Qwen) | **0.1x** | 1.25x |
| Anthropic | 0.1x | 1.25x |
| Google | 0.25x | — |
| Moonshot | 0.25x | — |
| Groq | 0.5x | — |

### 5.2 `session_id` sticky routing (KRİTİK)

OpenRouter cache'i sıcak tutmak için **provider sticky routing** yapar (10 dk timeout).
`session_id` gönderilirse routing garantilenir. Gönderilmezse cache isabeti düşer.

> **`session_id` = sohbet oturumu kimliği. Tek satırlık iş ama cache gelirinin belkemiği.**

### 5.3 Cache dahil gerçek tur maliyeti (20k girdi + 1k çıktı, %80 cache isabeti)

| Model | Cache'siz tur | **Cache'li tur** | Kazanç | 1 agent mesajı (6 çağrı) |
|---|---|---|---|---|
| `qwen/qwen3.7-flash` | $0.00073 | $0.00050 | 1.5x | **$0.003** |
| `qwen/qwen3.8-flash` | $0.0035 | $0.0021 | 1.6x | $0.013 |
| `xiaomi/mimo-v2.6-pro` | $0.0096 | **$0.0027** | **3.6x** 🚀 | $0.016 |
| `deepseek/deepseek-v4.1-flash` | $0.0072 | $0.0025 | 2.9x | $0.015 |
| `anthropic/claude-sonnet-4.5` | $0.075 | $0.047 | 1.6x | $0.28 |

🔥 **MiMo v2.6 Pro'da cache read $0.0036/1M** — normal girdinin **%0.8'i**. Güçlü modeli cache'li
agent akışında kullanmak beklenenden **3.6x ucuz**.

### 5.4 Uygulanacak formül

$$\text{kredi} = \frac{(\text{cached} \times \text{in\_rate} \times m_{\text{cache}}) + (\text{fresh} \times \text{in\_rate}) + (\text{completion} \times \text{out\_rate})}{1000}$$

($m_{\text{cache}}$: tier'a göre 0.1 / 0.25 / 0.5)

**Kullanıcıya etkisi:** Aynı sohbette tur maliyeti 1.5x–3.6x ucuzlar. Tooltip'te: *"Uzun sohbetlerde daha ucuz."*

---

## 6. Tokenizer Kararı (madde 5)

### 6.1 Kendi ölçümümüz (tiktoken o200k_base ile, 2026-09-29)

| İçerik tipi | Gerçek token | Bizim tahmin (len/4) | Sapma |
|---|---|---|---|
| TypeScript kod | 157 | 164 | **+4.5%** (fazla, güvenli) |
| JSON + TR payload | 127 | 123 | −3.1% |
| **Uzun Türkçe metin** | **215** | **175** | **−18.6%** ⚠️ |

⚠️ **Kritik bulgu:** Uzun Türkçe prose'de tahmin **%19 eksik** kalıyor (Türkçe ekli kelimeler
tokenizasyonda parçalanıyor). Türkçe konuşan kullanıcıda ön provizyon sürekli yetersiz →
ledger sapması → "kredim haksız eriyor" hissi.

### 6.2 Karar: 3 adım

1. **Kısa vade (1 gün iş):** `tiktoken` (o200k_base) + **%20 güvenlik payı**. Offline, ücretsiz.
   Sapmayı −18%'den ±5%'e indirir.
2. **Orta vade:** Settle zaten **gerçek sayımı** yapıyor (OpenRouter native tokenizer) → fatura doğru.
3. **İsteğe bağlı:** Anthropic/Google tier'ları için sağlayıcının `count_tokens` API'si (ek gecikme getirir).

---

## 7. Kaçırılan 15 Madde → Karar Tablosu

| # | Konu | Karar | Yöntem |
|---|---|---|---|
| 1 | Cache pricing | ✅ **Dahil** | `cached_tokens`/`cache_write_tokens` ayrı fiyatla + `session_id` sticky routing |
| 2 | Sub-agent kontrolü | ✅ **3 katman** | Sistem promptu kuralı + hard bütçe kill-switch + derinlik 5→2 |
| 3 | DB'ye maliyet yazma | ✅ **Yazılacak** | 8 yeni alan + `cost_daily_rollup` tablosu |
| 4 | Reasoning token | ✅ **Paralı + açıklama** | `out_rate` ile kes + "12 sn düşündü" notu + `effort: low` opsiyonu |
| 5 | Tokenizer | ✅ **tiktoken + %20 pay** | Piyasa standardı; Türkçe −18% sapmayı düzeltir |
| 6 | Hesap paylaşımı | ✅ **Claude/Codex modeli** | Sözleşme maddesi + eşzamanlı oturum limiti + anomali alarmı |
| 7 | Ödeme testi | 📝 **Ayrı session** | Dodo/Paddle sandbox → `provider_price_id` → `POST /billing/checkout` |
| 8 | Auto Router | ✅ **Bağlanacak** | `openrouter/auto` + `costTier: "low"` + `allowed_models` çiti |
| 9 | Pareto Router | 📖 **OpenRouter'ın kendi özelliği** | `openrouter/pareto-code` + `minCodingScore` → sub-agent için ideal |
| 10 | Fallback + alternatif sağlayıcı | ✅ **Çift katman** | OpenRouter `models` array + LiteLLM/Portkey yedek |
| 11 | Free tier | ✅ **`:free` YOK** | Ucuz Çinli + 100 kredi/ay (maliyet $0.015/ay) |
| 12 | Vision pahalı | ✅ **Karışmayız** | Normal fiyat, tooltip'te not |
| 13 | Tooltip tasarımı | ✅ **ⓘ hover kartı** | `price_note_tr` + `speed/quality_hint` backend'de hazır |
| 14 | Burst/eşzamanlılık | ✅ **Kota hard-stop + makul paralel** | Komşu koruması; keyfi kısıt YOK |
| 15 | Kota devri | ✅ **Devrolmaz** | Aylık sıfırla, sözleşmeye yaz |

### 7.1 Madde 2 — Sub-agent 3 katmanlı kontrol

| Katman | Ne yapar | Etki |
|---|---|---|
| **1. Sistem promptu** | *"Tek görevi yap. Alt ajan oluşturma. Gereksiz araç çağırma. Maks N adım."* | İyi niyetli modeli durdurur |
| **2. Hard limit (backend)** | Tek chat mesajı başına maks kredi bütçesi (Plus: 50, Pro: 400). Aşınca zincir zorla durur | Kötü senaryoyu kesin durdurur |
| **3. Derinlik + dallanma** | `RUN_SUBAGENT_MAX_NESTING_DEPTH`: 5 → **2**; tek seviyede maks 4 paralel | Üstel patlamayı kökten keser |

### 7.2 Madde 3 — DB'ye eklenecek alanlar (`usage_events`)

| Alan | Ne işe yarar |
|---|---|
| `upstream_cost_usd` | OpenRouter `usage.cost` — **gerçek dolar maliyeti**, marj takibinin temeli |
| `cached_prompt_tokens` | Cache'ten okunan token |
| `cache_write_tokens` | Cache'e yazılan token |
| `reasoning_tokens` | Düşünme token'ları |
| `selected_model_id` | Auto/sub-agent hangi modeli seçti |
| `parent_request_id` | Sub-agent'ın bağlı olduğu ana istek → zincir maliyeti |
| `session_id` | Sohbet bazlı cache isabet analizi |
| `finish_reason` | `tool_calls` / `length` / `stop` |

**Ek tablo — `cost_daily_rollup`:** Günlük kullanıcı × model bazında toplam USD + kredi + token.
*"Bu kullanıcı bize $2.30'a mal oldu, $10 ödedi"* sorusuna SQL ile 1 saniyede cevap.

### 7.3 Madde 4 — Reasoning token

- **Paralı:** `reasoning_tokens` normal completion gibi `out_rate` ile kesilir (OpenRouter FAQ:
  *"models that charge ... for reasoning tokens"*).
- **Açıklama şart:** Yanıt altında ince gri yazı *"Bu yanıt 12 sn düşünme içeriyor"* +
  tooltip *"Bu model uzun düşünür, daha çok kredi harcar."*
- **Alternatif:** `reasoning: {"effort": "low"}` varsayılan yapıp kullanıcı isterse "derin düşünme"
  alsın → reasoning maliyetini **10x** düşürebilir.

### 7.4 Madde 6 — Hesap paylaşımı

1. **Sözleşme maddesi** (Anthropic cümlesinin Türkçesi) — kayıt sırasında checkbox.
2. **Eşzamanlı oturum limiti:** Plus: 2, Pro: 5, Takım: koltuk başına 2.
3. **Anormal kullanım alarmı (soft):** 3+ farklı IP/cihaz + 24 saatte 500+ istek → admin panelinde
   sarı bayrak. Otomatik ban yok, önce inceleme.

### 7.5 Madde 8 — Auto Router bağlanması

1. `model_tiers` tablosuna: `alias: "auto"`, `upstream_model_id: "openrouter/auto"`.
2. İstek gövdesine: `plugins: [{"id": "auto-router", "costTier": "low"}]`.
3. **Güvenlik çiti:** `allowed_models` ile sadece onaylı listeye kısıtla.
4. ⚠️ `sanitize_request()` şu an `plugins` ve `models` alanlarını **dropluyor** → eklenmeli.

**Bonus:** `X-OpenRouter-Metadata: enabled` ile hangi görev tipine nasıl karar verdiğini görebiliriz
(30 görev tipi: `code:debugging`, `agent:multi_step_planning`...). Bu veriyle ileride kendi
"Faz B sınıflandırıcı" eğitilebilir.

### 7.6 Madde 9 — Pareto Router (başka sağlayıcı DEĞİL)

OpenRouter'ın kendi özelliği (`openrouter/pareto-code`). Tek sayı: `min_coding_score` (0-1).
*"Kodlama skoru en az bu kadar iyi olan modellerden **en ucuzunu** seç"* (Artificial Analysis
coding percentile'a göre). 2 same-tier fallback otomatik gelir.

| `min_coding_score` | Tier | Anlamı |
|---|---|---|
| ≥ 0.66 | high | Alanın en iyileri |
| 0.33–0.66 | medium | Güçlü modern amiral gemileri |
| < 0.33 | low | Medyan üstü çalışan kodlayıcılar |

**Aynı aileden — Auto Exacto:** Tool-calling içeren isteklerde provider sırasını otomatik optimize
eder (tool-call başarı oranı + GPQA + Tau2-bench). **Zaten varsayılan açık.**

### 7.7 Madde 10 — Fallback + alternatif sağlayıcılar

**a) OpenRouter içi fallback (ücretsiz, hazır):**
```json
{"models": ["qwen/qwen3.8-flash", "google/gemma-4-31b-it", "deepseek/deepseek-v4.1-flash"]}
```
İlk model hata verirse (rate limit, çökme, moderasyon reddi, context aşımı) otomatik sonrakine geçer.
Fiyat, kullanılan modelden kesilir. ⚠️ `sanitize_request()` `models` alanını dropluyor → eklenmeli.

**b) Sistem değişmeden geçilebilecek alternatifler (OpenAI-uyumlu):**

Bizim mimari **zaten OpenAI-uyumlu** (`/v1/chat/completions` + SSE). `UPSTREAM_BASE_URL` +
`UPSTREAM_API_KEY` değişince geçiş tamam — **kod değişikliği sıfır**.

| Sağlayıcı | Ne | Geçiş kolaylığı |
|---|---|---|
| **LiteLLM Proxy** (açık kaynak) | 100+ sağlayıcıya tek API, kendi sunucunda | ⭐⭐⭐⭐⭐ |
| **Portkey AI Gateway** | Ticari gateway, fallback + maliyet takibi + cache | ⭐⭐⭐⭐⭐ |
| **Together / Fireworks / DeepInfra / Groq / Novita** | Doğrudan ucuz açık-kaynak model hosting | ⭐⭐⭐⭐ |
| **Unify / Martian / Requesty** | Akıllı router'lar (en ucuz/en hızlı sağlayıcıyı seçer) | ⭐⭐⭐⭐ |

**Ek — OpenRouter BYOK:** Kendi provider key'lerimizi OpenRouter'a takabiliriz. Ücret: normal fiyatın
**%5'i** (aylık $25.000 list-price'a kadar ücretsiz). Prioritized/Fallback bölümleri var.

**Pratik strateji:** Ana = OpenRouter (fallback + cache + tek fatura). Yedek = LiteLLM Proxy
(kendi sunucumuzda, 2. sağlayıcı hesabı hazır). OpenRouter çökerse `.env` değişir, 5 dakikada geçilir.

### 7.8 Madde 11 — Free tier

**OpenRouter'ın kendi free limitleri:** Kredisiz hesap `:free` modellerde **günde 50 istek**;
$10+ kredili hesap **günde 1.000 istek**.

**Karar: `:free` varyantlarına BULAŞMA.** Bizim free plan 100 kredi/ay ≈ 30 mesaj. `qwen/qwen3.7-flash`
ile gerçek maliyet: 30 × $0.0005 ≈ **$0.015/ay**. `:free`'nin "50 istekte duvara çarpma" tecrübesi
$0.015 tasarrufa değmez.

Free plan davranışı: Ayda 100 kredi → bitince "Plus'a geç" ekranı. Free'in amacı kullanım değil,
**deneyim + dönüşüm hunisi** (Devin aynen böyle: *"Light quota to code with agents"*).

### 7.9 Madde 13 — Tooltip mockup

Backend'de **zaten hazır**: `price_note_tr`, `speed_hint`, `quality_hint`, `context_window`.
Sadece UI tooltip'i eksik.

**Ucuz model:**
```
┌──────────────────────────────────────┐
│  ⚡ Qwen 3.8 Flash                    │
│  "Dengeli — günlük kullanım için"     │
│                                       │
│  Hız      ●●●●○                       │
│  Kalite   ●●●○○                       │
│  Maliyet  ●○○○○  (çok ucuz)           │
│                                       │
│  ✓ Görsel destekli                    │
│  ✓ Araç çağırma (tool)                │
│  📷 1M token bağlam                   │
│                                       │
│  💡 Ne için: genel kodlama, refactor,  │
│     günlük görevler. Uzun sohbetlerde │
│     önbellek sayesinde daha da ucuzlar.│
└──────────────────────────────────────┘
```

**Frontier model:**
```
┌──────────────────────────────────────┐
│  🔥 Claude Sonnet 5.5                 │
│  "Frontier — en zor görevler için"    │
│                                       │
│  Hız      ●●○○○                       │
│  Kalite   ●●●●●                       │
│  Maliyet  ●●●●●  (çok pahalı)         │
│                                       │
│  ⚠️ Bu model 20x daha çok kredi harcar│
│  💡 Ne için: mimari kararlar, zor hata │
│     ayıklama, kritik refactor.        │
│     Günlük işler için önerilmez.      │
└──────────────────────────────────────┘
```

### 7.10 Madde 14 — Burst/eşzamanlılık açıklaması

*"Adam parasını ödediyse kullanmasın mı?"* → **Kullansın.** Sorun o değil, iki gerçek risk var:

**Risk 1 — Bir kullanıcının diğerlerini rehin alması:** `global:rpm` limiti tek OpenRouter key'ini
korur. Bir kullanıcı 20 paralel stream açarsa **herkes yavaşlar**. Burst limiti "kullanıcıyı kısıtlamak"
için değil, "bir kişinin tüm sistemi kilitlememesi" için.

**Risk 2 — Farkında olmadan bütçe patlaması:** Sub-agent zinciri ile tek mesaj yüzlerce çağrı yapabilir.
Kullanıcı "ben sadece dedim ki şunu yap" der, sabah $50 fatura gelir → itiraz + iade + kötü yorum.
Yani bu koruma **kullanıcının dostu**.

**Çözüm (kullanıcının "5 sohbette bitirsin" fikriyle uyumlu):**
- ✅ Kota = **hard stop**. Bitince durur, eksiye düşmez. Kullanıcı ister 5, ister 500 sohbette bitirsin.
- ✅ Paralel stream limiti: Plus 3, Pro 8, Takım 10 (koltuk başına 2). Tek amaç: komşunun suyunu kesmemek.
- ❌ "Şu saatte şu kadar istek" gibi **keyfi** kısıtlar YOK.

---

## 8. Backend Hazır mı? — Skor Kartı

| Özellik | Durum |
|---|---|
| Auth / JWT / abonelik / 30 günlük dönem | ✅ Hazır |
| Kredi ledger (atomik + dayanıklı) + per-user token takibi | ✅ Hazır |
| Ödeme (Dodo/Paddle/Stripe, MoR) webhook zinciri | 🟡 Test edildi, gerçek checkout + `provider_price_id` boş |
| RPM limit + circuit breaker + admin CRUD | ✅ Hazır |
| Kredi barı + kota bildirimi UI (%50/75/90/95 eşik) | ✅ Hazır |
| Model tier katalog + TR fiyat notu | ✅ Hazır |
| **$10/$100/Takım merdiveni** | 🟡 Tablo uygun — seed verisi + `provider_price_id` güncellenmeli |
| **5 saat + haftalık limit** | ❌ Sıfırdan (Redis sliding window + UI) |
| **Cache pricing (`cached_tokens`)** | ❌ Hesaplanmıyor |
| **`session_id` sticky routing** | ❌ Gönderilmiyor |
| **Gizli (internal) sub-agent tier ayrımı** | ❌ Yok (`is_internal` bayrağı + sunucu-side çağrı kilidi) |
| **Tool/görsel zorunluluğu doğrulaması** | ❌ Yok (2 tier text-only) |
| **Sub-agent maliyet kill-switch** | ❌ Yok → **üstel maliyet riski** |
| **`usage.cost` (gerçek USD) maliyet logu** | ❌ Tutulmuyor → marj takibi kör |
| **Auto tier** | ❌ Yok ama OpenRouter Auto Router ile ucuz kurulur |
| **`models` / `plugins` passthrough** | ❌ `sanitize_request()` dropluyor |
| **OpenRouter'a geçiş** | 🟡 Sadece `.env` (`UPSTREAM_BASE_URL=https://openrouter.ai/api/v1`) |

---

## 9. Öncelik Sırası (öneri)

| Öncelik | İş | Neden |
|---|---|---|
| 🔴 P0 | `session_id` + cache pricing | En büyük kaçan gelir/kalem (3-4x maliyet düşüşü) |
| 🔴 P0 | Sub-agent bütçe kill-switch + derinlik 5→2 | Üstel maliyet bombası |
| 🟠 P1 | `usage.cost` + 8 yeni alan + `cost_daily_rollup` | Marj takibi kör olmasın |
| 🟠 P1 | `models`/`plugins` passthrough + Auto tier | Auto Router + fallback açılır |
| 🟠 P1 | tiktoken + %20 pay | Türkçe sapma düzeltmesi |
| 🟡 P2 | $10/$100/Takım seed + `provider_price_id` | Satışa başlamak için |
| 🟡 P2 | 5s/haftalık limit + tooltip UI | Kullanıcı deneyimi |
| 🟢 P3 | Gizli sub-agent tier (`is_internal`) | Maliyet optimizasyonu |
| 🟢 P3 | LiteLLM yedek sağlayıcı | Süreklilik |

---

## 10. Kaynaklar

- OpenRouter canlı model kataloğu: `GET https://openrouter.ai/api/v1/models` (460 model, 2026-09-29)
- [OpenRouter — Prompt Caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching) (cache çarpanları, `session_id` sticky routing)
- [OpenRouter — Usage Accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting) (`usage.cost`, `cached_tokens`, `reasoning_tokens`)
- [OpenRouter — Auto Router](https://openrouter.ai/docs/guides/routing/routers/auto-router) (`cost_tier`, 30 görev tipi)
- [OpenRouter — Pareto Router](https://openrouter.ai/docs/guides/routing/routers/pareto-router) (`min_coding_score`)
- [OpenRouter — Auto Exacto](https://openrouter.ai/docs/guides/routing/auto-exacto) (tool-calling provider optimizasyonu)
- [OpenRouter — Model Fallbacks](https://openrouter.ai/docs/guides/routing/model-fallbacks) (`models` array)
- [OpenRouter — BYOK](https://openrouter.ai/docs/guides/overview/auth/byok) (%5 ücret, $25.000 ücretsiz pay)
- [OpenRouter — FAQ](https://openrouter.ai/docs/faq) (free limitleri: 50/1.000 RPD, kredi ücreti %5.5)
- [GitHub Copilot — Plans](https://docs.github.com/en/copilot/get-started/plans) ($10=1.000 / $39=3.900 / $100=10.000 AI Credits)
- [Devin — Pricing](https://devin.ai/pricing) ($0/$20/$200, takım $80+$40/koltuk, günlük+haftalık kota)
- [Claude — Pro/Max + Claude Code](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan) (paylaşılan limit, usage credits)
- [Anthropic — Consumer Terms](https://www.anthropic.com/legal/consumer-terms) §2 (hesap paylaşımı yasağı)
- [Cursor — Docs](https://cursor.com/docs) ("Hidden by default", cache çarpanları)
- [Lovable — Pricing](https://lovable.dev/pricing) (workspace havuzlu kredi + üye limiti)
- [OpenAI — Rate Limits](https://platform.openai.com/docs/guides/rate-limits) (organizasyon seviyesi limit, usage tiers)
- [Anthropic — Count Tokens API](https://platform.claude.com/docs/en/api/messages/count_tokens)
- [Portkey — AI Gateway](https://portkey.ai/docs/integrations/llms/openai) (alternatif sağlayıcı)
- Kendi ölçümümüz: `tiktoken` o200k_base ile Türkçe/İngilizce/kod token sapma testi (2026-09-29)