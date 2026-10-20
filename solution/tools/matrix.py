"""Матрица IoU по видам связей из баллов диагностических сдач."""
import json, sys
base=[0.934,0.943,0.940,0.935,0.937,0.942,0.940]
A=[0.684,0.704,0.716,0.708,0.687,0.706,0.718]
B=[0.713,0.713,0.690,0.699,0.716,0.710,0.690]
C=[0.697,0.693,0.713,0.712,0.702,0.692,0.701]
plans={'A':{1:'R',2:'C',3:'D',4:'E',5:'R',6:'C',7:'D'},'B':{1:'D',2:'E',3:'R',4:'C',5:'D',6:'E',7:'R'},'C':{1:'C',2:'R',3:'E',4:'D',5:'C',6:'R',7:'C'}}
vals={'A':A,'B':B,'C':C}
M={i:{} for i in range(1,8)}
for k,pl in plans.items():
    for i,r in pl.items(): M[i][r]=4*(base[i-1]-vals[k][i-1])
for i in range(1,8):
    rest=4*base[i-1]-sum(M[i].values()); miss=[r for r in 'ECRD' if r not in M[i]][0]; M[i][miss]=rest
sub=json.load(open('submission.json'))['scenarios']
print('IoU по видам и размеры наших множеств; n_extra = столько рёбер, если ошибки только лишние (G/P)')
for i in range(1,8):
    e=sub[f'S{i}']['edges']
    n={r:sum(1 for x in e if x['relation']==rel) for r,rel in zip('ECRD',['executes','calls','remote','data'])}
    print(f"S{i}: E={M[i]['E']:.3f} C={M[i]['C']:.3f} R={M[i]['R']:.3f} D={M[i]['D']:.3f}  | размеры {n} | ~diff E {n['E']*(1/M[i]['E']-1):.0f}, C {n['C']*(1/M[i]['C']-1):.0f}, D {n['D']*(1/M[i]['D']-1):.0f}")
for i in range(1,8):
    e=sub[f'S{i}']['edges']
    to_init=sum(1 for x in e if x['relation']=='calls' and '#<init>' in x['target'])
    from_init=sum(1 for x in e if x['relation']=='calls' and '#<init>' in x['source'])
    ex_init=sum(1 for x in e if x['relation']=='executes' and '#<init>' in x['target'])
    routes=sum(1 for x in e if x['relation']=='data' and ('route_stations' in x['target'] or 'route_distances' in x['target']))
    coll=sum(1 for x in e if x['relation']=='data' and any(t in x['target'] for t in ('user_roles','train_food_list','station_food_list','food_delivery_order_food_list')))
    print(f"S{i}: calls->init {to_init}, calls from init {from_init}, executes init {ex_init}; data route_* {routes}, other coll {coll}")
