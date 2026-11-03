# Atasun Optik — Mağaza XML Feed

`https://www.atasunoptik.com.tr/kurumsal/nerelerdeyiz_1476` sayfasındaki tüm mağazaları her gün çekip `docs/stores.xml` olarak yayınlar.

## Kurulum (GitHub Actions + Pages, ~5 dk)

1. GitHub'da yeni bir repo aç (örn. `atasun-store-feed`), bu klasördeki dosyaları yükle.
2. **Settings → Pages → Source:** "Deploy from a branch", branch `main`, klasör `/docs`.
3. **Actions** sekmesi → "Atasun mağaza XML güncelle" → **Run workflow** ile ilk çalıştırmayı yap.
4. Feed adresi: `https://<kullanıcı-adı>.github.io/atasun-store-feed/stores.xml`

Sonrasında her sabah 06:17'de (TR) otomatik çalışır.

## Çıktılar

| Dosya | İçerik |
|---|---|
| `docs/stores.xml` | Tüm mağazalar (kod, ad, tür, durum, saatler, telefonlar, adres, il/ilçe + ID, koordinat, mağaza sayfası URL'i) |
| `docs/changes.json` | Bir önceki güne göre eklenen / kapanan / bilgisi değişen mağazalar |

## Güvenlik kontrolü

Sayfadan 150'den az mağaza gelirse (site hatası, WAF engeli, şablon değişikliği) script mevcut XML'i **ezmez** ve iş başarısız olur — GitHub size e-posta bildirimi gönderir. Böylece boş/bozuk feed yayına çıkmaz.

## Notlar

- `type` alanı (AVM / Cadde / Diğer) mağaza adından türetilir; kaynak sitede ayrı bir alan yok.
- `status`: "Geçici olarak kapalıdır" yazan mağazalar `temporarily_closed`, diğerleri `open`.
- Telefonlar E.164 formatına (`+90...`) normalize edilir.
- Yerelde çalıştırmak için: `pip install requests beautifulsoup4 && python atasun_stores_to_xml.py`
