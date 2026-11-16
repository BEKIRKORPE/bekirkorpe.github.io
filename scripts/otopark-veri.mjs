// Rangeo Plus — Türkiye otopark verisi (haftalık, GitHub Actions'ta çalışır)
// OpenStreetMap (Overpass) -> sarjharitasi/otoparklar.json
// Uygulama bu dosyayı boşta iken arka planda bir kez indirir; otopark modu açılınca beklemeden gösterir.
//
// Dosya biçimi (küçük olsun diye sıkıştırılmış):
//   { v: 1, t: <oluşturma zamanı ms>, d: [[enlem*1e5, boylam*1e5, kapalı(0/1), "ad", {ek bilgi}], ...] }
//   ek bilgi anahtarları: p=parking türü, f=fee, c=capacity, cc=capacity:charging, h=maxheight,
//   oh=opening_hours, ac=access, s=supervised, op=operator  (boş olanlar yazılmaz)
import { writeFileSync, existsSync } from "node:fs";

const SUNUCU = [
  "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
];
const UA = "RangeoPlus-otopark-veri/1.0 (github.com/bekirkorpe)";
const CIKTI = "sarjharitasi/otoparklar.json";
const EN_AZ = 10000; // bundan azı bozuk çekim sayılır, eski dosya korunur
// Türkiye'yi 2°x2° parçalara böl (tek sorgu sunucuda zaman aşımına düşmesin)
const GUNEY = 35.8, KUZEY = 42.2, BATI = 25.6, DOGU = 44.9, ADIM = 2;
const KISA = { parking: "p", fee: "f", capacity: "c", "capacity:charging": "cc", maxheight: "h", opening_hours: "oh", access: "ac", supervised: "s", operator: "op" };

function kapaliMi(t) {
  return t.parking === "multi-storey" || t.parking === "underground" || t.parking === "rooftop" || t.parking === "carports" ||
    t.building === "parking" || t.covered === "yes" || t.indoor === "yes";
}
const bekle = ms => new Promise(r => setTimeout(r, ms));

async function sorgula(b) {
  const q = `[out:json][timeout:180];area["ISO3166-1"="TR"][admin_level=2]->.a;` +
    `nwr["amenity"="parking"]["access"!~"^(private|no)$"]["parking"!~"^(street_side|lane|on_kerb|half_on_kerb|layby)$"](area.a)(${b.join(",")});out center qt;`;
  for (let tur = 0; tur < 2; tur++) {
    for (const url of SUNUCU) {
      try {
        const ctl = new AbortController(), zt = setTimeout(() => ctl.abort(), 240000);
        const r = await fetch(url, { method: "POST", body: "data=" + encodeURIComponent(q), signal: ctl.signal,
          headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA, Accept: "application/json" } });
        clearTimeout(zt);
        if (!r.ok) throw new Error("HTTP " + r.status);
        const j = await r.json();
        if (!j || !Array.isArray(j.elements)) throw new Error("bozuk cevap");
        if (j.remark && /error|timed out|runtime/i.test(j.remark)) throw new Error("sunucu: " + j.remark);
        return j.elements;
      } catch (e) {
        console.log(`  ${url.split("/")[2]}: ${e.message}`);
        await bekle(5000);
      }
    }
    await bekle(30000);
  }
  throw new Error("parça indirilemedi: " + b.join(","));
}

const satirlar = [], gorulen = new Set();
let parca = 0;
for (let la = GUNEY; la < KUZEY; la += ADIM) {
  for (let lo = BATI; lo < DOGU; lo += ADIM) {
    const b = [la, lo, Math.min(la + ADIM, KUZEY), Math.min(lo + ADIM, DOGU)].map(v => +v.toFixed(2));
    parca++;
    const el = await sorgula(b);
    let n = 0;
    for (const e of el) {
      const id = e.type[0] + e.id; if (gorulen.has(id)) continue;
      const a = e.lat ?? e.center?.lat, o = e.lon ?? e.center?.lon, t = e.tags || {};
      if (!Number.isFinite(a) || !Number.isFinite(o)) continue;
      gorulen.add(id); n++;
      const ek = {};
      for (const [uzun, kisa] of Object.entries(KISA)) if (t[uzun]) ek[kisa] = String(t[uzun]).slice(0, 80);
      const s = [Math.round(a * 1e5), Math.round(o * 1e5), kapaliMi(t) ? 1 : 0, (t.name || "").slice(0, 60)];
      if (Object.keys(ek).length) s.push(ek);
      satirlar.push(s);
    }
    console.log(`parça ${parca} [${b}] -> ${n} otopark (toplam ${satirlar.length})`);
    await bekle(2000); // sunucuya nazik ol
  }
}

if (satirlar.length < EN_AZ) {
  console.log(`Sadece ${satirlar.length} otopark geldi (en az ${EN_AZ} bekleniyordu): eski dosya korunuyor.`);
  process.exit(existsSync(CIKTI) ? 0 : 1);
}
satirlar.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
const json = JSON.stringify({ v: 1, t: Date.now(), d: satirlar });
writeFileSync(CIKTI, json);
console.log(`Yazıldı: ${CIKTI} — ${satirlar.length} otopark, ${(json.length / 1048576).toFixed(2)} MB`);
