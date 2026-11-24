import json, urllib.request, urllib.parse
d=json.load(open('canlitv/diziler.json')); f=json.load(open('canlitv/filmler.json'))
K=d['apiKey']
def api(p,**q):
    q['key']=K
    return json.load(urllib.request.urlopen('https://www.googleapis.com/youtube/v3/'+p+'?'+urllib.parse.urlencode(q)))
mevcut=set()
for k in d['kanallar']:
    y=k.get('youtube') or []
    if isinstance(y,str): y=[y]
    mevcut.update(y)
for k in f['kanallar']: mevcut.add(k['src'])
ids=set(x for x in mevcut if x.startswith('UC'))
for x in mevcut:
    try:
        if x.startswith('@'): r=api('channels',part='id',forHandle=x)
        elif x.startswith('user:'): r=api('channels',part='id',forUsername=x[5:])
        else: continue
        for i in r.get('items',[]): ids.add(i['id'])
    except Exception as e: print('ERR',x,e)
print('MEVCUT',len(ids))
gruplar={
 'CIZGI':['Pepee resmi','Rafadan Tayfa resmi','Kral Şakir resmi','Maşa ile Koca Ayı Türkçe','Peppa Pig Türkçe resmi','Paw Patrol Türkçe','Bluey Türkçe','Cocomelon Türkçe','Pokemon Türkçe','Miraculous Uğur Böceği Türkçe','Şirinler Türkçe','Larva Türkçe','Robocar Poli Türkçe','Pororo Türkçe','Oddbods Türkçe','Grizzy ve Lemmings','Baby Shark Türkçe','Tayo Türkçe','Super Wings Türkçe','Mansur Kardeşler','İbi çizgi film','Elif ve Arkadaşları','Dede Korkut çizgi film','Kukuli resmi','Bebefinn Türkçe','Pinkfong Türkçe','Leo ve Tig Türkçe','Kiya Türkçe','Masha and the Bear Türkçe','Talking Tom Türkçe','Ben ve Holly Türkçe','Mia ve Ben','Oyuncak Kardeşler','Hakan Mengüç Tarık','Bizim Köy çizgi film'],
 'FILM':['yerli film tek parça resmi kanal','Türk filmi full HD resmi','Yeşilçam film resmi kanal','yerli komedi filmi full izle','film yapım şirketi resmi youtube','Türk sineması restorasyon resmi','Kemal Sunal filmleri resmi','Cüneyt Arkın filmleri resmi','Türkan Şoray filmleri','BKM film'],
 'SPOR':['maç özetleri resmi','Süper Lig özet resmi','Trendyol 1. Lig özet','Basketbol Süper Ligi resmi','Sultanlar Ligi resmi','Efeler Ligi','Hentbol Süper Lig','UEFA Türkiye','Kadın Futbol Süper Ligi','Türkiye Basketbol Ligi','Formula 1 Türkiye','TRT Spor Yıldız','Fenerbahçe resmi','Galatasaray resmi','Beşiktaş resmi','Trabzonspor resmi']}
for g,qs in gruplar.items():
    print('=====',g)
    gor={}
    for q in qs:
        try: r=api('search',part='snippet',type='channel',q=q,maxResults=6,regionCode='TR',relevanceLanguage='tr')
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
