"""Durations of run_command calls: successful vs timed out; time lost to timeouts per task."""
import json, sys, re, collections
from pathlib import Path
ROOT = Path('/Users/alex_ust/Desktop/Gemma_kaggle')
ok = []; to = collections.defaultdict(list); big = []
nruns = 0
for d in sys.argv[1:]:
    nruns += 1
    res = {r['instance_id']: r for r in map(json.loads, next((ROOT/'runs'/d).rglob('task_results.jsonl')).read_text().splitlines())}
    for tp in sorted((ROOT/'runs'/d).rglob('trace_*.json')):
        task = tp.stem[6:]
        for s in json.load(open(tp))['steps']:
            if s['source'] != 'agent' or not s.get('tool_calls') or not s.get('observation'): continue
            el = (s.get('extra') or {}).get('elapsed_s')
            txt = json.dumps(s['observation'])
            mm = re.findall(r'"elapsed_s": ([0-9.]+)', txt)
            if not mm or el is None: continue
            dur = float(mm[-1]) - el
            tc = s['tool_calls'][0]
            if (tc.get('function_name') or tc.get('name')) != 'run_command': continue
            cmd = (tc.get('arguments') or {}).get('command', '')
            if 'TimeoutExceeded' in txt:
                to[(d, task, res[task]['resolved'])].append(round(dur))
            else:
                ok.append(dur)
                if dur > 8: big.append((round(dur, 1), d, task, cmd[:120].replace('\n', ' ')))
ok.sort()
q = lambda p: ok[int(p * (len(ok) - 1))]
print(f'runs {nruns}; successful run_command calls {len(ok)}: p50 {q(.5):.2f}s p95 {q(.95):.2f}s p99 {q(.99):.2f}s p99.9 {q(.999):.2f}s max {ok[-1]:.1f}s')
for th in (5, 10, 15, 20, 30, 45, 60): print(f'   > {th:2d}s: {sum(x > th for x in ok)}')
print('longest successful:'); [print('  ', *b) for b in sorted(big, reverse=True)[:14]]
print(f'tasks with a timed-out command: {len(to)} ({len(to)/nruns:.1f} per run); seconds lost per task:')
by = collections.defaultdict(list)
for (d, task, r), v in sorted(to.items()): by[task].append((sum(v), 'S' if r else '-'))
for task, v in sorted(by.items()): print(f'   {task:16s} runs {len(v)}  lost {[x[0] for x in v]}  outcome {"".join(x[1] for x in v)}')
