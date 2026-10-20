import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from driver import *
proj, it = build()
w = it.web
rows = []
for module, hs in sorted(w.handlers.items()):
    for v, tpl, mi, ci in hs:
        rows.append((module.replace('ts-','').replace('-service',''), v or '*', '/'+'/'.join(tpl), ci.name+'#'+mi.name))
for r in rows: print(*r, sep=' | ')
