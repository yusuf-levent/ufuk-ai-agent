# ADIM 6 Araştırma Raporu — VS Code'un Workspace Context / Kod İndeksleme Mekanizmaları

> Kod yazılmadan önce yapılan araştırma (görev gereği). Soru: VS Code'un kendi
> Copilot/Agent altyapısında zaten bir workspace context / kod indeksleme
> mekanizması var mı ve Ufuk modelleri için kullanılabilir mi?

## Özet Sonuç

**VS Code'da GÜÇLÜ mekanizmalar var ve çoğu Ufuk modellerine AÇIK.** Eski
projedeki "proje haritası" özelliğinin (dosya ağacı + imza çıkarımı + önbellek)
büyük kısmını VS Code zaten karşılıyor. Sıfırdan bir proje haritası
mekanizması yazmak **yeniden icat olur**. Küçük bir boşluk var (aşağıda),
ama o boşluk için de tam bir repo-map katmanı değil, ince bir iyileştirme
yeterli olabilir.

## Bulunan Mekanizmalar

### 1. `copilot_readProjectStructure` — dosya ağacı tool'u ✅ Ufuk'a açık

- **Nerede:** `extensions/copilot/src/extension/tools/node/readProjectStructureTool.ts`
- **Ne yapar:** Workspace'in görsel dosya ağacını üretir (`workspaceVisualFileTree`,
  `MultirootWorkspaceStructure` prompt element'i, `maxSize: 1000` karakter bütçesi,
  dot-file hariç tutma). Tam olarak eski projedeki "dosya ağacı" kısmı.
- **Bağımlılık:** Yerel dosya sistemi. GitHub/Copilot API **gerekmez**.
- **Ufuk'a açıklık:** Copilot extension `vscode.lm.registerTool` ile kaydeder
  (`extension/tools/vscode-node/tools.ts:34`), workbench `_allToolsObs` üzerinden
  agent host'a akar. Tool enablement varsayılanı **açık**
  (`agentHostToolSetEnablementService.ts:42` — `?? true`). Ufuk modelleri
  `copilotcli` session tipini kullanır, tool'lar session tipine göre filtrelenmez.

### 2. `copilot_searchWorkspaceSymbols` — sembol arama ✅ Ufuk'a açık

- **Nerede:** `extensions/copilot/src/extension/tools/node/searchWorkspaceSymbolsTool.tsx`
- **Ne yapar:** VS Code'un kendi workspace symbol provider'ını sorgular
  (`languageFeaturesService.getWorkspaceSymbols`). Fonksiyon/sınıf isimlerini
  konumlarıyla döndürür (ilk 20 sonuç). Eski projedeki "imza çıkarımı"nın
  VS Code karşılığı — tree-sitter tabanlı language server'lardan beslenir.
- **Bağımlılık:** Yerel language server'lar. GitHub/Copilot API gerekmez.
- **Ufuk'a açıklık:** Yukarıdakiyle aynı — açık.

### 3. `semantic_search` / `#codebase` — anlamsal arama ⚠️ Ufuk'a KAPALI (Copilot API bağımlı)

- **Nerede:** `extensions/copilot/src/extension/tools/node/codebaseTool.tsx`
  (`copilot_searchCodebase`), agent host tarafında `SEMANTIC_SEARCH_TOOL_NAME`
  (`src/vs/platform/agentHost/common/semanticSearchConstants.ts:13`).
- **Ne yapar:** Workspace'i chunk'lar, GitHub'ın embedding API'siyle
  (`metis_1024_I16_Binary`) vektörleştirir, sorguya göre en alakalı kod
  parçalarını döndürür. Önbellek + artımlı indeksleme var
  (`workspaceChunkEmbeddingsIndex.ts`).
- **Bağımlılık:** GitHub oturumu + Copilot embedding endpoint'leri
  (`githubAvailableEmbeddingTypes.ts:105` — `getGitHubSession`).
- **Ufuk'a açıklık:** Tool kaydı agent'a açılır (`agentHostActiveClientService.ts:383`,
  `chat.copilot.semanticSearch.enabled` ayarıyla), ANCAK çalışma zamanında
  `workspaceChunkSearchService.isAvailable()` false döner (GitHub auth yoksa)
  ve tool "Semantic workspace search is not currently available" mesajı
  döndürür (`codebaseTool.tsx:88-92`). Yani: **kayıtlı ama işlevsiz**.

### 4. Diğer yerel tool'lar ✅ Ufuk'a açık

`copilot_findFiles`, `copilot_findTextInFiles`, `copilot_listDirectory`,
`copilot_readFile`, `copilot_getErrors` — hepsi yerel, hepsi agent'a açık.
Bunlar zaten agent'ın proje tarama zincirinin (list_dir → read_file) parçası.

### 5. Tool search (tool keşfi)

`toolSearch` + `deferThreshold` mekanizması var (`copilotSessionLauncher.ts:1117`):
agent tüm tool tanımlarını her istekte taşımak yerine tool'ları arayabiliyor.
Token tasarrufu sağlar ama repo tarama davranışını değiştirmez.

## Değerlendirme: Eski Projenin "Proje Haritası" vs VS Code Mevcudu

| Eski proje özelliği | VS Code karşılığı | Ufuk'ta durum |
|---|---|---|
| Dosya ağacı | `copilot_readProjectStructure` | ✅ Çalışır |
| Fonksiyon/sınıf imzaları | `copilot_searchWorkspaceSymbols` (sorgu bazlı) | ✅ Çalışır |
| Regex tabanlı çıkarım | Language server'lar (tree-sitter) — daha doğru | ✅ Çalışır |
| Önbellek + artımlı güncelleme | Symbol provider kendi yönetir; dosya ağacı her çağrıda tazelenir | ✅/🟡 |
| Anlamsal alt küme seçimi | `semantic_search` (embedding) | ❌ Copilot API gerekli |
| Boyut bütçesi | `maxSize: 1000` (ağaç), ilk 20 sonuç (sembol) | ✅ Var |

## Sonuç ve Öneri

**2-4. adımlara (kendi proje haritamızı yazmaya) girmeyi ÖNERMİYORUM.** VS Code'un
mecanizmaları eski projeninkinden daha yetkin (tree-sitter vs regex, dil desteği
geniş) ve Ufuk modellerine açık. Yeniden yazmak bakım yükü ve tutarsızlık yaratır.

**Kalan tek gerçek boşluk:** `semantic_search`'ün Ufuk'ta çalışmaması. Ama bu bir
"proje haritası" sorunu değil, embedding altyapısı sorunu. Çözüm istenirse:
(a) Ufuk backend'ine bir embedding endpoint'i ekleyip `IWorkspaceChunkSearchService`'i
ona yönlendirmek (orta ölçekli iş), veya (b) mevcut yerel tool'larla yetinmek
(agent zaten `readProjectStructure` + `searchWorkspaceSymbols` + `findTextInFiles`
zinciriyle projeyi verimli tarayabiliyor).

**Ölçüm (4. adım) notu:** Harita yazmadığımız için önce/sonra tool-call ölçümü
yapılmadı. Gerekçe: ölçülecek mekanizma (kendi repo map'imiz) üretilmedi;
mevcut VS Code mekanizmaları zaten agent'a açık ve görev başına tool-call
sayısı model davranışına bağlı.
