import sys, os, json, gzip, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from driver import *
import threading
threading.stack_size(64*1024*1024)

import traceback
def main():
  try:
    main2()
  except Exception:
    traceback.print_exc(limit=-12)

def main2():
    proj, it = build()
    web = it.web
    uid = '4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f'
    reqs = [
      ('POST','/api/v1/users/login', {'username':'fdse_microservice','password':'111111','verificationCode':''}),
      ('GET','/api/v1/contactservice/contacts/account/'+uid, None),
      ('POST','/api/v1/orderservice/order/refresh', {'loginId':uid,'enableStateQuery':False,'enableTravelDateQuery':False,'enableBoughtDateQuery':False,'travelDateStart':None,'travelDateEnd':None,'boughtDateStart':None,'boughtDateEnd':None,'state':0}),
      ('POST','/api/v1/orderOtherService/orderOther/refresh', {'loginId':uid,'enableStateQuery':False,'enableTravelDateQuery':False,'enableBoughtDateQuery':False,'travelDateStart':None,'travelDateEnd':None,'boughtDateStart':None,'boughtDateEnd':None,'state':0}),
      ('POST','/api/v1/orderservice/order/refresh', {'loginId':uid,'enableStateQuery':True,'enableTravelDateQuery':False,'enableBoughtDateQuery':False,'travelDateStart':None,'travelDateEnd':None,'boughtDateStart':None,'boughtDateEnd':None,'state':1}),
      ('POST','/api/v1/orderOtherService/orderOther/refresh', {'loginId':uid,'enableStateQuery':True,'enableTravelDateQuery':False,'enableBoughtDateQuery':False,'travelDateStart':None,'travelDateEnd':None,'boughtDateStart':None,'boughtDateEnd':None,'state':1}),
      ('GET','/api/v1/consignservice/consigns/account/'+uid, None),
    ]
    for v,pth,body in reqs:
        r = entry_request(web, v, pth, JMap(body) if body else None)
        print(v, pth, '->', (r.f['body'] if r else None) if True else '')
    tr = it.trace
    g = json.load(open(os.path.join(ROOT,'gold/S0.json'),encoding='utf-8'))['scenarios']['S0']
    G = {'executes': set(g['methods']), 'calls': {tuple(x) for x in g['calls']}, 'remote': {tuple(x) for x in g['remote']}, 'data': {tuple(x) for x in g['data']}}
    P = {'executes': tr.executes, 'calls': tr.calls, 'remote': tr.remote, 'data': tr.data}
    tot=0
    for k in G:
        inter=len(P[k]&G[k]); uni=len(P[k]|G[k]); j=inter/uni if uni else 1.0; tot+=j
        print(f"{k:9s} IoU {j:.3f} pred {len(P[k])} gold {len(G[k])} tp {inter}")
        for x in sorted(map(str,P[k]-G[k]))[:30]: print('   +', x.replace('method:','')[:200])
        for x in sorted(map(str,G[k]-P[k]))[:30]: print('   -', x.replace('method:','')[:200])
    print('score', tot/4)
    print('warnings', dict(it.warnings))
    print('decisions', it.decisions[:20])

t = threading.Thread(target=main); t.start(); t.join()
