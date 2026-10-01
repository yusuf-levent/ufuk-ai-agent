# Ufuk Kullanım Koşulları

**Sürüm:** `2026-10` · **Yürürlük:** 2026-10-01

Bu belge, Ufuk abonelik hizmetinin kullanım koşullarını tanımlar. Kayıt sırasında
"kullanım koşullarını kabul ediyorum" kutusunu işaretleyen kullanıcılar bu
hükümleri kabul etmiş sayılır. Koşulları kabul etmeyen hesaplar "grandfathered"
sayılır ve sonradan eklenen hükümler geriye dönük uygulanmaz.

## 1. Abonelik ve Kotalar

1.1. Her abonelik dönemi **30 gündür** ve plana tanımlı kredi, eşzamanlı istek ve
görsel üretimi kotaları ile birlikte gelir.

1.2. **Kullanılmayan kota bir sonraki döneme devretmez.** Kredi, görsel ve diğer
kotalar dönem sonunda sıfırlanır; bir sonraki döneme aktarılmaz.

1.3. **Paralı planlarda dönem, ödeme olmadan kendiliğinden uzamaz.** Yenileme
ödemesi alınmadıkça yeni dönem açılmaz ve hizmet devam etmez. Ücretsiz (free)
planlarda dönem, dönüşüm hunisi olarak kendiliğinden yenilenir.

1.4. Kota aşımlarında istek **üretim gerçekleşmeden** reddedilir; negatif bakiye
oluşmaz. Kota, kaç sohbet açıldığına bakılmaksızın toplam kullanımı sınırlar.

1.5. Tek bir istek ve kısa zaman penceresi için ayrı üst sınırlar
(`max_credits_per_request`, `max_credits_per_window`) geçerlidir. Bunlar, alt
ajan zincirlerinin kontrolsüz büyümesini engellemek için konulmuştur.

## 2. Hesap Paylaşımı

2.1. Bir hesap, aynı anda en fazla planında tanımlı sayıda istek işleyebilir
(`max_concurrent_requests`). Bu sınır, hesabın birden çok kişi tarafından
aynı anda kullanılmasını yumuşak biçimde caydırmak içindir.

2.2. Anormal kullanım (çok sayıda farklı istemciden erişim) tespit edilirse hesap
incelemeye alınabilir. Ham IP adresleri saklanmaz; yalnızca kullanıcıya özel
tuzlanmış özetler kullanılır.

## 3. Fiyatlandırma ve Maliyet

3.1. Sohbet kullanımı, modele göre tanımlı kredi oranlarıyla faturalanır. Önbellek
(cache) okuma ve yazma işlemleri ayrı katsayılarla fiyatlandırılır.

3.2. Akıl yürütme (reasoning) token'ları çıktı token'larının bir alt kümesidir ve
ayrı bir primle çarpılır; toplam maliyet asla iki kez hesaplanmaz.

3.3. Görsel üretimi, çözünürlük kalitesine göre ağırlıklı kredi harcar
(standart 1K = 1, yüksek 2K = 2, ultra 4K = 8 kredi). Yüksek çözünürlük talebi
asla maliyet altına satılmaz.

## 4. Gizlilik

4.1. Hesabınızı sildiğinizde kişisel verileriniz ve ürettiğiniz görseller
(dosyalar dahil) sistemlerimizden kaldırılır. Kullanım kayıtları, maliyet
takibi için anonimleştirilerek saklanabilir.

4.2. Ayrıntılar için [privacy-rules.md](./privacy-rules.md) belgesine bakınız.

## 5. Değişiklikler

5.1. Bu koşullar güncellendiğinde `terms_version` değeri yükseltilir. Yeni sürümü
kabul etmeyen mevcut kullanıcılar, kabul ettikleri sürüm hükümleriyle hizmet
almaya devam eder; yeni kayıtlar güncel sürümü kabul etmek zorundadır.