import json, os, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = json.load(open(os.path.join(ROOT, "canlitv", "diziler.json"), encoding="utf-8"))["apiKey"]
def get(path, **p):
    p["key"] = KEY
    try: return json.load(urllib.request.urlopen("https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode(p), timeout=30))
    except Exception as e: return {"hata": str(e)}
for q in ["Kral Şakir resmi", "Peppa Pig Türkçe resmi kanal", "Rafadan Tayfa resmi", "Keloğlan Masalları", "Pepee resmi", "Niloya resmi", "Maşa ile Koca Ayı Türkçe", "Caillou Türkçe", "Akıllı Tavşan Momo", "Kukuli resmi", "Pırıl resmi", "Elif'in Düşleri", "Leliko", "Smurfs Türkçe Şirinler", "Bluey Türkçe", "Paw Patrol Türkçe", "Cocomelon Türkçe", "Sünger Bob Türkçe", "Tom ve Jerry Türkçe", "Barbie Türkçe"]:
    r = get("search", part="snippet", q=q, type="channel", maxResults=3, regionCode="TR")
    ids = [it["snippet"]["channelId"] for it in r.get("items", [])]
    if not ids: print(q, "->", r.get("hata", "yok")); continue
    c = get("channels", part="snippet,statistics", id=",".join(ids))
    for it in c.get("items", []):
        print(f"{q:32} | {it['id']} | {it['snippet']['title'][:40]} | {it['snippet'].get('customUrl')} | abone {it['statistics'].get('subscriberCount')} | video {it['statistics'].get('videoCount')}")
