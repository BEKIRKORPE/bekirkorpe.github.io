#!/usr/bin/env python3
"""
Canlı TV — EN SON maç özetleri (2 saatte bir + diziler çalışmasından sonra).

Bekir: "10 sene önceki değil, en son yayınlanan maç özeti; bugün oynanan maçın özeti varsa o."
- Spor kanallarının YÜKLEMELER listesini (en yeni video en üstte) okur, sadece maç özeti / goller videolarını alır.
- Her spor kanalının en başına "🔥 Son Maç Özetleri" koyar (en yeni üstte, en fazla 300 video).
- Bütün kanalların son özetlerini birleştirip spor kanallarının en başına "⚽ Tüm Maç Özetleri" kanalı ekler.
- Kanalın diğer listelerini en yeni videosuna göre sıralar; son videosu 2 yıldan eski listeleri gizler.
Kota: kanal başına ~6 birim.
"""
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAZIR = os.path.join(ROOT, "canlitv", "hazir")
INDEX = os.path.join(HAZIR, "index.json")
STATE_F = os.path.join(ROOT, "scripts", "spor_onbellek.json")
API = "https://www.googleapis.com/youtube/v3/"

cfg = json.load(open(os.path.join(ROOT, "canlitv", "diziler.json"), encoding="utf-8"))
KEY = os.environ.get("YT_KEY") or cfg.get("apiKey", "")
I = re.IGNORECASE | re.UNICODE
SPOR_EVET = re.compile(r"(özet|ozet|goller|geniş özet|maçın tamamı|full maç|highlights|goals)", I)   # sadece gerçek özet/maç videoları
SPOR_HAYIR = re.compile(r"(#shorts|\bshorts\b|kısa|önemli an|röportaj|basın toplantısı|transfer|tanıyalım|teknik direktör açıkla|"
                        r"antrenman|canlı yayın|\blive\b|podcast|tahmin|yorumladı|değerlendir|stüdyo|program|orta nokta|sevinc|açıkladı|\?)", I)
SON_AD = "🔥 Son Maç Özetleri"
units = 0


class KotaDoldu(Exception):
    pass


def get(path, **params):
    global units
    params["key"] = KEY
    url = API + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "korpesoft-spor"}), timeout=30) as r:
                units += 1
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code in (400, 403, 404):
                print(f"  ! {path} {e.code} {body[:160]}", flush=True)
                if "quota" in body.lower() or "rateLimitExceeded" in body:
                    raise KotaDoldu()
                return None
            time.sleep(2 + attempt * 3)
        except Exception:
            time.sleep(2 + attempt * 3)
    return None


def saniye(iso):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


try:
    ST = json.load(open(STATE_F, encoding="utf-8"))
except Exception:
    ST = {}
ST.setdefault("kanal", {})     # kaynak → uploads listesi
ST.setdefault("video", {})     # video kimliği → {t, s, d} (bir kez sorulur)


def uploads(src):
    if src in ST["kanal"]:
        return ST["kanal"][src]
    m = re.search(r"(UC[A-Za-z0-9_-]{22})", src)
    if m:
        p = {"id": m.group(1)}
    elif src.startswith("user:"):
        p = {"forUsername": src[5:]}
    else:
        h = re.search(r"@([A-Za-z0-9._-]+)", src)
        p = {"forHandle": "@" + h.group(1)} if h else {"forUsername": src}
    r = get("channels", part="contentDetails,snippet", **p)
    it = ((r or {}).get("items") or [None])[0]
    up = it["contentDetails"]["relatedPlaylists"]["uploads"] if it else None
    print(f"  kaynak {src} → {it['snippet']['title'] if it else 'BULUNAMADI'}", flush=True)
    ST["kanal"][src] = up
    return up


def son_ozetler(up, sayfa=4):
    ids, page = [], None
    for _ in range(sayfa):
        p = dict(part="contentDetails", playlistId=up, maxResults=50)
        if page:
            p["pageToken"] = page
        r = get("playlistItems", **p)
        if not r:
            break
        ids += [x["contentDetails"]["videoId"] for x in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    yeni = [v for v in ids if v not in ST["video"]]
    for i in range(0, len(yeni), 50):
        r = get("videos", part="snippet,contentDetails", id=",".join(yeni[i:i + 50]), maxResults=50)
        for it in (r or {}).get("items", []):
            sn = it["snippet"]
            ST["video"][it["id"]] = dict(t=sn.get("title", ""), s=saniye(it["contentDetails"].get("duration")),
                                         d=sn.get("publishedAt", ""), l=sn.get("liveBroadcastContent", "none"))
    out = []
    for v in ids:
        x = ST["video"].get(v)
        if not x or x["l"] != "none" or x["s"] <= 61 or not SPOR_EVET.search(x["t"]) or SPOR_HAYIR.search(x["t"]):
            continue
        out.append(dict(i=v, t=x["t"], r=f"https://i.ytimg.com/vi/{v}/mqdefault.jpg", n=-1, k=-1, d=x["d"]))
    return out


def yaz(liste_id, eps):
    json.dump(eps, open(os.path.join(HAZIR, liste_id + ".json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


def son_tarih(liste_id):
    try:
        eps = json.load(open(os.path.join(HAZIR, liste_id + ".json"), encoding="utf-8"))
        return max((e.get("d", "") for e in eps), default="")
    except Exception:
        return ""


def main():
    idx = json.load(open(INDEX, encoding="utf-8"))
    spor_cfg = {k["ad"]: k for k in cfg["kanallar"] if (k.get("tur") or "").lower() == "spor"}
    iki_yil = (datetime.datetime.utcnow() - datetime.timedelta(days=730)).strftime("%Y-%m-%d")
    hepsi = []
    kota = False
    for kn in idx["kanallar"]:
        if not kn.get("spor") or kn["ad"] not in spor_cfg:
            continue
        print(f"== {kn['ad']}", flush=True)
        eps, ilk_liste = [], None
        try:
            for src in spor_cfg[kn["ad"]].get("youtube", []):
                up = uploads(src)
                if up:
                    ilk_liste = ilk_liste or up
                    eps += son_ozetler(up)
        except KotaDoldu:
            kota = True
            print("  kota doldu — önceki son özetler korunuyor", flush=True)
        diziler = [d for d in kn["diziler"] if d.get("ad") != SON_AD]
        # eski listeler: en yenisi üstte, 2 yıldan eski olanlar gizli
        for d in diziler:
            d["_son"] = max((son_tarih(z["id"]) for z in d.get("sezonlar", [])), default="")
        diziler = [d for d in diziler if not d["_son"] or d["_son"][:10] >= iki_yil]
        diziler.sort(key=lambda d: d["_son"], reverse=True)
        for d in diziler:
            d.pop("_son", None)
        lid = "SON_" + (ilk_liste or re.sub(r"\W", "", kn["ad"]))
        if eps:
            tek, gor = [], set()
            for e in sorted(eps, key=lambda e: e["d"], reverse=True):
                if e["i"] not in gor:
                    gor.add(e["i"])
                    tek.append(e)
            eps = tek[:300]
            yaz(lid, eps)
            hepsi += [dict(e, t=e["t"]) for e in eps[:120]]
        elif os.path.exists(os.path.join(HAZIR, lid + ".json")):
            eps = json.load(open(os.path.join(HAZIR, lid + ".json"), encoding="utf-8"))
            hepsi += eps[:120]
        if eps:
            diziler.insert(0, dict(ad=SON_AD, aciklama=f"{kn['ad']} kanalına yüklenen en son maç özetleri ve goller. En yeni en üstte.",
                                   afis=eps[0]["r"].replace("mqdefault", "hqdefault"),
                                   sezonlar=[dict(ad="Videolar", id=lid, adet=len(eps))], spor=True))
            print(f"  son özet: {len(eps)} (en yeni {eps[0]['d'][:16]} {eps[0]['t'][:60]})", flush=True)
        kn["diziler"] = diziler

    # ---- bütün kanalların son özetleri tek yerde ----
    idx["kanallar"] = [k for k in idx["kanallar"] if k.get("ad") != "Tüm Maç Özetleri"]
    if hepsi:
        tek, gor = [], set()
        for e in sorted(hepsi, key=lambda e: e["d"], reverse=True):
            if e["i"] not in gor:
                gor.add(e["i"])
                tek.append(e)
        tek = tek[:400]
        yaz("SON_TUM", tek)
        bugun = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        dun = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        son24 = [e for e in tek if e["d"][:10] >= dun]
        tum = dict(ad="Tüm Maç Özetleri", logo="https://bekirkorpe.github.io/canlitv/logo_tum_spor.png", spor=True, diziler=[])
        if son24:
            yaz("SON_BUGUN", son24)
            tum["diziler"].append(dict(ad="⚡ Son 24 Saat", aciklama="Son 24 saatte yayınlanan maç özetleri, bütün spor kanallarından.",
                                       afis=son24[0]["r"].replace("mqdefault", "hqdefault"),
                                       sezonlar=[dict(ad="Videolar", id="SON_BUGUN", adet=len(son24))], spor=True))
        tum["diziler"].append(dict(ad=SON_AD, aciklama="Bütün spor kanallarının en son maç özetleri. En yeni en üstte.",
                                   afis=tek[0]["r"].replace("mqdefault", "hqdefault"),
                                   sezonlar=[dict(ad="Videolar", id="SON_TUM", adet=len(tek))], spor=True))
        ilk_spor = next((i for i, k in enumerate(idx["kanallar"]) if k.get("spor") and k["ad"] in spor_cfg), len(idx["kanallar"]))   # Programlar da "spor" modunda; ona göre yer alınmaz
        idx["kanallar"].insert(ilk_spor, tum)
        print(f"Tüm: {len(tek)} özet, son 24 saat {len(son24)} (bugün {bugun})", flush=True)

    # eski videolar önbellekten temizlensin (dosya büyümesin): son 60 gün
    sinir = (datetime.datetime.utcnow() - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    ST["video"] = {v: x for v, x in ST["video"].items() if x.get("d", "")[:10] >= sinir}
    json.dump(ST, open(STATE_F, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(idx, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Bitti. Kota ~{units} birim{' (kota doldu)' if kota else ''}", flush=True)


if __name__ == "__main__":
    main()
