#!/usr/bin/env python3
"""
KorpeSoft Canlı TV — Diziler listesini her gün HAZIRLAR (GitHub Actions).

Neden: uygulama dizileri telefonda tek tek YouTube'a sorunca
  - içi boş (sadece fragman/klip) diziler ve sezonlar listede görünüyordu,
  - her kullanıcı YouTube kotası harcıyordu.
Şimdi bu betik günde bir kez bütün kanalları tarar, SADECE tam bölümü olan dizi ve sezonları yazar:
  canlitv/hazir/index.json          → kanallar, diziler, sezonlar (küçük dosya)
  canlitv/hazir/<listeId>.json      → o sezonun bölümleri (uygulama sezona basınca indirir)
Uygulama artık YouTube API'sine hiç sormuyor; boş dizi/sezon listeye giremiyor.

Kaynak: canlitv/diziler.json (kanallar, "youtube" hesapları, "gizle", elle eklenen diziler, apiKey).
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "canlitv", "diziler.json")
OUT = os.path.join(ROOT, "canlitv", "hazir")
API = "https://www.googleapis.com/youtube/v3/"

cfg = json.load(open(SRC, encoding="utf-8"))
KEY = os.environ.get("YT_KEY") or cfg.get("apiKey", "")
if not KEY:
    sys.exit("API anahtarı yok")

units = 0


class KotaDoldu(Exception):
    pass


# Önbellek: oynatma listesinin video sayısı değişmediyse bölümleri yeniden sorulmaz (günlük kota çok az harcanır)
CACHE_F = os.path.join(ROOT, "scripts", "dizi_onbellek.json")
KURAL = "v1"   # ayıklama kuralları değişirse artır → önbellek yenilenir
try:
    CACHE = json.load(open(CACHE_F, encoding="utf-8"))
    if CACHE.get("_kural") != KURAL:
        CACHE = {"_kural": KURAL}
except Exception:
    CACHE = {"_kural": KURAL}


def cache_kaydet():
    json.dump(CACHE, open(CACHE_F, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


def get(path, **params):
    global units
    params["key"] = KEY
    url = API + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "korpesoft-dizi-hazirla"})
            with urllib.request.urlopen(req, timeout=30) as r:
                units += 1
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code in (400, 403, 404):
                print(f"  ! {path} {e.code} {body[:200]}", flush=True)
                if "quota" in body.lower() or "rateLimitExceeded" in body:   # kota: yarım liste yazılmasın
                    raise KotaDoldu()
                return None
            time.sleep(2 + attempt * 3)
        except Exception as e:
            time.sleep(2 + attempt * 3)
    return None


# ---------- uygulamadaki kurallarla aynı ----------
def tr_lower(s):
    return (s or "").replace("I", "ı").replace("İ", "i").lower()


def key(s):
    return "".join(c for c in tr_lower(s) if c.isalnum())


I = re.IGNORECASE | re.UNICODE
SEZON = re.compile(r"(\d{1,2})\s*\.?\s*sezon|sezon\s*(\d{1,2})", I)
BOLUM = re.compile(r"(\d{1,4})\s*\.?\s*b[oö]l[uü]m", I)
KISIM = re.compile(r"(\d{1,2})\s*\.?\s*k[ıi]s[ıi]m", I)
LISTE_ATLA = re.compile(r"(kesit|en çok izlenen|özel klip|yeni sezon|yakında|fragman|ön ?izleme|onizleme|klip|kamera arkas|kamera önü|"
                        r"tanıtım|shorts|sahneler|sahnesi|dizi müzik|şarkıları|jenerik|canlı yayın|röportaj|teaser|trailer|best of|"
                        r"behind the scenes|unutulmaz an)", I)
VIDEO_ATLA = re.compile(r"(fragman|ön ?izleme|onizleme|tanıtım|teaser|trailer|kamera arkas|kamera önü|#shorts|\bshorts\b|sezon finali özeti)", I)
TEMIZLE = [r"\b4k\b", r"\d{1,2}\s*\.?\s*sezon", r"sezon\s*\d{1,2}", r"t[uü]m\s*b[oö]l[uü]mleri?", r"b[oö]l[uü]mleri?",
           r"full\s*b[oö]l[uü]m(ler)?", r"\bfull\b", r"\bhd\b", r"\(.*?\)", r"\[.*?\]"]
MIN_SURE, MIN_KISIM, MIN_SPOR = 20 * 60, 8 * 60, 61

# --- SADECE DİZİ: yarışma, yemek, sohbet, gezi, haber, derleme listeleri atlanır ---
DIZI_DEGIL = re.compile(
    r"(öne çıkan|one cikan|kolaj|\bkısa\b|arşiv|dizileri|shorts|özel|önemli an|yarışma|yarisma|konser|bağış|"
    r"mutfa|tarif|lezzet|yemek|sofra|sahur|iftar|ramazan|bayram|kur['’]?an|kuran|dua|vaaz|hadis|ilmihal|"
    r"gezi|gezme|tatil|moda|stil|haber|bülten|sorular|soru|sohbet|söyleşi|talk|show kuşu|skeç|güldür|komedi dükkanı|"
    r"futbol|maç|kupa|lig|spor|belgesel|çizgi film|klip|tv8\b|program|magazin|evlilik|gelin|yaparsın|pasaport|"
    r"milyon|var mısın|kim gitsin|lingo|sahne|canlı|live|podcast|vlog|best|en güzel)", I)
HOST = re.compile(r"(\bile\b|\b\w+['’](la|le|yla|yle)\b)", I)        # "Ömür Akkor ile …", "Zahide Yetiş'le …" → sunuculu program
YIL = re.compile(r"\b20\d\d\b")                                          # "… 2026" → yıllık program sezonu
SPOR_EVET = re.compile(r"(özet|ozet|goller|\bgol\b|full maç|geniş özet|maçın tamamı|highlights|goals)", I)
SPOR_HAYIR = re.compile(r"(shorts|kısa|önemli an|röportaj|basın toplantısı|transfer|tanıyalım|teknik|taktik|antrenman)", I)


TR_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")


def fold(s):
    """Karşılaştırma için: Türkçe harfler sadeleşir, sadece harf/rakam kalır. "Kuruluş Osman" → "kurulusosman" """
    return "".join(c for c in tr_lower(s).translate(TR_ASCII) if c.isalnum())


ARAMA_HAKKI = [45]          # tek çalışmada en fazla 45 kanal araması (her biri 100 kota birimi); sonuçlar 30 gün saklanır
ARAMA_GECERLI = 30 * 86400


def bas_harfler(ad):
    return "".join(w[0] for w in re.findall(r"[^\W\d_]+", tr_lower(ad).translate(TR_ASCII)) if w)


def resmi_kanal_bul(ad, kendi):
    """Dizinin kendi resmî YouTube kanalını arar (ör. "Eşkıya Dünyaya Hükümdar Olmaz" → EDHO kanalı).
    Kanal adı dizi adıyla (ya da baş harfleriyle) eşleşmezse kabul edilmez. Sonuç 30 gün önbellekte."""
    hedef = fold(ad)
    ck = "kanal:" + hedef
    c = CACHE.get(ck)
    if c and time.time() - c.get("t", 0) < ARAMA_GECERLI and (c.get("id") or c.get("v") == 2):
        return c.get("id")   # eski "bulunamadı" kayıtları (v2 öncesi) @hesap tahminiyle bir kez daha denenir
    bh = bas_harfler(ad)

    def uygun(t):
        return t == hedef or (hedef in t and len(t) <= len(hedef) + 12) or (len(bh) >= 3 and (t == bh or t.startswith(bh) and len(t) <= len(bh) + 6))

    # 1) Ucuz yol: tahmini @hesap adları (her deneme 1 kota birimi; arama 100 birim)
    tahminler = [hedef, hedef + "dizi", hedef + "atv", hedef + "kanald", hedef + "showtv", hedef + "startv", hedef + "nowtv", hedef + "trt", "dizi" + hedef]
    if len(bh) >= 3:
        tahminler += [bh, bh + "atv", bh + "dizi"]
    for h in tahminler[:12]:
        if len(h) > 30:
            continue
        r = get("channels", part="snippet", forHandle="@" + h)
        items = (r or {}).get("items") or []
        if items:
            t = fold(items[0].get("snippet", {}).get("title", ""))
            if t and t not in kendi and uygun(t):
                CACHE[ck] = {"id": items[0]["id"], "t": int(time.time())}
                return items[0]["id"]
    # 2) Bulunamadıysa YouTube araması (pahalı, günlük sınırlı)
    if ARAMA_HAKKI[0] <= 0:
        return None
    ARAMA_HAKKI[0] -= 1
    r = get("search", part="snippet", type="channel", q=ad + " dizi", maxResults=5, regionCode="TR")
    bulunan = None
    for it in (r or {}).get("items", []):
        sn = it.get("snippet", {})
        cid = (it.get("id") or {}).get("channelId") or sn.get("channelId")
        t = fold(sn.get("title", "") or sn.get("channelTitle", ""))
        if not cid or not t or t in kendi:
            continue
        # "Eşkıya Dünyaya Hükümdar Olmaz" ↔ "eskiyadunyayahukumdarolmaz" / "edho" / "edhoatv"
        if uygun(t):
            bulunan = cid
            break
    CACHE[ck] = {"id": bulunan, "t": int(time.time()), "v": 2}
    return bulunan


HANDLE_RX = re.compile(r"@([A-Za-z0-9._-]{3,})")
_kanal_listeleri = {}


def diziyi_tamamla(d, kanal_kaynaklari, gizle, sezon_yaz):
    """
    Eksik sezon: Kanallar çoğu dizinin eski sezonlarını dizinin KENDİ resmî YouTube hesabına koyuyor
    (ör. bölüm başlıklarında "@KurulusOsman"). Bölüm başlıklarındaki @hesap dizi adına benziyorsa o hesabın
    oynatma listeleri de taranır, aynı diziye ait sezonlar eklenir. Hesap adı dizi adıyla eşleşmezse dokunulmaz.
    """
    hedef = fold(d["ad"])
    if len(hedef) < 4 or not d.get("sezonlar"):
        return
    kendi = {fold(x.lstrip("@").replace("user:", "")) for x in kanal_kaynaklari}
    handles = set()
    for z in d["sezonlar"]:
        try:
            eps = json.load(open(os.path.join(OUT, z["id"] + ".json"), encoding="utf-8"))
        except Exception:
            continue
        for e in eps[:40]:
            for h in HANDLE_RX.findall(e.get("t", "")):
                fh = fold(h)
                if fh in kendi:
                    continue
                if hedef in fh or (len(fh) >= 6 and fh in hedef):   # @KurulusOsman ↔ "Kuruluş Osman"
                    handles.add(h)
    kaynaklar = ["@" + h for h in sorted(handles)[:2]]
    if not kaynaklar:
        cid = resmi_kanal_bul(d["ad"], kendi)   # başlıkta @hesap yoksa: YouTube'da dizinin kendi resmî kanalı aranır
        if cid:
            kaynaklar = [cid]
            handles.add(cid)
    if not kaynaklar:
        return
    var = {z["id"] for z in d["sezonlar"]}
    eklenen = 0
    for h in kaynaklar:
        if h not in _kanal_listeleri:
            cid = kanal_id(h)
            _kanal_listeleri[h] = listeler(cid, 4) if cid else []
        for l in _kanal_listeleri[h]:
            if l["id"] in var or l["adet"] < 3 or LISTE_ATLA.search(l["baslik"]):
                continue
            ad_k = fold(dizi_adi(l["baslik"]))
            if not (ad_k == hedef or (hedef in fold(l["baslik"]) and len(ad_k) <= len(hedef) + 4)):
                continue
            if key(l["baslik"]) in gizle:
                continue
            eps = bolumler(l["id"], False, 10, l["adet"])
            if not eps or sum(1 for e in eps if e["n"] >= 0) < max(2, 0.6 * len(eps)):
                continue
            n = num(SEZON, l["baslik"])
            sezon_yaz(l["id"], eps)
            d["sezonlar"].append(dict(ad=f"{n}. Sezon" if n > 0 else "Bölümler", id=l["id"], adet=len(eps), _n=n, _ilk=min([e["n"] for e in eps if e["n"] >= 0] or [0])))
            var.add(l["id"])
            eklenen += 1
    if not eklenen:
        return
    # Sezon sırası: başlıktaki sezon numarası, yoksa ilk bölüm numarası. Aynı bölümleri içeren tekrar listeler elenir.
    for z in d["sezonlar"]:
        if "_n" not in z:
            z["_n"] = num(SEZON, z["ad"])
            try:
                eps = json.load(open(os.path.join(OUT, z["id"] + ".json"), encoding="utf-8"))
                z["_ilk"] = min([e["n"] for e in eps if e["n"] >= 0] or [0])
            except Exception:
                z["_ilk"] = 0
    d["sezonlar"].sort(key=lambda z: (z["_n"] if z["_n"] > 0 else 999, z["_ilk"]))
    numarasiz = [z for z in d["sezonlar"] if z["_n"] <= 0]
    for i, z in enumerate(numarasiz):
        z["ad"] = "Bölümler" if len(numarasiz) == 1 else f"Bölümler {i + 1}"
    for z in d["sezonlar"]:
        z.pop("_n", None); z.pop("_ilk", None)
    print(f"  + {d['ad']}: dizinin kendi hesabından {eklenen} liste eklendi ({', '.join(sorted(str(x) for x in handles))})", flush=True)


def sezonlari_duzenle(d):
    """Aynı bölümleri içeren tekrar listeler silinir; numarasız tek liste numaralı sezonlardan sonra geliyorsa "N+1. Sezon" olur."""
    ss = d.get("sezonlar") or []
    if len(ss) < 2:
        return
    kume, nos = {}, {}
    for z in ss:
        try:
            eps = json.load(open(os.path.join(OUT, z["id"] + ".json"), encoding="utf-8"))
        except Exception:
            eps = []
        kume[z["id"]] = {e["i"] for e in eps}
        nos[z["id"]] = {(e["n"], max(e.get("k", -1), 0)) for e in eps if e["n"] >= 0}
    kalan = []
    for z in sorted(ss, key=lambda z: -len(kume[z["id"]])):        # büyük liste önce, küçük tekrarlar elenir
        a, an = kume[z["id"]], nos[z["id"]]
        if a and any(len(a & kume[y["id"]]) >= 0.8 * len(a) for y in kalan):
            continue
        # Numarasız liste, daha büyük bir listedeki bölüm numaralarının tekrarıysa (4K / "yeniden düzenlendi" tekrarları) elenir.
        # Numaralı sezonlar ("2. Sezon") bu kuralla silinmez: her sezon 1. bölümden başlayabilir.
        if an and num(SEZON, z["ad"]) <= 0 and any(len(an & nos[y["id"]]) >= 0.8 * len(an) for y in kalan):
            continue
        kalan.append(z)
    sira = {z["id"]: i for i, z in enumerate(ss)}
    kalan.sort(key=lambda z: sira[z["id"]])
    numarali = [num(SEZON, z["ad"]) for z in kalan if num(SEZON, z["ad"]) > 0]
    numarasiz = [z for z in kalan if num(SEZON, z["ad"]) <= 0]
    # Not: numarasız liste otomatik "N+1. Sezon" yapılmaz — bazen yeni sezon, bazen eski sezonun 4K tekrarı oluyor.
    if len(numarasiz) == 1:
        numarasiz[0]["ad"] = "Tüm Bölümler" if len(kalan) == 1 and len(kume[numarasiz[0]["id"]]) >= 60 else "Bölümler"
    else:
        for i, z in enumerate(numarasiz):
            z["ad"] = f"Bölümler {i + 1}"
    d["sezonlar"] = kalan


def dizi_mi(baslik):
    return not (DIZI_DEGIL.search(baslik) or HOST.search(baslik) or YIL.search(baslik))


def dizi_adi(t):
    s = t or ""
    for r in TEMIZLE:
        s = re.sub(r, " ", s, flags=I)
    s = re.sub(r"[|•·–—:_/#-]+", " ", s)
    s = re.sub(r"\s+I\s+|\s+I$", " ", s)                                         # "Taşacak Bu Deniz I" ayıracı
    s = re.sub(r"\b(trt ?1|atv|show ?tv|star ?tv|now ?tv|tv ?8)\b", " ", s, flags=I)    # "Mahrem TRT 1" → "Mahrem"
    s = re.sub(r"^nostal[jJ]i̇? ?seri̇?si̇?\s*", "", s, flags=I)                       # "Nostalji Serisi Bay Yanlış" → "Bay Yanlış"
    s = re.sub(r"\s+", " ", s).strip()
    # "Aşk Yeniden Tam" (Tam Bölüm) → "Aşk Yeniden"; "YENİDEN Göç Zamanı" / "Babalar ve Evlatlar Yeniden" → aynı diziyle birleşsin
    s = re.sub(r"\s+tam(\s+b[oö]l[uü]m)?$", "", s, flags=I)
    s = re.sub(r"^(YEN[İI]DEN|Yeniden)\s+", "", s)
    s = re.sub(r"\s+(YEN[İI]DEN|Yeniden)$", "", s) if not re.search(r"\başk\s+yeniden$", s, I) else s
    s = re.sub(r"\s+(dizisi|Dizisi|DİZİSİ)$", "", s)
    s = re.sub(r"\b(\w+)( \1\b)+", r"\1", s)                                         # "ve ve" → "ve"
    return s.strip()


def num(rx, t):
    last = -1
    for m in rx.finditer(t or ""):
        g = [x for x in m.groups() if x]
        if g:
            last = int(g[0])
    return last


def saniye(iso):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def kisalt(d):
    out = []
    for line in (d or "").split("\n"):
        t = line.strip()
        if not t or "http" in t or t.startswith("#") or t.startswith("@"):
            continue
        out.append(t)
        if len(" ".join(out)) > 220:
            break
    s = " ".join(out)
    if len(s) <= 220:
        return s
    cut = max(s.rfind(". ", 0, 220), s.rfind("! ", 0, 220), s.rfind("? ", 0, 220))
    return s[:cut + 1] if cut > 80 else s[:217].strip() + "…"


def thumb(sn):
    th = sn.get("thumbnails") or {}
    for q in ("maxres", "standard", "high", "medium", "default"):
        if th.get(q, {}).get("url"):
            return th[q]["url"]
    return ""


# ---------- YouTube ----------
def kanal_id(src):
    m = re.search(r"(UC[A-Za-z0-9_-]{22})", src)
    if m:
        return m.group(1)
    h = re.search(r"@([A-Za-z0-9._-]+)", src)
    u = re.search(r"(?:user/|user:)([A-Za-z0-9._-]+)", src)
    p = {"forHandle": "@" + h.group(1)} if h else {"forUsername": u.group(1)} if u else {"forHandle": "@" + src.split("/")[-1]}
    r = get("channels", part="id", **p)
    items = (r or {}).get("items") or []
    return items[0]["id"] if items else None


def listeler(cid, max_pages):
    out, page = [], None
    for _ in range(max_pages):
        p = dict(part="snippet,contentDetails", channelId=cid, maxResults=50)
        if page:
            p["pageToken"] = page
        r = get("playlists", **p)
        if not r:
            break
        for it in r.get("items", []):
            sn = it.get("snippet", {})
            out.append(dict(id=it["id"], baslik=sn.get("title", ""), aciklama=sn.get("description", ""),
                            resim=thumb(sn), adet=(it.get("contentDetails") or {}).get("itemCount", 0)))
        page = r.get("nextPageToken")
        if not page:
            break
    return out


def bolumler(liste_id, spor, max_pages, adet=-1):
    ck = ("s2:" if spor else "d:") + liste_id   # s2: spor listeleri artık 400 videoya kadar
    c = CACHE.get(ck)
    if adet >= 0 and c and c.get("adet") == adet:
        return c["eps"]
    eps = _bolumler(liste_id, spor, max_pages)
    if adet >= 0:
        CACHE[ck] = {"adet": adet, "eps": eps}
    return eps


def _bolumler(liste_id, spor, max_pages):
    vids, page = [], None
    for _ in range(max_pages):
        p = dict(part="snippet", playlistId=liste_id, maxResults=50)
        if page:
            p["pageToken"] = page
        r = get("playlistItems", **p)
        if not r:
            break
        for it in r.get("items", []):
            sn = it.get("snippet", {})
            t = sn.get("title", "")
            vid = (sn.get("resourceId") or {}).get("videoId")
            if not vid or t in ("Private video", "Deleted video"):
                continue
            if not spor and VIDEO_ATLA.search(t):
                continue
            vids.append(dict(i=vid, t=t, r=(sn.get("thumbnails") or {}).get("medium", {}).get("url") or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                             n=num(BOLUM, t), k=num(KISIM, t), d=sn.get("publishedAt", ""), s=sn.get("position", len(vids))))
        page = r.get("nextPageToken")
        if not page:
            break
    # süre: klip / sahne / Shorts ayıkla
    sure = {}
    for i in range(0, len(vids), 50):
        r = get("videos", part="contentDetails", id=",".join(v["i"] for v in vids[i:i + 50]))
        for it in (r or {}).get("items", []):
            sure[it["id"]] = saniye((it.get("contentDetails") or {}).get("duration"))
    keep = []
    seen = set()
    for v in vids:
        if v["i"] in seen:
            continue
        d = sure.get(v["i"])
        if d is None:
            continue
        mn = MIN_SPOR if spor else (MIN_KISIM if v["k"] > 0 else MIN_SURE)
        if d >= mn:
            seen.add(v["i"])
            keep.append(v)
    if spor:
        keep.sort(key=lambda v: v["d"], reverse=True)
        keep = keep[:400]
    else:
        numbered = sum(1 for v in keep if v["n"] >= 0)
        if numbered * 2 > len(keep):
            keep.sort(key=lambda v: (v["n"] if v["n"] >= 0 else 10 ** 9, max(v["k"], 0), v["s"]))
        else:
            keep.sort(key=lambda v: v["s"])
    for v in keep:
        v.pop("s", None)
    return keep


# ---------- hazırla ----------
def main():
    os.makedirs(OUT, exist_ok=True)
    gizle = {key(x) for x in cfg.get("gizle", [])}
    yazilan = set()
    index = {"guncelleme": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "kanallar": []}

    def sezon_yaz(liste_id, eps):
        json.dump(eps, open(os.path.join(OUT, liste_id + ".json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        yazilan.add(liste_id + ".json")

    for k in cfg.get("kanallar", []):
        spor = (k.get("tur") or "").lower() == "spor"
        print(f"== {k.get('ad')} ({'spor' if spor else 'dizi'})", flush=True)
        diziler, var = [], set()

        # 1) elle eklenen diziler (öncelikli)
        for d in k.get("diziler", []):
            ss = []
            for z in d.get("sezonlar", []):
                lid = re.search(r"list=([A-Za-z0-9_-]+)", z.get("liste", "")) or re.fullmatch(r"([A-Za-z0-9_-]{10,})", z.get("liste", "").strip())
                if not lid:
                    continue
                eps = bolumler(lid.group(1), spor, 20)
                if eps:
                    sezon_yaz(lid.group(1), eps)
                    ss.append(dict(ad=z.get("ad") or f"{len(ss) + 1}. Sezon", id=lid.group(1), adet=len(eps)))
            if ss or d.get("link"):
                diziler.append(dict(ad=d["ad"], aciklama=d.get("aciklama", ""), afis=d.get("afis", ""), link=d.get("link", ""), sezonlar=ss))
                var.add(key(d["ad"]))

        # 2) kanalın resmî YouTube hesaplarından otomatik
        lists = []
        for src in k.get("youtube", []):
            cid = kanal_id(src)
            if not cid:
                print(f"  ! kanal bulunamadı: {src}", flush=True)
                continue
            lists += listeler(cid, 6 if spor else 8)

        if spor:
            for l in lists[:120]:
                if l["adet"] < 3 or key(l["baslik"]) in gizle or key(l["baslik"]) in var:
                    continue
                if not SPOR_EVET.search(l["baslik"]) or SPOR_HAYIR.search(l["baslik"]):   # sadece maç özetleri / goller
                    continue
                eps = bolumler(l["id"], True, 8, l["adet"])
                if not eps:
                    continue
                sezon_yaz(l["id"], eps)
                diziler.append(dict(ad=l["baslik"].strip(), aciklama=kisalt(l["aciklama"]), afis=l["resim"],
                                    sezonlar=[dict(ad="Videolar", id=l["id"], adet=len(eps))], spor=True))
        else:
            gruplar, adlar, gorulen = {}, {}, set()
            for l in lists:
                if l["id"] in gorulen or l["adet"] < 3 or LISTE_ATLA.search(l["baslik"]) or not dizi_mi(l["baslik"]):
                    continue
                gorulen.add(l["id"])
                ad = dizi_adi(l["baslik"])
                kk = key(ad)
                if len(kk) < 2 or kk in var or kk in gizle or key(l["baslik"]) in gizle:
                    continue
                gruplar.setdefault(kk, []).append(l)
                adlar.setdefault(kk, ad)
            for kk, g in gruplar.items():
                g.sort(key=lambda l: max(num(SEZON, l["baslik"]), 0))
                dolu = []
                for l in g:
                    eps = bolumler(l["id"], False, 10, l["adet"])
                    # dizi bölümü: başlıkların çoğunda "N. Bölüm" olmalı (sohbet/derleme listelerini eler)
                    if eps and sum(1 for e in eps if e["n"] >= 0) >= max(2, 0.6 * len(eps)):
                        dolu.append((l, eps))
                if not dolu:   # içi boş dizi: listeye hiç girmez
                    continue
                ss = []
                numarasiz = [l for l, _ in dolu if num(SEZON, l["baslik"]) < 0]
                for idx, (l, eps) in enumerate(dolu):
                    n = num(SEZON, l["baslik"])
                    if len(dolu) == 1 and n < 0:
                        ad = "Bölümler"
                    elif n > 0:
                        ad = f"{n}. Sezon"
                    else:
                        ad = f"Bölümler {numarasiz.index(l) + 1}" if len(numarasiz) > 1 else "Bölümler"
                    sezon_yaz(l["id"], eps)
                    ss.append(dict(ad=ad, id=l["id"], adet=len(eps)))
                son = dolu[-1][0]
                afis = son["resim"] or dolu[-1][1][0]["r"].replace("mqdefault", "hqdefault")
                diziler.append(dict(ad=adlar[kk], aciklama=kisalt(son["aciklama"]), afis=afis, sezonlar=ss))

        if not spor:
            for d in diziler:
                try:
                    diziyi_tamamla(d, k.get("youtube", []), gizle, sezon_yaz)
                    sezonlari_duzenle(d)
                except KotaDoldu:
                    raise
                except Exception as e:
                    print(f"  ! tamamlama hatası {d['ad']}: {e}", flush=True)
        print(f"  {len(diziler)} dizi", flush=True)
        if diziler:
            index["kanallar"].append(dict(ad=k["ad"], logo=k.get("logo", ""), spor=spor, diziler=diziler))

    # Bir kanal bu sefer hiç dizi vermediyse (YouTube geçici hata vb.) önceki hazır listedeki hâli korunur
    try:
        eski = json.load(open(os.path.join(OUT, "index.json"), encoding="utf-8"))
    except Exception:
        eski = {"kanallar": []}
    var_ad = {k["ad"] for k in index["kanallar"]}
    sira = {k["ad"]: i for i, k in enumerate(cfg.get("kanallar", []))}
    for k in eski.get("kanallar", []):
        if k["ad"] in var_ad or k["ad"] not in sira:
            continue
        index["kanallar"].append(k)
        print(f"  ~ {k['ad']}: bu sefer alınamadı, önceki liste korundu", flush=True)
        for d in k.get("diziler", []):
            for z in d.get("sezonlar", []):
                yazilan.add(z["id"] + ".json")
    index["kanallar"].sort(key=lambda k: sira.get(k["ad"], 999))
    if not index["kanallar"]:
        sys.exit("Hiç dizi bulunamadı, eski liste korunuyor")
    json.dump(index, open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    yazilan.add("index.json")
    for f in os.listdir(OUT):   # artık kullanılmayan sezon dosyaları
        if f not in yazilan and not f.startswith("SON_") and f != "filmler.json":   # spor/sinema dosyaları başka betiklerin
            os.remove(os.path.join(OUT, f))
    print(f"Bitti: {len(yazilan) - 1} sezon dosyası, YouTube kotası ~{units} birim", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        # yarıda kalsa bile (kota doldu) önbellek kaydedilir; ertesi gün kaldığı yerden devam eder, eski liste korunur
        CACHE.pop("_kural", None); CACHE["_kural"] = KURAL
        cache_kaydet()
        print(f"YouTube kotası ~{units} birim", flush=True)
