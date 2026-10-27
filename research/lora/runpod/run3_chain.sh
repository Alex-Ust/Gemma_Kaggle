#!/bin/bash
# Adapter v3 cycle on ONE fresh RunPod pod (RTX PRO 6000 96 GB). Run from the Mac: bash research/lora/runpod/run3_chain.sh <ip> <port>
# Before: pod created (scripts/runpod_lora.py create --gpu "NVIDIA RTX PRO 6000 Blackwell Workstation Edition" --disk 200 --dc EUR-IS-2),
#         `python3 scripts/runpod_lora.py upload <pod>` (research/lora/kernel + data). The USER copies the Kaggle token at any time
#         (! scp -i runpod/id_ed25519 -P <port> kaggle/access_token root@<ip>:/workspace/kaggle_token); the eval bootstrap starts when it appears.
# Phases: 1 training bootstrap (model download + train.py, OUT=/workspace/adapter)  2 eval bootstrap in parallel (CPU/network only)
#         3 wait for training, fetch adapter -> research/lora/adapters/v3/adapter  4 LoRA arm on sound-71, concurrency 6  5 fetch results
set -u
cd /Users/alex_ust/Desktop/Gemma_kaggle
IP=$1; PORT=$2; TAG=${3:-v3}
OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=30 -i runpod/id_ed25519"
A="ssh $OPTS -p $PORT root@$IP"
RUNDIR=runs/v21-lora-$TAG-pod
scp $OPTS -P $PORT research/lora/runpod/eval_bootstrap.sh runs/v21-lora-v3-pod/kernel/run.py root@$IP:/workspace/ || exit 1
for i in 1 2 3 4 5; do $A 'cp /workspace/run.py /workspace/run_lora.py; if [ ! -f /workspace/bootstrap.log ]; then cd /workspace/lora && (setsid nohup bash bootstrap.sh > /workspace/bootstrap.log 2>&1 < /dev/null &); echo "training bootstrap started $(date -u +%H:%M)"; else echo "bootstrap already running"; fi' && break; echo "ssh attempt $i failed"; sleep 15; done
EVALB=0
start_eval_bootstrap() {
  $A 'export KAGGLE_API_TOKEN=/workspace/kaggle_token; if [ -f /workspace/eval_bootstrap.log ]; then echo "eval bootstrap already running"; exit 0; fi; (setsid nohup bash -c "bash /workspace/eval_bootstrap.sh; /workspace/evalenv/bin/pip install -q torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0; /workspace/evalenv/bin/pip install -q litellm google-adk==1.36.1 pytest pytest-timeout==2.1.0 typer pdm-backend setuptools wheel poetry-core hatchling flit-core editables; /workspace/evalenv/bin/pip install -q -U mcp; /workspace/evalenv/bin/pip install -q docker accelerate pandas; echo EVAL_ENV_DONE; rm -f /workspace/kaggle_token" > /workspace/eval_bootstrap.log 2>&1 < /dev/null &); echo "eval bootstrap started $(date -u +%H:%M)"'
  EVALB=1
}
while true; do
  out=$($A 'tail -c 300 /workspace/bootstrap.log | tr "\n" " " | cut -c1-120; grep -E "^\[" /workspace/train.log 2>/dev/null | tail -1 | cut -c1-150; grep -c OOM /workspace/train.log 2>/dev/null; tail -1 /workspace/eval_bootstrap.log 2>/dev/null | cut -c1-80; pgrep -f "[p]ython -u train.py" >/dev/null && echo ALIVE || echo NOTRAIN; nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader' 2>&1 | tr '\n' ' ')
  echo "$(date -u +%H:%M) TRAIN $out"
  case "$out" in *"] done"*) break;; esac
  if [ $EVALB = 0 ] && $A 'test -f /workspace/kaggle_token' 2>/dev/null; then start_eval_bootstrap; fi
  sleep 300
done
if ! $A 'test -f /workspace/adapter/adapter_model.safetensors'; then echo "NO ADAPTER — training failed, see /workspace/train.log"; exit 1; fi
mkdir -p research/lora/adapters/$TAG && scp $OPTS -r -P $PORT root@$IP:/workspace/adapter research/lora/adapters/$TAG/adapter && echo "adapter fetched: $(ls -la research/lora/adapters/$TAG/adapter | tail -2)"
while [ $EVALB = 0 ]; do echo "$(date -u +%H:%M) waiting for /workspace/kaggle_token (user: ! scp -i runpod/id_ed25519 -P $PORT kaggle/access_token root@$IP:/workspace/kaggle_token)"; if $A 'test -f /workspace/kaggle_token'; then start_eval_bootstrap; fi; sleep 300; done
while ! $A 'grep -q EVAL_ENV_DONE /workspace/eval_bootstrap.log 2>/dev/null'; do echo "$(date -u +%H:%M) eval env: $($A 'tail -1 /workspace/eval_bootstrap.log 2>/dev/null | cut -c1-80')"; sleep 180; done
scp $OPTS -P $PORT research/lora/runpod/precheck.sh research/lora/runpod/vllm_start.sh research/lora/runpod/probe/rawprobe3.py research/lora/runpod/probe/probe2_msgs.json research/lora/tools.json root@$IP:/workspace/
echo "$(date -u +%H:%M) adapter pre-check (wheelhouse install, vLLM, 6 samples on a second-turn prompt)"
$A "bash /workspace/precheck.sh /workspace/adapter $TAG" 2>&1 | tail -6 | tee $RUNDIR/precheck.txt
grep -q PRECHECK_OK $RUNDIR/precheck.txt || { echo "=== PRECHECK FAILED: not starting the 71-task arm (pod still running, decide manually)"; exit 2; }
$A 'D=/kaggle/input/datasets/alexust/gemma-lora-adapters; mkdir -p $D; cp /workspace/adapter/adapter_config.json $D/v3.adapter_config.json; cp /workspace/adapter/adapter_model.safetensors $D/v3.adapter_model.safetensors; rm -rf /kaggle/working/*; mkdir -p /kaggle/working; cd /kaggle/working && (setsid nohup /workspace/evalenv/bin/python /workspace/run_lora.py > /workspace/run_lora.log 2>&1 < /dev/null &); echo "LoRA arm started $(date -u +%H:%M)"'
mkdir -p $RUNDIR/results
while true; do
  out=$($A 'grep -E "^\[" /workspace/run_lora.log | tail -1 | cut -c1-120; f=/kaggle/working/results/task_results.jsonl; echo "done $(wc -l < $f 2>/dev/null || echo 0) resolved $(grep -c "\"resolved\": true" $f 2>/dev/null || echo 0)"; pgrep -f "[r]un_lora.py" >/dev/null && echo ALIVE || echo DEAD' 2>&1 | tr '\n' ' ')
  echo "$(date -u +%H:%M) EVAL $out"
  scp $OPTS -q -P $PORT root@$IP:/kaggle/working/results/task_results.jsonl $RUNDIR/results/task_results.jsonl 2>/dev/null
  case "$out" in *DONE*|*DEAD*) break;; esac
  sleep 600
done
scp $OPTS -q -r -P $PORT root@$IP:/kaggle/working/results/traces $RUNDIR/results/ && echo "traces fetched"
echo "=== $TAG chain finished; delete the pod: python3 scripts/runpod_lora.py delete <pod>"
