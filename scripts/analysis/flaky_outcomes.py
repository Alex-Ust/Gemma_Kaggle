import json, sys, collections
from pathlib import Path
ROOT = Path('/Users/alex_ust/Desktop/Gemma_kaggle')
ids = json.loads((ROOT/'data/task_sets.json').read_text())['flaky25']
arms = {'v34': 'v34-noedit-l4c2 v34-noedit-l4c2b v34-noedit-flaky-p3 v34-noedit-flaky-p4 v34-noedit-flaky-p5 v34-noedit-flaky-p6 v34-noedit-flaky-p7'.split(),
        'v40': 'v40-pin-flaky-p1 v40-pin-flaky-p2 v40-pin-flaky-p3 v40-pin-l4c2 v40-pin-flaky-p4 v40-pin-flaky-p5'.split()}
def cat(r):
    if r['resolved']: return 'S'
    to = bool(r.get('error')) and 'timeout' in str(r['error'])
    if r['agent_patch_size'] == 0: return 'T' if to else 'E'
    return 't' if to else 'W'
tot = collections.Counter()
for arm, runs in arms.items():
    rows = []
    for d in runs:
        p = next((ROOT/'runs'/d).rglob('task_results.jsonl'))
        rows.append({r['instance_id']: r for r in map(json.loads, p.read_text().splitlines())})
    print(arm)
    c = collections.Counter()
    for i in ids:
        s = ''.join(cat(r[i]) for r in rows)
        c.update(s)
        print(f'  {i:16s} {s}   calls {[r[i]["tool_calls"] for r in rows]}')
    print('  totals', dict(c), 'per pass', {k: round(v/len(runs),1) for k,v in c.items()})
