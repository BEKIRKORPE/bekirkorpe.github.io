import json, urllib.request, urllib.parse, re
K=json.load(open('canlitv/diziler.json'))['apiKey']
def api(p,**q):
    q['key']=K
    return json.load(urllib.request.urlopen('https://www.googleapis.com/youtube/v3/'+p+'?'+urllib.parse.urlencode(q)))
def dk(s):
    m=re.match(r'P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?',s or ''); return (int(m.group(1) or 0)*60+int(m.group(2) or 0)) if m else -1
aday=['UCjOweOpke_ZyXyLJNf6n8Xg','UCoe0QD045tgbTE6bsbRGU5w','UCUd3o920A_ijCRaTRRg8LSg','UC-wym_LQCcF_wENbh6x18MQ','UCEqDENJw9VoS_6R5l0mQYzg','UCXXUp-0D44cb7dH6yGbNZeA','UCJhEfZoLs5P_idxX--yhWOA','UCwNFFNp-pS_3jN3e1d6xBWg','UC4CwqqLmC5Y_aHj63Rq3btQ']
r=api('channels',part='snippet,contentDetails,statistics,brandingSettings',id=','.join(aday))
for it in r['items']:
    s=it['snippet']
    print('#####',it['id'],s['title'],it['statistics'].get('subscriberCount'),s.get('publishedAt','')[:10],s.get('country'))
    print('  DESC:',s.get('description','')[:500].replace('\n',' '))
    print('  KW:',it.get('brandingSettings',{}).get('channel',{}).get('keywords','')[:200])
    up=it['contentDetails']['relatedPlaylists']['uploads']
    v=api('playlistItems',part='snippet,contentDetails',playlistId=up,maxResults=25)
    vid=[x['contentDetails']['videoId'] for x in v['items']]
    vv={x['id']:x for x in api('videos',part='contentDetails,statistics',id=','.join(vid))['items']}
    for x in v['items']:
        i=x['contentDetails']['videoId']; d=vv.get(i)
        print('  -',x['snippet']['publishedAt'][:10],(dk(d['contentDetails']['duration']) if d else '?'),'dk',(d['statistics'].get('viewCount') if d else ''),x['snippet']['title'][:90])
    p=api('playlists',part='snippet,contentDetails',channelId=it['id'],maxResults=15)
    print('  PL:',' ; '.join(f"{x['snippet']['title'][:40]}({x['contentDetails']['itemCount']})" for x in p['items']))
for c in ['UCQpeujIamj2ZOKXZnrxTRhA','UCgqlho3-8a6FmDqQm7Q6gJw','UCLJVUlpsxZcIMECVDcZaM2g','UCnZoe1ncVK7ApLBPfpZ_LEA']:
    p=api('playlists',part='snippet,contentDetails',channelId=c,maxResults=25)
    print('CLUB',c,' ; '.join(f"{x['snippet']['title'][:40]}({x['contentDetails']['itemCount']})" for x in p['items']))
