#!/usr/bin/env python3
"""
Canlı TV — Sinema bölümü hazırlayıcı (GitHub Actions'ta her gün çalışır).

- canlitv/filmler.json'daki RESMÎ film kanallarının yüklemelerini okur.
- Sadece tam filmleri alır: ≥ 55 dk, herkese açık, başka uygulamada oynatılabilir, Türkiye'de engelli değil,
  dizi bölümü / canlı yayın / derleme değil.
- Türü (Komedi, Dram, Polisiye …) başlıktan, etiketlerden, kanalın oynatma listesi adlarından bulur.
- "Zamana yayma": ilk gün 'ilk' kadar film yayına girer, sonra her gün 'gunluk' kadar eski film + kanallara
  yeni yüklenen bütün filmler eklenir. Böylece uygulamada her gün yeni filmler görünür.
- Çıktı: canlitv/hazir/filmler.json (en son eklenen en üstte).
Kota: kanal başına ilk taramada ~120 birim, sonraki günlerde birkaç birim.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "canlitv", "filmler.json")
OUT = os.path.join(ROOT, "canlitv", "hazir", "filmler.json")
STATE_F = os.path.join(ROOT, "scripts", "film_onbellek.json")
API = "https://www.googleapis.com/youtube/v3/"

cfg = json.load(open(SRC, encoding="utf-8"))
dcfg = json.load(open(os.path.join(ROOT, "canlitv", "diziler.json"), encoding="utf-8"))
KEY = os.environ.get("YT_KEY") or dcfg.get("apiKey", "")
if not KEY:
    sys.exit("API anahtarı yok")
ILK = int(cfg.get("ilk", 600))
GUNLUK = int(cfg.get("gunluk", 60))
GIZLE = set(cfg.get("gizle") or [])
BUGUN = datetime.date.today().isoformat()
units = 0


class KotaDoldu(Exception):
    pass


def get(path, **params):
    global units
    params["key"] = KEY
    url = API + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "korpesoft-film-hazirla"})
            with urllib.request.urlopen(req, timeout=30) as r:
                units += 1
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code in (400, 403, 404):
                print(f"  ! {path} {e.code} {body[:200]}", flush=True)
                if "quota" in body.lower() or "rateLimitExceeded" in body:
                    raise KotaDoldu()
                return None
            time.sleep(2 + attempt * 3)
        except Exception:
            time.sleep(2 + attempt * 3)
    return None


try:
    ST = json.load(open(STATE_F, encoding="utf-8"))
except Exception:
    ST = {}
ST.setdefault("kanallar", {})
ST.setdefault("filmler", {})      # id → film kaydı (havuz). 'e' alanı varsa yayında (eklendiği gün)
ST.setdefault("red", [])          # film olmadığı anlaşılan video kimlikleri (bir daha sorulmaz)
KURAL = "v2"   # ayıklama/tür kuralları değişince artır: filmler yeniden incelenir, yayına giriş tarihleri korunur
if ST.get("kural") != KURAL:
    ST["eski_e"] = {v: f["e"] for v, f in ST["filmler"].items() if f.get("e")}
    ST["filmler"] = {}
    for kb in ST["kanallar"].values():
        kb.pop("tarandi", None)
    ST["kural"] = KURAL
RED = set(ST["red"])


def kaydet():
    ST["red"] = sorted(RED)
    json.dump(ST, open(STATE_F, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


# ---------------- metin kuralları ----------------
I = re.IGNORECASE | re.UNICODE
FILM_DEGIL = re.compile(
    r"(\bb[oö]l[uü]m\b|\d+\s*\.?\s*b[oö]l[uü]m|\bsezon\b|episode|canlı yayın|\blive\b|derleme|en komik sahne|sahneleri|kolaj|"
    r"\bklip\b|fragman|trailer|teaser|kamera arkası|röportaj|konser|şarkı|müzik|\bmix\b|belgesel|#shorts|\bdizi\b|"
    r"tiyatro|stand ?up|skeç|sesli kitap|masal|anları|\banlar\b|en güzel|en iyi sahne|best of|compilation|derlemesi|özel bölüm)", I)
GENEL = re.compile(
    r"(türk(?:çe)?|yerli|yabancı|film(?:i|leri|ler)?|sinema(?:sı)?|full|hd|4k|1080p|720p|tek parça|izle|restore(?:li)?|"
    r"restorasyonlu|sansürsüz|yeni|en iyi|komedi|dram|aksiyon|gerilim|polisiye|romantik|korku|aile|yeşilçam|"
    r"eski|klasik|nostalji|altyazılı|dublaj|seyret|\d{4}|[\(\)\[\]\-–—|:!.,★☆•])", I)
YIL_RX = re.compile(r"\b(19[3-9]\d|20[0-3]\d)\b")
TURLER = [
    ("Komedi", re.compile(r"(komedi|comedy|güldür|kahkaha)", I)),
    ("Dram", re.compile(r"(\bdram|drama|duygusal|ağlatan|hüzünlü)", I)),
    ("Aksiyon", re.compile(r"(aksiyon|action|macera|dövüş|adventure)", I)),
    ("Polisiye & Gerilim", re.compile(r"(polisiye|gerilim|thriller|\bsuç\b|dedektif|mafya|cinayet|soygun|crime)", I)),
    ("Romantik", re.compile(r"(romantik|romance|aşk filmi|aşk hikaye|love story)", I)),
    ("Korku", re.compile(r"(korku|horror|dehşet|cin(ler)? filmi)", I)),
    ("Aile & Çocuk", re.compile(r"(aile filmi|çocuk filmi|family|animasyon|çizgi film)", I)),
    ("Tarih & Savaş", re.compile(r"(tarihi film|tarih filmi|savaş filmi|biyografi|kurtuluş savaşı|çanakkale|osmanlı)", I)),
]
KATEGORILER = [t for t, _ in TURLER] + ["Yeşilçam"]


def saniye(iso):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def film_adi(t):
    """'Kibar Feyzo | Kemal Sunal Türk Komedi Filmi (1978)' → 'Kibar Feyzo'"""
    t = re.sub(r"\s+", " ", (t or "").replace("｜", "|")).strip()
    parcalar = re.split(r"\s+[|\-–—]\s+|\s*\|\s*", t)
    for p in parcalar:
        p2 = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", p).strip(" -–—|:")
        p2 = re.sub(r"\b(4k|full ?hd|hd|1080p|720p|tek parça|restorasyonlu)\b", "", p2, flags=I).strip(" -–—|:")
        if re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2}", GENEL.sub(" ", p2)):
            return p2[:80]
    return re.sub(r"[\(\[][^\)\]]*[\)\]]", "", parcalar[0]).strip()[:80] or t[:80]


def kisalt(d):
    out = []
    for line in (d or "").split("\n"):
        s = line.strip()
        if not s or "http" in s or s.startswith("#") or s.startswith("@") or "abone ol" in s.lower():
            continue
        out.append(s)
        if len(" ".join(out)) > 240:
            break
    s = " ".join(out)
    if len(s) <= 240:
        return s
    cut = max(s.rfind(". ", 0, 240), s.rfind("! ", 0, 240), s.rfind("? ", 0, 240))
    return s[:cut + 1] if cut > 80 else s[:237].strip() + "…"


def yil_bul(baslik, aciklama):
    m = YIL_RX.search(baslik or "")
    if m:
        return int(m.group(1))
    m = re.search(r"(yapım yılı|yapim yili|vizyon(?: tarihi)?|yıl)\s*[:\-]?\s*(19[3-9]\d|20[0-3]\d)", aciklama or "", I)
    return int(m.group(2)) if m else 0


def turler(metin_guclu, aciklama, liste_turleri):
    k = set(liste_turleri)
    for ad, rx in TURLER:
        if rx.search(metin_guclu):
            k.add(ad)
    # açıklamada sadece açıkça "Tür: Komedi" gibi yazılmışsa
    m = re.search(r"(tür|tur|genre|kategori)\s*[:\-]\s*([^\n]{0,60})", aciklama or "", I)
    if m:
        for ad, rx in TURLER:
            if rx.search(m.group(2)):
                k.add(ad)
    return k


# ---------------- YouTube ----------------
def kanal_bilgi(src):
    m = re.search(r"(UC[A-Za-z0-9_-]{22})", src)
    if m:
        p = {"id": m.group(1)}
    else:
        h = re.search(r"@([A-Za-z0-9._-]+)", src)
        p = {"forHandle": "@" + h.group(1)} if h else {"forUsername": src}
    r = get("channels", part="snippet,statistics,contentDetails", **p)
    items = (r or {}).get("items") or []
    return items[0] if items else None


def liste_turleri(cid, cache):
    """Kanalın 'Komedi Filmleri' gibi oynatma listelerinden video → tür eşlemesi (haftada bir yenilenir)."""
    if cache.get("tur_t", 0) > time.time() - 7 * 86400 and "tur" in cache:
        return cache["tur"]
    eslem, page, sayfa = {}, None, 0
    turlu = []
    while sayfa < 4:
        p = dict(part="snippet", channelId=cid, maxResults=50)
        if page:
            p["pageToken"] = page
        r = get("playlists", **p)
        sayfa += 1
        if not r:
            break
        for it in r.get("items", []):
            ad = it["snippet"].get("title", "")
            kt = [t for t, rx in TURLER if rx.search(ad)]
            if kt:
                turlu.append((it["id"], kt))
        page = r.get("nextPageToken")
        if not page:
            break
    for lid, kt in turlu[:15]:
        page = None
        for _ in range(10):
            p = dict(part="contentDetails", playlistId=lid, maxResults=50)
            if page:
                p["pageToken"] = page
            r = get("playlistItems", **p)
            if not r:
                break
            for it in r.get("items", []):
                v = it["contentDetails"]["videoId"]
                eslem.setdefault(v, [])
                for t in kt:
                    if t not in eslem[v]:
                        eslem[v].append(t)
            page = r.get("nextPageToken")
            if not page:
                break
    cache["tur"], cache["tur_t"] = eslem, time.time()
    return eslem


def yeni_videolar(uploads, ilk_tarama):
    """Yüklemeler listesini en yeniden okur; daha önce görülen bir sayfaya gelince durur."""
    out, page = [], None
    for _ in range(80 if ilk_tarama else 6):
        p = dict(part="contentDetails", playlistId=uploads, maxResults=50)
        if page:
            p["pageToken"] = page
        r = get("playlistItems", **p)
        if not r:
            break
        ids = [it["contentDetails"]["videoId"] for it in r.get("items", [])]
        yeni = [v for v in ids if v not in RED and v not in ST["filmler"]]
        out += yeni
        page = r.get("nextPageToken")
        if not page or (not ilk_tarama and len(yeni) < len(ids)):
            break
    return out


def incele(ids, kanal_no, klasik, tur_eslem):
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = get("videos", part="snippet,contentDetails,status", id=",".join(chunk), maxResults=50)
        bulunan = set()
        for it in (r or {}).get("items", []):
            v = it["id"]
            bulunan.add(v)
            sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("status", {})
            bas = sn.get("title", "")
            sure = saniye(cd.get("duration"))
            rr = cd.get("regionRestriction") or {}
            uygun = (55 * 60 <= sure <= 4 * 3600 and st.get("privacyStatus") == "public" and st.get("embeddable", True)
                     and sn.get("liveBroadcastContent", "none") == "none" and not FILM_DEGIL.search(bas)
                     and "TR" not in (rr.get("blocked") or []) and ("allowed" not in rr or "TR" in rr["allowed"]))
            if not uygun:
                RED.add(v)
                continue
            acik = sn.get("description", "")
            etiket = " ".join(sn.get("tags") or [])
            yil = yil_bul(bas, acik)
            # bazı kanallar her filme bütün türleri etiket olarak yazıyor: 3+ tür tutan etiketler yok sayılır
            et_tur = [t for t, rx in TURLER if rx.search(etiket)]
            k = turler(bas + (" " + etiket if len(et_tur) <= 2 else ""), acik, tur_eslem.get(v, []))
            if klasik or (0 < yil < 1990) or re.search(r"yeşilçam|yesilcam", bas + " " + etiket, I):
                k.add("Yeşilçam")
            ST["filmler"][v] = dict(t=film_adi(bas), y=yil, s=round(sure / 60), c=kanal_no, a=kisalt(acik),
                                    k=sorted(k), p=sn.get("publishedAt", "")[:10])
            if v in ST.get("eski_e", {}):          # kurallar değişse de yayına giriş günü aynı kalır
                ST["filmler"][v]["e"] = ST["eski_e"][v]
        for v in chunk:          # silinmiş / gizli
            if v not in bulunan:
                RED.add(v)


kota = [False]


def main():
    kanallar = []
    try:
        for n, k in enumerate(cfg["kanallar"]):
            ad = k["ad"]
            print(f"== {ad}", flush=True)
            kb = ST["kanallar"].setdefault(ad, {})
            bilgi = kanal_bilgi(k["src"])
            if not bilgi:
                print("  kanal bulunamadı", flush=True)
                kanallar.append(ad)
                continue
            cid = bilgi["id"]
            print(f"  {bilgi['snippet']['title']} | {bilgi['snippet'].get('customUrl')} | abone "
                  f"{bilgi.get('statistics', {}).get('subscriberCount')} | video {bilgi.get('statistics', {}).get('videoCount')}", flush=True)
            kanallar.append(ad)
            uploads = bilgi["contentDetails"]["relatedPlaylists"]["uploads"]
            ilk = not kb.get("tarandi")
            tur_eslem = liste_turleri(cid, kb)
            ids = yeni_videolar(uploads, ilk)
            once = len(ST["filmler"])
            incele(ids, n, k.get("klasik", False), tur_eslem)
            kb["tarandi"] = True
            print(f"  {len(ids)} yeni video incelendi, {len(ST['filmler']) - once} film", flush=True)
            kaydet()
    except KotaDoldu:
        kota[0] = True
        print("Kota doldu — kalan kanallar yarın", flush=True)

    # ---- yayına alma (zamana yayma) ----
    havuz = ST["filmler"]
    for v in GIZLE:
        havuz.pop(v, None)
    yayinda = [v for v, f in havuz.items() if f.get("e")]
    bekleyen = [v for v, f in havuz.items() if not f.get("e")]
    hafta_once = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    # kanallara son bir haftada yüklenen gerçekten yeni filmler hemen
    for v in bekleyen:
        if havuz[v].get("p", "") >= hafta_once:
            havuz[v]["e"] = BUGUN
    bekleyen = [v for v in bekleyen if not havuz[v].get("e")]
    if ST.get("son_gun") != BUGUN:
        hak = ILK if not yayinda else GUNLUK
        # kanallar arasında sırayla (çeşit olsun), her kanalda en yeni yüklenen önce
        kuyruk = {}
        for v in sorted(bekleyen, key=lambda x: havuz[x].get("p", ""), reverse=True):
            kuyruk.setdefault(havuz[v]["c"], []).append(v)
        while hak > 0 and any(kuyruk.values()):
            for c in list(kuyruk):
                if kuyruk[c] and hak > 0:
                    havuz[kuyruk[c].pop(0)]["e"] = BUGUN
                    hak -= 1
        ST["son_gun"] = BUGUN
    kaydet()

    liste = [(v, f) for v, f in havuz.items() if f.get("e")]
    # aynı film iki kez (iki kanalda ya da yeniden yüklenmiş): en yeni yükleme kalır
    liste.sort(key=lambda x: x[1].get("p", ""), reverse=True)
    gorulen, tek = set(), []
    for v, f in liste:
        anahtar = re.sub(r"[^a-z0-9çğıöşü]", "", f["t"].lower().replace("I", "ı"))
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        tek.append((v, f))
    liste = tek
    liste.sort(key=lambda x: (x[1]["e"], x[1].get("p", "")), reverse=True)
    ki = {k: i for i, k in enumerate(KATEGORILER)}
    out = dict(
        guncelleme=datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        kategoriler=KATEGORILER,
        kanallar=[k["ad"] for k in cfg["kanallar"]],
        bekleyen=len([1 for f in havuz.values() if not f.get("e")]),
        filmler=[dict(i=v, t=f["t"], y=f["y"], s=f["s"], c=f["c"], a=f["a"], e=f["e"],
                      k=[ki[x] for x in f["k"] if x in ki]) for v, f in liste],
    )
    if not out["filmler"]:
        print("Hiç film yok — dosya yazılmadı", flush=True)
        return
    try:
        onceki = len(json.load(open(OUT, encoding="utf-8")).get("filmler", []))
    except Exception:
        onceki = 0
    if kota[0] and len(out["filmler"]) < onceki:
        print(f"Kota yarıda kaldı ({len(out['filmler'])} < {onceki}) — eski liste korunuyor", flush=True)
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    say = {k: 0 for k in KATEGORILER}
    for _, f in liste:
        for x in f["k"]:
            say[x] = say.get(x, 0) + 1
    print(f"Yayında {len(liste)} film, bekleyen {out['bekleyen']}, kota {units} birim", flush=True)
    print("Kategoriler: " + ", ".join(f"{k} {n}" for k, n in say.items()), flush=True)


if __name__ == "__main__":
    main()
