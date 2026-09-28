# Otomatik Model Seçimi ("Auto") — Tasarım Notu (Sadece Plan, Kod Yok)

> Not: Bu bir tasarım önerisidir; henüz kodlanmamıştır. ADIM 4 stretch goal kapsamında
> yalnızca yaklaşım önerisi olarak yazılmıştır.

## Hedef

Kullanıcı "Otomatik" seçtiğinde, sistem isteğin karmaşıklığına göre 6 model arasından
en uygun fiyat/performans dengesini seçsin.

## Önerilen Yaklaşım: Kademeli Heuristik (Önce Basit, Sonra Akıllı)

### Faz A — Kural Tabanlı Heuristik (Önerilen İlk Adım)

Backend'de (`evren-backend`) yeni bir `auto` tier alias'ı ekle. Gateway, `model: "auto"`
geldiğinde istem içeriğine bakıp gerçek bir tier'a yönlendirir:

1. **İstem uzunluğu** (karakter/token sayısı): kısa istem (< ~500 token) → `fast`/`fast2`
2. **Tool-call varlığı**: tool tanımı gönderilmişse → en az `balanced` (tool-calling güvenilirliği)
3. **Anahtar kelime sinyalleri**: "analiz et", "refactor", "mimari", "debug et", "test yaz" gibi
   karmaşıklık belirten fiiller → `strong`/`strong2`; "selam", "teşekkür", kısa sorular → `fast`
4. **Kullanıcı kredisi**: kalan kredi düşükse (< %10) → en ucuz model
5. **Fallback**: hiçbir kural tetiklenmezse → `balanced` (mevcut "dengeli" konumu)

**Artıları:** Birkaç saatte implement edilir, deterministik, debug'ı kolay, ek maliyet yok.
**Eksileri:** Kaba; yanlış sınıflandırma olabilir; dil bağımlı (Türkçe/İngilizce anahtar kelimeler).

### Faz B — Küçük Sınıflandırıcı (Veri Toplandıkten Sonra)

Faz A çalışırken her isteğin `(istem özellikleri, seçilen model, kullanıcı memnuniyeti
— örn. yeniden gönderme/abort oranı, yanıt uzunluğu)` kaydını `usage_events`'e ekleyin.
Yeterli veri birikince (binlerce istek):

- Basit bir **logistic regression / gradient-boosted tree** (scikit-learn) eğit:
  girdi = istem uzunluğu, tool varlığı, geçmiş turn sayısı, dosya sayısı; çıktı = tier
- Modeli ONNX'e çevirip backend'e göm (ağır bağımlılık yok)
- Güven skoru düşükse (`balanced`'a dön) — yanlış seçim maliyeti asimetrik

**Artıları:** Daha isabetli, dil bağımsız özellikler.
**Eksileri:** Veri toplama süresi gerektirir; bakım yükü; soğuk başlangıç sorunu.

### Neden LLM-ile-sınıflandırma DEĞİL

"İstemi bir küçük modele gösterip hangi modelin uygun olduğunu sormak" yaklaşımı önerilmez:
ekstra gecikme + ekstra maliyet + özyineleme riski. Heuristik/sınıflandırıcı yeterli.

## VS Code Tarafı Entegrasyon Noktası

- Picker'a sentetik bir `ufuk/auto` modeli ekle (mevcut `auto` model deseni gibi —
  `isAutoModel` / `autoModeTiers` altyapısı referans)
- "Optimize for" dropdown'u (`AutoTierConfigKey`) mevcut `efficiency/balance/intelligence`
  profillerini `auto` tier'ına iletir; backend bu profili heuristiğin ağırlıklandırmasında kullanır
- `ufukProxyService` isteği olduğu gibi `model: "auto"` ile iletir; backend yanıttaki
  `model` alanını gerçek tier'a çevirip döner (mevcut `_transform_sse_line` zaten alias'a
  rewrite yapıyor — `auto` için gerçek seçilen tier'ı yazması gerekir)

## Kaba Efor Tahmini

- Faz A (heuristik): ~1 gün backend + yarım gün test
- Faz B (sınıflandırıcı): veri toplama 2-4 hafta (pasif) + 2-3 gün eğitim/entegrasyon
