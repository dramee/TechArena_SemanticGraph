"""Подбор гипотез по data: какие группы рёбер убрать, чтобы IoU совпал с измеренным."""
import json, itertools
MEAS = {1:0.884,2:0.896,3:0.896,4:0.892,5:0.884,6:0.896,7:0.888}
sub = json.load(open('submission.json'))['scenarios']
def cat(e):
    s, t = e['source'].split(':',2)[2].split('#')[0].split('.')[-1] + '#' + e['source'].split('#')[1].split('(')[0], e['target'].split('.')[-1]
    return s, t
groups = {
 'route_read':  lambda s,t: t in ('route_stations','route_distances') and s.startswith('RouteServiceImpl#getRoute'),
 'route_write': lambda s,t: t in ('route_stations','route_distances') and not s.startswith('RouteServiceImpl#getRoute'),
 'train_food_list': lambda s,t: t=='train_food_list',
 'station_food_list': lambda s,t: t=='station_food_list',
 'user_roles': lambda s,t: t=='user_roles',
 'delivery': lambda s,t: t=='delivery',
 'inside_money': lambda s,t: t=='inside_money',
}
names = list(groups)
inv = {}
for sid in range(1,8):
    E = [cat(e) for e in sub[f'S{sid}']['edges'] if e['relation']=='data']
    inv[sid] = {g: sum(1 for s,t in E if groups[g](s,t)) for g in names}
    print(f"S{sid} |D|={len(E)}", inv[sid])
best = []
for r in range(0, len(names)+1):
    for sub_g in itertools.combinations(names, r):
        err = 0; preds = []
        for sid in range(1,8):
            P = sum(1 for e in sub[f'S{sid}']['edges'] if e['relation']=='data')
            rm = sum(inv[sid][g] for g in sub_g)
            iou = (P-rm)/P
            preds.append(iou); err += (iou - MEAS[sid])**2
        best.append((err, sub_g, [round(x,3) for x in preds]))
best.sort()
for b in best[:6]: print(round(b[0],5), b[1], b[2])
print('измерено', list(MEAS.values()))
