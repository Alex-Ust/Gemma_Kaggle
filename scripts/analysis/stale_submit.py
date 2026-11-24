"""Runs where a successful edit comes after the last submit_patch (the harness grades the last submission
and skips the working-tree fallback once any submit_patch was made), and runs whose first submit was empty.

Usage: python scripts/analysis/stale_submit.py <run-dir-name> ...
"""
import json, re, sys, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
tot = collections.Counter()
for d in sys.argv[1:]:
    res = {r['instance_id']: r for r in map(json.loads, next((ROOT / 'runs' / d).rglob('task_results.jsonl')).read_text().splitlines())}
    for tp in sorted((ROOT / 'runs' / d).rglob('trace_*.json')):
        task = tp.stem[6:]
        if task not in res: continue
        r = res[task]; seq = ''; sizes = []
        for s in json.load(open(tp))['steps']:
            if s['source'] != 'agent' or not s.get('tool_calls'): continue
            tc = s['tool_calls'][0]
            nm = tc.get('function_name') or tc.get('name')
            cmd = (tc.get('arguments') or {}).get('command', '') if nm == 'run_command' else ''
            obs = json.dumps(s.get('observation') or '')
            if nm == 'submit_patch':
                m = re.search(r'patch_size\\*"?: ?(\d+)', obs)
                sizes.append(int(m.group(1)) if m else -1); seq += 'P'
            elif ('write_text' in cmd or re.search(r'cat > (?!/tmp)', cmd)) and 'edited' in obs and 'AssertionError' not in obs and 'BudgetExceeded' not in obs:
                seq += 'E'
            elif 'git checkout' in cmd or 'git stash' in cmd or 'git restore' in cmd: seq += 'R'
            else: seq += '.'
        tot['runs'] += 1
        if 'P' not in seq: 
            tot['no submit'] += 1
            if 'E' in seq: tot['no submit, edited (fallback path)'] += 1
            continue
        tail = seq[seq.rindex('P') + 1:]
        if sizes and sizes[0] == 0: tot['first submit empty'] += 1
        if 'E' in tail or 'R' in tail:
            tot['edit/revert after last submit'] += 1
            tot['  of them resolved'] += r['resolved']
            to = 'timeout' in str(r.get('error') or '')
            print(f"{d[-12:]:12s} {task:15s} {'S' if r['resolved'] else '-'} {'TO' if to else '  '} graded {r['agent_patch_size']:5d} submits {sizes} tail {tail!r}")
print(dict(tot))
