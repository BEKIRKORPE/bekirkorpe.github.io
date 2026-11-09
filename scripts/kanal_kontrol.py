#!/usr/bin/env python3
"""
Canlı TV — 8 saatte bir BÜTÜN kanalları dener (Bekir: "hangisi çalışmıyor tek tek nereden bileyim").

- canlitv/kanallar.m3u'daki her yayın adresini açar: cevap veriyor mu, gerçekten yayın listesi (#EXTM3U) mi.
- Not: GitHub'ın sunucuları Türkiye dışında. Türkiye'ye özel (yurt dışına kapalı, 403) yayınlar "belirsiz" sayılır,
  kapalı sayılmaz. Kapalı = adres yok (404/410), sunucu yok, zaman aşımı, yayın listesi değil.
- Bir kanalın BÜTÜN adresleri art arda 3 denemede (≈24 saat) kapalıysa:
  1) Kendi yeni adresini arar — sadece kanalın kendi resmî sunucu ailesinde: aynı CDN'in -live / canlı olmayan
     adı, ?app=web eki ve herkese açık iptv-org listesindeki aynı kanalın resmî sunucudaki adresleri.
     Çalışan bulursa kanallar.m3u'ya kendisi yazar, kapalı adresi "# kapalı" diye işaretler.
  2) Bulamazsa her kontrolde (8 saatte bir) "Kapalı kanallar" konusuna yazar → Bekir'e e-posta gider.
- Sonuç herkese açık: canlitv/kanal_durum.json
"""
import datetime
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M3U = os.path.join(ROOT, "canlitv", "kanallar.m3u")
OUT = os.path.join(ROOT, "canlitv", "kanal_durum.json")
STATE_F = os.path.join(ROOT, "scripts", "kanal_onbellek.json")
IPTV_ORG = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/tr.m3u"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
BUGUN = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
KAPALI_SAYI = 3          # art arda bu kadar denemede kapalıysa (8 saatte bir → ≈24 saat)

# Resmî yayın sunucu aileleri: yeni adres SADECE bunlardan biriyse kabul edilir (korsan adres asla girmez)
RESMI = re.compile(r"(\.trt\.com\.tr|daioncdn\.net|ercdn\.net|mncdn\.com|turknet\.|tv8\.com\.tr|startv\.com\.tr|"
                   r"showtv\.com\.tr|kanald\.com\.tr|atv\.com\.tr|nowtv\.com\.tr|ntv\.com\.tr|haberturk\.|halktv\.com\.tr|"
                   r"tv100\.com|artidijitalmedya\.com|duhnet\.tv|socialsmart\.tv|yayin\.com\.tr|ensonhaber\.com)", re.I)


def ac(url, timeout=15):
    """→ ('ok'|'belirsiz'|'kapali', açıklama, gövde)"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            body = r.read(200000).decode("utf-8", "ignore")
            if "#EXTM3U" not in body[:2000]:
                return "kapali", "yayın listesi değil", ""
            return "ok", f"{r.status}", body
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 451):
            return "belirsiz", f"{e.code} (yurt dışına kapalı olabilir)", ""
        if e.code in (429, 500, 502, 503, 504):
            return "belirsiz", f"{e.code} (sunucu yoğun)", ""
        return "kapali", f"{e.code}", ""
    except (socket.timeout, TimeoutError):
        return "kapali", "zaman aşımı", ""
    except urllib.error.URLError as e:
        r = str(e.reason)
        if "timed out" in r:
            return "kapali", "zaman aşımı", ""
        return "kapali", r[:80], ""
    except Exception as e:
        return "kapali", str(e)[:80], ""


def dene(url):
    durum, neden, body = ac(url)
    if durum == "ok":
        # ana liste ise ilk alt listeyi de dene (bazı kanallar ana listeyi verip görüntüyü vermiyor)
        alt = next((l.strip() for l in body.splitlines() if l.strip() and not l.startswith("#")), None)
        if alt and (".m3u8" in alt or "m3u8" in alt.lower()):
            d2, n2, _ = ac(urllib.parse.urljoin(url, alt))
            if d2 == "kapali":
                return "kapali", "alt liste: " + n2
    return durum, neden


def oku_m3u():
    satirlar = open(M3U, encoding="utf-8").read().splitlines()
    kayit, son = [], None
    for i, l in enumerate(satirlar):
        if l.startswith("#EXTINF"):
            ad = l.rsplit(",", 1)[-1].strip()
            tid = (re.search(r'tvg-id="([^"]*)"', l) or [None, ""])[1]
            son = (ad, tid, i)
        elif l.strip() and not l.startswith("#") and son:
            kayit.append(dict(ad=son[0], id=son[1], extinf=son[2], satir=i, url=l.strip()))
            son = None
    return satirlar, kayit


def tahminler(url):
    """Aynı resmî sunucu ailesinde olası yeni adresler."""
    u = urllib.parse.urlsplit(url)
    out = set()
    h = u.netloc
    if "-live." in h:
        out.add(h.replace("-live.", "."))
    elif h.endswith("daioncdn.net"):
        out.add(h.replace(".daioncdn.net", "-live.daioncdn.net"))
    adaylar = []
    for nh in out:
        adaylar.append(urllib.parse.urlunsplit((u.scheme, nh, u.path, u.query, "")))
    if "app=web" not in u.query:
        adaylar.append(url + ("&" if u.query else "?") + "app=web")
    if u.query:
        adaylar.append(urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", "")))
    return adaylar


def iptv_org():
    try:
        body = urllib.request.urlopen(urllib.request.Request(IPTV_ORG, headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return {}
    d, tid = {}, None
    for l in body.splitlines():
        if l.startswith("#EXTINF"):
            m = re.search(r'tvg-id="([^"@]*)', l)
            tid = m.group(1).lower() if m else None
        elif l.strip() and not l.startswith("#") and tid:
            d.setdefault(tid, []).append(l.strip())
            tid = None
    return d


def github_bildir(kapali):
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not tok or not repo:
        return
    api = f"https://api.github.com/repos/{repo}/issues"
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": "kanal-kontrol"}

    def istek(url, veri=None, yontem=None):
        yontem = yontem or ("POST" if veri is not None else "GET")
        req = urllib.request.Request(url, data=json.dumps(veri).encode() if veri is not None else None,
                                     headers=dict(hdr, **({"Content-Type": "application/json"} if veri is not None else {})), method=yontem)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    try:
        acik = [i for i in istek(api + "?state=open&per_page=50") if i.get("title") == "Kapalı kanallar"]
        if not kapali:
            for i in acik:
                istek(i["url"], {"state": "closed"}, "PATCH")
                istek(i["url"] + "/comments", {"body": "✅ Bütün kanallar yeniden açıldı."}, "POST")
            return
        govde = ("@BEKIRKORPE Canlı TV kanal kontrolü (8 saatte bir) bu kanalların **bütün adreslerini kapalı** buldu "
                 "ve resmî sunucularında yeni adres bulamadı:\n\n" +
                 "\n".join(f"- **{k['ad']}** — {k['neden']}" for k in kapali) +
                 "\n\nUygulamada bu kanallar açılmayınca \"biraz bekleyin\" yazar. Claude'a bu listeyi gönder, yeni resmî adresi bulsun."
                 f"\n\n_Son kontrol: {BUGUN} UTC_")
        if acik:
            onceki = acik[0].get("body") or ""
            istek(acik[0]["url"], {"body": govde}, "PATCH")
            # Bekir: 8 saatte bir e-posta → her kontrolde yorum (GitHub her yorumu e-postayla gönderir)
            istek(acik[0]["url"] + "/comments", {"body": f"@BEKIRKORPE 📺 Kontrol {BUGUN} UTC — açılmayan ve yeni adresi bulunamayan {len(kapali)} kanal:\n\n"
                                                       + "\n".join(f"- **{k['ad']}** — {k['neden']}" for k in kapali)}, "POST")
        else:
            istek(api, {"title": "Kapalı kanallar", "body": govde})
    except Exception as e:
        print("GitHub bildirimi gönderilemedi:", e, flush=True)


def main():
    try:
        ST = json.load(open(STATE_F, encoding="utf-8"))
    except Exception:
        ST = {}
    ST.setdefault("url", {})        # url → art arda kapalı sayısı
    satirlar, kayit = oku_m3u()
    with ThreadPoolExecutor(16) as ex:
        sonuc = dict(zip([k["url"] for k in kayit], ex.map(dene, [k["url"] for k in kayit])))
    for k in kayit:
        d, n = sonuc[k["url"]]
        k["durum"], k["neden"] = d, n
        ST["url"][k["url"]] = ST["url"].get(k["url"], 0) + 1 if d == "kapali" else 0

    # kanal bazında
    kanallar = {}
    for k in kayit:
        kanallar.setdefault(k["ad"], []).append(k)
    iorg = None
    degisti = False
    kapali_kanallar, ozet = [], []
    for ad, ks in kanallar.items():
        durumlar = [k["durum"] for k in ks]
        if "ok" in durumlar:
            dk = "acik"
        elif "belirsiz" in durumlar:
            dk = "belirsiz"
        else:
            dk = "kapali"
        uzun = dk == "kapali" and all(ST["url"].get(k["url"], 0) >= KAPALI_SAYI for k in ks)
        yeni = None
        if dk == "kapali":   # Bekir: kapanan kanala hemen yeni adres aransın, bulunamazsa her 8 saatte haber verilsin
            # 1) kendi yeni adresini ara (resmî sunucu ailesi)
            adaylar = []
            for k in ks:
                adaylar += tahminler(k["url"])
            if iorg is None:
                iorg = iptv_org()
            tid = (ks[0]["id"] or "").split("@")[0].lower()
            adaylar += [u for u in iorg.get(tid, []) if RESMI.search(urllib.parse.urlsplit(u).netloc)]
            mevcut = {k["url"] for k in kayit}
            for u in dict.fromkeys(adaylar):
                if u in mevcut or not RESMI.search(urllib.parse.urlsplit(u).netloc):
                    continue
                if dene(u)[0] == "ok":
                    yeni = u
                    break
            if yeni:
                ilk = ks[0]
                if uzun:   # 24 saattir kapalı eski adresler işaretlenir
                    satirlar[ilk["satir"]] = yeni + "\n# kapalı " + BUGUN[:10] + " (eski adres): " + ilk["url"]
                    for k in ks[1:]:
                        satirlar[k["extinf"]] = "# " + satirlar[k["extinf"]]
                        satirlar[k["satir"]] = "# kapalı " + BUGUN[:10] + ": " + k["url"]
                else:      # geçici kesinti olabilir: eski adres kalır, yeni adres önce denensin diye üstüne eklenir
                    satirlar[ilk["extinf"]] = satirlar[ilk["extinf"]] + "\n" + yeni + "\n" + satirlar[ilk["extinf"]]
                degisti = True
                dk = "yenilendi"
                print(f"✓ {ad}: yeni adres bulundu → {yeni}", flush=True)
            else:
                kapali_kanallar.append(dict(ad=ad, neden=", ".join(sorted({k['neden'] for k in ks}))))
        ozet.append(dict(ad=ad, durum=dk, adres=[dict(url=k["url"], durum=k["durum"], neden=k["neden"],
                                                     kapali_sayi=ST["url"].get(k["url"], 0)) for k in ks],
                         yeni=yeni))
        print(f"{'✅' if dk == 'acik' else '❔' if dk == 'belirsiz' else '🔁' if dk == 'yenilendi' else '❌'} {ad}: "
              + "; ".join(f"{k['durum']}({k['neden']})" for k in ks), flush=True)

    if degisti:
        metin = "\n".join(satirlar)
        if not metin.startswith("#EXTM3U"):
            metin = "#EXTM3U\n" + metin.lstrip("z ﻿").removeprefix("#EXTM3U\n")
        open(M3U, "w", encoding="utf-8").write(metin.rstrip("\n") + "\n")
    canli = {k["url"] for k in kayit}
    ST["url"] = {u: n for u, n in ST["url"].items() if u in canli}
    json.dump(ST, open(STATE_F, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    say = {d: sum(1 for o in ozet if o["durum"] == d) for d in ("acik", "belirsiz", "kapali", "yenilendi")}
    json.dump(dict(kontrol=BUGUN + " UTC", sayi=say, kapali_24saat=[k["ad"] for k in kapali_kanallar], kanallar=ozet),
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nAçık {say['acik']}, belirsiz (yurt dışına kapalı olabilir) {say['belirsiz']}, kapalı {say['kapali']}, "
          f"yeni adres bulundu {say['yenilendi']}; 24 saattir kapalı ve adresi bulunamayan: {len(kapali_kanallar)}", flush=True)
    github_bildir(kapali_kanallar)


if __name__ == "__main__":
    main()
