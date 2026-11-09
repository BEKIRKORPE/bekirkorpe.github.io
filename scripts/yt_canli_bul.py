#!/usr/bin/env python3
"""Tek seferlik: kanalların resmî YouTube hesabını ve şu an canlı yayın yapıp yapmadığını bulur."""
import json, os, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = json.load(open(os.path.join(ROOT, "canlitv", "diziler.json"), encoding="utf-8"))["apiKey"]
def get(path, **p):
    p["key"] = KEY
    try:
        return json.load(urllib.request.urlopen("https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode(p), timeout=30))
    except Exception as e:
        return {"hata": str(e)}
ADAY = {
 "Akit TV": ["@akittv", "@AkitTVResmi", "@yeniakittv"], "TGRT Avrupa": ["@tgrteu", "@tgrtavrupa"], "TGRT Haber": ["@tgrthaber"],
 "Bursa TV": ["@bursatv", "@bursatvresmi"], "İBB TV": ["@ibbtv", "@ibbistanbul", "@ibbwebtv"], "TV100": ["@tv100", "@tv100com"],
 "Tele1": ["@tele1comtr", "@tele1tv", "@tele1"], "Kardelen TV": ["@kardelentv"], "Gonca TV": ["@goncatv"], "Deha TV": ["@dehatv"], "Nora TV": ["@noratv"],
}
out = {}
for ad, hs in ADAY.items():
    bul = []
    for h in hs:
        r = get("channels", part="snippet,statistics", forHandle=h)
        for it in r.get("items", []):
            bul.append((it["id"], it["snippet"]["title"], it["snippet"].get("customUrl"), it["statistics"].get("subscriberCount")))
    if not bul:
        r = get("search", part="snippet", q=ad + " canlı yayın", type="channel", maxResults=3, regionCode="TR")
        for it in r.get("items", []):
            bul.append((it["snippet"]["channelId"], it["snippet"]["title"], "arama", ""))
    out[ad] = []
    for cid, t, cu, sub in dict.fromkeys(bul):
        r = get("search", part="snippet", channelId=cid, eventType="live", type="video", maxResults=3)
        canli = [(x["id"]["videoId"], x["snippet"]["title"][:60]) for x in r.get("items", [])]
        out[ad].append(dict(id=cid, ad=t, url=cu, abone=sub, canli=canli))
        print(f"{ad:12} | {cid} | {t} | {cu} | abone {sub} | CANLI: {canli}", flush=True)
json.dump(out, open(os.path.join(ROOT, "scripts", "yt_canli.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
