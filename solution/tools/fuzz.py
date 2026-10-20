"""Прогон всех обработчиков с типовыми аргументами: ищем падения интерпретатора (не Java-исключения)."""
import sys, os, json, copy, threading, traceback, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from solve import *
import interp as I
import web as W
from values import *
def main():
    proj = Project('skeleton/trainticket.json.gz', 'targets/trainticket')
    tables0 = dbm.parse_dump('context/db-after-warmup.sql.gz')
    uid = '4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f'
    fails = collections.Counter(); examples = {}
    tables = copy.deepcopy(tables0)
    it = I.Interp(proj, tables); Repos(it); web = Web(it)
    web.enforce_auth = False
    n = 0
    for module in sorted(web.handlers):
        for verb, tpl, mi, ci in web.handlers[module]:
            if verb is None: verb = 'GET'
            pv = {}
            for s in tpl:
                if s.startswith('{'): pv[s[1:-1].split(':')[0]] = uid if 'ccount' in s or 'user' in s.lower() else 'D1345' if 'trip' in s.lower() else 'shanghai'
            path = '/' + '/'.join(pv.get(s[1:-1].split(':')[0], s) if s.startswith('{') else s for s in tpl)
            it.trace = I.Trace(); it.fuel = 400000
            try:
                web.serve(module, mi, ci, pv, {}, JMap(), None, LibObj('HttpHeaders', map=JMap()), path, verb)
                n += 1
            except I.OutOfFuel:
                fails['OutOfFuel ' + mi.cls.name + '#' + mi.name] += 1
            except Exception as e:
                key = f"{type(e).__name__}: {str(e)[:80]} @ {mi.cls.name}#{mi.name}"
                fails[key] += 1
                if key not in examples: examples[key] = (getattr(e, '_where', None), traceback.format_exc(limit=-2)[-300:])
    print('handlers run', n)
    for k, c in fails.most_common(60):
        print(c, k); print('     ', examples.get(k, ('',))[0])
th = threading.Thread(target=main); threading.stack_size(64*1024*1024); th = threading.Thread(target=main); th.start(); th.join()
