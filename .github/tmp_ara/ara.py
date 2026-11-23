import json, urllib.request, urllib.parse
d=json.load(open('canlitv/diziler.json')); f=json.load(open('canlitv/filmler.json'))
K=d['apiKey']
mevcut=set()
for k in d['kanallar']:
    for y in (k.get('youtube') or []): mevcut.add(y)
for k in f['kanallar']: mevcut.add(k['src'])
def api(p,**q):
    q['key']=K
    return json.load(urllib.request.urlopen('https://www.googleapis.com/youtube/v3/'+p+'?'+urllib.parse.urlencode(q)))
# mevcut handle/user -> ID
ids=set(x for x in mevcut if x.startswith('UC'))
for x in mevcut:
    try:
        if x.startswith('@'): r=api('channels',part='id',forHandle=x)
        elif x.startswith('user:'): r=api('channels',part='id',forUsername=x[5:])
        else: continue
        for i in r.get('items',[]): ids.add(i['id'])
    except Exception as e: print('ERR',x,e)
gruplar={
 'CIZGI':['çizgi film resmi kanal','Türkçe çizgi film official','Peppa Pig Türkçe','Bluey Türkçe','Paw Patrol Türkçe','Maşa ile Koca Ayı','Pepee','Rafadan Tayfa','Niloya','Kral Şakir','Caillou Türkçe','Barbie Türkçe','Ninjago Türkçe','Tom ve Jerry Türkçe','Pokemon Türkçe','Miraculous Türkçe','Cocomelon Türkçe','Smurfs Şirinler Türkçe','Larva Türkçe','Robocar Poli Türkçe','Pororo Türkçe','Oddbods Türkçe','Mansur Kardeşler','Akıllı Tavşan Momo','Elif ve Arkadaşları','Grizzy ve Lemmings Türkçe','Sonic Türkçe','Transformers Türkçe','Thomas ve Arkadaşları Türkçe','Baby Shark Türkçe'],
 'FILM':['yerli film full izle resmi','Türk filmi tek parça resmi kanal','komedi filmi full HD yerli','Yeşilçam filmleri resmi','yerli film yapım şirketi'],
 'SPOR':['maç özetleri resmi','Süper Lig maç özeti','TFF 1. Lig özet','Basketbol Süper Ligi özet','Sultanlar Ligi maç özeti','Formula 1 Türkçe','UEFA Türkçe özet','hentbol süper lig']}
for g,qs in gruplar.items():
    print('=====',g)
    gor={}
    for q in qs:
        try: r=api('search',part='snippet',type='channel',q=q,maxResults=8,regionCode='TR',relevanceLanguage='tr')
        except Exception as e: print('ERR',q,e); continue
        for it in r['items']:
            c=it['snippet']['channelId']
            if c not in ids: gor.setdefault(c,q)
    cl=list(gor)
    for i in range(0,len(cl),50):
        r=api('channels',part='snippet,statistics',id=','.join(cl[i:i+50]))
        for it in sorted(r['items'],key=lambda x:-int(x['statistics'].get('subscriberCount',0))):
            s=it['snippet']; st=it['statistics']
            subs=int(st.get('subscriberCount',0))
            if subs<50000: continue
            print(f"{it['id']} | {s['title']} | {s.get('customUrl','')} | abone={subs} | video={st.get('videoCount')} | ulke={s.get('country','')} | q={gor[it['id']]} | {s.get('description','')[:120].replace(chr(10),' ')}")
