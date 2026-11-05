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
            body = e.read().decode("utf-8", "ignore")[:300]
            if e.code in (400, 403, 404):
                print(f"  ! {path} {e.code} {body}", flush=True)
                if "quotaExceeded" in body:
                    raise SystemExit("YouTube kotası doldu")
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
TEMIZLE = [r"\d{1,2}\s*\.?\s*sezon", r"sezon\s*\d{1,2}", r"t[uü]m\s*b[oö]l[uü]mleri?", r"b[oö]l[uü]mleri?",
           r"full\s*b[oö]l[uü]m(ler)?", r"\bfull\b", r"\bhd\b", r"\(.*?\)", r"\[.*?\]"]
MIN_SURE, MIN_KISIM, MIN_SPOR = 20 * 60, 8 * 60, 61


def dizi_adi(t):
    s = t or ""
    for r in TEMIZLE:
        s = re.sub(r, " ", s, flags=I)
    s = re.sub(r"[|•·–—:_/#-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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


def bolumler(liste_id, spor, max_pages):
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
        keep = keep[:150]
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
            lists += listeler(cid, 2 if spor else 4)

        if spor:
            for l in lists[:30]:
                if l["adet"] < 3 or key(l["baslik"]) in gizle or key(l["baslik"]) in var:
                    continue
                eps = bolumler(l["id"], True, 2)
                if not eps:
                    continue
                sezon_yaz(l["id"], eps)
                diziler.append(dict(ad=l["baslik"].strip(), aciklama=kisalt(l["aciklama"]), afis=l["resim"],
                                    sezonlar=[dict(ad="Videolar", id=l["id"], adet=len(eps))], spor=True))
        else:
            gruplar, adlar, gorulen = {}, {}, set()
            for l in lists:
                if l["id"] in gorulen or l["adet"] < 3 or LISTE_ATLA.search(l["baslik"]):
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
                    eps = bolumler(l["id"], False, 10)
                    if eps:
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

        print(f"  {len(diziler)} dizi", flush=True)
        if diziler:
            index["kanallar"].append(dict(ad=k["ad"], logo=k.get("logo", ""), spor=spor, diziler=diziler))

    if not index["kanallar"]:
        sys.exit("Hiç dizi bulunamadı, eski liste korunuyor")
    json.dump(index, open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    yazilan.add("index.json")
    for f in os.listdir(OUT):   # artık kullanılmayan sezon dosyaları
        if f not in yazilan:
            os.remove(os.path.join(OUT, f))
    print(f"Bitti: {len(yazilan) - 1} sezon dosyası, YouTube kotası ~{units} birim", flush=True)


if __name__ == "__main__":
    main()
