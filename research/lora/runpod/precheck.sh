#!/bin/bash
# Pod-side adapter pre-check before the paid 71-task arm: install the scorer's wheelhouse into evalenv (same as run.py),
# serve the base model + adapter with vLLM, sample a real second-turn prompt 6 times, require clean stops.
# usage: bash precheck.sh <adapter_dir> <name>   -> prints PRECHECK_OK or PRECHECK_FAIL
set -u
AD=$1; NAME=$2; PY=/workspace/evalenv/bin/python
$PY - <<'PYEOF'
import glob, os, shutil, subprocess, sys
from pathlib import Path
WH = Path(glob.glob('/kaggle/input/**/gemma-4-developer-agent-wheelhouse', recursive=True)[0])
tmp = Path('/tmp/wheelhouse'); tmp.mkdir(parents=True, exist_ok=True)
for w in WH.glob('*.whl'):
    if 'cutlass' in w.name.lower(): continue
    t = tmp / (w.name.replace('cu128', '+cu128') if ('cu128' in w.name and '+' not in w.name) else w.name)
    if not t.exists():
        try: os.symlink(w, t)
        except OSError: shutil.copyfile(w, t)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', '--force-reinstall', *sorted(str(w) for w in tmp.glob('*.whl'))], check=True)
import vllm; print('wheels installed, vllm', vllm.__version__)
PYEOF
pkill -f "[a]pi_server" 2>/dev/null; sleep 3
(setsid nohup bash /workspace/vllm_start.sh $NAME=$AD > /workspace/vllm_precheck.log 2>&1 < /dev/null &)
for i in $(seq 1 60); do curl -s -m 3 http://127.0.0.1:8000/v1/models >/dev/null && break; sleep 15; done
curl -s -m 3 http://127.0.0.1:8000/v1/models >/dev/null || { echo "vLLM did not come up"; tail -20 /workspace/vllm_precheck.log; echo PRECHECK_FAIL; exit 1; }
cd /workspace && $PY rawprobe3.py $NAME 2>&1 | grep -v Warning | grep "with_thought\|no_thought" | tee /workspace/precheck_out.txt
pkill -f "[a]pi_server"; sleep 5
$PY - <<'PYEOF'
import re
txt = open('/workspace/precheck_out.txt').read()
line = [l for l in txt.splitlines() if l.startswith('with_thought')]
if not line: print('PRECHECK_FAIL (no output)'); raise SystemExit(1)
l = line[0]; stops = l.count("'stop/calls1/"); runaway = l.count('length'); empty = l.count('/thought18')
print(f'adapter second-turn samples: clean stops {stops}/6, runaway {runaway}, empty thoughts {empty}')
print('PRECHECK_OK' if stops >= 5 and runaway == 0 and empty <= 1 else 'PRECHECK_FAIL')
PYEOF
