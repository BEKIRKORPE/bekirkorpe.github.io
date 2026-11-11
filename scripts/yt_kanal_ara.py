import json, os, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = json.load(open(os.path.join(ROOT, "canlitv", "diziler.json"), encoding="utf-8"))
KEY = D["apiKey"]
def get(path, **p):
    p["key"] = KEY
    try: return json.load(urllib.request.urlopen("https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode(p), timeout=30))
    except Exception as e: return {"hata": str(e)}
def show(tag, it):
    s = it["snippet"]; st = it["statistics"]
    print(f"{tag:28} | {it['id']} | {s['title'][:40]} | {s.get('customUrl')} | {s.get('country')} | abone {st.get('subscriberCount')} | video {st.get('videoCount')}")
mevcut = [y for k in D["kanallar"] if k.get("tur") == "cizgi" for y in k["youtube"] if y.startswith("UC")]
c = get("channels", part="snippet,statistics", id=",".join(mevcut[:50]))
for it in c.get("items", []): show("MEVCUT", it)
Q = ["Sünger Bob Türkçe", "Tom ve Jerry Türkçe", "Cocomelon Türkçe", "Caillou Türkçe", "Leliko resmi", "Kukuli resmi", "Pırıl resmi",
     "Akıllı Tavşan Momo", "Keloğlan Masalları", "Robocar Poli Türkçe", "Pinkfong Türkçe", "Oddbods Türkçe", "Larva Türkçe",
     "Disney Junior Türkiye", "Cartoon Network Türkiye", "Minika Çocuk", "LEGO Türkiye", "Gecko's Garage Türkçe", "Ben ve Holly Türkçe",
     "Pokemon Türkiye resmi",
     "FILM:Bir Film yerli film", "FILM:Plato Film", "FILM:BKM", "FILM:TAFF Pictures", "FILM:yerli film resmi kanal tam film",
     "SPOR:TFF resmi", "SPOR:Trendyol Süper Lig resmi", "SPOR:Galatasaray resmi", "SPOR:Fenerbahçe resmi", "SPOR:Beşiktaş resmi", "SPOR:Trabzonspor resmi"]
for q in Q:
    qq = q.split(":", 1)[-1]
    r = get("search", part="snippet", q=qq, type="channel", maxResults=4, regionCode="TR")
    ids = [it["snippet"]["channelId"] for it in r.get("items", [])]
    if not ids: print(q, "->", r.get("hata", "yok")); continue
    c = get("channels", part="snippet,statistics", id=",".join(ids))
    for it in c.get("items", []): show(q, it)
