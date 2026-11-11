#!/usr/bin/env python3
"""
Canlı TV — yabancı ülke kanalları kontrolü (8 saatte bir, kanal kontrolünden sonra).

Bekir: "Azerbaycan, Özbekistan, Rusya kanallarında eksik / çalışmayan olmasın."
- Bu ülkelerin kanalları uygulamaya herkese açık iptv-org listesinden geliyor; çoğu zaman bir kısmı ölü.
- Her kanalın bütün adresleri denenir. BÜTÜN adresleri kesin kapalıysa (adres yok, sunucu yok, yayın değil)
  kanal canlitv/kanallar.m3u'nun sonundaki "Dünya: kapalı" bölümüne "#KAPALI|" satırı olarak yazılır →
  uygulama (V5.8+) o kanalı listede göstermez. Kanal yeniden açılınca satır kendiliğinden silinir.
- Türkiye kanalları bu betikte YOK (onlar asla gizlenmez; kanal_kontrol.py yeni adres arar).
- Sunucu yurt dışında (ABD): cevap vermeyen / 403 veren adres "belirsiz" sayılır, gizlenmez.
"""
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M3U = os.path.join(ROOT, "canlitv", "kanallar.m3u")
OUT = os.path.join(ROOT, "canlitv", "dunya_durum.json")
ULKELER = {"az": "Azerbaycan", "uz": "Özbekistan", "ru": "Rusya", "kz": "Kazakistan", "tm": "Türkmenistan", "kg": "Kırgızistan"}
BAS, SON = "# --- Dünya: kapalı (dunya_kontrol.py yazar, elle düzenlemeyin) ---", "# --- Dünya: kapalı sonu ---"

spec = importlib.util.spec_from_file_location("k", os.path.join(ROOT, "scripts", "kanal_kontrol.py"))
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)


def liste(kod):
    for u in (f"https://iptv-org.github.io/iptv/countries/{kod}.m3u",
              f"https://raw.githubusercontent.com/iptv-org/iptv/gh-pages/countries/{kod}.m3u"):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": k.UA}), timeout=30).read().decode("utf-8", "ignore")
        except Exception:
            continue
    return ""


def anahtar(extinf):
    m = re.search(r'tvg-id="([^"]*)"', extinf)
    tid = (m.group(1) if m else "").split("@")[0].strip()
    if tid:
        return tid.lower()
    ad = extinf.rsplit(",", 1)[-1]
    return re.sub(r"[^A-Za-z0-9ÇĞİÖŞÜçğıöşü]", "", re.sub(r"\([^)]*\)", "", ad)).lower()


def main():
    kanallar = {}          # anahtar → {extinf, ulke, urls}
    for kod, ad in ULKELER.items():
        ext = None
        for l in liste(kod).splitlines():
            l = l.strip()
            if l.startswith("#EXTINF"):
                ext = l
            elif l and not l.startswith("#") and ext:
                kk = kod + ":" + anahtar(ext)
                kanallar.setdefault(kk, dict(extinf=ext, ulke=ad, urls=[]))["urls"].append(l)
                ext = None
    urls = sorted({u for v in kanallar.values() for u in v["urls"]})
    print(f"{len(kanallar)} kanal, {len(urls)} adres deneniyor", flush=True)
    with ThreadPoolExecutor(24) as ex:
        sonuc = dict(zip(urls, ex.map(lambda u: k.dene(u), urls)))
    kapali, ozet = [], {}
    for kk, v in kanallar.items():
        durumlar = [sonuc[u][0] for u in v["urls"]]
        o = ozet.setdefault(v["ulke"], dict(acik=0, belirsiz=0, kapali=0))
        if "ok" in durumlar:
            o["acik"] += 1
        elif "belirsiz" in durumlar or any("zaman aşımı" in sonuc[u][1] for u in v["urls"]):
            o["belirsiz"] += 1
        else:
            o["kapali"] += 1
            kapali.append(v)
    for u, o in ozet.items():
        print(f"{u}: açık {o['acik']}, belirsiz {o['belirsiz']}, kapalı (gizlenecek) {o['kapali']}", flush=True)

    # kanallar.m3u'nun sonundaki bölümü yeniden yaz
    metin = open(M3U, encoding="utf-8").read()
    metin = re.sub(re.escape(BAS) + r".*?" + re.escape(SON) + r"\n?", "", metin, flags=re.S).rstrip("\n") + "\n"
    if kapali:
        satir = [BAS]
        for v in sorted(kapali, key=lambda v: (v["ulke"], v["extinf"].rsplit(",", 1)[-1])):
            satir.append("#KAPALI|" + v["extinf"])
            satir.append("#KAPALI|" + v["urls"][0])
        satir.append(SON)
        metin += "\n".join(satir) + "\n"
    open(M3U, "w", encoding="utf-8").write(metin)
    json.dump(dict(kontrol=k.BUGUN + " UTC", ulkeler=ozet,
                   kapali=[dict(ulke=v["ulke"], ad=v["extinf"].rsplit(",", 1)[-1].strip()) for v in kapali]),
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
