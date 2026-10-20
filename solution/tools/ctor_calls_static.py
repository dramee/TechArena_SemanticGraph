"""Классы проекта, чьи конструкторы / инициализаторы полей содержат вызовы (статический обзор)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from model import *
from model import _walk_names
proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
for ci in proj.classes_list() if hasattr(proj,'classes_list') else []:
    pass
seen = set()
for mid, mi in proj.methods_by_id.items():
    if mi.ctor:
        names = set(); 
        if mi.decl.body is not None: _walk_names(mi.decl.body, names)
        if names:
            print(mid.split(':',2)[2], sorted(names)[:8])
