#!/usr/bin/env python3
"""Tek seferlik: scripts/adaylar.json'daki olası yeni yayın adreslerini GitHub sunucusundan dener, sonucu yazar.
Ayrıca kanalın sitesini tarayıcıda açıp oynatıcının istediği adresi yakalar (kanal_kontrol.tarayici_ile)."""
import importlib.util, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("k", os.path.join(ROOT, "scripts", "kanal_kontrol.py"))
k = importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
aday = json.load(open(os.path.join(ROOT, "scripts", "adaylar.json"), encoding="utf-8"))
sonuc = {}
for ad, urls in aday.items():
    site = k.tarayici_ile(ad)
    print(f"== {ad} | sitede: {site[:3]}", flush=True)
    sonuc[ad] = []
    for u in list(dict.fromkeys(site + urls)):
        d = k.dene(u)
        print(f"   {d[0]:9} {d[1][:70]:70} {u}", flush=True)
        sonuc[ad].append(dict(url=u, durum=d[0], neden=d[1], sitede=u in site))
json.dump(sonuc, open(os.path.join(ROOT, "scripts", "aday_sonuc.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
