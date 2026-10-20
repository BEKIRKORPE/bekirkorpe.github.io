// Türkiye Şarj Haritası — günlük veri birleştirme (GitHub Actions'ta çalışır)
// Open Charge Map + OpenStreetMap -> sarjharitasi/stations.json
import { writeFileSync, mkdirSync } from "node:fs";

const OCM_KEY = process.env.OCM_KEY || "";
const OCM_URL = "https://api.openchargemap.io/v3/poi/?output=json&countrycode=TR&maxresults=20000&compact=false&verbose=false&opendata=true&key=" + OCM_KEY;
const OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"];
const SORGU = '[out:json][timeout:180];area["ISO3166-1"="TR"][admin_level=2]->.a;nwr["amenity"="charging_station"](area.a);out center meta;';
const UA = "TurkiyeSarjHaritasi-veri/1.0 (github.com/bekirkorpe)";
const ESIK_M = 150;
// Kullanıcı bildirimleri (Supabase). Anahtar herkese açık "publishable" anahtardır; sadece özet fonksiyonunu çağırabilir.
const SUPA_URL = process.env.SUPA_URL || "https://njovzzztvxdmrqlfrcvo.supabase.co";
const SUPA_KEY = process.env.SUPA_KEY || "sb_publishable_L8lNaClfegwTgJFiiOorGw_zC0KvTs2";
const KULLANICI_ID = 1e14;      // kullanıcı istasyonlarının kimlik aralığı (OCM ve OSM ile çakışmaz)
const DURUM_GUN = 14;           // çalışıyor/çalışmıyor bildirimleri bu kadar gün geçerli
const DOGRULANMAMIS_GUN = 120;  // tek kişinin eklediği istasyon bu kadar gün sonra düşer

export function km(a1, o1, a2, o2) {
  const R = 6371, r = Math.PI / 180, x = (a2 - a1) * r, y = (o2 - o1) * r;
  const h = Math.sin(x / 2) ** 2 + Math.cos(a1 * r) * Math.cos(a2 * r) * Math.sin(y / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
const s = v => (v == null ? "" : String(v).trim());
const r6 = d => Math.round(d * 1e6) / 1e6;

export function ocmDonustur(liste) {
  const out = [];
  for (const p of liste || []) {
    const a = p && p.AddressInfo;
    if (!a || typeof a.Latitude !== "number" || typeof a.Longitude !== "number") continue;
    let op = s(p.OperatorInfo && p.OperatorInfo.Title); if (op.startsWith("(")) op = "";
    const st = p.StatusType;
    const durum = st && st.IsOperational != null ? (st.IsOperational ? 1 : 0) : -1;
    const v = s(p.DateLastVerified) || s(p.DateLastStatusUpdate);
    const adres = [];
    for (const x of [s(a.AddressLine1), s(a.Town), s(a.StateOrProvince)]) if (x && !adres.join(", ").includes(x)) adres.push(x);
    const c = [];
    for (const cn of p.Connections || []) {
      if (!cn) continue;
      const cur = cn.CurrentTypeID;
      c.push([s(cn.ConnectionType && cn.ConnectionType.Title), Math.round((Number(cn.PowerKW) || 0) * 10) / 10,
        cur === 30 ? 1 : (cur === 10 || cur === 20 ? 0 : -1), cn.Quantity > 0 ? cn.Quantity : 1]);
    }
    out.push({ i: p.ID, a: r6(a.Latitude), o: r6(a.Longitude), t: s(a.Title), d: adres.join(", "), p: op, s: durum, v: v.slice(0, 10), u: s(p.UsageCost), c });
  }
  return out;
}

const SOKET = {
  type2_combo: ["CCS (Type 2)", 1], chademo: ["CHAdeMO", 1], tesla_supercharger: ["Tesla Supercharger", 1], nacs: ["Tesla (NACS)", 1],
  tesla_supercharger_ccs: ["CCS (Type 2)", 1], type2: ["Type 2 (Socket Only)", 0], type2_cable: ["Type 2 (Tethered Connector)", 0],
  type1: ["Type 1 (J1772)", 0], type1_combo: ["CCS (Type 1)", 1], gb_dc: ["GB/T DC", 1], schuko: ["Schuko (Ev prizi)", 0], cee_blue: ["CEE Mavi", 0]
};
function guc(v) { const m = s(v).replace(",", ".").match(/([\d.]+)\s*(kw|w)?/i); if (!m) return 0; let n = parseFloat(m[1]); if (m[2] && m[2].toLowerCase() === "w") n /= 1000; return isFinite(n) ? Math.round(n * 10) / 10 : 0; }
const TIP = { node: 0, way: 1, relation: 2 };

export function osmDonustur(el) {
  const out = [];
  for (const e of el || []) {
    const lat = typeof e.lat === "number" ? e.lat : e.center && e.center.lat;
    const lon = typeof e.lon === "number" ? e.lon : e.center && e.center.lon;
    if (typeof lat !== "number" || typeof lon !== "number") continue;
    const t = e.tags || {};
    const c = [];
    for (const k of Object.keys(t)) {
      const m = k.match(/^socket:([a-z0-9_]+)$/); if (!m) continue;
      const adet = parseInt(t[k], 10); if (!(adet > 0)) continue;
      const tanim = SOKET[m[1]] || [m[1], -1];
      c.push([tanim[0], guc(t["socket:" + m[1] + ":output"]), tanim[1], adet]);
    }
    const op = s(t.operator) || s(t.brand) || s(t.network);
    const adres = [s(t["addr:street"]) + (t["addr:housenumber"] ? " " + s(t["addr:housenumber"]) : ""), s(t["addr:district"]), s(t["addr:city"]) || s(t["addr:province"])].filter(Boolean);
    const v = s(t.check_date) || s(e.timestamp);
    out.push({ i: -(e.id * 10 + (TIP[e.type] || 0)), x: e.type + "/" + e.id, a: r6(lat), o: r6(lon), t: s(t.name) || op || "Şarj istasyonu",
      d: adres.join(", "), p: op, s: -1, v: v.slice(0, 10), u: s(t.charge) || (t.fee === "no" ? "Ücretsiz" : ""), c });
  }
  return out;
}

// OSM noktalarından OCM'de ESIK_M içinde karşılığı olmayanları ekler
export function birlestir(ocm, osm, esikM = ESIK_M) {
  const h = 0.002, izgara = new Map(), k = (a, b) => Math.floor(a / h) + ":" + Math.floor(b / h);
  for (const p of ocm) { const key = k(p.a, p.o); if (!izgara.has(key)) izgara.set(key, []); izgara.get(key).push(p); }
  const eklenen = [];
  for (const p of osm) {
    const i = Math.floor(p.a / h), j = Math.floor(p.o / h); let var_ = false;
    for (let di = -1; di <= 1 && !var_; di++) for (let dj = -1; dj <= 1 && !var_; dj++) {
      for (const q of izgara.get((i + di) + ":" + (j + dj)) || []) if (km(p.a, p.o, q.a, q.o) * 1000 <= esikM) { var_ = true; break; }
    }
    if (!var_) eklenen.push(p);
  }
  return { list: ocm.concat(eklenen), eklenen: eklenen.length, ortak: osm.length - eklenen.length };
}

const KULLANICI_SOKET = { "CCS": ["CCS (Type 2)", 1], "Type 2": ["Type 2 (Socket Only)", 0], "CHAdeMO": ["CHAdeMO", 1], "Tesla": ["Tesla Supercharger", 1], "Diğer": ["Diğer", -1] };
function enCok(arr) { const m = new Map(); for (const x of arr) if (x) m.set(x, (m.get(x) || 0) + 1); let best = "", n = 0; for (const [k, v] of m) if (v > n) { best = k; n = v; } return best; }

// raporlar: [{id, created_at, tur, istasyon_id, lat, lon, ad, operator, soket, kw, c}] (c = cihaz özeti)
export function kullaniciBirlestir(list, raporlar, simdi = Date.now()) {
  const gun = 864e5, mevcut = new Map(list.map(s => [s.i, s]));
  const yeniler = raporlar.filter(r => r.tur === "yeni" && typeof r.lat === "number" && typeof r.lon === "number").sort((a, b) => a.id - b.id);
  const kumeler = [];
  for (const r of yeniler) {
    let kume = kumeler.find(k => km(k.lat, k.lon, r.lat, r.lon) * 1000 <= 30);
    if (!kume) { kume = { id: r.id, lat: r.lat, lon: r.lon, r: [] }; kumeler.push(kume); }
    kume.r.push(r);
  }
  let eklenen = 0;
  for (const k of kumeler) {
    if (list.some(s => km(s.a, s.o, k.lat, k.lon) * 1000 <= 30)) continue; // 30 m içinde: aynı istasyon (kullanıcı "yine de ekle" dese bile)
    const i = -(KULLANICI_ID + k.id);
    const cihazlar = new Set(k.r.map(r => r.c));
    for (const r of raporlar) if (r.tur === "dogrula" && r.istasyon_id === i) cihazlar.add(r.c);
    const sonTarih = Math.max(...k.r.map(r => Date.parse(r.created_at) || 0));
    if (cihazlar.size < 2 && simdi - sonTarih > DOGRULANMAMIS_GUN * gun) continue;
    const soketli = k.r.filter(r => r.soket).slice(-1)[0];
    const tanim = soketli ? (KULLANICI_SOKET[soketli.soket] || ["Diğer", -1]) : null;
    const st = { i, a: r6(k.lat), o: r6(k.lon), t: enCok(k.r.map(r => s(r.ad))) || "Şarj istasyonu", d: "", p: enCok(k.r.map(r => s(r.operator))),
      s: -1, v: new Date(sonTarih).toISOString().slice(0, 10), u: "", c: tanim ? [[tanim[0], Number(soketli.kw) || 0, tanim[1], 1]] : [], y: 1, k: cihazlar.size };
    list.push(st); mevcut.set(i, st); eklenen++;
  }
  // çalışıyor / çalışmıyor: her cihazın son bildirimi sayılır
  const son = new Map();
  for (const r of raporlar) {
    if (r.tur !== "calismiyor" && r.tur !== "calisiyor") continue;
    if (simdi - (Date.parse(r.created_at) || 0) > DURUM_GUN * gun) continue;
    const key = r.istasyon_id + "|" + r.c, onceki = son.get(key);
    if (!onceki || r.id > onceki.id) son.set(key, r);
  }
  let durumlu = 0;
  const sayac = new Map();
  for (const r of son.values()) {
    const x = sayac.get(r.istasyon_id) || { b: 0, w: 0 };
    if (r.tur === "calismiyor") x.b++; else x.w++;
    sayac.set(r.istasyon_id, x);
  }
  for (const [id, x] of sayac) { const st = mevcut.get(id); if (st) { st.b = x.b; st.w = x.w; durumlu++; } }
  return { eklenen, durumlu };
}

async function raporlariGetir() {
  const r = await fetch(SUPA_URL + "/rest/v1/rpc/sarj_bildirim_liste", { method: "POST",
    headers: { apikey: SUPA_KEY, "Content-Type": "application/json", "User-Agent": UA }, body: "{}", signal: AbortSignal.timeout(60000) });
  if (!r.ok) throw new Error("Supabase " + r.status);
  const j = await r.json();
  if (!Array.isArray(j)) throw new Error("Supabase beklenmeyen cevap");
  return j;
}

async function getir(url, opt, deneme = 3) {
  let son;
  for (let n = 1; n <= deneme; n++) {
    try {
      const r = await fetch(url, { ...opt, headers: { "User-Agent": UA, ...(opt && opt.headers) }, signal: AbortSignal.timeout(240000) });
      if (!r.ok) throw new Error(url + " -> " + r.status);
      return await r.json();
    } catch (e) { son = e; console.log("Deneme " + n + " başarısız: " + e.message); await new Promise(z => setTimeout(z, 15000 * n)); }
  }
  throw son;
}

export async function calistir(cikti = "sarjharitasi/stations.json") {
  if (!OCM_KEY) throw new Error("OCM_KEY tanımlı değil (GitHub Secrets)");
  const ocmHam = await getir(OCM_URL);
  const ocm = ocmDonustur(ocmHam);
  let osm = [], osmHata = "";
  for (const u of OVERPASS) {
    try {
      const j = await getir(u, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "data=" + encodeURIComponent(SORGU) }, 2);
      osm = osmDonustur(j.elements); osmHata = ""; break;
    } catch (e) { osmHata = e.message; }
  }
  if (ocm.length < 500) throw new Error("OCM verisi şüpheli derecede az: " + ocm.length + " (eski dosya korunuyor)");
  const b = birlestir(ocm, osm);
  let kul = { eklenen: 0, durumlu: 0 }, kulHata = "";
  try { kul = kullaniciBirlestir(b.list, await raporlariGetir()); } catch (e) { kulHata = e.message; }
  const veri = {
    ts: Date.now(), count: b.list.length, sources: { ocm: ocm.length, osm: osm.length, osmEklenen: b.eklenen, osmHata, kullanici: kul.eklenen, durumBildirimli: kul.durumlu, kulHata },
    license: "Open Charge Map (CC BY 4.0) ve © OpenStreetMap katkıcıları (ODbL). Birleşik veri ODbL kapsamında açıktır.",
    list: b.list
  };
  mkdirSync(cikti.split("/").slice(0, -1).join("/") || ".", { recursive: true });
  writeFileSync(cikti, JSON.stringify(veri));
  console.log(`Tamam: OCM ${ocm.length}, OSM ${osm.length} (yeni ${b.eklenen}), kullanıcı ${kul.eklenen}, durum bildirimli ${kul.durumlu}, toplam ${b.list.length}${osmHata ? " | OSM hatası: " + osmHata : ""}${kulHata ? " | Bildirim hatası: " + kulHata : ""}`);
  return veri;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  calistir().catch(e => { console.error("HATA:", e.message); process.exit(1); });
}
