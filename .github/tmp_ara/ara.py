import json, urllib.request, urllib.parse
K=json.load(open('canlitv/diziler.json'))['apiKey']
def api(p,**q):
    q['key']=K
    return json.load(urllib.request.urlopen('https://www.googleapis.com/youtube/v3/'+p+'?'+urllib.parse.urlencode(q)))
aday=['UCgGuCXWCHMf-chlvbQQzoTg','UCtuU4x0P9uhkG-lveoMqLdg','UC7VFEYiNXytUAalXsV559bQ','UCq2sXHHjY9AYkxN93SWtzMQ','UCTGhA386sDm1QoGBUHGyGyA','UCaXP8Tb2QIjk2q3VHyLjD1Q','UCQ-aQK4lA3N1qQrwDWRC9qw','UCjOweOpke_ZyXyLJNf6n8Xg']
r=api('channels',part='snippet,contentDetails,statistics,brandingSettings',id=','.join(aday))
for it in r['items']:
    s=it['snippet']
    print('#####',it['id'],s['title'],it['statistics'].get('subscriberCount'),s.get('publishedAt'))
    print('  DESC:',s.get('description','')[:400].replace('\n',' '))
    up=it['contentDetails']['relatedPlaylists']['uploads']
    v=api('playlistItems',part='snippet',playlistId=up,maxResults=6)
    for x in v['items']: print('  -',x['snippet']['publishedAt'][:10],x['snippet']['title'][:90])
for q in ['Oddbods Türkçe resmi','Zig ve Sharko Türkçe','Larva Türkçe resmi','Kukuli','Aslan çizgi film TRT','Keloğlan Masalları','Pırıl çizgi film','Leliko','Maysa ve Bulut','Kardeşim Ozi']:
    r=api('search',part='snippet',type='channel',q=q,maxResults=4,regionCode='TR')
    ids=[i['snippet']['channelId'] for i in r['items']]
    c=api('channels',part='snippet,statistics',id=','.join(ids))
    for it in c['items']: print('Q',q,'|',it['id'],'|',it['snippet']['title'],'|',it['snippet'].get('customUrl'),'|',it['statistics'].get('subscriberCount'))
