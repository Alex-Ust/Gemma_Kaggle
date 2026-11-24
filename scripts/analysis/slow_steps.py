"""Decompose task time into LLM-call time and tool time; list slow LLM calls and tool timeouts."""
import json, sys, collections
from pathlib import Path
ROOT = Path('/Users/alex_ust/Desktop/Gemma_kaggle')
runs = sys.argv[1:]
allslow = []; alltool = []
for d in runs:
    res = {r['instance_id']: r for r in map(json.loads, next((ROOT/'runs'/d).rglob('task_results.jsonl')).read_text().splitlines())}
    for tp in sorted((ROOT/'runs'/d).rglob('trace_*.json')):
        task = tp.stem[6:]
        t = json.load(open(tp))
        prev_end = None
        for s in t['steps']:
            el = (s.get('extra') or {}).get('elapsed_s')
            if s['source'] != 'agent':
                prev_end = el; continue
            m = s.get('metrics') or {}
            llm = el - prev_end if prev_end is not None and el is not None else None
            obs = s.get('observation')
            oel = None
            if obs:
                # observation may be dict or list
                o = obs if isinstance(obs, dict) else None
                txt = json.dumps(obs)
                try:
                    oel = (obs.get('extra') or {}).get('elapsed_s') if isinstance(obs, dict) else None
                except Exception: oel = None
                if oel is None:
                    import re
                    mm = re.findall(r'"elapsed_s": ([0-9.]+)', txt)
                    oel = float(mm[-1]) if mm else None
            tool = oel - el if oel is not None else None
            call = ''
            for tc in s.get('tool_calls') or []:
                call = (tc.get('function_name') or tc.get('name') or '') + ' ' + json.dumps(tc.get('arguments') or {})[:110]
            if llm is not None and llm > 80:
                allslow.append((d, task, res[task]['resolved'], s['step_id'], round(llm), m.get('prompt_tokens'), m.get('completion_tokens'), call))
            if tool is not None and tool > 30:
                alltool.append((d, task, res[task]['resolved'], s['step_id'], round(tool), call, 'Timeout' in json.dumps(obs)))
            prev_end = oel if oel is not None else el
print('SLOW LLM CALLS (>80 s):', len(allslow))
for x in allslow: print('  ', *x)
print('SLOW TOOLS (>30 s):', len(alltool))
for x in alltool: print('  ', *x)
