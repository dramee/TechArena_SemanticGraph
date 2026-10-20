import sys, os, json, copy, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import lib
from values import *
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json('scenarios/S1.json'); S['steps']=S['steps'][:2]
    om = lib.set_method
    def sm(it, s, n, a, fr):
        before = len(s)
        r = om(it, s, n, a, fr)
        if n in ('removeAll','remove','add','addAll') and fr and fr.method and fr.method.name=='queryForTravels':
            print('SET', n, [str(x)[:80] for x in a], before, '->', len(s), 'ret', r)
        return r
    lib.set_method = sm
    it, cl, errors = run_scenario(proj, tables0, S)
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
