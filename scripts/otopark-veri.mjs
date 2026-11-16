// Rangeo Plus — Türkiye otopark verisi (haftalık, GitHub Actions'ta çalışır)
// OpenStreetMap Türkiye kopyası (Geofabrik) -> osmium ile otoparklar ayıklanır -> sarjharitasi/otoparklar.json
// (Genel Overpass sunucuları tüm Türkiye sorgusunda zaman aşımına düşüyor; Geofabrik dosyası güvenilir ve sunuculara yük bindirmez.)
// Uygulama bu dosyayı boşta iken arka planda bir kez indirir; otopark modu açılınca beklemeden gösterir.
//
// Kullanım: node scripts/otopark-veri.mjs otoparklar.geojsonseq
//
// Dosya biçimi (küçük olsun diye sıkıştırılmış):
//   { v: 1, t: <oluşturma zamanı ms>, d: [[enlem*1e5, boylam*1e5, kapalı(0/1), "ad", {ek bilgi}], ...] }
//   ek bilgi anahtarları: p=parking türü, f=fee, c=capacity, cc=capacity:charging, h=maxheight,
//   oh=opening_hours, ac=access, s=supervised, op=operator  (boş olanlar yazılmaz)
import { writeFileSync, existsSync, createReadStream } from "node:fs";
import { createInterface } from "node:readline";

const GIRDI = process.argv[2] || "otoparklar.geojsonseq";
const CIKTI = "sarjharitasi/otoparklar.json";
const EN_AZ = 10000; // bundan azı bozuk çekim sayılır, eski dosya korunur
const KISA = { parking: "p", fee: "f", capacity: "c", "capacity:charging": "cc", maxheight: "h", opening_hours: "oh", access: "ac", supervised: "s", operator: "op" };
const ATLA_ERISIM = /^(private|no)$/, ATLA_TUR = /^(street_side|lane|on_kerb|half_on_kerb|layby)$/;

function kapaliMi(t) {
  return t.parking === "multi-storey" || t.parking === "underground" || t.parking === "rooftop" || t.parking === "carports" ||
    t.building === "parking" || t.covered === "yes" || t.indoor === "yes";
}
// Geometrinin orta noktası (alanlarda dış halkanın köşe ortalaması: otopark için yeterince doğru)
function merkez(g) {
  if (!g) return null;
  if (g.type === "Point") return g.coordinates;
  const pts = g.type === "LineString" ? g.coordinates : g.type === "Polygon" ? g.coordinates[0] : g.type === "MultiPolygon" ? g.coordinates[0][0] : null;
  if (!pts || !pts.length) return null;
  let x = 0, y = 0; for (const p of pts) { x += p[0]; y += p[1]; }
  return [x / pts.length, y / pts.length];
}

const satirlar = [];
let okunan = 0;
const rl = createInterface({ input: createReadStream(GIRDI), crlfDelay: Infinity });
for await (let satir of rl) {
  satir = satir.replace(/^\x1e/, "").trim(); if (!satir) continue;
  okunan++;
  let f; try { f = JSON.parse(satir); } catch { continue; }
  const t = f.properties || {};
  if (t.amenity !== "parking" || ATLA_ERISIM.test(t.access || "") || ATLA_TUR.test(t.parking || "")) continue;
  const c = merkez(f.geometry); if (!c || !Number.isFinite(c[0]) || !Number.isFinite(c[1])) continue;
  const ek = {};
  for (const [uzun, kisa] of Object.entries(KISA)) if (t[uzun]) ek[kisa] = String(t[uzun]).slice(0, 80);
  const s = [Math.round(c[1] * 1e5), Math.round(c[0] * 1e5), kapaliMi(t) ? 1 : 0, String(t.name || "").slice(0, 60)];
  if (Object.keys(ek).length) s.push(ek);
  satirlar.push(s);
}
console.log(`Okunan kayıt: ${okunan}, otopark: ${satirlar.length}`);

if (satirlar.length < EN_AZ) {
  console.log(`Sadece ${satirlar.length} otopark (en az ${EN_AZ} bekleniyordu): eski dosya korunuyor.`);
  process.exit(existsSync(CIKTI) ? 0 : 1);
}
satirlar.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
const json = JSON.stringify({ v: 1, t: Date.now(), d: satirlar });
writeFileSync(CIKTI, json);
console.log(`Yazıldı: ${CIKTI} — ${satirlar.length} otopark, ${(json.length / 1048576).toFixed(2)} MB`);
