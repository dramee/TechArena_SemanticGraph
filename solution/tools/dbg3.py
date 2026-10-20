import sys, os, json, copy, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
from values import *
def main():
    sid = sys.argv[1]; upto = int(sys.argv[2])
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    S = load_json(f'scenarios/{sid}.json')
    S['steps'] = S['steps'][:upto]
    it, cl, errors = run_scenario(proj, tables0, S)
    print('trips', json.dumps(cl.trips, default=str)[:1500])
    print('trip', cl.trip)
    print('errors', errors[:3])
    for l in cl.log[-3:]: print(l)
    print('exc', it.exc_log[:5])
    print('warn', dict(it.warnings))
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
