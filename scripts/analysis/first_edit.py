"""First successful edit: call index histogram per arm, restricted to a task set.

Usage: python scripts/analysis/first_edit.py [--set flaky25] name=run[,run...] ...
"""
import json, re, sys, statistics as st
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
args = sys.argv[1:]
setname = 'flaky25'
if args[0] == '--set': setname = args[1]; args = args[2:]
ids = set(json.loads((ROOT / 'data/task_sets.json').read_text())[setname])
BINS = [(1, 8), (9, 12), (13, 18), (19, 24), (25, 28), (29, 34)]
print('arm'.ljust(8) + 'runs  ' + ''.join(f'{a}-{b}'.ljust(8) for a, b in BINS) + 'none    lateB   median  calls')
for spec in args:
    name, dirs = spec.split('=')
    hist = [0] * len(BINS); none = lateb = n = 0; firsts = []; ncalls = []
    nruns = 0
    for d in dirs.split(','):
        tps = sorted((ROOT / d).rglob('trace_*.json'))
        if not tps: continue
        nruns += 1
        for tp in tps:
            if tp.stem[6:] not in ids: continue
            n += 1; ncall = 0; first = None; b = False
            for s in json.load(open(tp))['steps']:
                if s['source'] != 'agent' or not s.get('tool_calls'): continue
                tc = s['tool_calls'][0]
                nm = tc.get('function_name') or tc.get('name')
                if nm in ('submit_patch', 'get_status'): continue
                ncall += 1
                cmd = (tc.get('arguments') or {}).get('command', '') if nm == 'run_command' else ''
                obs = json.dumps(s.get('observation') or '')
                is_edit = 'write_text' in cmd or re.search(r'cat > (?!/tmp)', cmd) is not None
                if not is_edit: continue
                if 'BudgetExceeded' in obs: b = True
                elif first is None and 'edited' in obs and 'AssertionError' not in obs: first = ncall
            ncalls.append(ncall)
            if first is None:
                none += 1; lateb += b
            else:
                firsts.append(first)
                for k, (a, z) in enumerate(BINS):
                    if a <= first <= z: hist[k] += 1
    if not nruns: print(name.ljust(8) + 'no finished runs'); continue
    f = lambda x: f'{x / nruns:.1f}'.ljust(8)
    print(name.ljust(8) + f'{nruns}'.ljust(6) + ''.join(f(h) for h in hist) + f(none) + f(lateb)
          + f'{st.median(firsts):.0f}'.ljust(8) + f'{st.mean(ncalls):.1f}')
