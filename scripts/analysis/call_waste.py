"""How the 28 calls are spent: repeats, re-reads of already seen line ranges, calls redone after a compaction."""
import json, sys, re, collections, statistics as st
from pathlib import Path
ROOT = Path('/Users/alex_ust/Desktop/Gemma_kaggle')
def cat(r):
    if r['resolved']: return 'S'
    to = bool(r.get('error')) and 'timeout' in str(r['error'])
    if r['agent_patch_size'] == 0: return 'T' if to else 'E'
    return 't' if to else 'W'
agg = collections.defaultdict(list)
for d in sys.argv[1:]:
    res = {r['instance_id']: r for r in map(json.loads, next((ROOT/'runs'/d).rglob('task_results.jsonl')).read_text().splitlines())}
    for tp in sorted((ROOT/'runs'/d).rglob('trace_*.json')):
        task = tp.stem[6:]
        if task not in res: continue
        seen = set(); ranges = collections.defaultdict(list); lastp = None
        n = dup = reread = aftercomp_dup = 0; comp_at = []; reads = greps = 0; lines_read = 0; tok_out = 0; whole = 0
        compacted = False
        for s in json.load(open(tp))['steps']:
            if s['source'] != 'agent': continue
            p = (s.get('metrics') or {}).get('prompt_tokens')
            if lastp and p and p < lastp - 2000: compacted = True; comp_at.append(n)
            lastp = p or lastp
            if not s.get('tool_calls'): continue
            tc = s['tool_calls'][0]; name = tc.get('function_name'); a = tc.get('arguments') or {}
            if name in ('get_status', 'submit_patch'): continue
            n += 1
            if n > 28: continue
            key = name + json.dumps(a, sort_keys=True)
            isdup = key in seen; seen.add(key)
            if name == 'read_file':
                reads += 1
                f = a.get('filepath'); lo = a.get('start_line') or 1; hi = a.get('end_line') or lo + 149
                if a.get('start_line') is None: whole += 1
                new = set(range(lo, hi + 1)); old = set().union(*ranges[f]) if ranges[f] else set()
                if len(new & old) >= 0.6 * len(new): reread += 1; isdup = True
                ranges[f].append(new); lines_read += len(new)
            elif 'grep' in a.get('command', ''): greps += 1
            if isdup:
                dup += 1
                if compacted: aftercomp_dup += 1
        agg[cat(res[task])].append((n, dup, aftercomp_dup, reads, greps, whole, lines_read, comp_at[0] if comp_at else None))
print('class  n  calls  redundant  of-which-after-compaction  read_file  grep  reads-without-range  lines-read  first-compaction-call(median)  compacted-share')
for k in 'SWEtT':
    v = agg[k]
    if not v: continue
    f = lambda i: st.mean(x[i] for x in v)
    ca = [x[7] for x in v if x[7] is not None]
    print(f'{k:5s} {len(v):3d} {min(f(0),99):6.1f} {f(1):9.2f} {f(2):12.2f} {f(3):18.1f} {f(4):6.1f} {f(5):10.2f} {f(6):14.0f} {st.median(ca) if ca else None!s:>14} {len(ca)/len(v):16.0%}')
