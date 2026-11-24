"""Edit attempts per task: ok / assert failed / budget exceeded / other error; by outcome class."""
import json, sys, re, collections
from pathlib import Path
ROOT = Path('/Users/alex_ust/Desktop/Gemma_kaggle')
def cat(r):
    if r['resolved']: return 'S'
    to = bool(r.get('error')) and 'timeout' in str(r['error'])
    if r['agent_patch_size'] == 0: return 'T' if to else 'E'
    return 't' if to else 'W'
agg = collections.defaultdict(collections.Counter); ntask = collections.Counter(); lines = []
for d in sys.argv[1:]:
    res = {r['instance_id']: r for r in map(json.loads, next((ROOT/'runs'/d).rglob('task_results.jsonl')).read_text().splitlines())}
    for tp in sorted((ROOT/'runs'/d).rglob('trace_*.json')):
        task = tp.stem[6:]
        if task not in res: continue
        k = cat(res[task]); ntask[k] += 1
        seq = ''; ncall = 0
        for s in json.load(open(tp))['steps']:
            if s['source'] != 'agent' or not s.get('tool_calls'): continue
            ncall += 1
            tc = s['tool_calls'][0]
            name = tc.get('function_name') or tc.get('name')
            cmd = (tc.get('arguments') or {}).get('command', '') if name == 'run_command' else ''
            obs = json.dumps(s.get('observation') or '')
            is_edit = 'write_text' in cmd or (re.search(r'cat > (?!/tmp)', cmd) is not None)
            if 'BudgetExceeded' in obs or 'budget' in obs.lower() and 'exceeded' in obs.lower():
                c = 'B' if is_edit else 'b'
            elif is_edit:
                if 'edited' in obs and 'AssertionError' not in obs: c = 'E'
                elif 'AssertionError' in obs: c = 'a'
                elif 'Timeout' in obs: c = 'x'
                else: c = '?' if 'error' in obs.lower()[:200] else 'E'
            elif 'git checkout' in cmd or 'git stash' in cmd or 'git restore' in cmd: c = 'R'
            elif name == 'submit_patch': c = 'P'
            elif 'pytest' in cmd or 'unittest' in cmd: c = 't'
            else: c = '.'
            seq += c
        for ch in seq: agg[k][ch] += 1
        if k in 'ET': lines.append(f'{d[-9:]:9s} {task:15s} {k} {seq}')
print('legend: . read/search  t test  E edit ok  a edit assert failed  ? edit other error  x edit timeout  B edit after budget  b other call after budget  R git revert  P submit')
for k in 'SWEtT':
    n = ntask[k]
    if n: print(k, n, {c: round(v / n, 2) for c, v in sorted(agg[k].items())})
print(); print('\n'.join(lines))
