# Ufuk Agent System — Detaylı Araştırma Raporu

> Tarih: 2026-09-26
> Kapsam: `C:\Users\Yusuf\Desktop\ufuk agent system` (eski/Ufuk) + `C:\Users\Yusuf\Desktop\ufuk_agent_system` (yeni/VS Code fork) + VS Code Agents mimarisi
> Not: Bu rapor sadece araştırma içerir, kod değişikliği yapılmamıştır.

---

## 1. İki Projenin Karşılaştırması

| Konu | Eski Proje (`ufuk agent system` — boşluklu) | Yeni Proje (`ufuk_agent_system` — alt çizgili) |
|---|---|---|
| Durum | Milestone 1–10 tamam, çalışan ürün | Sıfırdan iskelet, VS Code fork denemesi |
| `frontend/` | Var — Electron 44 + React 18 + Zustand + Tailwind, 128 vitest + 11 Playwright e2e | Yok (bilerek silinmiş) |
| `evren-agent/` | Var — `agent-core` + `local-runner` + CLI, 237 test, ayrı git repo (gitlink) | Yok |
| `evren-backend/` | Var — FastAPI + Postgres:5433 + Redis:6380 | Var — **dosya dosya birebir aynı** |
| `vscode/` | Yok | Var — `microsoft/vscode` tam klonu (commit `529ee190`, `origin https://github.com/microsoft/vscode.git`) |
| `pnpm-workspace.yaml` | `evren-agent/packages/*` + `frontend` | Aynı içerik ama hedef klasörler artık yok → `pnpm install` bozuk |
| `.gitignore` | `vscode/` yok | `vscode/` ignore edilmiş (`git -C vscode pull` ile güncellenecek) |
| `docs/` | `STATUS.md` / `PLAN.md` / `PROGRESS.md` / `SECURITY.md` | Yok (bu raporla oluşturuldu) |

**Sonuç:** Backend korunmuş, frontend/agent sıfırlanıp yerine VS Code konmuş. Doğru hamle — en zayıf halka UI/editör idi.

---

## 2. Abonelik Sistemi Nasıl Çalışacak? (Mevcut Backend Mantığı)

### 2.1 Akış (kullanıcı gözünden)

```
Kullanıcı kayıt → e-posta doğrulama → login (JWT access_token, 900s)
  → otomatik default plan atanır (ensure_default_subscription)
  → /v1/chat/completions isteği → gateway krediyi rezerve eder → upstream'e proxy → token sayar → krediyi kesinleştirir
  → /me, /usage, /plans ile kalan kredi / plan bilgisi
  → admin /plans ile plan atar, /admin ile yönetir
```

### 2.2 Veri modeli

- **Plan** (`app/models/plan.py`): `name`, `monthly_credit_limit` (Decimal 12,6), `max_output_tokens_per_request`, `requests_per_minute`, `allowed_tier_aliases[]`, `is_default`.
- **ModelTier** (`app/models/tier.py`): `alias` (örn. `fast`, `pro`), `upstream_model_id` (gerçek model adı), `upstream_provider_name`, `input/output_credits_per_1k_tokens`, `max_output_tokens`, `context_window`, `enabled`.
- **Subscription** (`app/models/subscription.py`): `user_id`, `plan_id`, `period_start/end` (30 gün), `status` (ACTIVE/CANCELLED). Plan değişince **aynı dönem korunur** — kredi sıfırlanmaz (abuse engeli).
- **UsageEvent** (`app/models/usage.py`): `request_id`, `tier_alias`, `upstream_model_id`, `credits_charged`, `prompt/completion_tokens`, `status` (RESERVED/SETTLED/FAILED), `estimated`.

### 2.3 Kredi / limit mekanizması

- **Rezervasyon:** İstek gelince `estimate_messages_tokens()` ile prompt token tahmini + `max_output_tokens` üzerinden `reserve_amount()` hesaplanır, Redis `credits:{user_id}:{period_key}` anahtarında `incrbyfloat` ile atomik rezerve edilir. Limit aşılırsa `402 quota_exceeded`.
- **Kesinleştirme:** Upstream SSE `usage` alanından gerçek `prompt_tokens`/`completion_tokens` okunur, `token_cost()` ile gerçek kredi hesaplanır, `ledger.adjust(delta)` ile fark düzeltilir, `usage_events` SETTLED yapılır. Bağlantı koparsa `completion_estimate()` ile tahmin üzerinden kesinleştirme.
- **Ledger senkronu:** Redis anahtarı yoksa `ensure_ledger_synced()` DB'deki `RESERVED+SETTLED` toplamından yeniden kurar (TTL = dönem sonuna kadar + 5 gün grace).
- **Rate limit:** `app/services/rate_limiter.py` + `check_rate_limit()` — plan başına `requests_per_minute`, ayrıca `/auth` için IP bazlı limitler.
- **Circuit breaker:** `app/services/circuit_breaker.py` — upstream çökerse hızlı fail.

### 2.4 OpenRouter / upstream bağlantısı

- **Tek yerden konfigürasyon:** `app/config.py` → `Settings` içinde `upstream_base_url`, `upstream_api_key` (SecretStr), `upstream_auth_header` (Authorization / X-API-Key), `upstream_timeout_seconds` (300s). `.env` / `.env.example` ile yönetilir.
- **UpstreamClient** (`app/services/upstream.py`): `httpx.AsyncClient`, `sanitize_request()` ile sadece izinli alanları geçirir (`ALLOWED_REQUEST_FIELDS`), `model` alanını `tier.upstream_model_id` ile **zorla ezer** (kullanıcı model seçemez), `max_tokens` plan limitine kırpılır, `stream_options: {include_usage:true}` eklenir. 2 deneme retry.
- **OpenRouter'a geçiş:** Sadece `.env` içinde `UPSTREAM_BASE_URL=https://openrouter.ai/api/v1` ve `UPSTREAM_API_KEY=sk-or-...` yapmak yeterli. Kod değişikliği gerekmez. İstersen `upstream_provider_name` ile provider bazlı yönlendirme de eklenebilir.
- **API key limitleri:** Kullanıcıya **hiçbir zaman** upstream API key verilmez. Tüm istekler gateway üzerinden proxy'lenir, gateway tek bir sunucu anahtarı kullanır. Kullanıcı bazlı limit = plan kredisi + rate limit. OpenRouter tarafında tek anahtarın limitini aşmamak için gateway'de global rate limit / kuyruk eklenebilir (şu an yok — eklenmesi önerilir).

### 2.5 Abonelik → para akışı

- Şu an backend'de **ödeme entegrasyonu yok** — plan atama manuel (`assign_plan()` / admin router). Abonelik satmak için Stripe/Iyzico webhook'u ekleyip `assign_plan()` çağırmak yeterli. `period_start/end` ve `monthly_credit_limit` zaten hazır.

---

## 3. IDE'yi Kaldırmak / Sadeleştirmek

### 3.1 "Agent System'den IDE'ye geçiş butonu" var mı?

VS Code'da böyle tek bir buton yok. Kastettiğin muhtemelen:

- **Explorer / Editor / Terminal / SCM** gibi workbench parçaları — hepsi `src/vs/workbench/contrib/*` altında contribution olarak kayıtlı.
- **Chat/Agent view** (`workbench/contrib/chat`) zaten ayrı bir view — IDE'den bağımsız durabilir.

**Yapılabilir:** `src/vs/workbench/browser/workbench.ts` ve `workbench/contrib/*` içinden istemediğin contribution'ları `package.json` / `product.json` veya `workbench.contribution.ts` kayıtlarından çıkararak gizleyebilirsin. Örneğin `terminal`, `scm`, `debug`, `extensions` view'lerini kapatıp sadece `chat` + `editor` + `explorer` bırakmak mümkün. Tamamen IDE'siz (sadece agent chat) isteniyorsa `workbench` yerine `chat` view'i ana view yapmak gerekir — bu daha derin bir değişiklik.

### 3.2 İhtiyaç olmayan IDE parçaları

Kaldırılması kolay (sadece contribution kaydını silmek / `when` clause ile gizlemek):

- `terminal`, `debug`, `scm` (git), `extensions` marketplace, `search`, `testing`, `notebook`, `mergeEditor`, `timeline`, `outline` gibi contrib'ler.
- `extensions/` altındaki dil eklentileri (`cpp`, `go`, `python`, `java` vb.) — `product.json` içindeki `builtInExtensions` listesinden çıkarılır.

Kaldırılması zor / riskli:

- `files` (explorer) — agent dosya yazıyorsa lazım.
- `editor` — diff / dosya görüntüleme için lazım.
- `workbench` çekirdeği — tamamen atılamaz.

**Öneri:** İlk sürümde sadece `extensions` marketplace + `terminal` + `debug` + `scm` gizle, `explorer` + `editor` + `chat` bırak. Sonra kademeli sadeleştir.

### 3.3 Plugin / MCP düzenlemesi

- **MCP:** `src/vs/workbench/contrib/mcp/` — `mcp.contribution.ts`, `mcpServersView.ts`, `mcpGatewayService.ts` vb. MCP sunucuları `mcp.json` / settings üzerinden yönetiliyor. Görsel olarak `MCP Servers` view'i var, burayı sadeleştirip sadece senin onayladığın MCP'leri gösterecek şekilde filtreleyebilirsin.
- **Plugin (Extension) marketplace:** `src/vs/workbench/contrib/extensions/` — `product.json` içindeki `extensionsGallery` ile marketplace URL'i belirlenir. Kendi marketplace'ini kurabilir veya tamamen kapatabilirsin (`extensionsGallery: null`).
- **Görsel düzenleme:** `chat` view içindeki `agentSessionsView`, `mcpServersView`, `chatView` CSS'leri `src/vs/workbench/contrib/chat/browser/` altında — Tailwind yok, VS Code'un kendi CSS variable sistemi var. Tasarımı değiştirmek için bu dosyaları override etmen gerekir.

---

## 4. Backend ↔ VS Code Agents Uyumu — Bağlarsan Çalışır mı?

### 4.1 Protokol uyumu

| Katman | Backend (evren-backend) | VS Code Agents | Uyum |
|---|---|---|---|
| Protokol | OpenAI-compatible `/v1/chat/completions` (SSE streaming, `usage` ile) | `ILanguageModelService` → `LanguageModelProvider` API, OpenAI formatını konuşur (Copilot provider da aynı) | **Uyumlu** |
| Streaming | `data: {...}\n\n` SSE, `stream_options: {include_usage:true}` | `vscode.lm` streaming'i aynı SSE'yi tüketir | Uyumlu |
| Model seçimi | `tier.alias` → `upstream_model_id` (kullanıcı model seçemez) | `languageModels.ts` içinde `modelSelection.ts` / `chatSelectedModel.ts` ile model picker | **Hook gerekli** — picker'ı tier alias'lara map'le |
| Auth | JWT `Authorization: ******` | `authentication` contribution + `ISecretStorageService` | Hook gerekli — VS Code secret storage → gateway JWT |
| Tool calling | `tools` / `tool_choice` passthrough (`ALLOWED_REQUEST_FIELDS`) | `chat` tool calling (MCP tools dahil) | Uyumlu — gateway zaten `tools` geçiriyor |
| Kredi / quota | `402 quota_exceeded`, `429 rate_limited` | `chatQuotaNotification.ts`, `chatErrorMessages.ts` | Hook gerekli — hata kodlarını VS Code notification'a çevir |

**Cevap: Evet, bağlarsan çalışır.** Gateway zaten OpenAI-compatible SSE konuşuyor, VS Code da aynı protokolü bekliyor. Tek yapılması gereken VS Code tarafında `LanguageModelProvider`'ı gateway'e yönlendirmek.

### 4.2 Nasıl bağlanır? (kod yazmadan mimari)

1. **Provider hook:** `src/vs/workbench/contrib/chat/common/languageModels.ts` içindeki `COPILOT_VENDOR_ID` yerine kendi vendor'ını (`ufuk` / `evren`) ekle veya Copilot extension'ını (`extensions/copilot`) fork'layıp `byok/*Provider.ts` içindeki `openrouter` provider'ını gateway URL'ine yönlendir. En az kodla çözüm: `extensions/copilot/src/extension/byok/vscode-node/openRouterProvider.ts` benzeri bir `evrenProvider.ts` yaz.
2. **Auth hook:** `src/vs/workbench/services/authentication/` + `ISecretStorageService` ile login ekranı (eski `LoginScreen.tsx` mantığı) → `POST /auth/login` → JWT'yi secret storage'a yaz → her LLM isteğinde `Authorization` header'ı ekle.
3. **Model picker hook:** `chatSelectedModel.ts` / `modelSelection.ts` içindeki model listesini `GET /plans` + `GET /tiers` (veya `GET /v1/models`) ile doldur, seçilen alias'ı `POST /v1/chat/completions` içinde `model` alanına koy (gateway zaten alias → upstream_model_id çeviriyor).
4. **Quota hook:** Gateway `402` / `429` dönünce `chatQuotaNotification.ts` ve `chatErrorMessages.ts` üzerinden kullanıcıya "kredin bitti, plan yükselt" göster.
5. **Rebrand:** `product.json` → `nameShort`, `nameLong`, `applicationName`, `dataFolderName`, `agentsTelemetryAppName`, `extensionsGallery` (kapat veya kendi gallery'n).

### 4.3 Riskler / dikkat edilmesi gerekenler

- **VS Code güncellemeleri:** `vscode/` `.gitignore`'da ve ayrı git history'si var — `git -C vscode pull` ile upstream merge ederken conflict çıkabilir. Provider hook'larını mümkün olduğunca `extensions/copilot` içinde tut, core `src/vs/*` değişikliğini minimal tut.
- **pnpm workspace bozuk:** `pnpm-workspace.yaml` hala `evren-agent/packages/*` ve `frontend`'i referans ediyor ama bu klasörler yok. Ya bu satırları sil ya da `evren-agent`'ı geri ekle (gateway hook'u için gerekebilir).
- **Global rate limit:** Şu an gateway'de kullanıcı bazlı limit var ama OpenRouter tek anahtarının global limiti için ek koruma yok — eklenmeli.
- **Ödeme:** Stripe/Iyzico entegrasyonu yok — abonelik satışı için eklenmesi şart.

---

## 5. Önerilen Yol Haritası (sırayla)

1. `pnpm-workspace.yaml` düzelt + `product.json` rebrand (isim, ikon, dataFolder).
2. `extensions/copilot` içinde `evrenProvider.ts` (gateway'e SSE proxy) + auth hook (JWT).
3. Model picker → tier alias map + quota notification hook.
4. Workbench sadeleştirme (extensions marketplace kapat, terminal/debug/scm gizle).
5. MCP view sadeleştirme + görsel düzenleme.
6. Ödeme webhook'u (Stripe/Iyzico → `assign_plan()`).
7. `gulp` + `electron-winstaller` ile installer build.

---

*Bu rapor araştırma amaçlıdır, kod değişikliği içermez.*
