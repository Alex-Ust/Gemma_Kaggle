"""Where the session time goes, by outcome class."""
import json, sys, re, collections, statistics as st
from pathlib import Path
ROOT = Path('/Users/alex_ust/Desktop/Gemma_kaggle')
def cat(r):
    if r['resolved']: return 'S'
    to = bool(r.get('error')) and 'timeout' in str(r['error'])
    if r['agent_patch_size'] == 0: return 'T' if to else 'E'
    return 't' if to else 'W'
rows = collections.defaultdict(list)
detail = []
for d in sys.argv[1:]:
    res = {r['instance_id']: r for r in map(json.loads, next((ROOT/'runs'/d).rglob('task_results.jsonl')).read_text().splitlines())}
    for tp in sorted((ROOT/'runs'/d).rglob('trace_*.json')):
        task = tp.stem[6:]
        if task not in res: continue
        prev = None; llm = tool = 0.0; n = 0; ctok = 0; comp = 0; compcost = 0.0; lastp = None; big = 0; bigs = 0.0; first_edit = None
        for s in json.load(open(tp))['steps']:
            el = (s.get('extra') or {}).get('elapsed_s')
            if s['source'] != 'agent' or el is None:
                prev = el; continue
            m = s.get('metrics') or {}
            dt = el - prev if prev is not None else 0
            llm += dt; n += 1; c = m.get('completion_tokens') or 0; ctok += c
            p = m.get('prompt_tokens')
            if lastp and p and p < lastp - 2000: comp += 1; compcost += dt
            lastp = p or lastp
            if c > 1500: big += 1; bigs += dt
            cmd = json.dumps(s.get('tool_calls') or '')
            if first_edit is None and ('write_text' in cmd or "cat >" in cmd and '/tmp' not in cmd): first_edit = (n, round(el))
            oe = el
            if s.get('observation'):
                mm = re.findall(r'"elapsed_s": ([0-9.]+)', json.dumps(s['observation']))
                if mm: oe = float(mm[-1])
            tool += oe - el; prev = oe
        k = cat(res[task])
        rows[k].append((llm, tool, n, ctok, comp, compcost, big, bigs, first_edit[1] if first_edit else None))
        if k in 'Tt': detail.append((d[-12:], task, k, round(llm), round(tool), n, ctok, comp, round(compcost), big, round(bigs), first_edit))
print('class  n   llm_s  tool_s  steps  ctok   s/step  compactions  comp_s  big_calls  big_s  first_edit_s(median)')
for k in 'SWEtT':
    v = rows[k]
    if not v: continue
    f = lambda i: st.mean(x[i] for x in v)
    fe = [x[8] for x in v if x[8] is not None]
    print(f'{k:5s} {len(v):3d}  {f(0):6.0f} {f(1):6.0f} {f(2):6.1f} {f(3):6.0f} {f(0)/f(2):6.1f} {f(4):8.2f} {f(5):10.0f} {f(6):8.2f} {f(7):7.0f}   {st.median(fe) if fe else None} (edited {len(fe)}/{len(v)})')
print('\ntimed-out tasks: run task class llm tool steps ctok compactions comp_s big_calls big_s first_edit(step,s)')
for x in detail: print('  ', *x)
