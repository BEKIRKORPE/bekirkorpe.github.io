// sürüm: 2026-10-21 G (Toger "DC/AC" başlığı düzeltmesi)
// Türkiye Şarj Haritası — günlük veri birleştirme (GitHub Actions'ta çalışır)
// Open Charge Map + OpenStreetMap -> sarjharitasi/stations.json
import { writeFileSync, mkdirSync, readFileSync, existsSync } from "node:fs";
import https from "node:https";
import http from "node:http";

const OCM_KEY = process.env.OCM_KEY || "";
const OCM_URL = "https://api.openchargemap.io/v3/poi/?output=json&countrycode=TR&maxresults=20000&compact=false&verbose=false&opendata=true&key=" + OCM_KEY;
const OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"];
const SORGU = '[out:json][timeout:180];area["ISO3166-1"="TR"][admin_level=2]->.a;nwr["amenity"="charging_station"](area.a);out center meta;';
const UA = "TurkiyeSarjHaritasi-veri/1.0 (github.com/bekirkorpe)";
const ESIK_M = 150;
// EPDK Serbest Erişim Platformu (Şarj Hizmeti Yönetmeliği md. 17/2, 30/1). Resmi, kimlik doğrulamasız REST servisi.
// Kota çok sıkı (filtresiz istek saatte 1): tek istek atılır, ASLA tekrar denenmez.
const EPDK_URL = process.env.EPDK_URL || "https://apigateway.epdk.gov.tr/sarjIstasyonlari";
const EPDK_ID = 3e14;          // EPDK istasyonlarının kimlik aralığı
const EPDK_EN_AZ = 5000;       // bundan azı bozuk çekim sayılır, önceki EPDK verisi kullanılır
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

// ---- EPDK
const EPDK_SOKET = { AC_TYPE2: "Type 2", AC_TYPE_2: "Type 2", DC_CCS: "CCS (Type 2)", DC_CCS2: "CCS (Type 2)", DC_CHADEMO: "CHAdeMO",
  AC_SCHUKO: "Schuko (Ev prizi)", DC_GBT: "GB/T DC", AC_GBT: "GB/T AC", DC_TESLA: "Tesla Supercharger", AC_TYPE1: "Type 1 (J1772)" };
function marka(raw) { // "zes" -> "Zes", "eşarj" -> "Eşarj"; zaten büyük harfli olana dokunma
  return s(raw).split(/\s+/).filter(Boolean).map(w => (w === w.toLocaleLowerCase("tr") && /^\p{L}/u.test(w)) ? w.charAt(0).toLocaleUpperCase("tr") + w.slice(1) : w).join(" ");
}
function epdkKimlik(kod) {
  const m = s(kod).match(/(\d+)\s*$/);
  if (m) return -(EPDK_ID + Number(m[1]));
  let h = 0; for (const ch of s(kod)) h = (h * 31 + ch.codePointAt(0)) % 1e9;
  return -(EPDK_ID + 5e13 + h);
}
const trIcinde = (a, o) => isFinite(a) && isFinite(o) && a >= 35.5 && a <= 42.5 && o >= 25.5 && o <= 45;
const sayi = v => Number(s(v).replace(",", "."));
// Koordinatı çöz: doğruysa al, enlem/boylam yer değiştirmişse düzelt, değilse sebebini söyle
export function konumCoz(r) {
  const ham1 = s(r.enlem), ham2 = s(r.boylam);
  if (!ham1 || !ham2) return { sebep: "koordinat boş" };
  const lat = sayi(ham1), lon = sayi(ham2);
  if (!isFinite(lat) || !isFinite(lon)) return { sebep: "koordinat okunamadı" };
  if (lat === 0 && lon === 0) return { sebep: "koordinat sıfır" };
  if (trIcinde(lat, lon)) return { a: lat, o: lon, duzeltme: (ham1.includes(",") || ham2.includes(",")) ? "virgul" : "" };
  if (trIcinde(lon, lat)) return { a: lon, o: lat, duzeltme: "yer-degistirme" };
  return { sebep: "Türkiye dışı" };
}
export function epdkDonustur(feed, bugun = new Date().toISOString().slice(0, 10), rapor = null) {
  const kayitlar = Array.isArray(feed) ? feed : (feed && Array.isArray(feed.data) ? feed.data : null);
  if (!kayitlar) throw new Error("EPDK beklenmeyen cevap biçimi");
  const out = [];
  for (const r of kayitlar) {
    if (!r) continue;
    const hizmet = s(r.hizmetSekli), halka = hizmet.toLocaleLowerCase("tr").startsWith("halka");
    const kod = s(r.sarjIstasyonuNo);
    if (!kod) { if (rapor) rapor.sebep["kodsuz"] = (rapor.sebep["kodsuz"] || 0) + 1; continue; }
    const k = konumCoz(r);
    if (rapor && k.duzeltme) rapor.duzeltilen[k.duzeltme] = (rapor.duzeltilen[k.duzeltme] || 0) + 1;
    if (k.sebep) {
      if (rapor) {
        rapor.sebep[k.sebep] = (rapor.sebep[k.sebep] || 0) + 1;
        rapor.konumsuz.push({ kod, ad: s(r.sarjIstasyonuAdi), adres: s(r.adres), marka: marka(r.marka), hizmet, sebep: k.sebep, ham: r });
      }
      continue;
    }
    out.push(epdkIstasyon(r, k.a, k.o, bugun, halka, hizmet));
  }
  return out;
}
// Tek bir EPDK kaydını uygulama biçimine çevirir (konum dışarıdan verilir: kayıttan veya adresten)
export function epdkIstasyon(r, lat, lon, bugun, halka, hizmet) {
  const kod = s(r.sarjIstasyonuNo);
  const gruplar = new Map();
  for (const k of r.soketler || []) {
    if (!k) continue;
    const tur = s(k.soketTuru).toUpperCase(), tip = s(k.soketTipi).toUpperCase();
    const ad = EPDK_SOKET[tur] || (tur.includes("CHADEMO") ? "CHAdeMO" : tur.includes("CCS") ? "CCS (Type 2)" : tur.includes("TYPE2") ? "Type 2" : (tur || tip || "Bilinmeyen"));
    const dc = tip === "DC" || tur.startsWith("DC") ? 1 : (tip === "AC" || tur.startsWith("AC") ? 0 : -1);
    const kw = Math.round((Number(k.soketGucu) || 0) * 10) / 10;
    const anahtar = ad + "|" + kw + "|" + dc;
    gruplar.set(anahtar, (gruplar.get(anahtar) || 0) + 1);
  }
  const c = [...gruplar].map(([k, q]) => { const [ad, kw, dc] = k.split("|"); return [ad, Number(kw), Number(dc), q]; })
    .sort((x, y) => y[1] - x[1]);
  // Not: kişi adı içerebilecek "sarjIstasyonuIsletmecisi" alanı bilerek alınmaz (KVKK)
  const st = { i: epdkKimlik(kod), e: kod, a: r6(lat), o: r6(lon), t: s(r.sarjIstasyonuAdi) || (marka(r.marka) + " Şarj Noktası").trim(),
    d: s(r.adres), p: marka(r.marka), s: -1, v: bugun, u: "", c };
  if (!halka) { st.k = 1; st.h = hizmet || "Belirtilmemiş"; } // özel / erişimi kısıtlı: uygulamada uyarı notuyla gösterilir
  return st;
}

// ---- Adresten konum bulma (Nominatim). Kural: en fazla 1 istek/sn, uygulama kimliği, sonuçlar saklanır.
const NOMINATIM = process.env.NOMINATIM_URL || "https://nominatim.openstreetmap.org/search";
const ONBELLEK = "sarjharitasi/konum-onbellek.json";
const ARAMA_SINIRI = 300;         // bir çalışmada en fazla bu kadar yeni adres aranır (~6 dk)
const BULUNAMADI_TEKRAR_GUN = 30; // bulunamayan adres 30 gün sonra tekrar denenir
// "Görgü Mahallesi No:104 Tavşantepe Yeşilyurt / MALATYA" -> [tam adres, "Görgü Mahallesi, Yeşilyurt, Malatya"]
export function adresSorgulari(adres) {
  const a = s(adres).replace(/\s+/g, " ");
  if (!a) return [];
  const parca = a.split("/"), il = s(parca[parca.length - 1]), sol = s(parca.slice(0, -1).join("/"));
  const ilce = s(sol.split(" ").pop());
  const mah = (sol.match(/([\p{L}\d.\- ]+?)\s+(Mahallesi|Mah\.?)/iu) || [])[1];
  const q = [ (sol + ", " + il).replace(/No\s*:\s*/gi, ""), ];
  if (mah && ilce && il) q.push(s(mah) + " Mahallesi, " + ilce + ", " + il);
  return q.filter((x, i, l) => x.length > 5 && l.indexOf(x) === i);
}
async function adresAra(q, bekle) {
  await bekle();
  const url = NOMINATIM + "?format=jsonv2&countrycodes=tr&limit=1&accept-language=tr&q=" + encodeURIComponent(q);
  const r = await fetch(url, { headers: { "User-Agent": UA, "Accept-Language": "tr" }, signal: AbortSignal.timeout(30000) });
  if (r.status === 429 || r.status >= 500) throw new Error("Nominatim " + r.status);
  if (!r.ok) return null;
  const j = await r.json();
  if (!Array.isArray(j) || !j.length) return null;
  const a = Number(j[0].lat), o = Number(j[0].lon);
  return trIcinde(a, o) ? { a: r6(a), o: r6(o) } : null;
}
// ---- Koordinat kalite kontrolü (dış servis gerektirmez)
function ilAdi(adres) { const p = s(adres).split("/"); return p.length > 1 ? s(p[p.length - 1]).toLocaleUpperCase("tr") : ""; }
function ondalik(v) { const t = s(v); const i = t.indexOf("."); return i < 0 ? 0 : t.length - i - 1; }
function medyan(l) { const x = [...l].sort((a, b) => a - b), m = x.length >> 1; return x.length % 2 ? x[m] : (x[m - 1] + x[m]) / 2; }
export function konumKalite(liste, hamKoord) {
  const iller = new Map();
  for (const st of liste) { const il = ilAdi(st.d); if (!il) continue; if (!iller.has(il)) iller.set(il, []); iller.get(il).push(st); }
  const merkez = new Map(), sayac = { il: 0, kaba: 0, ortak: 0 };
  for (const [il, l] of iller) {
    if (l.length < 5) continue;
    const m = { a: medyan(l.map(x => x.a)), o: medyan(l.map(x => x.o)) };
    const uz = l.map(x => km(x.a, x.o, m.a, m.o)).sort((a, b) => a - b);
    m.esik = Math.max(200, 2.5 * uz[Math.floor(uz.length * 0.9)]); // uzun/büyük illerde (Mersin, Muğla, Konya) yanlış alarm vermesin
    merkez.set(il, m);
    for (const x of l) if (km(x.a, x.o, m.a, m.o) > m.esik) { x.q = "il"; sayac.il++; }
  }
  for (const x of liste) {
    const h = hamKoord && hamKoord.get(x.e);
    if (!x.q && h && Math.min(ondalik(h.enlem), ondalik(h.boylam)) <= 2) { x.q = "kaba"; sayac.kaba++; }
  }
  const nokta = new Map();
  for (const x of liste) { const k = x.a + "," + x.o; if (!nokta.has(k)) nokta.set(k, []); nokta.get(k).push(x); }
  for (const l of nokta.values()) {
    if (l.length < 3 || new Set(l.map(x => s(x.d).toLocaleLowerCase("tr"))).size < 2) continue; // aynı adreste çok istasyon normaldir
    for (const x of l) if (!x.q) { x.q = "ortak"; sayac.ortak++; }
  }
  return { merkez, sayac };
}

export async function konumsuzlariCoz(konumsuz, bugun, secenek = {}) {
  const onbellekYol = secenek.onbellek || ONBELLEK, simdi = secenek.simdi || Date.now();
  let onbellek = {};
  try { if (existsSync(onbellekYol)) onbellek = JSON.parse(readFileSync(onbellekYol, "utf8")); } catch (e) { onbellek = {}; }
  let son = 0, arama = 0, durdu = "";
  const bekle = secenek.bekle || (async () => { const g = 1100 - (Date.now() - son); if (g > 0) await new Promise(z => setTimeout(z, g)); son = Date.now(); });
  const cikti = [], sayac = { adres: 0, mahalle: 0, bulunamadi: 0, aranmadi: 0 };
  for (const x of konumsuz) {
    const anahtar = x.kod + "|" + x.adres;
    let o = onbellek[anahtar];
    const eski = o && o.q === "yok" && (simdi - Date.parse(o.t || 0)) > BULUNAMADI_TEKRAR_GUN * 864e5;
    if ((!o || eski) && !durdu) {
      if (arama >= ARAMA_SINIRI) { durdu = "sınır"; }
      else {
        const sorgular = adresSorgulari(x.adres);
        o = { q: "yok", t: new Date(simdi).toISOString().slice(0, 10) };
        try {
          for (let n = 0; n < sorgular.length; n++) {
            arama++;
            const b = await adresAra(sorgular[n], bekle);
            if (b) { o = { a: b.a, o: b.o, q: n === 0 ? "adres" : "mahalle", t: o.t }; break; }
          }
          onbellek[anahtar] = o;
        } catch (e) { durdu = e.message; o = undefined; }
      }
    }
    if (!o) { sayac.aranmadi++; continue; }
    if (o.q === "yok") { sayac.bulunamadi++; continue; }
    sayac[o.q]++;
    const halka = s(x.hizmet).toLocaleLowerCase("tr").startsWith("halka");
    const st = epdkIstasyon(x.ham, o.a, o.o, bugun, halka, x.hizmet);
    st.z = o.q; // konum yaklaşık: "adres" (sokak düzeyi) veya "mahalle"
    cikti.push(st);
  }
  // kaybolan istasyonların kayıtlarını temizle (dosya şişmesin)
  const gecerli = new Set(konumsuz.map(x => x.kod + "|" + x.adres));
  for (const k of Object.keys(onbellek)) if (!gecerli.has(k)) delete onbellek[k];
  try { mkdirSync(onbellekYol.split("/").slice(0, -1).join("/") || ".", { recursive: true }); writeFileSync(onbellekYol, JSON.stringify(onbellek)); } catch (e) { }
  return { list: cikti, sayac, durdu, arama };
}
export function epdkGetir() { // GET + boş JSON gövde; node fetch GET'te gövdeye izin vermediği için https modülü
  return new Promise((ok, hata) => {
    const govde = "{}";
    const istek = (EPDK_URL.startsWith("http:") ? http : https).request(EPDK_URL, { method: "GET", headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(govde), "User-Agent": UA }, timeout: 180000 }, cevap => {
      const parcalar = []; cevap.on("data", x => parcalar.push(x));
      cevap.on("end", () => {
        if (cevap.statusCode !== 200) return hata(new Error("EPDK " + cevap.statusCode));
        try { ok(JSON.parse(Buffer.concat(parcalar).toString("utf8"))); } catch (e) { hata(new Error("EPDK JSON çözülemedi")); }
      });
    });
    istek.on("timeout", () => istek.destroy(new Error("EPDK zaman aşımı")));
    istek.on("error", hata);
    istek.end(govde);
  });
}
function oncekiEpdk(cikti) { // EPDK erişilemezse dünkü yayındaki EPDK kayıtları kullanılır
  try { if (!existsSync(cikti)) return []; const d = JSON.parse(readFileSync(cikti, "utf8")); return (d.list || []).filter(x => x.e); } catch (e) { return []; }
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
  // konum düzeltmeleri: her cihazın son düzeltmesi; 2+ cihaz 50 m içinde anlaşırsa istasyon taşınır
  const sonKonum = new Map();
  for (const r of raporlar) {
    if (r.tur !== "konum" || typeof r.lat !== "number" || typeof r.lon !== "number") continue;
    const key = r.istasyon_id + "|" + r.c, onceki = sonKonum.get(key);
    if (!onceki || r.id > onceki.id) sonKonum.set(key, r);
  }
  const istasyonaGore = new Map();
  for (const r of sonKonum.values()) { if (!istasyonaGore.has(r.istasyon_id)) istasyonaGore.set(r.istasyon_id, []); istasyonaGore.get(r.istasyon_id).push(r); }
  let tasinan = 0;
  for (const [id, l] of istasyonaGore) {
    const st = mevcut.get(id); if (!st) continue;
    let enIyi = [];
    for (const r of l) { const yakin = l.filter(x => km(x.lat, x.lon, r.lat, r.lon) * 1000 <= 50); if (yakin.length > enIyi.length) enIyi = yakin; }
    if (enIyi.length >= 2) {
      st.a = r6(enIyi.reduce((t, x) => t + x.lat, 0) / enIyi.length); st.o = r6(enIyi.reduce((t, x) => t + x.lon, 0) / enIyi.length);
      st.kd = enIyi.length; delete st.q; delete st.z; tasinan++;
    } else st.kb = l.length; // tek kişi bildirdi: uyarı göster, taşıma
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
  return { eklenen, durumlu, tasinan };
}

// ---- Şirket adlarını birleştir: aynı şirket kaynaklara göre farklı yazılıyor ("Zes", "ZES", "Zorlu Enerji"...).
// Uygulamadaki şirket listesi ve filtresi adı birebir karşılaştırdığı için hepsi tek yazıma çevrilir.
const HUKUKI = new Set(["a.s", "as", "a.s.", "anonim", "sirketi", "ltd", "sti", "limited", "san", "tic", "sanayi", "ticaret", "ve", "inc", "gmbh", "co", "llc", "tr", "turkiye", "turkey"]);
function sirketAnahtar(ad) {
  const n = s(ad).toLocaleLowerCase("tr").replace(/[çğıöşüâîû]/g, ch => ({ "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u" })[ch])
    .replace(/i̇/g, "i").replace(/[(),;]/g, " ");
  return n.split(/\s+/).map(w => w.replace(/\.+$/, "")).filter(w => w && !HUKUKI.has(w)).join(" ");
}
// Bilinen markalar: anahtarın başı bu kelimelerle başlıyorsa marka adına çevrilir
const MARKALAR = [
  [/^(zes|zorlu)\b/, "ZES"],
  [/^(esarj|e-sarj|enerjisa esarj|enerjisa)\b/, "Eşarj"],
  [/^(trugo|togg)\b/, "Trugo"],
  [/^voltrun\b/, "Voltrun"],
  [/^sharz\b/, "Sharz.net"],
  [/^tesla\b/, "Tesla"],
  [/^beefull\b/, "Beefull"],
  [/^otopriz\b/, "Otopriz"]
];
export function sirketleriBirlestir(list) {
  const yazimlar = new Map(); // anahtar -> {yazım: adet}
  for (const x of list) {
    if (!x.p) continue;
    const k = sirketAnahtar(x.p); if (!k) continue;
    if (!yazimlar.has(k)) yazimlar.set(k, new Map());
    const m = yazimlar.get(k); m.set(x.p, (m.get(x.p) || 0) + 1);
  }
  const hedef = new Map();
  for (const [k, m] of yazimlar) {
    const marka = MARKALAR.find(([re]) => re.test(k));
    if (marka) { hedef.set(k, marka[1]); continue; }
    // markası bilinmiyorsa: önce düzgün yazılmış olan ("Toger" > "TOGER"), sonra en çok kullanılan, sonra kısa olan ("Aksa Şarj" > "Aksa Şarj A.Ş.")
    const puan = (y, c) => [y !== y.toLocaleUpperCase("tr") ? 1 : 0, c, -y.length];
    const iyi = (x, y) => { for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i]; return false; };
    let enIyi = "", ep = null;
    for (const [ham, c] of m) {
      const y = ham.replace(/\s*\((tr|türkiye|turkiye|turkey)\)\s*$/i, "").trim() || ham; // OCM'nin "(TR)" ekini at
      const p = puan(y, c); if (!ep || iyi(p, ep)) { enIyi = y; ep = p; }
    }
    hedef.set(k, enIyi);
  }
  let degisen = 0;
  for (const x of list) {
    if (!x.p) continue;
    const yeni = hedef.get(sirketAnahtar(x.p));
    if (yeni && yeni !== x.p) { x.p = yeni; degisen++; }
  }
  const once = [...yazimlar.values()].reduce((t, m) => t + m.size, 0);
  return { degisen, once, sonra: new Set(list.filter(x => x.p).map(x => x.p)).size };
}

// ---- Şirket fiyatları: her gün şirketlerin RESMİ sitelerindeki tarife sayfasından okunur.
// Yönetmelik gereği fiyatlar sitede ilan edilmek zorunda. robots.txt izin vermeyen site okunmaz.
// Okunamazsa son doğru fiyat (kontrol tarihiyle) kullanılmaya devam eder.
const FIYAT_DOSYA = "sarjharitasi/fiyatlar.json";
export const FIYAT_KAYNAK = [ // ad: birleştirilmiş şirket adı (sirketleriBirlestir sonrası) · url: sırayla denenir
  { ad: "ZES", url: ["https://zes.net/tr/fiyatlandirma"] },
  { ad: "Trugo", url: ["https://www.trugo.com.tr/price"] },
  { ad: "Voltrun", url: ["https://www.voltrun.com/tr/tarifeler", "https://voltrun.com/tr/tarifeler"] },
  { ad: "Wat Mobilite", url: ["https://www.watmobilite.com/cozumler/kamusal-alanlar"] },
  { ad: "Beefull", url: ["https://beefull.com/tarifeler/elektrikli-arac-tarifesi/"] },
  { ad: "ASTOR", url: ["https://www.astorsarj.com.tr/", "https://www.astorsarj.com.tr/index.html"] }, // fiyat ana sayfada ("₺ 9,89 / kWh")
  { ad: "En Yakıt", url: ["https://www.enyakit.com.tr/ucretlendirme"] },
  { ad: "Oncharge", url: ["https://www.oncharge.com.tr/fiyatlar"] },
  { ad: "AKSA ŞARJ", url: ["https://www.aksasarj.com.tr/tr/ucretler"] },
  { ad: "Toger", url: ["https://www.toger.co/pricing"] },
  { ad: "otoWATT", url: ["https://www.otowatt.com.tr/tarifelerimiz"] },
  { ad: "Efish", url: ["https://www.efish.com.tr/tr/fiyatlandirma/"] },
  { ad: "Eşarj", url: ["https://www.esarj.com/fiyatlar", "https://esarj.com/tr/fiyatlar"] } // 21.10.2026: site GitHub'dan gelen isteğe 403 veriyor (engel aşılmaz)
];
const FIYAT_MIN = 3, FIYAT_MAX = 40; // TL/kWh: bunun dışı yanlış okuma sayılır

export function htmlMetin(html) {
  return s(html)
    .replace(/<(script|style|noscript)[^>]*>[\s\S]*?<\/\1>/gi, " ")
    .replace(/<br\s*\/?>|<\/(p|div|li|tr|td|th|h\d|span)>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&#160;/g, " ").replace(/&#8378;|&#x20ba;/gi, "₺").replace(/&amp;/g, "&").replace(/&#\d+;/g, " ")
    .replace(/\s+/g, " ").trim();
}
// "AC 9.90TL / kWh", "1 kWh ücreti 12,00 TL - 14,98 TL", "10,99₺", "9,99 - 10,99 ₺/kWh" biçimlerinin hepsini okur
export function fiyatAyikla(metin, kanitIste) {
  const t = s(metin).replace(/\\u20ba/gi, "₺"), sonuc = {}, ilkYer = {}, kanit = {};
  const sayi = x => Math.round(parseFloat(x.replace(",", ".")) * 100) / 100;
  const FIYAT = /(\d{1,2}[.,]\d{1,2})\s*(tl|₺|try)?(?:\s*\/\s*kwh)?(?:\s*(?:[-–—~]|ile|ila)\s*(\d{1,2}[.,]\d{1,2})\s*(tl|₺|try)?)?/gi; // "12,99₺ / kWh - 16,49₺ / kWh" de aralıktır
  const ANAHTAR = /(?:^|[^a-zçğıöşü0-9])(ac|dc)(?=[^a-zçğıöşü]|$)/gi;
  let m;
  while ((m = ANAHTAR.exec(t))) {
    const tur = m[1].toLowerCase();
    // aynı türün sonraki geçişleri (ör. "DC-1 … DC-2 …") sadece ilk fiyata yakınsa (600 karakter) aralığa eklenir;
    // sayfanın çok aşağısındaki kampanya metinleri fiyatı bozmasın
    if (sonuc[tur] && m.index - ilkYer[tur] > 600) continue;
    const bas = m.index + m[0].length, pencere = t.slice(bas, bas + 160);
    // pencerede öbür tür geçiyorsa onun öncesine kadar bak (AC'nin fiyatı DC'ninkiyle karışmasın)
    const ote = pencere.search(new RegExp("(^|[^a-zçğıöşü0-9])" + (tur === "ac" ? "dc" : "ac") + "([^a-zçğıöşü]|$)", "i"));
    const alan = ote >= 0 ? pencere.slice(0, ote) : pencere; // "DC/AC Hızlı…" gibi bitişik yazımda (ote = 0) bu geçiş atlanır
    FIYAT.lastIndex = 0; let f;
    while ((f = FIYAT.exec(alan))) {
      const sonra = alan.slice(f.index + f[0].length, f.index + f[0].length + 14).toLowerCase();
      const once = alan.slice(Math.max(0, f.index - 40), f.index).toLowerCase();
      const birimli = !!(f[2] || f[4] || /kwh/i.test(f[0])); // yanında TL/₺/kWh olan sayı yüzde ya da güç olamaz ("9,99 TL/kWh %20 indirim")
      if (/^\s*kw(?!h)/.test(sonra) || /^\s*\/?\s*(dk|dak|saat|sa\b)/.test(sonra) || (!birimli && /^\s*%/.test(sonra))) continue; // güç (kW), dakika ücreti, yüzde
      const paraVar = f[2] || f[4] || /kwh/i.test(f[0]) || /^\s*\/?\s*kwh/.test(sonra) || /kwh/.test(once) || /(₺|\btl)\s*$/.test(once); // "₺ 9,89 / kWh": işaret sayının önünde
      if (!paraVar) continue;
      const a = sayi(f[1]), b = f[3] ? sayi(f[3]) : a;
      if (!(a >= FIYAT_MIN && b <= FIYAT_MAX && b >= a)) continue;
      if (!sonuc[tur]) { sonuc[tur] = [a, b]; ilkYer[tur] = m.index; kanit[tur] = t.slice(m.index, bas + f.index + f[0].length + 12).trim(); }
      else { sonuc[tur] = [Math.min(sonuc[tur][0], a), Math.max(sonuc[tur][1], b)]; kanit[tur] += " … " + t.slice(m.index, bas + f.index + f[0].length + 12).trim(); }
      break;
    }
  }
  if (kanitIste) sonuc.kanit = kanit;
  return sonuc;
}
// robots.txt kuralı: * herhangi bir dizi, $ satır sonu. En uzun eşleşen kural kazanır; eşitlikte Allow.
function robotsKurali(desen) {
  const kacir = desen.replace(/[.+?^{}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp("^" + (kacir.endsWith("\\$") ? kacir.slice(0, -2) + "$" : kacir.replace(/\$$/, "$")));
}
export function robotsDegerlendir(metin, yol, ajan = UA.toLowerCase()) { // ajan: bizim User-Agent (TurkiyeSarjHaritasi-veri/…)
  const gruplar = []; let g = null, sonAjan = false;
  for (const satir of s(metin).split(/\r?\n/)) {
    const temiz = satir.split("#")[0]; const i = temiz.indexOf(":"); if (i < 0) continue;
    const k = temiz.slice(0, i).trim().toLowerCase(), v = temiz.slice(i + 1).trim();
    if (k === "user-agent") { if (!sonAjan) { g = { ajan: [], kural: [] }; gruplar.push(g); } g.ajan.push(v.toLowerCase()); sonAjan = true; }
    else if (g && (k === "allow" || k === "disallow")) { sonAjan = false; if (v) g.kural.push([k === "allow", v]); }
    else sonAjan = false;
  }
  const ozel = gruplar.filter(x => x.ajan.some(a => a !== "*" && ajan.includes(a)));
  const kurallar = (ozel.length ? ozel : gruplar.filter(x => x.ajan.includes("*"))).flatMap(x => x.kural);
  let enIyi = null;
  for (const [izin, desen] of kurallar) {
    if (!robotsKurali(desen).test(yol)) continue;
    if (!enIyi || desen.length > enIyi[1].length || (desen.length === enIyi[1].length && izin)) enIyi = [izin, desen];
  }
  return !enIyi || enIyi[0];
}
async function robotsIzin(url) {
  try {
    const u = new URL(url);
    const r = await fetch(u.origin + "/robots.txt", { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(20000) });
    if (!r.ok) return true; // robots.txt yoksa izin var sayılır
    return robotsDegerlendir(await r.text(), u.pathname + u.search);
  } catch (e) { return true; }
}
async function sayfaGetir(url) {
  // 429 (çok fazla istek) / 503 gelirse sitenin istediği kadar (en çok 60 sn) bekleyip 2 kez daha dener
  for (let n = 0; ; n++) {
    const r = await fetch(url, { headers: { "User-Agent": UA, "Accept": "text/html", "Accept-Language": "tr" }, signal: AbortSignal.timeout(30000) });
    if (r.ok) return await r.text();
    if ((r.status === 429 || r.status === 503) && n < 2) {
      const bekle = Math.min(60, Math.max(15, parseInt(r.headers.get("retry-after"), 10) || 20 * (n + 1)));
      await new Promise(z => setTimeout(z, bekle * 1000)); continue;
    }
    throw new Error("HTTP " + r.status);
  }
}
// Fiyatları oku; önceki dosyayla birleştir (okunamayan şirketin son doğru fiyatı kalır)
export async function fiyatlariGuncelle(secenek = {}) {
  const yol = secenek.dosya || FIYAT_DOSYA, getir = secenek.getir || sayfaGetir, izin = secenek.robots || robotsIzin;
  const bugun = (secenek.bugun || new Date().toISOString().slice(0, 10));
  let eski = {}; try { if (existsSync(yol)) eski = JSON.parse(readFileSync(yol, "utf8")).sirketler || {}; } catch (e) { eski = {}; }
  const sirketler = {}, kayit = [], tani = {};
  for (const k of secenek.kaynak || FIYAT_KAYNAK) {
    const onceki = eski[k.ad] || null; let bulundu = null, hata = "", iz = [];
    for (const url of k.url) {
      try {
        if (!(await izin(url))) { hata = "robots.txt izin vermiyor"; iz.push(url + ": robots"); continue; }
        const html = await getir(url);
        const metin = htmlMetin(html);
        let f = fiyatAyikla(metin, true);
        if (!f.ac && !f.dc) f = fiyatAyikla(s(html).replace(/<[^>]+>/g, " "), true); // fiyat sayfa içi veride olabilir
        if (f.ac || f.dc) { bulundu = { ...f, kaynak: url }; break; }
        hata = "sayfada fiyat bulunamadı";
        // teşhis: sayfa ne kadar büyük, metinde kWh / TL geçiyor mu, kWh'in çevresi ne
        const i = metin.search(/kwh|₺|\btl\b/i);
        iz.push(url + ": html " + s(html).length + " bayt, metin " + metin.length + " | " + (i >= 0 ? metin.slice(Math.max(0, i - 120), i + 120) : metin.slice(0, 240)));
      } catch (e) { hata = (e && e.cause && e.cause.code) ? e.message + " (" + e.cause.code + ")" : e.message; iz.push(url + ": " + hata); }
    }
    if (bulundu) {
      const ayni = onceki && JSON.stringify([onceki.ac, onceki.dc]) === JSON.stringify([bulundu.ac, bulundu.dc]);
      sirketler[k.ad] = { ac: bulundu.ac || null, dc: bulundu.dc || null, kaynak: bulundu.kaynak, kontrol: bugun, degisim: ayni ? (onceki.degisim || bugun) : bugun,
        okunan: Object.values(bulundu.kanit || {}).map(x => x.slice(0, 200)) }; // sayfada fiyatın göründüğü metin (kontrol için)
      kayit.push(k.ad + " ✓ AC " + (bulundu.ac ? bulundu.ac.join("-") : "—") + " / DC " + (bulundu.dc ? bulundu.dc.join("-") : "—") + (ayni ? "" : onceki ? " (DEĞİŞTİ)" : " (ilk kayıt)"));
    } else if (onceki) { sirketler[k.ad] = { ...onceki, hata }; kayit.push(k.ad + " ✗ " + hata + " → son fiyat korunuyor (" + onceki.kontrol + ")"); }
    else kayit.push(k.ad + " ✗ " + hata);
    if (!bulundu) tani[k.ad] = iz;
  }
  const veri = { guncelleme: Date.now(), not: "Şirketlerin resmi sitelerinden otomatik okunur; KDV dahil liste fiyatı, kampanyalar hariç.", sirketler, okunamayan: tani };
  try { mkdirSync(yol.split("/").slice(0, -1).join("/") || ".", { recursive: true }); writeFileSync(yol, JSON.stringify(veri, null, 1)); } catch (e) { }
  return { veri, kayit };
}
const tl = x => x.toFixed(2).replace(".", ",");
const aralik = f => f[0] === f[1] ? tl(f[0]) : tl(f[0]) + "–" + tl(f[1]);
// İstasyonların "u" alanına şirket tarifesini yazar (eski uygulama sürümleri de "Ücret:" satırında gösterir)
export function fiyatlariUygula(list, sirketler) {
  let n = 0;
  const anahtarla = new Map(Object.entries(sirketler).map(([ad, f]) => [sirketAnahtar(ad), f])); // "ASTOR" = "Astor"
  for (const x of list) {
    const f = x.p && (sirketler[x.p] || anahtarla.get(sirketAnahtar(x.p))); if (!f || (!f.ac && !f.dc)) continue;
    const dcVar = (x.c || []).some(c => c[2] === 1 || c[1] >= 50), acVar = (x.c || []).some(c => c[2] === 0 || (c[2] !== 1 && c[1] > 0 && c[1] < 50));
    const parca = [];
    if (f.ac && (acVar || !dcVar)) parca.push("AC " + aralik(f.ac) + " TL");
    if (f.dc && (dcVar || !acVar)) parca.push("DC " + aralik(f.dc) + " TL");
    if (!parca.length) continue;
    const [y, a, g] = f.kontrol.split("-");
    x.u = parca.join(" · ") + " /kWh · " + x.p + " tarifesi, " + g + "." + a + "." + y;
    n++;
  }
  return n;
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

export async function calistir(cikti = "sarjharitasi/stations.json", secenek = {}) {
  if (!OCM_KEY) throw new Error("OCM_KEY tanımlı değil (GitHub Secrets)");
  let epdk = [], epdkDurum = "", konumRapor = null, konumSonuc = null;
  try {
    const rapor = { sebep: {}, duzeltilen: {}, konumsuz: [], hamKoord: new Map(), hamByKod: new Map() };
    const hamFeed = await (secenek.epdkGetir || epdkGetir)();
    for (const r of (Array.isArray(hamFeed) ? hamFeed : (hamFeed && hamFeed.data) || [])) {
      if (r && s(r.sarjIstasyonuNo)) { rapor.hamKoord.set(s(r.sarjIstasyonuNo), { enlem: r.enlem, boylam: r.boylam }); rapor.hamByKod.set(s(r.sarjIstasyonuNo), r); }
    }
    epdk = epdkDonustur(hamFeed, undefined, rapor);
    konumRapor = rapor;
    const say = {}; for (const x of epdk) { const k = x.k ? x.h : "Halka Açık"; say[k] = (say[k] || 0) + 1; }
    console.log("EPDK hizmet şekilleri: " + Object.entries(say).sort((a, b) => b[1] - a[1]).map(([k, n]) => k + "=" + n).join(", "));
    if (epdk.length < EPDK_EN_AZ) throw new Error("EPDK verisi şüpheli derecede az: " + epdk.length);
    epdkDurum = "güncel";
  } catch (e) {
    epdk = oncekiEpdk(cikti);
    epdkDurum = (epdk.length ? "dünkü veri (" : "yok (") + e.message + ")";
  }
  let kaliteSonuc = null;
  if (epdk.length && konumRapor) {
    const kal = konumKalite(epdk, konumRapor.hamKoord);
    const supheli = epdk.filter(x => x.q);
    const aranacak = supheli.map(x => ({ kod: x.e, adres: x.d, hizmet: x.k ? x.h : "Halka Açık", ham: konumRapor.hamByKod.get(x.e) })).filter(x => x.ham);
    let duzelen = 0, dogrulanan = 0;
    if (aranacak.length) {
      const sonuc = await konumsuzlariCoz(aranacak, new Date().toISOString().slice(0, 10), Object.assign({ onbellek: "sarjharitasi/konum-kalite-onbellek.json" }, secenek.konum || {}));
      const bulunan = new Map(sonuc.list.map(x => [x.e, x]));
      for (const x of supheli) {
        const b = bulunan.get(x.e); if (!b) continue;
        const m = kal.merkez.get(ilAdi(x.d));
        if (x.q === "il" && (!m || km(b.a, b.o, m.a, m.o) > m.esik)) continue; // adres sonucu da ilin dışında: ne doğrula ne taşı
        if (b.z === "adres" && km(b.a, b.o, x.a, x.o) <= 5) { x.dq = x.q; delete x.q; dogrulanan++; continue; } // adres, koordinatı doğruladı
        if (b.z === "mahalle" && x.q === "ortak") continue;                    // mahalle merkezi, ortak noktadan iyi değil
        x.eskiKonum = [x.a, x.o]; x.a = b.a; x.o = b.o; x.z = b.z; x.dq = x.q; delete x.q; duzelen++;
      }
      kaliteSonuc = { sayac: kal.sayac, duzelen, dogrulanan, kalan: epdk.filter(x => x.q).length, durdu: sonuc.durdu };
    } else kaliteSonuc = { sayac: kal.sayac, duzelen: 0, kalan: 0 };
    for (const x of epdk) delete x.eskiKonum;
    console.log(`Konum kalitesi: il dışı=${kal.sayac.il}, kaba=${kal.sayac.kaba}, ortak nokta=${kal.sayac.ortak} | adresle düzeltilen=${kaliteSonuc.duzelen}, adresle doğrulanan=${kaliteSonuc.dogrulanan || 0}, şüpheli kalan=${kaliteSonuc.kalan}`);
  }
  if (konumRapor) {
    const kr = konumRapor;
    console.log("EPDK konum sorunları: " + (Object.entries(kr.sebep).map(([k, n]) => k + "=" + n).join(", ") || "yok") +
      " | düzeltilen: " + (Object.entries(kr.duzeltilen).map(([k, n]) => k + "=" + n).join(", ") || "yok"));
    if (kr.konumsuz.length) {
      konumSonuc = await konumsuzlariCoz(kr.konumsuz, new Date().toISOString().slice(0, 10), secenek.konum || {});
      const sc = konumSonuc.sayac;
      console.log(`Adresten konum: sokak=${sc.adres}, mahalle=${sc.mahalle}, bulunamadı=${sc.bulunamadi}, sırada=${sc.aranmadi}` + (konumSonuc.durdu ? " | durdu: " + konumSonuc.durdu : ""));
      epdk = epdk.concat(konumSonuc.list);
    }
  }
  const ocmHam = await getir(OCM_URL);
  const ocm = ocmDonustur(ocmHam);
  let osm = [], osmHata = "";
  for (const u of OVERPASS) {
    try {
      const j = await getir(u, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "data=" + encodeURIComponent(SORGU) }, 2);
      osm = osmDonustur(j.elements); osmHata = ""; break;
    } catch (e) { osmHata = e.message; }
  }
  if (ocm.length < 500 && epdk.length < EPDK_EN_AZ) throw new Error("OCM verisi şüpheli derecede az: " + ocm.length + " (eski dosya korunuyor)");
  // Öncelik: EPDK > OCM > OSM. Daha alttaki kaynak, üsttekinde 150 m içinde karşılığı yoksa eklenir.
  const e1 = birlestir(epdk, ocm), ocmEklenen = e1.eklenen;
  const b = birlestir(e1.list, osm);
  let kul = { eklenen: 0, durumlu: 0 }, kulHata = "";
  try { kul = kullaniciBirlestir(b.list, await raporlariGetir()); } catch (e) { kulHata = e.message; }
  const sirket = sirketleriBirlestir(b.list);
  console.log(`Şirket adları: ${sirket.once} farklı yazım -> ${sirket.sonra} şirket (${sirket.degisen} istasyonun adı düzeltildi)`);
  let fiyatOzet = null;
  try {
    const fy = await fiyatlariGuncelle(secenek.fiyat || {});
    const n = fiyatlariUygula(b.list, fy.veri.sirketler);
    console.log("Fiyatlar:\n  " + fy.kayit.join("\n  ") + "\n  → " + n + " istasyona tarife yazıldı");
    fiyatOzet = { sirket: Object.keys(fy.veri.sirketler).length, istasyon: n };
  } catch (e) { console.log("Fiyat adımı atlandı: " + e.message); }
  const veri = {
    ts: Date.now(), count: b.list.length, sources: { epdk: epdk.length, epdkKisitli: epdk.filter(x => x.k).length, epdkDurum,
      kalite: kaliteSonuc,
      konum: konumRapor ? { sebep: konumRapor.sebep, duzeltilen: konumRapor.duzeltilen, adrestenBulunan: konumSonuc ? konumSonuc.sayac : null } : null, ocm: ocm.length, ocmEklenen, osm: osm.length, osmEklenen: b.eklenen, osmHata, kullanici: kul.eklenen, durumBildirimli: kul.durumlu, kulHata, fiyat: fiyatOzet },
    license: "EPDK Serbest Erişim Platformu; Open Charge Map (CC BY 4.0); © OpenStreetMap katkıcıları (ODbL). Birleşik veri ODbL kapsamında açıktır.",
    list: b.list
  };
  mkdirSync(cikti.split("/").slice(0, -1).join("/") || ".", { recursive: true });
  writeFileSync(cikti, JSON.stringify(veri));
  console.log(`Tamam: EPDK ${epdk.length} [${epdkDurum}], OCM ${ocm.length} (yeni ${ocmEklenen}), OSM ${osm.length} (yeni ${b.eklenen}), kullanıcı ${kul.eklenen}, durum bildirimli ${kul.durumlu}, toplam ${b.list.length}${osmHata ? " | OSM hatası: " + osmHata : ""}${kulHata ? " | Bildirim hatası: " + kulHata : ""}`);
  return veri;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  calistir().catch(e => { console.error("HATA:", e.message); process.exit(1); });
}
